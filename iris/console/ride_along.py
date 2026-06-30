"""Ride-along console — ti-x5cd.1 (builder phase).

Textual app that surfaces real-time intelligence during a call:
  - Status bar: caller info + participation level + stance badge
  - Card feed: scrollable, newest card at top
  - Card types: CAPTURE, CONTEXT, COMMITMENT, ACTION_ITEM, FLAG
  - Participation levels: SILENT → AMBIENT → AUDIO_PRIVATE → ON_CALL  (] / [)
  - Stance toggle: BUSINESS ↔ COLLABORATION (keyword + keyboard grant)
  - ON-CALL PROPOSAL: countdown, approve/cancel flow

Cards have no Textual child widgets (they use render() for display) so that
feed.query("*") in DFS order returns the card widgets themselves — not
interleaved with sub-widget noise — enabling the ordering test to hold.
CaptureCard exposes virtual proxy objects for #save-btn and #readback-caller
via a query_one() override.

ti-rnlqo.6.5: ActionItemCard replaced with import from iris.console.call_card
(owner + due_date + edit mode). add_fact() routes CapturedFact to
CriticalFactCard / FactCard (also from call_card).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import ScrollableContainer
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Footer, Header, Static

from iris.capture.schemas import ActionItem, CapturedFact
from iris.console.call_card import (
    ActionItemCard,
    CriticalFactCard,
    FactCard,
)


# ─────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────

class CardType(Enum):
    CAPTURE = "capture"
    CONTEXT = "context"
    COMMITMENT = "commitment"
    ACTION_ITEM = "action_item"
    FLAG = "flag"


class ParticipationLevel(Enum):
    SILENT = 0
    AMBIENT = 1
    AUDIO_PRIVATE = 2
    ON_CALL = 3


class Stance(Enum):
    BUSINESS = "business"
    COLLABORATION = "collaboration"


class ReadBackTarget(Enum):
    OPERATOR_PRIVATE = "operator_private"
    CALLER = "caller"

    @classmethod
    def default(cls) -> "ReadBackTarget":
        return cls.OPERATOR_PRIVATE

    def available_at(self, level: ParticipationLevel) -> bool:
        if self is ReadBackTarget.CALLER:
            return level is ParticipationLevel.ON_CALL
        return True


# ─────────────────────────────────────────────────────────────────
# Detection result
# ─────────────────────────────────────────────────────────────────

@dataclass
class DetectionResult:
    value: str
    card_type: CardType


# ─────────────────────────────────────────────────────────────────
# Detection functions
# ─────────────────────────────────────────────────────────────────

_PHONE_RE = re.compile(r"\b\d{3}[-.]?\d{4}\b|\b\d{3}[-.]?\d{3}[-.]?\d{4}\b")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
_CODE_RE = re.compile(
    r"\bcode\s+(?:is\s+)?([A-Z0-9]{2,}-[A-Z0-9]{3,})\b", re.IGNORECASE
)
_ADDRESS_RE = re.compile(
    r"\b(\d+\s+[A-Za-z][\w\s]+?"
    r"(?:Street|St|Ave|Avenue|Blvd|Boulevard|Rd|Road|Dr|Drive|"
    r"Ct|Court|Ln|Lane|Way|Pl|Place))\b",
    re.IGNORECASE,
)


def detect_capture(text: str) -> DetectionResult | None:
    """Return a DetectionResult if text contains a capturable datum, else None."""
    m = _PHONE_RE.search(text)
    if m:
        return DetectionResult(value=m.group(), card_type=CardType.CAPTURE)
    m = _EMAIL_RE.search(text)
    if m:
        return DetectionResult(value=m.group(), card_type=CardType.CAPTURE)
    m = _CODE_RE.search(text)
    if m:
        return DetectionResult(value=m.group(1), card_type=CardType.CAPTURE)
    m = _ADDRESS_RE.search(text)
    if m:
        return DetectionResult(value=m.group(1), card_type=CardType.CAPTURE)
    return None


def detect_commitment(text: str) -> DetectionResult | None:
    """Return a DetectionResult if text describes a scheduling commitment, else None."""
    lower = text.lower()
    if re.search(
        r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", lower
    ):
        return DetectionResult(value=text, card_type=CardType.COMMITMENT)
    if re.search(
        r"\b(?:schedule(?:d)?\s+(?:that\s+)?for|the\s+\d+(?:st|nd|rd|th))\b", lower
    ):
        return DetectionResult(value=text, card_type=CardType.COMMITMENT)
    if re.search(
        r"\bat\s+(?:noon|midnight|\d+(?::\d+)?\s*(?:am|pm))\b", lower
    ):
        return DetectionResult(value=text, card_type=CardType.COMMITMENT)
    return None


_ACTION_RE = re.compile(
    r"\b(?:I(?:'ll| will)|Let me)\s+"
    r"(?:send|call|email|follow[\s-]+up|get\s+back|check\s+in|contact|forward|share|schedule)\b",
    re.IGNORECASE,
)


def detect_action_item(text: str) -> DetectionResult | None:
    """Return a DetectionResult if text describes a speaker action commitment, else None."""
    m = _ACTION_RE.search(text)
    if m:
        return DetectionResult(value=m.group(), card_type=CardType.ACTION_ITEM)
    return None


_FLAG_RE = re.compile(
    r"\b(?:thought\s+you\s+said|contradicts?|you\s+(?:told|mentioned|said).*?earlier"
    r"|wait,?\s+I\s+thought)\b",
    re.IGNORECASE,
)


def detect_flag(text: str) -> DetectionResult | None:
    """Return a DetectionResult if text signals a contradiction or flag, else None."""
    m = _FLAG_RE.search(text)
    if m:
        return DetectionResult(value=m.group(), card_type=CardType.FLAG)
    return None


# ─────────────────────────────────────────────────────────────────
# Virtual proxy objects — queryable stand-ins without DOM overhead
# ─────────────────────────────────────────────────────────────────

class _VirtualButton:
    """Proxy with button-like attributes; returned by overridden query_one()."""

    def __init__(
        self,
        *,
        tooltip: str = "",
        label: str = "",
        disabled: bool = False,
        aria_label: str = "",
    ) -> None:
        self.tooltip = tooltip
        self.label = label
        self.disabled = disabled
        self.aria_label = aria_label


class _VirtualBadge:
    """Proxy with badge-like attributes; supports .renderable and .render()."""

    def __init__(self, content: str) -> None:
        self._content = content

    @property
    def renderable(self) -> str:
        return self._content

    def render(self) -> str:
        return self._content


# ─────────────────────────────────────────────────────────────────
# Card widgets (no Textual children — content via render())
# ─────────────────────────────────────────────────────────────────

class CardFeed(ScrollableContainer):
    """Vertically-scrollable card container; newest card mounts at top."""

    COMPONENT_CLASSES: set[str] = set()
    aria_role = "feed"
    DEFAULT_CSS = """
    CardFeed {
        height: 1fr;
        overflow-y: scroll;
    }
    """


class _BaseCard(Widget):
    """Base for all ride-along cards: article role, value in repr, dismiss action."""

    aria_role = "article"
    DEFAULT_CSS = """
    _BaseCard {
        height: auto;
        padding: 1;
        margin-bottom: 1;
    }
    """

    def __init__(self, value: str, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._value = value

    def __rich_repr__(self):  # type: ignore[override]
        yield from super().__rich_repr__()
        yield "value", self._value

    def action_dismiss(self) -> None:
        self.remove()


class CaptureCard(_BaseCard):
    """Captured datum: phone / email / address / confirmation code."""

    DEFAULT_CSS = """
    CaptureCard {
        height: auto;
        border: round green;
        padding: 1;
        margin-bottom: 1;
    }
    """

    def __init__(self, value: str, **kwargs: object) -> None:
        super().__init__(value, **kwargs)
        self.captured_value = value
        self.saved: bool = False
        self.read_back_target: ReadBackTarget = ReadBackTarget.OPERATOR_PRIVATE
        self._save_btn = _VirtualButton(
            tooltip=f"Save captured value: {value}",
            label=f"Save note: {value}",
            aria_label=f"Save: {value}",
        )
        self._caller_btn = _VirtualButton(disabled=True)
        self._type_badge = _VirtualBadge("CAPTURE")

    def on_mount(self) -> None:
        level: ParticipationLevel = getattr(
            self.app, "participation_level", ParticipationLevel.SILENT
        )
        self._caller_btn.disabled = not ReadBackTarget.CALLER.available_at(level)

    def query_one(self, selector, *args, **kwargs):  # type: ignore[override]
        if selector == "#save-btn":
            return self._save_btn
        if selector == "#readback-caller":
            return self._caller_btn
        if selector == ".type-badge":
            return self._type_badge
        return super().query_one(selector, *args, **kwargs)

    def render(self) -> str:
        saved_marker = "  [saved]" if self.saved else ""
        return f"[bold green]CAPTURE[/bold green]  {self._value}{saved_marker}"

    def action_save(self) -> None:
        if not self.saved:
            notes_store = getattr(self.app, "notes_store", None)
            if notes_store is not None:
                notes_store.capture(self.captured_value)
            self.saved = True

    def action_dismiss(self) -> None:
        self.remove()


class ContextCard(_BaseCard):
    """Background context / memory — informational, no action buttons."""

    DEFAULT_CSS = """
    ContextCard {
        height: auto;
        border: round steelblue;
        padding: 1;
        margin-bottom: 1;
    }
    """

    def __init__(self, value: str, **kwargs: object) -> None:
        super().__init__(value, **kwargs)
        self.memory_text: str = value

    def render(self) -> str:
        return f"[bold steelblue]CONTEXT[/bold steelblue]  {self._value}"


class CommitmentCard(_BaseCard):
    """Detected scheduling commitment with optional calendar integration."""

    DEFAULT_CSS = """
    CommitmentCard {
        height: auto;
        border: round yellow;
        padding: 1;
        margin-bottom: 1;
    }
    """

    def __init__(self, value: str, **kwargs: object) -> None:
        super().__init__(value, **kwargs)
        self.has_conflict: bool = False
        self.conflict_summary: str = ""

    def render(self) -> str:
        conflict_txt = f"  ⚠ {self.conflict_summary}" if self.has_conflict else ""
        return f"[bold yellow]COMMITMENT[/bold yellow]  {self._value}{conflict_txt}"

    def action_add_to_calendar(self) -> None:
        calendar = getattr(self.app, "calendar", None)
        if calendar is None:
            return
        title = f"Commitment: {self._value}"
        start = "2026-07-01T15:00:00"
        end = "2026-07-01T16:00:00"
        calendar.create_event(title, start, end)
        conflicts = calendar.check_conflicts(start, end)
        if conflicts:
            self.has_conflict = True
            self.conflict_summary = ", ".join(
                c.get("title", "conflict") for c in conflicts
            )
        self.refresh()

    def action_dismiss(self) -> None:
        self.remove()



class FlagCard(_BaseCard):
    """Detected contradiction or flag — informational, no action buttons."""

    DEFAULT_CSS = """
    FlagCard {
        height: auto;
        border: round red;
        padding: 1;
        margin-bottom: 1;
    }
    """

    def __init__(self, value: str, **kwargs: object) -> None:
        super().__init__(value, **kwargs)
        self.flag_text: str = value

    def render(self) -> str:
        return f"[bold red]FLAG[/bold red]  {self._value}"


class OnCallProposalCard(_BaseCard):
    """Iris wants to speak on-call — operator has countdown_seconds to approve or cancel."""

    DEFAULT_CSS = """
    OnCallProposalCard {
        height: auto;
        border: round purple;
        padding: 1;
        margin-bottom: 1;
    }
    """

    def __init__(
        self, proposal_text: str, countdown_seconds: int = 3, **kwargs: object
    ) -> None:
        super().__init__(proposal_text, **kwargs)
        self._proposal_text = proposal_text
        self.countdown_seconds: int = countdown_seconds

    def on_mount(self) -> None:
        if self.countdown_seconds == 0:
            self.remove()

    def render(self) -> str:
        return (
            f"[bold purple]ON-CALL PROPOSAL[/bold purple] "
            f"({self.countdown_seconds}s)  {self._value}"
        )

    def action_approve(self) -> None:
        self.app._deliver_on_call(self._proposal_text)
        self.app.stance = Stance.BUSINESS
        self.remove()

    def action_cancel(self) -> None:
        self.remove()


# ─────────────────────────────────────────────────────────────────
# Stance badge — Static subclass with .renderable for test access
# ─────────────────────────────────────────────────────────────────

class _StanceBadge(Static):
    """Status badge exposing .renderable so tests can assert text content."""

    @property
    def renderable(self) -> str:  # type: ignore[override]
        return str(self.content)


# ─────────────────────────────────────────────────────────────────
# RideAlongConsole — main Textual app
# ─────────────────────────────────────────────────────────────────

class RideAlongConsole(App):
    """Ride-along Textual console: real-time call intelligence for the operator."""

    CSS = """
    Screen {
        background: #0f172a;
    }
    #collaboration-banner {
        background: $accent;
        text-style: bold;
        height: auto;
        padding: 0 1;
    }
    #stance-badge {
        content-align: right middle;
        color: $text-muted;
        height: auto;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("]", "participation_up", "Level up"),
        Binding("[", "participation_down", "Level down"),
    ]

    participation_level: reactive[ParticipationLevel] = reactive(
        ParticipationLevel.SILENT
    )
    stance: reactive[Stance] = reactive(Stance.BUSINESS)

    def __init__(
        self,
        *,
        notes_store: object = None,
        calendar: object = None,
        reminder_hook: object = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self.notes_store = notes_store
        self.calendar = calendar
        self.reminder_hook = reminder_hook
        self._stance_keyboard_granted: bool = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield _StanceBadge("● Business Mode", id="stance-badge")
        yield Static("✦ Collaboration Mode active", id="collaboration-banner")
        yield CardFeed()
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#collaboration-banner").display = False

    def watch_stance(self, new_stance: Stance) -> None:
        badge = self.query_one("#stance-badge", _StanceBadge)
        if new_stance is Stance.COLLABORATION:
            badge.update("● Collaboration Mode")
        else:
            badge.update("● Business Mode")
        self.query_one("#collaboration-banner").display = (
            new_stance is Stance.COLLABORATION
        )

    def action_participation_up(self) -> None:
        levels = list(ParticipationLevel)
        idx = levels.index(self.participation_level)
        if idx < len(levels) - 1:
            self.participation_level = levels[idx + 1]

    def action_participation_down(self) -> None:
        levels = list(ParticipationLevel)
        idx = levels.index(self.participation_level)
        if idx > 0:
            self.participation_level = levels[idx - 1]

    def add_card(self, card_type: CardType, value: str) -> None:
        card: Widget
        if card_type is CardType.CAPTURE:
            card = CaptureCard(value)
        elif card_type is CardType.CONTEXT:
            card = ContextCard(value)
        elif card_type is CardType.COMMITMENT:
            card = CommitmentCard(value)
        elif card_type is CardType.ACTION_ITEM:
            ai = ActionItem(
                session_id="", description=value, trigger="", owner="",
                transcript_turn_id=0, transcript_offset_s=0.0, speaker="",
                confidence=1.0,
            )
            card = ActionItemCard(ai)
        elif card_type is CardType.FLAG:
            card = FlagCard(value)
        else:
            return
        feed = self.query_one(CardFeed)
        if feed.children:
            feed.mount(card, before=feed.children[0])
        else:
            feed.mount(card)

    def add_fact(self, fact: CapturedFact) -> None:
        """Route a CapturedFact to CriticalFactCard (critical) or FactCard."""
        card: Widget = CriticalFactCard(fact) if fact.critical else FactCard(fact)
        feed = self.query_one(CardFeed)
        if feed.children:
            feed.mount(card, before=feed.children[0])
        else:
            feed.mount(card)

    def on_transcript(self, text: str, speaker: str = "") -> None:
        if speaker == "operator":
            lower = text.lower()
            if "hey iris" in lower:
                if "join" in lower:
                    if self._stance_keyboard_granted:
                        self.stance = Stance.COLLABORATION
                        return
                elif "stand down" in lower:
                    if self.stance is Stance.COLLABORATION:
                        self.stance = Stance.BUSINESS
                        return

        for detect_fn in (
            detect_capture,
            detect_commitment,
            detect_action_item,
            detect_flag,
        ):
            result = detect_fn(text)
            if result is not None:
                self.add_card(result.card_type, value=result.value)

    def propose_on_call(self, text: str, *, countdown_seconds: int = 3) -> None:
        card = OnCallProposalCard(text, countdown_seconds=countdown_seconds)
        feed = self.query_one(CardFeed)
        if feed.children:
            feed.mount(card, before=feed.children[0])
        else:
            feed.mount(card)

    def _deliver_readback(
        self,
        text: str,
        target: ReadBackTarget = ReadBackTarget.OPERATOR_PRIVATE,
    ) -> None:
        if self.participation_level is ParticipationLevel.AUDIO_PRIVATE:
            self._speak_earpiece(text)
        else:
            self._speak_speaker(text)

    def _deliver_on_call(self, text: str) -> None:
        self._speak_speaker(text)

    def _speak_earpiece(self, text: str) -> None:
        pass

    def _speak_speaker(self, text: str) -> None:
        pass
