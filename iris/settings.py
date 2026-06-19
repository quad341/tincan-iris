"""Single source for Iris's launch knobs: environment over a TOML config file.

Launching Iris historically meant exporting a pile of ``IRIS_*`` env vars (audio
routing, model assets, voice, …). Those knobs now also load from a config file
so you can set them once and launch clean (``python -m iris.console``).

Everything lives under one root, ``IRIS_HOME`` (default ``~/.local/share/iris``
— where the db/transcripts/memories already live). Set it once in your shell, or
rely on the default. The config file is ``$IRIS_HOME/config.toml`` (override the
file alone with ``IRIS_CONFIG``).

Precedence, highest first:

  1. an explicit ``IRIS_*`` environment variable (per-launch override)
  2. ``config.toml`` (set once, your machine's defaults)
  3. the caller's built-in default

Read every ``IRIS_*`` knob through :func:`get` / :func:`get_bool` so all three
layers apply. ``config.toml`` keys are ``[section].key`` and map to ``IRIS_*``
names via :data:`_KEYMAP`; add a row there to make a new knob file-configurable.
"""
from __future__ import annotations

import os
import tomllib
from functools import lru_cache
from pathlib import Path

_TRUE = ("1", "true", "yes", "on")


def iris_home() -> Path:
    """The single umbrella root for Iris config + data + assets.

    ``IRIS_HOME`` overrides everything; else XDG (``$XDG_DATA_HOME/iris``,
    default ``~/.local/share/iris``).
    """
    override = os.environ.get("IRIS_HOME")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / "iris"


def config_path() -> Path:
    """Location of config.toml: ``IRIS_CONFIG`` if set, else ``$IRIS_HOME/config.toml``."""
    override = os.environ.get("IRIS_CONFIG")
    return Path(override).expanduser() if override else iris_home() / "config.toml"


# config.toml ``[section].key`` -> ``IRIS_*`` environment name. Add a row here to
# make a knob file-configurable. Secrets (e.g. IRIS_EMAIL_PASSWORD) are
# deliberately ABSENT — they stay environment-only and never live in this file
# (see config.py).
_KEYMAP: dict[tuple[str, str], str] = {
    ("audio", "mode"):             "IRIS_AUDIO",
    ("audio", "aec"):              "IRIS_AEC",
    ("audio", "playback_target"):  "IRIS_PLAYBACK_TARGET",
    ("audio", "capture_target"):   "IRIS_CAPTURE_TARGET",
    ("audio", "playback_device"):  "IRIS_PLAYBACK_DEVICE",
    ("audio", "capture_device"):   "IRIS_CAPTURE_DEVICE",
    ("audio", "va_aec"):           "IRIS_VA_AEC",
    ("audio", "sco_sink"):         "IRIS_SCO_SINK",
    ("audio", "sco_source"):       "IRIS_SCO_SOURCE",
    ("assets", "home"):            "IRIS_ASSET_HOME",
    ("assets", "whisper_dir"):     "IRIS_WHISPER_DIR",
    ("assets", "whisper_python"):  "IRIS_WHISPER_PYTHON",
    ("assets", "whisper_model_size"): "IRIS_WHISPER_MODEL_SIZE",
    ("assets", "kokoro_dir"):      "IRIS_KOKORO_DIR",
    ("assets", "kokoro_python"):   "IRIS_KOKORO_PYTHON",
    ("voice", "kokoro_voice"):     "IRIS_KOKORO_VOICE",
    # Email lane (NEVER the password — secrets stay environment-only):
    ("email", "imap_host"):        "IRIS_EMAIL_IMAP_HOST",
    ("email", "imap_port"):        "IRIS_EMAIL_IMAP_PORT",
    ("email", "smtp_host"):        "IRIS_EMAIL_SMTP_HOST",
    ("email", "smtp_port"):        "IRIS_EMAIL_SMTP_PORT",
    ("email", "user"):             "IRIS_EMAIL_USER",
    # Screening / take-message capture windows (seconds):
    ("screening", "intro_s"):          "IRIS_SC_INTRO_S",
    ("screening", "retry_s"):          "IRIS_SC_RETRY_S",
    ("screening", "relay_timeout_s"):  "IRIS_SC_RELAY_TIMEOUT_S",
    ("screening", "pivot_s"):          "IRIS_SC_PIVOT_S",
    ("take_message", "name_s"):        "IRIS_TM_NAME_S",
    ("take_message", "msg_s"):         "IRIS_TM_MSG_S",
    ("take_message", "add_s"):         "IRIS_TM_ADD_S",
    # Local server URLs + console log:
    ("servers", "stt_url"):        "IRIS_STT_SERVER_URL",
    ("servers", "tts_url"):        "IRIS_TTS_SERVER_URL",
    ("storage", "log_file"):       "IRIS_LOG_FILE",
}


def _stringify(value: object) -> str:
    """Render a TOML scalar the way the env layer expects (bools -> 1/0)."""
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


@lru_cache(maxsize=1)
def _file_values() -> dict[str, str]:
    """``IRIS_*`` values sourced from config.toml (empty if absent/unreadable).

    Cached: the file is read once per process. Tests that write a config file
    should call :func:`reload` afterwards.
    """
    path = config_path()
    try:
        data = tomllib.loads(path.read_text())
    except (FileNotFoundError, IsADirectoryError, OSError, tomllib.TOMLDecodeError):
        return {}
    values: dict[str, str] = {}
    for (section, key), env_name in _KEYMAP.items():
        sec = data.get(section)
        if isinstance(sec, dict) and key in sec:
            values[env_name] = _stringify(sec[key])
    return values


def reload() -> None:
    """Drop the cached config.toml read (call after the file changes; tests)."""
    _file_values.cache_clear()


def get(name: str, default: str | None = None) -> str | None:
    """Resolve an ``IRIS_*`` knob: environment → config.toml → ``default``."""
    if name in os.environ:
        return os.environ[name]
    file_values = _file_values()
    if name in file_values:
        return file_values[name]
    return default


def get_bool(name: str, default: bool = False) -> bool:
    """:func:`get` coerced to bool (``1/true/yes/on`` are true; empty is false)."""
    raw = get(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE


def get_int(name: str, default: int) -> int:
    """:func:`get` coerced to int; ``default`` on unset/empty/unparseable."""
    raw = get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def get_float(name: str, default: float) -> float:
    """:func:`get` coerced to float; ``default`` on unset/empty/unparseable."""
    raw = get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default
