"""Presentation profile data model and four-step resolution chain (ti-6371).

ProfileResolver locks a PresentationProfile for the call at end of utterance-1.
No mid-call language swaps; slow-mode cadence is a per-turn exception only.
ADR-0005: trust is never touched here.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PresentationProfile:
    """Resolved TTS presentation parameters for a single call."""

    language: str          # BCP-47 tag, e.g. 'en', 'es', 'ja'
    tts_voice: str         # Kokoro voice_id (e.g. 'ef_dalia'); empty = espeak
    tts_lang: str          # Kokoro lang hint; BCP-47 tag when using espeak
    cadence: float = 1.0   # speed multiplier (1.0 = normal)
    source: str = "default"  # 'override' | 'annotation' | 'detector' | 'default'


class ProfileResolver:
    """Resolves the presentation profile for a call via a four-step chain.

    Priority order (first hit wins):
      ① override_key  — runtime key injected by operator tooling
      ② annotation    — PreferencesStore lang/cadence for the contact
      ③ detector      — single-utterance Whisper confidence
      ④ default       — config.default_language

    The resolved profile is locked for the call lifetime (no mid-call swaps).
    Cadence slow-mode (re_ask) is a per-turn exception, not a profile mutation.
    """

    def __init__(
        self,
        config: Any,
        prefs: Any,
        voice_lookup: Callable[[str], Any],
        detector: Callable[[str], dict[str, float]],
    ) -> None:
        self._config = config
        self._prefs = prefs
        self._voice_lookup = voice_lookup
        self._detector = detector

    def _build(self, language: str, source: str, cadence: float | None = None) -> PresentationProfile:
        entry = self._voice_lookup(language)
        tts_voice = getattr(entry, 'voice_id', '')
        if not isinstance(tts_voice, str):
            tts_voice = ''
        return PresentationProfile(
            language=language,
            tts_voice=tts_voice,
            tts_lang=language,
            cadence=cadence if cadence is not None else self._config.cadence_default,
            source=source,
        )

    def resolve(
        self,
        override_key: str | None = None,
        contact_id: str | None = None,
        utterance: str | None = None,
    ) -> PresentationProfile:
        """Run the chain; return a locked PresentationProfile."""
        language_set: list[str] = list(self._config.language_set)

        # ① override key
        if override_key is not None:
            return self._build(override_key, "override")

        # ② contact annotation
        if contact_id is not None:
            ann_lang = self._prefs.get(contact_id, "lang", "")
            if ann_lang and ann_lang in language_set:
                ann_cadence_raw = self._prefs.get(contact_id, "cadence", "")
                ann_cadence: float | None = None
                if ann_cadence_raw:
                    try:
                        ann_cadence = float(ann_cadence_raw)
                    except ValueError:
                        pass
                return self._build(ann_lang, "annotation", ann_cadence)

        # ③ Whisper detector
        if utterance is not None:
            confidences = self._detector(utterance)
            threshold: float = self._config.language_detect_threshold
            for lang in language_set:
                if confidences.get(lang, 0.0) >= threshold:
                    return self._build(lang, "detector")

        # ④ default
        return self._build(self._config.default_language, "default")

    def turn_cadence(self, profile: PresentationProfile, *, re_ask: bool) -> float:
        """Return effective cadence for this turn; does not mutate the profile."""
        if re_ask:
            return self._config.cadence_slow
        return profile.cadence
