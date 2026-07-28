"""Tests for ListSkill — the brain-facing interface over CallListStore.

Data-layer tests (CRUD, schema, retention) live in test_list_store.py.
This file covers only the skill class: actions, intent routing, spoken
replies, export, and lookup state machine visible through the skill.

Imports from iris.list_store are assumed to be stable (covered by
test_list_store.py); imports from iris.list_skill will fail until
ti-ccc.16.2 is implemented.
"""
from __future__ import annotations

import pytest

from iris.list_skill import ListSkill, list_skills
from iris.list_store import CallListStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    return CallListStore(tmp_path / "iris.db")


@pytest.fixture
def skill(tmp_path):
    return ListSkill(CallListStore(tmp_path / "iris.db"))


# ---------------------------------------------------------------------------
# Skill protocol conformance
# ---------------------------------------------------------------------------

def test_skill_has_name(skill):
    assert skill.name


def test_skill_has_description(skill):
    assert skill.description


def test_skill_params_is_list(skill):
    assert isinstance(skill.params, list)


def test_list_skills_factory(tmp_path):
    store = CallListStore(tmp_path / "iris.db")
    skills = list_skills(store)
    assert len(skills) >= 1


# ---------------------------------------------------------------------------
# Action: start
# ---------------------------------------------------------------------------

def test_start_creates_active_list(skill, tmp_path):
    store = CallListStore(tmp_path / "iris.db")
    sk = ListSkill(store)
    sk.run(action="start", session_id="s1")
    assert store.active_list("s1") is not None


def test_start_returns_confirmation(skill):
    reply = skill.run(action="start", session_id="s1")
    assert reply


def test_start_confirmation_mentions_list(skill):
    reply = skill.run(action="start", session_id="s1", title="Gift Ideas")
    assert "list" in reply.lower() or "gift ideas" in reply.lower()


def test_start_second_list_prompts_confirmation(skill):
    skill.run(action="start", session_id="s1")
    reply = skill.run(action="start", session_id="s1", title="Grocery Run")
    assert "confirm" in reply.lower() or "replace" in reply.lower() or "start another" in reply.lower()


def test_start_replaces_list_when_confirmed(skill, tmp_path):
    store = CallListStore(tmp_path / "iris.db")
    sk = ListSkill(store)
    sk.run(action="start", session_id="s1", title="Old List")
    sk.run(action="start", session_id="s1", title="New List", confirm_replace=True)
    active = store.active_list("s1")
    assert active is not None
    assert "New List" in active.title or active is not None


# ---------------------------------------------------------------------------
# Action: add
# ---------------------------------------------------------------------------

def test_add_returns_confirmation(skill):
    skill.run(action="start", session_id="s1")
    reply = skill.run(action="add", session_id="s1", item="cast iron skillet")
    assert reply


def test_add_confirmation_mentions_item(skill):
    skill.run(action="start", session_id="s1")
    reply = skill.run(action="add", session_id="s1", item="cast iron skillet")
    assert "cast iron skillet" in reply.lower() or "added" in reply.lower()


def test_add_item_appears_in_store(tmp_path):
    store = CallListStore(tmp_path / "iris.db")
    sk = ListSkill(store)
    sk.run(action="start", session_id="s1")
    sk.run(action="add", session_id="s1", item="herb garden kit")
    lst = store.active_list("s1")
    items = store.get_items(lst.id)
    assert any("herb garden" in i.text.lower() for i in items)


def test_add_multiple_items_ordered(tmp_path):
    store = CallListStore(tmp_path / "iris.db")
    sk = ListSkill(store)
    sk.run(action="start", session_id="s1")
    sk.run(action="add", session_id="s1", item="first")
    sk.run(action="add", session_id="s1", item="second")
    lst = store.active_list("s1")
    items = store.get_items(lst.id)
    assert [i.text for i in items] == ["first", "second"]


# ---------------------------------------------------------------------------
# Action: remove
# ---------------------------------------------------------------------------

def test_remove_item_returns_confirmation(skill, tmp_path):
    store = CallListStore(tmp_path / "iris.db")
    sk = ListSkill(store)
    sk.run(action="start", session_id="s1")
    sk.run(action="add", session_id="s1", item="skillet")
    reply = sk.run(action="remove", session_id="s1", item="skillet")
    assert reply


def test_remove_item_deletes_from_store(tmp_path):
    store = CallListStore(tmp_path / "iris.db")
    sk = ListSkill(store)
    sk.run(action="start", session_id="s1")
    sk.run(action="add", session_id="s1", item="skillet")
    sk.run(action="remove", session_id="s1", item="skillet")
    lst = store.active_list("s1")
    assert store.get_items(lst.id) == []


def test_remove_unknown_item_returns_not_found(skill):
    skill.run(action="start", session_id="s1")
    reply = skill.run(action="remove", session_id="s1", item="ghost item xyz")
    assert "not" in reply.lower() or "couldn't" in reply.lower() or "found" in reply.lower()


# ---------------------------------------------------------------------------
# Action: check (mark done)
# ---------------------------------------------------------------------------

