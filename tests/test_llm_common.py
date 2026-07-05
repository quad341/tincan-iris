"""Unit tests for ask_structured (ti-pkt2r.1.1).

Documented contract:
  ask_structured(cloud, prompt, retry_prompt, schema) -> BaseModel | None
    - strips a ```/```json code fence around the model's answer, if present
    - validates the parsed JSON against `schema`
    - retries exactly once, with `retry_prompt`, on invalid JSON or a
      pydantic ValidationError
    - returns None (not an exception) after a second consecutive failure
    - does NOT catch cloud.ask() itself raising -- that propagates unchanged
      to the caller
"""
from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest
from pydantic import BaseModel

from iris.capture._llm_common import ask_structured


class _Schema(BaseModel):
    value: str


PROMPT = "prompt"
RETRY_PROMPT = "retry prompt"


def _cloud(*answers):
    cloud = MagicMock()
    cloud.ask.side_effect = list(answers)
    return cloud


# ---------------------------------------------------------------------------
# success path / code-fence stripping
# ---------------------------------------------------------------------------

def test_valid_json_on_first_attempt_returns_validated_model():
    cloud = _cloud('{"value": "ok"}')

    result = ask_structured(cloud, PROMPT, RETRY_PROMPT, _Schema)

    assert result == _Schema(value="ok")
    cloud.ask.assert_called_once_with(PROMPT)


@pytest.mark.parametrize("fenced", [
    '```\n{"value": "ok"}\n```',
    '```json\n{"value": "ok"}\n```',
])
def test_code_fence_is_stripped_before_parsing(fenced):
    cloud = _cloud(fenced)

    result = ask_structured(cloud, PROMPT, RETRY_PROMPT, _Schema)

    assert result == _Schema(value="ok")


def test_unfenced_json_with_surrounding_whitespace_parses():
    cloud = _cloud('  \n {"value": "ok"} \n  ')

    result = ask_structured(cloud, PROMPT, RETRY_PROMPT, _Schema)

    assert result == _Schema(value="ok")


# ---------------------------------------------------------------------------
# retry-once semantics
# ---------------------------------------------------------------------------

def test_invalid_json_on_first_attempt_retries_with_retry_prompt():
    cloud = _cloud("not json", '{"value": "ok"}')

    result = ask_structured(cloud, PROMPT, RETRY_PROMPT, _Schema)

    assert result == _Schema(value="ok")
    assert cloud.ask.call_args_list == [call(PROMPT), call(RETRY_PROMPT)]


def test_schema_validation_error_on_first_attempt_retries():
    cloud = _cloud('{"wrong_field": "x"}', '{"value": "ok"}')

    result = ask_structured(cloud, PROMPT, RETRY_PROMPT, _Schema)

    assert result == _Schema(value="ok")
    assert cloud.ask.call_count == 2


def test_both_attempts_invalid_json_returns_none_after_exactly_two_tries():
    # side_effect has exactly 2 entries -- a 3rd cloud.ask() call would raise
    # StopIteration and fail the test, proving no further retries happen.
    cloud = _cloud("not json", "still not json")

    result = ask_structured(cloud, PROMPT, RETRY_PROMPT, _Schema)

    assert result is None
    assert cloud.ask.call_count == 2


def test_both_attempts_fail_schema_validation_returns_none():
    cloud = _cloud('{"wrong_field": "x"}', '{"also_wrong": "y"}')

    result = ask_structured(cloud, PROMPT, RETRY_PROMPT, _Schema)

    assert result is None
    assert cloud.ask.call_count == 2


# ---------------------------------------------------------------------------
# cloud.ask() exceptions propagate uncaught
# ---------------------------------------------------------------------------

def test_cloud_ask_exception_on_first_attempt_propagates_unchanged():
    cloud = MagicMock()
    cloud.ask.side_effect = RuntimeError("session not ready")

    with pytest.raises(RuntimeError, match="session not ready"):
        ask_structured(cloud, PROMPT, RETRY_PROMPT, _Schema)


def test_cloud_ask_exception_on_retry_attempt_propagates_unchanged():
    cloud = MagicMock()
    cloud.ask.side_effect = ["not json", RuntimeError("session died mid-retry")]

    with pytest.raises(RuntimeError, match="session died mid-retry"):
        ask_structured(cloud, PROMPT, RETRY_PROMPT, _Schema)
