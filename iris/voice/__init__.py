"""Voice mode — Iris speaks her replies aloud.

For now: text in (you type), voice out (TTS -> speaker). While a lane lags she
speaks randomized fillers ("let me think" / "hang on" / ...); Ctrl-C stops her
instantly; and if a lane blows the deadline she speaks a graceful fallback
instead of dead air. The mic side (STT) lands with whisper.cpp.

    python -m iris.voice        # or, once installed:  iris-speak
"""
from __future__ import annotations

import sys

from ..audio.endpoint import AudioEndpoint, LocalAudio
from ..audio.tts import TTS, default_tts
from ..brain import Brain
from ..fillers import filler_picker


class Voice:
    """Wires the brain to a TTS provider and an audio endpoint."""

    def __init__(
        self,
        brain: Brain | None = None,
        tts: TTS | None = None,
        endpoint: AudioEndpoint | None = None,
    ) -> None:
        self.brain = brain or Brain()
        self.tts = tts or default_tts()
        self.endpoint = endpoint or LocalAudio()
        self._pick = filler_picker()

    def speak(self, text: str) -> None:
        self.endpoint.playback(self.tts.synth(text))

    def say_reply(self, user_text: str):
        # randomized spoken fillers while a lane lags; Ctrl-C stops it
        reply = self.brain.respond(user_text, on_filler=lambda i: self.speak(self._pick()))
        self.speak(reply.text)
        return reply

    def close(self) -> None:
        self.brain.close()


def main() -> int:
    v = Voice()
    print("Iris voice mode — type a message; Iris speaks the reply.")
    print("Try: " + " · ".join(v.brain.tier0.examples()[:5]) + ' · or "what can you do".')
    print("(Ctrl-C stops her mid-thought · Ctrl-D quits · I'm an AI.)\n")
    try:
        while True:
            try:
                text = input("you › ").strip()
            except EOFError:
                print("\nbye!")
                return 0
            except KeyboardInterrupt:
                print()  # Ctrl-C at the prompt: fresh line, keep going
                continue
            if not text:
                continue
            try:
                reply = v.say_reply(text)
            except Exception as exc:  # noqa: BLE001 — surface, keep the loop alive
                print(f"iris ✗ {type(exc).__name__}: {exc}\n")
                continue
            tag = reply.lane + (f"/{reply.skill}" if reply.skill else "")
            print(f"iris › {reply.text}")
            print(f"      ⟮{tag} · {reply.timeline.summary()}⟯\n")
    finally:
        v.close()


if __name__ == "__main__":
    sys.exit(main())
