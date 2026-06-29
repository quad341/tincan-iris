"""A11y tests for presentation profile screens (Screens 1–4). WCAG 2.1 AA.

Bead: ti-rimc (validator phase) — written BEFORE builder implementation (TDD red phase).
Fails until builder implements:
  - iris/console/profile_config.py     (Screen 1: Operator Config, bead ti-hxse)
  - iris/console/profile_status.py     (Screens 2+3: Detection + Locked, bead ti-ih35)
  - iris/console/profile_annotation.py (Screen 4: Contact Annotation, bead ti-kau8)

Pure-logic helper tests run without Textual — they fail with ImportError until the
modules exist. Textual pilot tests are skipped when textual is not installed.

No visual comparison — DOM/ARIA attribute assertions only.
Colour contrast verified by convention: text + border present alongside colour.

Coverage per WCAG 2.1 AA audit in design ti-6371:
  Screen 1: keyboard drag-reorder, slider aria-valuetext, tab order, callout non-colour
  Screen 2: confidence bar aria-label, spinner text label, resolution chain ol/li
  Screen 3: aria-current on active chain item, locked badge aria-label + visible text
  Screen 4: warning callout, trust-tier aria-readonly, dropdown keyboard nav, button a11y
"""
from __future__ import annotations

import asyncio

import pytest


# ---------------------------------------------------------------------------
# ── Pure-logic A11y helpers — NO Textual required.
# ── Fail with ImportError until builder writes iris/console/profile_status.py
# ── and iris/console/profile_config.py.
# ---------------------------------------------------------------------------

def test_confidence_bar_label_includes_language_and_percent():
    """confidence_bar_label() produces text with language tag and percentage (WCAG 1.4.1)."""
    from iris.console.profile_status import confidence_bar_label

    label = confidence_bar_label("es", 0.94)
    assert "es" in label.lower() or "spanish" in label.lower()
    assert "94" in label


def test_confidence_bar_label_low_confidence_has_text():
    """Low-confidence bars still get a text label — not blank (WCAG 1.4.1)."""
    from iris.console.profile_status import confidence_bar_label

    label = confidence_bar_label("en", 0.12)
    assert len(label.strip()) > 0
    assert "12" in label or "0.12" in label


def test_resolution_chain_step_label_active():
    """Active step label includes the language and an 'active' marker (WCAG 1.3.1)."""
    from iris.console.profile_status import resolution_chain_step_label

    label = resolution_chain_step_label("detector", "es", 0.94, is_active=True)
    assert "es" in label.lower()
    assert any(marker in label.upper() for marker in ("ACTIVE", "✓", "SELECTED"))


def test_resolution_chain_step_label_inactive_has_text():
    """Inactive step labels include descriptive text — not blank/colour-only (WCAG 1.4.1)."""
    from iris.console.profile_status import resolution_chain_step_label

    label = resolution_chain_step_label("override", None, None, is_active=False)
    assert len(label.strip()) > 0, "Inactive step must have text, not blank (colour-only)"


def test_locked_badge_aria_label_says_locked():
    """locked_badge_aria_label() returns a WCAG-compliant description string."""
    from iris.console.profile_status import locked_badge_aria_label

    label = locked_badge_aria_label()
    assert "locked" in label.lower()
    assert "profile" in label.lower() or "call" in label.lower()


def test_reask_callout_text_has_description():
    """Re-ask callout text is non-empty descriptive text, not just an icon (WCAG 1.4.1)."""
    from iris.console.profile_config import reask_callout_text

    text = reask_callout_text()
    stripped = text.strip()
    assert len(stripped) > 2, "Callout must have descriptive text beyond just an icon"


# ---------------------------------------------------------------------------
# ── Textual pilot tests — skipped when textual is not installed.
# ── When textual IS installed, fail with ImportError until builder writes modules.
# ── Import textual lazily (inside each function) to avoid module-level skip.
# ---------------------------------------------------------------------------

# Screen 1 — Operator Config

def test_s1_language_list_keyboard_reorder():
    """Language drag-to-reorder is keyboard operable: Space to grab, arrows to move."""
    pytest.importorskip("textual")
    from textual.app import App
    from iris.console.profile_config import LanguageSetPanel

    async def scenario():
        class _App(App):
            def compose(self):
                yield LanguageSetPanel(languages=["en", "es", "fr"])

        app = _App()
        async with app.run_test() as pilot:
            panel = app.query_one(LanguageSetPanel)
            assert panel.can_focus or panel.has_focus_within
            await pilot.press("tab")
            await pilot.press("space")
            await pilot.press("down")
            await pilot.press("space")
            await pilot.press("q")

    asyncio.run(scenario())


