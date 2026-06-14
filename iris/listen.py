"""Local voice loop — talk to Iris with your own mic (no tincan, no phone).

The standalone test harness: judge Iris's STT accuracy, brain quality, and
end-to-end latency in isolation before the tincan-SCO call routing exists. Here
every utterance is obviously meant for her, so there's no wake-word/addressing
(that lands with the always-on/call phase — see the supervised-co-pilot memory).

Push-to-talk: press Enter to start talking, Enter again to stop. Iris transcribes,
thinks, and speaks the reply; the transcript + per-turn latency print so you can
judge both. Ctrl-C quits.

    python -m iris.listen        # needs scripts/setup_whisper.sh + a llama-server
"""
from __future__ import annotations

import sys
import time

from .audio.endpoint import LocalAudio
from .audio.stt import default_stt
from .audio.tts import default_tts
from .brain import Brain
from .fillers import filler_picker


def main() -> int:
    stt = default_stt()
    if not stt.available():
        print("STT isn't set up yet — run:  bash scripts/setup_whisper.sh")
        return 1

    brain = Brain()
    tts = default_tts()
    mic = LocalAudio()
    pick = filler_picker()

    def speak(text: str) -> None:
        mic.playback(tts.synth(text))

    print(f"Iris local voice — STT: {stt.name} · TTS: {tts.name}")
    print("Enter to talk, Enter to stop · Ctrl-C quits · (I'm an AI.)\n")
    try:
        while True:
            try:
                input("[Enter] to talk › ")
            except EOFError:
                break
            rec = mic.start_capture()
            try:
                input("  …recording — [Enter] to stop › ")
            except EOFError:
                pass
            t0 = time.monotonic()
            wav = rec.stop()
            try:
                text = stt.transcribe(wav)
            except Exception as exc:  # noqa: BLE001 — surface, keep the loop alive
                print(f"  stt ✗ {type(exc).__name__}: {exc}\n")
                continue
            t_stt = (time.monotonic() - t0) * 1000
            if not text:
                print("  (heard nothing)\n")
                continue
            print(f"  you said: {text!r}  ⟮stt {t_stt:.0f}ms⟯")
            try:
                reply = brain.respond(text, on_filler=lambda i: speak(pick()))
            except Exception as exc:  # noqa: BLE001 — surface, keep the loop alive
                print(f"  iris ✗ {type(exc).__name__}: {exc}\n")
                continue
            speak(reply.text)
            tag = reply.lane + (f"/{reply.skill}" if reply.skill else "")
            print(f"  iris › {reply.text}")
            print(f"        ⟮{tag} · {reply.timeline.summary()}⟯\n")
    except KeyboardInterrupt:
        print("\nbye!")
    finally:
        brain.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
