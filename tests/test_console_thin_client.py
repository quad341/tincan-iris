"""Tests for console thin-client mode: proxy path, direct path, and disconnect fallback.

Covers ti-s9mm.3.3 acceptance criteria:
  1. Proxy mode startup — DaemonProxy.connect() succeeds → _proxy set, correct log
  2. Direct mode startup — DaemonProxy raises DaemonNotRunning → ctrl.start(), direct pill
  3. Proxy turn routing — _dispatch() calls proxy.send(stream_turn); brain_chunk renders
  4. Disconnect fallback — disconnected event → ctrl.start(), "switched" log, direct pill
  5. Status pill content — text label "daemon"/"direct" present (not emoji-only, SC 1.4.1)

Tests are intentionally RED until ti-s9mm.3.1 and ti-s9mm.3.2 are built.
No Qwen/network calls; DaemonProxy and TincanCallControl are mocked throughout.
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("textual")

from textual.widgets import Static  # noqa: E402

from iris.console.app import IrisConsole  # noqa: E402
from iris.daemon.proxy import DaemonNotRunning  # noqa: E402


# ── helpers ───────────────────────────────────────────────────────────────────────


def _proxy_ok():
    """MagicMock DaemonProxy whose connect() succeeds (proxy mode)."""
    p = MagicMock()
    p.connect.return_value = None
    return p


def _proxy_down():
    """MagicMock DaemonProxy whose connect() raises DaemonNotRunning (direct mode)."""
    p = MagicMock()
    p.connect.side_effect = DaemonNotRunning("no daemon socket")
    return p


def _get_status_content(app: IrisConsole) -> str:
    """Call _refresh_status() and return the #status widget content as a string."""
    app._refresh_status()
    return app.query_one("#status", Static).content


# ── 1. Proxy mode startup ─────────────────────────────────────────────────────────


def test_proxy_mode_startup_sets_proxy():
    """DaemonProxy.connect() succeeds → app._proxy is the proxy instance."""

    async def scenario():
        mock_proxy = _proxy_ok()
        with patch("iris.console.app.DaemonProxy", return_value=mock_proxy):
            app = IrisConsole()
            async with app.run_test() as pilot:
                assert app._proxy is mock_proxy
                await pilot.press("q")

    asyncio.run(scenario())


def test_proxy_mode_startup_log_says_brain_turns_via_socket():
    """Proxy startup log must say 'brain turns via socket' (ti-s9mm.3.1 spec)."""

    async def scenario():
        mock_proxy = _proxy_ok()
        written = []
        with patch("iris.console.app.DaemonProxy", return_value=mock_proxy):
            app = IrisConsole()
            app._w = lambda msg: written.append(msg)
            async with app.run_test() as pilot:
                assert any("brain turns via socket" in m for m in written), (
                    f"Expected 'brain turns via socket' in startup log; got: {written}"
                )
                await pilot.press("q")

    asyncio.run(scenario())


def test_proxy_mode_ctrl_not_started():
    """In proxy mode TincanCallControl.start() must NOT be called (call events arrive via daemon)."""

    async def scenario():
        mock_proxy = _proxy_ok()
        with patch("iris.console.app.DaemonProxy", return_value=mock_proxy), \
             patch("iris.console.app.TincanCallControl") as MockCtrl:
            mock_ctrl = MagicMock()
            MockCtrl.return_value = mock_ctrl
            app = IrisConsole()
            async with app.run_test() as pilot:
                mock_ctrl.start.assert_not_called()
                await pilot.press("q")

    asyncio.run(scenario())


# ── 2. Direct mode startup ────────────────────────────────────────────────────────


def test_direct_mode_startup_proxy_is_none():
    """DaemonProxy.connect() raises DaemonNotRunning → app._proxy is None."""

    async def scenario():
        mock_proxy = _proxy_down()
        with patch("iris.console.app.DaemonProxy", return_value=mock_proxy), \
             patch("iris.console.app.TincanCallControl") as MockCtrl:
            MockCtrl.return_value = MagicMock()
            app = IrisConsole()
            async with app.run_test() as pilot:
                assert app._proxy is None
                await pilot.press("q")

    asyncio.run(scenario())


def test_direct_mode_startup_ctrl_started():
    """In direct mode TincanCallControl.start() is called on startup."""

    async def scenario():
        mock_proxy = _proxy_down()
        with patch("iris.console.app.DaemonProxy", return_value=mock_proxy), \
             patch("iris.console.app.TincanCallControl") as MockCtrl:
            mock_ctrl = MagicMock()
            MockCtrl.return_value = mock_ctrl
            app = IrisConsole()
            async with app.run_test() as pilot:
                mock_ctrl.start.assert_called_once()
                await pilot.press("q")

    asyncio.run(scenario())


