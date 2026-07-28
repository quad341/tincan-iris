"""Profile status screens — Screens 2 and 3 of the presentation profile UI (ti-ih35).

Screen 2 — DetectionInProgressScreen: shown while utt-1 Whisper analysis runs.
Screen 3 — ProfileLockedScreen: shown after the profile is locked for the call.

Pure-logic A11y helpers (confidence_bar_label, resolution_chain_step_label,
locked_badge_aria_label) are importable without Textual installed.
Textual widget classes are defined only when Textual is available.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from iris.profile_resolver import PresentationProfile


# ---------------------------------------------------------------------------
# Pure-logic A11y helpers — no Textual dependency
# ---------------------------------------------------------------------------

def confidence_bar_label(lang: str, confidence: float) -> str:
    """Return accessible text for a confidence bar (WCAG 1.4.1 — not colour alone)."""
    pct = round(confidence * 100)
    return f"{lang}: {pct}%"


def resolution_chain_step_label(
    source: str,
    lang: str | None,
    confidence: float | None,
    *,
    is_active: bool,
) -> str:
    """Return a text label for a resolution chain step (WCAG 1.3.1 / 1.4.1)."""
    if is_active:
        pct = f" ({round(confidence * 100)}%)" if confidence is not None else ""
        lang_str = f" {lang}" if lang else ""
        return f"✓{lang_str}{pct} ← ACTIVE"
    return f"— {source}: none"


def locked_badge_aria_label() -> str:
    """Return the WCAG-compliant aria-label for the profile-locked badge (WCAG 4.1.2)."""
    return "Profile locked for this call"


# ---------------------------------------------------------------------------
# Internal plain-Python proxies (no Textual DOM overhead)
# ---------------------------------------------------------------------------

class _ConfidenceBar:
    """Plain object returned by DetectionInProgressScreen.confidence_bars dict."""

    def __init__(self, lang: str, confidence: float) -> None:
        pct = round(confidence * 100)
        self.accessible_label = f"{lang}: {pct}%"
        self.aria_label = self.accessible_label
        self.lang = lang
        self.confidence = confidence


class _ChainItem:
    """One step in the four-step resolution chain."""

    def __init__(
        self,
        source: str,
        lang: str | None = None,
        confidence: float | None = None,
        *,
        is_active: bool = False,
    ) -> None:
        self.source = source
        self.lang = lang
        self.confidence = confidence
        self.is_active = is_active
        self.aria_current = is_active
        self.is_aria_current = is_active
        if is_active:
            pct = f" ({round(confidence * 100)}%)" if confidence is not None else ""
            lang_str = f" {lang}" if lang else ""
            self.status_text = f"✓{lang_str}{pct} ← ACTIVE"
        else:
            self.status_text = f"— {source}: none"
        self.label = self.status_text
        self.renderable = self.status_text


class _ResolutionChain:
    """Ordered container for resolution chain items (override → annotation → detector → default)."""

    SOURCES = ("override", "annotation", "detector", "default")

    def __init__(self, active_source: str | None = None, lang: str | None = None, confidence: float | None = None) -> None:
        self._items = [
            _ChainItem(src, lang if src == active_source else None,
                       confidence if src == active_source else None,
                       is_active=(src == active_source))
            for src in self.SOURCES
        ]

    @property
    def items(self) -> list[_ChainItem]:
        return self._items

    def __iter__(self):
        return iter(self._items)


class _LockedBadge:
    """Plain object representing the 🔒 LOCKED badge (WCAG 4.1.2)."""

    aria_label = "Profile locked for this call"
    accessible_label = "Profile locked for this call"
    label = "🔒 LOCKED"
    renderable = "🔒 LOCKED"


# ---------------------------------------------------------------------------
# Textual widget classes — defined only when Textual is available
# ---------------------------------------------------------------------------

try:
    from textual.app import ComposeResult
    from textual.widget import Widget
    from textual.widgets import Static

    class DetectionInProgressScreen(Widget):
        """Screen 2 — shown while Whisper language detection runs on utt-1."""

        spinner_label: str = "Detecting… [voice]"

        def __init__(
            self,
            utterance: str,
            confidences: dict[str, float],
            **kwargs,
        ) -> None:
            super().__init__(**kwargs)
            self._utterance = utterance
            self.confidence_bars: dict[str, _ConfidenceBar] = {
                lang: _ConfidenceBar(lang, conf)
                for lang, conf in confidences.items()
            }
            self.resolution_chain = _ResolutionChain(active_source="detector")

        def compose(self) -> ComposeResult:
            yield Static(self._utterance, id="utterance")
            yield Static(self.spinner_label, id="spinner")

        def render(self) -> str:
            return f"[amber][WAIT] Detecting… [voice][/amber]  {self._utterance}"

    class ProfileLockedScreen(Widget):
        """Screen 3 — shown after the profile is locked for the call."""

        def __init__(
            self,
            profile: PresentationProfile,
            utterance: str,
            **kwargs,
        ) -> None:
            super().__init__(**kwargs)
            self._profile = profile
            self._utterance = utterance
            self.resolution_chain = _ResolutionChain(
                active_source=profile.source,
                lang=profile.language,
                confidence=None,
            )
            self.locked_badge = _LockedBadge()

        def compose(self) -> ComposeResult:
            yield Static(self._utterance, id="utterance")
            yield Static(self.locked_badge.label, id="locked-badge")

        def render(self) -> str:
            lang = self._profile.language
            return f"[blue][SPEAKING] [voice] · {lang} · 🔒[/blue]"

except ImportError:
    pass
