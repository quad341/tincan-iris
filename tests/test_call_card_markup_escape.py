"""Rich-markup escaping regression tests for call_card.py render() sinks (ti-z1utm / ti-u4ngs).

ti-z1utm found that CriticalFactCard, FactCard, and ActionItemCard interpolate
caller/STT-derived content (raw_text, normalized_value, description, owner,
due_date, and their edit-mode buffer counterparts) into markup-parsed
render() strings without escaping -- a literal '[' in that content is treated
as an unrecognized style-tag attempt and silently dropped (and can corrupt
rendering). The fix wraps every dynamic segment in rich.markup.escape(); this
file locks that in per the technique ti-z1utm verified with ad-hoc
Text.from_markup exploit/fix demos: a payload like "[bold red]X[/bold red]"
must survive as literal text, not be parsed into a style span.

No Textual App/Pilot is used -- render() only reads instance state. Edit-mode
buffers are set directly (matching the bare-widget convention already used
for _edit_buffer/_edit_desc/etc. in this suite) rather than driving on_key,
since key-routing into edit mode is covered separately (ti-e7sfx) and is
orthogonal to what render() does with whatever the buffer holds.
"""
from __future__ import annotations

from rich.text import Text

from iris.capture.schemas import ActionItem, CapturedFact, FactType
from iris.console.call_card import ActionItemCard, CriticalFactCard, FactCard


def _plain(rendered: str) -> str:
    """What Textual's markup parser would show on screen -- brackets survive
    only if the dynamic content was escaped before interpolation."""
    return Text.from_markup(rendered).plain


def _fact(*, raw_text: str = "case AB123", normalized_value: str = "AB123") -> CapturedFact:
    return CapturedFact(
        id="f1",
        session_id="s1",
        fact_type=FactType.CASE_ID,
        raw_text=raw_text,
        normalized_value=normalized_value,
        critical=True,
        confidence=0.95,
        confirmed=None,
        transcript_turn_id=1,
        transcript_offset_s=1.0,
        speaker="far",
    )


def _item(
    *,
    description: str = "Call back tomorrow",
    owner: str = "Them",
    due_date: str | None = None,
) -> ActionItem:
    return ActionItem(
        id="a1",
        session_id="s1",
        description=description,
        trigger="I will",
        owner=owner,
        due_date=due_date,
        confidence=0.8,
        confirmed=None,
        transcript_turn_id=2,
        transcript_offset_s=5.0,
        speaker="far",
    )


# ---------------------------------------------------------------------------
# CriticalFactCard.render() -- raw_text (display + edit line), normalized_value
# (display), edit_buffer (edit).
# ---------------------------------------------------------------------------

def test_critical_fact_card_raw_text_survives_markup_display_mode():
    payload = "[bold red]RAW_INJECT[/bold red]"
    card = CriticalFactCard(_fact(raw_text=payload))
    assert payload in _plain(card.render())


def test_critical_fact_card_normalized_value_survives_markup_display_mode():
    payload = "[bold blue]NORM_INJECT[/bold blue]"
    card = CriticalFactCard(_fact(normalized_value=payload))
    assert payload in _plain(card.render())


def test_critical_fact_card_raw_text_survives_markup_edit_mode():
    payload = "[bold red]RAW_INJECT[/bold red]"
    card = CriticalFactCard(_fact(raw_text=payload))
    card._editing = True
    assert payload in _plain(card.render())


def test_critical_fact_card_edit_buffer_survives_markup_edit_mode():
    payload = "[bold blue]NORM_INJECT[/bold blue]"
    card = CriticalFactCard(_fact())
    card._editing = True
    card._edit_buffer = payload
    assert payload in _plain(card.render())


# ---------------------------------------------------------------------------
# FactCard.render() -- identical shape to CriticalFactCard.
# ---------------------------------------------------------------------------

def test_fact_card_raw_text_survives_markup_display_mode():
    payload = "[bold red]RAW_INJECT[/bold red]"
    card = FactCard(_fact(raw_text=payload))
    assert payload in _plain(card.render())


def test_fact_card_normalized_value_survives_markup_display_mode():
    payload = "[bold blue]NORM_INJECT[/bold blue]"
    card = FactCard(_fact(normalized_value=payload))
    assert payload in _plain(card.render())


def test_fact_card_raw_text_survives_markup_edit_mode():
    payload = "[bold red]RAW_INJECT[/bold red]"
    card = FactCard(_fact(raw_text=payload))
    card._editing = True
    assert payload in _plain(card.render())


def test_fact_card_edit_buffer_survives_markup_edit_mode():
    payload = "[bold blue]NORM_INJECT[/bold blue]"
    card = FactCard(_fact())
    card._editing = True
    card._edit_buffer = payload
    assert payload in _plain(card.render())


# ---------------------------------------------------------------------------
# ActionItemCard.render() -- description, owner (via _owner_display), due_date
# (display), and their edit_desc/edit_owner/edit_due counterparts (edit).
# ---------------------------------------------------------------------------

def test_action_item_card_description_survives_markup_display_mode():
    payload = "[bold red]DESC_INJECT[/bold red]"
    card = ActionItemCard(_item(description=payload))
    assert payload in _plain(card.render())


def test_action_item_card_owner_survives_markup_display_mode():
    payload = "[bold green]OWNER_INJECT[/bold green]"
    card = ActionItemCard(_item(owner=payload))
    assert payload in _plain(card.render())


def test_action_item_card_due_date_survives_markup_display_mode():
    payload = "[bold magenta]DUE_INJECT[/bold magenta]"
    card = ActionItemCard(_item(due_date=payload))
    assert payload in _plain(card.render())


def test_action_item_card_description_survives_markup_edit_mode():
    payload = "[bold red]DESC_INJECT[/bold red]"
    card = ActionItemCard(_item())
    card._editing = True
    card._edit_desc = payload
    assert payload in _plain(card.render())


def test_action_item_card_owner_survives_markup_edit_mode():
    payload = "[bold green]OWNER_INJECT[/bold green]"
    card = ActionItemCard(_item())
    card._editing = True
    card._edit_owner = payload
    assert payload in _plain(card.render())


def test_action_item_card_due_date_survives_markup_edit_mode():
    payload = "[bold magenta]DUE_INJECT[/bold magenta]"
    card = ActionItemCard(_item())
    card._editing = True
    card._edit_due = payload
    assert payload in _plain(card.render())
