"""Call Card widgets for iris/console — ti-rnlqo.6 (builder phase).

ti-rnlqo.6.1: DisclosureCard — focus-trapped modal gate with disk state persistence
ti-rnlqo.6.2: CriticalFactCard, FactCard — confidence bar, edit mode, CapturedFact schema
ti-rnlqo.6.3: ActionItemCard — description/owner/due_date display + inline edit mode
ti-ir12t: DisclosureCard posts DisclosureAcknowledged/DisclosureSkipped so the app
can forward disclosure_ack/disclosure_skip to the daemon (hard-gates far capture).
"""
from __future__ import annotations

import json
import os
import time
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from rich.markup import escape
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import ScrollableContainer
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Footer, Static

from iris.capture.after_store import AfterStore
from iris.capture.schemas import ActionItem, CapturedFact, FactType
from iris.console._confidence_bar import render_confidence_bar as _render_confidence_bar


# ─────────────────────────────────────────────────────────────────
# Disclosure state
# ─────────────────────────────────────────────────────────────────

class DisclosureState(str, Enum):
    EXPANDED = "expanded"
    DISCLOSED = "disclosed"
    SKIPPED = "skipped"


# ─────────────────────────────────────────────────────────────────
# Virtual proxy (same pattern as ride_along.py _VirtualButton)
# ─────────────────────────────────────────────────────────────────

class _VirtualButton:
    """Proxy with button-like attributes; returned by overridden query_one()."""

    def __init__(
        self,
        *,
        label: str = "",
        disabled: bool = False,
        aria_label: str = "",
    ) -> None:
        self.label = label
        self.disabled = disabled
        self.aria_label = aria_label


# ─────────────────────────────────────────────────────────────────
# DisclosureCard
# ─────────────────────────────────────────────────────────────────

_DISCLOSURE_SCRIPT = (
    "This call is being assisted by AI (Iris).\n"
    "Iris will listen and help capture important information."
)

_STATE_DIR = Path.home() / ".local" / "share" / "iris"


