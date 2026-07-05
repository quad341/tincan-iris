"""Unit tests for CallCardCloudSession (ti-pkt2r.1.1).

ClaudeTuiSession is patched at the cloud_session module boundary so these
tests exercise only CallCardCloudSession's own lazy-start/reuse, lock
serialization, and close() idempotency -- never a real tmux session.

Documented contract:
  CallCardCloudSession(cfg)
    .ask(prompt) -> str
      - constructs + starts a ClaudeTuiSession on the FIRST call only;
        later calls reuse the same instance
      - falls back to hardcoded defaults for any cfg attribute that's absent
      - serializes concurrent calls with an internal lock (one warm session
        can't answer two prompts at once)
    .close()
      - safe to call when never started (no-op, never touches ClaudeTuiSession)
      - safe to call twice (second call is a no-op)
      - a subsequent ask() after close() starts a fresh session
"""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

from iris.capture.cloud_session import CallCardCloudSession


def _cfg(**overrides):
    defaults = dict(
        call_card_llm_model="claude-haiku-4-5",
        call_card_llm_system_prompt="system prompt",
        call_card_llm_tmux_session="iris-callcard-llm",
        call_card_llm_ready_timeout_s=40.0,
        call_card_llm_ask_timeout_s=120.0,
    )
    defaults.update(overrides)
    return MagicMock(**defaults)


# ---------------------------------------------------------------------------
# lazy start / reuse
# ---------------------------------------------------------------------------

@patch("iris.capture.cloud_session.ClaudeTuiSession")
def test_first_ask_constructs_and_starts_session(mock_cls):
    session_mock = MagicMock()
    mock_cls.return_value = session_mock
    cloud = CallCardCloudSession(_cfg())

    result = cloud.ask("hello")

    mock_cls.assert_called_once_with(
        model="claude-haiku-4-5",
        system_prompt="system prompt",
        session="iris-callcard-llm",
        ready_timeout_s=40.0,
    )
    session_mock.start.assert_called_once_with()
    session_mock.ask.assert_called_once_with("hello", timeout_s=120.0)
    assert result == session_mock.ask.return_value


@patch("iris.capture.cloud_session.ClaudeTuiSession")
def test_second_ask_reuses_session_without_reconstructing(mock_cls):
    session_mock = MagicMock()
    mock_cls.return_value = session_mock
    cloud = CallCardCloudSession(_cfg())

    cloud.ask("first")
    cloud.ask("second")

    mock_cls.assert_called_once()
    session_mock.start.assert_called_once()
    assert session_mock.ask.call_count == 2
    session_mock.ask.assert_any_call("first", timeout_s=120.0)
    session_mock.ask.assert_any_call("second", timeout_s=120.0)


@patch("iris.capture.cloud_session.ClaudeTuiSession")
def test_ask_uses_hardcoded_defaults_when_cfg_lacks_attributes(mock_cls):
    session_mock = MagicMock()
    mock_cls.return_value = session_mock
    cloud = CallCardCloudSession(object())  # no call_card_llm_* attributes at all

    cloud.ask("hello")

    mock_cls.assert_called_once_with(
        model="claude-haiku-4-5",
        system_prompt="",
        session="iris-callcard-llm",
        ready_timeout_s=40.0,
    )
    session_mock.ask.assert_called_once_with("hello", timeout_s=120.0)


# ---------------------------------------------------------------------------
# lock serialization
# ---------------------------------------------------------------------------

@patch("iris.capture.cloud_session.ClaudeTuiSession")
def test_concurrent_asks_are_serialized(mock_cls):
    session_mock = MagicMock()
    mock_cls.return_value = session_mock
    cloud = CallCardCloudSession(_cfg())

    events: list[str] = []
    first_entered = threading.Event()
    release_first = threading.Event()

    def slow_ask(prompt, timeout_s):
        events.append(f"enter-{prompt}")
        if prompt == "first":
            first_entered.set()
            release_first.wait(timeout=2.0)
        events.append(f"exit-{prompt}")
        return "ok"

    session_mock.ask.side_effect = slow_ask

    t1 = threading.Thread(target=cloud.ask, args=("first",))
    t2 = threading.Thread(target=cloud.ask, args=("second",))
    t1.start()
    assert first_entered.wait(timeout=2.0), "first ask() never entered the session"

    t2.start()
    time.sleep(0.1)  # give t2 a chance to run if it is (incorrectly) not blocked
    assert events == ["enter-first"], "second ask() must not proceed while first holds the lock"

    release_first.set()
    t1.join(timeout=2.0)
    t2.join(timeout=2.0)

    assert events == ["enter-first", "exit-first", "enter-second", "exit-second"]


# ---------------------------------------------------------------------------
# close() idempotency
# ---------------------------------------------------------------------------

@patch("iris.capture.cloud_session.ClaudeTuiSession")
def test_close_before_any_ask_is_a_noop(mock_cls):
    cloud = CallCardCloudSession(_cfg())

    cloud.close()  # must not raise

    mock_cls.assert_not_called()


@patch("iris.capture.cloud_session.ClaudeTuiSession")
def test_close_after_ask_closes_the_session(mock_cls):
    session_mock = MagicMock()
    mock_cls.return_value = session_mock
    cloud = CallCardCloudSession(_cfg())
    cloud.ask("hello")

    cloud.close()

    session_mock.close.assert_called_once_with()


@patch("iris.capture.cloud_session.ClaudeTuiSession")
def test_close_twice_only_closes_underlying_session_once(mock_cls):
    session_mock = MagicMock()
    mock_cls.return_value = session_mock
    cloud = CallCardCloudSession(_cfg())
    cloud.ask("hello")

    cloud.close()
    cloud.close()  # must not raise, must not re-close

    session_mock.close.assert_called_once_with()


@patch("iris.capture.cloud_session.ClaudeTuiSession")
def test_ask_after_close_starts_a_new_session(mock_cls):
    session_mock = MagicMock()
    mock_cls.return_value = session_mock
    cloud = CallCardCloudSession(_cfg())
    cloud.ask("hello")
    cloud.close()

    cloud.ask("hello again")

    assert mock_cls.call_count == 2
    assert session_mock.start.call_count == 2