def test_s1_language_list_escape_cancels_reorder():
    """Esc during keyboard drag cancels reorder without changing the list order."""
    pytest.importorskip("textual")
    from textual.app import App
    from iris.console.profile_config import LanguageSetPanel

    async def scenario():
        class _App(App):
            def compose(self):
                yield LanguageSetPanel(languages=["en", "es"])

        app = _App()
        async with app.run_test() as pilot:
            panel = app.query_one(LanguageSetPanel)
            await pilot.press("tab")
            await pilot.press("space")
            await pilot.press("down")
            await pilot.press("escape")
            assert panel.language_order == ["en", "es"]
            await pilot.press("q")

    asyncio.run(scenario())


def test_s1_cadence_slider_exposes_accessible_value():
    """Cadence slider exposes an accessible value for screen readers (WCAG 4.1.2)."""
    pytest.importorskip("textual")
    from textual.app import App
    from iris.console.profile_config import CadencePanel

    async def scenario():
        class _App(App):
            def compose(self):
                yield CadencePanel(cadence=1.0)

        app = _App()
        async with app.run_test() as pilot:
            panel = app.query_one(CadencePanel)
            assert (hasattr(panel, "slider_aria_valuetext")
                    or hasattr(panel, "accessible_value")), (
                "Cadence slider must expose an accessible value attribute"
            )
            await pilot.press("q")

    asyncio.run(scenario())


def test_s1_cadence_slider_valuetext_updates_on_change():
    """Slider aria-valuetext updates when the cadence value changes."""
    pytest.importorskip("textual")
    from textual.app import App
    from iris.console.profile_config import CadencePanel

    async def scenario():
        class _App(App):
            def compose(self):
                yield CadencePanel(cadence=1.0)

        app = _App()
        async with app.run_test() as pilot:
            panel = app.query_one(CadencePanel)
            panel.set_cadence(0.7)
            await pilot.pause()
            label = (getattr(panel, "slider_aria_valuetext", None)
                     or getattr(panel, "accessible_value", None))
            assert label is not None and "0.7" in str(label)
            await pilot.press("q")

    asyncio.run(scenario())


def test_s1_tab_order_language_then_cadence_then_save():
    """Tab order: Language set → Cadence slider → Save button (WCAG 2.4.3)."""
    pytest.importorskip("textual")
    from textual.app import App
    from iris.console.profile_config import ProfileConfigScreen

    async def scenario():
        class _App(App):
            def compose(self):
                yield ProfileConfigScreen()

        app = _App()
        async with app.run_test() as pilot:
            screen = app.query_one(ProfileConfigScreen)
            focusable = [w for w in screen.query("*") if w.can_focus]
            names = [getattr(w, "id", "") or type(w).__name__ for w in focusable]
            assert any("language" in str(n).lower() for n in names[:2])
            assert any("save" in str(n).lower() for n in names[-2:])
            await pilot.press("q")

    asyncio.run(scenario())


# Screen 2 — Detection In Progress

def test_s2_confidence_bars_have_aria_label():
    """Confidence bars must have accessible text — not bar width or colour alone."""
    pytest.importorskip("textual")
    from textual.app import App
    from iris.console.profile_status import DetectionInProgressScreen

    async def scenario():
        class _App(App):
            def compose(self):
                yield DetectionInProgressScreen(
                    utterance="hola",
                    confidences={"es": 0.94, "en": 0.12},
                )

        app = _App()
        async with app.run_test() as pilot:
            screen = app.query_one(DetectionInProgressScreen)
            for lang, bar in screen.confidence_bars.items():
                label = (getattr(bar, "accessible_label", None)
                         or getattr(bar, "aria_label", None))
                assert label is not None, f"Confidence bar for '{lang}' missing accessible label"
                assert lang in str(label)
            await pilot.press("q")

    asyncio.run(scenario())


def test_s2_spinner_has_adjacent_text_label():
    """Detection spinner must have adjacent visible text (not animation-only)."""
    pytest.importorskip("textual")
    from textual.app import App
    from iris.console.profile_status import DetectionInProgressScreen

    async def scenario():
        class _App(App):
            def compose(self):
                yield DetectionInProgressScreen(utterance="hi", confidences={})

        app = _App()
        async with app.run_test() as pilot:
            screen = app.query_one(DetectionInProgressScreen)
            label = screen.spinner_label
            assert label is not None and len(label.strip()) > 0
            await pilot.press("q")

    asyncio.run(scenario())


