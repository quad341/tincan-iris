"""Call Card widgets for iris/console — ti-rnlqo.6 (builder phase).

ti-rnlqo.6.1: DisclosureCard — focus-trapped modal gate with disk state persistence
"""
from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any

from textual.widget import Widget


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
