"""Post-call list review screen — Screen 2 of the Iris console.

Auto-displays when a call with an active list ends.  Accessible via [v] in the
live list panel or ``iris list <call-id>`` CLI.

Keybindings:
  [enter]  toggle check on focused item
  [e]      edit item text (inline)
  [d]      delete item
  [L]      trigger lookup now (queues web search)
  [s]      save item as a note (to NotesStore)
  [S]      send item to Iris memory (bd remember)
  [export] copy to clipboard
  [copy]   write plain-text file to ~/iris-exports/
  [q]      close and return to console

Footer shows: "<N> items · <M> looked up · [q] close"
"""
from __future__ import annotations

import datetime
import subprocess
from pathlib import Path
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from ..list_store import CallList, CallListStore, ListItem

_EXPORT_DIR = Path.home() / "iris-exports"


class PostCallListView(Screen):
    """Full-screen review of a completed or active call list.

    Parameters
    ----------
    store:
        ``CallListStore`` instance to read and mutate items.
    call_list:
        The ``CallList`` being reviewed.
    web_skill:
        Optional ``WebSearchSkill``; if provided [L] fires live lookups.
    """

    TITLE = "Iris — Call List Review"

    CSS = """
    PostCallListView {
        background: #0f1624;
        color: #cce0ff;
    }
    DataTable {
        height: 1fr;
        background: #1c2333;
        color: #cce0ff;
    }
    DataTable > .datatable--header { background: #2a3a5e; color: #ffffff; }
    DataTable > .datatable--cursor { background: #3a5080; }
    #list-footer { height: 1; background: #2a3a5e; color: #9ab5e0; padding: 0 1; }
    """

    BINDINGS: ClassVar = [
        Binding("enter", "toggle_check", "check/uncheck"),
        Binding("d", "delete_item", "delete"),
        Binding("L", "lookup_now", "lookup"),
        Binding("s", "save_note", "save note"),
        Binding("export", "export_clipboard", "clipboard"),
        Binding("S", "copy_file", "copy file"),
        Binding("q", "app.pop_screen", "close", priority=True),
    ]

    def __init__(
        self,
        store: CallListStore,
        call_list: CallList,
        *,
        web_skill: object | None = None,
    ) -> None:
        super().__init__()
        self._store = store
        self._list = call_list
        self._web_skill = web_skill

    # ------------------------------------------------------------------
    # Compose

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield DataTable(id="items-table")
        yield Static(id="list-footer")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("#", "State", "Item", "Lookup result", "Added")
        table.cursor_type = "row"
        self._reload()

    # ------------------------------------------------------------------
    # Data helpers

    def _reload(self) -> None:
        table = self.query_one(DataTable)
        table.clear()
        items = self._store.get_items(self._list.id)
        for it in items:
            icon = self._state_icon(it)
            lookups = self._store.get_lookups(it.id)
            lookup_text = lookups[-1].text[:50] if lookups else "—"
            added = datetime.datetime.fromtimestamp(it.created_at).strftime("%H:%M")
            table.add_row(str(it.position), icon, it.text, lookup_text, added,
                          key=str(it.id))
        self._update_footer(items)

    def _update_footer(self, items: list[ListItem]) -> None:
        total = len(items)
        looked_up = sum(1 for it in items if it.lookup_status == "done")
        self.query_one("#list-footer", Static).update(
            f" {total} items · {looked_up} looked up  ·  [q] close"
        )

    @staticmethod
    def _state_icon(it: ListItem) -> str:
        if it.checked:
            return "☑"
        return {"none": "○", "pending": "⏳", "done": "✓", "failed": "⚠"}.get(
            it.lookup_status, "○"
        )

    def _focused_item_id(self) -> int | None:
        table = self.query_one(DataTable)
        row_key = table.cursor_row
        if row_key is None:
            return None
        try:
            table.get_row_at(row_key)
            return int(table.coordinate_to_cell_key(
                (row_key, 0)
            ).row_key.value)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Actions

    def action_toggle_check(self) -> None:
        item_id = self._focused_item_id()
        if item_id is None:
            return
        items = self._store.get_items(self._list.id)
        for it in items:
            if it.id == item_id:
                self._store.check_item(item_id, checked=not it.checked)
                break
        self._reload()

    def action_delete_item(self) -> None:
        item_id = self._focused_item_id()
        if item_id is not None:
            self._store.remove_item(item_id)
            self._reload()

    def action_lookup_now(self) -> None:
        """Trigger a web lookup for the focused item (requires web_skill)."""
        if self._web_skill is None:
            self.notify("No web skill configured — cannot look up.", severity="warning")
            return
        item_id = self._focused_item_id()
        if item_id is None:
            return
        items = self._store.get_items(self._list.id)
        item = next((it for it in items if it.id == item_id), None)
        if item is None:
            return
        self._store.set_lookup_status(item_id, "pending")
        self.notify(f"Looking up '{item.text}'…", severity="information")
        import threading
        threading.Thread(
            target=self._do_lookup, args=(item_id, item.text), daemon=True
        ).start()

    def _do_lookup(self, item_id: int, text: str) -> None:
        try:
            reply = self._web_skill.run(url="", question=f"price of {text}", speaker="operator")
            if "couldn't" not in reply and "What URL" not in reply:
                self._store.set_lookup_status(item_id, "done")
                self._store.add_lookup(item_id, "web", reply)
            else:
                self._store.set_lookup_status(item_id, "failed")
        except Exception:
            self._store.set_lookup_status(item_id, "failed")
        self.call_from_thread(self._reload)

    def action_save_note(self) -> None:
        """Save focused item text to NotesStore (iris notes)."""
        item_id = self._focused_item_id()
        if item_id is None:
            return
        items = self._store.get_items(self._list.id)
        item = next((it for it in items if it.id == item_id), None)
        if item is None:
            return
        try:
            from ..notes import NotesStore
            NotesStore().capture(item.text)
            self.notify(f"Saved to notes: {item.text[:40]}", severity="information")
        except Exception as e:
            self.notify(f"Note save failed: {e}", severity="error")

    def action_copy_file(self) -> None:
        """Write the list to a plain-text file in ~/iris-exports/."""
        items = self._store.get_items(self._list.id)
        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        _EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        out = _EXPORT_DIR / f"iris-list-{timestamp}.txt"
        lines = [f"Iris list — {self._list.title}", ""]
        for i, it in enumerate(items, 1):
            check = "[x]" if it.checked else "[ ]"
            lookups = self._store.get_lookups(it.id)
            lookup_str = f"  → {lookups[-1].text[:60]}" if lookups else ""
            lines.append(f"{i}. {check} {it.text}{lookup_str}")
        out.write_text("\n".join(lines))
        self.notify(f"Saved: {out.name}", severity="information")

    def action_export_clipboard(self) -> None:
        """Copy list as plain text to system clipboard."""
        items = self._store.get_items(self._list.id)
        lines = []
        for i, it in enumerate(items, 1):
            check = "✓" if it.checked else "○"
            lines.append(f"{i}. {check} {it.text}")
        text = "\n".join(lines)
        try:
            # xclip / xsel / wl-copy
            for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--input", "--clipboard"]):
                if subprocess.run(["which", cmd[0]], capture_output=True, check=False).returncode == 0:
                    subprocess.run(cmd, input=text.encode(), check=True)
                    self.notify("Copied to clipboard.", severity="information")
                    return
            self.notify("No clipboard tool found (install wl-copy or xclip).", severity="warning")
        except Exception as e:
            self.notify(f"Clipboard error: {e}", severity="error")