def test_direct_mode_brain_instantiated():
    """In direct mode app.brain is a real Brain instance (not None)."""

    async def scenario():
        mock_proxy = _proxy_down()
        with patch("iris.console.app.DaemonProxy", return_value=mock_proxy), \
             patch("iris.console.app.TincanCallControl") as MockCtrl:
            MockCtrl.return_value = MagicMock()
            app = IrisConsole()
            async with app.run_test() as pilot:
                assert app.brain is not None
                await pilot.press("q")

    asyncio.run(scenario())


# ── 3. Proxy turn routing ─────────────────────────────────────────────────────────


def test_proxy_dispatch_sends_stream_turn_cmd():
    """_dispatch() in proxy mode calls proxy.send({'cmd':'stream_turn',...})."""

    async def scenario():
        mock_proxy = _proxy_ok()
        with patch("iris.console.app.DaemonProxy", return_value=mock_proxy):
            app = IrisConsole()
            async with app.run_test() as pilot:
                mock_proxy.send.reset_mock()
                app._dispatch("what time is it", "operator")
                mock_proxy.send.assert_called_once_with({
                    "cmd": "stream_turn",
                    "text": "what time is it",
                    "speaker": "operator",
                })
                await pilot.press("q")

    asyncio.run(scenario())


def test_proxy_brain_chunk_renders_in_richlog():
    """daemon_event brain_chunk → _w called with the chunk text (renders in RichLog)."""

    async def scenario():
        mock_proxy = _proxy_ok()
        written = []
        with patch("iris.console.app.DaemonProxy", return_value=mock_proxy):
            app = IrisConsole()
            app._w = lambda msg: written.append(msg)
            async with app.run_test() as pilot:
                written.clear()
                app.events.put(("daemon_event", {"event": "brain_chunk", "text": "It is 3pm."}))
                app._drain()
                assert any("It is 3pm." in m for m in written), (
                    f"Expected chunk text in log; got: {written}"
                )
                await pilot.press("q")

    asyncio.run(scenario())


def test_proxy_brain_turn_started_sets_thinking_flag():
    """brain_turn_started event sets app._thinking = True."""

    async def scenario():
        mock_proxy = _proxy_ok()
        with patch("iris.console.app.DaemonProxy", return_value=mock_proxy):
            app = IrisConsole()
            async with app.run_test() as pilot:
                app.events.put(("daemon_event", {"event": "brain_turn_started"}))
                app._drain()
                assert app._thinking is True
                await pilot.press("q")

    asyncio.run(scenario())


def test_proxy_brain_turn_started_logs_thinking_hint():
    """brain_turn_started logs a thinking hint to RichLog (SC 4.1.3 a11y requirement)."""

    async def scenario():
        mock_proxy = _proxy_ok()
        written = []
        with patch("iris.console.app.DaemonProxy", return_value=mock_proxy):
            app = IrisConsole()
            app._w = lambda msg: written.append(msg)
            async with app.run_test() as pilot:
                written.clear()
                app.events.put(("daemon_event", {"event": "brain_turn_started"}))
                app._drain()
                assert any("thinking" in m.lower() for m in written), (
                    f"Expected 'thinking' hint in log after brain_turn_started; got: {written}"
                )
                await pilot.press("q")

    asyncio.run(scenario())


def test_proxy_brain_reply_clears_thinking_flag():
    """brain_reply event sets app._thinking = False and logs the reply text."""

    async def scenario():
        mock_proxy = _proxy_ok()
        written = []
        with patch("iris.console.app.DaemonProxy", return_value=mock_proxy):
            app = IrisConsole()
            app._w = lambda msg: written.append(msg)
            async with app.run_test() as pilot:
                app._thinking = True
                written.clear()
                app.events.put(("daemon_event", {
                    "event": "brain_reply",
                    "text": "Done.",
                    "lane": "tier1",
                    "elapsed_ms": 850,
                }))
                app._drain()
                assert app._thinking is False
                assert any("Done." in m for m in written), (
                    f"Expected reply text in log; got: {written}"
                )
                await pilot.press("q")

    asyncio.run(scenario())


def test_proxy_send_error_triggers_disconnect_fallback():
    """If proxy.send raises DaemonNotRunning, the console falls back to direct mode."""

    async def scenario():
        mock_proxy = _proxy_ok()
        mock_proxy.send.side_effect = DaemonNotRunning("connection lost")
        with patch("iris.console.app.DaemonProxy", return_value=mock_proxy), \
             patch("iris.console.app.TincanCallControl") as MockCtrl:
            MockCtrl.return_value = MagicMock()
            app = IrisConsole()
            async with app.run_test() as pilot:
                assert app._proxy is not None  # sanity
                app._dispatch("what time is it", "operator")
                # After send raises, disconnect path should clear _proxy
                assert app._proxy is None, "send error must trigger disconnect fallback"
                await pilot.press("q")

    asyncio.run(scenario())


# ── 4. Disconnect fallback ────────────────────────────────────────────────────────


