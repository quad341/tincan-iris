"""DisclosureCard.action_disclose()/action_skip() — Message posting (ti-ir12t).

Previously these actions only mutated local widget state and disk persistence,
with no daemon wiring at all. ti-ir12t adds DisclosureAcknowledged/DisclosureSkipped
Message posting so IrisConsole can forward the operator's choice to the daemon.

The already-resolved guard (both actions no-op once the card has left the
EXPANDED state) means a second call must not re-post -- verified directly here
since a regression would silently double-fire disclosure_ack/disclosure_skip
against the daemon.

Message.handler_name is asserted directly: Textual dispatches by this computed
name, and a mismatch between it and IrisConsole's on_disclosure_acknowledged/
on_disclosure_skipped method names would fail silently (message just bubbles,
no error) -- this was flagged as the highest-risk part of the wiring to get wrong.
"""
from __future__ import annotations

from iris.console import call_card
from iris.console.call_card import (
    DisclosureAcknowledged,
    DisclosureCard,
    DisclosureSkipped,
    DisclosureState,
)


def _card(monkeypatch, tmp_path, session_id="s1"):
    # Redirect disk persistence away from the real ~/.local/share/iris.
    monkeypatch.setattr(call_card, "_STATE_DIR", tmp_path)
    card = DisclosureCard(session_id)
    posted: list = []
    monkeypatch.setattr(card, "post_message", lambda msg: posted.append(msg))
    return card, posted


def test_action_disclose_posts_disclosure_acknowledged_once(monkeypatch, tmp_path):
    card, posted = _card(monkeypatch, tmp_path)
    card.action_disclose()
    assert len(posted) == 1
    assert isinstance(posted[0], DisclosureAcknowledged)
    assert posted[0].session_id == "s1"


def test_action_disclose_second_call_does_not_repost(monkeypatch, tmp_path):
    card, posted = _card(monkeypatch, tmp_path)
    card.action_disclose()
    card.action_disclose()
    assert len(posted) == 1


def test_action_skip_posts_disclosure_skipped_once(monkeypatch, tmp_path):
    card, posted = _card(monkeypatch, tmp_path)
    card.action_skip()
    assert len(posted) == 1
    assert isinstance(posted[0], DisclosureSkipped)
    assert posted[0].session_id == "s1"


def test_action_skip_second_call_does_not_repost(monkeypatch, tmp_path):
    card, posted = _card(monkeypatch, tmp_path)
    card.action_skip()
    card.action_skip()
    assert len(posted) == 1


def test_action_disclose_after_skip_does_not_post(monkeypatch, tmp_path):
    # The guard is "already resolved", not per-action -- once skipped, disclose
    # must also be inert (and vice versa), since the state is terminal.
    card, posted = _card(monkeypatch, tmp_path)
    card.action_skip()
    card.action_disclose()
    assert len(posted) == 1
    assert isinstance(posted[0], DisclosureSkipped)


def test_disclosure_acknowledged_handler_name_matches_app_method():
    msg = DisclosureAcknowledged("s1")
    assert msg.handler_name == "on_disclosure_acknowledged"


def test_disclosure_skipped_handler_name_matches_app_method():
    msg = DisclosureSkipped("s1")
    assert msg.handler_name == "on_disclosure_skipped"


# ---------------------------------------------------------------------------
# set_disclosure_result() -- the daemon-driven auto-disclose path (ti-iv69h).
# Unlike action_disclose()/action_skip(), this must NOT post
# DisclosureAcknowledged/DisclosureSkipped: the daemon already made the
# transition (that's WHY this event exists), so posting again would just
# re-send an already-applied ack/skip back to it.
# ---------------------------------------------------------------------------

def test_set_disclosure_result_disclosed_updates_state_without_posting(monkeypatch, tmp_path):
    card, posted = _card(monkeypatch, tmp_path)

    card.set_disclosure_result(DisclosureState.DISCLOSED)

    assert card.state is DisclosureState.DISCLOSED
    assert posted == []


def test_set_disclosure_result_skipped_updates_state_without_posting(monkeypatch, tmp_path):
    card, posted = _card(monkeypatch, tmp_path)

    card.set_disclosure_result(DisclosureState.SKIPPED)

    assert card.state is DisclosureState.SKIPPED
    assert posted == []


def test_set_disclosure_result_persists_state_to_disk(monkeypatch, tmp_path):
    card, _posted = _card(monkeypatch, tmp_path, session_id="s1")

    card.set_disclosure_result(DisclosureState.DISCLOSED)

    reloaded = DisclosureCard("s1")
    assert reloaded.state is DisclosureState.DISCLOSED


def test_set_disclosure_result_is_noop_once_already_resolved(monkeypatch, tmp_path):
    # Guard mirrors action_disclose/action_skip's own "already resolved" check --
    # an operator's manual [S] keypress must win over a slightly-delayed automatic
    # disclosure-succeeded broadcast landing after it (and vice versa).
    card, posted = _card(monkeypatch, tmp_path)
    card.action_skip()

    card.set_disclosure_result(DisclosureState.DISCLOSED)

    assert card.state is DisclosureState.SKIPPED
    assert len(posted) == 1
    assert isinstance(posted[0], DisclosureSkipped)
