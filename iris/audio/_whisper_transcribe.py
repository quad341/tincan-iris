"""Standalone faster-whisper transcriber — runs INSIDE the 3.12 whisper venv.

Kept out of the importable ``iris`` package on purpose: it needs faster-whisper +
ctranslate2, which live only in the dedicated 3.12 venv (the box's system Python
is 3.14, with no wheels). ``FasterWhisperSTT`` in ``stt.py`` shells this script —
and wraps it in ``unshare -rn`` so the third-party model runs with no network
(the model is pre-downloaded by scripts/setup_whisper.sh; download != execute,
see the sandbox-inference memory).

    python _whisper_transcribe.py --model models/whisper/small.en --wav in.wav
"""
from __future__ import annotations

import argparse
import os

# Belt-and-suspenders with ``unshare -rn``: never reach for the network. The
# model is already on disk, so load it locally and don't phone HuggingFace home.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="faster-whisper WAV -> text (run in the whisper venv)"
    )
    ap.add_argument("--model", required=True, help="path to a CTranslate2 model dir")
    ap.add_argument("--wav", required=True)
    ap.add_argument("--compute-type", default="int8")
    ap.add_argument("--language", default="en")
    ap.add_argument("--beam-size", type=int, default=5)
    args = ap.parse_args()

    from faster_whisper import WhisperModel

    model = WhisperModel(args.model, device="cpu", compute_type=args.compute_type)
    segments, _info = model.transcribe(
        args.wav, language=args.language, beam_size=args.beam_size
    )
    # segments is a generator; realizing it is what actually runs inference.
    print("".join(seg.text for seg in segments).strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
