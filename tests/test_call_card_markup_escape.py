"""Adversarial regression coverage for escape_for_content() and the Call Card
render() sinks it fixed -- ti-gx6rp (validator coverage for ti-kpidj).

ti-kpidj added iris/console/_markup.py::escape_for_content() because
rich.markup.escape() only escapes '[' when followed by a Rich tag-opening
character ([a-z#/@]), while Textual's Content.from_markup() tokenizer opens a
tag on ANY unescaped '['. Bracket-shaped dynamic content like '[$50]' or
'[50%]' sailed past rich.markup.escape() unescaped and was then silently
DELETED (not mis-styled) by Content.from_markup(). Fixed at 14 call sites
across CriticalFactCard/FactCard/ActionItemCard's render() (both display and
edit-mode branches).

Assertions run text through Content.from_markup(...).plain, matching the
project's existing 'survives_markup_rendering' convention (tests/test_console_app.py)
-- checking the raw string would miss a regression to an unescaped bracket,
since the raw text still *contains* the bracket even when Content.from_markup
would go on to mangle it.
"""
from __future__ import annotations

from rich.markup import escape as rich_escape
from textual.content import Content

from iris.capture.schemas import ActionItem, CapturedFact, FactType
from iris.console import call_card
from iris.console._markup import escape_for_content
from iris.console.call_card import (
    ActionItemCard,
    CriticalFactCard,
    DisclosureCard,
    FactCard,
)


def _plain(markup: str) -> str:
    return Content.from_markup(markup).plain


# ---------------------------------------------------------------------------
# escape_for_content() -- direct delta vs rich.markup.escape()
# ---------------------------------------------------------------------------

def test_dollar_bracket_survives_where_rich_escape_loses_it():
    raw = "[$50]"
    assert _plain(rich_escape(raw)) == ""  # ti-kpidj bug: silently deleted
    assert _plain(escape_for_content(raw)) == raw  # fixed


def test_percent_bracket_survives_where_rich_escape_loses_it():
    raw = "[50%]"
    assert _plain(rich_escape(raw)) == ""
    assert _plain(escape_for_content(raw)) == raw


def test_digit_only_bracket_round_trips():
    # Textual's tokenizer happens not to swallow bare-digit bracket content
    # the way it does '[$50]'/'[50%]' -- no delta vs rich.markup.escape() for
    # this specific shape, but escape_for_content() must not regress it.
    raw = "[12345]"
    assert _plain(rich_escape(raw)) == raw
    assert _plain(escape_for_content(raw)) == raw


def test_multiple_brackets_all_survive():
    raw = "[$50] and [50%] and [12345]"
    assert _plain(rich_escape(raw)) != raw  # the $/% spans get silently dropped
    assert _plain(escape_for_content(raw)) == raw


def test_unicode_text_with_bracket_survives():
    raw = "café said [$50] more"
    assert _plain(rich_escape(raw)) != raw
    assert _plain(escape_for_content(raw)) == raw


def test_already_rich_safe_bracket_content_unaffected():
    # '[bold]' is already escaped correctly by rich.markup.escape() (its '['
    # is followed by a lowercase letter -- Rich's own tag grammar). escape_for_content
    # must not change behavior -- and should produce the identical escaped form.
    raw = "[bold]"
    assert _plain(rich_escape(raw)) == raw
    assert _plain(escape_for_content(raw)) == raw
    assert escape_for_content(raw) == rich_escape(raw)


# ---------------------------------------------------------------------------
# CriticalFactCard / FactCard -- render() sinks (no App/Pilot needed)
# ---------------------------------------------------------------------------

def _fact(raw_text: str, normalized_value: str, *, critical: bool = True) -> CapturedFact:
    return CapturedFact(
        session_id="s1",
        fact_type=FactType.AMOUNT,
        raw_text=raw_text,
        normalized_value=normalized_value,
        transcript_turn_id=1,
        transcript_offset_s=0.0,
        speaker="far",
        confidence=0.9,
        critical=critical,
    )


def test_critical_fact_card_display_mode_preserves_bracket_content():
    fact = _fact("[$1200] reported", "[92%] match")
    rendered = _plain(CriticalFactCard(fact).render())
    assert "[$1200] reported" in rendered
    assert "[92%] match" in rendered


def test_critical_fact_card_edit_mode_preserves_bracket_content():
    fact = _fact("[$40] baseline", "old value")
    card = CriticalFactCard(fact)
    card._editing = True
    card._edit_buffer = "[77%] override"
    rendered = _plain(card.render())
    assert "[$40] baseline" in rendered  # raw_text dim reminder line, still shown while editing
    assert "[77%] override" in rendered  # live edit buffer


def test_fact_card_display_mode_preserves_bracket_content():
    fact = _fact("[$1250] noted", "[33%] confidence", critical=False)
    rendered = _plain(FactCard(fact).render())
    assert "[$1250] noted" in rendered
    assert "[33%] confidence" in rendered


def test_fact_card_edit_mode_preserves_bracket_content():
    fact = _fact("[$8] baseline", "old value", critical=False)
    card = FactCard(fact)
    card._editing = True
    card._edit_buffer = "[61%] override"
    rendered = _plain(card.render())
    assert "[$8] baseline" in rendered
    assert "[61%] override" in rendered


# ---------------------------------------------------------------------------
# ActionItemCard -- render() sinks (three-field edit mode)
# ---------------------------------------------------------------------------

def _action_item(description: str, owner: str, due_date: str | None) -> ActionItem:
    return ActionItem(
        session_id="s1",
        description=description,
        trigger="",
        owner=owner,
        transcript_turn_id=1,
        transcript_offset_s=0.0,
        speaker="far",
        confidence=0.9,
        due_date=due_date,
    )


def test_action_item_card_display_mode_preserves_bracket_content():
    item = _action_item("follow up on [$500] refund", "[91%] Team", "[$25] fee due")
    rendered = _plain(ActionItemCard(item).render())
    assert "follow up on [$500] refund" in rendered
    assert "[91%] Team" in rendered
    assert "[$25] fee due" in rendered


def test_action_item_card_edit_mode_preserves_bracket_content():
    item = _action_item("original", "original owner", None)
    card = ActionItemCard(item)
    card._editing = True
    card._edit_desc = "[$77] update"
    card._edit_due = "[14%] late fee"
    card._edit_owner = "[$3] copay"
    rendered = _plain(card.render())
    assert "[$77] update" in rendered
    assert "[14%] late fee" in rendered
    assert "[$3] copay" in rendered


# ---------------------------------------------------------------------------
# DisclosureCard -- regression guard: _script must stay UNescaped
# ---------------------------------------------------------------------------

def test_disclosure_card_script_remains_unescaped(monkeypatch, tmp_path):
    """ti-kpidj deliberately does not touch DisclosureCard -- its _script is
    trusted, developer-authored disclosure text, not user/call data. A future
    well-meaning refactor might wrap it in escape_for_content() too; this pins
    the exact unescaped line so that change fails here rather than silently
    changing how the disclosure text renders."""
    monkeypatch.setattr(call_card, "_STATE_DIR", tmp_path)
    script = "Iris may quote amounts like [$50] verbatim during the call."
    card = DisclosureCard("s-regression", script=script)

    # Exact (not substring-loose) containment: if _script were ever escaped,
    # this line would instead read "...like \[$50] verbatim..." and fail here.
    assert f"[yellow]{script}[/yellow]" in card.render()