class DisclosureCard(Widget):
    """AI disclosure modal gate — focus-trapped; acknowledges AI listening consent.

    NOT a _BaseCard subclass — modal widget, not a feed card.

    Expanded state: orange border, amber header, yellow script body, [D]/[S] buttons.
    Collapsed badge: '✓ AI Disclosed' (green) or '⊘ Skipped' (gray).
    Disk persistence: ~/.local/share/iris/disclosure-{session_id}.json.
    On re-init with matching session_id, loads saved state — skips expansion.
    """

    COMPONENT_CLASSES: set[str] = set()
    can_focus = True
    aria_role = "alertdialog"

    DEFAULT_CSS = """
    DisclosureCard {
        height: auto;
        border: heavy #f97316;
        padding: 1;
        margin-bottom: 1;
    }
    DisclosureCard.-badge {
        border: none;
        padding: 0 1;
        height: auto;
    }
    """

    def __init__(
        self,
        session_id: str,
        *,
        script: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._session_id = session_id
        self._script = script or _DISCLOSURE_SCRIPT
        self._focused_btn: str = "disclose"

        saved = self._load_state()
        self._state: DisclosureState = (
            saved if saved is not None else DisclosureState.EXPANDED
        )

        self._disclose_btn = _VirtualButton(
            label="[D] Disclosed",
            aria_label="Disclosed",
        )
        self._skip_btn = _VirtualButton(
            label="[S] Skip",
            aria_label="Skip",
        )

    # ── Disk I/O ──────────────────────────────────────────────────

    def _state_path(self) -> Path:
        return _STATE_DIR / f"disclosure-{self._session_id}.json"

    def _load_state(self) -> DisclosureState | None:
        try:
            data = json.loads(self._state_path().read_text(encoding="utf-8"))
            return DisclosureState(data["state"])
        except (OSError, KeyError, ValueError):
            return None

    def _save_state(self) -> None:
        path = self._state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"session_id": self._session_id, "state": self._state.value}),
            encoding="utf-8",
        )

    # ── Textual lifecycle ─────────────────────────────────────────

    def on_mount(self) -> None:
        if self._state is not DisclosureState.EXPANDED:
            self.add_class("-badge")

    def query_one(self, selector: str, *args: Any, **kwargs: Any) -> Any:
        if selector == "#disclose-btn":
            return self._disclose_btn
        if selector == "#skip-btn":
            return self._skip_btn
        return super().query_one(selector, *args, **kwargs)

    # ── Rendering ─────────────────────────────────────────────────

    def render(self) -> str:
        if self._state is DisclosureState.DISCLOSED:
            return "[bold green]✓ AI Disclosed[/bold green]"
        if self._state is DisclosureState.SKIPPED:
            return "[#999999]⊘ Skipped[/#999999]"

        # Expanded modal — highlight the focused button
        d_style = (
            "[bold underline green]"
            if self._focused_btn == "disclose"
            else "[green]"
        )
        s_style = (
            "[bold underline #999999]"
            if self._focused_btn == "skip"
            else "[#999999]"
        )

        lines = [
            "[bold yellow]⚠ DISCLOSURE REQUIRED[/bold yellow]",
            "",
            f"[yellow]{self._script}[/yellow]",
            "",
            f"{d_style}\\[D] Disclosed[/]  {s_style}\\[S] Skip[/]",
        ]
        return "\n".join(lines)

    # ── Input / focus trap ────────────────────────────────────────

    def on_key(self, event: Any) -> None:
        if self._state is not DisclosureState.EXPANDED:
            return

        key = event.key
        if key in ("tab", "shift+tab"):
            event.stop()
            event.prevent_default()
            self._focused_btn = (
                "skip" if self._focused_btn == "disclose" else "disclose"
            )
            self.refresh()
        elif key == "escape":
            event.stop()
            self.action_skip()
        elif key == "enter":
            event.stop()
            if self._focused_btn == "disclose":
                self.action_disclose()
            else:
                self.action_skip()
        elif key == "d":
            event.stop()
            self.action_disclose()
        elif key == "s":
            event.stop()
            self.action_skip()

    # ── Actions ───────────────────────────────────────────────────

    def action_disclose(self) -> None:
        if self._state is not DisclosureState.EXPANDED:
            return
        self._state = DisclosureState.DISCLOSED
        self._save_state()
        self.post_message(DisclosureAcknowledged(self._session_id))
        self.add_class("-badge")
        self.refresh()
        self._return_focus()

    def action_skip(self) -> None:
        if self._state is not DisclosureState.EXPANDED:
            return
        self._state = DisclosureState.SKIPPED
        self._save_state()
        self.post_message(DisclosureSkipped(self._session_id))
        self.add_class("-badge")
        self.refresh()
        self._return_focus()

    def _return_focus(self) -> None:
        try:
            from iris.console.ride_along import CardFeed
            feed = self.screen.query_one(CardFeed)
            feed.focus()
        except Exception:
            pass

    # ── Public state access ───────────────────────────────────────

    @property
    def state(self) -> DisclosureState:
        return self._state


# ─────────────────────────────────────────────────────────────────
# Messages — posted to parent on disclosure actions
# ─────────────────────────────────────────────────────────────────

class DisclosureAcknowledged(Message):
    """Operator disclosed AI listening to the far party — daemon may start far capture."""

    def __init__(self, session_id: str) -> None:
        super().__init__()
        self.session_id = session_id


class DisclosureSkipped(Message):
    """Operator explicitly declined to disclose — far capture must stay off this call."""

    def __init__(self, session_id: str) -> None:
        super().__init__()
        self.session_id = session_id


# ─────────────────────────────────────────────────────────────────
# Confidence bar (shared by CriticalFactCard and FactCard)
# ─────────────────────────────────────────────────────────────────
# _render_confidence_bar and _BAR_WIDTH imported from _confidence_bar above.


# ─────────────────────────────────────────────────────────────────
# Messages — posted to parent on fact card actions
# ─────────────────────────────────────────────────────────────────

class FactConfirmed(Message):
    """Operator confirmed the captured fact as-is."""

    def __init__(self, fact_id: str) -> None:
        super().__init__()
        self.fact_id = fact_id


class FactDismissed(Message):
    """Operator dismissed (rejected) the captured fact."""

    def __init__(self, fact_id: str) -> None:
        super().__init__()
        self.fact_id = fact_id


class FactValueOverride(Message):
    """Operator corrected the normalized value via CriticalFactCard edit mode."""

    def __init__(self, fact_id: str, new_value: str) -> None:
        super().__init__()
        self.fact_id = fact_id
        self.new_value = new_value


# ─────────────────────────────────────────────────────────────────
# _FactBaseCard — base for CriticalFactCard and FactCard
# ─────────────────────────────────────────────────────────────────