def test_disconnect_fallback_clears_proxy():
    """disconnected daemon event → app._proxy = None."""

    async def scenario():
        mock_proxy = _proxy_ok()
        with patch("iris.console.app.DaemonProxy", return_value=mock_proxy), \
             patch("iris.console.app.TincanCallControl") as MockCtrl:
            MockCtrl.return_value = MagicMock()
            app = IrisConsole()
            async with app.run_test() as pilot:
                assert app._proxy is not None
                app.events.put(("daemon_event", {"event": "disconnected"}))
                app._drain()
                assert app._proxy is None
                await pilot.press("q")

    asyncio.run(scenario())


def test_disconnect_fallback_starts_ctrl():
    """disconnected event activates direct mode: ctrl.start() is called."""

    async def scenario():
        mock_proxy = _proxy_ok()
        with patch("iris.console.app.DaemonProxy", return_value=mock_proxy), \
             patch("iris.console.app.TincanCallControl") as MockCtrl:
            mock_ctrl = MagicMock()
            MockCtrl.return_value = mock_ctrl
            app = IrisConsole()
            async with app.run_test() as pilot:
                mock_ctrl.start.assert_not_called()  # not called in proxy mode
                app.events.put(("daemon_event", {"event": "disconnected"}))
                app._drain()
                mock_ctrl.start.assert_called_once()
                await pilot.press("q")

    asyncio.run(scenario())


def test_disconnect_fallback_logs_switched_message():
    """disconnected event must log 'switched to direct mode' (mandatory — SC 4.1.3)."""

    async def scenario():
        mock_proxy = _proxy_ok()
        written = []
        with patch("iris.console.app.DaemonProxy", return_value=mock_proxy), \
             patch("iris.console.app.TincanCallControl") as MockCtrl:
            MockCtrl.return_value = MagicMock()
            app = IrisConsole()
            app._w = lambda msg: written.append(msg)
            async with app.run_test() as pilot:
                written.clear()
                app.events.put(("daemon_event", {"event": "disconnected"}))
                app._drain()
                assert any("switched to direct mode" in m for m in written), (
                    f"Expected 'switched to direct mode' in log; got: {written}"
                )
                await pilot.press("q")

    asyncio.run(scenario())


def test_disconnect_fallback_next_dispatch_bypasses_proxy():
    """After disconnect, _dispatch() routes via Brain (not proxy.send)."""

    async def scenario():
        mock_proxy = _proxy_ok()
        with patch("iris.console.app.DaemonProxy", return_value=mock_proxy), \
             patch("iris.console.app.TincanCallControl") as MockCtrl:
            MockCtrl.return_value = MagicMock()
            app = IrisConsole()
            async with app.run_test() as pilot:
                app.events.put(("daemon_event", {"event": "disconnected"}))
                app._drain()
                assert app._proxy is None
                mock_proxy.send.reset_mock()
                app._dispatch("what time is it", "operator")
                mock_proxy.send.assert_not_called()
                await pilot.press("q")

    asyncio.run(scenario())


# ── 5. Status pill content ────────────────────────────────────────────────────────


def test_status_pill_daemon_text_in_proxy_mode():
    """Status bar must contain 'daemon' text in proxy mode (SC 1.4.1 — not emoji-only)."""

    async def scenario():
        mock_proxy = _proxy_ok()
        with patch("iris.console.app.DaemonProxy", return_value=mock_proxy):
            app = IrisConsole()
            async with app.run_test() as pilot:
                content = _get_status_content(app)
                assert "daemon" in content, (
                    f"Status pill must contain 'daemon' text in proxy mode; got: {content!r}"
                )
                await pilot.press("q")

    asyncio.run(scenario())


def test_status_pill_direct_text_in_direct_mode():
    """Status bar must contain 'direct' text in direct mode (SC 1.4.1 — not emoji-only)."""

    async def scenario():
        mock_proxy = _proxy_down()
        with patch("iris.console.app.DaemonProxy", return_value=mock_proxy), \
             patch("iris.console.app.TincanCallControl") as MockCtrl:
            MockCtrl.return_value = MagicMock()
            app = IrisConsole()
            async with app.run_test() as pilot:
                content = _get_status_content(app)
                assert "direct" in content, (
                    f"Status pill must contain 'direct' text in direct mode; got: {content!r}"
                )
                await pilot.press("q")

    asyncio.run(scenario())


def test_status_pill_switches_from_daemon_to_direct_after_disconnect():
    """Status bar switches from 'daemon' to 'direct' after the disconnected event."""

    async def scenario():
        mock_proxy = _proxy_ok()
        with patch("iris.console.app.DaemonProxy", return_value=mock_proxy), \
             patch("iris.console.app.TincanCallControl") as MockCtrl:
            MockCtrl.return_value = MagicMock()
            app = IrisConsole()
            async with app.run_test() as pilot:
                pre = _get_status_content(app)
                assert "daemon" in pre, f"Pre-disconnect: status must show 'daemon'; got: {pre!r}"

                app.events.put(("daemon_event", {"event": "disconnected"}))
                app._drain()

                post = _get_status_content(app)
                assert "direct" in post, (
                    f"Post-disconnect: status must show 'direct'; got: {post!r}"
                )
                await pilot.press("q")

    asyncio.run(scenario())
