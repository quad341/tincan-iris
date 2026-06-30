"""Tests for WakeWordSource — confidence gate, in_call gate, chime, headless TTS gate (ti-s9mm.5.3).

WakeWordSource lives at iris.daemon.wake_word.  faster-whisper and BrainHost are mocked;
chime and Kokoro TTS calls are patched — no real mic or audio output.

Six acceptance criteria from the bead notes:
  1. confidence < 0.85  ->  async_turn NOT called
  2. confidence >= 0.85 ->  async_turn IS called
  3. in_call=True       ->  async_turn NOT called (entire wake response muted)
  4. chime plays BEFORE async_turn (operator feedback)
  5. IRIS_HEADLESS_TTS=1 + in_call=True  -> Kokoro TTS NOT called
  6. IRIS_HEADLESS_TTS=1 + in_call=False -> Kokoro TTS called after reply
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from iris.daemon.wake_word import WakeWordSource


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_brain_host(*, in_call: bool = False) -> MagicMock:
    host = MagicMock()
    host.call_context = SimpleNamespace(in_call=in_call)
    host.async_turn.return_value = {"ok": True}
    return host


def _make_source(brain_host=None, *, threshold: float = 0.85) -> WakeWordSource:
    if brain_host is None:
        brain_host = _make_brain_host()
    return WakeWordSource(brain_host, threshold=threshold)


# ---------------------------------------------------------------------------
# 1. Confidence below threshold — async_turn NOT called
# ---------------------------------------------------------------------------


def test_confidence_below_threshold_skips_turn():
    """confidence 0.84 < 0.85 threshold: async_turn must not be called."""
    host = _make_brain_host()
    src = _make_source(host)
    with patch.object(src, "_play_chime"):
        src._handle_wake("hey iris", confidence=0.84)
    host.async_turn.assert_not_called()


def test_confidence_well_below_threshold_skips_turn():
    """confidence 0.50 is far below threshold: async_turn must not be called."""
    host = _make_brain_host()
    src = _make_source(host)
    with patch.object(src, "_play_chime"):
        src._handle_wake("hey iris", confidence=0.50)
    host.async_turn.assert_not_called()


# ---------------------------------------------------------------------------
# 2. Confidence at/above threshold — async_turn IS called
# ---------------------------------------------------------------------------


def test_confidence_at_threshold_calls_turn():
    """confidence exactly 0.85 meets threshold: async_turn must be called."""
    host = _make_brain_host()
    src = _make_source(host)
    with patch.object(src, "_play_chime"):
        src._handle_wake("hey iris, call John", confidence=0.85)
    host.async_turn.assert_called_once()


def test_confidence_above_threshold_calls_turn_with_utterance():
    """confidence 0.97 > threshold: async_turn receives the utterance text."""
    host = _make_brain_host()
    src = _make_source(host)
    with patch.object(src, "_play_chime"):
        src._handle_wake("hey iris, remind me at 3pm", confidence=0.97)
    host.async_turn.assert_called_once()
    args, kwargs = host.async_turn.call_args
    utterance = args[0] if args else kwargs.get("text", kwargs.get("utterance", ""))
    assert "remind me" in utterance


# ---------------------------------------------------------------------------
# 3. in_call=True — entire wake response muted
# ---------------------------------------------------------------------------


def test_in_call_mutes_async_turn():
    """When in_call is True, async_turn must not be called even with high confidence."""
    host = _make_brain_host(in_call=True)
    src = _make_source(host)
    with patch.object(src, "_play_chime"):
        src._handle_wake("hey iris", confidence=0.95)
    host.async_turn.assert_not_called()


def test_in_call_also_suppresses_chime():
    """When in_call is True, the confirmation chime must not play either."""
    host = _make_brain_host(in_call=True)
    src = _make_source(host)
    with patch.object(src, "_play_chime") as mock_chime:
        src._handle_wake("hey iris", confidence=0.95)
    mock_chime.assert_not_called()


# ---------------------------------------------------------------------------
# 4. Chime fires before async_turn
# ---------------------------------------------------------------------------


def test_chime_plays_before_async_turn():
    """Confirmation chime must fire before async_turn for immediate operator feedback."""
    call_order: list[str] = []

    host = _make_brain_host()
    host.async_turn.side_effect = lambda *a, **kw: call_order.append("async_turn") or {"ok": True}

    src = _make_source(host)

    def _fake_chime():
        call_order.append("chime")

    with patch.object(src, "_play_chime", side_effect=_fake_chime):
        src._handle_wake("hey iris", confidence=0.90)

    assert "chime" in call_order, "chime was not played"
    assert "async_turn" in call_order, "async_turn was not called"
    assert call_order.index("chime") < call_order.index("async_turn"), (
        f"chime must precede async_turn; order={call_order}"
    )


def test_chime_not_played_below_threshold():
    """Chime must not fire when confidence is below threshold (gate fails silently)."""
    host = _make_brain_host()
    src = _make_source(host)
    with patch.object(src, "_play_chime") as mock_chime:
        src._handle_wake("hey iris", confidence=0.50)
    mock_chime.assert_not_called()


# ---------------------------------------------------------------------------
# 5. IRIS_HEADLESS_TTS=1 + in_call=True -> Kokoro TTS NOT called
# ---------------------------------------------------------------------------


def test_headless_tts_not_called_when_in_call(monkeypatch):
    """IRIS_HEADLESS_TTS=1 and in_call=True: on_reply must not trigger TTS."""
    monkeypatch.setenv("IRIS_HEADLESS_TTS", "1")
    host = _make_brain_host(in_call=True)
    src = _make_source(host)
    with patch.object(src, "_tts_reply") as mock_tts:
        src.on_reply("I'll place that call now.")
    mock_tts.assert_not_called()


def test_headless_tts_not_called_when_env_unset(monkeypatch):
    """Without IRIS_HEADLESS_TTS=1: on_reply must not trigger TTS regardless of in_call."""
    monkeypatch.delenv("IRIS_HEADLESS_TTS", raising=False)
    host = _make_brain_host(in_call=False)
    src = _make_source(host)
    with patch.object(src, "_tts_reply") as mock_tts:
        src.on_reply("I'll place that call now.")
    mock_tts.assert_not_called()


# ---------------------------------------------------------------------------
# 6. IRIS_HEADLESS_TTS=1 + in_call=False -> Kokoro TTS called after reply
# ---------------------------------------------------------------------------


def test_headless_tts_called_with_reply_text_when_not_in_call(monkeypatch):
    """IRIS_HEADLESS_TTS=1 and not in_call: on_reply must call _tts_reply with the text."""
    monkeypatch.setenv("IRIS_HEADLESS_TTS", "1")
    host = _make_brain_host(in_call=False)
    src = _make_source(host)
    reply_text = "I'll place that call now."
    with patch.object(src, "_tts_reply") as mock_tts:
        src.on_reply(reply_text)
    mock_tts.assert_called_once_with(reply_text)


def test_headless_tts_reads_live_in_call_on_reply(monkeypatch):
    """on_reply must check call_context.in_call at reply time, not at wake time.

    Scenario: call begins between wake detection and reply — TTS should be suppressed.
    """
    monkeypatch.setenv("IRIS_HEADLESS_TTS", "1")
    ctx = SimpleNamespace(in_call=False)
    host = MagicMock()
    host.call_context = ctx
    host.async_turn.return_value = {"ok": True}
    src = WakeWordSource(host, threshold=0.85)

    # Call begins between wake and reply
    ctx.in_call = True

    with patch.object(src, "_tts_reply") as mock_tts:
        src.on_reply("I'll place that call now.")
    mock_tts.assert_not_called()
