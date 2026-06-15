"""Brain.respond() — DEMO-mode Tier2/skill-dispatch blocking.

Four scenarios (bead ti-93w):
  1. far_trust=DEMO + speaker=far  → Haiku (Tier 2) call blocked
  2. far_trust=DEMO + speaker=far  → skill dispatch disabled (allow_skills=False)
  3. far_trust=FULL + speaker=far  → Haiku allowed, skill dispatch enabled
  4. far_trust=DEMO + speaker=operator → not blocked (only the far party is gated)
"""
from __future__ import annotations

from unittest.mock import MagicMock, call, patch

from iris.brain import Brain
from iris.config import Config
from iris.lanes import LaneResult
from iris.trust import TrustMode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _brain(*, haiku_enabled: bool = True) -> Brain:
    """Return a Brain with both inner tiers replaced by synchronous mocks."""
    b = Brain(Config(haiku_enabled=haiku_enabled))
    b.tier1 = MagicMock()
    b.tier2 = MagicMock()
    b.tier1.handle.return_value = LaneResult("tier1 reply", "tier1-qwen")
    b.tier2.handle.return_value = LaneResult("tier2 reply", "tier2-haiku")
    return b


def _noop_masking(
    work,
    *,
    first_filler_s,
    repeat_filler_s,
    deadline_s,
    on_filler=None,
    fallback=None,
    interrupted=None,
    stop_event=None,
):
    """Synchronous masking stub — execute work immediately, no threads."""
    return work()


# ---------------------------------------------------------------------------
# 1. DEMO + far: Haiku (Tier 2) is blocked
# ---------------------------------------------------------------------------

def test_demo_far_does_not_call_tier2():
    b = _brain(haiku_enabled=True)
    with patch("iris.brain.run_with_masking", side_effect=_noop_masking):
        b.respond("ask Haiku about the weather", speaker="far", far_trust=TrustMode.DEMO)
    b.tier2.handle.assert_not_called()


def test_demo_far_haiku_block_returns_correct_lane():
    b = _brain(haiku_enabled=True)
    with patch("iris.brain.run_with_masking", side_effect=_noop_masking):
        reply = b.respond("ask Haiku about the weather", speaker="far", far_trust=TrustMode.DEMO)
    assert reply.lane == "tier2-haiku(blocked-demo)"


def test_demo_far_haiku_block_reply_mentions_full_access():
    b = _brain(haiku_enabled=True)
    with patch("iris.brain.run_with_masking", side_effect=_noop_masking):
        reply = b.respond("ask Haiku about Paris", speaker="far", far_trust=TrustMode.DEMO)
    assert "full access" in reply.text.lower()


def test_demo_far_haiku_block_preserves_speaker():
    b = _brain(haiku_enabled=True)
    with patch("iris.brain.run_with_masking", side_effect=_noop_masking):
        reply = b.respond("ask Haiku about Paris", speaker="far", far_trust=TrustMode.DEMO)
    assert reply.speaker == "far"


# ---------------------------------------------------------------------------
# 2. DEMO + far: skill dispatch disabled (allow_skills=False passed to Tier 1)
# ---------------------------------------------------------------------------

def test_demo_far_tier1_called_with_allow_skills_false():
    b = _brain(haiku_enabled=False)
    with patch("iris.brain.run_with_masking", side_effect=_noop_masking):
        b.respond("what's on my calendar", speaker="far", far_trust=TrustMode.DEMO)
    b.tier1.handle.assert_called_once()
    _, kwargs = b.tier1.handle.call_args
    assert kwargs.get("allow_skills") is False


# ---------------------------------------------------------------------------
# 3. FULL + far: both Haiku and skill dispatch allowed
# ---------------------------------------------------------------------------

def test_full_far_calls_tier2():
    b = _brain(haiku_enabled=True)
    with patch("iris.brain.run_with_masking", side_effect=_noop_masking):
        reply = b.respond("ask Haiku about Paris", speaker="far", far_trust=TrustMode.FULL)
    b.tier2.handle.assert_called_once()
    assert reply.lane != "tier2-haiku(blocked-demo)"


def test_full_far_tier1_called_with_allow_skills_true():
    b = _brain(haiku_enabled=False)
    with patch("iris.brain.run_with_masking", side_effect=_noop_masking):
        b.respond("what's on my calendar", speaker="far", far_trust=TrustMode.FULL)
    b.tier1.handle.assert_called_once()
    _, kwargs = b.tier1.handle.call_args
    assert kwargs.get("allow_skills") is True


# ---------------------------------------------------------------------------
# 4. DEMO + operator: not blocked (trust mode only gates the far party)
# ---------------------------------------------------------------------------

def test_operator_not_blocked_by_demo_haiku():
    b = _brain(haiku_enabled=True)
    with patch("iris.brain.run_with_masking", side_effect=_noop_masking):
        reply = b.respond("ask Haiku about Paris", speaker="operator", far_trust=TrustMode.DEMO)
    b.tier2.handle.assert_called_once()
    assert reply.lane != "tier2-haiku(blocked-demo)"


def test_operator_not_blocked_by_demo_skill_dispatch():
    b = _brain(haiku_enabled=False)
    with patch("iris.brain.run_with_masking", side_effect=_noop_masking):
        b.respond("what's on my calendar", speaker="operator", far_trust=TrustMode.DEMO)
    b.tier1.handle.assert_called_once()
    _, kwargs = b.tier1.handle.call_args
    assert kwargs.get("allow_skills") is True
