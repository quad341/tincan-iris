"""Call Card widgets for iris/console — ti-rnlqo.6 (builder phase).

ti-rnlqo.6.1: DisclosureCard — focus-trapped modal gate with disk state persistence
ti-rnlqo.6.2: CriticalFactCard, FactCard — confidence bar, edit mode, CapturedFact schema
ti-rnlqo.6.3: ActionItemCard — description/owner/due_date display + inline edit mode
"""
from __future__ import annotations

import json
import os
from enum import Enum
from pathlib import Path
from typing import Any

from textual.message import Message
from textual.widget import Widget

from iris.capture.schemas import ActionItem, CapturedFact


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
        self.add_class("-badge")
        self.refresh()
        self._return_focus()

    def action_skip(self) -> None:
        if self._state is not DisclosureState.EXPANDED:
            return
        self._state = DisclosureState.SKIPPED
        self._save_state()
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
# Confidence bar (shared by CriticalFactCard and FactCard)
# ─────────────────────────────────────────────────────────────────

_BAR_WIDTH = 10


def _render_confidence_bar(confidence: float) -> str:
    """Render a rounded-integer confidence bar with bucket colour.

    Operator decision (2026-06-30): show coarse bucket colour + integer %, not
    a raw float. Buckets: >=85% green, 60-84% amber (#f59e0b), <60% red.
    """
    pct = round(confidence * 100)
    filled = round(pct * _BAR_WIDTH / 100)
    bar = "▓" * filled + "░" * (_BAR_WIDTH - filled)
    if pct >= 85:
        color = "green"
    elif pct >= 60:
        color = "#f59e0b"
    else:
        color = "red"
    return f"[{color}]{pct}% {bar}[/{color}]"


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
                f"[dim]{self._fact.raw_text}[/dim]\n"
                f"[bold white]{self._edit_buffer}{cursor}[/bold white]\n"
                f"[dim]Enter to confirm  •  Esc to cancel[/dim]"
            )

        return (
            f"{header}\n"
            f"[dim]{self._fact.raw_text}[/dim]\n"
            f"[bold white]{self._fact.normalized_value}[/bold white]\n"
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
        if new_value:
            self.post_message(FactValueOverride(self._fact.id, new_value))
        self._editing = False
        self._edit_buffer = ""
        self.remove()


# ─────────────────────────────────────────────────────────────────
# FactCard — teal border, confirm/dismiss only (no edit)
# ─────────────────────────────────────────────────────────────────

class FactCard(_FactBaseCard):
    """Normal-confidence fact card: teal border, confirm/dismiss only.

    Actions: [D] Confirm, [X] Dismiss. No edit mode (deferred to ti-tr1m5).
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
    """

    def render(self) -> str:
        conf_bar = _render_confidence_bar(self._fact.confidence)
        return (
            f"[bold #14b8a6]● FACT[/bold #14b8a6]  {conf_bar}\n"
            f"[dim]{self._fact.raw_text}[/dim]\n"
            f"[bold white]{self._fact.normalized_value}[/bold white]\n"
            f"[dim]\\[D] Confirm  \\[X] Dismiss[/dim]"
        )

    def on_key(self, event: Any) -> None:
        if event.key == "d":
            event.stop()
            self.action_confirm()
        elif event.key == "x":
            event.stop()
            self.action_dismiss()


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

    aria_role = "article"

    DEFAULT_CSS = """
    ActionItemCard {
        border: solid #818cf8;
        height: auto;
        padding: 1;
        margin-bottom: 1;
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
                f"[bold #818cf8]✓ ACTION ITEM[/bold #818cf8]  [dim]Owner: {self._edit_owner}{cursor if self._edit_field == 2 else ''}[/dim]",
                f"[bold white]{self._edit_desc}{cursor if self._edit_field == 0 else ''}[/bold white]",
                f"[dim]Due: {self._edit_due}{cursor if self._edit_field == 1 else ''}[/dim]",
                f"[dim]Tab to switch field  •  Enter to save  •  Esc to cancel[/dim]",
            ]
            return "\n".join(lines)

        return (
            f"[bold #818cf8]✓ ACTION ITEM[/bold #818cf8]  [dim]Owner: {owner_str}[/dim]\n"
            f"[bold white]{self._item.description}[/bold white]\n"
            f"[dim]Due: {due_str}[/dim]\n"
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
