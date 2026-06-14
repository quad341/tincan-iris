#!/usr/bin/env bash
# Provision the faster-whisper STT runtime for Iris's ears.
#
# Why a separate venv: faster-whisper needs ctranslate2, which has no wheels for
# this box's Python 3.14 — so it lives in a dedicated 3.12 venv that
# `iris.audio.stt.FasterWhisperSTT` shells out to. Inference runs network-
# isolated (`unshare -rn`); this step only *downloads* the model (download !=
# execute; see the sandbox-inference memory).
#
# Re-runnable. Model size via IRIS_WHISPER_MODEL_SIZE (default small.en).
# After it finishes: `python -m iris.listen` can hear you (needs a llama-server).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv-whisper"
SIZE="${IRIS_WHISPER_MODEL_SIZE:-small.en}"
MODELS="$ROOT/models/whisper/$SIZE"

echo "==> Creating 3.12 venv at $VENV"
uv venv --python 3.12 "$VENV"

echo "==> Installing faster-whisper"
uv pip install --python "$VENV/bin/python" faster-whisper

echo "==> Downloading whisper model '$SIZE' to $MODELS"
mkdir -p "$MODELS"
"$VENV/bin/python" - "$SIZE" "$MODELS" <<'PY'
import sys
from faster_whisper import download_model
size, out = sys.argv[1], sys.argv[2]
download_model(size, output_dir=out)
print("downloaded", size, "->", out)
PY

echo "==> Whisper ready. Try:  python -m iris.listen"
