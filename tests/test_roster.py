"""Tests for iris.roster — Contact, RosterStore, RosterProvider, ImportResult."""
from __future__ import annotations

import pytest

from iris.roster import Contact, ImportResult, RosterProvider, RosterStore


@pytest.fixture
def store(tmp_path):
    return RosterStore(tmp_path / "roster.db")


# --- add + get_by_phone ---

def test_add_returns_contact(store):
    c = store.add("Mom", "+12025550100")
    assert isinstance(c, Contact)
    assert c.display_name == "Mom"
    assert c.phone_e164 == "+12025550100"
    assert c.handling_rule == "normal"
    assert c.trust_tier == "demo"
    assert c.relationship_notes == ""
    assert c.id >= 1


def test_add_custom_fields(store):
    c = store.add("VIP Caller", "+12025550200", handling_rule="vip",
                  trust_tier="full", relationship_notes="Board member")
    assert c.handling_rule == "vip"
    assert c.trust_tier == "full"
    assert c.relationship_notes == "Board member"


def test_get_by_phone_returns_contact(store):
    store.add("Mom", "+12025550100")
    c = store.get_by_phone("+12025550100")
    assert c is not None
    assert c.display_name == "Mom"


def test_get_by_phone_missing_returns_none(store):
    assert store.get_by_phone("+19999999999") is None


def test_add_duplicate_phone_raises(store):
    store.add("Mom", "+12025550100")
    with pytest.raises(Exception):  # UNIQUE constraint
        store.add("Mom Clone", "+12025550100")


# --- get + all ---

def test_get_by_id_returns_contact(store):
    c = store.add("Mom", "+12025550100")
    fetched = store.get(c.id)
    assert fetched is not None
    assert fetched.id == c.id


def test_get_missing_returns_none(store):
    assert store.get(9999) is None


def test_all_returns_alphabetical(store):
    store.add("Zara", "+12025550301")
    store.add("Alice", "+12025550302")
    store.add("Mike", "+12025550303")
    names = [c.display_name for c in store.all()]
    assert names == ["Alice", "Mike", "Zara"]


def test_all_empty(store):
    assert store.all() == []


# --- update ---

def test_update_display_name(store):
    c = store.add("Mom", "+12025550100")
    assert store.update(c.id, display_name="Mum") is True
    updated = store.get(c.id)
    assert updated.display_name == "Mum"


def test_update_handling_rule(store):
    c = store.add("Mom", "+12025550100")
    store.update(c.id, handling_rule="vip")
    assert store.get(c.id).handling_rule == "vip"


def test_update_trust_tier(store):
    c = store.add("Mom", "+12025550100")
    store.update(c.id, trust_tier="full")
    assert store.get(c.id).trust_tier == "full"


def test_update_relationship_notes(store):
    c = store.add("Mom", "+12025550100")
    store.update(c.id, relationship_notes="Prefers mornings")
    assert store.get(c.id).relationship_notes == "Prefers mornings"


def test_update_no_fields_returns_false(store):
    c = store.add("Mom", "+12025550100")
    assert store.update(c.id) is False


def test_update_missing_returns_false(store):
    assert store.update(9999, display_name="Ghost") is False


def test_update_bumps_updated_at(store):
    import time
    c = store.add("Mom", "+12025550100")
    before = c.updated_at
    time.sleep(0.01)
    store.update(c.id, display_name="Mum")
    assert store.get(c.id).updated_at > before


# --- delete ---

def test_delete_removes_contact(store):
    c = store.add("Mom", "+12025550100")
    assert store.delete(c.id) is True
    assert store.get(c.id) is None


def test_delete_missing_returns_false(store):
    assert store.delete(9999) is False


def test_delete_phone_can_be_reused(store):
    c = store.add("Mom", "+12025550100")
    store.delete(c.id)
    c2 = store.add("Mom Reborn", "+12025550100")
    assert c2.id != c.id


# --- import_contacts ---

def test_import_new_contacts(store):
    result = store.import_contacts([
        {"display_name": "Alice", "phone_e164": "+12025550001"},
        {"display_name": "Bob", "phone_e164": "+12025550002"},
    ])
    assert isinstance(result, ImportResult)
    assert result.added == 2
    assert result.skipped == 0
    assert result.conflicts == []
    assert store.get_by_phone("+12025550001") is not None


def test_import_skips_existing_phone(store):
    store.add("Alice", "+12025550001")
    result = store.import_contacts([
        {"display_name": "Alice", "phone_e164": "+12025550001"},
    ])
    assert result.added == 0
    assert result.skipped == 1
    assert result.conflicts == []


def test_import_records_name_conflict(store):
    store.add("Alice Smith", "+12025550001")
    result = store.import_contacts([
        {"display_name": "Alice Jones", "phone_e164": "+12025550001"},
    ])
    assert result.skipped == 1
    assert len(result.conflicts) == 1
    phone, existing, incoming = result.conflicts[0]
    assert phone == "+12025550001"
    assert existing == "Alice Smith"
    assert incoming == "Alice Jones"


def test_import_no_conflict_when_same_name(store):
    store.add("Alice", "+12025550001")
    result = store.import_contacts([
        {"display_name": "Alice", "phone_e164": "+12025550001"},
    ])
    assert result.skipped == 1
    assert result.conflicts == []


def test_import_mixed_new_and_existing(store):
    store.add("Alice", "+12025550001")
    result = store.import_contacts([
        {"display_name": "Alice", "phone_e164": "+12025550001"},
        {"display_name": "Bob", "phone_e164": "+12025550002"},
    ])
    assert result.added == 1
    assert result.skipped == 1


def test_import_skips_missing_phone(store):
    result = store.import_contacts([
        {"display_name": "Alice"},  # no phone_e164
    ])
    assert result.added == 0
    assert result.skipped == 0


def test_import_skips_missing_name(store):
    result = store.import_contacts([
        {"phone_e164": "+12025550001"},  # no display_name
    ])
    assert result.added == 0


def test_import_preserves_existing_contact_data(store):
    store.add("Alice", "+12025550001", trust_tier="full")
    store.import_contacts([
        {"display_name": "Alice", "phone_e164": "+12025550001", "trust_tier": "demo"},
    ])
    c = store.get_by_phone("+12025550001")
    assert c.trust_tier == "full"  # import does not overwrite


# --- RosterProvider protocol check ---

def test_roster_store_satisfies_protocol(store):
    assert isinstance(store, RosterProvider)


# --- persistence across connections ---

def test_contacts_persist_across_reconnect(tmp_path):
    path = tmp_path / "roster.db"
    s1 = RosterStore(path)
    s1.add("Mom", "+12025550100")
    # new connection object
    s2 = RosterStore(path)
    assert s2.get_by_phone("+12025550100") is not None
