"""Smoke test for the Textual console — verifies the app mounts and a key wires
through to the Conductor. Skipped when textual isn't installed (it's an optional
extra; the pipeline logic itself is covered in test_conductor). Uses asyncio.run
so no pytest-async plugin is needed."""
from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("textual")

from textual.widgets import Button  # noqa: E402

from iris.console.app import ActiveCallCard, IrisConsole, _GRANT  # noqa: E402
from iris.console.conductor import State  # noqa: E402
from iris.trust import TrustMode  # noqa: E402


def test_console_mounts_and_mute_key_toggles():
    async def scenario():
        app = IrisConsole()
        async with app.run_test() as pilot:
            assert app.conductor.muted is False
            await pilot.press("m")          # mute key -> conductor.toggle_mute
            assert app.conductor.muted is True
            # [a] is now an approve placeholder — does not grant trust
            await pilot.press("a")
            assert app.conductor.far_trust is TrustMode.DEMO
            await pilot.press("f")          # hear respondent (no STT in CI: safe no-op)
            await pilot.press("c")          # dump commands (must not error)
            await pilot.press("q")          # quit

    asyncio.run(scenario())


# --- _on_heard speaking gate (ti-lfp) -----------------------------------------

def test_on_heard_gate_suppresses_when_speaking():
    async def scenario():
        app = IrisConsole()
        async with app.run_test() as pilot:
            # Drain any startup events posted before we start checking.
            while not app.events.empty():
                app.events.get_nowait()

            app.conductor.state = State.SPEAKING
            assert app.conductor.speaking is True
            app._on_heard("hello", "operator")
            # No await between call and assertion — no timer ticks in between.
            assert app.events.empty()

            app.conductor.state = State.IDLE
            assert app.conductor.speaking is False
            app._on_heard("hello", "operator")
            assert app.events.get_nowait() == ("heard", "hello", "operator")

            await pilot.press("q")

    asyncio.run(scenario())


def test_on_heard_gate_suppresses_when_thinking():
    async def scenario():
        app = IrisConsole()
        async with app.run_test() as pilot:
            while not app.events.empty():
                app.events.get_nowait()

            app.conductor.state = State.THINKING
            assert app.conductor.speaking is True
            app._on_heard("what time is it", "operator")
            assert app.events.empty()

            await pilot.press("q")

    asyncio.run(scenario())


# --- _GRANT regex and trust spoof-block (ti-hr2) ------------------------------


def test_grant_regex_matches_expected_phrases():
    assert _GRANT.match("grant full access")
    assert _GRANT.match("give full access")
    assert _GRANT.match("allow full access")
    assert _GRANT.match("trust full access")
    assert _GRANT.match("grant them full access")
    assert _GRANT.match("  grant full access")


def test_grant_regex_rejects_false_positives():
    assert not _GRANT.match("give him directions")
    assert not _GRANT.match("allow her to speak")
    assert not _GRANT.match("give him full details")
    assert not _GRANT.match("grant access")
    assert not _GRANT.match("grant her full")


def test_operator_spoken_grant_no_longer_elevates_far_trust():
    """Spoken 'grant full access' must NOT elevate far trust (removed for security, ti-qt1i.1.1).
    Trust elevation now requires the physical ARM TRUST button or [g] key."""
    async def scenario():
        app = IrisConsole()
        async with app.run_test() as pilot:
            assert app.conductor.far_trust is TrustMode.DEMO
            app._on_heard_main("hey Iris, grant full access", "operator")
            assert app.conductor.far_trust is TrustMode.DEMO  # spoken grant no longer works
            await pilot.press("q")

    asyncio.run(scenario())


def test_grant_command_ignored_from_far_speaker():
    """speaker='far' in _on_heard_main must not elevate trust even with the grant phrase."""
    async def scenario():
        app = IrisConsole()
        async with app.run_test() as pilot:
            app.conductor.state = State.SPEAKING  # prevent dispatch worker
            assert app.conductor.far_trust is TrustMode.DEMO
            app._on_heard_main("hey Iris, grant full access", "far")
            assert app.conductor.far_trust is TrustMode.DEMO
            await pilot.press("q")

    asyncio.run(scenario())


