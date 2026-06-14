"""Textual operator console for Iris — the local 'admin app'.

Live transcription, per-turn tier + latency, a hard interrupt (barge-in), and a
mute toggle, over the standalone local voice loop (Iris in isolation). It drives
the UI-agnostic ``Conductor`` and renders the events it posts to a thread-safe
queue; the blocking pipeline runs in a Textual thread-worker so the UI stays
responsive (and the interrupt key always lands).

    python -m iris.console      # needs scripts/setup_whisper.sh + a llama-server

Keys:  [space] talk/stop · [i] interrupt (barge-in) · [m] mute · [q] quit

The supervised-call controls (who-hears-what, addressing) layer on with the
tincan-SCO endpoint — this is Iris in isolation.
"""
from __future__ import annotations

import queue

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, RichLog, Static

from ..audio.endpoint import default_endpoint
from ..audio.stt import default_stt
from ..audio.tts import default_tts
from ..brain import Brain
from ..fillers import filler_picker
from .conductor import Conductor, State


class IrisConsole(App):
    TITLE = "Iris console"

    CSS = """
    #log { height: 1fr; border: round $accent; padding: 0 1; }
    #status { height: 1; background: $boost; color: $text; padding: 0 1; }
    """

    BINDINGS = [
        Binding("space", "talk", "talk/stop", priority=True),
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

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield RichLog(id="log", markup=True, wrap=True)
        yield Static(id="status")
        yield Footer()

    def on_mount(self) -> None:
        log = self.query_one("#log", RichLog)
        log.can_focus = False  # so [space] is the talk key, not log-scroll
        log.write(f"[dim]STT: {self.stt.name} · TTS: {self.tts.name} · (I'm an AI.)[/]")
        if not self.stt.available():
            log.write("[red]STT not set up — run:  bash scripts/setup_whisper.sh[/]")
        self.set_interval(0.05, self._drain)
        self._refresh_status()

    def _drain(self) -> None:
        """Pump conductor events (posted from the worker thread) into the UI."""
        log = self.query_one("#log", RichLog)
        try:
            while True:
                ev = self.events.get_nowait()
                kind = ev[0]
                if kind == "transcript":
                    text, ms = ev[1], ev[2]
                    log.write(
                        f"[bold]you[/]  › {text or '(heard nothing)'}"
                        f"  [dim]⟮stt {ms:.0f}ms⟯[/]"
                    )
                elif kind == "reply":
                    log.write(f"[bold cyan]iris[/] › {ev[1]}")
                    log.write(f"        [dim]⟮{ev[2]} · {ev[3]}⟯[/]")
                elif kind == "error":
                    log.write(f"[red]✗ {ev[1]}[/]")
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

    def _refresh_status(self) -> None:
        c = self.conductor
        state = c.state.value.upper()
        mute = "  ·  [b]MUTED[/]" if c.muted else ""
        note = f"  ·  {self._note}" if self._note else ""
        self.query_one("#status", Static).update(f" {state}{mute}{note}")

    def action_talk(self) -> None:
        c = self.conductor
        if c.state is State.IDLE:
            c.start_recording()
            self._refresh_status()
        elif c.state is State.RECORDING:
            self.run_worker(c.stop_and_respond, thread=True, exclusive=True)

    def action_interrupt(self) -> None:
        self.conductor.interrupt()
        self._refresh_status()

    def action_mute(self) -> None:
        self.conductor.toggle_mute()
        self._refresh_status()

    def action_commands(self) -> None:
        """Dump the well-defined Tier-0 commands — what Iris handles instantly."""
        log = self.query_one("#log", RichLog)
        log.write("[b]Known commands[/] [dim](Tier-0 — instant, no model)[/]")
        for name, example in self.brain.tier0.commands():
            log.write(f'  [cyan]{name:<10}[/] [dim]e.g.[/] "{example}"')
        log.write('[dim]Anything else → local model · "ask Haiku about …" → cloud[/]')

    def on_unmount(self) -> None:
        self.conductor.interrupt()
        self.conductor.close()


def main() -> int:
    IrisConsole().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
