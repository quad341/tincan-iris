"""Voice mode — Iris speaks her replies aloud.

For now: text in (you type), voice out (TTS -> speaker), with the latency filler
spoken too ("umm, one sec") when a lane is slow. The mic side (STT) lands with
whisper.cpp; this is the half that's testable today on any box with espeak-ng.

    python -m iris.voice        # or, once installed:  iris-speak
"""
from __future__ import annotations

import sys

from .audio.endpoint import AudioEndpoint, LocalAudio
from .audio.tts import TTS, EspeakTTS
from .brain import Brain


class Voice:
    """Wires the brain to a TTS provider and an audio endpoint."""

    def __init__(
        self,
        brain: Brain | None = None,
        tts: TTS | None = None,
        endpoint: AudioEndpoint | None = None,
    ) -> None:
        self.brain = brain or Brain()
        self.tts = tts or EspeakTTS()
        self.endpoint = endpoint or LocalAudio()

    def speak(self, text: str) -> None:
        self.endpoint.playback(self.tts.synth(text))

    def say_reply(self, user_text: str):
        # the masking filler becomes an audible "umm" on slow lanes
        reply = self.brain.respond(user_text, on_filler=lambda: self.speak("umm, one sec"))
        self.speak(reply.text)
        return reply

    def close(self) -> None:
        self.brain.close()


def main() -> int:
    v = Voice()
    print("Iris voice mode — type a message; Iris speaks the reply (Ctrl-D to quit).")
    print(f"(TTS: {v.tts.name} · out: {v.endpoint.name} · I'm an AI.)\n")
    try:
        while True:
            try:
                text = input("you › ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nbye!")
                return 0
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
