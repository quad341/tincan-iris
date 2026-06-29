"""Contacts panel for the Iris operator console — ti-9szl / ti-wig8.

Full-screen contacts management: search, table, inline row editor with notes
textarea (600-char cap, 500-char warning) and handling-rule selector.

Open with [K] from the main console; [q] / Escape closes.

Badge palette (ADR-0006 enum names):
  ring_with_announcement → purple (ANNOUNCE)
  take_message           → blue   (MSG)
  screen                 → amber  (SCREEN)
  ignore                 → red    (IGNORE)
  ring_through           → grey   (no badge)
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Select, Static, TextArea

from ..roster import Contact, RosterProvider
from .contacts_logic import (
    _HANDLING_RULES,
    _NOTES_MAX,
    _NOTES_WARN,
    char_counter_text,
    rule_badge,
)

_UNKNOWN_ROW_KEY = "__unknown__"

# Visible labels for the Select widget (ADR-0006 enum names).
_RULE_LABELS: list[tuple[str, str]] = [
    ("Ring through",   "ring_through"),
    ("Announce caller","ring_with_announcement"),
    ("Screen call",    "screen"),
    ("Take message",   "take_message"),
    ("Ignore",         "ignore"),
]


# ---------------------------------------------------------------------------
# ContactEditor — inline editor shown when a row is selected
# ---------------------------------------------------------------------------

class ContactEditor(Vertical):
    """Inline editor for a single contact's handling rule and relationship notes.

    Hidden by default (``display: none``).  Call ``load_contact()`` then add
    the ``"visible"`` CSS class to show.
    """

    DEFAULT_CSS = """
    ContactEditor {
        display: none;
        height: auto;
        max-height: 18;
        border: round #4040aa;
        padding: 1 2;
        background: #12112a;
        margin: 0 0 1 0;
    }
    ContactEditor.visible {
        display: block;
    }
    ContactEditor #editor-name {
        color: #cce0ff;
        text-style: bold;
        margin-bottom: 1;
    }
    ContactEditor #rule-row {
        height: auto;
        margin-bottom: 1;
    }
    ContactEditor #rule-select {
        width: 24;
    }
    ContactEditor #ignore-warning {
        display: none;
        color: #c8a000;
        border: solid #c8a000;
        background: #3a2d00;
        padding: 0 2;
        margin-left: 1;
        height: 3;
        width: auto;
    }
    ContactEditor #ignore-warning.visible {
        display: block;
    }
    ContactEditor #notes-area {
        height: 5;
        border: solid #3a5080;
        margin-bottom: 0;
    }
    ContactEditor #char-counter {
        height: 1;
        color: #9ab5e0;
        margin-bottom: 1;
    }
    ContactEditor .editor-buttons {
        height: 3;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="contact-editor")
        self._contact_id: int | None = None

    def compose(self) -> ComposeResult:
        yield Static("", id="editor-name")
        with Horizontal(id="rule-row"):
            yield Select(
                options=_RULE_LABELS,
                value="ring_through",
                id="rule-select",
                allow_blank=False,
            )
            yield Static(
                "⚠  Caller goes to carrier voicemail directly.",
                id="ignore-warning",
            )
        yield TextArea("", id="notes-area")
        yield Static("0/600", id="char-counter")
        with Horizontal(classes="editor-buttons"):
            yield Button("Save", id="save-btn", variant="success")
            yield Button("Cancel", id="cancel-btn")

    def load_contact(self, contact: Contact) -> None:
        """Populate the editor with an existing contact's data."""
        self._contact_id = contact.id
        self.query_one("#editor-name", Static).update(
            f"[b]Editing:[/] {contact.display_name}  [dim]{contact.phone_e164}[/]"
        )
        select = self.query_one("#rule-select", Select)
        rule = contact.handling_rule if contact.handling_rule in _HANDLING_RULES else "ring_through"
        select.value = rule
        self._update_ignore_warning(rule)
        ta = self.query_one("#notes-area", TextArea)
        ta.load_text(contact.relationship_notes or "")
        self._update_counter(len(contact.relationship_notes or ""))

    def load_new(self) -> None:
        """Prepare editor for a new contact (blank fields)."""
        self._contact_id = None
        self.query_one("#editor-name", Static).update("[b]New contact[/]")
        self.query_one("#rule-select", Select).value = "ring_through"
        self._update_ignore_warning("ring_through")
        ta = self.query_one("#notes-area", TextArea)
        ta.load_text("")
        self._update_counter(0)

    def current_rule(self) -> str:
        sel = self.query_one("#rule-select", Select)
        return str(sel.value) if sel.value else "ring_through"

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "rule-select":
            self._update_ignore_warning(str(event.value))

    def _update_ignore_warning(self, rule: str) -> None:
        warning = self.query_one("#ignore-warning", Static)
        if rule == "ignore":
            warning.add_class("visible")
        else:
            warning.remove_class("visible")

    def current_notes(self) -> str:
        return self.query_one("#notes-area", TextArea).text

    def _update_counter(self, n: int) -> None:
        self.query_one("#char-counter", Static).update(char_counter_text(n))

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        n = len(event.text_area.text)
        self._update_counter(n)


