"""Standalone streaming transcriber — runs INSIDE the 3.12 whisper venv.

Reads raw s16le 16 kHz mono audio from stdin (piped from a continuous recorder),
uses webrtcvad to find utterance boundaries (so you can pause mid-sentence), and
transcribes each finished utterance with faster-whisper — the model loaded ONCE,
so there's no per-turn reload tax. Emits one JSON line per event:
  {"ready": true}        once the model is warm
  {"text": "..."}        a finished utterance

webrtcvad is tiny and works directly on the s16 frames (no resample, no torch).
Kept out of the importable iris package (needs faster-whisper + webrtcvad, the
3.12 venv). The main process pipes a recorder in and runs this under unshare -rn
(the model is local; no network).

    parecord --raw --rate=16000 --channels=1 --format=s16le \
        | python _whisper_stream.py --model models/whisper/small.en
"""
from __future__ import annotations

import argparse
import json
import os
import sys

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

_RATE = 16000
_FRAME_MS = 30
_FRAME_BYTES = int(_RATE * _FRAME_MS / 1000) * 2  # 960 bytes = 480 s16 samples
_START_FRAMES = 2   # consecutive voiced frames to start an utterance (~60 ms)
_PREROLL = 8        # frames (~240 ms) kept before start so onsets aren't clipped


def _read_exactly(stream, nbytes: int) -> bytes:
    buf = b""
    while len(buf) < nbytes:
        part = stream.read(nbytes - len(buf))
        if not part:
            return buf  # EOF
        buf += part
    return buf


def main() -> int:
    ap = argparse.ArgumentParser(description="streaming VAD + faster-whisper (venv)")
    ap.add_argument("--model", required=True, help="CTranslate2 model dir")
    ap.add_argument("--compute-type", default="int8")
    ap.add_argument("--language", default="en")
    ap.add_argument("--beam-size", type=int, default=1)
    ap.add_argument("--aggressiveness", type=int, default=2, help="webrtcvad 0-3")
    ap.add_argument("--min-silence-ms", type=int, default=800,
                    help="silence that ends an utterance (your pause tolerance)")
    args = ap.parse_args()

    import numpy as np
    import webrtcvad
    from faster_whisper import WhisperModel

    model = WhisperModel(args.model, device="cpu", compute_type=args.compute_type)
    vad = webrtcvad.Vad(args.aggressiveness)
    end_frames = max(1, args.min_silence_ms // _FRAME_MS)

    def transcribe(pcm: bytes) -> None:
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _info = model.transcribe(
            audio, language=args.language, beam_size=args.beam_size
        )
        text = "".join(s.text for s in segments).strip()
        if text:
            print(json.dumps({"text": text}), flush=True)

    stdin = sys.stdin.buffer
    preroll: list = []
    utt = bytearray()
    speaking = False
    voiced = silence = 0
    print(json.dumps({"ready": True}), flush=True)

    while True:
        frame = _read_exactly(stdin, _FRAME_BYTES)
        if len(frame) < _FRAME_BYTES:
            break  # EOF
        is_speech = vad.is_speech(frame, _RATE)
        if not speaking:
            preroll.append(frame)
            if len(preroll) > _PREROLL:
                preroll.pop(0)
            voiced = voiced + 1 if is_speech else 0
            if voiced >= _START_FRAMES:
                speaking, silence = True, 0
                utt = bytearray(b"".join(preroll))
                preroll = []
        else:
            utt += frame
            if is_speech:
                silence = 0
            else:
                silence += 1
                if silence >= end_frames:
                    transcribe(bytes(utt))
                    speaking = False
                    utt, voiced, silence = bytearray(), 0, 0

    if speaking and utt:
        transcribe(bytes(utt))  # flush a trailing utterance at EOF
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