class _FactBaseCard(Widget):
    """Base for fact-feed cards; holds a CapturedFact and handles dismiss/confirm."""

    can_focus = True
    aria_role = "article"

    DEFAULT_CSS = """
    _FactBaseCard {
        height: auto;
        padding: 1;
        margin-bottom: 1;
    }
    """

    def __init__(self, fact: CapturedFact, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._fact = fact

    def action_confirm(self) -> None:
        self.post_message(FactConfirmed(self._fact.id))
        self.remove()

    def action_dismiss(self) -> None:
        self.post_message(FactDismissed(self._fact.id))
        self.remove()


# ─────────────────────────────────────────────────────────────────
# CriticalFactCard — amber border, pulsing animation, edit mode
# ─────────────────────────────────────────────────────────────────

class CriticalFactCard(_FactBaseCard):
    """High-urgency fact card: amber border, pulsing mount animation, inline edit.

    Actions: [D] Confirm, [E] Edit (inline, Enter=save / Esc=cancel), [X] Dismiss.
    ARIA: aria-live=assertive.
    Edit mode posts FactValueOverride to the app; Confirm/Dismiss post their own messages.
    Pulsing animation stops after 4 cycles (4.8 s) or on first focus.
    Set PREFERS_REDUCED_MOTION=1 to disable the animation entirely.
    """

    aria_role = "article"

    DEFAULT_CSS = """
    CriticalFactCard {
        border: heavy #f59e0b;
        height: auto;
        padding: 1;
        margin-bottom: 1;
    }
    CriticalFactCard.-pulse-dim {
        border: heavy #7c5308;
    }
    CriticalFactCard:focus {
        border: heavy #fbbf24;
    }
    """

    def __init__(self, fact: CapturedFact, **kwargs: Any) -> None:
        super().__init__(fact, **kwargs)
        self._editing: bool = False
        self._edit_buffer: str = ""
        self._pulse_timer: Any = None
        self._pulse_count: int = 0
        self._pulse_bright: bool = True

    def on_mount(self) -> None:
        if os.environ.get("PREFERS_REDUCED_MOTION", "0") == "1":
            return
        self._pulse_timer = self.set_interval(0.6, self._pulse_tick)

    def _pulse_tick(self) -> None:
        self._pulse_count += 1
        self._pulse_bright = not self._pulse_bright
        if self._pulse_bright:
            self.remove_class("-pulse-dim")
        else:
            self.add_class("-pulse-dim")
        if self._pulse_count >= 8:  # 4 cycles × 2 ticks
            self._pulse_timer.stop()
            self.remove_class("-pulse-dim")

    def on_focus(self) -> None:
        if self._pulse_timer is not None:
            self._pulse_timer.stop()
            self._pulse_timer = None
        self.remove_class("-pulse-dim")

    def render(self) -> str:
        conf_bar = _render_confidence_bar(self._fact.confidence)
        header = f"[bold #f59e0b]⚡ CRITICAL FACT[/bold #f59e0b]  {conf_bar}"

        if self._editing:
            cursor = "▋"
            return (
                f"{header}\n"
                f"[dim]{escape(self._fact.raw_text)}[/dim]\n"
                f"[bold white]{escape(self._edit_buffer)}{cursor}[/bold white]\n"
                f"[dim]Enter to confirm  •  Esc to cancel[/dim]"
            )

        return (
            f"{header}\n"
            f"[dim]{escape(self._fact.raw_text)}[/dim]\n"
            f"[bold white]{escape(self._fact.normalized_value)}[/bold white]\n"
            f"[dim]\\[D] Confirm  \\[E] Edit  \\[X] Dismiss[/dim]"
        )

    def on_key(self, event: Any) -> None:
        if self._editing:
            event.stop()
            event.prevent_default()
            if event.key == "escape":
                self._editing = False
                self._edit_buffer = ""
                self.refresh()
            elif event.key == "enter":
                self._commit_edit()
            elif event.key == "backspace":
                self._edit_buffer = self._edit_buffer[:-1]
                self.refresh()
            elif event.character and event.character.isprintable():
                self._edit_buffer += event.character
                self.refresh()
        else:
            if event.key == "e":
                event.stop()
                self._editing = True
                self._edit_buffer = self._fact.normalized_value
                self.refresh()
            elif event.key == "d":
                event.stop()
                self.action_confirm()
            elif event.key == "x":
                event.stop()
                self.action_dismiss()

    def _commit_edit(self) -> None:
        new_value = self._edit_buffer.strip()
        if not new_value:
            # Empty buffer = user changed their mind; treat as cancel
            self._editing = False
            self._edit_buffer = ""
            self.refresh()
            return
        self.post_message(FactValueOverride(self._fact.id, new_value))
        self._editing = False
        self._edit_buffer = ""
        self.remove()


# ─────────────────────────────────────────────────────────────────
# FactCard — teal border, confirm/dismiss only (no edit)
# ─────────────────────────────────────────────────────────────────

class FactCard(_FactBaseCard):
    """Normal-confidence fact card: teal border, confirm/dismiss/edit.

    Actions: [D] Confirm, [E] Edit (inline, Enter=save / Esc=cancel), [X] Dismiss.
    ARIA: aria-live=polite.
    """

    aria_role = "article"

    DEFAULT_CSS = """
    FactCard {
        border: solid #14b8a6;
        height: auto;
        padding: 1;
        margin-bottom: 1;
    }
    FactCard:focus {
        border: heavy #2dd4bf;
    }
    """

    def __init__(self, fact: CapturedFact, **kwargs: Any) -> None:
        super().__init__(fact, **kwargs)
        self._editing: bool = False
        self._edit_buffer: str = ""

    def render(self) -> str:
        conf_bar = _render_confidence_bar(self._fact.confidence)
        header = f"[bold #14b8a6]● FACT[/bold #14b8a6]  {conf_bar}"

        if self._editing:
            cursor = "▋"
            return (
                f"{header}\n"
                f"[dim]{escape(self._fact.raw_text)}[/dim]\n"
                f"[bold white]{escape(self._edit_buffer)}{cursor}[/bold white]\n"
                f"[dim]Enter to confirm  •  Esc to cancel[/dim]"
            )

        return (
            f"{header}\n"
            f"[dim]{escape(self._fact.raw_text)}[/dim]\n"
            f"[bold white]{escape(self._fact.normalized_value)}[/bold white]\n"
            f"[dim]\\[D] Confirm  \\[E] Edit  \\[X] Dismiss[/dim]"
        )

    def on_key(self, event: Any) -> None:
        if self._editing:
            event.stop()
            event.prevent_default()
            if event.key == "escape":
                self._editing = False
                self._edit_buffer = ""
                self.refresh()
            elif event.key == "enter":
                self._commit_edit()
            elif event.key == "backspace":
                self._edit_buffer = self._edit_buffer[:-1]
                self.refresh()
            elif event.character and event.character.isprintable():
                self._edit_buffer += event.character
                self.refresh()
        else:
            if event.key == "e":
                event.stop()
                self._editing = True
                self._edit_buffer = self._fact.normalized_value
                self.refresh()
            elif event.key == "d":
                event.stop()
                self.action_confirm()
            elif event.key == "x":
                event.stop()
                self.action_dismiss()

    def _commit_edit(self) -> None:
        new_value = self._edit_buffer.strip()
        if not new_value:
            # Empty buffer = user changed their mind; treat as cancel
            self._editing = False
            self._edit_buffer = ""
            self.refresh()
            return
        self.post_message(FactValueOverride(self._fact.id, new_value))
        self._editing = False
        self._edit_buffer = ""
        self.remove()


# ─────────────────────────────────────────────────────────────────
# ActionItemCard — indigo border, three-field inline edit mode
# ─────────────────────────────────────────────────────────────────

class ActionItemConfirmed(Message):
    """Operator confirmed the action item as-is."""

    def __init__(self, item_id: str) -> None:
        super().__init__()
        self.item_id = item_id


class ActionItemEdited(Message):
    """Operator saved edits to an action item."""

    def __init__(
        self,
        item_id: str,
        description: str,
        owner: str,
        due_date: str | None,
    ) -> None:
        super().__init__()
        self.item_id = item_id
        self.description = description
        self.owner = owner
        self.due_date = due_date or None


def _owner_display(owner: str | None) -> str:
    return owner if owner else "Them"


# Edit field order: 0=description, 1=due_date, 2=owner
_EDIT_FIELD_LABELS = ["Description", "Due", "Owner"]
_N_EDIT_FIELDS = 3


class ActionItemCard(Widget):
    """Action item card: indigo border, description + owner + due date, inline edit.

    Actions: [D] Confirm (as-is), [E] Edit (Tab cycles fields, Enter saves, Esc cancels).
    Owner defaults to 'Them' when ActionItem.owner is empty/None.
    ARIA: aria-live=polite.
    """

    can_focus = True
    aria_role = "article"

    DEFAULT_CSS = """
    ActionItemCard {
        border: solid #818cf8;
        height: auto;
        padding: 1;
        margin-bottom: 1;
    }
    ActionItemCard:focus {
        border: heavy #a5b4fc;
    }
    """

    def __init__(self, item: ActionItem, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._item = item
        self._editing: bool = False
        self._edit_field: int = 0
        self._edit_desc: str = ""
        self._edit_due: str = ""
        self._edit_owner: str = ""

    def _start_edit(self) -> None:
        self._editing = True
        self._edit_field = 0
        self._edit_desc = self._item.description
        self._edit_due = self._item.due_date or ""
        self._edit_owner = _owner_display(self._item.owner)
        self.refresh()

    def _cancel_edit(self) -> None:
        self._editing = False
        self.refresh()

    def _commit_edit(self) -> None:
        due = self._edit_due.strip() or None
        self.post_message(
            ActionItemEdited(
                self._item.id,
                self._edit_desc.strip() or self._item.description,
                self._edit_owner.strip() or "Them",
                due,
            )
        )
        self._editing = False
        self.remove()

    def _current_buf(self) -> str:
        return [self._edit_desc, self._edit_due, self._edit_owner][self._edit_field]

    def _set_current_buf(self, value: str) -> None:
        if self._edit_field == 0:
            self._edit_desc = value
        elif self._edit_field == 1:
            self._edit_due = value
        else:
            self._edit_owner = value

    def render(self) -> str:
        owner_str = _owner_display(self._item.owner)
        due_str = self._item.due_date if self._item.due_date else "—"

        if self._editing:
            cursor = "▋"
            lines = [
                f"[bold #818cf8]✓ ACTION ITEM[/bold #818cf8]  [dim]Owner: {escape(self._edit_owner)}{cursor if self._edit_field == 2 else ''}[/dim]",
                f"[bold white]{escape(self._edit_desc)}{cursor if self._edit_field == 0 else ''}[/bold white]",
                f"[dim]Due: {escape(self._edit_due)}{cursor if self._edit_field == 1 else ''}[/dim]",
                "[dim]Tab to switch field  •  Enter to save  •  Esc to cancel[/dim]",
            ]
            return "\n".join(lines)

        return (
            f"[bold #818cf8]✓ ACTION ITEM[/bold #818cf8]  [dim]Owner: {escape(owner_str)}[/dim]\n"
            f"[bold white]{escape(self._item.description)}[/bold white]\n"
            f"[dim]Due: {escape(due_str)}[/dim]\n"
            f"[dim]\\[D] Confirm  \\[E] Edit[/dim]"
        )

    def on_key(self, event: Any) -> None:
        if self._editing:
            event.stop()
            event.prevent_default()
            if event.key == "escape":
                self._cancel_edit()
            elif event.key == "enter":
                self._commit_edit()
            elif event.key == "tab":
                self._edit_field = (self._edit_field + 1) % _N_EDIT_FIELDS
                self.refresh()
            elif event.key == "shift+tab":
                self._edit_field = (self._edit_field - 1) % _N_EDIT_FIELDS
                self.refresh()
            elif event.key == "backspace":
                self._set_current_buf(self._current_buf()[:-1])
                self.refresh()
            elif event.character and event.character.isprintable():
                self._set_current_buf(self._current_buf() + event.character)
                self.refresh()
        else:
            if event.key == "e":
                event.stop()
                self._start_edit()
            elif event.key == "d":
                event.stop()
                self.post_message(ActionItemConfirmed(self._item.id))
                self.remove()

    def action_dismiss(self) -> None:
        """Remove the card (backward-compat with ride_along.py ActionItemCard API)."""
        self.remove()

    def action_create_reminder(self) -> None:
        """Delegate to app.reminder_hook (backward-compat with ride_along.py API)."""
        hook = getattr(self.app, "reminder_hook", None)
        if hook is not None:
            hook.create_reminder(self._item.description)


# ─────────────────────────────────────────────────────────────────
# PriorCommitmentCard — "Since last time" open-commitment display (ti-w0dvp)
# ─────────────────────────────────────────────────────────────────

class PriorCommitmentCard(Widget):
    """Displays one open commitment row from AfterStore.get_open_commitments().

    "Broken" is a computed overdue-vs-due_date display state, not a DB status --
    get_open_commitments() only ever returns status='open' rows. [H]/[B] resolve
    the commitment via the AfterStore reference the caller passed in, then
    remove() itself, mirroring FactCard/ActionItemCard's remove-after-resolve
    idiom. A _resolved guard mirrors DisclosureCard's already-resolved no-repost
    check so a second action_honor()/action_break() can't double-write or
    double-remove().
    """

    can_focus = True
    aria_role = "article"

    DEFAULT_CSS = """
    PriorCommitmentCard {
        height: auto;
        padding: 1;
        margin-bottom: 1;
    }
    PriorCommitmentCard.-broken {
        border: solid #f87171;
    }
    PriorCommitmentCard.-open {
        border: solid #818cf8;
    }
    PriorCommitmentCard:focus {
        border: heavy #a5b4fc;
    }
    """

    def __init__(
        self,
        commitment: dict,
        store: AfterStore,
        *,
        rep_name: str = "",
        _now: date | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._commitment = commitment
        self._store = store
        self._rep_name = rep_name
        self._now = _now
        self._resolved = False

    # ── Overdue computation ────────────────────────────────────────

    def _due_date_obj(self) -> date | None:
        raw = self._commitment.get("due_date")
        if not raw:
            return None
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None

    @property
    def days_overdue(self) -> int:
        due = self._due_date_obj()
        if due is None:
            return 0
        today = self._now or date.today()
        diff = (today - due).days
        return diff if diff > 0 else 0

    @property
    def is_broken(self) -> bool:
        return self.days_overdue > 0

    def _who(self, *, capitalize: bool) -> str:
        if self._commitment["direction"] == "i_promised":
            return "You" if capitalize else "you"
        if self._rep_name:
            return self._rep_name
        return "Your rep" if capitalize else "your rep"

    # ── Textual lifecycle ──────────────────────────────────────────

    def on_mount(self) -> None:
        self.add_class("-broken" if self.is_broken else "-open")

    # ── Rendering ──────────────────────────────────────────────────

    def render(self) -> str:
        description = escape(self._commitment["description"])
        raw_due = self._commitment.get("due_date")
        due_str = escape(raw_due) if raw_due else "—"

        if self.is_broken:
            who = escape(self._who(capitalize=False))
            header = (
                f"[bold #f87171]⚠ BROKEN COMMITMENT[/bold #f87171]  "
                f"[dim]{self.days_overdue}d overdue[/dim]"
            )
            body = (
                f"[bold white]{who} promised {description} by {due_str} "
                f"— it didn't happen.[/bold white]"
            )
            footer = "[dim]\\[H] Honor anyway  \\[B] Confirm broken[/dim]"
            return f"{header}\n{body}\n{footer}"

        who = escape(self._who(capitalize=True))
        header = "[bold #818cf8]⏳ OPEN COMMITMENT[/bold #818cf8]"
        body = f"[bold white]{who} promised {description}[/bold white]\n[dim]Due: {due_str}[/dim]"
        footer = "[dim]\\[H] Honor  \\[B] Broken[/dim]"
        return f"{header}\n{body}\n{footer}"

    # ── Input ──────────────────────────────────────────────────────

    def on_key(self, event: Any) -> None:
        if event.key == "h":
            event.stop()
            self.action_honor()
        elif event.key == "b":
            event.stop()
            self.action_break()

    # ── Actions ────────────────────────────────────────────────────

    def action_honor(self) -> None:
        if self._resolved:
            return
        self._resolved = True
        self._store.resolve_commitment(self._commitment["id"], "honored")
        self.remove()

    def action_break(self) -> None:
        if self._resolved:
            return
        self._resolved = True
        self._store.resolve_commitment(self._commitment["id"], "broken")
        self.remove()


# ─────────────────────────────────────────────────────────────────
# CallCardView — full-screen Textual App (ti-rnlqo.6.4)
# ─────────────────────────────────────────────────────────────────

class _ParticipationLevel(Enum):
    SILENT = 0
    AMBIENT = 1
    AUDIO_PRIVATE = 2
    ON_CALL = 3


class _CallCardFeed(ScrollableContainer):
    """Scrollable card feed; newest card prepended at top."""
    aria_role = "feed"
    DEFAULT_CSS = """
    _CallCardFeed {
        height: 1fr;
        overflow-y: scroll;
    }
    """


def _fact_from_dict(d: dict) -> CapturedFact:
    """Reconstruct a CapturedFact from a daemon event payload dict."""
    return CapturedFact(
        session_id=d["session_id"],
        fact_type=FactType(d["fact_type"]),
        raw_text=d["raw_text"],
        normalized_value=d["normalized_value"],
        transcript_turn_id=d.get("transcript_turn_id", 0),
        transcript_offset_s=d.get("transcript_offset_s", 0.0),
        speaker=d.get("speaker", ""),
        confidence=d.get("confidence", 0.0),
        critical=bool(d.get("critical", False)),
        confirmed=d.get("confirmed"),
        source_layer=d.get("source_layer", 1),
        id=d.get("id", uuid4().hex),
        created_at=d.get("created_at", time.time()),
    )


def _action_item_from_dict(d: dict) -> ActionItem:
    """Reconstruct an ActionItem from a daemon event payload dict."""
    return ActionItem(
        session_id=d["session_id"],
        description=d["description"],
        trigger=d.get("trigger", ""),
        owner=d.get("owner", ""),
        transcript_turn_id=d.get("transcript_turn_id", 0),
        transcript_offset_s=d.get("transcript_offset_s", 0.0),
        speaker=d.get("speaker", ""),
        confidence=d.get("confidence", 0.0),
        due_date=d.get("due_date"),
        confirmed=d.get("confirmed"),
        source_layer=d.get("source_layer", 1),
        id=d.get("id", uuid4().hex),
        created_at=d.get("created_at", time.time()),
    )


class CallCardView(App):
    """Full-screen Textual call card — DisclosureCard + live fact/action feeds.

    Layout (top → bottom): header bar, DisclosureCard, card feed (CriticalFact /
    Fact / ActionItem cards newest-first), enriching indicator, footer.

    Call on_daemon_event(event_dict) from the daemon API connection thread to
    feed live events into the UI. Thread-safe via Textual's call_from_thread.
    """

    CSS = """
    Screen {
        background: #0f172a;
    }
    #header-bar {
        height: 1;
        background: #1e293b;
        color: $text;
        content-align: left middle;
        padding: 0 1;
    }
    #enriching {
        height: 1;
        background: #f59e0b;
        color: #0f172a;
        content-align: center middle;
        display: none;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("]", "participation_up", "Level↑"),
        Binding("[", "participation_down", "Level↓"),
    ]

    participation_level: reactive[_ParticipationLevel] = reactive(
        _ParticipationLevel.SILENT
    )

    def __init__(self, *, session_id: str = "", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._session_id = session_id
        self._caller_phone = ""
        self._topic = ""
        self._disclosure: DisclosureCard | None = None

    def compose(self) -> ComposeResult:
        yield Static("📞 Iris Call Card", id="header-bar")
        self._disclosure = DisclosureCard(self._session_id or "default")
        yield self._disclosure
        yield _CallCardFeed(id="card-feed")
        yield Static(
            "⏳ Enriching...",
            id="enriching",
            markup=False,
        )
        yield Footer()

    def _prepend_card(self, card: Widget) -> None:
        feed = self.query_one("#card-feed", _CallCardFeed)
        if feed.children:
            feed.mount(card, before=feed.children[0])
        else:
            feed.mount(card)

    # ── Daemon event router ───────────────────────────────────────

    def on_daemon_event(self, event: dict) -> None:
        """Route a daemon event dict; call from any thread via call_from_thread."""
        ev = event.get("event", "")
        if ev == "call_card_started":
            self._handle_started(event)
        elif ev == "call_card_fact":
            self._handle_fact(event)
        elif ev == "call_card_action_item":
            self._handle_action_item(event)
        elif ev == "call_card_ended":
            self.call_from_thread(self._show_enriching)
        elif ev == "call_card_enriched":
            self.call_from_thread(self._hide_enriching)

    def _handle_started(self, event: dict) -> None:
        self._caller_phone = event.get("caller_phone", "")
        self._topic = event.get("topic", "")
        self._session_id = event.get("session_id", self._session_id)
        header = f"📞 Iris Call Card | {self._caller_phone}"
        if self._topic:
            header += f" · {self._topic}"
        self.call_from_thread(self.query_one("#header-bar", Static).update, header)

    def _handle_fact(self, event: dict) -> None:
        payload = event.get("fact", event)
        try:
            fact = _fact_from_dict(payload)
        except (KeyError, ValueError):
            return
        card: Widget = CriticalFactCard(fact) if fact.critical else FactCard(fact)
        self.call_from_thread(self._prepend_card, card)

    def _handle_action_item(self, event: dict) -> None:
        payload = event.get("action_item", event)
        try:
            item = _action_item_from_dict(payload)
        except (KeyError, ValueError):
            return
        self.call_from_thread(self._prepend_card, ActionItemCard(item))

    def _show_enriching(self) -> None:
        self.query_one("#enriching").display = True

    def _hide_enriching(self) -> None:
        self.query_one("#enriching").display = False

    # ── Participation level ───────────────────────────────────────

    def action_participation_up(self) -> None:
        levels = list(_ParticipationLevel)
        idx = levels.index(self.participation_level)
        if idx < len(levels) - 1:
            self.participation_level = levels[idx + 1]

    def action_participation_down(self) -> None:
        levels = list(_ParticipationLevel)
        idx = levels.index(self.participation_level)
        if idx > 0:
            self.participation_level = levels[idx - 1]


# ─────────────────────────────────────────────────────────────────
# CallCardPanel — embeddable live feed for IrisConsole (ti-913rw)
# ─────────────────────────────────────────────────────────────────

class CallCardPanel(ScrollableContainer):
    """Live Call Card side panel for the ride-along console.

    A newest-first feed of the DisclosureCard + Critical/Fact/ActionItem cards,
    driven by ``call_card_*`` daemon events via :meth:`handle_event`. It is meant
    to sit alongside the ride-along log (additive — the console keeps speaking
    when addressed; this just shows what the daemon silently captured).

    ``handle_event`` runs on the console's UI thread (events are drained from the
    app's event queue), so widget mutations are direct — no ``call_from_thread``.

    Payload keys match the daemon broadcasts (iris/daemon/call_card_host.py):
    ``fact`` / ``item`` / ``caller_number`` / ``contact_name`` / ``script``.
    """

    DEFAULT_CSS = """
    CallCardPanel {
        width: 46;
        height: 1fr;
        background: #10151f;
        border: round #3a5080;
        padding: 0 1;
        display: none;
    }
    CallCardPanel.visible-panel {
        display: block;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.border_title = "Call Card"
        self._session_id = ""

    def compose(self) -> ComposeResult:
        # A visible empty state so [V] on an idle console shows the panel is there
        # (an empty container renders as nothing). Hidden once real cards arrive.
        yield Static("[dim]○ waiting for a call…[/dim]", id="cc-empty")

    def _hide_placeholder(self) -> None:
        try:
            self.query_one("#cc-empty").display = False
        except Exception:  # noqa: BLE001 — placeholder already gone
            pass

    def _prepend(self, card: Widget) -> None:
        self._hide_placeholder()
        if self.children:
            self.mount(card, before=self.children[0])
        else:
            self.mount(card)

    def show_panel(self) -> None:
        self.add_class("visible-panel")

    def toggle_panel(self) -> None:
        self.toggle_class("visible-panel")

    def handle_event(self, event: dict) -> None:
        """Route one ``call_card_*`` daemon event into the panel. Unknown → ignored."""
        ev = event.get("event", "")
        if ev == "call_card_started":
            self._session_id = event.get("session_id", "")
            caller = event.get("contact_name") or event.get("caller_number") or "call"
            self.border_title = f"Call Card · {caller}"
            self.border_subtitle = ""
            self.show_panel()
        elif ev == "call_card_disclosure_needed":
            self._session_id = event.get("session_id", self._session_id)
            self.show_panel()
            self._prepend(
                DisclosureCard(self._session_id or "default", script=event.get("script"))
            )
        elif ev == "call_card_fact":
            try:
                fact = _fact_from_dict(event.get("fact", event))
            except (KeyError, ValueError):
                return
            self._prepend(CriticalFactCard(fact) if fact.critical else FactCard(fact))
            self.show_panel()
        elif ev == "call_card_action_item":
            try:
                item = _action_item_from_dict(event.get("item", event))
            except (KeyError, ValueError):
                return
            self._prepend(ActionItemCard(item))
            self.show_panel()
        elif ev == "call_card_enriched":
            self.border_subtitle = "✨ enriched"
        elif ev == "call_card_ended":
            self.border_subtitle = "· ended"
