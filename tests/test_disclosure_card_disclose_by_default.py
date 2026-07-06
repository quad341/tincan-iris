"""DisclosureCard/CallCardPanel disclose-by-default coverage (ti-tk06c, design: ti-n9vey).

Builder implemented the disclose-by-default redesign (state rename EXPANDED ->
DISCLOSING, apply_daemon_state() reconciliation, focus-trap removal, 12s stall
escalation) without authoring new tests, per role boundaries. This file adds the
4 scenarios ti-n9vey's design doc (§6) calls out as the resulting new coverage:

1. apply_daemon_state(): no-op on a matching state (zero flicker, no disk
   write) vs. an actual transition + persistence on a mismatched state.
2. CallCardPanel.suppress_active_disclosure() reaches the active card's
   action_skip() even when that card does not have focus -- the exact case
   the new global [S] binding exists to cover.
3. Tab / Shift+Tab navigation actually leaves DisclosureCard while it is
   still DISCLOSING (negative test for the removed focus trap).
4. _on_stalled() only flips to the amber "stalled" presentation while still
   DISCLOSING; no-ops if the card already resolved before the 12s timer fired.
"""
from __future__ import annotations

import asyncio
import json

from textual.app import App, ComposeResult

from iris.console import call_card
from iris.console.call_card import CallCardPanel, DisclosureCard, DisclosureState


def _card(monkeypatch, tmp_path, session_id="s1"):
    # Redirect disk persistence away from the real ~/.local/share/iris.
    monkeypatch.setattr(call_card, "_STATE_DIR", tmp_path)
    card = DisclosureCard(session_id)
    posted: list = []
    monkeypatch.setattr(card, "post_message", lambda msg: posted.append(msg))
    return card, posted


# ─────────────────────────────────────────────────────────────────
# 1. apply_daemon_state() -- no-op on match, transition + persist on mismatch
# ─────────────────────────────────────────────────────────────────

def test_apply_daemon_state_noop_when_matching_current_state(monkeypatch, tmp_path):
    card, posted = _card(monkeypatch, tmp_path)
    card.action_disclose()  # DISCLOSING -> DISCLOSED
    assert len(posted) == 1

    save_calls: list = []
    refresh_calls: list = []
    monkeypatch.setattr(card, "_save_state", lambda: save_calls.append(True))
    monkeypatch.setattr(card, "refresh", lambda *a, **kw: refresh_calls.append(True))

    card.apply_daemon_state(DisclosureState.DISCLOSED)  # daemon echoes the same state

    assert save_calls == []
    assert refresh_calls == []
    assert card.state is DisclosureState.DISCLOSED
    assert len(posted) == 1  # no extra message re-posted to the daemon


def test_apply_daemon_state_transitions_and_persists_on_mismatch(monkeypatch, tmp_path):
    card, posted = _card(monkeypatch, tmp_path)
    assert card.state is DisclosureState.DISCLOSING

    card.apply_daemon_state(DisclosureState.SKIPPED)

    assert card.state is DisclosureState.SKIPPED
    assert card.has_class("-badge")
    on_disk = json.loads(card._state_path().read_text(encoding="utf-8"))
    assert on_disk["state"] == "skipped"
    assert posted == []  # reconciliation never posts operator-style messages


# ─────────────────────────────────────────────────────────────────
# 2. CallCardPanel.suppress_active_disclosure() reaches an unfocused card
# ─────────────────────────────────────────────────────────────────

def test_suppress_active_disclosure_skips_unfocused_card(monkeypatch, tmp_path):
    card, posted = _card(monkeypatch, tmp_path)
    assert card.has_focus is False  # operator navigated elsewhere; [S] must still land

    panel = CallCardPanel()
    panel._disclosure_card = card

    panel.suppress_active_disclosure()

    assert card.state is DisclosureState.SKIPPED
    assert len(posted) == 1
    assert posted[0].session_id == "s1"


def test_suppress_active_disclosure_is_noop_without_an_active_card():
    panel = CallCardPanel()  # no call_card_disclosure_needed event yet -> None
    panel.suppress_active_disclosure()  # must not raise


# ─────────────────────────────────────────────────────────────────
# 3. Tab / Shift+Tab actually leave DisclosureCard while DISCLOSING
# ─────────────────────────────────────────────────────────────────

class _Harness(App):
    def compose(self) -> ComposeResult:
        yield CallCardPanel(id="call-card-panel")


def test_tab_and_shift_tab_leave_disclosure_card_while_disclosing(monkeypatch, tmp_path):
    monkeypatch.setattr(call_card, "_STATE_DIR", tmp_path)

    async def scenario():
        app = _Harness()
        async with app.run_test(size=(120, 40)) as pilot:
            panel = app.query_one(CallCardPanel)
            panel.handle_event({
                "event": "call_card_disclosure_needed", "session_id": "s1", "script": "hi",
            })
            panel.handle_event({
                "event": "call_card_fact", "session_id": "s1",
                "fact": {"session_id": "s1", "fact_type": "amount", "raw_text": "$5",
                         "normalized_value": "$5.00", "critical": False, "confidence": 0.9},
            })
            await pilot.pause()

            card = panel._disclosure_card
            assert card.state is DisclosureState.DISCLOSING

            card.focus()
            await pilot.pause()
            assert app.focused is card

            await pilot.press("tab")
            await pilot.pause()
            assert app.focused is not card
            assert card.state is DisclosureState.DISCLOSING  # tabbing away resolves nothing

            card.focus()
            await pilot.pause()
            assert app.focused is card

            await pilot.press("shift+tab")
            await pilot.pause()
            assert app.focused is not card

    asyncio.run(scenario())


# ─────────────────────────────────────────────────────────────────
# 4. _on_stalled() -- amber escalation only while still DISCLOSING
# ─────────────────────────────────────────────────────────────────

def test_on_stalled_flips_stalled_while_still_disclosing(monkeypatch, tmp_path):
    card, _ = _card(monkeypatch, tmp_path)
    assert card.state is DisclosureState.DISCLOSING
    assert card._stalled is False

    card._on_stalled()

    assert card._stalled is True
    assert card.has_class("-stalled")


def test_on_stalled_is_noop_once_already_resolved(monkeypatch, tmp_path):
    card, _ = _card(monkeypatch, tmp_path)
    card.action_disclose()  # resolved to DISCLOSED before the 12s timer fires
    assert card._stalled is False

    card._on_stalled()

    assert card._stalled is False
    assert not card.has_class("-stalled")
