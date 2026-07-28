"""Unit tests for ProfileResolver chain steps, lock semantics, and config model.

Bead: ti-uzfq (validator phase) — written BEFORE builder implementation (TDD red phase).
Fails until builder implements:
  - iris/profile_resolver.py  (ProfileResolver, PresentationProfile)
  - Config gains language_set/default_language/cadence_* fields (ti-140k)

Coverage map (12 acceptance criteria):
  ①  override key → source='override'
  ②  annotation lang in set → source='annotation'; cadence annotation applied
  ②  annotation lang NOT in set → falls through to detector
  ③  detector confidence ≥ threshold → source='detector'
  ③  detector confidence < threshold → falls through to default
  ③  language_set order respected (top-to-bottom)
  ④  default config → source='default'
  lock  profile immutable after resolve()
  cadence  slow-mode 0.7× on re_ask; does not mutate locked profile
  ADR-0005  resolver never modifies trust level
  Config   language_set/default_language/cadence fields have correct defaults
  Profile  default cadence=1.0, default source='default'
"""
from __future__ import annotations

import dataclasses
from unittest.mock import MagicMock

import pytest

from iris.config import Config
from iris.prefs import PreferencesStore
from iris.profile_resolver import PresentationProfile, ProfileResolver

# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

def _stub_voice_lookup(lang: str):
    """Returns a minimal voice-entry-like object for any language."""
    entry = MagicMock()
    entry.voice_id = f"{lang}-voice"
    entry.lang = lang
    return entry


def _stub_detector(confidences: dict[str, float]):
    """Returns a callable that reports per-language Whisper confidence."""
    def detect(utterance: str) -> dict[str, float]:
        return confidences
    return detect


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def prefs(tmp_path):
    return PreferencesStore(tmp_path / "prefs.json")


def _resolver(config: Config, prefs: PreferencesStore,
              confidences: dict[str, float] | None = None) -> ProfileResolver:
    detector = _stub_detector(confidences or {})
    return ProfileResolver(config=config, prefs=prefs,
                           voice_lookup=_stub_voice_lookup,
                           detector=detector)


# ---------------------------------------------------------------------------
# Config defaults (criteria #11)
# ---------------------------------------------------------------------------

def test_config_language_set_default():
    cfg = Config()
    assert cfg.language_set == ["en"]


def test_config_default_language_default():
    cfg = Config()
    assert cfg.default_language == "en"


def test_config_cadence_default_is_one():
    cfg = Config()
    assert cfg.cadence_default == 1.0


def test_config_cadence_slow_is_point_seven():
    cfg = Config()
    assert cfg.cadence_slow == 0.7


def test_config_cadence_range():
    cfg = Config()
    assert cfg.cadence_range == (0.7, 1.4)


def test_config_language_detect_threshold():
    cfg = Config()
    assert cfg.language_detect_threshold == pytest.approx(0.80)


# ---------------------------------------------------------------------------
# PresentationProfile defaults (criteria #12)
# ---------------------------------------------------------------------------

def test_profile_default_cadence():
    p = PresentationProfile(language="en", tts_voice="", tts_lang="en")
    assert p.cadence == 1.0


def test_profile_default_source():
    p = PresentationProfile(language="en", tts_voice="", tts_lang="en")
    assert p.source == "default"


def test_profile_fields_present():
    p = PresentationProfile(language="es", tts_voice="es-voice", tts_lang="es",
                            cadence=1.0, source="detector")
    assert p.language == "es"
    assert p.tts_voice == "es-voice"
    assert p.tts_lang == "es"


# ---------------------------------------------------------------------------
# Chain step ① — override key (criteria #1)
# ---------------------------------------------------------------------------

def test_override_key_locks_with_source_override(prefs):
    cfg = Config(language_set=["en", "es"])
    r = _resolver(cfg, prefs)
    profile = r.resolve(override_key="es")
    assert profile.source == "override"
    assert profile.language == "es"


def test_override_key_wins_over_annotation(prefs, tmp_path):
    """Override takes priority even when annotation exists."""
    cfg = Config(language_set=["en", "es"])
    prefs.set("contact:alice", "lang", "es")
    r = _resolver(cfg, prefs)
    profile = r.resolve(override_key="en", contact_id="contact:alice")
    assert profile.source == "override"
    assert profile.language == "en"


# ---------------------------------------------------------------------------
# Chain step ② — contact annotation (criteria #2, #3)
# ---------------------------------------------------------------------------

def test_annotation_lang_in_set_locks_annotation(prefs):
    cfg = Config(language_set=["en", "es"])
    prefs.set("contact:alice", "lang", "es")
    r = _resolver(cfg, prefs)
    profile = r.resolve(contact_id="contact:alice")
    assert profile.source == "annotation"
    assert profile.language == "es"


def test_annotation_cadence_applied(prefs):
    cfg = Config(language_set=["en", "es"])
    prefs.set("contact:alice", "lang", "es")
    prefs.set("contact:alice", "cadence", "0.9")
    r = _resolver(cfg, prefs)
    profile = r.resolve(contact_id="contact:alice")
    assert profile.source == "annotation"
    assert profile.cadence == pytest.approx(0.9)


