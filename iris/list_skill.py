"""ListSkill — brain-facing interface for live-call scratchpad lists.

Translates operator utterances into CRUD operations on CallListStore.
Six actions: start, add, remove, check, show, export.
v1 export: plain-text file (+ clipboard if available). SMS is not supported.

``parse_intent(phrase)`` maps free-form utterances to action names so the
dispatch layer can route without a dedicated grammar rule per phrase.
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path

from .list_store import CallList, CallListStore, ListItem
from .skills import SkillParam


class ListSkill:
    name = "list"
    description = (
        "Manage a shopping or task list during a call: "
        "start/add/remove/check/show/export."
    )
    params: list[SkillParam] = [
        SkillParam(
            name="action",
            type="string",
            description="One of: start, add, remove, check, show, export.",
            enum=["start", "add", "remove", "check", "show", "export"],
        ),
        SkillParam(
            name="session_id",
            type="string",
            description="Current call session identifier.",
        ),
        SkillParam(
            name="item",
            type="string",
            description="Item text for add/remove/check actions.",
            required=False,
            default="",
        ),
        SkillParam(
            name="title",
            type="string",
            description="Optional list title for start action.",
            required=False,
            default="Shopping list",
        ),
    ]

    def __init__(self, store: CallListStore) -> None:
        self._store = store

    # ------------------------------------------------------------------
    # Main dispatch

    def run(
        self,
        *,
        action: str,
        session_id: str = "",
        item: str = "",
        title: str = "Shopping list",
        confirm_replace: bool = False,
        lookup: bool = False,
        method: str = "file",
        export_dir: str = "",
        **_kwargs: object,
    ) -> str:
        if action == "start":
            return self._start(session_id, title, confirm_replace)
        if action == "add":
            return self._add(session_id, item, lookup)
        if action == "remove":
            return self._remove(session_id, item)
        if action == "check":
            return self._check(session_id, item)
        if action == "show":
            return self._show(session_id)
        if action == "export":
            return self._export(session_id, export_dir, method)
        return f"Unknown action: {action!r}."

    # ------------------------------------------------------------------
    # Intent routing

    _INTENT_PATTERNS: list[tuple[re.Pattern, str]] = [
        (re.compile(r"^(start|create)\s+a\b", re.I), "start"),
        (re.compile(r"^(add|put)\b", re.I), "add"),
        (re.compile(r"^show\b", re.I), "show"),
        (re.compile(r"^(remove|delete)\b", re.I), "remove"),
        (re.compile(r"^check\s+off\b", re.I), "check"),
        (re.compile(r"^look\s+up\b", re.I), "lookup"),
    ]

    def parse_intent(self, phrase: str) -> str:
        p = phrase.strip()
        for pattern, action in self._INTENT_PATTERNS:
            if pattern.match(p):
                return action
        return "unknown"

    # ------------------------------------------------------------------
    # Action implementations

    def _start(self, session_id: str, title: str, confirm_replace: bool) -> str:
        existing = self._store.active_list(session_id)
        if existing is not None and not confirm_replace:
            return (
                f"There's already an active list — '{existing.title}'. "
                "Say 'confirm replace' or 'start another list' to replace it."
            )
        if existing is not None and confirm_replace:
            self._store.complete_list(existing.id)
        self._store.create_list(session_id, title)
        return f"Started a new list — '{title}'. Say 'add X to the list' to begin."

    def _add(self, session_id: str, item: str, lookup: bool) -> str:
        lst = self._active_or_auto_start(session_id)
        status = "pending" if lookup else "none"
        self._store.add_item(lst.id, item, lookup_status=status)
        if lookup:
            return (
                f"Added '{item}' to the list and I'm looking up details now."
            )
        return f"Got it — '{item}' added to the list."

    def _remove(self, session_id: str, item: str) -> str:
        lst = self._active_or_none(session_id)
        if lst is None:
            return "No active list — nothing to remove from."
        found = self._find_item(self._store.get_items(lst.id), item)
        if found is None:
            return f"Couldn't find '{item}' on the list."
        self._store.remove_item(found.id)
        return f"Removed '{found.text}' from the list."

    def _check(self, session_id: str, item: str) -> str:
        lst = self._active_or_none(session_id)
        if lst is None:
            return "No active list."
        found = self._find_item(self._store.get_items(lst.id), item)
        if found is None:
            return f"Couldn't find '{item}' on the list."
        self._store.check_item(found.id)
        return f"Checked off '{found.text}'."

    def _show(self, session_id: str) -> str:
        lst = self._active_or_none(session_id)
        if lst is None:
            return "No active list."
        items = self._store.get_items(lst.id)
        if not items:
            return "The list is empty."
        lines = []
        for i, it in enumerate(items, 1):
            check = "✓" if it.checked else "○"
            lines.append(f"{i}. {check} {it.text}")
        return "\n".join(lines)

    def _export(self, session_id: str, export_dir: str, method: str) -> str:
        if method == "sms":
            raise NotImplementedError("SMS export is not supported in v1.")
        lst = self._active_or_none(session_id)
        items = self._store.get_items(lst.id) if lst else []
        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"iris-list-{timestamp}.txt"
        out_dir = Path(export_dir) if export_dir else Path.home() / "iris-exports"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / filename
        lines = [f"Iris list — {lst.title if lst else 'unknown'}", ""]
        for i, it in enumerate(items, 1):
            check = "[x]" if it.checked else "[ ]"
            lines.append(f"{i}. {check} {it.text}")
        out_path.write_text("\n".join(lines))
        return f"Saved list to file: {out_path.name}"

    # ------------------------------------------------------------------
    # Helpers

    def _active_or_none(self, session_id: str) -> CallList | None:
        return self._store.active_list(session_id)

    def _active_or_auto_start(self, session_id: str) -> CallList:
        lst = self._store.active_list(session_id)
        if lst is None:
            lst = self._store.create_list(session_id)
        return lst

    @staticmethod
    def _find_item(items: list[ListItem], query: str) -> ListItem | None:
        q = query.lower()
        for it in items:
            t = it.text.lower()
            if q in t or t in q:
                return it
        return None


def list_skills(store: CallListStore | None = None) -> list[ListSkill]:
    """Return a list of skills backed by ``store`` (or a default-path store)."""
    return [ListSkill(store or CallListStore())]