def test_far_routing_path_cannot_grant():
    """_on_heard_far_main has no grant branch — far party cannot escalate trust."""
    async def scenario():
        app = IrisConsole()
        async with app.run_test() as pilot:
            app.conductor.state = State.SPEAKING  # prevent dispatch worker
            assert app.conductor.far_trust is TrustMode.DEMO
            app._on_heard_far_main("hey Iris, grant full access", "far")
            assert app.conductor.far_trust is TrustMode.DEMO
            await pilot.press("q")

    asyncio.run(scenario())


def test_action_far_disconnect_resets_far_trust():
    """Toggling off the far stream (hangup) resets far_trust to DEMO."""
    from unittest.mock import MagicMock

    async def scenario():
        app = IrisConsole()
        async with app.run_test() as pilot:
            app.conductor.grant_far()
            assert app.conductor.far_trust is TrustMode.FULL
            app._far_stream = MagicMock()
            await pilot.press("f")
            assert app.conductor.far_trust is TrustMode.DEMO
            await pilot.press("q")

    asyncio.run(scenario())


# --- ti-n1a: Iris converses with the far party by default (DEMO) --------------


def test_far_party_demo_dispatched_without_grant():
    """A far-party "Iris, …" is dispatched by default — not blocked on approval.

    The console no longer pre-gates the far party; the brain restricts DEMO to
    safe conversation (see test_brain). So with no grant, the command must still
    reach _dispatch tagged speaker="far".
    """
    async def scenario():
        app = IrisConsole()
        async with app.run_test() as pilot:
            assert app.conductor.far_trust is TrustMode.DEMO  # never granted
            seen = []
            app._dispatch = lambda cmd, speaker="": seen.append((cmd, speaker)) or True
            app._on_heard_far_main("hey Iris, what time is it?", "far")
            assert len(seen) == 1
            cmd, spk = seen[0]
            assert spk == "far" and "time" in cmd.lower()  # dispatched, not blocked
            await pilot.press("q")

    asyncio.run(scenario())


def test_approve_key_is_placeholder_no_trust_change():
    """[a] is now a placeholder for a future approve workflow, not a grant key.
    Trust stays DEMO after pressing [a]; grant is [g] after physical ARM TRUST."""
    async def scenario():
        app = IrisConsole()
        async with app.run_test() as pilot:
            assert app.conductor.far_trust is TrustMode.DEMO
            await pilot.press("a")
            assert app.conductor.far_trust is TrustMode.DEMO  # [a] is a no-op for trust
            await pilot.press("q")

    asyncio.run(scenario())


# --- ARM TRUST card flow (ti-3qgj) -------------------------------------------


def test_active_call_card_shows_on_call_connected():
    """ARM TRUST card becomes visible after call_connected when contact is trust-eligible."""
    async def scenario():
        app = IrisConsole()
        async with app.run_test() as pilot:
            app._call_contact_name = "Alice"
            app._call_trust_eligible = True

            app.events.put(("call_connected",))
            app._drain()

            card = app.query_one(ActiveCallCard)
            assert "visible" in card.classes

            await pilot.press("q")

    asyncio.run(scenario())


def test_arm_trust_button_arms_conductor():
    """Pressing the ARM TRUST button (or calling _do_arm_trust) calls conductor.arm()."""
    async def scenario():
        app = IrisConsole()
        async with app.run_test() as pilot:
            app._call_contact_name = "Bob"
            app._call_trust_eligible = True
            app.events.put(("call_connected",))
            app._drain()

            assert not app.conductor._armed
            app._do_arm_trust()
            assert app.conductor._armed

            await pilot.press("q")

    asyncio.run(scenario())


def test_far_trust_event_shows_armed_badge():
    """Receiving far_trust=BOTH while card is visible hides the button and shows badge."""
    async def scenario():
        app = IrisConsole()
        async with app.run_test() as pilot:
            app._call_contact_name = "Bob"
            app._call_trust_eligible = True
            app.events.put(("call_connected",))
            app._drain()

            app.conductor.grant_far()  # _trust=BOTH so far_trust=BOTH/FULL
            app.events.put(("far_trust", app.conductor.far_trust))
            app._drain()

            card = app.query_one(ActiveCallCard)
            btn = card.query_one("#arm-trust-btn", Button)
            assert btn.display is False  # button hidden after arming

            await pilot.press("q")

    asyncio.run(scenario())