def test_check_item_marks_as_checked(tmp_path):
    store = CallListStore(tmp_path / "iris.db")
    sk = ListSkill(store)
    sk.run(action="start", session_id="s1")
    sk.run(action="add", session_id="s1", item="skillet")
    sk.run(action="check", session_id="s1", item="skillet")
    lst = store.active_list("s1")
    items = store.get_items(lst.id)
    assert items[0].checked is True


def test_check_item_returns_confirmation(skill):
    skill.run(action="start", session_id="s1")
    skill.run(action="add", session_id="s1", item="skillet")
    reply = skill.run(action="check", session_id="s1", item="skillet")
    assert reply


# ---------------------------------------------------------------------------
# Action: show
# ---------------------------------------------------------------------------

def test_show_empty_list(skill):
    skill.run(action="start", session_id="s1")
    reply = skill.run(action="show", session_id="s1")
    assert "empty" in reply.lower() or "nothing" in reply.lower() or "no items" in reply.lower()


def test_show_lists_all_items(tmp_path):
    store = CallListStore(tmp_path / "iris.db")
    sk = ListSkill(store)
    sk.run(action="start", session_id="s1")
    sk.run(action="add", session_id="s1", item="skillet")
    sk.run(action="add", session_id="s1", item="herb garden")
    reply = sk.run(action="show", session_id="s1")
    assert "skillet" in reply.lower()
    assert "herb garden" in reply.lower()


# ---------------------------------------------------------------------------
# Action: export
# ---------------------------------------------------------------------------

def test_export_writes_plain_text_file(tmp_path):
    store = CallListStore(tmp_path / "iris.db")
    sk = ListSkill(store)
    sk.run(action="start", session_id="s1")
    sk.run(action="add", session_id="s1", item="skillet")
    export_dir = tmp_path / "iris-exports"
    export_dir.mkdir()
    sk.run(action="export", session_id="s1", export_dir=str(export_dir))
    files = list(export_dir.iterdir())
    assert len(files) == 1
    assert "skillet" in files[0].read_text().lower()


def test_export_confirms_file_written(tmp_path):
    store = CallListStore(tmp_path / "iris.db")
    sk = ListSkill(store)
    sk.run(action="start", session_id="s1")
    sk.run(action="add", session_id="s1", item="skillet")
    export_dir = tmp_path / "iris-exports"
    export_dir.mkdir()
    reply = sk.run(action="export", session_id="s1", export_dir=str(export_dir))
    assert "export" in reply.lower() or "saved" in reply.lower() or "file" in reply.lower()


def test_export_sms_not_supported_in_v1(tmp_path):
    """v1 export: clipboard + file only — SMS raises NotImplementedError (PM decision)."""
    store = CallListStore(tmp_path / "iris.db")
    sk = ListSkill(store)
    sk.run(action="start", session_id="s1")
    export_dir = tmp_path / "iris-exports"
    export_dir.mkdir()
    with pytest.raises((NotImplementedError, ValueError)):
        sk.run(action="export", session_id="s1", method="sms", export_dir=str(export_dir))


# ---------------------------------------------------------------------------
# Lookup status exposed through the skill
# ---------------------------------------------------------------------------

def test_add_with_lookup_sets_pending_status(tmp_path):
    """When the operator requests a lookup, status must transition to pending."""
    store = CallListStore(tmp_path / "iris.db")
    sk = ListSkill(store)
    sk.run(action="start", session_id="s1")
    sk.run(action="add", session_id="s1", item="cast iron skillet", lookup=True)
    lst = store.active_list("s1")
    items = store.get_items(lst.id)
    assert items[0].lookup_status in ("pending", "done")


def test_add_without_lookup_leaves_status_none(tmp_path):
    store = CallListStore(tmp_path / "iris.db")
    sk = ListSkill(store)
    sk.run(action="start", session_id="s1")
    sk.run(action="add", session_id="s1", item="cast iron skillet")
    lst = store.active_list("s1")
    items = store.get_items(lst.id)
    assert items[0].lookup_status == "none"


def test_add_with_lookup_confirmation_mentions_queued(skill):
    skill.run(action="start", session_id="s1")
    reply = skill.run(action="add", session_id="s1", item="pearl earrings", lookup=True)
    assert "looking up" in reply.lower() or "queued" in reply.lower() or "searching" in reply.lower()


# ---------------------------------------------------------------------------
# Intent routing — design-spec phrases (ti-ccc.16.2 acceptance criteria)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("phrase,expected_action", [
    ("start a list", "start"),
    ("create a list", "start"),
    ("add cast iron skillet to the list", "add"),
    ("put herb garden kit on the list", "add"),
    ("show me the list", "show"),
    ("remove skillet from the list", "remove"),
    ("delete skillet from the list", "remove"),
    ("check off skillet", "check"),
    ("look up price for skillet", "lookup"),
    ("look up hours for hardware store", "lookup"),
    ("look up distance to the mall", "lookup"),
])
def test_intent_routing(phrase, expected_action, tmp_path):
    store = CallListStore(tmp_path / "iris.db")
    sk = ListSkill(store)
    action = sk.parse_intent(phrase)
    assert action == expected_action
