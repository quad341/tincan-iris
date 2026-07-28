"""Tests for iris.roster — Contact, RosterStore, RosterProvider, ImportResult."""
from __future__ import annotations

import sqlite3

import pytest

from iris.roster import (
    SENTINEL_CONTACT_ID,
    Contact,
    ContactAddress,
    ContactWithAddresses,
    ImportResult,
    RosterProvider,
    RosterStore,
)


@pytest.fixture
def store(tmp_path):
    return RosterStore(tmp_path / "roster.db")


# --- add + get_by_phone ---

def test_add_returns_contact(store):
    c = store.add("Mom", "+12025550100")
    assert isinstance(c, Contact)
    assert c.display_name == "Mom"
    assert c.phone_e164 == "+12025550100"
    assert c.handling_rule == "ring_through"
    assert c.trust_tier == "demo"
    assert c.relationship_notes == ""
    assert c.id >= 1


def test_add_custom_fields(store):
    c = store.add("VIP Caller", "+12025550200", handling_rule="ring_with_announcement",
                  trust_tier="full", relationship_notes="Board member")
    assert c.handling_rule == "ring_with_announcement"
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
    with pytest.raises(sqlite3.IntegrityError):  # UNIQUE constraint
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
    store.update(c.id, handling_rule="ring_with_announcement")
    assert store.get(c.id).handling_rule == "ring_with_announcement"


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


# --- get_by_address ---

def test_get_by_address_found(store):
    c = store.add("Discord User", addresses=[("discord", "user#1234")])
    result = store.get_by_address("discord", "user#1234")
    assert result is not None
    assert result.id == c.id
    assert result.display_name == "Discord User"


def test_get_by_address_not_found(store):
    assert store.get_by_address("email", "nobody@example.com") is None


def test_get_by_address_sentinel_not_returned(store):
    # Migration inserts the sentinel (id=0) but with no addresses; querying any
    # address that has no owner must return None, not the sentinel.
    sentinel = store.get(SENTINEL_CONTACT_ID)
    assert sentinel is not None  # sentinel exists
    assert store.get_by_address("phone", "ghostnumber") is None


# --- get_by_phone backward compat ---

def test_get_by_phone_delegates_to_get_by_address(store, monkeypatch):
    calls: list[tuple[str, str]] = []
    original = store.get_by_address
    def spy(channel: str, value: str) -> object:
        calls.append((channel, value))
        return original(channel, value)
    monkeypatch.setattr(store, "get_by_address", spy)
    store.get_by_phone("+12025550100")
    assert calls == [("phone", "+12025550100")]


# --- search ---

def test_search_empty_query_returns_all_non_sentinel(store):
    store.add("Alice", "+12025550001")
    store.add("Bob", "+12025550002")
    results = store.search("")
    names = [r.contact.display_name for r in results]
    assert "Alice" in names
    assert "Bob" in names


def test_search_name_match(store):
    store.add("Alice Wonderland", "+12025550001")
    store.add("Bob Smith", "+12025550002")
    results = store.search("Alice")
    assert len(results) == 1
    assert results[0].contact.display_name == "Alice Wonderland"


def test_search_address_value_match(store):
    c = store.add("Discord Guy")
    store.add_address(c.id, "discord", "coolguy#5678")
    results = store.search("coolguy")
    assert len(results) == 1
    assert results[0].contact.id == c.id


def test_search_multiple_results(store):
    store.add("Alice Smith", "+12025550001")
    store.add("Bob Smith", "+12025550002")
    results = store.search("Smith")
    assert len(results) == 2


def test_search_sentinel_excluded(store):
    results = store.search("")
    ids = [r.contact.id for r in results]
    assert SENTINEL_CONTACT_ID not in ids


def test_search_no_match(store):
    store.add("Alice", "+12025550001")
    assert store.search("zzz-no-such-person") == []


# --- add_address ---

def test_add_address_returns_contact_address(store):
    c = store.add("Alice", "+12025550001")
    addr = store.add_address(c.id, "email", "alice@example.com", label="personal")
    assert isinstance(addr, ContactAddress)
    assert addr.contact_id == c.id
    assert addr.channel == "email"
    assert addr.value == "alice@example.com"
    assert addr.label == "personal"
    assert addr.id >= 1
    assert addr.created_at > 0


def test_add_address_duplicate_raises(store):
    c1 = store.add("Alice", "+12025550001")
    c2 = store.add("Bob", "+12025550002")
    store.add_address(c1.id, "email", "shared@example.com")
    with pytest.raises(sqlite3.IntegrityError):  # UNIQUE(channel, value)
        store.add_address(c2.id, "email", "shared@example.com")


# --- remove_address ---

def test_remove_address_returns_true_on_success(store):
    c = store.add("Alice", "+12025550001")
    addr = store.add_address(c.id, "email", "alice@example.com")
    assert store.remove_address(addr.id) is True


def test_remove_address_returns_false_for_missing(store):
    assert store.remove_address(9999) is False


# --- add with addresses list ---

def test_add_with_addresses_stores_them(store):
    store.add("Alice", addresses=[("email", "alice@example.com"), ("discord", "alice#1234")])
    assert store.get_by_address("email", "alice@example.com") is not None
    assert store.get_by_address("discord", "alice#1234") is not None


def test_add_phone_dedup_guard_no_duplicate_row(store):
    # phone_e164 is auto-inserted into contact_addresses; passing the same phone
    # in addresses must not hit the UNIQUE constraint.
    phone = "+12025550001"
    c = store.add("Alice", phone_e164=phone, addresses=[("phone", phone), ("email", "a@example.com")])
    result = store.get_by_address("phone", phone)
    assert result is not None and result.id == c.id


# --- ContactWithAddresses.primary_display ---

def _make_contact(name: str = "Alice") -> Contact:
    return Contact(id=1, display_name=name, phone_e164=None,
                   handling_rule="ring_through", trust_tier="demo",
                   relationship_notes="", created_at=0.0, updated_at=0.0)


def _make_addr(channel: str, value: str, addr_id: int = 1) -> ContactAddress:
    return ContactAddress(id=addr_id, contact_id=1, channel=channel, value=value,
                          label="", created_at=0.0)


def test_primary_display_no_addresses():
    cwa = ContactWithAddresses(contact=_make_contact("Alice"), addresses=[])
    assert cwa.primary_display() == "Alice"


def test_primary_display_one_address():
    cwa = ContactWithAddresses(
        contact=_make_contact("Alice"),
        addresses=[_make_addr("email", "alice@example.com")],
    )
    assert cwa.primary_display() == "Alice (email:alice@example.com)"


def test_primary_display_three_addresses_truncates_at_two():
    addrs = [
        _make_addr("phone", "v1", addr_id=1),
        _make_addr("email", "v2", addr_id=2),
        _make_addr("discord", "v3", addr_id=3),
    ]
    cwa = ContactWithAddresses(contact=_make_contact("Alice"), addresses=addrs)
    result = cwa.primary_display()
    assert result == "Alice (phone:v1, email:v2)"
    assert "discord" not in result
