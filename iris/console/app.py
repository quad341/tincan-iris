"""Textual operator console for Iris — the local 'admin app'.

Live transcription, per-turn tier + latency, a hard interrupt (barge-in), mute,
and a command dump — over the local voice loop. Ways to talk:
  - push-to-talk: [space] to start/stop a turn;
  - listen [l]: continuous — just talk, Iris acts only when addressed ("Iris, …");
  - respondent [f]: also hear the far-end party (the other side of a call);
  - approve [a]: allow the respondent's "Iris, …" commands to act (default OFF —
    their requests are shown but ignored until you approve).

Drives the UI-agnostic Conductor; the blocking pipeline runs in a Textual thread-
worker so the UI stays responsive (and the interrupt key always lands).

    python -m iris.console      # needs scripts/setup_whisper.sh + a llama-server

Every line shown is also appended (plain text) to a session logfile —
~/.local/state/iris/console.log by default, or $IRIS_LOG_FILE — so a session can
be read back or shared without copying out of the TUI.

Keys: [space] talk · [l] hear you · [f] hear them · [a] approve them · [i] interrupt · [m] mute · [c] commands · [q] quit
"""
from __future__ import annotations

import os
import queue
import re
from datetime import datetime

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, RichLog, Static

from ..addressing import address
from ..audio.endpoint import default_endpoint
from ..audio.streaming import StreamingTranscriber
from ..audio.stt import default_stt
from ..audio.tts import default_tts
from ..brain import Brain
from ..fillers import filler_picker
from ..trust import TrustMode
from .conductor import Conductor, State

# Addressed stop words -> a hard interrupt (cut her off now, no spoken reply).
_STOP = re.compile(
    r"^\s*(?:stop|stand[ -]?down|cancel|never ?mind|quiet|enough|shush|hush)\b",
    re.IGNORECASE,
)

# Grant far party full access — operator mic only; cannot be spoofed from downlink.
_GRANT = re.compile(
    r"^\s*(?:grant|give|allow|trust)\b.*\b(?:full|access|them|her|him)\b",
    re.IGNORECASE,
)

# Strip Rich markup ([red], [/], [bold cyan]…) so the session logfile is plain text.
_MARKUP = re.compile(r"\[/?[^\]]*\]")


def _open_log():
    """Open the plain-text session logfile (fresh per run). $IRIS_LOG_FILE overrides
    the default ~/.local/state/iris/console.log. Returns (file, path) or (None, None)."""
    path = os.environ.get("IRIS_LOG_FILE")
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


class IrisConsole(App):
    TITLE = "Iris console"

    CSS = """
    #log { height: 1fr; border: round $accent; padding: 0 1; }
    #status { height: 1; background: $boost; color: $text; padding: 0 1; }
    """

    BINDINGS = [
        Binding("space", "talk", "talk/stop", priority=True),
        Binding("l", "listen", "hear you"),
        Binding("f", "far", "hear them"),
        Binding("a", "approve", "approve them"),
        Binding("i", "interrupt", "interrupt", priority=True),
        Binding("m", "mute", "mute"),
        Binding("c", "commands", "commands"),
        Binding("q", "quit", "quit", priority=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.events: queue.Queue = queue.Queue()
        self.stt = default_stt()
        self.tts = default_tts()
        self.brain = Brain()
        self.mic = default_endpoint()
        self.conductor = Conductor(
            self.stt, self.brain, self.tts, self.mic,
            emit=self.events.put, pick=filler_picker(),
        )
        self._note = ""
        self._stream: StreamingTranscriber | None = None      # you (operator mic)
        self._far_stream: StreamingTranscriber | None = None  # the respondent
        self._approved = False                                # act on their commands?
        self._log: RichLog | None = None                      # cached in on_mount
        self._logf, self._logpath = _open_log()               # plain-text session log

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield RichLog(id="log", markup=True, wrap=True)
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
        cmd = address(text)
        if cmd is None:
            self._w(f"[dim]· {text}[/]")  # overheard, not for Iris
            return
        self._w(f"[bold]you[/] → iris: {text}")
        if not cmd:
            self._w('[dim](yes? — say "Iris, <command>")[/]')
        elif _STOP.match(cmd):
            self.conductor.interrupt()  # cut her off now; no spoken reply
            self._w("[yellow](stopped)[/]")
            self._refresh_status()
        elif _GRANT.match(cmd) and speaker == "operator":
            self.conductor.grant_far()
            self._w("[green]far party granted FULL access for this call[/]")
            self._refresh_status()
        elif not self._dispatch(cmd, speaker):
            self._w("[dim](busy — one sec)[/]")

    def _on_heard_far_main(self, text: str, speaker: str = "") -> None:
        """A streamed utterance from the RESPONDENT: act only if approved."""
        cmd = address(text)
        if cmd is None:
            self._w(f"[dim]them: {text}[/]")  # respondent, not addressing Iris
            return
        self._w(f"[magenta]them[/] → iris: {text}")
        if not cmd:
            return
        if not self._approved:
            self._w("[dim](respondent's command — not approved; press 'a' to allow)[/]")
        elif not self._dispatch(cmd, speaker):
            self._w("[dim](busy — one sec)[/]")

    def _refresh_status(self) -> None:
        c = self.conductor
        parts = [c.state.value.upper()]
        if c.muted:
            parts.append("[b]MUTED[/]")
        if self._stream is not None:
            parts.append("[b]HEAR-YOU[/]")
        if self._far_stream is not None:
            parts.append("[b]HEAR-THEM[/]")
        if self._approved:
            parts.append("[b green]THEM-APPROVED[/]")
        if self._far_stream is not None and c.far_trust is TrustMode.FULL:
            parts.append("[b green]FAR-FULL[/]")
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
        stream = StreamingTranscriber(self._on_heard, label="operator")
        if not stream.available():
            self._w("[red]STT not set up — run:  bash scripts/setup_whisper.sh[/]")
            return
        self._stream = stream
        stream.start()
        self._w('[green]hearing you — just talk; say "Iris, …" to address her[/]')
        self._refresh_status()

    def action_far(self) -> None:
        if self._far_stream is not None:
            self._far_stream.stop()
            self._far_stream = None
            self.conductor.reset_far_trust()  # hangup/disconnect resets to DEMO
            self._w("[yellow]no longer hearing the respondent[/]")
            self._refresh_status()
            return
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

    def action_approve(self) -> None:
        self._approved = not self._approved
        if self._approved:
            self._w("[green]respondent's commands APPROVED — Iris will act on their \"Iris, …\"[/]")
        else:
            self._w("[yellow]respondent's commands blocked[/]")
        self._refresh_status()

    def _on_heard(self, text: str, label: str) -> None:
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
