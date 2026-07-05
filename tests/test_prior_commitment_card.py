"""PriorCommitmentCard — "Since last time" open-commitment display (ti-w0dvp).

Renders one row from AfterStore.get_open_commitments(contact_id). That method
only ever returns DB rows with the literal status='open' (a resolved-broken
commitment is no longer open by definition) -- so "broken" here is a
*computed* overdue-vs-due_date display state, never read off a DB column.
_now is an injectable override (same convention as processor.py's self._now)
so the overdue computation is deterministic in tests instead of depending on
the real date.today().

[H]/[B] call AfterStore.resolve_commitment(commitment_id, ...) directly --
the card holds an AfterStore reference passed in by its caller, the same
"instantiate directly, no daemon round-trip" pattern as self._roster =
RosterStore() in app.py -- then remove() itself, mirroring
FactCard/ActionItemCard's remove-after-resolve idiom. A _resolved guard
mirrors DisclosureCard's "already resolved" no-repost check: a second
action_honor()/action_break() call must not double-write the DB or
double-remove() the widget.

Widget.remove() raises NoActiveAppError outside a mounted App (verified
directly against this Textual version), so -- exactly like
test_disclosure_card.py monkeypatches post_message to avoid needing a live
App -- these tests monkeypatch remove() as an instance attribute rather than
paying for a full Pilot/run_test() harness the rest of this module's tests
don't use either.
"""
from __future__ import annotations

from datetime import date

import pytest

from iris.capture.after_store import AfterStore
from iris.console.call_card import PriorCommitmentCard
from iris.roster import RosterStore


