"""Tests for iris.capture.after_store.AfterStore — Call Card AFTER writeback
data layer (ti-hb2dx / ti-05kyj).

AfterStore shares the roster.db SQLite file so contact_id is a real, enforced
FK into contacts(id). These tests stand up a RosterStore (which owns the
contacts table) + a contact, then exercise AfterStore against the same db:
DDL/idempotency, FK + CHECK + UNIQUE enforcement, upsert idempotency, and the
get_*/resolve_* read/mutate surface.
"""
from __future__ import annotations

import sqlite3

import pytest

from iris.capture.after_store import AfterStore
from iris.capture.schemas import DURABLE_FACT_TYPES, FactType
from iris.roster import RosterStore


@pytest.fixture
def db(tmp_path):
    """A roster.db with the contacts table created and one contact present."""
    path = tmp_path / "roster.db"
    roster = RosterStore(path)
    contact = roster.add("Mom", "+12025550100")
    return path, contact.id


@pytest.fixture
def store(db):
    path, _cid = db
    return AfterStore(path)


@pytest.fixture
def contact_id(db):
    _path, cid = db
    return cid


# --- construction / DDL -----------------------------------------------------

def test_init_is_idempotent(db):
    """DDL is CREATE ... IF NOT EXISTS, run on every connect — a second
    AfterStore over the same db must not raise or clobber existing rows."""
    path, cid = db
    s1 = AfterStore(path)
    log_id = s1.insert_call_log(cid, "sess-1", 1.0, 2.0, "iris", None, "")
    # Re-open over the same file — DDL re-runs, existing data survives.
    s2 = AfterStore(path)
    assert s2.get_open_commitments(cid) == []
    s2.insert_commitment(cid, log_id, "i_promised", "call back", None, None, None, None)
    assert len(s2.get_open_commitments(cid)) == 1


# --- call_log ---------------------------------------------------------------

def test_insert_call_log_returns_rowid(store, contact_id):
    log_id = store.insert_call_log(contact_id, "sess-a", 100.0, 200.0, "iris", 150.0, "went well")
    assert isinstance(log_id, int) and log_id > 0


def test_call_log_session_id_is_unique(store, contact_id):
    store.insert_call_log(contact_id, "dup-sess", None, None, "iris", None, "")
    with pytest.raises(sqlite3.IntegrityError):
        store.insert_call_log(contact_id, "dup-sess", None, None, "iris", None, "")


def test_call_log_contact_fk_is_enforced(store):
    """PRAGMA foreign_keys=ON — a call_log for a non-existent contact must fail
    rather than silently orphan."""
    with pytest.raises(sqlite3.IntegrityError):
        store.insert_call_log(999_999, "sess-orphan", None, None, "iris", None, "")


# --- commitment -------------------------------------------------------------

def test_insert_commitment_defaults_to_open(store, contact_id):
    log_id = store.insert_call_log(contact_id, "sess-c", None, None, "iris", None, "")
    store.insert_commitment(
        contact_id, log_id, "they_promised", "send the check", "$50", "2026-08-01", 7, 12.5
    )
    open_ = store.get_open_commitments(contact_id)
    assert len(open_) == 1
    assert open_[0]["description"] == "send the check"
    assert open_[0]["status"] == "open"
    assert open_[0]["amount"] == "$50"
    assert open_[0]["direction"] == "they_promised"


def test_commitment_direction_check_constraint(store, contact_id):
    log_id = store.insert_call_log(contact_id, "sess-d", None, None, "iris", None, "")
    with pytest.raises(sqlite3.IntegrityError):
        store.insert_commitment(
            contact_id, log_id, "maybe_someday", "vague", None, None, None, None
        )


def test_commitment_call_log_fk_is_enforced(store, contact_id):
    with pytest.raises(sqlite3.IntegrityError):
        store.insert_commitment(
            contact_id, 999_999, "i_promised", "orphan", None, None, None, None
        )


def test_resolve_commitment_removes_it_from_open(store, contact_id):
    log_id = store.insert_call_log(contact_id, "sess-e", None, None, "iris", None, "")
    store.insert_commitment(contact_id, log_id, "i_promised", "fix the bug", None, None, None, None)
    cid_row = store.get_open_commitments(contact_id)[0]["id"]

    store.resolve_commitment(cid_row, "honored")

    assert store.get_open_commitments(contact_id) == []
    row = store._conn.execute(
        "SELECT status, resolved_at FROM commitment WHERE id=?", (cid_row,)
    ).fetchone()
    assert row["status"] == "honored"
    assert row["resolved_at"] is not None


# --- contact_fact -----------------------------------------------------------

def test_upsert_contact_fact_is_idempotent(store, contact_id):
    """Same (contact_id, fact_type, normalized_value) upserted twice must yield
    one row, with last_confirmed_at advanced (not a duplicate)."""
    store.upsert_contact_fact(contact_id, "account_id", "AB-123", "Acct", "sess-1")
    first = store.get_contact_facts(contact_id)
    assert len(first) == 1
    first_ts = first[0]["last_confirmed_at"]

    store.upsert_contact_fact(contact_id, "account_id", "AB-123", "Acct", "sess-2")
    facts = store.get_contact_facts(contact_id)
    assert len(facts) == 1  # still one row — upsert, not insert
    assert facts[0]["last_confirmed_at"] >= first_ts
    # first_seen_session is preserved from the original insert.
    assert facts[0]["first_seen_session"] == "sess-1"


def test_upsert_contact_fact_distinct_values_coexist(store, contact_id):
    store.upsert_contact_fact(contact_id, "account_id", "AB-123", "", "s")
    store.upsert_contact_fact(contact_id, "account_id", "CD-456", "", "s")
    store.upsert_contact_fact(contact_id, "policy_id", "AB-123", "", "s")
    assert len(store.get_contact_facts(contact_id)) == 3


# --- per-contact isolation --------------------------------------------------

def test_reads_are_scoped_per_contact(store, db):
    path, mom_id = db
    dad = RosterStore(path).add("Dad", "+12025550199")
    mom_log = store.insert_call_log(mom_id, "s-mom", None, None, "iris", None, "")
    store.insert_commitment(mom_id, mom_log, "they_promised", "mom item", None, None, None, None)
    store.upsert_contact_fact(mom_id, "member_id", "M-1", "", "s-mom")

    assert len(store.get_open_commitments(mom_id)) == 1
    assert len(store.get_contact_facts(mom_id)) == 1
    assert store.get_open_commitments(dad.id) == []
    assert store.get_contact_facts(dad.id) == []


# --- FactType extension (ti-hb2dx) ------------------------------------------

def test_durable_fact_types_include_new_ids():
    """The AFTER data layer extends FactType with the durable-ID promotions."""
    for ft in (FactType.ACCOUNT_ID, FactType.MEMBER_ID, FactType.POLICY_ID):
        assert ft in DURABLE_FACT_TYPES
        assert isinstance(ft.value, str)
