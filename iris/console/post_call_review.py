"""Call Card AFTER — post-call review screen (Screens 1 & 2) — ti-qyo3p, ti-viv73.

Screen 1 (ti-qyo3p) is pushed when a call ends, to confirm/edit facts and
action items captured during the call and resolve any previously-open
commitments for the same contact. Triggered on "call_card_recap_ready"
(recap generated), with a "call_card_ended" + bounded-wait fallback for NFR2
(no API key configured, so no recap is ever generated). Reuses
CriticalFactCard/FactCard/ActionItemCard/PriorCommitmentCard unchanged --
their D/E/X/H/B keys and Message bubbling to IrisConsole's existing
on_fact_*/on_action_item_* handlers work identically whether mounted here or
on the live CallCardPanel.

Screen 2 (ti-viv73) is a phase transition on this SAME screen
(_ReviewPhase.REVIEWING -> SAVED), not a new Screen subclass, per ti-lvsnh's
design. [S] posts SaveRequested, which IrisConsole forwards to the daemon via
finalize_call_card (mirroring the disclosure_ack call-site); the screen only
swaps to the delta view once the daemon's call_card_written_back broadcast
actually arrives (IrisConsole calls on_saved()/on_save_failed() in response)
-- not immediately on keypress -- so there is a single source of truth for
"did it actually happen."
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Footer, Header, RichLog, Static

from iris.capture.after_store import AfterStore
from iris.capture.schemas import DURABLE_FACT_TYPES, FactType
from iris.roster import Contact

from .call_card import (
    ActionItemCard,
    CommitmentResolved,
    CriticalFactCard,
    FactCard,
    PriorCommitmentCard,
    _action_item_from_dict,
    _fact_from_dict,
)

_FACT_LABELS: dict[FactType, str] = {
    FactType.ACCOUNT_ID: "Account #",
    FactType.MEMBER_ID: "Member ID",
    FactType.POLICY_ID: "Policy #",
    FactType.ADDRESS: "Address",
    FactType.EMAIL: "Email",
}

# Bounded wait for call_card_written_back after a [S] press. Must exceed
# DaemonProxy.ACK_TIMEOUT_S (5.0s): action_save() starts this timer before
# the (blocking, main-thread) send() call, so a shorter timeout could fire
# while send() is still legitimately waiting on its own ack. The margin
# above 5.0s just covers the drain-loop tick once the ack (and, in the
# happy path, the already-queued event) arrive. See ti-viv73.
_SAVE_TIMEOUT_S = 7.0


def _format_short_date(ts: float | None) -> str:
    if not ts:
        return "—"
    dt = datetime.fromtimestamp(ts)
    return f"{dt.strftime('%b')} {dt.day}"


def _format_date_and_clock(ts: float | None) -> str:
    if not ts:
        return "—"
    dt = datetime.fromtimestamp(ts)
    return f"{dt.strftime('%b')} {dt.day} {dt.strftime('%H:%M')}"


def _format_clock(ts: float | None) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def _format_duration(started: float | None, ended: float | None) -> str:
    if not started or not ended:
        return "—"
    secs = max(0, int(ended - started))
    minutes, seconds = divmod(secs, 60)
    return f"{minutes}m{seconds:02d}s"


class _ReviewPhase(str, Enum):
    """PostCallReviewScreen's own phase — a state transition on one screen,
    not a new Screen subclass, per ti-lvsnh's design."""

    REVIEWING = "reviewing"
    SAVING = "saving"
    SAVED = "saved"


class SaveRequested(Message):
    """Operator pressed [S] -- ask the daemon to finalize this call's card."""

    def __init__(self, session_id: str) -> None:
        super().__init__()
        self.session_id = session_id