class _FakeAfterStore:
    """Records resolve_commitment() calls without touching a real DB."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    def resolve_commitment(self, commitment_id: int, status: str) -> None:
        self.calls.append((commitment_id, status))


def _commitment(**overrides) -> dict:
    base = {
        "id": 1,
        "contact_id": 7,
        "call_log_id": 1,
        "direction": "they_promised",
        "description": "send the check",
        "amount": "$50",
        "due_date": "2026-06-01",
        "status": "open",
        "captured_at": 1_774_000_000.0,
        "resolved_at": None,
    }
    base.update(overrides)
    return base


def _card(*, commitment=None, store=None, rep_name="", now=None):
    commitment = commitment if commitment is not None else _commitment()
    store = store if store is not None else _FakeAfterStore()
    card = PriorCommitmentCard(commitment, store, rep_name=rep_name, _now=now)
    card.remove = lambda: None
    return card, store


# --- overdue computation (drives which visual state renders) ---------------

def test_overdue_due_date_is_broken():
    card, _ = _card(commitment=_commitment(due_date="2026-06-01"), now=date(2026, 6, 5))
    assert card.is_broken is True
    assert card.days_overdue == 4


def test_due_date_today_is_not_broken():
    card, _ = _card(commitment=_commitment(due_date="2026-06-05"), now=date(2026, 6, 5))
    assert card.is_broken is False
    assert card.days_overdue == 0


def test_future_due_date_is_not_broken():
    card, _ = _card(commitment=_commitment(due_date="2026-07-01"), now=date(2026, 6, 5))
    assert card.is_broken is False
    assert card.days_overdue == 0


def test_missing_due_date_is_not_broken():
    card, _ = _card(commitment=_commitment(due_date=None), now=date(2026, 6, 5))
    assert card.is_broken is False
    assert card.days_overdue == 0


def test_unparseable_due_date_is_not_broken():
    card, _ = _card(commitment=_commitment(due_date="not-a-date"), now=date(2026, 6, 5))
    assert card.is_broken is False
    assert card.days_overdue == 0


# --- render() content --------------------------------------------------

def test_broken_render_has_warning_icon_and_days_overdue():
    card, _ = _card(commitment=_commitment(due_date="2026-06-01"), now=date(2026, 6, 5))
    text = card.render()
    assert "⚠" in text
    assert "4d overdue" in text


def test_broken_render_is_literal_quotable_text_with_rep_name():
    commitment = _commitment(due_date="2026-06-01", description="send the check")
    card, _ = _card(commitment=commitment, rep_name="Maria", now=date(2026, 6, 5))
    text = card.render()
    assert "Maria promised send the check by 2026-06-01" in text
    assert "it didn't happen" in text


def test_broken_render_defaults_rep_name_to_your_rep():
    card, _ = _card(
        commitment=_commitment(due_date="2026-06-01"), rep_name="", now=date(2026, 6, 5)
    )
    text = card.render()
    assert "your rep promised" in text


def test_broken_render_i_promised_says_you_not_rep_name():
    commitment = _commitment(due_date="2026-06-01", direction="i_promised")
    card, _ = _card(commitment=commitment, rep_name="Maria", now=date(2026, 6, 5))
    text = card.render()
    assert "you promised" in text
    assert "Maria" not in text


def test_open_render_has_hourglass_icon():
    card, _ = _card(commitment=_commitment(due_date="2026-07-01"), now=date(2026, 6, 5))
    text = card.render()
    assert "⏳" in text
    assert "send the check" in text
    assert "2026-07-01" in text


def test_open_render_missing_due_date_shows_placeholder():
    card, _ = _card(commitment=_commitment(due_date=None), now=date(2026, 6, 5))
    text = card.render()
    assert "—" in text


def test_open_render_i_promised_says_you():
    commitment = _commitment(due_date="2026-07-01", direction="i_promised")
    card, _ = _card(commitment=commitment, rep_name="Maria", now=date(2026, 6, 5))
    text = card.render()
    assert "You promised" in text
    assert "Maria" not in text


# --- CSS class reflects computed state --------------------------------------

def test_on_mount_adds_broken_class_when_overdue():
    card, _ = _card(commitment=_commitment(due_date="2026-06-01"), now=date(2026, 6, 5))
    card.on_mount()
    assert card.has_class("-broken")
    assert not card.has_class("-open")


def test_on_mount_adds_open_class_when_not_overdue():
    card, _ = _card(commitment=_commitment(due_date="2026-07-01"), now=date(2026, 6, 5))
    card.on_mount()
    assert card.has_class("-open")
    assert not card.has_class("-broken")


# --- accessibility -----------------------------------------------------

def test_can_focus_is_true():
    card, _ = _card()
    assert card.can_focus is True


def test_aria_role_is_article():
    card, _ = _card()
    assert card.aria_role == "article"


def test_focus_css_present():
    assert "PriorCommitmentCard:focus" in PriorCommitmentCard.DEFAULT_CSS
    assert "#a5b4fc" in PriorCommitmentCard.DEFAULT_CSS
    assert "heavy" in PriorCommitmentCard.DEFAULT_CSS


# --- [H]/[B] resolve, via a fake store --------------------------------------

def test_action_honor_calls_resolve_commitment_honored():
    card, store = _card(commitment=_commitment(id=42))
    card.action_honor()
    assert store.calls == [(42, "honored")]


def test_action_break_calls_resolve_commitment_broken():
    card, store = _card(commitment=_commitment(id=42))
    card.action_break()
    assert store.calls == [(42, "broken")]


def test_action_honor_removes_the_card():
    card, _ = _card()
    removed = []
    card.remove = lambda: removed.append(True)
    card.action_honor()
    assert removed == [True]


def test_action_honor_second_call_does_not_double_resolve():
    card, store = _card()
    card.action_honor()
    card.action_honor()
    assert len(store.calls) == 1


def test_action_break_after_honor_does_not_also_resolve():
    card, store = _card(commitment=_commitment(id=9))
    card.action_honor()
    card.action_break()
    assert store.calls == [(9, "honored")]


def test_on_key_h_calls_action_honor(monkeypatch):
    card, _ = _card()
    calls = []
    monkeypatch.setattr(card, "action_honor", lambda: calls.append("honor"))
    event = type("Event", (), {"key": "h", "stop": lambda self: None})()
    card.on_key(event)
    assert calls == ["honor"]


def test_on_key_b_calls_action_break(monkeypatch):
    card, _ = _card()
    calls = []
    monkeypatch.setattr(card, "action_break", lambda: calls.append("break"))
    event = type("Event", (), {"key": "b", "stop": lambda self: None})()
    card.on_key(event)
    assert calls == ["break"]


def test_on_key_other_key_does_not_resolve():
    card, store = _card()
    event = type("Event", (), {"key": "x", "stop": lambda self: None})()
    card.on_key(event)
    assert store.calls == []


# --- integration: real AfterStore + real DB row -----------------------------

@pytest.fixture
def real_store(tmp_path):
    path = tmp_path / "roster.db"
    roster = RosterStore(path)
    contact = roster.add("Mom", "+12025550100")
    store = AfterStore(path)
    log_id = store.insert_call_log(contact.id, "sess-1", None, None, "iris", None, "")
    store.insert_commitment(
        contact.id, log_id, "they_promised", "send the check", "$50", "2026-06-01", None, None
    )
    return store, contact.id


def test_action_honor_updates_real_db_row(real_store):
    store, contact_id = real_store
    commitment = store.get_open_commitments(contact_id)[0]
    card = PriorCommitmentCard(commitment, store)
    card.remove = lambda: None

    card.action_honor()

    assert store.get_open_commitments(contact_id) == []
    row = store._conn.execute(
        "SELECT status, resolved_at FROM commitment WHERE id=?", (commitment["id"],)
    ).fetchone()
    assert row["status"] == "honored"
    assert row["resolved_at"] is not None


def test_action_break_updates_real_db_row(real_store):
    store, contact_id = real_store
    commitment = store.get_open_commitments(contact_id)[0]
    card = PriorCommitmentCard(commitment, store)
    card.remove = lambda: None

    card.action_break()

    row = store._conn.execute(
        "SELECT status, resolved_at FROM commitment WHERE id=?", (commitment["id"],)
    ).fetchone()
    assert row["status"] == "broken"
    assert row["resolved_at"] is not None
