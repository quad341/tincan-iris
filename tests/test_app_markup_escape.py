"""Adversarial regression coverage for escape_for_content() call sites in
iris/console/app.py -- ti-l9arm (validator coverage for ti-dqxc1).

ti-dqxc1 swapped 27 call sites in app.py from rich.markup.escape() to
escape_for_content() (see iris/console/_markup.py, fixed for call_card.py by
ti-kpidj / covered by ti-gx6rp). This file does NOT re-test escape_for_content()
itself -- that delta is already pinned in tests/test_call_card_markup_escape.py.
Instead it proves the *call sites* in app.py actually depend on the fix, across
both vulnerable sink families:

  * notify() -> Toast -> Content.from_markup()      (textual/widgets/_toast.py)
  * Static.update() -> visualize() -> Content.from_markup()  (textual/visual.py)

Assertions run text through Content.from_markup(...).plain (for notify(), via
a spy on app.notify) or read back Static.render().plain directly (which IS a
Content instance -- the real post-visualize() state), matching the project's
existing 'survives_markup_rendering' convention (tests/test_console_app.py).

A dedicated section also proves two of these guards are genuine (not vacuous)
by monkeypatching escape_for_content back to rich.markup.escape() -- the
pre-ti-dqxc1 behavior -- and confirming the assertion then fails, same
technique as ti-gx6rp. Finally, one test documents why _w()/RichLog.write()
sinks are a *different, non-vulnerable* family: RichLog renders via Rich's own
Text.from_markup() (see RichLog._make_renderable), which shares
rich.markup.escape()'s narrow '[' grammar and never swallows this content
regardless of which escape function produced it.
"""
from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from rich.markup import escape as rich_escape  # noqa: E402
from textual.content import Content  # noqa: E402

import iris.console.app as app_module  # noqa: E402
from iris.console.app import IncomingCallPanel, IrisConsole  # noqa: E402


def _plain(markup: str) -> str:
    return Content.from_markup(markup).plain


# ---------------------------------------------------------------------------
# notify() (Toast) sinks -- adversarial coverage
# ---------------------------------------------------------------------------

def test_incoming_call_notify_preserves_bracket_caller_name():
    """app.py:~766-769 -- _on_daemon_event('incoming_call') notifies with the
    CNAM/SIP-derived caller name, not fully trusted."""
    async def scenario():
        app = IrisConsole()
        notified: list[tuple] = []
        app.notify = lambda *a, **kw: notified.append((a, kw))
        async with app.run_test() as pilot:
            app._on_daemon_event({
                "event": "incoming_call",
                "caller_name": "[$50] Corp",
                "caller_number": "",
                "choices": [],
            })
            assert len(notified) == 1
            args, kwargs = notified[0]
            assert _plain(args[0]) == "Incoming call: [$50] Corp"
            assert kwargs.get("severity") == "warning"
            await pilot.press("q")

    asyncio.run(scenario())


def test_arm_trust_notify_preserves_adversarial_tag_shaped_name():
    """app.py:~1234-1236 -- _do_arm_trust()'s toast. Complements the existing
    safe-name coverage in test_console_app.py::test_do_arm_trust_hints_survive_markup_rendering
    with a fake-tag-shaped contact name: it must show up literally, not be
    interpreted as bold-red styling nor silently dropped."""
    async def scenario():
        app = IrisConsole()
        notified: list[tuple] = []
        app.notify = lambda *a, **kw: notified.append((a, kw))
        async with app.run_test() as pilot:
            app._call_contact_name = "[bold red]Mallory[/bold red]"
            app._do_arm_trust()

            assert len(notified) == 1
            args, _kwargs = notified[0]
            assert _plain(args[0]) == (
                "Trust armed for [bold red]Mallory[/bold red]; press [g] to grant"
            )
            await pilot.press("q")

    asyncio.run(scenario())


def test_choice_notify_preserves_bracket_label():
    """app.py:~1394-1395 -- _send_choose()'s toast interpolates the daemon-
    supplied choice label."""
    async def scenario():
        app = IrisConsole()
        notified: list[tuple] = []
        app.notify = lambda *a, **kw: notified.append((a, kw))
        async with app.run_test() as pilot:
            app._incoming_call_id = "call-1"
            app._incoming_choices = [{"label": "[$25] fee waiver", "id": "a1"}]
            app._proxy = None  # force direct mode -- no daemon send() to mock

            app._send_choose(1)

            assert len(notified) == 1
            args, _kwargs = notified[0]
            assert _plain(args[0]) == "Choice: [$25] fee waiver"
            await pilot.press("q")

    asyncio.run(scenario())


