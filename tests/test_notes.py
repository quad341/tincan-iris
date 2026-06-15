"""Tests for NotesStore and the three notes skills.

All I/O is redirected to a tmp_path — no home-dir writes."""
from __future__ import annotations

import pytest

from iris.notes import (
    CaptureNoteSkill,
    ListNotesSkill,
    MarkDoneSkill,
    NotesStore,
    notes_skills,
)


@pytest.fixture
def store(tmp_path):
    return NotesStore(tmp_path / "notes.json")


# --- NotesStore ---

def test_capture_creates_note(store):
    note = store.capture("follow up with Alice")
    assert note["id"] == 1
    assert note["text"] == "follow up with Alice"
    assert note["done"] is False
    assert note["done_at"] is None


def test_capture_increments_id(store):
    store.capture("first")
    n2 = store.capture("second")
    assert n2["id"] == 2


def test_list_open_excludes_done(store):
    store.capture("open note")
    n2 = store.capture("done note")
    store.mark_done(n2["id"])
    assert len(store.list_open()) == 1
    assert store.list_open()[0]["text"] == "open note"


def test_mark_done_returns_note(store):
    note = store.capture("test")
    result = store.mark_done(note["id"])
    assert result["done"] is True
    assert result["done_at"] is not None


def test_mark_done_unknown_id_returns_none(store):
    assert store.mark_done(99) is None


def test_persists_across_store_instances(tmp_path):
    path = tmp_path / "notes.json"
    s1 = NotesStore(path)
    s1.capture("persisted note")
    s2 = NotesStore(path)
    assert len(s2.all_notes()) == 1
    assert s2.all_notes()[0]["text"] == "persisted note"


# --- CaptureNoteSkill ---

def test_capture_skill_returns_confirmation(store):
    skill = CaptureNoteSkill(store)
    reply = skill.run(text="review the contract")
    assert "review the contract" in reply
    assert len(store.all_notes()) == 1


def test_capture_skill_empty_text_prompts(store):
    skill = CaptureNoteSkill(store)
    reply = skill.run(text="")
    assert "note down" in reply.lower() or "what" in reply.lower()
    assert store.all_notes() == []


# --- ListNotesSkill ---

def test_list_skill_no_notes(store):
    skill = ListNotesSkill(store)
    assert "no open" in skill.run().lower()


def test_list_skill_shows_count_and_items(store):
    store.capture("first task")
    store.capture("second task")
    skill = ListNotesSkill(store)
    reply = skill.run()
    assert "2" in reply
    assert "first task" in reply
    assert "second task" in reply


def test_list_skill_excludes_done(store):
    store.capture("done already")
    n = store.capture("still open")
    store.mark_done(1)
    skill = ListNotesSkill(store)
    reply = skill.run()
    assert "still open" in reply
    assert "done already" not in reply


# --- MarkDoneSkill ---

def test_mark_done_skill_success(store):
    store.capture("finish report")
    skill = MarkDoneSkill(store)
    reply = skill.run(index="1")
    assert "done" in reply.lower() or "marked" in reply.lower()
    assert store.list_open() == []


def test_mark_done_skill_invalid_index(store):
    skill = MarkDoneSkill(store)
    reply = skill.run(index="42")
    assert "42" in reply


def test_mark_done_skill_non_numeric(store):
    skill = MarkDoneSkill(store)
    reply = skill.run(index="abc")
    assert "number" in reply.lower() or "which" in reply.lower()


# --- notes_skills factory ---

def test_notes_skills_returns_three_skills(tmp_path):
    store = NotesStore(tmp_path / "n.json")
    skills = notes_skills(store)
    names = {s.name for s in skills}
    assert names == {"capture_note", "list_notes", "mark_done"}


def test_notes_skills_share_store(tmp_path):
    store = NotesStore(tmp_path / "n.json")
    capture, list_, done = notes_skills(store)
    capture.run(text="shared note")
    assert "shared note" in list_.run()