class DeltaRow(Static):
    """One promoted-item row in the Screen 2 delta view.

    Border/text color carries the provenance of the originating card type
    (amber=critical fact, teal=fact, indigo=commitment, muted-blue=call_log)
    through to the saved view.
    """

    DEFAULT_CSS = """
    DeltaRow {
        height: auto;
        padding: 1;
        margin-bottom: 1;
        background: #10151f;
    }
    DeltaRow.-critical-fact { border: solid #f59e0b; color: #fce8c8; }
    DeltaRow.-fact          { border: solid #14b8a6; color: #cdeee7; }
    DeltaRow.-commitment    { border: solid #818cf8; color: #e3e1fb; }
    DeltaRow.-call-log      { border: solid #3a5080; color: #9ab5e0; }
    """

    def __init__(self, text: str, kind: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._text = text
        self.add_class(f"-{kind}")

    def render(self) -> str:
        return self._text


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
    """Confirm/edit review (Screen 1) + save/delta view (Screen 2) -- ti-qyo3p, ti-viv73."""

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
    #recap-banner.-saved {
        background: #0f2e22;
        border: solid #16a34a;
    }
    #recap-banner:focus {
        border: heavy #4ade80;
    }
    #review-body {
        height: 1fr;
        padding: 1;
    }
    .review-section-title {
        height: auto;
        padding: 1 0 0 0;
    }
    .resolved-line {
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
        Binding("s", "save", "Save"),
    ]

    def __init__(
        self,
        contact: Contact,
        call_card: dict,
        commitments: list[dict],
        after_store: AfterStore,
        session_id: str,
        *,
        rep_name: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._contact = contact
        self._call_card = call_card
        self._commitments = commitments
        self._after_store = after_store
        self._session_id = session_id
        self._rep_name = rep_name
        self._phase = _ReviewPhase.REVIEWING
        self._save_failed = False
        self._unconfirmed_count = 0
        self._resolved_commitments: list[tuple[dict, str]] = []
        self._save_timeout_timer: Any = None
        contact_name = contact.display_name
        self.title = "📞 Iris — Post-Call Review"
        self.sub_title = f"{contact_name} ({rep_name})" if rep_name else contact_name

    @property
    def session_id(self) -> str:
        return self._session_id

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

    def check_action(self, action: str, parameters: tuple) -> bool:
        if action == "save":
            return self._phase is _ReviewPhase.REVIEWING
        return True

    # ── Rendering helpers (Screen 1) ───────────────────────────────────

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
        if self._phase is _ReviewPhase.SAVED:
            parts.append("\\[q] Close")
        elif self._phase is _ReviewPhase.SAVING:
            parts.append("[dim]saving…[/dim]")
        else:
            if self._save_failed:
                parts.append(
                    "[#f87171]did not save — still available next time[/#f87171]"
                )
            if self._commitments:
                parts.append("\\[H]/\\[B] resolve above")
            parts.append("\\[↑↓/tab] navigate")
            parts.append("\\[s] Save")
            parts.append("\\[q] Skip review (raw record already saved)")

        if self._unconfirmed_count:
            parts.append(
                f"{self._unconfirmed_count} item"
                f"{'s' if self._unconfirmed_count != 1 else ''} not reviewed "
                f"— still available next time"
            )
        if self._phase is _ReviewPhase.SAVED:
            broken_preview = self._broken_preview_text()
            if broken_preview:
                parts.append(broken_preview)
        self.query_one("#review-footer", Static).update("    ".join(parts))

    # ── Save (ti-viv73) ────────────────────────────────────────────────

    def action_save(self) -> None:
        if self._phase is not _ReviewPhase.REVIEWING:
            return
        self._unconfirmed_count = len(
            list(self.query(CriticalFactCard))
            + list(self.query(FactCard))
            + list(self.query(ActionItemCard))
        )
        self._phase = _ReviewPhase.SAVING
        self._save_failed = False
        self.refresh_bindings()
        self._render_footer()
        self._save_timeout_timer = self.set_timer(_SAVE_TIMEOUT_S, self._on_save_timeout)
        self.post_message(SaveRequested(self._session_id))

    def on_commitment_resolved(self, message: CommitmentResolved) -> None:
        for commitment in self._commitments:
            if commitment.get("id") == message.commitment_id:
                self._resolved_commitments.append((commitment, message.status))
                break

    def on_save_failed(self) -> None:
        """Called by IrisConsole when finalize_call_card couldn't complete --
        either immediately (proxy down / ack error) or after _SAVE_TIMEOUT_S
        with no call_card_written_back. Non-blocking per the AC: stays on
        Screen 1 so the operator can retry [S] or move on.
        """
        if self._phase is not _ReviewPhase.SAVING:
            return
        self._stop_save_timeout()
        self._phase = _ReviewPhase.REVIEWING
        self._save_failed = True
        self.refresh_bindings()
        self._render_footer()

    def on_saved(self, fresh_card: dict) -> None:
        """Called by IrisConsole once call_card_written_back arrives for this
        session_id. fresh_card is a re-fetch from the shared store, so it
        reflects confirm/dismiss/edit interactions made during review even
        though this screen's own self._call_card constructor-time snapshot
        is stale by now.
        """
        if self._phase is not _ReviewPhase.SAVING:
            return
        self._stop_save_timeout()
        self._phase = _ReviewPhase.SAVED
        self._call_card = fresh_card
        self.refresh_bindings()
        self._rebuild_saved_view()

    def _on_save_timeout(self) -> None:
        self._save_timeout_timer = None
        self.on_save_failed()

    def _stop_save_timeout(self) -> None:
        if self._save_timeout_timer is not None:
            self._save_timeout_timer.stop()
            self._save_timeout_timer = None

    # ── Screen 2: saved / delta view (ti-viv73) ─────────────────────────

    def _rebuild_saved_view(self) -> None:
        self.add_class("-saved")
        self.query_one("#recap-banner", Static).add_class("-saved")

        facts = [_fact_from_dict(d) for d in self._call_card.get("facts", [])]
        items = [
            _action_item_from_dict(d)
            for d in self._call_card.get("action_items", [])
        ]
        # Mirrors CallCardHost.finalize_writeback's own promotion filter
        # exactly: facts need confirmed AND a durable fact_type; action
        # items promote on confirmed alone. Critical-then-normal ordering
        # matches Screen 1's own grouping (stable sort keeps capture order
        # within each group).
        promoted_facts = sorted(
            (f for f in facts if f.confirmed and f.fact_type in DURABLE_FACT_TYPES),
            key=lambda f: not f.critical,
        )
        promoted_items = [i for i in items if i.confirmed]
        self._render_success_banner(len(promoted_facts), len(promoted_items))

        body = self.query_one("#review-body", VerticalScroll)
        body.remove_children()
        contact_name = escape(self._contact.display_name)
        rows: list[Static] = [
            Static(
                f"[#9ab5e0]FROM THIS CALL → {contact_name}'s record[/#9ab5e0]",
                classes="review-section-title",
            )
        ]
        for fact in promoted_facts:
            label = escape(_FACT_LABELS.get(fact.fact_type, fact.fact_type.value))
            kind = "critical-fact" if fact.critical else "fact"
            rows.append(
                DeltaRow(
                    f"◆ contact_fact   {label}   {escape(fact.normalized_value)}"
                    f"     ✓ verified",
                    kind,
                )
            )
        for item in promoted_items:
            direction = "they_promised" if item.owner == "far" else "i_promised"
            due = escape(item.due_date or "—")
            rows.append(
                DeltaRow(
                    f"→ commitment     {direction} · {escape(item.description)} · "
                    f"due {due}   ✓ verified",
                    "commitment",
                )
            )
        rows.append(DeltaRow(self._call_log_line(), "call-log"))
        for commitment, status in self._resolved_commitments:
            rows.append(self._render_resolved_line(commitment, status))
        body.mount(*rows)

        self._render_footer()
        self._focus_after_saved()

    def _call_log_line(self) -> str:
        duration = _format_duration(
            self._call_card.get("started_at"), self._call_card.get("ended_at")
        )
        started = _format_date_and_clock(self._call_card.get("started_at"))
        line = f"📞 call_log       {duration} · {started}"
        disclosed = _format_clock(self._call_card.get("disclosure_ack_ts"))
        if disclosed:
            line += f" · disclosed {disclosed}"
        line += "            ✓ logged"
        return line

    def _render_success_banner(self, facts_n: int, items_n: int) -> None:
        banner = self.query_one("#recap-banner", Static)
        banner.update(
            f"[bold #d1fae5]✓ Saved.[/bold #d1fae5] [#bbf7d0]"
            f"{facts_n} fact{'s' if facts_n != 1 else ''} · "
            f"{items_n} action item{'s' if items_n != 1 else ''} · "
            f"1 call logged.[/#bbf7d0]"
        )

    def _render_resolved_line(self, commitment: dict, status: str) -> Static:
        description = escape(commitment.get("description", ""))
        if status == "broken":
            text = (
                f"[#f87171]↩ Resolved: {description} → marked BROKEN "
                f"(opens as next-call leverage)[/#f87171]"
            )
        else:
            text = f"[#9ab5e0]↩ Resolved: {description} → marked HONORED[/#9ab5e0]"
        return Static(text, classes="resolved-line")

    def _broken_preview_text(self) -> str | None:
        for commitment, status in self._resolved_commitments:
            if status == "broken":
                contact_name = escape(self._contact.display_name)
                return (
                    f'Next call to {contact_name} opens with: '
                    f'"{self._seam_contract_text(commitment)}"'
                )
        return None

    def _seam_contract_text(self, commitment: dict) -> str:
        who = self._rep_name or "your rep"
        due = escape(commitment.get("due_date") or "—")
        date_str = _format_short_date(commitment.get("captured_at"))
        description = escape(commitment.get("description", ""))
        return f"On {date_str}, {who} promised {description} by {due} — it didn't happen."

    def _focus_after_saved(self) -> None:
        banner = self.query_one("#recap-banner", Static)
        banner.can_focus = True
        banner.focus()