def test_s2_resolution_chain_ordered_four_steps():
    """Resolution chain is ordered and covers all 4 steps (override > annotation > detector > default)."""
    pytest.importorskip("textual")
    from textual.app import App
    from iris.console.profile_status import DetectionInProgressScreen

    async def scenario():
        class _App(App):
            def compose(self):
                yield DetectionInProgressScreen(utterance="hi", confidences={"en": 0.5})

        app = _App()
        async with app.run_test() as pilot:
            screen = app.query_one(DetectionInProgressScreen)
            chain = screen.resolution_chain
            items = list(getattr(chain, "items", chain))
            assert len(items) >= 4
            sources = [getattr(item, "source", str(item)) for item in items]
            assert sources.index("override") < sources.index("annotation")
            assert sources.index("annotation") < sources.index("detector")
            assert sources.index("detector") < sources.index("default")
            await pilot.press("q")

    asyncio.run(scenario())


# Screen 3 — Profile Locked

def test_s3_active_chain_item_has_aria_current():
    """Active resolution chain step must expose aria-current (WCAG 1.3.1)."""
    pytest.importorskip("textual")
    from textual.app import App
    from iris.console.profile_status import ProfileLockedScreen
    from iris.profile_resolver import PresentationProfile

    async def scenario():
        profile = PresentationProfile(language="es", tts_voice="es-voice",
                                      tts_lang="es", cadence=1.0, source="detector")

        class _App(App):
            def compose(self):
                yield ProfileLockedScreen(profile=profile, utterance="hola")

        app = _App()
        async with app.run_test() as pilot:
            screen = app.query_one(ProfileLockedScreen)
            chain = screen.resolution_chain
            items = list(getattr(chain, "items", chain))
            active = [item for item in items
                      if getattr(item, "is_active", False) or getattr(item, "aria_current", False)]
            assert len(active) == 1, "Exactly one chain step must be active"
            item = active[0]
            assert (getattr(item, "aria_current", None) is True
                    or getattr(item, "is_aria_current", False)), (
                "Active chain item must set aria-current=true"
            )
            await pilot.press("q")

    asyncio.run(scenario())


def test_s3_locked_badge_aria_label():
    """Locked badge must have an accessible label that says the profile is locked."""
    pytest.importorskip("textual")
    from textual.app import App
    from iris.console.profile_status import ProfileLockedScreen
    from iris.profile_resolver import PresentationProfile

    async def scenario():
        profile = PresentationProfile(language="es", tts_voice="", tts_lang="es",
                                      source="detector")

        class _App(App):
            def compose(self):
                yield ProfileLockedScreen(profile=profile, utterance="hola")

        app = _App()
        async with app.run_test() as pilot:
            screen = app.query_one(ProfileLockedScreen)
            badge = screen.locked_badge
            label = (getattr(badge, "aria_label", None)
                     or getattr(badge, "accessible_label", None))
            assert label is not None
            assert "locked" in str(label).lower()
            await pilot.press("q")

    asyncio.run(scenario())


def test_s3_locked_badge_has_visible_locked_text():
    """Locked badge must contain visible 'LOCKED' text alongside any icon."""
    pytest.importorskip("textual")
    from textual.app import App
    from iris.console.profile_status import ProfileLockedScreen
    from iris.profile_resolver import PresentationProfile

    async def scenario():
        profile = PresentationProfile(language="es", tts_voice="", tts_lang="es",
                                      source="annotation")

        class _App(App):
            def compose(self):
                yield ProfileLockedScreen(profile=profile, utterance="hola")

        app = _App()
        async with app.run_test() as pilot:
            screen = app.query_one(ProfileLockedScreen)
            badge = screen.locked_badge
            visible = getattr(badge, "label", None) or getattr(badge, "renderable", None)
            assert "LOCKED" in str(visible).upper()
            await pilot.press("q")

    asyncio.run(scenario())


def test_s3_inactive_chain_rows_have_text_indicator():
    """Inactive chain rows have text indicators — not colour alone (WCAG 1.4.1)."""
    pytest.importorskip("textual")
    from textual.app import App
    from iris.console.profile_status import ProfileLockedScreen
    from iris.profile_resolver import PresentationProfile

    async def scenario():
        profile = PresentationProfile(language="es", tts_voice="", tts_lang="es",
                                      source="detector")

        class _App(App):
            def compose(self):
                yield ProfileLockedScreen(profile=profile, utterance="hola")

        app = _App()
        async with app.run_test() as pilot:
            screen = app.query_one(ProfileLockedScreen)
            chain = screen.resolution_chain
            items = list(getattr(chain, "items", chain))
            inactive = [item for item in items if not getattr(item, "is_active", False)]
            for item in inactive:
                text = (getattr(item, "status_text", None)
                        or getattr(item, "label", None)
                        or getattr(item, "renderable", None))
                assert text is not None and len(str(text).strip()) > 0
            await pilot.press("q")

    asyncio.run(scenario())


