"""Textual operator console for Iris — the local 'admin app'.

Live transcription, per-turn tier + latency, a hard interrupt (barge-in), mute,
and a command dump — over the local voice loop. Ways to talk:
  - push-to-talk: [space] to start/stop a turn;
  - listen [L]: continuous — just talk, Iris acts only when addressed ("Iris, …");
  - respondent [f]: also hear the far-end party (the other side of a call);
  - approve [a]: allow the respondent's "Iris, …" commands to act (default OFF —
    their requests are shown but ignored until you approve).
  - list panel [L] (capital): toggle the right-side live list panel.
  - ARM TRUST button: shown during calls with trust_tier=full contacts; grants full
    access; replaced by amber TRUST ARMED badge after arming.

Drives the UI-agnostic Conductor; the blocking pipeline runs in a Textual thread-
worker so the UI stays responsive (and the interrupt key always lands).

    python -m iris.console      # needs scripts/setup_whisper.sh + a llama-server

Every line shown is also appended (plain text) to a session logfile —
~/.local/state/iris/console.log by default, or $IRIS_LOG_FILE — so a session can
be read back or shared without copying out of the TUI.

Keys: [space] talk · [l] hear you · [L] list panel · [f] hear them · [a] approve them · [i] interrupt · [m] mute · [c] commands · [q] quit
"""
from __future__ import annotations

import os
import queue
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Button, Footer, Header, RichLog, Static

from .. import settings
from ..addressing import address
from ..message_store import MessageStore, VoiceMessage
from ..prefs import PreferencesStore
from .contacts import ContactsScreen
from .list_view import PostCallListView
from ..audio.endpoint import default_endpoint
from ..audio.streaming import StreamingTranscriber
from ..audio.stt import default_stt
from ..audio.tts import default_tts
from ..brain import Brain
from ..call_control import TincanCallControl
from ..fillers import filler_picker
from ..proactive_delivery import ProactiveDelivery, SilenceTracker
from ..proactive_store import ProactiveStore
from ..roster import RosterStore
from ..trust import TrustMode
from .conductor import Conductor, State

# ti-veyx: WebRTC AEC bring-up / SCO bridge for the seamless phone-call ride-along.
_AEC_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "aec_audio.sh"

# ti-rqhn: consent gate. Iris ALWAYS announces itself before transcribing the far
# party on a call — assume listening = recording (WA is all-party consent), never
# silently capture. The phrase is configurable via IRIS_CALL_ANNOUNCE; we always
# announce regardless.
_DEFAULT_ANNOUNCE = (
    "Hi, this is Iris, an A.I. assistant on this call. "
    "I'll be listening and may respond."
)

# Addressed stop words -> a hard interrupt (cut her off now, no spoken reply).
_STOP = re.compile(
    r"^\s*(?:stop|stand[ -]?down|cancel|never ?mind|quiet|enough|shush|hush)\b",
    re.IGNORECASE,
)

# After a bare wake-word ("Hey Iris"), accept the next utterance without a wake-word
# for this many seconds.
_FOLLOW_UP_S = 8.0

# Trust-escalation phrase pattern — kept as a tested constant so regressions are caught.
# The spoken-grant path that acted on this was removed (ti-qt1i.1.1); trust elevation
# now requires a physical operator action (ARM TRUST button or [g] key).
_GRANT = re.compile(
    r"^\s*(?:grant|give|allow|trust)(?:\s+(?:them|him|her|it))?\s+full\s+access\b",
    re.IGNORECASE,
)

# Strip Rich markup ([red], [/], [bold cyan]…) so the session logfile is plain text.
_MARKUP = re.compile(r"\[/?[^\]]*\]")


def _open_log():
    """Open the plain-text session logfile (fresh per run). $IRIS_LOG_FILE overrides
    the default ~/.local/state/iris/console.log. Returns (file, path) or (None, None)."""
    path = settings.get("IRIS_LOG_FILE")
    if not path:
        base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
        try:
            os.makedirs(os.path.join(base, "iris"), exist_ok=True)
        except OSError:
            return None, None
        path = os.path.join(base, "iris", "console.log")
    try:
        return open(path, "w", buffering=1), path
    except OSError:
        return None, None