def test_clipboard_error_notify_preserves_bracket_content():
    """app.py:~1330-1334 -- _copy_text_to_clipboard()'s error toast interpolates
    str(exc) from a failed clipboard subprocess, which can itself contain
    bracket-shaped text (argv reprs, tool-specific error output)."""
    from unittest.mock import MagicMock, patch

    async def scenario():
        app = IrisConsole()
        app.copy_to_clipboard = MagicMock()  # OSC52 leg: succeeds, no exception
        notified: list[tuple] = []
        app.notify = lambda *a, **kw: notified.append((a, kw))
        async with app.run_test() as pilot:
            with patch("iris.console.app.subprocess.run") as mock_run:
                mock_run.side_effect = [
                    MagicMock(returncode=0),  # `which wl-copy` found
                    Exception("exit [1] nonzero"),  # copy subprocess fails
                ]
                app._copy_text_to_clipboard("hello")

            assert len(notified) == 1
            args, kwargs = notified[0]
            assert _plain(args[0]) == "Clipboard error: exit [1] nonzero"
            assert kwargs.get("severity") == "error"
            await pilot.press("q")

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Static.update() sinks (IncomingCallPanel) -- adversarial coverage
#
# Reads back via widget.render().plain rather than re-deriving
# Content.from_markup() ourselves -- render() returns the actual Content
# instance produced by Static.update()'s visualize() call, i.e. the real
# post-parse state, not a re-simulation of it.
# ---------------------------------------------------------------------------

def test_incoming_call_panel_show_preserves_bracket_content_in_all_fields():
    """app.py:~357-370 -- IncomingCallPanel.show() interpolates verb,
    caller_name/caller_number, and choice labels into four Static.update()
    sinks. Each is CNAM/SIP- or daemon-classification-derived and not fully
    trusted; bracket- and fake-tag-shaped content in any of them must round-
    trip unchanged."""
    from textual.widgets import Static

    async def scenario():
        app = IrisConsole()
        async with app.run_test() as pilot:
            panel = app.query_one(IncomingCallPanel)
            panel.show(
                "[50%] priority",
                "[$50] Corp",
                "+15551234567",
                [{"key": "1", "label": "[bold red]Accept[/bold red]"}],
            )

            header = panel.query_one("#call-header", Static).render()
            caller = panel.query_one("#call-caller", Static).render()
            choices = panel.query_one("#call-choices", Static).render()

            assert header.plain == "📞 INCOMING CALL — [50%] priority"
            assert caller.plain == "[$50] Corp  ·  +15551234567"
            assert choices.plain == "[1] [bold red]Accept[/bold red]"

            await pilot.press("q")

    asyncio.run(scenario())


def test_incoming_call_panel_update_intro_preserves_bracket_content():
    """app.py:~373-375 -- the screening intro transcript is literally what the
    caller said during the auto-screen window: fully caller-controlled."""
    from textual.widgets import Static

    async def scenario():
        app = IrisConsole()
        async with app.run_test() as pilot:
            panel = app.query_one(IncomingCallPanel)
            panel.update_intro("yes I owe [$1200] on account")

            intro = panel.query_one("#call-intro", Static).render()
            assert intro.plain == 'Caller: "yes I owe [$1200] on account"'

            await pilot.press("q")

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Regression-guard genuineness proof (monkeypatch-revert, ti-gx6rp technique)
#
# Reverts escape_for_content -> rich.markup.escape (the pre-ti-dqxc1 behavior)
# at the app.py module level and confirms a representative assertion from
# each sink family above then FAILS -- proving these guards actually depend
# on the fix rather than passing incidentally.
# ---------------------------------------------------------------------------

def test_incoming_call_notify_regression_guard_is_real(monkeypatch):
    monkeypatch.setattr(app_module, "escape_for_content", rich_escape)

    async def scenario():
        app = IrisConsole()
        notified: list[tuple] = []
        app.notify = lambda *a, **kw: notified.append((a, kw))
        async with app.run_test() as pilot:
            app._on_daemon_event({
                "event": "incoming_call",
                "caller_name": "[$50] Corp",
                "caller_number": "",
                "choices": [],
            })
            assert "[$50] Corp" in _plain(notified[0][0][0])
            await pilot.press("q")

    with pytest.raises(AssertionError):
        asyncio.run(scenario())


def test_incoming_call_panel_show_regression_guard_is_real(monkeypatch):
    monkeypatch.setattr(app_module, "escape_for_content", rich_escape)

    async def scenario():
        from textual.widgets import Static

        app = IrisConsole()
        async with app.run_test() as pilot:
            panel = app.query_one(IncomingCallPanel)
            panel.show("announce", "[$50] Corp", "", [])
            assert "[$50] Corp" in panel.query_one("#call-caller", Static).render().plain
            await pilot.press("q")

    with pytest.raises(AssertionError):
        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# RichLog (_w()/log.write()) sinks -- confirmed NOT part of this vulnerability
# class. Documented here (rather than asserted only in a code comment) so a
# future change that made this assumption false would be caught.
# ---------------------------------------------------------------------------

def test_w_sink_unaffected_by_choice_of_escape_function():
    """_w() writes through RichLog(markup=True), which renders via Rich's own
    Text.from_markup() (RichLog._make_renderable), not Textual's
    Content.from_markup(). Rich's tokenizer shares rich.markup.escape()'s
    narrow '[' grammar, so an unescaped '[$50]'-shaped span is never swallowed
    here -- escape_for_content() and plain rich.markup.escape() produce
    IDENTICAL, correct output. Contrast with the notify()/Static.update()
    tests above, where the choice of escape function changes the result."""
    from rich.text import Text

    from iris.console._markup import escape_for_content

    for raw in ("[$50] safe?", "[50%] safe?", "café said [$50] more", "[12345] safe?"):
        via_rich_escape = Text.from_markup(rich_escape(raw)).plain
        via_escape_for_content = Text.from_markup(escape_for_content(raw)).plain
        assert via_rich_escape == via_escape_for_content == raw
