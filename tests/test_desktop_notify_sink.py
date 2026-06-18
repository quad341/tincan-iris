"""Tests for DesktopNotifySink + ProactiveDelivery out_of_call routing (ti-6qsb.3).

These tests FAIL until the builder implements iris/notify_sink.py and the
out_of_call delivery path in ProactiveDelivery.
"""
from __future__ import annotations

import subprocess
import time
from unittest.mock import MagicMock, patch

import pytest

from iris.notify_sink import DesktopNotifySink


# ---------------------------------------------------------------------------
# DesktopNotifySink — subprocess invocation
# ---------------------------------------------------------------------------

def test_notify_calls_notify_send():
    with patch("iris.notify_sink.subprocess.run") as run:
        DesktopNotifySink().notify("Alice (VIP)", "Missed call", urgency="critical")
    run.assert_called_once()


def test_notify_send_includes_urgency_flag():
    with patch("iris.notify_sink.subprocess.run") as run:
        DesktopNotifySink().notify("Title", "Body", urgency="critical")
    cmd = run.call_args[0][0]
    assert "-u" in cmd
    assert "critical" in cmd


def test_notify_send_includes_app_name_iris():
    with patch("iris.notify_sink.subprocess.run") as run:
        DesktopNotifySink().notify("Title", "Body")
    cmd = run.call_args[0][0]
    assert "-a" in cmd
    idx = cmd.index("-a")
    assert cmd[idx + 1] == "Iris"


def test_notify_send_includes_double_dash_separator():
    """-- must appear before title to prevent flag injection from title text."""
    with patch("iris.notify_sink.subprocess.run") as run:
        DesktopNotifySink().notify("Title", "Body")
    cmd = run.call_args[0][0]
    assert "--" in cmd


def test_notify_send_double_dash_precedes_title():
    with patch("iris.notify_sink.subprocess.run") as run:
        DesktopNotifySink().notify("MyTitle", "MyBody")
    cmd = run.call_args[0][0]
    dash_pos = cmd.index("--")
    title_pos = cmd.index("MyTitle")
    assert dash_pos < title_pos


def test_notify_send_title_and_body_present():
    with patch("iris.notify_sink.subprocess.run") as run:
        DesktopNotifySink().notify("My Title", "My Body")
    cmd = run.call_args[0][0]
    assert "My Title" in cmd
    assert "My Body" in cmd


def test_file_not_found_silently_skips():
    with patch("iris.notify_sink.subprocess.run", side_effect=FileNotFoundError):
        DesktopNotifySink().notify("title", "body")  # must not raise


def test_timeout_expired_silently_skips():
    exc = subprocess.TimeoutExpired(cmd="notify-send", timeout=2.0)
    with patch("iris.notify_sink.subprocess.run", side_effect=exc):
        DesktopNotifySink().notify("title", "body")  # must not raise


def test_default_urgency_is_normal():
    with patch("iris.notify_sink.subprocess.run") as run:
        DesktopNotifySink().notify("title", "body")  # no urgency arg
    cmd = run.call_args[0][0]
    idx = cmd.index("-u")
    assert cmd[idx + 1] == "normal"


# ---------------------------------------------------------------------------
# ProactiveDelivery out_of_call routing
# ---------------------------------------------------------------------------

def _item(priority: int) -> "ProactiveItem":  # noqa: F821
    from iris.proactive_store import ProactiveItem
    return ProactiveItem(
        id=1, trigger_class="test", priority=priority,
        message="test event", source_skill="test", source_id="s-1",
        created_at=time.time(), expires_at=time.time() + 86400,
        delivered_at=None, dismissed=False,
    )


def _out_of_call_delivery(priority: int = 1, cooldown_s: float = 0.0):
    from iris.config import Config
    from iris.mode import IrisMode
    from iris.proactive_delivery import ProactiveDelivery, SilenceTracker

    store = MagicMock()
    store.next_pending.return_value = _item(priority)
    store.pending_count.return_value = 1
    sink = MagicMock(spec=DesktopNotifySink)
    cfg = Config(
        proactive_enabled=True,
        proactive_classes=("test",),
        proactive_cooldown_s=cooldown_s,
    )
    d = ProactiveDelivery(
        store=store,
        tts_fn=MagicMock(),
        emit=[].append,
        cfg=cfg,
        silence_tracker=SilenceTracker(),
        iris_mode_fn=lambda: IrisMode.OUT_OF_CALL,
        notify_sink=sink,
    )
    return d, store, sink


def test_p0_event_triggers_critical_notify():
    d, _store, sink = _out_of_call_delivery(priority=0)
    d.tick()
    sink.notify.assert_called_once()
    _args, kwargs = sink.notify.call_args
    assert kwargs.get("urgency") == "critical"


def test_p1_event_triggers_normal_notify():
    d, _store, sink = _out_of_call_delivery(priority=1)
    d.tick()
    sink.notify.assert_called_once()
    _args, kwargs = sink.notify.call_args
    assert kwargs.get("urgency") == "normal"


def test_p2_event_does_not_call_notify_send(tmp_path):
    d, _store, sink = _out_of_call_delivery(priority=2)
    d.tick()
    sink.notify.assert_not_called()


def test_p0_bypasses_cooldown_gate():
    """P0 items bypass the cooldown gate — critical events always notify."""
    from iris.config import Config
    from iris.mode import IrisMode
    from iris.proactive_delivery import ProactiveDelivery, SilenceTracker

    store = MagicMock()
    store.next_pending.return_value = _item(0)
    store.pending_count.return_value = 1
    sink = MagicMock(spec=DesktopNotifySink)
    cfg = Config(proactive_enabled=True, proactive_classes=("test",),
                 proactive_cooldown_s=9999.0)  # very long cooldown
    d = ProactiveDelivery(
        store=store,
        tts_fn=MagicMock(),
        emit=[].append,
        cfg=cfg,
        silence_tracker=SilenceTracker(),
        iris_mode_fn=lambda: IrisMode.OUT_OF_CALL,
        notify_sink=sink,
    )

    d.tick()
    store.next_pending.return_value = _item(0)
    d.tick()  # second tick — P0 should bypass the 9999s cooldown

    # Builder must implement: P0 skips the outer cooldown gate at tick() level
    assert sink.notify.call_count == 2