def test_call_ended_hides_active_call_card():
    """call_ended event hides the ARM TRUST card and clears call state."""
    async def scenario():
        app = IrisConsole()
        async with app.run_test() as pilot:
            app._call_contact_name = "Carol"
            app._call_trust_eligible = True
            app.events.put(("call_connected",))
            app._drain()

            card = app.query_one(ActiveCallCard)
            assert "visible" in card.classes

            app.events.put(("call_ended", "session-abc"))
            app._drain()

            assert "visible" not in card.classes
            assert not app._in_call
            assert app._call_contact_name == ""

            await pilot.press("q")

    asyncio.run(scenario())


# --- call mic mute + far-party downlink gate (ti-gbz4.1, ti-gbz4.2) --------


def test_call_connected_auto_mutes_unmuted_conductor():
    """call_connected mutes an unmuted conductor and records _pre_call_muted=False."""
    async def scenario():
        app = IrisConsole()
        async with app.run_test() as pilot:
            assert app.conductor.muted is False
            app.events.put(("call_connected",))
            app._drain()
            assert app._in_call is True
            assert app._pre_call_muted is False
            assert app.conductor.muted is True
            await pilot.press("q")

    asyncio.run(scenario())


def test_call_connected_preserves_already_muted_state():
    """call_connected records _pre_call_muted=True and does not double-toggle when already muted."""
    async def scenario():
        app = IrisConsole()
        async with app.run_test() as pilot:
            app.conductor.toggle_mute()
            assert app.conductor.muted is True
            app.events.put(("call_connected",))
            app._drain()
            assert app._pre_call_muted is True
            assert app.conductor.muted is True
            await pilot.press("q")

    asyncio.run(scenario())


def test_call_ended_restores_unmuted_pre_call_state():
    """call_ended unmutes the conductor when the operator was not muted before the call."""
    async def scenario():
        app = IrisConsole()
        async with app.run_test() as pilot:
            assert app.conductor.muted is False
            app.events.put(("call_connected",))
            app._drain()
            assert app.conductor.muted is True  # auto-muted at call start

            app.events.put(("call_ended", "session-x"))
            app._drain()
            assert app.conductor.muted is False  # restored to pre-call state
            assert app._in_call is False
            await pilot.press("q")

    asyncio.run(scenario())


def test_call_ended_preserves_muted_state_when_pre_call_was_muted():
    """call_ended does not unmute when the operator was already muted before the call."""
    async def scenario():
        app = IrisConsole()
        async with app.run_test() as pilot:
            app.conductor.toggle_mute()
            assert app.conductor.muted is True
            app.events.put(("call_connected",))
            app._drain()
            assert app._pre_call_muted is True

            app.events.put(("call_ended", "session-y"))
            app._drain()
            assert app.conductor.muted is True  # stays muted — was muted before call
            await pilot.press("q")

    asyncio.run(scenario())


def test_call_connected_stops_active_far_stream():
    """call_connected stops and clears an active far-party stream (ti-gbz4.2)."""
    from unittest.mock import MagicMock

    async def scenario():
        app = IrisConsole()
        async with app.run_test() as pilot:
            mock_stream = MagicMock()
            app._far_stream = mock_stream
            app.events.put(("call_connected",))
            app._drain()
            mock_stream.stop.assert_called_once()
            assert app._far_stream is None
            await pilot.press("q")

    asyncio.run(scenario())


def test_on_heard_far_main_suppressed_during_call():
    """_on_heard_far_main returns early during an active call — far commands are not dispatched."""
    async def scenario():
        app = IrisConsole()
        async with app.run_test() as pilot:
            dispatched = []
            app._dispatch = lambda cmd, speaker="": dispatched.append((cmd, speaker)) or True
            app._in_call = True
            app._on_heard_far_main("Iris, what time is it?", "far")
            assert dispatched == []
            await pilot.press("q")

    asyncio.run(scenario())


def test_action_far_blocked_during_call():
    """[f] is a no-op during a call — does not start a far stream."""
    async def scenario():
        app = IrisConsole()
        async with app.run_test() as pilot:
            app._in_call = True
            assert app._far_stream is None
            await pilot.press("f")
            assert app._far_stream is None
            await pilot.press("q")

    asyncio.run(scenario())