# ---------------------------------------------------------------------------
# ContactsScreen — full-width contacts management screen
# ---------------------------------------------------------------------------

class ContactsScreen(Screen):
    """Full-width Contacts panel — push as a Screen from the main console.

    Parameters
    ----------
    roster:
        A ``RosterProvider`` instance (typically ``RosterStore``).
    """

    TITLE = "Iris — Contacts"

    CSS = """
    ContactsScreen {
        background: #0f1624;
        color: #cce0ff;
    }
    #contacts-toolbar {
        height: 3;
        align: left middle;
        padding: 0 1;
        background: #1c2333;
        border-bottom: solid #2a3a5e;
    }
    #contacts-search {
        width: 30;
        margin-right: 2;
    }
    #add-btn { margin-right: 1; }
    #contacts-table {
        height: 1fr;
        background: #1c2333;
        color: #cce0ff;
    }
    DataTable > .datatable--header { background: #2a3a5e; color: #ffffff; }
    DataTable > .datatable--cursor { background: #3a5080; }
    DataTable > .datatable--highlight { background: #263348; }
    #contacts-wrap { height: 1fr; }
    """

    BINDINGS = [
        Binding("q", "app.pop_screen", "close", priority=True),
        Binding("escape", "cancel_edit", "cancel / close", priority=True),
        Binding("n", "add_contact", "new contact"),
        Binding("delete", "delete_contact", "delete"),
    ]

    def __init__(self, roster: RosterProvider) -> None:
        super().__init__()
        self._roster = roster
        self._filter: str = ""
        self._editing_new: bool = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="contacts-toolbar"):
            yield Input(placeholder="Search name or phone…", id="contacts-search")
            yield Button("Add Contact", id="add-btn", variant="primary")
            yield Button("Import…", id="import-btn")
        with Vertical(id="contacts-wrap"):
            yield ContactEditor()
            yield DataTable(id="contacts-table")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#contacts-table", DataTable)
        table.add_columns("NAME", "PHONE", "RULE", "NOTES", "TRUST")
        table.cursor_type = "row"
        self._reload()

    # ------------------------------------------------------------------
    # Data

    def _reload(self) -> None:
        table = self.query_one("#contacts-table", DataTable)
        table.clear()

        contacts = self._filtered_contacts()
        for c in contacts:
            notes_preview = (c.relationship_notes or "—")[:40]
            if len(c.relationship_notes or "") > 40:
                notes_preview += "…"
            table.add_row(
                c.display_name,
                c.phone_e164,
                rule_badge(c.handling_rule),
                notes_preview,
                c.trust_tier,
                key=str(c.id),
            )

        # Static unknown-caller row — always at the bottom, not editable.
        table.add_row(
            "[dim](unknown callers)[/]",
            "[dim]*[/]",
            rule_badge("ring_through"),
            "[dim]—[/]",
            "[dim]demo[/]",
            key=_UNKNOWN_ROW_KEY,
        )

    def _filtered_contacts(self) -> list[Contact]:
        all_contacts = self._roster.all()
        if not self._filter:
            return all_contacts
        needle = self._filter.lower()
        return [
            c for c in all_contacts
            if needle in c.display_name.lower() or needle in c.phone_e164.lower()
        ]

    # ------------------------------------------------------------------
    # Search

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "contacts-search":
            self._filter = event.value
            self._reload()

    # ------------------------------------------------------------------
    # Row selection → open editor

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row_key = str(event.row_key.value) if event.row_key.value else ""
        if row_key == _UNKNOWN_ROW_KEY:
            return  # unknown-caller row is not editable

        editor = self.query_one(ContactEditor)
        try:
            contact_id = int(row_key)
        except (ValueError, TypeError):
            return
        contact = self._roster.get(contact_id)
        if contact is None:
            return
        self._editing_new = False
        editor.load_contact(contact)
        editor.add_class("visible")

    # ------------------------------------------------------------------
    # Buttons

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "add-btn":
            self.action_add_contact()
        elif event.button.id == "import-btn":
            self.notify(
                "Import: paste contacts as JSON in the console (roster.import_contacts).",
                severity="information",
            )
        elif event.button.id == "save-btn":
            self._save_editor()
        elif event.button.id == "cancel-btn":
            self.action_cancel_edit()

    def action_add_contact(self) -> None:
        self._editing_new = True
        editor = self.query_one(ContactEditor)
        editor.load_new()
        editor.add_class("visible")
        editor.query_one("#notes-area", TextArea).focus()

    def _save_editor(self) -> None:
        editor = self.query_one(ContactEditor)
        rule = editor.current_rule()
        notes = editor.current_notes()[:_NOTES_MAX]

        if self._editing_new:
            # Saving a new contact requires name + phone — show a prompt for now.
            # The inline editor for new contacts is a future UX iteration (v2).
            self.notify(
                "To add a contact, say: 'Hey Iris, add a contact — [name], [phone]'",
                severity="information",
                timeout=6,
            )
            editor.remove_class("visible")
            self._editing_new = False
            return

        contact_id = editor._contact_id
        if contact_id is None:
            return

        if len(notes) >= _NOTES_WARN:
            self.notify(
                f"Notes are {len(notes)} chars — approaching the 600-char limit.",
                severity="warning",
            )

        self._roster.update(contact_id, handling_rule=rule, relationship_notes=notes)
        editor.remove_class("visible")
        self._reload()
        self.notify("Contact updated.", severity="information")

    def action_cancel_edit(self) -> None:
        editor = self.query_one(ContactEditor)
        if "visible" in editor.classes:
            editor.remove_class("visible")
            self._editing_new = False
        else:
            self.app.pop_screen()

    def action_delete_contact(self) -> None:
        table = self.query_one("#contacts-table", DataTable)
        row_key = None
        try:
            # DataTable cursor_row gives the *index*, not the row key.
            if table.cursor_row is not None:
                keys = list(table._data.keys())  # type: ignore[attr-defined]
                if 0 <= table.cursor_row < len(keys):
                    row_key = str(keys[table.cursor_row].value)
        except Exception:
            return
        if not row_key or row_key == _UNKNOWN_ROW_KEY:
            return
        try:
            contact_id = int(row_key)
        except (ValueError, TypeError):
            return
        contact = self._roster.get(contact_id)
        if contact is None:
            return
        self._roster.delete(contact_id)
        self.query_one(ContactEditor).remove_class("visible")
        self._reload()
        self.notify(f"Removed {contact.display_name}.", severity="information")
