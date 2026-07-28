"""Operator Config UI — Screen 1 of the presentation profile UI (ti-hxse).

Language set panel (ordered checklist, keyboard drag-to-reorder) and
cadence slider (0.7–1.4×, screen-reader-accessible).

Pure-logic helpers (reask_callout_text) importable without Textual.
Textual widget classes defined only when Textual is available.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Pure-logic helpers — no Textual dependency
# ---------------------------------------------------------------------------

def reask_callout_text() -> str:
    """Return the descriptive callout text for the re-ask cadence note (WCAG 1.4.1)."""
    return "⚠ Re-ask trigger drops cadence to 0.7× for that turn only"


# ---------------------------------------------------------------------------
# Textual widget classes — defined only when Textual is available
# ---------------------------------------------------------------------------

try:
    from textual.app import ComposeResult
    from textual.widget import Widget
    from textual.widgets import Button, Static

    class LanguageSetPanel(Widget):
        """Ordered checklist of available languages with keyboard drag-to-reorder (WCAG 2.1.1)."""

        can_focus = True

        def __init__(self, languages: list[str], **kwargs) -> None:
            super().__init__(**kwargs)
            self._language_order = list(languages)
            self._dragging: bool = False
            self._drag_idx: int = -1
            self._original_order: list[str] = list(languages)

        @property
        def language_order(self) -> list[str]:
            return list(self._language_order)

        def compose(self) -> ComposeResult:
            for lang in self._language_order:
                yield Static(lang, classes="lang-item")

        def on_key(self, event) -> None:
            key = getattr(event, "key", "")
            if key == "space":
                if not self._dragging:
                    self._dragging = True
                    self._original_order = list(self._language_order)
                    self._drag_idx = 0
                else:
                    self._dragging = False
            elif key == "escape" and self._dragging:
                self._language_order = list(self._original_order)
                self._dragging = False
            elif key == "down" and self._dragging:
                i = self._drag_idx
                if i < len(self._language_order) - 1:
                    self._language_order[i], self._language_order[i + 1] = (
                        self._language_order[i + 1],
                        self._language_order[i],
                    )
                    self._drag_idx = i + 1
            elif key == "up" and self._dragging:
                i = self._drag_idx
                if i > 0:
                    self._language_order[i], self._language_order[i - 1] = (
                        self._language_order[i - 1],
                        self._language_order[i],
                    )
                    self._drag_idx = i - 1

    class CadencePanel(Widget):
        """Cadence speed slider (0.7–1.4×) with screen-reader accessible value (WCAG 4.1.2)."""

        can_focus = True

        def __init__(self, cadence: float = 1.0, **kwargs) -> None:
            super().__init__(**kwargs)
            self._cadence = cadence
            self.slider_aria_valuetext: str = f"{cadence:.1f}×"
            self.accessible_value: str = self.slider_aria_valuetext

        def set_cadence(self, value: float) -> None:
            self._cadence = value
            self.slider_aria_valuetext = f"{value:.1f}×"
            self.accessible_value = self.slider_aria_valuetext

        def compose(self) -> ComposeResult:
            yield Static(f"Cadence: {self.slider_aria_valuetext}", id="cadence-display")

    class ProfileConfigScreen(Widget):
        """Screen 1 — Operator Config: language set + cadence panel + save (ti-hxse)."""

        def compose(self) -> ComposeResult:
            yield LanguageSetPanel(languages=["en"], id="language-set-panel")
            yield CadencePanel(cadence=1.0, id="cadence-panel")
            yield Button("Save", id="save-btn")
            yield Static(reask_callout_text(), id="reask-callout")

except ImportError:
    pass