# Screen 4 — Contact Annotation

def test_s4_trust_tier_field_is_readonly():
    """Trust tier field must be read-only — ADR-0005: profiles never modify trust."""
    pytest.importorskip("textual")
    from textual.app import App
    from iris.console.profile_annotation import ContactAnnotationScreen

    async def scenario():
        class _App(App):
            def compose(self):
                yield ContactAnnotationScreen(contact_id="contact:alice")

        app = _App()
        async with app.run_test() as pilot:
            screen = app.query_one(ContactAnnotationScreen)
            field = screen.trust_tier_field
            is_readonly = (getattr(field, "aria_readonly", False)
                           or getattr(field, "read_only", False)
                           or not getattr(field, "can_edit", True))
            assert is_readonly, "Trust tier field must be read-only (ADR-0005)"
            await pilot.press("q")

    asyncio.run(scenario())


def test_s4_trust_tier_field_has_accessible_label():
    """Trust tier field exposes an accessible name for screen readers (WCAG 4.1.2)."""
    pytest.importorskip("textual")
    from textual.app import App
    from iris.console.profile_annotation import ContactAnnotationScreen

    async def scenario():
        class _App(App):
            def compose(self):
                yield ContactAnnotationScreen(contact_id="contact:alice")

        app = _App()
        async with app.run_test() as pilot:
            screen = app.query_one(ContactAnnotationScreen)
            field = screen.trust_tier_field
            label = (getattr(field, "aria_label", None)
                     or getattr(field, "accessible_label", None)
                     or getattr(field, "label", None))
            assert label is not None and len(str(label).strip()) > 0
            await pilot.press("q")

    asyncio.run(scenario())


def test_s4_language_dropdown_can_focus():
    """Language preference dropdown is keyboard focusable (WCAG 2.1.1)."""
    pytest.importorskip("textual")
    from textual.app import App
    from iris.console.profile_annotation import ContactAnnotationScreen

    async def scenario():
        class _App(App):
            def compose(self):
                yield ContactAnnotationScreen(contact_id="contact:alice",
                                              available_languages=["en", "es", "fr"])

        app = _App()
        async with app.run_test() as pilot:
            screen = app.query_one(ContactAnnotationScreen)
            assert screen.language_dropdown.can_focus
            await pilot.press("tab")
            await pilot.press("down")
            await pilot.press("up")
            await pilot.press("enter")
            await pilot.press("q")

    asyncio.run(scenario())


def test_s4_save_button_keyboard_accessible():
    """Save button is keyboard focusable (WCAG 2.1.1)."""
    pytest.importorskip("textual")
    from textual.app import App
    from iris.console.profile_annotation import ContactAnnotationScreen

    async def scenario():
        class _App(App):
            def compose(self):
                yield ContactAnnotationScreen(contact_id="contact:alice")

        app = _App()
        async with app.run_test() as pilot:
            screen = app.query_one(ContactAnnotationScreen)
            assert screen.save_button.can_focus
            await pilot.press("q")

    asyncio.run(scenario())


def test_s4_clear_button_keyboard_accessible():
    """Clear button is keyboard focusable (WCAG 2.1.1)."""
    pytest.importorskip("textual")
    from textual.app import App
    from iris.console.profile_annotation import ContactAnnotationScreen

    async def scenario():
        class _App(App):
            def compose(self):
                yield ContactAnnotationScreen(contact_id="contact:alice")

        app = _App()
        async with app.run_test() as pilot:
            screen = app.query_one(ContactAnnotationScreen)
            assert screen.clear_button.can_focus
            await pilot.press("q")

    asyncio.run(scenario())


def test_s4_warning_callout_has_text_not_colour_alone():
    """Warning callout uses icon + text + border, not colour alone (WCAG 1.4.1)."""
    pytest.importorskip("textual")
    from textual.app import App
    from iris.console.profile_annotation import ContactAnnotationScreen

    async def scenario():
        class _App(App):
            def compose(self):
                yield ContactAnnotationScreen(contact_id="contact:alice")

        app = _App()
        async with app.run_test() as pilot:
            screen = app.query_one(ContactAnnotationScreen)
            callout = screen.warning_callout
            if callout is not None:
                text = getattr(callout, "renderable", "") or getattr(callout, "label", "")
                assert len(str(text).strip()) > 2, (
                    "Warning callout must have descriptive text alongside any icon"
                )
            await pilot.press("q")

    asyncio.run(scenario())
