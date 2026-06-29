"""Disclosure WAV generation — rendered once at daemon start, cached on disk.

The file is pre-rendered at startup so auto-answer flows can play it within
500ms of picking up (ADR-0004). If the operator name changes in config, the
cached WAV is regenerated automatically.

Script template:
    "Hi, I'm Iris, an AI assistant. I'll let [Name] know you're calling."
    (or the generic variant when no operator_name is configured)

Sidecar file `<wav_path>.name` holds the operator name that was used to
render the current WAV; on mismatch the WAV is re-rendered.
"""
from __future__ import annotations

import logging
from pathlib import Path

from .audio.tts import TTS, default_tts

logger = logging.getLogger(__name__)

_DEFAULT_WAV_PATH = Path.home() / ".local" / "share" / "iris" / "disclosure.wav"

_SCRIPT_PERSONAL = (
    "Hi, I'm Iris, an AI assistant. I'll let {name} know you're calling."
)
_SCRIPT_GENERIC = (
    "Hi, I'm Iris, an AI assistant. I'll let the person you're calling know "
    "you're calling."
)


def _disclosure_script(operator_name: str) -> str:
    name = operator_name.strip()
    if name:
        return _SCRIPT_PERSONAL.format(name=name)
    return _SCRIPT_GENERIC


def _sidecar_path(wav_path: Path) -> Path:
    return wav_path.with_suffix(".wav.name")


def _cached_name(wav_path: Path) -> str:
    """Return the operator name recorded in the sidecar, or '' if absent."""
    sidecar = _sidecar_path(wav_path)
    try:
        return sidecar.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _write_sidecar(wav_path: Path, name: str) -> None:
    _sidecar_path(wav_path).write_text(name.strip(), encoding="utf-8")


def ensure_disclosure_wav(
    operator_name: str = "",
    wav_path: Path | str | None = None,
    tts: TTS | None = None,
) -> Path:
    """Ensure a disclosure WAV exists at *wav_path* and is current.

    Re-renders if the WAV is missing or the operator name changed.
    Returns the path to the WAV file.
    """
    out = Path(wav_path) if wav_path else _DEFAULT_WAV_PATH
    tts = tts or default_tts()

    need_render = not out.exists() or _cached_name(out) != operator_name.strip()
    if not need_render:
        logger.debug("disclosure WAV up to date: %s", out)
        return out

    script = _disclosure_script(operator_name)
    logger.info("rendering disclosure WAV (%s): %s", out, script[:60])

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = tts.synth(script)

    # Atomic replace so a half-written file is never used for auto-answer.
    tmp_path = Path(tmp)
    tmp_path.replace(out)
    _write_sidecar(out, operator_name)

    logger.info("disclosure WAV ready: %s", out)
    return out
