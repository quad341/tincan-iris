"""Tests for roster v0→v1 migration, sentinel exclusion, contact_addresses (ti-s6sp).

F-COV-01 [BLOCKING]: v0→v1 migration on an old-schema database
F-COV-02 [MEDIUM]:   sentinel (id=0) excluded from all()
F-COV-03 [MEDIUM]:   add() writes phone into contact_addresses
"""
from __future__ import annotations

import sqlite3
import time

from iris.roster import SENTINEL_CONTACT_ID, RosterStore


_V0_DDL = """
CREATE TABLE contacts (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name       TEXT    NOT NULL,
    phone_e164         TEXT    NOT NULL UNIQUE,
    handling_rule      TEXT    NOT NULL DEFAULT 'normal',
    trust_tier         TEXT    NOT NULL DEFAULT 'demo',
    relationship_notes TEXT    NOT NULL DEFAULT '',
    created_at         REAL    NOT NULL,
    updated_at         REAL    NOT NULL
);
CREATE TABLE _schema_version (
    id      INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL DEFAULT 0
);
INSERT INTO _schema_version VALUES (1, 0);
"""


def _v0_db(path):
    """Create a v0 database (NOT NULL phone_e164) with two contacts. Returns path."""
    conn = sqlite3.connect(str(path))
    conn.executescript(_V0_DDL)
    now = time.time()
    conn.execute(
        "INSERT INTO contacts (display_name, phone_e164, created_at, updated_at) VALUES (?,?,?,?)",
        ("Alice", "+12025550001", now, now),
    )
    conn.execute(
        "INSERT INTO contacts (display_name, phone_e164, created_at, updated_at) VALUES (?,?,?,?)",
        ("Bob", "+12025550002", now, now),
    )
    conn.commit()
    conn.close()
    return path


# ---------------------------------------------------------------------------
# F-COV-01: v0→v1 migration
# ---------------------------------------------------------------------------

def test_migration_phone_e164_becomes_nullable(tmp_path):
    db = _v0_db(tmp_path / "roster.db")
    RosterStore(db).all()  # triggers _connect() → migration
    conn = sqlite3.connect(str(db))
    col_info = {
        row[1]: row[3]
        for row in conn.execute("PRAGMA table_info(contacts)").fetchall()
    }
    conn.close()
    assert col_info.get("phone_e164") == 0  # NOT NULL bit cleared


def test_migration_contact_addresses_table_created(tmp_path):
    db = _v0_db(tmp_path / "roster.db")
    RosterStore(db).all()
    conn = sqlite3.connect(str(db))
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    conn.close()
    assert "contact_addresses" in tables


def test_migration_existing_phones_backfilled(tmp_path):
    db = _v0_db(tmp_path / "roster.db")
    RosterStore(db).all()
    conn = sqlite3.connect(str(db))
    phones = {r[0] for r in conn.execute(
        "SELECT value FROM contact_addresses WHERE channel='phone'"
    ).fetchall()}
    conn.close()
    assert "+12025550001" in phones
    assert "+12025550002" in phones


def test_migration_sentinel_inserted(tmp_path):
    db = _v0_db(tmp_path / "roster.db")
    RosterStore(db).all()
    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT id FROM contacts WHERE id=?", (SENTINEL_CONTACT_ID,)
    ).fetchone()
    conn.close()
    assert row is not None


def test_migration_schema_version_set_to_1(tmp_path):
    db = _v0_db(tmp_path / "roster.db")
    RosterStore(db).all()
    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT version FROM _schema_version WHERE id=1").fetchone()
    conn.close()
    assert row[0] == 1


def test_migration_existing_contacts_preserved(tmp_path):
    db = _v0_db(tmp_path / "roster.db")
    store = RosterStore(db)
    contacts = store.all()
    names = {c.display_name for c in contacts}
    assert "Alice" in names
    assert "Bob" in names


def test_migration_idempotent_second_open_does_not_re_migrate(tmp_path):
    db = _v0_db(tmp_path / "roster.db")
    RosterStore(db).all()   # first open — migrates
    RosterStore(db).all()   # second open — should not corrupt anything
    conn = sqlite3.connect(str(db))
    version = conn.execute("SELECT version FROM _schema_version WHERE id=1").fetchone()[0]
    conn.close()
    assert version == 1


# ---------------------------------------------------------------------------
# F-COV-02: sentinel excluded from all()
# ---------------------------------------------------------------------------

def test_all_excludes_sentinel_id(tmp_path):
    store = RosterStore(tmp_path / "roster.db")
    store.add("Alice", "+12025550001")
    ids = [c.id for c in store.all()]
    assert SENTINEL_CONTACT_ID not in ids


def test_all_sentinel_present_in_db_but_hidden(tmp_path):
    store = RosterStore(tmp_path / "roster.db")
    store.add("Alice", "+12025550001")
    assert store.get(SENTINEL_CONTACT_ID) is not None  # sentinel IS in the DB
    assert all(c.id != SENTINEL_CONTACT_ID for c in store.all())  # but not in all()


# ---------------------------------------------------------------------------
# F-COV-03: add() writes to contact_addresses
# ---------------------------------------------------------------------------

def test_add_with_phone_inserts_contact_addresses_row(tmp_path):
    db_path = tmp_path / "roster.db"
    store = RosterStore(db_path)
    c = store.add("Alice", "+12025550001")
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT value FROM contact_addresses WHERE contact_id=? AND channel='phone'",
        (c.id,),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "+12025550001"


def test_add_without_phone_no_contact_addresses_row(tmp_path):
    db_path = tmp_path / "roster.db"
    store = RosterStore(db_path)
    c = store.add("Alice")  # no phone
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT id FROM contact_addresses WHERE contact_id=?", (c.id,)
    ).fetchone()
    conn.close()
    assert row is None


def test_get_by_address_phone_finds_contact_via_contact_addresses(tmp_path):
    store = RosterStore(tmp_path / "roster.db")
    c = store.add("Alice", "+12025550001")
    result = store.get_by_address("phone", "+12025550001")
    assert result is not None
    assert result.id == c.id
