"""Voice catalogue for multilingual TTS (ADR ti-joq2).

Maps BCP-47 language tags to Kokoro voice IDs and espeak fallback voices.
Operator overrides loaded from [voice.catalogue] in config.toml.
Importable without pipecat or kokoro installed.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class VoiceEntry:
    kokoro_lang: str
    voice_id: str     # Kokoro voice ID (e.g. 'ef_dalia'); empty = use espeak
    espeak_voice: str


DEFAULT_CATALOGUE: dict[str, VoiceEntry] = {
    "en":    VoiceEntry(kokoro_lang="en-us", voice_id="af_heart",  espeak_voice="en"),
    "en-us": VoiceEntry(kokoro_lang="en-us", voice_id="af_heart",  espeak_voice="en"),
    "en-gb": VoiceEntry(kokoro_lang="en-gb", voice_id="bf_emma",   espeak_voice="en-gb"),
    "ja":    VoiceEntry(kokoro_lang="ja",    voice_id="jf_alpha",  espeak_voice="ja"),
    "ko":    VoiceEntry(kokoro_lang="ko",    voice_id="kf_bella",  espeak_voice="ko"),
    "zh":    VoiceEntry(kokoro_lang="zh",    voice_id="zf_xiaobei",espeak_voice="zh"),
    "fr":    VoiceEntry(kokoro_lang="fr-fr", voice_id="ff_siwis",  espeak_voice="fr"),
    "pt":    VoiceEntry(kokoro_lang="pt-br", voice_id="pf_dora",   espeak_voice="pt"),
    "hi":    VoiceEntry(kokoro_lang="hi",    voice_id="hf_alpha",  espeak_voice="hi"),
    "it":    VoiceEntry(kokoro_lang="it",    voice_id="if_sara",   espeak_voice="it"),
    "es":    VoiceEntry(kokoro_lang="es",    voice_id="ef_dalia",  espeak_voice="es"),
}


def _load_toml_overrides() -> dict[str, VoiceEntry]:
    """Read [voice.catalogue] from config.toml if present."""
    config_path = Path("config.toml")
    if not config_path.exists():
        return {}
    try:
        import tomllib
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
    except Exception:
        return {}
    section: dict[str, Any] = data.get("voice", {}).get("catalogue", {})
    result: dict[str, VoiceEntry] = {}
    for lang, entry in section.items():
        if isinstance(entry, dict):
            result[lang] = VoiceEntry(
                kokoro_lang=entry.get("kokoro_lang", lang),
                voice_id=entry.get("voice_id", ""),
                espeak_voice=entry.get("espeak_voice", lang),
            )
    return result


def voice_for_lang(
    lang: str,
    overrides: dict[str, VoiceEntry] | None = None,
) -> VoiceEntry:
    """Return the VoiceEntry for a BCP-47 language tag.

    Priority: overrides > exact catalogue match > base-tag strip > espeak fallback.
    The caller may pass `overrides` from [voice.catalogue] in config.toml, or
    leave it as None to auto-load from disk on each call.
    """
    if overrides is None:
        overrides = _load_toml_overrides()

    normalized = lang.lower()

    # 1. operator override (exact match)
    if normalized in overrides:
        return overrides[normalized]

    # 2. exact match in default catalogue
    if normalized in DEFAULT_CATALOGUE:
        return DEFAULT_CATALOGUE[normalized]

    # 3. base-tag strip (e.g. 'es-MX' -> 'es')
    base = normalized.split("-")[0]
    if base in overrides:
        return overrides[base]
    if base in DEFAULT_CATALOGUE:
        return DEFAULT_CATALOGUE[base]

    # 4. espeak fallback
    return VoiceEntry(kokoro_lang=base, voice_id="", espeak_voice=base)