class ActiveCallCard(Widget, can_focus=False):
    """Card shown during active calls with trust_tier=full contacts.

    Pre-arm: shows ARM TRUST button (Tab-reachable, Enter/Space activates).
    Post-arm: replaces button with amber TRUST ARMED badge.
    Visibility is controlled by show_card() / hide_card() on the IrisConsole.
    """

    DEFAULT_CSS = """
    ActiveCallCard {
        display: none;
        height: 3;
        background: #1a1a3a;
        border: round #4040aa;
        padding: 0 2;
        layout: horizontal;
        align: left middle;
    }
    ActiveCallCard.visible {
        display: block;
    }
    ActiveCallCard #arm-trust-btn {
        min-width: 14;
        margin: 0 1;
    }
    ActiveCallCard #trust-armed-badge {
        color: yellow;
        text-style: bold;
        margin: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Button("ARM TRUST", id="arm-trust-btn", variant="default")
        yield Static("", id="trust-armed-badge")

    def show_card(self, contact_name: str) -> None:
        """Enter pre-arm state: show button, clear badge."""
        btn = self.query_one("#arm-trust-btn", Button)
        btn.tooltip = f"Arm trust for {contact_name}"
        btn.display = True
        self.query_one("#trust-armed-badge", Static).update("")
        self.add_class("visible")

    def hide_card(self) -> None:
        """Hide the card entirely (call ended)."""
        self.remove_class("visible")

    def mark_armed(self) -> None:
        """Switch to post-arm state: hide button, show amber badge."""
        self.query_one("#arm-trust-btn", Button).display = False
        self.query_one("#trust-armed-badge", Static).update(
            "[b yellow]■ TRUST ARMED[/]"
        )

    def mark_unarmed(self) -> None:
        """Revert to pre-arm state (trust was revoked)."""
        btn = self.query_one("#arm-trust-btn", Button)
        btn.display = True
        self.query_one("#trust-armed-badge", Static).update("")


class ListPanel(Static):
    """Right-side panel showing the active call list with live lookup states.

    Design spec (ti-ccc.16.3):
      bg #1c2333 · text #cce0ff · fixed 30 cols wide · [L] toggles visibility.
    Items use Unicode state indicators:
      ○ normal   ⏳ pending lookup   ✓ enriched (lookup done)   ⚠ failed   ☑ checked
    """

    DEFAULT_CSS = """
    ListPanel {
        width: 30;
        height: 1fr;
        background: #1c2333;
        color: #cce0ff;
        border: round #3a5080;
        padding: 0 1;
        display: none;
    }
    ListPanel.visible-panel {
        display: block;
    }
    """

    def __init__(self) -> None:
        super().__init__("", id="list-panel")
        self._items: list[tuple[str, str, str]] = []  # (text, state, lookup_text)
        self._session: str = ""

    def update_items(self, items: list) -> None:
        """Refresh displayed items from a list of ListItem dataclass instances."""
        self._items = []
        for it in items:
            state = it.lookup_status  # "none", "pending", "done", "failed"
            self._items.append((it.text, state, ""))
        self._render()

    def on_lookup_done(self, item_id: int, result: str) -> None:
        self._render()

    def on_lookup_failed(self, item_id: int, msg: str) -> None:
        self._render()

    def add_item(self, text: str) -> None:
        self._items.append((text, "none", ""))
        self._render()

    def _icon(self, state: str, checked: bool) -> str:
        if checked:
            return "☑"
        return {"none": "○", "pending": "⏳", "done": "✓", "failed": "⚠"}.get(state, "○")

    def _render(self) -> None:
        if not self._items:
            lines = ["[dim]— empty —[/dim]"]
        else:
            lines = []
            for i, (text, state, lookup_text) in enumerate(self._items, 1):
                icon = self._icon(state, False)
                line = f"{i}. {icon} {text}"
                if state == "done" and lookup_text:
                    line += f"\n   [dim]{lookup_text[:40]}[/dim]"
                elif state == "failed":
                    line += " [red]⚠[/red]"
                lines.append(line)
        self.update("\n".join(lines))

    def toggle_visible(self) -> bool:
        """Toggle panel visibility. Returns new visible state."""
        if "visible-panel" in self.classes:
            self.remove_class("visible-panel")
            return False
        self.add_class("visible-panel")
        return True

    def on_key(self, event) -> None:
        if event.key == "v":
            self.app.action_open_list_view()
        elif event.key == "escape":
            self.toggle_visible()
            self.app.query_one("#log", RichLog).focus()


class IrisConsole(App):
    TITLE = "Iris console"

    CSS = """
    #main-row { height: 1fr; }
    #log { height: 1fr; border: round $accent; padding: 0 1; }
    #status { height: 1; background: $boost; color: $text; padding: 0 1; }
    """

    BINDINGS = [
        Binding("space", "talk", "talk/stop", priority=True),
        Binding("l", "listen", "hear you"),
        Binding("L", "list_panel", "list"),
        Binding("f", "far", "hear them"),
        Binding("g", "grant", "grant", priority=True),
        Binding("a", "approve", "approve"),
        Binding("i", "interrupt", "interrupt", priority=True),
        Binding("m", "mute", "mute"),
        Binding("n", "notification", "next notif", show=False),
        Binding("c", "commands", "commands"),
        Binding("K", "contacts", "contacts"),
        Binding("q", "quit", "quit", priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.events: queue.Queue = queue.Queue()
        self.stt = default_stt()
        self.tts = default_tts()
        # Call control: subscribes to tincan's im.tincan.Calls signals and places
        # outgoing dials. Emitting into self.events surfaces incoming_call /
        # call_connected / call_ended in _drain (already handled there); passing it
        # to the Brain registers the operator-only dial skills ("Iris, call <name>").
        # auto_answer=False = supervised: the operator answers; Iris just picks up
        # the SCO audio endpoint on CallConnected.
        self.ctrl = TincanCallControl(auto_answer=False, emit=self.events.put)
        self.brain = Brain(ctrl=self.ctrl)
        self.mic = default_endpoint()
        self._local_mic = self.mic  # ti-veyx: endpoint to restore when a call ends
        self.conductor = Conductor(
            self.stt, self.brain, self.tts, self.mic,
            emit=self.events.put, pick=filler_picker(),
        )
        self._note = ""
        self._stream: StreamingTranscriber | None = None      # you (operator mic)
        self._far_stream: StreamingTranscriber | None = None  # the respondent
        self._log: RichLog | None = None                      # cached in on_mount
        self._logf, self._logpath = _open_log()               # plain-text session log
        self._proactive_badge: str = ""
        self._proactive_queue_count: int = 0
        self._current_notification_id: int | None = None
        self._silence_tracker = SilenceTracker()
        self._proactive_store = ProactiveStore()
        self._prefs = PreferencesStore()
        self._call_contact_name: str = ""
        self._call_contact_number: str = ""
        self._call_trust_eligible: bool = False
        self._in_call: bool = False
        self._pre_call_muted: bool = False
        self._far_announced: bool = False  # ti-rqhn: announced consent to the far party this call?
        self._follow_up_until: float = 0.0
        self._messages = MessageStore()
        self._roster = RosterStore()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield ActiveCallCard(id="active-call-card")
        with Horizontal(id="main-row"):
            yield RichLog(id="log", markup=True, wrap=True)
            yield ListPanel()
        yield Static(id="status")
        yield Footer()

    def _w(self, markup: str) -> None:
        """Write a line to the on-screen log AND (plain) to the session logfile."""
        if self._log is not None:
            self._log.write(markup)
        if self._logf is not None:
            self._logf.write(f"{datetime.now():%H:%M:%S} {_MARKUP.sub('', markup)}\n")

    def on_mount(self) -> None:
        self._log = self.query_one("#log", RichLog)
        self._log.can_focus = False  # so [space] is the talk key, not log-scroll
        self._w(f"[dim]STT: {self.stt.name} · TTS: {self.tts.name} · (I'm an AI.)[/]")
        if self._logpath:
            self._w(f"[dim]session log → {self._logpath}[/]")
        if not self.stt.available():
            self._w("[red]STT not set up — run:  bash scripts/setup_whisper.sh[/]")
        self.set_interval(0.05, self._drain)
        self.ctrl.start()  # listen for tincan call signals (daemon thread; safe if bus down)
        self._ensure_aec_up()  # ti-veyx: load the WebRTC AEC once (idempotent) for feedback-free call audio

        def _current_mode() -> str:
            if self._far_stream is not None:
                return "far"
            if self._stream is not None:
                return "listen"
            return "idle"

        self._proactive_delivery = ProactiveDelivery(
            store=self._proactive_store,
            cfg=self.brain.cfg,
            mode_fn=_current_mode,
            silence_tracker=self._silence_tracker,
            tts_fn=lambda msg: self.run_worker(
                lambda m=msg: self.mic.start_playback(self.conductor.tts.synth(m)),
                thread=True,
            ),
            emit=self.events.put,
        )
        self.set_interval(0.5, self._proactive_delivery.tick)
        self._refresh_status()

    def _drain(self) -> None:
        """Pump conductor + stream events (posted from worker threads) into the UI."""
        try:
            while True:
                ev = self.events.get_nowait()
                kind = ev[0]
                if kind == "transcript":
                    text, ms = ev[1], ev[2]
                    self._w(
                        f"[bold]you[/]  › {text or '(heard nothing)'}"
                        f"  [dim]⟮stt {ms:.0f}ms⟯[/]"
                    )
                elif kind == "reply":
                    self._w(f"[bold cyan]iris[/] › {ev[1]}")
                    self._w(f"        [dim]⟮{ev[2]} · {ev[3]}⟯[/]")
                elif kind == "heard":
                    self._on_heard_main(ev[1], ev[2] if len(ev) > 2 else "")
                elif kind == "heard_far":
                    self._on_heard_far_main(ev[1], ev[2] if len(ev) > 2 else "")
                elif kind == "error":
                    self._w(f"[red]✗ {ev[1]}[/]")
                elif kind == "list":
                    self._on_list_event(ev)
                elif kind == "incoming_call":
                    caller_name = ev[1] if len(ev) > 1 else ""
                    caller_number = ev[2] if len(ev) > 2 else ""
                    self._call_contact_name = caller_name or caller_number or ""
                    self._call_contact_number = caller_number
                    key = (
                        f"contact:{caller_number}" if caller_number
                        else f"contact:{caller_name}"
                    )
                    self._call_trust_eligible = (
                        self._prefs.get(key, "trust_tier", "") == "full"
                    )
                elif kind == "call_connected":
                    self._in_call = True
                    # ti-gbz4.1: mute mic by default at call start (push-to-talk model)
                    self._pre_call_muted = self.conductor.muted
                    if not self.conductor.muted:
                        self.conductor.toggle_mute()
                    self._w("[yellow]call connected — mic muted (press [m] to unmute / push-to-talk)[/]")
                    # ti-gbz4.2: stop far-party transcription gate
                    if self._far_stream is not None:
                        self._far_stream.stop()
                        self._far_stream = None
                    if self._call_trust_eligible and self._call_contact_name:
                        self.query_one(ActiveCallCard).show_card(
                            self._call_contact_name
                        )
                    # ti-veyx: ride along on THIS console session — adopt the live
                    # SCO endpoint instead of relaunching with IRIS_AUDIO=tincan-sco.
                    self._attach_call_audio()
                    # ti-rqhn: re-announce every call — never assume prior consent.
                    self._far_announced = False
                    # ti-rqhn screening seam (D2, not built): when auto_answer
                    # screening lands, auto-announce here on pickup BEFORE enabling
                    # far-party transcription (the gate stays the same).
                elif kind in ("far_trust", "trust"):
                    card = self.query_one(ActiveCallCard)
                    if "visible" in card.classes:
                        if self.conductor.far_trust is TrustMode.BOTH:
                            card.mark_armed()
                        else:
                            card.mark_unarmed()
                    self._refresh_status()
                elif kind == "armed":
                    self._refresh_status()
                elif kind == "far_announced":
                    # ti-rqhn: open the gate ONLY if the announcement actually played
                    # (fail-closed). Record consent only for announcements that happened.
                    if len(ev) > 1 and ev[1]:
                        self._far_announced = True
                        self._log_consent(ev[2] if len(ev) > 2 else "")
                        self._start_far_stream()
                    else:
                        self._w("[red]announcement did not play — NOT listening (consent not established)[/]")
                elif kind == "call_ended":
                    self._in_call = False
                    self._call_trust_eligible = False
                    self._call_contact_name = ""
                    self._call_contact_number = ""
                    # ti-gbz4.1: restore pre-call mute state
                    if self.conductor.muted and not self._pre_call_muted:
                        self.conductor.toggle_mute()
                    self.query_one(ActiveCallCard).hide_card()
                    self._detach_call_audio()  # ti-veyx: restore local audio
                    self._far_announced = False  # ti-rqhn: reset consent gate for next call
                    session_id = ev[1] if len(ev) > 1 else ""
                    self._maybe_show_post_call_list(str(session_id))
                elif kind == "take_message_done":
                    caller_name = ev[1] if len(ev) > 1 else "the caller"
                    transcript = ev[2] if len(ev) > 2 else ""
                    contact_name = ev[3] if len(ev) > 3 else ""
                    caller_number = ev[4] if len(ev) > 4 else ""
                    msg = self._messages.add(
                        caller_name,
                        transcript,
                        caller_number=caller_number,
                        contact_name=contact_name,
                    )
                    self._w(
                        f"[b]📩 Message from {caller_name}[/]"
                        + (f" ({caller_number})" if caller_number else "")
                    )
                    self._w(f"   [dim]{transcript[:120]}{'…' if len(transcript) > 120 else ''}[/]")
                    self._w(f"   [dim]msg-id:{msg.id}  ·  say 'mark read {msg.id}' or 'call back {msg.id}'[/]")
                elif kind == "proactive_badge":
                    self._proactive_badge = ev[1][:40] if ev[1] else ""
                    self._proactive_queue_count = ev[2] if len(ev) > 2 else 0
                    self._refresh_status()
                    self._toggle_notification_binding()
                elif kind == "proactive_tts":
                    self._w(
                        f"[b yellow]🔔[/] {ev[1] if len(ev) > 1 else ''}  [dim](proactive)[/]"
                    )
                elif kind == "filler":
                    self._note = f"… {ev[1]}"
                    self._refresh_status()
                elif kind == "state":
                    if ev[1] is State.IDLE:
                        self._note = ""
                    self._refresh_status()
                elif kind == "mute":
                    self._refresh_status()
        except queue.Empty:
            pass

    # --- ti-veyx: seamless phone-call ride-along (adopt the live SCO endpoint) ---

    def _aec(self, action: str) -> bool:
        """Run ``scripts/aec_audio.sh <action>`` (up / bridge / unbridge).

        Best-effort: the AEC is opt-in (``IRIS_AEC``) and ``up`` deliberately exits
        non-zero when already loaded, so a failure here is never fatal — the call
        still works, just without echo cancellation. Returns True on rc==0.
        """
        if not _AEC_SCRIPT.exists():
            return False
        try:
            proc = subprocess.run(
                ["bash", str(_AEC_SCRIPT), action],
                capture_output=True, text=True, timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self._w(f"[dim]aec {action} failed: {exc}[/]")
            return False
        return proc.returncode == 0

    def _ensure_aec_up(self) -> None:
        """Load the WebRTC AEC once at startup when ``IRIS_AEC`` is set.

        Keeping it always-loaded (not per-call) is the ti-veyx design: the
        canceller is harmless when idle / on a headset and avoids a module load on
        every call. A second ``up`` just no-ops.
        """
        if settings.get_bool("IRIS_AEC"):
            self._aec("up")

    def _attach_call_audio(self) -> None:
        """On CallConnected, adopt the live SCO endpoint that TincanCallControl
        built so THIS console session rides the call — Iris's replies go to the
        call uplink (the far party hears her) and push-to-talk captures the
        echo-cancelled mic — without relaunching under ``IRIS_AUDIO=tincan-sco``.

        Bridging the SCO into the AEC also routes the far-party downlink to the
        operator's speakers feedback-free. Far-party *transcription* stays gated by
        ti-gbz4.2 (see ``action_far``) until the ti-rqhn consent gate lands.
        """
        ep = getattr(self.ctrl, "endpoint", None)
        if ep is None:  # SCO nodes not discoverable (no live call) — stay on local audio
            return
        self.mic = ep
        self.conductor.mic = ep
        if getattr(ep, "aec", False):
            self._aec("bridge")
        self._w("[dim]ride-along: on call audio — Iris speaks to the call[/]")

    def _detach_call_audio(self) -> None:
        """On CallEnded, drop the SCO bridge and restore the local audio endpoint."""
        if self.mic is self._local_mic:
            return  # never attached (e.g. no SCO nodes) — nothing to restore
        if getattr(self.mic, "aec", False):
            self._aec("unbridge")
        self.mic = self._local_mic
        self.conductor.mic = self._local_mic
        self._w("[dim]ride-along: call ended — restored local audio[/]")

    def _on_list_event(self, ev: tuple) -> None:
        """Handle list-related events from ListSkill background threads."""
        panel = self.query_one(ListPanel)
        log = self.query_one("#log", RichLog)
        kind = ev[1] if len(ev) > 1 else ""
        if kind == "lookup_done" and len(ev) >= 4:
            item_id, result = ev[2], ev[3]
            log.write(f"[dim cyan]⟨list: lookup done — {result[:60]}⟩[/]")
            panel.on_lookup_done(item_id, result)
        elif kind == "lookup_failed" and len(ev) >= 4:
            item_id, msg = ev[2], ev[3]
            log.write(f"[dim red]⟨list: lookup failed — {msg}⟩[/]")
            panel.on_lookup_failed(item_id, msg)

    def _maybe_show_post_call_list(self, session_id: str) -> None:
        """Auto-display PostCallListView when a call ends if an active list exists."""
        try:
            from ..list_store import CallListStore
            store = CallListStore()
            active = store.active_list(session_id)
            if active is not None and store.get_items(active.id):
                self.push_screen(PostCallListView(store, active))
        except Exception:  # noqa: BLE001
            pass

    def _dispatch(self, cmd: str, speaker: str = "") -> bool:
        """Run an addressed command if Iris is free. Returns True if dispatched."""
        if self.conductor.state is State.IDLE:
            self.run_worker(
                lambda c=cmd, s=speaker: self.conductor.respond_to(c, speaker=s),
                thread=True, exclusive=True,
            )
            return True
        return False

    def _on_heard_main(self, text: str, speaker: str = "") -> None:
        """A streamed utterance from YOU (main thread): act only if addressed."""
        self._silence_tracker.touch()
        cmd = address(text)
        if cmd is None:
            if time.monotonic() < self._follow_up_until:
                # Within the active-listening window opened by a bare wake-word:
                # treat this utterance as a command without requiring "Iris, …".
                self._follow_up_until = 0.0
                self._w(f"[bold]you[/] → iris: {text}")
                self._dispatch(text, speaker)
            else:
                self._w(f"[dim]· {text}[/]")  # overheard, not for Iris
            return
        self._w(f"[bold]you[/] → iris: {text}")
        if not cmd:
            # Bare wake-word ("Hey Iris"): speak an ack and open a follow-up window.
            self._follow_up_until = time.monotonic() + _FOLLOW_UP_S
            if self.conductor.state is State.IDLE:
                self.run_worker(
                    lambda: self.conductor.say("Yes?"), thread=True, exclusive=True,
                )
            else:
                self._w('[dim](yes? — say your request)[/]')
        elif _STOP.match(cmd):
            self.conductor.interrupt()  # cut her off now; no spoken reply
            self._w("[yellow](stopped)[/]")
            self._refresh_status()
        elif not self._dispatch(cmd, speaker):
            self._w("[dim](busy — one sec)[/]")

    def _on_heard_far_main(self, text: str, speaker: str = "") -> None:
        """A streamed utterance from the RESPONDENT: respond by default.

        Far-party commands always reach the brain, which gates *capability* by
        ``far_trust``: DEMO (the default) allows conversation only — Tier 0 +
        local knowledge, no skills, data, or cloud — while the operator grants
        FULL out-of-band via the [g] grant cycle, the ARM TRUST button, or the
        iris-arm CLI (the spoken-grant path was removed — ti-qt1i.1.1). The far
        party can never self-escalate (this path has no grant branch). See ADR-0002.
        """
        if self._in_call:
            return  # ti-gbz4.2: downlink suppressed during SCO/HFP calls
        cmd = address(text)
        if cmd is None:
            self._w(f"[dim]them: {text}[/]")  # respondent, not addressing Iris
            return
        self._w(f"[magenta]them[/] → iris: {text}")
        if not cmd:
            return
        if not self._dispatch(cmd, speaker):
            self._w("[dim](busy — one sec)[/]")

    def _refresh_status(self) -> None:
        import os as _os  # noqa: PLC0415
        c = self.conductor
        parts = [c.state.value.upper()]
        if c.muted:
            parts.append("[b]MUTED[/]")
        # Audio mode label (startup-time env var)
        if _os.environ.get("IRIS_VA_AEC"):
            parts.append("[dim]AEC[/]")
        elif _os.environ.get("IRIS_AEC"):
            parts.append("[dim]HEADSET[/]")
        else:
            parts.append("[dim]SPEAKERS[/]")
        if self._stream is not None:
            parts.append("[b]HEAR-YOU[/]")
        if self._far_stream is not None:
            parts.append("[b]HEAR-THEM[/]")
        # Trust state label
        trust = c.trust_state
        if trust is TrustMode.BOTH:
            parts.append("[b #79c0ff]LOCAL+FAR-REMOTE[/]")
        elif trust is TrustMode.LOCAL:
            parts.append("[b #56d364]LOCAL[/]")
        elif c._armed:
            parts.append("[dim white]ARMED[/]")
        else:
            parts.append("[yellow #d29922]UNARMED[/]")
        if self._proactive_badge:
            if self._proactive_queue_count > 1:
                parts.append(
                    f"[b yellow]🔔 {self._proactive_queue_count} pending  ·  press [n] to cycle[/]"
                )
            else:
                parts.append(f"[b yellow]🔔 {self._proactive_badge}[/]")
        if self._note:
            parts.append(self._note)
        self.query_one("#status", Static).update(" " + "  ·  ".join(parts))

    # --- talk / listen ---------------------------------------------------------
    def action_talk(self) -> None:
        c = self.conductor
        if c.state is State.IDLE:
            c.start_recording()
            self._refresh_status()
        elif c.state is State.RECORDING:
            self.run_worker(c.stop_and_respond, thread=True, exclusive=True)

    def action_listen(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream = None
            self._w("[yellow]no longer hearing you[/]")
            self._refresh_status()
            return
        stream = StreamingTranscriber(
            self._on_heard,
            source=self.mic.capture_target,  # None = default mic; AEC source when IRIS_VA_AEC=1
            label="operator",
        )
        if not stream.available():
            self._w("[red]STT not set up — run:  bash scripts/setup_whisper.sh[/]")
            return
        self._stream = stream
        stream.start()
        self._w('[green]hearing you — just talk; say "Iris, …" to address her[/]')
        self._refresh_status()

    def action_far(self) -> None:
        # Toggle OFF (either mode).
        if self._far_stream is not None:
            self._far_stream.stop()
            self._far_stream = None
            self.conductor.reset_far_trust()  # hangup/disconnect resets to DEMO
            self._w("[yellow]no longer hearing the respondent[/]")
            self._refresh_status()
            return
        # ti-rqhn consent gate: on a call, Iris must ANNOUNCE itself before it may
        # transcribe the far party (WA all-party consent — never silently capture).
        # The announcement auto-fires on the first enable; the gate opens only after
        # it has played (see _announce_then_hear_far -> the "far_announced" event).
        if self._in_call and not self._far_announced:
            self._announce_then_hear_far()
            return
        self._start_far_stream()

    def _start_far_stream(self) -> None:
        """Open far-party transcription on the current endpoint's far source."""
        src = self.mic.far_source or "iris_ear.monitor"
        stream = StreamingTranscriber(
            self._on_heard_far, source=src, backend=self.mic.far_backend, label="far"
        )
        if not stream.available():
            self._w("[red]STT not set up — run:  bash scripts/setup_whisper.sh[/]")
            return
        self._far_stream = stream
        stream.start()
        self._w(f"[green]hearing the respondent — capturing {src}[/]")
        if src == "iris_ear.monitor":
            self._w("[dim]set the app's OUTPUT to Iris_Ear[/]")
        self._refresh_status()

    def _announce_then_hear_far(self) -> None:
        """ti-rqhn: play the consent announcement into the call uplink, then — ONLY
        if it actually played — open far-party transcription. FAIL-CLOSED: if the
        announcement can't be delivered (no call endpoint, or a TTS/playback error),
        Iris does NOT listen. The far party is never captured without an announcement."""
        if not getattr(self.mic, "far_source", None):
            # No live call audio endpoint to announce into / hear from -> fail closed.
            self._w("[red]no call audio endpoint — not announcing or listening (consent gate fail-closed)[/]")
            return
        phrase = settings.get("IRIS_CALL_ANNOUNCE", "") or _DEFAULT_ANNOUNCE
        self._w(f"[yellow]announcing to the call (consent): {phrase}[/]")

        def _play() -> None:
            ok = False
            try:
                self.mic.start_playback(self.tts.synth(phrase)).wait()
                ok = True
            except Exception:  # noqa: BLE001 — any failure => fail closed (do not listen)
                ok = False
            self.events.put(("far_announced", ok, phrase))

        self.run_worker(_play, thread=True)

    def _log_consent(self, phrase: str) -> None:
        """Append an append-only consent record (the all-party-consent artifact):
        timestamp, far-party number, mode, and the announced phrase."""
        base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
        num = self._call_contact_number or self._call_contact_name or "unknown"
        try:
            os.makedirs(os.path.join(base, "iris"), exist_ok=True)
            with open(os.path.join(base, "iris", "consent.log"), "a", buffering=1) as f:
                f.write(f"{datetime.now().isoformat()}\tsupervised\t{num}\t{phrase}\n")
        except OSError:
            pass

    def action_open_list_view(self) -> None:
        """Open PostCallListView for the most recent active list."""
        self._maybe_show_post_call_list(
            getattr(self.conductor, "session_id", "") or ""
        )

    def action_list_panel(self) -> None:
        """Toggle the right-side list panel (WCAG 2.1 AA: [L] moves focus in, [Esc] returns)."""
        panel = self.query_one(ListPanel)
        visible = panel.toggle_visible()
        log = self.query_one("#log", RichLog)
        if visible:
            panel.focus()
            log.write("[dim]⟨list panel on — [Esc] or [L] to hide⟩[/]")
            self.notify("List panel opened", severity="information")
        else:
            self.query_one("#log", RichLog).focus()
            log.write("[dim]⟨list panel hidden⟩[/]")

    def action_contacts(self) -> None:
        """Open the full-width Contacts management panel ([K])."""
        self.push_screen(ContactsScreen(self._roster))

    def action_approve(self) -> None:
        """Placeholder for future approve workflow (e.g. send a drafted reply)."""
        self._w("[dim]approve not yet wired[/]")

    def action_grant(self) -> None:
        """Cycle trust NONE→LOCAL→BOTH→NONE. No-op when not armed."""
        c = self.conductor
        if not c._armed:
            self._w("[red]cannot grant — not armed / run: iris-arm[/]")
            self.notify("Cannot grant: not armed. Run: iris-arm", severity="warning")
            return
        c.grant()
        trust = c.trust_state
        if trust is TrustMode.LOCAL:
            msg = "[b #56d364]local-admin granted — you have full access[/]"
            note = "local-admin granted"
        elif trust is TrustMode.BOTH:
            msg = "[b #79c0ff]remote-admin granted — far party elevated (limited)[/]"
            note = "remote-admin granted: far party elevated"
        else:
            msg = "[yellow]all trust revoked[/]"
            note = "all trust revoked"
        self._w(msg)
        self.notify(note)
        self._refresh_status()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "arm-trust-btn":
            self._do_arm_trust()

    def _do_arm_trust(self) -> None:
        """Arm the trust session; operator can then use [g] to grant the far party."""
        self.conductor.arm()
        name = self._call_contact_name or "contact"
        self._w(f"[b yellow]ARM TRUST — {name} armed; press [g] to grant far access[/]")
        self.notify(f"Trust armed for {name}; press [g] to grant")
        self._refresh_status()
        # Card update happens via ("armed", True) in _drain()

    def _on_heard(self, text: str, label: str) -> None:
        if self.conductor.speaking:
            return  # speaking gate: Iris is talking, suppress mic to avoid self-echo
        self.events.put(("heard", text, label))  # reader thread -> main thread via the queue

    def _on_heard_far(self, text: str, label: str) -> None:
        self.events.put(("heard_far", text, label))

    # --- controls --------------------------------------------------------------
    def action_interrupt(self) -> None:
        self.conductor.interrupt()
        self._refresh_status()

    def action_mute(self) -> None:
        self.conductor.toggle_mute()
        self._refresh_status()

    def action_commands(self) -> None:
        """Dump what Iris handles: Tier-0 instant commands + the Tier-1 skills."""
        self._w("[b]Known commands[/] [dim](Tier-0 — instant, no model)[/]")
        for name, example in self.brain.tier0.commands():
            self._w(f'  [cyan]{name:<10}[/] [dim]e.g.[/] "{example}"')
        skills = [self.brain.skills.get(n) for n in self.brain.skills.names()]
        skills = [s for s in skills if s is not None]
        if skills:
            self._w('[b]Skills[/] [dim](Tier-1 — just ask naturally, e.g. "Iris, …")[/]')
            for s in skills:
                self._w(f"  [cyan]{s.name:<12}[/] [dim]{s.description}[/]")
        self._w('[dim]Anything else → local model · "ask Haiku about …" → cloud[/]')

    def action_notification(self) -> None:
        """Cycle to the next pending proactive notification ([n] key)."""
        item = self._proactive_store.cycle_next(after_id=self._current_notification_id)
        if item is None:
            self._proactive_badge = ""
            self._proactive_queue_count = 0
            self._current_notification_id = None
        else:
            self._proactive_badge = item.message[:40]
            self._proactive_queue_count = self._proactive_store.pending_count()
            self._current_notification_id = item.id
        self._proactive_delivery.reset_shown()
        self._refresh_status()
        self._toggle_notification_binding()

    def _toggle_notification_binding(self) -> None:
        """Show [n] in the footer only when a badge is active."""
        self.refresh_bindings()

    def check_action(self, action: str, parameters: tuple) -> bool:
        if action == "notification":
            return bool(self._proactive_badge)
        return True

    def on_unmount(self) -> None:
        for stream in (self._stream, self._far_stream):
            if stream is not None:
                stream.stop()
        self.conductor.interrupt()
        self.conductor.close()
        if self._logf is not None:
            self._logf.close()


def main() -> int:
    IrisConsole().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
