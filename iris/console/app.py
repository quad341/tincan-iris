"""Textual operator console for Iris — the local 'admin app'.

Live transcription, per-turn tier + latency, a hard interrupt (barge-in), mute,
and a command dump — over the local voice loop. Ways to talk:
  - push-to-talk: [space] to start/stop a turn;
  - listen [L]: continuous — just talk, Iris acts only when addressed ("Hey Iris, …");
  - respondent [f]: also hear the far-end party (the other side of a call);
  - approve [a]: allow the respondent's "Hey Iris, …" commands to act (default OFF —
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

Keys: [space] talk · [l] hear you · [L] list panel · [f] hear them · [a] approve them · [i] interrupt · [m] mute · [d] DND · [c] commands · [y] copy last reply · [q] quit
"""
from __future__ import annotations

import os
import queue
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from rich.markup import escape
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Button, Footer, Header, RichLog, Static

from .. import settings
from ..addressing import address
from ..daemon.posture import PostureManager
from ..daemon.proxy import DaemonNotRunning, DaemonProxy
from ..message_store import MessageStore
from ..prefs import PreferencesStore
from . import diagnostics
from .contacts import ContactsScreen
from .contacts_logic import VERB_DESCRIPTION
from .help_screen import HelpScreen
from .list_view import PostCallListView
from .call_card import (
    ActionItemConfirmed,
    ActionItemEdited,
    CallCardPanel,
    DisclosureAcknowledged,
    DisclosureSkipped,
    FactConfirmed,
    FactDismissed,
    FactValueOverride,
)
from .post_call_review import PostCallReviewScreen
from ..audio.endpoint import default_endpoint
from ..audio.streaming import StreamingTranscriber
from ..audio.stt import default_stt
from ..audio.tts import default_tts
from ..brain import Brain
from ..call_control import TincanCallControl
from ..capture.after_store import AfterStore
from ..capture.store import CallCardStore
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

