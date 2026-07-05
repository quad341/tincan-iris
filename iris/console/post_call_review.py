"""Call Card AFTER — post-call review screen (Screen 1) — ti-qyo3p.

Pushed when a call ends, to confirm/edit facts and action items captured
during the call and resolve any previously-open commitments for the same
contact. Triggered on "call_card_recap_ready" (recap generated), with a
"call_card_ended" + bounded-wait fallback for NFR2 (no API key configured,
so no recap is ever generated). Reuses CriticalFactCard/FactCard/
ActionItemCard/PriorCommitmentCard unchanged -- their D/E/X/H/B keys and
Message bubbling to IrisConsole's existing on_fact_*/on_action_item_*
handlers work identically whether mounted here or on the live CallCardPanel.

Saving ([S]) and the resulting Screen 2 saved/delta view are ti-viv73's
scope, not this bead's -- deliberately absent here.
"""
from __future__ import annotations

from typing import Any

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, RichLog, Static

from iris.capture.after_store import AfterStore
from iris.roster import Contact

from .call_card import (
    ActionItemCard,
    CriticalFactCard,
    FactCard,
    PriorCommitmentCard,
    _action_item_from_dict,
    _fact_from_dict,
)


class SettledRow(Static):
    """Quiet, non-interactive row for a fact/action item already confirmed
    live (via [D]) during the call -- avoids re-prompting for something the
    rep already handled.
    """

    aria_role = "status"

    DEFAULT_CSS = """
    SettledRow {
        height: auto;
        padding: 0 1;
        color: #7c8aa8;
    }
    """

    def __init__(self, text: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._text = text

    def render(self) -> str:
        return f"✓ {escape(self._text)}  [dim]already confirmed[/dim]"


class PostCallReviewScreen(Screen):
    """Confirm/edit review pushed after a call ends -- ti-qyo3p."""

    CSS = """
    PostCallReviewScreen {
        background: #0f1624;
        color: #cce0ff;
    }
    #recap-banner {
        height: auto;
        background: #152238;
        border: solid #3a5080;
        padding: 1;
        margin: 1 1 0 1;
    }
    #review-body {
        height: 1fr;
        padding: 1;
    }
    .review-section-title {
        height: auto;
        padding: 1 0 0 0;
    }
    #review-footer {
        height: 1;
        background: #2a3a5e;
        color: #9ab5e0;
        padding: 0 1;
    }
    """

    # priority=True (matches HelpScreen/PostCallListView): IrisConsole's own
    # "q" is ALSO priority=True (bound to "quit"), and Textual checks
    # priority bindings App-first -- without adding this screen to
    # IrisConsole.check_action's "quit" gate, pressing "q" here would quit
    # the whole app instead of closing this screen. See app.py.
    BINDINGS = [
        Binding("q", "app.pop_screen", "skip review", priority=True),
        Binding("escape", "app.pop_screen", "skip review", priority=True),
        Binding("down", "app.focus_next", "navigate", show=False),
        Binding("up", "app.focus_previous", "navigate", show=False),
    ]

    def __init__(
        self,
        contact: Contact,
        call_card: dict,
        commitments: list[dict],
        after_store: AfterStore,
        *,
        rep_name: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._contact = contact
        self._call_card = call_card
        self._commitments = commitments
        self._after_store = after_store
        self._rep_name = rep_name
        contact_name = contact.display_name
        self.title = "📞 Iris — Post-Call Review"
        self.sub_title = f"{contact_name} ({rep_name})" if rep_name else contact_name

    # ── Compose ──────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(id="recap-banner")
        with VerticalScroll(id="review-body"):
            if self._commitments:
                yield Static(
                    f"[#818cf8]SINCE LAST TIME — resolve open commitments "
                    f"({len(self._commitments)})[/#818cf8]",
                    classes="review-section-title",
                )
                for commitment in self._commitments:
                    yield PriorCommitmentCard(
                        commitment, self._after_store, rep_name=self._rep_name
                    )

            facts = [_fact_from_dict(d) for d in self._call_card.get("facts", [])]
            items = [
                _action_item_from_dict(d)
                for d in self._call_card.get("action_items", [])
            ]
            critical_facts = [
                f for f in facts if f.critical and f.confirmed is not False
            ]
            normal_facts = [
                f for f in facts if not f.critical and f.confirmed is not False
            ]
            visible_items = [i for i in items if i.confirmed is not False]
            total = len(critical_facts) + len(normal_facts) + len(visible_items)

            yield Static(
                f"[#9ab5e0]CAPTURED THIS CALL — confirm or edit before saving "
                f"({total})[/#9ab5e0]",
                classes="review-section-title",
            )
            for fact in critical_facts:
                yield (
                    SettledRow(fact.normalized_value)
                    if fact.confirmed
                    else CriticalFactCard(fact)
                )
            for fact in normal_facts:
                yield (
                    SettledRow(fact.normalized_value)
                    if fact.confirmed
                    else FactCard(fact)
                )
            for item in visible_items:
                yield (
                    SettledRow(item.description)
                    if item.confirmed
                    else ActionItemCard(item)
                )
        yield Static(id="review-footer")
        yield Footer()

    # ── Lifecycle ────────────────────────────────────────────────────

    def on_mount(self) -> None:
        self._render_recap_banner()
        self._render_footer()

        # Focus order: prior commitments first (if the section is present),
        # then captured-this-call cards grouped critical/fact/action-item --
        # matches DOM order, so concatenating per-type queries in this
        # priority order and taking the first hit gives the right target
        # without guessing at comma-selector evaluation order.
        candidates = (
            list(self.query(PriorCommitmentCard))
            + list(self.query(CriticalFactCard))
            + list(self.query(FactCard))
            + list(self.query(ActionItemCard))
        )
        if candidates:
            candidates[0].focus()

    def on_unmount(self) -> None:
        self.app.query_one("#log", RichLog).focus()

    # ── Rendering helpers ────────────────────────────────────────────

    def _render_recap_banner(self) -> None:
        banner = self.query_one("#recap-banner", Static)
        summary = (self._call_card.get("outcome_summary") or "").strip()
        label = (
            "[bold #f59e0b]RECAP[/bold #f59e0b]  "
            "[dim](generated · grounded in captured facts only)[/dim]"
        )
        if summary:
            banner.update(f"{label}\n{escape(summary)}")
        else:
            banner.update(f"{label}\n[dim](no recap — no API key configured)[/dim]")

    def _render_footer(self) -> None:
        parts = []
        if self._commitments:
            parts.append("\\[H]/\\[B] resolve above")
        parts.append("\\[↑↓/tab] navigate")
        parts.append("\\[q] Skip review (raw record already saved)")
        self.query_one("#review-footer", Static).update("    ".join(parts))
