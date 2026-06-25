"""Unit tests for iris/delegate_skill.py (ti-h9di.1, ti-h9di.2).

Covers: _DelegateState, DelegateSkill, ConfirmDelegateSkill, CancelDelegateSkill.
No real gc binary — subprocess.run is mocked. No SSE listener.
Timeout tests patch _read_timeout_s() to return 0.02s to avoid 30-minute waits.
ADR-0005: confirm is required before mail is sent (no silent dispatch).
"""
from __future__ import annotations

import os
import threading
import time
from subprocess import CalledProcessError, CompletedProcess
from unittest.mock import MagicMock, call, patch

import pytest

from iris.delegate_skill import (
    CancelDelegateSkill,
    ConfirmDelegateSkill,
    DelegateSkill,
    _DelegateState,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LONG = "x" * 201          # 201 chars — one over the 200-char cap
_UNDER = "x" * 200         # exactly at the limit — must pass
_ENTRY = "entry-001"


def _mail_ok(*args, **kwargs):
    return CompletedProcess(args[0], 0)


def _mail_fail(*args, **kwargs):
    raise CalledProcessError(1, "gc")


# ---------------------------------------------------------------------------
# _DelegateState — staged (pending operator confirm)
# ---------------------------------------------------------------------------

def test_state_no_staged_initially():
    assert not _DelegateState().has_staged


def test_state_stage_makes_staged():
    s = _DelegateState()
    s.stage("Re: deploy backlog", "please triage the deploy backlog")
    assert s.has_staged


def test_state_pop_staged_returns_subject_and_body():
    s = _DelegateState()
    s.stage("Subject line", "body text")
    subject, body = s.pop_staged()
    assert subject == "Subject line"
    assert body == "body text"


def test_state_pop_staged_clears_staged():
    s = _DelegateState()
    s.stage("S", "B")
    s.pop_staged()
    assert not s.has_staged


def test_state_clear_staged_removes_pending():
    s = _DelegateState()
    s.stage("S", "B")
    s.clear_staged()
    assert not s.has_staged


def test_state_clear_staged_then_pop_returns_empty():
    s = _DelegateState()
    s.stage("S", "B")
    s.clear_staged()
    subject, body = s.pop_staged()
    assert subject == "" and body == ""


# ---------------------------------------------------------------------------
# _DelegateState — sent queue (confirmed delegations awaiting mayor reply)
# ---------------------------------------------------------------------------

def test_queue_initially_empty():
    assert _DelegateState().queue_count == 0


def test_queue_enqueue_increments_count():
    s = _DelegateState()
    s.enqueue(_ENTRY, "S", "B")
    assert s.queue_count == 1


def test_queue_enqueue_two_shows_count_two():
    s = _DelegateState()
    s.enqueue("e-1", "S1", "B1")
    s.enqueue("e-2", "S2", "B2")
    assert s.queue_count == 2


def test_queue_dequeue_decrements_count():
    s = _DelegateState()
    s.enqueue(_ENTRY, "S", "B")
    s.dequeue(_ENTRY)
    assert s.queue_count == 0


def test_queue_dequeue_nonexistent_is_noop():
    s = _DelegateState()
    s.enqueue(_ENTRY, "S", "B")
    s.dequeue("no-such-id")
    assert s.queue_count == 1


def test_queue_drains_to_zero():
    s = _DelegateState()
    s.enqueue("e-1", "S1", "B1")
    s.enqueue("e-2", "S2", "B2")
    s.dequeue("e-1")
    s.dequeue("e-2")
    assert s.queue_count == 0


# ---------------------------------------------------------------------------
# _DelegateState — status bar text
# ---------------------------------------------------------------------------

def test_status_bar_empty_when_no_pending():
    assert _DelegateState().status_bar_text() == ""


def test_status_bar_shows_one_pending():
    s = _DelegateState()
    s.enqueue(_ENTRY, "S", "B")
    text = s.status_bar_text()
    assert "1" in text
    assert "pending" in text.lower()


def test_status_bar_shows_two_pending():
    s = _DelegateState()
    s.enqueue("e-1", "S1", "B1")
    s.enqueue("e-2", "S2", "B2")
    text = s.status_bar_text()
    assert "2" in text


def test_status_bar_clears_when_queue_drains():
    s = _DelegateState()
    s.enqueue(_ENTRY, "S", "B")
    s.dequeue(_ENTRY)
    assert s.status_bar_text() == ""


# ---------------------------------------------------------------------------
# DelegateSkill
# ---------------------------------------------------------------------------

def _delegate_skill(state=None):
    return DelegateSkill(state or _DelegateState())


def test_delegate_skill_far_party_returns_none():
    skill = _delegate_skill()
    assert skill.run(utterance="ask the mayor to do X", speaker="far") is None


def test_delegate_skill_empty_utterance_prompts_for_content():
    skill = _delegate_skill()
    result = skill.run(utterance="", speaker="operator")
    assert result is not None
    assert "?" in result or "what" in result.lower() or "ask" in result.lower()


def test_delegate_skill_stages_pending_on_normal_utterance():
    state = _DelegateState()
    skill = DelegateSkill(state)
    skill.run(utterance="please triage the deploy backlog", speaker="operator")
    assert state.has_staged


def test_delegate_skill_returns_confirmation_preview():
    skill = _delegate_skill()
    result = skill.run(utterance="please triage the deploy backlog", speaker="operator")
    assert result is not None
    assert "?" in result or "send" in result.lower() or "mayor" in result.lower()


def test_delegate_skill_preview_includes_body_excerpt():
    skill = _delegate_skill()
    result = skill.run(utterance="please triage the deploy backlog", speaker="operator")
    assert result is not None
    assert "deploy backlog" in result or "triage" in result.lower()


def test_delegate_skill_under_200_char_passes():
    state = _DelegateState()
    skill = DelegateSkill(state)
    skill.run(utterance=_UNDER, speaker="operator")
    assert state.has_staged


def test_delegate_skill_over_200_char_prompts_rephrase():
    state = _DelegateState()
    skill = DelegateSkill(state)
    result = skill.run(utterance=_LONG, speaker="operator")
    assert result is not None
    assert "shorter" in result.lower() or "rephrase" in result.lower() or "brief" in result.lower()


def test_delegate_skill_over_200_char_does_not_stage():
    state = _DelegateState()
    skill = DelegateSkill(state)
    skill.run(utterance=_LONG, speaker="operator")
    assert not state.has_staged


def test_delegate_skill_is_operator_only():
    assert getattr(DelegateSkill, "operator_only", False)


# ---------------------------------------------------------------------------
# ConfirmDelegateSkill — ADR-0005 gate: confirm required before mail is sent
# ---------------------------------------------------------------------------

def _confirm_skill(state=None, gc_bin="gc"):
    return ConfirmDelegateSkill(state or _DelegateState(), gc_bin=gc_bin)


def test_confirm_no_staged_returns_nothing_to_confirm():
    """ADR-0005: no mail sent without a staged delegation."""
    with patch("iris.delegate_skill.subprocess.run") as mock_run:
        result = _confirm_skill().run()
    assert "nothing" in result.lower() or "confirm" in result.lower()
    mock_run.assert_not_called()


def test_confirm_happy_path_sends_mail_and_acks():
    state = _DelegateState()
    state.stage("Triage backlog", "please triage the deploy backlog")
    skill = ConfirmDelegateSkill(state)
    with patch("iris.delegate_skill.subprocess.run", side_effect=_mail_ok):
        result = skill.run()
    assert result is not None
    assert "mayor" in result.lower() or "sent" in result.lower()


def test_confirm_enqueues_on_successful_send():
    state = _DelegateState()
    state.stage("S", "B")
    skill = ConfirmDelegateSkill(state)
    with patch("iris.delegate_skill.subprocess.run", side_effect=_mail_ok):
        skill.run()
    assert state.queue_count == 1


def test_confirm_pops_staged_before_sending():
    state = _DelegateState()
    state.stage("S", "B")
    skill = ConfirmDelegateSkill(state)
    with patch("iris.delegate_skill.subprocess.run", side_effect=_mail_ok):
        skill.run()
    assert not state.has_staged


def test_confirm_retry_on_first_failure():
    """First gc mail failure is silent; second attempt succeeds."""
    state = _DelegateState()
    state.stage("S", "B")
    skill = ConfirmDelegateSkill(state)
    with patch(
        "iris.delegate_skill.subprocess.run",
        side_effect=[CalledProcessError(1, "gc"), CompletedProcess(["gc"], 0)],
    ) as mock_run:
        result = skill.run()
    assert mock_run.call_count == 2
    assert result is not None
    assert "mayor" in result.lower() or "sent" in result.lower()


def test_confirm_retry_enqueues_on_second_success():
    state = _DelegateState()
    state.stage("S", "B")
    skill = ConfirmDelegateSkill(state)
    with patch(
        "iris.delegate_skill.subprocess.run",
        side_effect=[CalledProcessError(1, "gc"), CompletedProcess(["gc"], 0)],
    ):
        skill.run()
    assert state.queue_count == 1


def test_confirm_double_failure_returns_error_voice_line():
    state = _DelegateState()
    state.stage("S", "B")
    skill = ConfirmDelegateSkill(state)
    with patch(
        "iris.delegate_skill.subprocess.run",
        side_effect=[CalledProcessError(1, "gc"), CalledProcessError(1, "gc")],
    ) as mock_run:
        result = skill.run()
    assert mock_run.call_count == 2
    assert result is not None
    assert "couldn't" in result.lower() or "sorry" in result.lower() or "failed" in result.lower()


def test_confirm_double_failure_does_not_enqueue():
    state = _DelegateState()
    state.stage("S", "B")
    skill = ConfirmDelegateSkill(state)
    with patch(
        "iris.delegate_skill.subprocess.run",
        side_effect=[CalledProcessError(1, "gc"), CalledProcessError(1, "gc")],
    ):
        skill.run()
    assert state.queue_count == 0


def test_confirm_is_operator_only():
    assert getattr(ConfirmDelegateSkill, "operator_only", False)


# ---------------------------------------------------------------------------
# CancelDelegateSkill
# ---------------------------------------------------------------------------

def test_cancel_clears_staged():
    state = _DelegateState()
    state.stage("S", "B")
    CancelDelegateSkill(state).run()
    assert not state.has_staged


def test_cancel_returns_ack():
    state = _DelegateState()
    state.stage("S", "B")
    result = CancelDelegateSkill(state).run()
    assert isinstance(result, str) and len(result) > 0
    assert "cancel" in result.lower() or "ok" in result.lower() or "skip" in result.lower()


def test_cancel_no_staged_still_succeeds():
    result = CancelDelegateSkill(_DelegateState()).run()
    assert isinstance(result, str)


def test_cancel_is_operator_only():
    assert getattr(CancelDelegateSkill, "operator_only", False)


# ---------------------------------------------------------------------------
# Reply timeout — fires voice line and dequeues
# ---------------------------------------------------------------------------

def test_timeout_dequeues_entry():
    timed_out: list[str] = []
    s = _DelegateState()
    with patch("iris.delegate_skill._read_timeout_s", return_value=0.02):
        s.enqueue(_ENTRY, "S", "B", on_timeout=lambda eid: timed_out.append(eid))
    time.sleep(0.1)
    assert s.queue_count == 0


def test_timeout_calls_on_timeout_callback():
    cb = MagicMock()
    s = _DelegateState()
    with patch("iris.delegate_skill._read_timeout_s", return_value=0.02):
        s.enqueue(_ENTRY, "S", "B", on_timeout=cb)
    time.sleep(0.1)
    cb.assert_called_once_with(_ENTRY)


def test_timeout_fires_voice_line_via_callback():
    spoken: list[str] = []

    def on_timeout(eid: str) -> None:
        spoken.append("I haven't heard back from the mayor yet.")

    s = _DelegateState()
    with patch("iris.delegate_skill._read_timeout_s", return_value=0.02):
        s.enqueue(_ENTRY, "S", "B", on_timeout=on_timeout)
    time.sleep(0.1)
    assert spoken and "mayor" in spoken[0].lower()


def test_timeout_config_env_override(tmp_path, monkeypatch):
    """settings.toml delegation.reply_timeout_minutes feeds _read_timeout_s() and the timer."""
    import iris.settings as _settings

    cfg = tmp_path / "config.toml"
    cfg.write_text("[delegation]\nreply_timeout_minutes = 1\n")
    monkeypatch.setenv("IRIS_CONFIG", str(cfg))
    _settings.reload()

    from iris.delegate_skill import _read_timeout_s

    try:
        assert _read_timeout_s() == pytest.approx(60.0)
        # Verify enqueue() actually calls _read_timeout_s (not the dead constant).
        s = _DelegateState()
        with patch("iris.delegate_skill._read_timeout_s", return_value=0.02) as mock_fn:
            s.enqueue(_ENTRY, "S", "B", on_timeout=lambda eid: None)
        mock_fn.assert_called_once()
    finally:
        monkeypatch.delenv("IRIS_CONFIG", raising=False)
        _settings.reload()