# Operator voice command to end the call: "Hey Iris, hang up" (operator stream only).
_HANGUP = re.compile(
    r"^\s*(?:hang\s*up|hang\s*the\s*phone|end\s+(?:the\s+)?call|drop\s+the\s+call)\b",
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
    """Open the plain-text session logfile (append; survives restarts/crashes).
    $IRIS_LOG_FILE overrides the default ~/.local/state/iris/console.log. Auto-rotates
    to a single console.log.1 backup once IRIS_LOG_MAX_BYTES (default 5MB) is exceeded,
    so the file stays bounded without multiplying discoverable paths (ti-qz990 OQ1).
    Returns (file, path) or (None, None)."""
    path = settings.get("IRIS_LOG_FILE")
    if not path:
        base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
        try:
            os.makedirs(os.path.join(base, "iris"), exist_ok=True)
        except OSError:
            return None, None
        path = os.path.join(base, "iris", "console.log")
    max_bytes = settings.get_int("IRIS_LOG_MAX_BYTES", 5_000_000)
    try:
        if os.path.getsize(path) > max_bytes:
            os.replace(path, path + ".1")
    except OSError:
        pass  # doesn't exist yet, or rotation failed — fall through to open/create below
    try:
        f = open(path, "a", buffering=1)
        os.chmod(path, 0o600)  # may carry call content/contact PII
        f.write(f"=== session start: pid={os.getpid()} {datetime.now().isoformat()} ===\n")
        return f, path
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
        self._refresh()

    def on_lookup_done(self, item_id: int, result: str) -> None:
        self._refresh()

    def on_lookup_failed(self, item_id: int, msg: str) -> None:
        self._refresh()

    def add_item(self, text: str) -> None:
        self._items.append((text, "none", ""))
        self._refresh()

    def _icon(self, state: str, checked: bool) -> str:
        if checked:
            return "☑"
        return {"none": "○", "pending": "⏳", "done": "✓", "failed": "⚠"}.get(state, "○")

    def _refresh(self) -> None:
        # NB: must NOT be named _render — that collides with Textual's internal
        # Widget._render(), whose return value is used by the renderer (returning
        # None here crashes the moment the panel is shown).
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


class IncomingCallPanel(Widget, can_focus=False):
    """Shown when an incoming call is pending; hidden otherwise.

    State transitions:
      hide()                   → hidden (no call)
      show(verb, ...)          → visible (one of 3 verb states)
      update_intro(text)       → updates the caller-intro transcript (screen only)
      update_countdown(s)      → updates the 'Auto-message in Ns' counter (screen)
    """

    DEFAULT_CSS = """
    IncomingCallPanel {
        display: none;
        height: auto;
        min-height: 4;
        background: #1a2a4a;
        border: round #4040aa;
        padding: 0 2;
        margin: 0 0 1 0;
    }
    IncomingCallPanel.active {
        display: block;
    }
    IncomingCallPanel #call-header {
        color: #cdd6f4;
        text-style: bold;
    }
    IncomingCallPanel #call-caller {
        color: #89b4fa;
    }
    IncomingCallPanel #call-body {
        color: #a6adc8;
    }
    IncomingCallPanel #call-intro {
        color: #a6e3a1;
    }
    IncomingCallPanel #call-countdown {
        color: #fab387;
    }
    IncomingCallPanel #call-choices {
        color: #cdd6f4;
        text-style: bold;
        margin-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="call-header")
        yield Static("", id="call-caller")
        yield Static("", id="call-body")
        yield Static("", id="call-intro")
        yield Static("", id="call-countdown")
        yield Static("", id="call-choices")

    def show(
        self,
        verb: str,
        caller_name: str,
        caller_number: str,
        choices: list[dict],
    ) -> None:
        """Display the panel for an incoming call."""
        header = f"📞 INCOMING CALL — {escape(verb)}"
        display_name = escape(caller_name or caller_number or "(unknown)")
        caller_line = f"{display_name}  [dim]·[/]  {escape(caller_number)}" if caller_name else escape(caller_number)
        body = VERB_DESCRIPTION.get(verb, "")
        choice_keys = "  ".join(
            rf"[b]\[{c['key']}][/] {escape(c['label'])}" for c in choices
        ) if choices else ""

        self.query_one("#call-header", Static).update(header)
        self.query_one("#call-caller", Static).update(caller_line)
        self.query_one("#call-body", Static).update(body)
        self.query_one("#call-intro", Static).update("")
        self.query_one("#call-countdown", Static).update("")
        self.query_one("#call-choices", Static).update(choice_keys)
        self.add_class("active")

    def update_intro(self, text: str) -> None:
        """Update the screening intro transcript."""
        self.query_one("#call-intro", Static).update(f'Caller: "{escape(text)}"')

    def update_countdown(self, seconds_remaining: int) -> None:
        """Update the auto-message countdown (screen verb)."""
        if seconds_remaining > 0:
            filled = max(0, min(10, 10 - seconds_remaining // 3))
            bar = "▓" * filled + "░" * (10 - filled)
            self.query_one("#call-countdown", Static).update(
                f"[{bar}]  Auto-message in {seconds_remaining}s"
            )
        else:
            self.query_one("#call-countdown", Static).update("")

    def hide(self) -> None:
        """Hide the panel (call ended)."""
        self.remove_class("active")


class IrisConsole(App):
    TITLE = "Iris console"

    CSS = """
    #main-row { height: 1fr; }
    #log { height: 1fr; border: round $accent; padding: 0 1; }
    #status { height: 1; background: $boost; color: $text; padding: 0 1; }
    """

    BINDINGS = [
        Binding("question_mark", "help", "help"),
        Binding("space", "talk", "talk/stop", priority=True),
        Binding("l", "listen", "hear"),
        Binding("L", "list_panel", "list"),
        Binding("V", "call_card_panel", "card"),
        Binding("f", "far", "far"),
        Binding("g", "grant", "grant", priority=True),
        Binding("a", "approve", "approve"),
        Binding("i", "interrupt", "stop", priority=True),
        Binding("m", "mute", "mute"),
        Binding("d", "toggle_dnd", "dnd", show=False),
        Binding("n", "notification", "next notif", show=False),
        Binding("c", "commands", "cmds"),
        Binding("y", "copy_last", "copy reply", show=False),
        Binding("e", "copy_last_error", "copy error", show=False),
        Binding("b", "file_bug", "file a bug"),
        Binding("K", "contacts", "book"),
        Binding("q", "quit", "quit", priority=True),
        Binding("1", "choose_1", "put through", show=False),
        Binding("2", "choose_2", "take message", show=False),
        Binding("3", "choose_3", "decline", show=False),
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
        self._last_iris_reply: str = ""
        self._last_error: str = ""
        self._call_contact_name: str = ""
        self._call_contact_number: str = ""
        self._call_trust_eligible: bool = False
        self._in_call: bool = False
        self._pre_call_muted: bool = False
        self._far_announced: bool = False  # ti-rqhn: announced consent to the far party this call?
        self._follow_up_until: float = 0.0
        # Iris asked a question → listen for the reply without a wake word. Armed when
        # her reply ends with "?"; the window opens when she stops speaking (→ IDLE).
        self._await_answer: bool = False
        self._messages = MessageStore()
        self._roster = RosterStore()
        self._call_card_store = CallCardStore()
        self._after_store = AfterStore()
        self._post_call_review_shown: set[str] = set()
        self._posture = PostureManager()
        self._dnd: bool = False
        self._dnd_expires: float | None = None
        self._proxy: DaemonProxy | None = None  # set in on_mount if daemon is running
        self._mode: str = "direct"  # "proxy" or "direct"; set in on_mount
        self._incoming_call_id: str | None = None
        self._incoming_verb: str | None = None
        self._incoming_choices: list[dict] = []
        self._screen_start: float = 0.0
        self._screen_auto_s: int = 30   # default auto-message timeout; wired from flow in ti-gxpt.5+
        self._countdown_last: float = 0.0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield ActiveCallCard(id="active-call-card")
        yield IncomingCallPanel(id="incoming-call-panel")
        with Horizontal(id="main-row"):
            yield RichLog(id="log", markup=True, wrap=True)
            yield ListPanel()
            yield CallCardPanel(id="call-card-panel")
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
        self._w("[dim]press [?] for help[/]")
        if not self.stt.available():
            self._w("[red]STT not set up — run:  bash scripts/setup_whisper.sh[/]")
        self.set_interval(0.05, self._drain)

        # Try to connect to the daemon; fall back to direct TincanCallControl.
        proxy = DaemonProxy()
        try:
            proxy.connect()
            self._proxy = proxy
            self._mode = "proxy"
            proxy.start_event_reader(
                on_event=lambda ev: self.events.put(("daemon_event", ev)),
                on_disconnect=lambda: self.events.put(("daemon_event", {"event": "disconnected"})),
            )
            self._w("[dim]Daemon connected — brain turns via socket[/]")
            eff = self._posture.effective()
            self._dnd = eff["dnd"]
            self._refresh_status()
        except DaemonNotRunning:
            proxy.close()
            self._proxy = None
            self._mode = "direct"
            self._w("[yellow]Daemon not running — using direct mode (iris daemon start)[/]")
            self.ctrl.start()  # direct TincanCallControl
            self._posture.subscribe(lambda ev: self.events.put(("posture_changed", ev)))
            eff = self._posture.effective()
            self._dnd = eff["dnd"]
            self._refresh_status()

        # ti-veyx: load the WebRTC AEC once (idempotent) for feedback-free call
        # audio. Unconditional so it's ready in direct mode and after a
        # daemon-disconnect fallback (which calls ctrl.start()).
        self._ensure_aec_up()

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

    def _drain(self) -> None:
        """Pump conductor + stream events (posted from worker threads) into the UI."""
        try:
            while True:
                ev = self.events.get_nowait()
                kind = ev[0]
                if kind == "transcript":
                    text, ms = ev[1], ev[2]
                    self._w(
                        f"[bold]you[/]  › {escape(text) or '(heard nothing)'}"
                        f"  [dim]⟮stt {ms:.0f}ms⟯[/]"
                    )
                elif kind == "reply":
                    self._last_iris_reply = ev[1]
                    self._w(f"[bold cyan]iris[/] › {escape(ev[1])}")
                    self._w(f"        [dim]⟮{ev[2]} · {ev[3]}⟯[/]")
                    # If Iris asked a question, listen for the answer without a wake
                    # word — the window opens when she stops speaking (state → IDLE).
                    self._await_answer = bool(ev[1]) and ev[1].rstrip().endswith("?")
                elif kind == "heard":
                    self._on_heard_main(ev[1], ev[2] if len(ev) > 2 else "")
                elif kind == "heard_far":
                    self._on_heard_far_main(ev[1], ev[2] if len(ev) > 2 else "")
                elif kind == "error":
                    self._w(f"[red]✗ {escape(ev[1])}[/]")
                    self._last_error = ev[1]
                    self.notify(
                        r"Error - press \[e] to copy it, \[b] to file a bug",
                        severity="error",
                    )
                    self._refresh_status()
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
                    # Hands-free ride-along: keep the mic UNMUTED so Iris's addressed
                    # replies are audible to both parties (was: auto-mute push-to-talk,
                    # ti-gbz4.1). She still only SPEAKS when addressed ("Hey Iris, …").
                    self._pre_call_muted = self.conductor.muted
                    # No auto-mute (was ti-gbz4.1 push-to-talk): ride-along keeps the
                    # conductor's current state — unmuted by default — so addressed
                    # replies are audible to both. The operator can still [m] to mute.
                    # Drop any stale far stream from a prior call before re-consenting.
                    if self._far_stream is not None:
                        self._far_stream.stop()
                        self._far_stream = None
                    # ti-veyx: adopt the live SCO endpoint so Iris hears/speaks on the call.
                    self._attach_call_audio()
                    # Make the grant control reachable on ANY call (incl. outbound): the
                    # operator arms via the ARM TRUST button, then [g] grants the far party.
                    self.query_one(ActiveCallCard).show_card(
                        self._call_contact_name or self._call_contact_number or "call"
                    )
                    # ti-rqhn: re-announce every call — never assume prior consent.
                    self._far_announced = False
                    self._w(
                        "[green]call connected — ride-along: say \"Hey Iris …\"; "
                        "ARM TRUST + \\[g] to grant the far party[/]"
                    )
                    # Hands-free: continuously listen to the operator, and disclose to
                    # BOTH parties — a successful announcement opens far-party
                    # transcription via the far_announced gate (consent stays fail-closed).
                    self._begin_ride_along()
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
                        f"[b]📩 Message from {escape(caller_name)}[/]"
                        + (f" ({escape(caller_number)})" if caller_number else "")
                    )
                    self._w(f"   [dim]{escape(transcript[:120])}{'…' if len(transcript) > 120 else ''}[/]")
                    self._w(f"   [dim]msg-id:{msg.id}  ·  say 'mark read {msg.id}' or 'call back {msg.id}'[/]")
                elif kind == "proactive_badge":
                    self._proactive_badge = ev[1][:40] if ev[1] else ""
                    self._proactive_queue_count = ev[2] if len(ev) > 2 else 0
                    self._refresh_status()
                    self._toggle_notification_binding()
                elif kind == "proactive_tts":
                    self._w(
                        f"[b yellow]🔔[/] {escape(ev[1]) if len(ev) > 1 else ''}  [dim](proactive)[/]"
                    )
                elif kind == "mayor_reply":
                    # ti-h9di.3: mayor reply delivered via SSE listener.
                    # Display in transcript (no-audio path); also speak if unmuted.
                    reply_text = ev[1] if len(ev) > 1 else ""
                    if reply_text:
                        self._w(f"[b magenta]mayor[/] → iris: {escape(reply_text)}")
                        if self.conductor.state is State.IDLE:
                            self.run_worker(
                                lambda t=reply_text: self.conductor.say(t),
                                thread=True, exclusive=True,
                            )
                elif kind == "filler":
                    self._note = f"… {ev[1]}"
                    self._refresh_status()
                elif kind == "state":
                    if ev[1] is State.IDLE:
                        self._note = ""
                        if self._await_answer:
                            # Iris just finished asking a question — open the
                            # no-wake-word window so the operator can just answer.
                            self._await_answer = False
                            self._follow_up_until = time.monotonic() + _FOLLOW_UP_S
                    self._refresh_status()
                elif kind == "mute":
                    self._refresh_status()
                elif kind == "posture_changed":
                    payload = ev[1]
                    self._dnd = payload.get("dnd", False)
                    self._dnd_expires = payload.get("dnd_expires")
                    self._refresh_status()
                elif kind == "daemon_event":
                    self._on_daemon_event(ev[1])
        except queue.Empty:
            pass
        # Update screen countdown once per second (visual-only; flow wired in ti-gxpt.5+)
        if self._incoming_call_id and self._incoming_verb == "screen":
            now = time.monotonic()
            if now - self._countdown_last >= 1.0:
                self._countdown_last = now
                elapsed = int(now - self._screen_start)
                remaining = max(0, self._screen_auto_s - elapsed)
                self.query_one(IncomingCallPanel).update_countdown(remaining)

    def _on_daemon_event(self, ev: dict) -> None:
        """Handle a JSON event received from DaemonProxy.

        SINGLE-OWNER INVARIANT: deliberately has no "call_connected" case, so
        proxy mode never starts the console's own ride-along capture
        (_attach_call_audio()/_begin_ride_along(), direct-mode-only — see the
        streaming-loop handler above). Proxy mode's daemon already owns
        capture via CallCardHost/HandlingEngine/BrainHost. Adding a
        "call_connected" case here (e.g. to restore proxy-mode UI feedback)
        would double audio capture unless it keeps excluding those calls.
        """
        event_type = ev.get("event", "")
        if event_type == "incoming_call":
            self._incoming_call_id = ev.get("call_id")
            self._incoming_verb = ev.get("verb", "")
            self._incoming_choices = ev.get("choices", [])
            caller_name = ev.get("caller_name", "")
            caller_number = ev.get("caller_number", "")
            if self._incoming_verb == "screen":
                self._screen_start = time.monotonic()
                self._countdown_last = 0.0
            panel = self.query_one(IncomingCallPanel)
            panel.show(
                self._incoming_verb,
                caller_name,
                caller_number,
                self._incoming_choices,
            )
            self.notify(
                f"Incoming call: {escape(caller_name or caller_number)}",
                severity="warning",
            )
            self.refresh_bindings()
            self._refresh_status()
        elif event_type == "screen_intro":
            if ev.get("call_id") == self._incoming_call_id:
                self.query_one(IncomingCallPanel).update_intro(ev.get("intro", ""))
        elif event_type == "call_ended":
            if ev.get("call_id") == self._incoming_call_id or self._incoming_call_id:
                self._incoming_call_id = None
                self._incoming_verb = None
                self._incoming_choices = []
                self.query_one(IncomingCallPanel).hide()
                self.refresh_bindings()
                self._refresh_status()
        elif event_type == "posture":
            self._dnd = ev.get("dnd", False)
            self._dnd_expires = ev.get("expires_in_s")
            self._refresh_status()
        elif event_type == "call_card_recap_ready":
            # Primary Post-Call Review trigger (ti-qyo3p): recap generated,
            # so the LLM-summary path succeeded — show the review screen now
            # rather than waiting for the call_card_ended fallback below.
            self.query_one(CallCardPanel).handle_event(ev)
            session_id = ev.get("session_id")
            if session_id is not None:
                self._maybe_show_post_call_review(str(session_id))
        elif event_type == "call_card_ended":
            # NFR2 fallback (ti-qyo3p): no API key configured means
            # call_card_recap_ready never fires. Give the recap a couple of
            # seconds to arrive anyway; _maybe_show_post_call_review's dedup
            # guard makes this a no-op if it already has.
            self.query_one(CallCardPanel).handle_event(ev)
            session_id = ev.get("session_id")
            if session_id is not None:
                self.set_timer(
                    2.5,
                    lambda sid=str(session_id): self._maybe_show_post_call_review(sid),
                )
        elif event_type.startswith("call_card"):
            # Live Call Card capture events from the daemon (ti-913rw) — feed the
            # side panel. Runs on the UI thread (drained from the queue).
            self.query_one(CallCardPanel).handle_event(ev)
        elif event_type == "disconnected":
            self._w("[yellow]Daemon disconnected — switched to direct mode[/]")
            self._proxy = None
            self._mode = "direct"
            self.ctrl.start()
            self._posture.subscribe(lambda e: self.events.put(("posture_changed", e)))

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
            self._w(f"[dim]aec {action} failed: {escape(str(exc))}[/]")
            return False
        return proc.returncode == 0

    def _ensure_aec_up(self) -> None:
        """Load the WebRTC AEC at startup — default ON, ``IRIS_AEC=0`` to disable.

        Echo cancellation is the make-or-break requirement of the whole stack
        (ti-wunrs): without it the far party hears themselves. Default-on is
        safe *because this runs before any capture starts*: the historical
        mic-contention (module-echo-cancel grabbing the mic as source_master
        and starving a continuous-listen capture) only bites captures opened
        BEFORE the module loads — at startup none exist yet, and every later
        capture reads the new default source (``iris_aec_src``), which is the
        echo-cancelled mic.

        Keeping it always-loaded (not per-call) is the ti-veyx design: the
        canceller is harmless when idle / on a headset and avoids a module load
        on every call. A second ``up`` just no-ops. Opt out with
        ``[audio] aec = false`` / ``IRIS_AEC=0`` (e.g. dedicated-headset rigs
        that want the raw mic).
        """
        if settings.get_bool("IRIS_AEC", default=True):
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

    def _begin_ride_along(self) -> None:
        """Hands-free ride-along on connect: continuously listen to the operator and
        disclose to BOTH parties. The disclosure (on a successful announcement) opens
        far-party transcription via the ``far_announced`` gate — consent stays
        fail-closed. No push-to-talk; the operator addresses Iris with "Hey Iris, …"."""
        if self._stream is None:
            self.action_listen()             # start operator continuous listen
        if not self._far_announced:
            self._announce_then_hear_far()   # disclose -> far_announced -> _start_far_stream

    def _hang_up_call(self) -> None:
        """Operator voice command "Hey Iris, hang up": speak a goodbye to both parties
        (blocking, so it is heard before the line drops), then end the call. Reached
        only from the operator stream — the far party cannot hang up."""
        if not self._in_call:
            self._w("[dim](no active call to hang up)[/]")
            return
        self._w("[yellow]you → iris: hang up[/]")

        def _bye_then_hangup() -> None:
            try:
                self.conductor.say("Sure — talk soon. Goodbye!")
            finally:
                self.ctrl._hangup("")  # noqa: SLF001 — D-Bus Hangup; CallEnded cleans up

        self.run_worker(_bye_then_hangup, thread=True, exclusive=True)

    def _on_list_event(self, ev: tuple) -> None:
        """Handle list-related events from ListSkill background threads."""
        panel = self.query_one(ListPanel)
        log = self.query_one("#log", RichLog)
        kind = ev[1] if len(ev) > 1 else ""
        if kind == "lookup_done" and len(ev) >= 4:
            item_id, result = ev[2], ev[3]
            log.write(f"[dim cyan]⟨list: lookup done — {escape(str(result)[:60])}⟩[/]")
            panel.on_lookup_done(item_id, result)
        elif kind == "lookup_failed" and len(ev) >= 4:
            item_id, msg = ev[2], ev[3]
            log.write(f"[dim red]⟨list: lookup failed — {escape(str(msg))}⟩[/]")
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

    def _maybe_show_post_call_review(self, session_id: str) -> None:
        """Push PostCallReviewScreen (ti-qyo3p) for a finished call.

        Called from both the "call_card_recap_ready" event (primary trigger)
        and a bounded-wait fallback timer off "call_card_ended" (NFR2: no
        API key configured, so no recap event ever arrives). The dedup guard
        makes whichever fires first win and the other a no-op.
        """
        if session_id in self._post_call_review_shown:
            return
        try:
            card = self._call_card_store.get_call_card(session_id)
            if not card:
                return
            contact_id = card.get("contact_id")
            if contact_id is None:
                return
            contact = self._roster.get(contact_id)
            if contact is None:
                return
            self._post_call_review_shown.add(session_id)
            commitments = self._after_store.get_open_commitments(contact_id)
            rep_name = self.brain.cfg.operator_name
            self.push_screen(
                PostCallReviewScreen(
                    contact, card, commitments, self._after_store, rep_name=rep_name
                )
            )
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
                self._w(f"[bold]you[/] → iris: {escape(text)}")
                self._dispatch(text, speaker)
            else:
                self._w(f"[dim]· {escape(text)}[/]")  # overheard, not for Iris
            return
        self._w(f"[bold]you[/] → iris: {escape(text)}")
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
        elif _HANGUP.match(cmd):
            self._hang_up_call()  # operator-only end-call: say goodbye, then Hangup
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
        if self._in_call and not self._far_announced:
            return  # ti-gbz4.2 + ti-rqhn: far party suppressed UNTIL consent announced
        cmd = address(text)
        if cmd is None:
            self._w(f"[dim]them: {escape(text)}[/]")  # respondent, not addressing Iris
            return
        self._w(f"[magenta]them[/] → iris: {escape(text)}")
        if not cmd:
            return
        if not self._dispatch(cmd, speaker):
            self._w("[dim](busy — one sec)[/]")

    def _refresh_status(self) -> None:
        import os as _os  # noqa: PLC0415
        c = self.conductor
        mode_pill = "🟢 daemon" if self._mode == "proxy" else "🟡 direct"
        parts = [mode_pill, c.state.value.upper()]
        if c.muted:
            parts.append("[b]MUTED[/]")
        # Audio mode label (startup-time env var)
        if _os.environ.get("IRIS_VA_AEC"):
            parts.append("[dim]AEC[/]")
        elif settings.get_bool("IRIS_AEC", default=True):
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
                    rf"[b yellow]🔔 {self._proactive_queue_count} pending  ·  press \[n] to cycle[/]"
                )
            else:
                parts.append(f"[b yellow]🔔 {escape(self._proactive_badge)}[/]")
        if self._last_error:
            parts.append(r"[b red]⚠ error just now — \[e] copy · \[b] file bug[/]")
        if self._dnd:
            if self._dnd_expires is not None:
                from datetime import datetime as _dt
                until = _dt.fromtimestamp(self._dnd_expires).strftime("%H:%M")
                parts.append(f"[b #f38ba8]■ DND until {until}[/]")
            else:
                parts.append("[b #f38ba8]■ DND[/]")
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
        self._w('[green]hearing you — just talk; say "Hey Iris, …" to address her[/]')
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

    def action_call_card_panel(self) -> None:
        """Toggle the live Call Card side panel."""
        self.query_one(CallCardPanel).toggle_panel()

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

    def action_help(self) -> None:
        """Open the [?] help screen — the universal 'how do I use this' key."""
        self.push_screen(HelpScreen(self._logpath))

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

    def on_disclosure_acknowledged(self, message: DisclosureAcknowledged) -> None:
        """Forward the operator's disclosure to the daemon — gates far-party capture."""
        if self._proxy is not None:
            try:
                self._proxy.send({"cmd": "disclosure_ack", "session_id": message.session_id})
            except DaemonNotRunning:
                self._w("[red]Daemon disconnected — disclosure not recorded[/]")

    def on_disclosure_skipped(self, message: DisclosureSkipped) -> None:
        """Forward the operator's explicit skip — daemon must never start far capture."""
        if self._proxy is not None:
            try:
                self._proxy.send({"cmd": "disclosure_skip", "session_id": message.session_id})
            except DaemonNotRunning:
                self._w("[red]Daemon disconnected — skip not recorded[/]")

    def on_fact_confirmed(self, message: FactConfirmed) -> None:
        self._call_card_store.confirm_fact(message.fact_id, True)

    def on_fact_dismissed(self, message: FactDismissed) -> None:
        self._call_card_store.confirm_fact(message.fact_id, False)

    def on_fact_value_override(self, message: FactValueOverride) -> None:
        self._call_card_store.confirm_fact(
            message.fact_id, True, normalized_value=message.new_value
        )

    def on_action_item_confirmed(self, message: ActionItemConfirmed) -> None:
        self._call_card_store.confirm_action_item(message.item_id, True)

    def on_action_item_edited(self, message: ActionItemEdited) -> None:
        self._call_card_store.confirm_action_item(
            message.item_id,
            True,
            description=message.description,
            due_date=message.due_date,
        )

    def _do_arm_trust(self) -> None:
        """Arm the trust session; operator can then use [g] to grant the far party."""
        self.conductor.arm()
        name = escape(self._call_contact_name or "contact")
        self._w(rf"[b yellow]ARM TRUST — {name} armed; press \[g] to grant far access[/]")
        self.notify(rf"Trust armed for {name}; press \[g] to grant")
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

    def action_toggle_dnd(self) -> None:
        """Toggle DND (do not disturb) via proxy (daemon mode) or PostureManager (direct)."""
        if self._proxy is not None:
            action = "off" if self._dnd else "on"
            try:
                self._proxy.send({"cmd": "dnd", "action": action})
            except DaemonNotRunning:
                self._w("[red]Daemon disconnected — DND not toggled[/]")
                return
            if action == "on":
                self._w("[yellow]DND ON — calls will be screened.[/]")
                self.notify("DND on — calls will be screened.", severity="warning")
            else:
                self._w("[green]DND OFF.[/]")
                self.notify("DND off — calls will ring normally.", severity="information")
        else:
            if self._dnd:
                self._posture.clear_dnd()
                self._w("[green]DND OFF.[/]")
                self.notify("DND off — calls will ring normally.", severity="information")
            else:
                self._posture.set_dnd("manual")
                self._w("[yellow]DND ON — calls will be screened.[/]")
                self.notify("DND on — calls will be screened.", severity="warning")

    def action_commands(self) -> None:
        """Dump what Iris handles: Tier-0 instant commands + the Tier-1 skills."""
        self._w("[b]Known commands[/] [dim](Tier-0 — instant, no model)[/]")
        for name, example in self.brain.tier0.commands():
            self._w(f'  [cyan]{name:<10}[/] [dim]e.g.[/] "{example}"')
        skills = [self.brain.skills.get(n) for n in self.brain.skills.names()]
        skills = [s for s in skills if s is not None]
        if skills:
            self._w('[b]Skills[/] [dim](Tier-1 — just ask naturally, e.g. "Hey Iris, …")[/]')
            for s in skills:
                self._w(f"  [cyan]{s.name:<12}[/] [dim]{s.description}[/]")
        self._w('[dim]Anything else → local model · "ask Haiku about …" → cloud[/]')
        self._w("  [cyan]d[/]          [dim]toggle DND (do not disturb)[/]")

    def action_copy_last(self) -> None:
        """Copy the last Iris reply to the system clipboard ([y] key)."""
        if not self._last_iris_reply:
            self.notify("No reply to copy yet.", severity="warning")
            return
        self._copy_text_to_clipboard(self._last_iris_reply)

    def action_copy_last_error(self) -> None:
        """Copy the last captured error to the system clipboard ([e] key)."""
        if not self._last_error:
            self.notify("No error to copy yet.", severity="warning")
            return
        self._copy_text_to_clipboard(self._last_error)

    def action_file_bug(self) -> None:
        """Write a bug-report snapshot ([b] key) — works mid-session, not only post-crash."""
        path = diagnostics.write_bug_report("manual")
        if path is not None:
            self.notify(f"Bug report written: {path}", severity="information")
        else:
            self.notify("Could not write bug report (see stderr).", severity="error")

    def _copy_text_to_clipboard(self, text: str) -> None:
        """OSC 52 always (dependency-free, works over SSH); subprocess additionally when a
        clipboard binary is present. OSC 52 has no delivery acknowledgment, so this is
        redundancy, not an either/or chain (ti-qz990 OQ6) — wording says "best-effort"
        because a silently-ignored OSC 52 sequence can't be told apart from success.
        """
        try:
            self.copy_to_clipboard(text)
        except Exception:  # noqa: BLE001 — OSC52 is best-effort; the subprocess path still runs
            pass
        for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--input", "--clipboard"]):
            if subprocess.run(["which", cmd[0]], capture_output=True).returncode == 0:
                try:
                    subprocess.run(cmd, input=text.encode(), check=True)
                except Exception as e:  # noqa: BLE001
                    self.notify(f"Clipboard error: {escape(str(e))}", severity="error")
                    return
                break
        self.notify("Copied (best-effort).", severity="information")

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
        if action in ("choose_1", "choose_2", "choose_3"):
            return self._incoming_call_id is not None
        if action == "copy_last":
            return bool(self._last_iris_reply)
        if action == "quit":
            # HelpScreen's own "q" is priority=True (matches ContactsScreen's
            # convention); Textual's priority-binding dispatch checks the App
            # before the Screen, so without this gate "q" would quit the app
            # instead of closing help. Suppressing "quit" here falls through
            # to HelpScreen's own binding in the same priority pass. Same
            # deal for PostCallReviewScreen (ti-qyo3p). ContactsScreen and
            # PostCallListView have the identical priority=True "q" binding
            # but aren't listed here — a pre-existing gap, not introduced by
            # this bead; tracked separately rather than widened here.
            return not isinstance(self.screen, (HelpScreen, PostCallReviewScreen))
        return True

    def _send_choose(self, index: int) -> None:
        """Send a choose command for the Nth choice (1-based)."""
        if self._incoming_call_id is None:
            return
        choices = self._incoming_choices
        if index < 1 or index > len(choices):
            self._w(f"[dim](choice {index} not available)[/]")
            return
        choice = choices[index - 1]
        label = choice.get("label", str(index))
        action_id = choice.get("id", "")
        if self._proxy is not None:
            try:
                self._proxy.send({
                    "cmd": "choose",
                    "call_id": self._incoming_call_id,
                    "action_id": action_id,
                })
            except DaemonNotRunning:
                self._w("[red]Daemon disconnected — choice not sent[/]")
                return
        self._w(f"[cyan]→ {escape(label)}[/]")
        self.notify(f"Choice: {escape(label)}", severity="information")

    def action_choose_1(self) -> None:
        self._send_choose(1)

    def action_choose_2(self) -> None:
        self._send_choose(2)

    def action_choose_3(self) -> None:
        self._send_choose(3)

    def on_unmount(self) -> None:
        for stream in (self._stream, self._far_stream):
            if stream is not None:
                stream.stop()
        self.conductor.interrupt()
        self.conductor.close()
        if self._proxy is not None:
            self._proxy.close()
        if self._logf is not None:
            self._logf.close()

    def _handle_exception(self, error: Exception) -> None:
        """Persist the crash before Textual's own panic/restore handling (ti-qz990 OQ2).

        Covers the message pump and every run_worker(..., thread=True) call site in this
        file (the STT/TTS pipeline included) — Textual's own run()/run_async() never
        re-raise, so this override is the only reliable funnel point for those crashes.
        """
        diagnostics.persist_crash("app", error)
        super()._handle_exception(error)


_CRASH_EXIT_LABEL_WIDTH = 23  # aligns the value column across all three lines below


def _crash_exit_message() -> str:
    """Final stderr block for a message-pump/run_worker crash — printed once Textual's
    own panic/traceback dump has already rendered to the restored terminal and the app
    has fully exited, so it's the last thing left in scrollback (ti-00jr4.2)."""
    lines = [
        "Iris crashed — sorry about that.",
        "  " + "Log (just appended):".ljust(_CRASH_EXIT_LABEL_WIDTH) + diagnostics.log_path(),
    ]
    bug_report = diagnostics.last_crash_bug_report()
    if bug_report is not None:
        lines.append("  " + "Bug report:".ljust(_CRASH_EXIT_LABEL_WIDTH) + str(bug_report))
    lines.append("  " + "Retry:".ljust(_CRASH_EXIT_LABEL_WIDTH) + "python -m iris.console")
    return "\n".join(lines)


def main() -> int:
    diagnostics.install_exception_hooks()
    app = IrisConsole()
    diagnostics.set_active_app(app)
    try:
        app.run()
    finally:
        # app.return_code is set to 1 exclusively by Textual's own _handle_exception
        # (IrisConsole never sets a custom return_code elsewhere) — an unambiguous
        # crash signal. By the time app.run() returns, Textual has already restored
        # the terminal and printed its own panic/traceback dump (_print_error_renderables
        # runs after driver.close(), before run_async returns), so this print is
        # strictly the last thing in scrollback, per ti-00jr4.2.
        if app.return_code:
            print(_crash_exit_message(), file=sys.stderr)
        diagnostics.clear_active_app()
    return app.return_code or 0


if __name__ == "__main__":
    raise SystemExit(main())
