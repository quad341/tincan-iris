"""Notes & follow-ups — local persistent store + three dispatcher-callable skills.

Notes are stored as a JSON array in ``~/.local/share/iris/notes.json`` (or any
path you hand to ``NotesStore``). The three skills implement the full lifecycle:
capture → list → mark-done.

Each note:
    {"id": int, "text": str, "done": bool, "created_at": float, "done_at": float|null}

IDs are 1-based (matching the spoken list ordinals).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .skills import Skill, SkillParam

_DEFAULT_PATH = Path.home() / ".local" / "share" / "iris" / "notes.json"


class NotesStore:
    """Read/write the notes list from a JSON file. Thread-safe via re-read/re-write."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else _DEFAULT_PATH

    def _load(self) -> list[dict]:
        try:
            return json.loads(self.path.read_text())
        except (FileNotFoundError, ValueError):
            return []

    def _save(self, notes: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(notes, indent=2))

    def capture(self, text: str) -> dict:
        notes = self._load()
        next_id = max((n["id"] for n in notes), default=0) + 1
        note = {"id": next_id, "text": text.strip(), "done": False,
                "created_at": time.time(), "done_at": None}
        notes.append(note)
        self._save(notes)
        return note

    def list_open(self) -> list[dict]:
        return [n for n in self._load() if not n["done"]]

    def mark_done(self, note_id: int) -> dict | None:
        notes = self._load()
        for n in notes:
            if n["id"] == note_id:
                n["done"] = True
                n["done_at"] = time.time()
                self._save(notes)
                return n
        return None

    def all_notes(self) -> list[dict]:
        return self._load()


class CaptureNoteSkill:
    """Capture a note or follow-up item for this call."""

    name = "capture_note"
    description = "Save a note or follow-up item. Use when the user says 'note that', 'follow up on', or 'remind me to'."
    params: list[SkillParam] = [
        SkillParam(name="text", type="string", description="The note content to save."),
    ]

    def __init__(self, store: NotesStore) -> None:
        self._store = store

    def run(self, text: str = "", **kwargs: object) -> str:
        if not text.strip():
            return "What would you like me to note down?"
        self._store.capture(text)
        return f"Got it — noted: {text.strip()}"


class ListNotesSkill:
    """List open follow-ups and notes from this session."""

    name = "list_notes"
    description = "List open notes and follow-up items. Use when the user asks 'what are my notes' or 'list follow-ups'."
    params: list[SkillParam] = []

    def __init__(self, store: NotesStore) -> None:
        self._store = store

    def run(self, **kwargs: object) -> str:
        open_notes = self._store.list_open()
        if not open_notes:
            return "No open notes."
        items = "; ".join(f"{n['id']}. {n['text']}" for n in open_notes)
        count = len(open_notes)
        noun = "note" if count == 1 else "notes"
        return f"You have {count} open {noun}: {items}."


class MarkDoneSkill:
    """Mark a note as done by its list number."""

    name = "mark_done"
    description = "Mark an open note as done. Use when the user says 'done with note 2' or 'mark 3 done'."
    params: list[SkillParam] = [
        SkillParam(name="index", type="string",
                   description="The note ID (number from the list) to mark done."),
    ]

    def __init__(self, store: NotesStore) -> None:
        self._store = store

    def run(self, index: str = "", **kwargs: object) -> str:
        try:
            note_id = int(index)
        except (ValueError, TypeError):
            return "Which note number should I mark done?"
        note = self._store.mark_done(note_id)
        if note is None:
            return f"I don't have a note {note_id}."
        return f"Done — marked note {note_id} complete."


def notes_skills(store: NotesStore | None = None) -> list[Skill]:
    """Return the three notes skills sharing a store instance."""
    s = store or NotesStore()
    return [CaptureNoteSkill(s), ListNotesSkill(s), MarkDoneSkill(s)]
