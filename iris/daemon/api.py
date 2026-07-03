"""DaemonAPI — Unix socket server for the iris always-on daemon (ADR-0006).

Protocol: line-delimited JSON.  Every command receives an ack response.
Clients connect, receive events, and send commands on the same connection.

Socket: ~/.local/run/iris/daemon.sock (mode 0600); override with $IRIS_DAEMON_SOCK.

Event types broadcast to all connected clients:
  incoming_call, screen_intro, call_connected, call_ended, posture, take_message_done
  brain_turn_started, brain_chunk, brain_reply
  call_card_started, call_card_disclosure_needed, call_card_fact, call_card_action_item,
  call_card_ended, call_card_enriched

Commands accepted from clients:
  choose              — operator selects a call-handling action
  dnd                 — set/clear/timed DND
  status              — request current state snapshot
  turn                — dispatch text to Brain; returns ack when queued
  stream_turn         — same as turn; ack key is 'stream_turn'
  call_context        — return current contact_id, contact_name, in_call
  confirm_fact        — operator confirms/edits a captured fact (requires call_card_host)
  confirm_action_item — operator confirms/edits an action item (requires call_card_host)
  disclosure_ack      — operator acknowledged AI disclosure (requires call_card_host)
  get_call_card       — return current call card snapshot (requires call_card_host)
"""
from __future__ import annotations

import json
import logging
import os
import socketserver
import stat
import threading
import time
from pathlib import Path

from ._socket_path import daemon_socket_path
from .brain_host import BrainHost
from .posture import PostureManager

_log = logging.getLogger(__name__)


def _format_caller_number(number: str) -> str:
    """Format E.164 number for human display; return as-is if not parseable."""
    n = number.lstrip("+")
    if len(n) == 11 and n.startswith("1"):
        return f"+1 {n[1:4]}-{n[4:7]}-{n[7:]}"
    return number


class _ClientWriter:
    """Wraps a client socket file for thread-safe line-JSON writes."""

    def __init__(self, wfile) -> None:
        self._wfile = wfile
        self._lock = threading.Lock()
        self.closed = False

    def write(self, obj: dict) -> bool:
        """Serialize obj as JSON line.  Returns False if the client disconnected."""
        line = json.dumps(obj, separators=(",", ":")) + "\n"
        with self._lock:
            if self.closed:
                return False
            try:
                self._wfile.write(line.encode())
                self._wfile.flush()
                return True
            except OSError:
                self.closed = True
                return False


class _RequestHandler(socketserver.StreamRequestHandler):
    """Handles one connected client: reads commands, writes acks + events."""

    def setup(self) -> None:
        super().setup()
        self._writer = _ClientWriter(self.wfile)
        self.server.api._register(self._writer)

    def handle(self) -> None:
        api: DaemonAPI = self.server.api
        for raw in self.rfile:
            raw = raw.strip()
            if not raw:
                continue
            try:
                cmd = json.loads(raw)
            except json.JSONDecodeError:
                self._writer.write({"ack": "error", "ok": False, "error": "Invalid JSON"})
                continue
            api._dispatch(cmd, self._writer)

    def finish(self) -> None:
        self._writer.closed = True
        self.server.api._unregister(self._writer)
        super().finish()


