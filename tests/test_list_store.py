"""Tests for CallListStore — CallList, ListItem, LookupResult CRUD + retention."""
from __future__ import annotations

import pytest

from iris.list_store import CallList, CallListStore, ListItem, LookupResult


@pytest.fixture
def store(tmp_path):
    return CallListStore(tmp_path / "iris.db")


# --- CallList ---

def test_create_list_returns_dataclass(store):
    cl = store.create_list("s1")
    assert isinstance(cl, CallList)
    assert cl.session_id == "s1"
    assert cl.status == "active"
    assert cl.title == "Shopping list"
    assert cl.id >= 1


def test_create_list_custom_title(store):
    cl = store.create_list("s1", title="Grocery run")
    assert cl.title == "Grocery run"


def test_get_list_roundtrip(store):
    cl = store.create_list("s1")
    fetched = store.get_list(cl.id)
    assert fetched is not None
    assert fetched.id == cl.id
    assert fetched.session_id == "s1"


def test_get_list_missing(store):
    assert store.get_list(9999) is None


def test_active_list_returns_active(store):
    cl = store.create_list("s1")
    found = store.active_list("s1")
    assert found is not None and found.id == cl.id


def test_active_list_none_after_complete(store):
    cl = store.create_list("s1")
    store.complete_list(cl.id)
    assert store.active_list("s1") is None


def test_complete_list_updates_status(store):
    cl = store.create_list("s1")
    assert store.complete_list(cl.id) is True
    assert store.get_list(cl.id).status == "complete"


def test_complete_list_missing_returns_false(store):
    assert store.complete_list(9999) is False


# --- ListItem ---

def test_add_item_returns_dataclass(store):
    cl = store.create_list("s1")
    item = store.add_item(cl.id, "milk")
    assert isinstance(item, ListItem)
    assert item.list_id == cl.id
    assert item.text == "milk"
    assert item.checked is False
    assert item.position == 1


def test_add_item_positions_increment(store):
    cl = store.create_list("s1")
    i1 = store.add_item(cl.id, "milk")
    i2 = store.add_item(cl.id, "eggs")
    assert i2.position == i1.position + 1


def test_get_items_ordered_by_position(store):
    cl = store.create_list("s1")
    store.add_item(cl.id, "first")
    store.add_item(cl.id, "second")
    items = store.get_items(cl.id)
    assert [i.text for i in items] == ["first", "second"]


def test_get_items_empty_list(store):
    cl = store.create_list("s1")
    assert store.get_items(cl.id) == []


def test_check_item_marks_checked(store):
    cl = store.create_list("s1")
    item = store.add_item(cl.id, "butter")
    assert store.check_item(item.id) is True
    items = store.get_items(cl.id)
    assert items[0].checked is True


def test_uncheck_item(store):
    cl = store.create_list("s1")
    item = store.add_item(cl.id, "butter")
    store.check_item(item.id, checked=True)
    store.check_item(item.id, checked=False)
    assert store.get_items(cl.id)[0].checked is False


def test_remove_item(store):
    cl = store.create_list("s1")
    item = store.add_item(cl.id, "butter")
    assert store.remove_item(item.id) is True
    assert store.get_items(cl.id) == []


def test_remove_item_missing(store):
    assert store.remove_item(9999) is False


# --- LookupResult ---

def test_add_lookup_returns_dataclass(store):
    cl = store.create_list("s1")
    item = store.add_item(cl.id, "milk")
    lr = store.add_lookup(item.id, "web", "Milk is $3.49 at Safeway.")
    assert isinstance(lr, LookupResult)
    assert lr.list_item_id == item.id
    assert lr.source == "web"
    assert "Safeway" in lr.text


def test_get_lookups_ordered_by_timestamp(store):
    cl = store.create_list("s1")
    item = store.add_item(cl.id, "eggs")
    store.add_lookup(item.id, "web", "first")
    store.add_lookup(item.id, "web", "second")
    lrs = store.get_lookups(item.id)
    assert len(lrs) == 2
    assert lrs[0].text == "first"


def test_get_lookups_empty(store):
    cl = store.create_list("s1")
    item = store.add_item(cl.id, "cheese")
    assert store.get_lookups(item.id) == []


def test_remove_item_cascades_lookups(store):
    cl = store.create_list("s1")
    item = store.add_item(cl.id, "bread")
    store.add_lookup(item.id, "web", "some result")
    store.remove_item(item.id)
    assert store.get_lookups(item.id) == []


# --- retention ---

def test_prune_removes_old_lists(tmp_path):
    store = CallListStore(tmp_path / "iris.db", retention_days=0)
    cl = store.create_list("s1")
    pruned = store.prune()
    assert pruned >= 1
    assert store.get_list(cl.id) is None


def test_prune_keeps_recent_lists(store):
    cl = store.create_list("s1")
    pruned = store.prune()  # retention=90 days; just created
    assert pruned == 0
    assert store.get_list(cl.id) is not None


# --- persistence ---

def test_persists_across_instances(tmp_path):
    path = tmp_path / "iris.db"
    s1 = CallListStore(path)
    cl = s1.create_list("sess")
    s1.add_item(cl.id, "apple")
    s2 = CallListStore(path)
    items = s2.get_items(cl.id)
    assert len(items) == 1 and items[0].text == "apple"
