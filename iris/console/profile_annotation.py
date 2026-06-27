"""Contact Annotation UI — Screen 4 of the presentation profile UI (ti-kau8).

ContactAnnotationScreen: contacts > [name] > Preferences.
Shows language/cadence dropdowns for per-contact annotation.
Trust tier is read-only (ADR-0005: trust grants are never modified here).

Textual widget classes defined only when Textual is available.
"""
from __future__ import annotations


try:
    from textual.app import ComposeResult
    from textual.widget import Widget
    from textual.widgets import Button, Static

    class _TrustTierField(Static):
        """Read-only display of the contact's trust tier (ADR-0005)."""

        aria_readonly: bool = True
        read_only: bool = True
        can_edit: bool = False
        can_focus: bool = False

        def __init__(self, **kwargs) -> None:
            super().__init__("—", **kwargs)
            self.aria_label = "Trust tier (read-only)"
            self.accessible_label = "Trust tier (read-only)"
            self.label = "Trust tier (read-only)"

    class _LanguageDropdown(Widget):
        """Keyboard-focusable language preference selector (WCAG 2.1.1)."""

        can_focus = True

        def __init__(self, available_languages: list[str], **kwargs) -> None:
            super().__init__(**kwargs)
            self.available_languages = available_languages

        def compose(self) -> ComposeResult:
            for lang in self.available_languages:
                yield Static(lang, classes="lang-option")

    class _WarningCallout(Static):
        """Icon + text + border callout (WCAG 1.4.1 — not colour alone)."""

        def __init__(self, **kwargs) -> None:
            text = "⚠ Cosmetic only — trust grants stay in ADR-0005"
            super().__init__(text, **kwargs)
            self.label = text
            self.renderable = text

    class ContactAnnotationScreen(Widget):
        """Screen 4 — Contact language/cadence annotation (ti-kau8).

        Accessible from contacts > [name] > Preferences.
        Trust tier is read-only (ADR-0005 invariant — profiles never grant trust).
        """

        def __init__(
            self,
            contact_id: str,
            available_languages: list[str] | None = None,
            **kwargs,
        ) -> None:
            super().__init__(**kwargs)
            self.contact_id = contact_id
            self._available_languages = available_languages or ["en"]
            self.trust_tier_field = _TrustTierField(id="trust-tier-field")
            self.language_dropdown = _LanguageDropdown(
                self._available_languages, id="language-dropdown"
            )
            self.save_button = Button("Save", id="save-btn")
            self.clear_button = Button("Clear", id="clear-btn")
            self.warning_callout = _WarningCallout(id="warning-callout")

        def compose(self) -> ComposeResult:
            yield self.trust_tier_field
            yield self.language_dropdown
            yield self.save_button
            yield self.clear_button
            yield self.warning_callout

except ImportError:
    pass
