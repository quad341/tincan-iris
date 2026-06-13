#!/usr/bin/env bash
# Provision the Kokoro TTS runtime for Iris's natural voice.
#
# Why a separate venv: Kokoro ships as ONNX and needs onnxruntime, which has no
# wheels for this box's Python 3.14 — so it lives in a dedicated 3.12 venv that
# `iris.audio.tts.KokoroTTS` shells out to. Inference itself runs network-
# isolated (`unshare -rn`); this step only *downloads* (download != execute).
#
# Re-runnable. After it finishes: `python -m iris.voice` uses Kokoro by default
# (falls back to espeak-ng automatically if this setup hasn't been run).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv-kokoro"
MODELS="$ROOT/models/kokoro"
BASE="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"

echo "==> Creating 3.12 venv at $VENV"
uv venv --python 3.12 "$VENV"

echo "==> Installing kokoro-onnx + onnxruntime + soundfile"
uv pip install --python "$VENV/bin/python" kokoro-onnx onnxruntime soundfile

echo "==> Downloading kokoro-82M model + voices to $MODELS"
mkdir -p "$MODELS"
curl -L --fail -o "$MODELS/kokoro-v1.0.onnx" "$BASE/kokoro-v1.0.onnx"
curl -L --fail -o "$MODELS/voices-v1.0.bin"  "$BASE/voices-v1.0.bin"

echo "==> Kokoro ready. Try:  python -m iris.voice"