class DaemonAPI:
    """Unix socket server that connects clients to the daemon components.

    Usage::
        api = DaemonAPI(posture=pm, engine=engine)
        api.start()          # non-blocking; server runs in daemon thread
        api.broadcast(event) # push event to all connected clients
        api.stop()
    """

    def __init__(
        self,
        *,
        posture: PostureManager,
        engine: object,                         # HandlingEngine
        socket_path: Path | None = None,
        brain_host: BrainHost | None = None,
        call_card_host: object | None = None,   # CallCardHost
    ) -> None:
        self._posture = posture
        self._engine = engine
        self._brain_host = brain_host
        self._call_card_host = call_card_host
        self._socket_path = socket_path or daemon_socket_path()
        self._clients: list[_ClientWriter] = []
        self._clients_lock = threading.Lock()
        self._server: socketserver.ThreadingUnixStreamServer | None = None
        self._thread: threading.Thread | None = None

        posture.subscribe(self._on_posture_changed)

    # --- server lifecycle ---

    def start(self) -> None:
        """Start the server in a daemon background thread."""
        path = self._socket_path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise OSError(
                f"Cannot create socket at {path}\n"
                "Ensure XDG_RUNTIME_DIR is set, or set IRIS_DAEMON_SOCK to an alternate path."
            ) from exc

        if path.exists():
            path.unlink()

        server = socketserver.ThreadingUnixStreamServer(str(path), _RequestHandler)
        server.api = self  # type: ignore[attr-defined]
        server.daemon_threads = True

        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # mode 0600

        self._server = server
        self._thread = threading.Thread(
            target=server.serve_forever, name="daemon-api", daemon=True
        )
        self._thread.start()
        _log.info("DaemonAPI listening on %s", path)

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server = None
        if self._socket_path.exists():
            self._socket_path.unlink(missing_ok=True)

    # --- client registry ---

    def _register(self, writer: _ClientWriter) -> None:
        with self._clients_lock:
            self._clients.append(writer)
        _log.debug("DaemonAPI: client connected (%d total)", len(self._clients))

    def _unregister(self, writer: _ClientWriter) -> None:
        with self._clients_lock:
            self._clients = [c for c in self._clients if c is not writer]
        _log.debug("DaemonAPI: client disconnected (%d remaining)", len(self._clients))

    def broadcast(self, event: dict) -> None:
        """Push event to all connected clients; prune dead connections."""
        dead: list[_ClientWriter] = []
        with self._clients_lock:
            snapshot = list(self._clients)
        for writer in snapshot:
            if not writer.write(event):
                dead.append(writer)
        if dead:
            with self._clients_lock:
                self._clients = [c for c in self._clients if c not in dead]

    def client_count(self) -> int:
        with self._clients_lock:
            return len(self._clients)

    # --- command dispatch ---

    def _dispatch(self, cmd: dict, writer: _ClientWriter) -> None:
        kind = cmd.get("cmd", "")
        if kind == "choose":
            self._handle_choose(cmd, writer)
        elif kind == "dnd":
            self._handle_dnd(cmd, writer)
        elif kind == "status":
            self._handle_status(cmd, writer)
        elif kind == "turn":
            self._handle_turn(cmd, writer)
        elif kind == "stream_turn":
            self._handle_stream_turn(cmd, writer)
        elif kind == "call_context":
            self._handle_call_context(cmd, writer)
        elif kind == "confirm_fact":
            self._handle_confirm_fact(cmd, writer)
        elif kind == "confirm_action_item":
            self._handle_confirm_action_item(cmd, writer)
        elif kind == "disclosure_ack":
            self._handle_disclosure_ack(cmd, writer)
        elif kind == "get_call_card":
            self._handle_get_call_card(cmd, writer)
        else:
            writer.write({"ack": kind or "unknown", "ok": False,
                          "error": f"Unknown command: {kind!r}"})

    def _handle_choose(self, cmd: dict, writer: _ClientWriter) -> None:
        call_id = cmd.get("call_id", "")
        action_id = cmd.get("action_id", "")
        if not call_id or not action_id:
            writer.write({"ack": "choose", "ok": False,
                          "error": "Missing call_id or action_id"})
            return
        try:
            self._engine.on_choose(call_id, action_id)  # type: ignore[attr-defined]
            writer.write({"ack": "choose", "ok": True})
        except Exception as exc:
            _log.exception("choose handler error")
            writer.write({"ack": "choose", "ok": False, "error": str(exc)})

    def _handle_dnd(self, cmd: dict, writer: _ClientWriter) -> None:
        # Write ack BEFORE mutating posture so the ack arrives before any
        # posture broadcast event on the same connection.
        action = cmd.get("action", "")
        if action == "on":
            writer.write({"ack": "dnd", "ok": True,
                          "posture": {"dnd": True, "expires_in_s": None}})
            self._posture.set_dnd("manual")
        elif action == "off":
            writer.write({"ack": "dnd", "ok": True,
                          "posture": {"dnd": False, "expires_in_s": None}})
            self._posture.clear_dnd()
        elif action == "until":
            until = cmd.get("until")
            if not isinstance(until, (int, float)):
                writer.write({"ack": "dnd", "ok": False,
                              "error": "'until' must be a Unix timestamp (number)"})
                return
            expires_in = max(0.0, float(until) - time.time())
            writer.write({"ack": "dnd", "ok": True,
                          "posture": {"dnd": True, "expires_in_s": expires_in}})
            self._posture.set_dnd("manual", expires=float(until))
        else:
            writer.write({"ack": "dnd", "ok": False,
                          "error": f"Unknown DND action: {action!r}. Use on, off, or until."})

    def _handle_status(self, cmd: dict, writer: _ClientWriter) -> None:
        eff = self._posture.effective()
        try:
            active_id = self._engine._attention.active_call_id  # type: ignore[attr-defined]
            call_state = "active" if active_id else "idle"
        except AttributeError:
            call_state = "unknown"
        writer.write({
            "ack": "status",
            "ok": True,
            "state": {
                "call":    call_state,
                "posture": {"dnd": eff["dnd"], "busy": eff["busy"]},
                "clients": self.client_count(),
                "pid":     os.getpid(),
            },
        })

    def _handle_turn(self, cmd: dict, writer: _ClientWriter) -> None:
        if self._brain_host is None:
            writer.write({"ack": "turn", "ok": False, "error": "no brain"})
            return
        text = cmd.get("text", "")
        speaker = cmd.get("speaker", "")
        result = self._brain_host.async_turn(text, speaker)
        writer.write(result)

    def _handle_stream_turn(self, cmd: dict, writer: _ClientWriter) -> None:
        if self._brain_host is None:
            writer.write({"ack": "stream_turn", "ok": False, "error": "no brain"})
            return
        text = cmd.get("text", "")
        speaker = cmd.get("speaker", "")
        result = self._brain_host.async_turn(text, speaker)
        writer.write({**result, "ack": "stream_turn"})

    def _handle_call_context(self, cmd: dict, writer: _ClientWriter) -> None:
        if self._brain_host is None:
            writer.write({"ack": "call_context", "ok": False, "error": "no brain"})
            return
        ctx = self._brain_host.call_context_snapshot()
        writer.write({"ack": "call_context", "ok": True, **ctx})

    # --- Call Card command handlers ---

    def _handle_confirm_fact(self, cmd: dict, writer: _ClientWriter) -> None:
        if self._call_card_host is None:
            writer.write({"ack": "confirm_fact", "ok": False, "error": "call_card not configured"})
            return
        session_id = cmd.get("session_id", "")
        fact_id = cmd.get("fact_id", "")
        if not session_id or not fact_id:
            writer.write({"ack": "confirm_fact", "ok": False, "error": "Missing session_id or fact_id"})
            return
        confirmed = bool(cmd.get("confirmed", True))
        normalized_value = cmd.get("normalized_value")
        self._call_card_host.confirm_fact(session_id, fact_id, confirmed, normalized_value)  # type: ignore[attr-defined]
        writer.write({"ack": "confirm_fact", "ok": True})

    def _handle_confirm_action_item(self, cmd: dict, writer: _ClientWriter) -> None:
        if self._call_card_host is None:
            writer.write({"ack": "confirm_action_item", "ok": False, "error": "call_card not configured"})
            return
        session_id = cmd.get("session_id", "")
        item_id = cmd.get("item_id", "")
        if not session_id or not item_id:
            writer.write({"ack": "confirm_action_item", "ok": False, "error": "Missing session_id or item_id"})
            return
        confirmed = bool(cmd.get("confirmed", True))
        description = cmd.get("description")
        due_date = cmd.get("due_date")
        self._call_card_host.confirm_action_item(session_id, item_id, confirmed, description, due_date)  # type: ignore[attr-defined]
        writer.write({"ack": "confirm_action_item", "ok": True})

    def _handle_disclosure_ack(self, cmd: dict, writer: _ClientWriter) -> None:
        if self._call_card_host is None:
            writer.write({"ack": "disclosure_ack", "ok": False, "error": "call_card not configured"})
            return
        session_id = cmd.get("session_id", "")
        if not session_id:
            writer.write({"ack": "disclosure_ack", "ok": False, "error": "Missing session_id"})
            return
        self._call_card_host.disclosure_ack(session_id)  # type: ignore[attr-defined]
        writer.write({"ack": "disclosure_ack", "ok": True})

    def _handle_get_call_card(self, cmd: dict, writer: _ClientWriter) -> None:
        if self._call_card_host is None:
            writer.write({"ack": "get_call_card", "ok": False, "error": "call_card not configured"})
            return
        session_id = cmd.get("session_id")
        result = self._call_card_host.get_call_card(session_id=session_id)  # type: ignore[attr-defined]
        writer.write({"ack": "get_call_card", "ok": True, "call_card": result})

    # --- PostureManager subscriber ---

    def _on_posture_changed(self, ev: dict) -> None:
        """Forward posture_changed → posture event to all clients (<200ms)."""
        self.broadcast({
            "event": "posture",
            "dnd":   ev["dnd"],
            "busy":  ev["busy"],
        })