def test_annotation_lang_not_in_set_falls_through(prefs):
    """Annotation lang not in language_set → skip to detector."""
    cfg = Config(language_set=["en"], language_detect_threshold=0.80)
    prefs.set("contact:alice", "lang", "fr")  # fr not in set
    confidences = {"en": 0.95}
    r = _resolver(cfg, prefs, confidences)
    profile = r.resolve(contact_id="contact:alice", utterance="hello")
    # Falls through to detector which fires on 'en' at 0.95
    assert profile.source in ("detector", "default")
    assert profile.language == "en"


# ---------------------------------------------------------------------------
# Chain step ③ — Whisper detector (criteria #4, #5, #6)
# ---------------------------------------------------------------------------

def test_detector_above_threshold_locks_detector(prefs):
    cfg = Config(language_set=["en", "es"], language_detect_threshold=0.80)
    confidences = {"es": 0.94}
    r = _resolver(cfg, prefs, confidences)
    profile = r.resolve(utterance="hola")
    assert profile.source == "detector"
    assert profile.language == "es"


def test_detector_below_threshold_falls_through_to_default(prefs):
    cfg = Config(language_set=["en", "es"], language_detect_threshold=0.80)
    confidences = {"es": 0.60, "en": 0.55}  # both below threshold
    r = _resolver(cfg, prefs, confidences)
    profile = r.resolve(utterance="uh")
    assert profile.source == "default"


def test_detector_language_set_order_respected(prefs):
    """When both languages clear threshold, top-of-list wins."""
    cfg = Config(language_set=["es", "en"], language_detect_threshold=0.80)
    confidences = {"es": 0.85, "en": 0.91}  # en is higher but es is first
    r = _resolver(cfg, prefs, confidences)
    profile = r.resolve(utterance="mixed")
    assert profile.source == "detector"
    assert profile.language == "es"  # first in set beats higher confidence


def test_detector_lang_not_in_set_skipped(prefs):
    """Detector result for a lang outside language_set is ignored."""
    cfg = Config(language_set=["en"], language_detect_threshold=0.80)
    confidences = {"fr": 0.99, "en": 0.55}  # fr not in set; en below threshold
    r = _resolver(cfg, prefs, confidences)
    profile = r.resolve(utterance="bonjour")
    assert profile.language == "en"  # falls through to default
    assert profile.source == "default"


# ---------------------------------------------------------------------------
# Chain step ④ — default config (criteria #7)
# ---------------------------------------------------------------------------

def test_default_config_locks_default(prefs):
    cfg = Config(language_set=["en", "es"], default_language="en")
    confidences = {}  # no detection
    r = _resolver(cfg, prefs, confidences)
    profile = r.resolve()
    assert profile.source == "default"
    assert profile.language == "en"


def test_default_language_used_as_fallback(prefs):
    cfg = Config(language_set=["en", "es"], default_language="es",
                 language_detect_threshold=0.80)
    r = _resolver(cfg, prefs, {})
    profile = r.resolve()
    assert profile.language == "es"


# ---------------------------------------------------------------------------
# Lock semantics (criteria #8)
# ---------------------------------------------------------------------------

def test_locked_profile_is_frozen(prefs):
    cfg = Config()
    r = _resolver(cfg, prefs)
    profile = r.resolve()
    with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
        profile.language = "fr"  # type: ignore[misc]


def test_resolve_returns_same_profile_on_multiple_calls(prefs):
    """Re-calling resolve() returns consistent result (idempotent after lock)."""
    cfg = Config(language_set=["en"])
    r = _resolver(cfg, prefs)
    p1 = r.resolve()
    p2 = r.resolve()
    assert p1.language == p2.language
    assert p1.source == p2.source


# ---------------------------------------------------------------------------
# Cadence slow-mode (criteria #9)
# ---------------------------------------------------------------------------

def test_slow_mode_returns_slow_cadence_on_re_ask(prefs):
    cfg = Config(cadence_slow=0.7)
    r = _resolver(cfg, prefs)
    profile = r.resolve()
    effective = r.turn_cadence(profile, re_ask=True)
    assert effective == pytest.approx(0.7)


def test_slow_mode_returns_profile_cadence_when_no_re_ask(prefs):
    cfg = Config(cadence_default=1.0)
    r = _resolver(cfg, prefs)
    profile = r.resolve()
    effective = r.turn_cadence(profile, re_ask=False)
    assert effective == pytest.approx(profile.cadence)


def test_slow_mode_does_not_mutate_locked_profile(prefs):
    cfg = Config(cadence_default=1.0, cadence_slow=0.7)
    r = _resolver(cfg, prefs)
    profile = r.resolve()
    cadence_before = profile.cadence
    _ = r.turn_cadence(profile, re_ask=True)
    assert profile.cadence == cadence_before  # profile unchanged


# ---------------------------------------------------------------------------
# ADR-0005: resolver never touches trust (criteria #10)
# ---------------------------------------------------------------------------

def test_resolver_does_not_have_trust_attribute(prefs):
    """ProfileResolver must not expose any trust-related interface."""
    cfg = Config(language_set=["en", "es"])
    r = _resolver(cfg, prefs)
    profile = r.resolve()
    assert not hasattr(profile, "trust_tier")
    assert not hasattr(profile, "trust_level")
    assert not hasattr(profile, "trust")


def test_profile_has_no_trust_fields(prefs):
    p = PresentationProfile(language="en", tts_voice="", tts_lang="en")
    for attr in dir(p):
        assert "trust" not in attr.lower(), (
            f"PresentationProfile must not expose trust: found attribute '{attr}'"
        )
