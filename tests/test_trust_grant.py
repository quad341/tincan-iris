"""Unit tests for the trust grant flow: arm/disarm state + grant() cycle.

ti-qt1i.1.5 (unit half) — written BEFORE builder implementation (TDD red phase).
Fails until ti-qt1i.1.2 ships: TrustMode NONE/LOCAL/BOTH + Conductor arm/grant.

Textual integration tests live in test_trust_grant_app.py.
iris-arm/iris-disarm CLI tests live in test_trust_grant_cli.py.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from iris.console.conductor import Conductor
from iris.trust import TrustMode

# ---------------------------------------------------------------------------
# Fixture — mirrors _make() in test_conductor.py
# ---------------------------------------------------------------------------

def _make():
    stt = MagicMock()
    stt.transcribe.return_value = "hello"
    reply = MagicMock()
    reply.text = "hi"
    reply.lane = "tier1-qwen"
    reply.skill = None
    reply.timeline.summary.return_value = "tier1=+50ms"
    brain = MagicMock()
    brain.respond.return_value = reply
    tts = MagicMock()
    tts.synth.return_value = "/tmp/out.wav"
    rec = MagicMock()
    rec.stop.return_value = "/tmp/in.wav"
    play = MagicMock()
    mic = MagicMock()
    mic.start_capture.return_value = rec
    mic.start_playback.return_value = play
    events: list = []
    c = Conductor(stt, brain, tts, mic, emit=events.append, pick=lambda: "one sec")
    return c, events


# ---------------------------------------------------------------------------
# arm / disarm
# ---------------------------------------------------------------------------

def test_conductor_unarmed_by_default():
    c, _ = _make()
    assert c._armed is False


def test_conductor_arm_sets_armed():
    c, _ = _make()
    c.arm()
    assert c._armed is True


def test_conductor_arm_emits_event():
    c, events = _make()
    c.arm()
    assert ("armed", True) in events


def test_conductor_disarm_clears_armed():
    c, _ = _make()
    c.arm()
    c.disarm()
    assert c._armed is False


def test_conductor_disarm_emits_event():
    c, events = _make()
    c.arm()
    events.clear()
    c.disarm()
    assert ("armed", False) in events


def test_conductor_disarm_revokes_grant():
    """disarm() clears armed AND reverts all trust to minimum."""
    c, _ = _make()
    c.arm()
    c.grant()  # → LOCAL
    c.disarm()
    assert c.trust_state is TrustMode.NONE
    assert c.op_trust is TrustMode.DEMO
    assert c.far_trust is TrustMode.DEMO


# ---------------------------------------------------------------------------
# grant() when unarmed — blocked, not silent
# ---------------------------------------------------------------------------

def test_grant_noop_when_unarmed():
    c, _ = _make()
    c.grant()
    assert c.trust_state is TrustMode.NONE
    assert c.op_trust is TrustMode.DEMO
    assert c.far_trust is TrustMode.DEMO


def test_grant_unarmed_emits_error():
    c, events = _make()
    c.grant()
    assert any(e[0] == "error" for e in events)


# ---------------------------------------------------------------------------
# grant() cycle when armed: NONE → LOCAL → BOTH → NONE
# ---------------------------------------------------------------------------

def test_grant_armed_none_to_local():
    c, _ = _make()
    c.arm()
    c.grant()
    assert c.trust_state is TrustMode.LOCAL


def test_trust_mode_local_op_full_far_demo():
    """LOCAL: operator elevated to FULL; far party stays DEMO."""
    c, _ = _make()
    c.arm()
    c.grant()  # → LOCAL
    assert c.op_trust is TrustMode.FULL
    assert c.far_trust is TrustMode.DEMO


def test_grant_armed_local_to_both():
    c, _ = _make()
    c.arm()
    c.grant()  # → LOCAL
    c.grant()  # → BOTH
    assert c.trust_state is TrustMode.BOTH


def test_trust_mode_both_op_full_far_full():
    """BOTH: operator and far party both elevated to FULL."""
    c, _ = _make()
    c.arm()
    c.grant()  # → LOCAL
    c.grant()  # → BOTH
    assert c.op_trust is TrustMode.FULL
    assert c.far_trust is TrustMode.FULL


def test_grant_armed_both_to_none():
    """Third press revokes all grants; trust returns to minimum."""
    c, _ = _make()
    c.arm()
    c.grant()  # → LOCAL
    c.grant()  # → BOTH
    c.grant()  # → NONE (revoke)
    assert c.trust_state is TrustMode.NONE
    assert c.op_trust is TrustMode.DEMO
    assert c.far_trust is TrustMode.DEMO


def test_grant_cycle_emits_trust_event():
    c, events = _make()
    c.arm()
    events.clear()
    c.grant()
    assert any(e[0] == "trust" for e in events)


# ---------------------------------------------------------------------------
# reset_far_trust() — reverts far only, op_trust unchanged
# ---------------------------------------------------------------------------

def test_reset_far_trust_reverts_far_only():
    """At BOTH: reset_far_trust() → far → DEMO, op stays FULL."""
    c, _ = _make()
    c.arm()
    c.grant()  # → LOCAL (op=FULL, far=DEMO)
    c.grant()  # → BOTH  (op=FULL, far=FULL)
    c.reset_far_trust()
    assert c.far_trust is TrustMode.DEMO
    assert c.op_trust is TrustMode.FULL


def test_reset_far_trust_at_none_leaves_op_unchanged():
    """reset_far_trust() when at NONE: op_trust stays DEMO."""
    c, _ = _make()
    c.reset_far_trust()
    assert c.far_trust is TrustMode.DEMO
    assert c.op_trust is TrustMode.DEMO


# ---------------------------------------------------------------------------
# op_trust threads to brain.respond() alongside far_trust
# ---------------------------------------------------------------------------

def test_op_trust_threaded_to_brain_at_local():
    """After LOCAL grant, brain.respond gets op_trust=FULL."""
    c, _ = _make()
    c.arm()
    c.grant()  # → LOCAL
    c.respond_to("do something", speaker="operator")
    _, kwargs = c.brain.respond.call_args
    assert kwargs.get("op_trust") is TrustMode.FULL


def test_far_trust_threaded_to_brain_at_both():
    """After BOTH grant, brain.respond gets far_trust=FULL."""
    c, _ = _make()
    c.arm()
    c.grant()  # → LOCAL
    c.grant()  # → BOTH
    c.respond_to("do something", speaker="far")
    _, kwargs = c.brain.respond.call_args
    assert kwargs.get("far_trust") is TrustMode.FULL


def test_op_trust_default_demo_threads_to_brain():
    """Without any grant, brain.respond gets op_trust=DEMO."""
    c, _ = _make()
    c.respond_to("do something", speaker="operator")
    _, kwargs = c.brain.respond.call_args
    assert kwargs.get("op_trust") is TrustMode.DEMO
