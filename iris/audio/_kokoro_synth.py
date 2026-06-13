"""Standalone Kokoro synthesizer — runs INSIDE the 3.12 Kokoro venv.

Kept out of the importable ``iris`` package on purpose: it needs kokoro-onnx +
onnxruntime + soundfile, which live only in the dedicated 3.12 venv (the box's
system Python is 3.14, with no onnxruntime wheels). ``KokoroTTS`` in ``tts.py``
shells this script — and wraps it in ``unshare -rn`` so it runs with no network.

    python _kokoro_synth.py --model M.onnx --voices V.bin \
        --voice af_heart --text-file in.txt --out out.wav
"""
from __future__ import annotations

import argparse


def main() -> int:
    ap = argparse.ArgumentParser(description="Kokoro text -> WAV (run in the Kokoro venv)")
    ap.add_argument("--model", required=True)
    ap.add_argument("--voices", required=True)
    ap.add_argument("--voice", default="af_heart")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--lang", default="en-us")
    ap.add_argument("--text-file", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(args.text_file, encoding="utf-8") as fh:
        text = fh.read().strip()

    import soundfile as sf
    from kokoro_onnx import Kokoro

    kokoro = Kokoro(args.model, args.voices)
    samples, sample_rate = kokoro.create(
        text, voice=args.voice, speed=args.speed, lang=args.lang
    )
    sf.write(args.out, samples, sample_rate)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
