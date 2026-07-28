"""Tests for roster v0→v1 migration, sentinel exclusion, contact_addresses (ti-s6sp).
Tests for roster v1→v2 migration: enum rename, posture table, schedules stub (ti-gxpt.1.3).

F-COV-01 [BLOCKING]: v0→v1 migration on an old-schema database
F-COV-02 [MEDIUM]:   sentinel (id=0) excluded from all()
F-COV-03 [MEDIUM]:   add() writes phone into contact_addresses
F-COV-04 [BLOCKING]: v2 migration runs on fresh db (no prior _schema_version)
F-COV-05 [BLOCKING]: v2 migration is idempotent — skips when version already = 2
F-COV-06 [BLOCKING]: all three enum renames applied (normal→ring_through, vip→ring_with_announcement, block→ignore)
F-COV-07 [BLOCKING]: unknown legacy enum falls back to ring_through
F-COV-08 [MEDIUM]:   WARNING logged with contact ID for unknown legacy enum
F-COV-09 [BLOCKING]: posture table created by migration
F-COV-10 [BLOCKING]: posture id=1 default row inserted at daemon first-start (exactly once)
F-COV-11 [BLOCKING]: posture id=1 row NOT re-inserted if row already exists
F-COV-12 [BLOCKING]: handling_schedules table created and empty after migration
F-COV-13 [MEDIUM]:   migration is transactional — db unchanged on failure
"""
from __future__ import annotations

import logging
import sqlite3
import time

import pytest

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


def test_migration_schema_version_set_to_2(tmp_path):
    db = _v0_db(tmp_path / "roster.db")
    RosterStore(db).all()
    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT version FROM _schema_version WHERE id=1").fetchone()
    conn.close()
    assert row[0] == 2  # v0→v1→v2 migrations both run


def test_migration_existing_contacts_preserved(tmp_path):
    db = _v0_db(tmp_path / "roster.db")
    store = RosterStore(db)
    contacts = store.all()
    names = {c.display_name for c in contacts}
    assert "Alice" in names
    assert "Bob" in names


def test_migration_idempotent_second_open_does_not_re_migrate(tmp_path):
    db = _v0_db(tmp_path / "roster.db")
    RosterStore(db).all()   # first open — migrates v0→v1→v2
    RosterStore(db).all()   # second open — should not corrupt anything
    conn = sqlite3.connect(str(db))
    version = conn.execute("SELECT version FROM _schema_version WHERE id=1").fetchone()[0]
    conn.close()
    assert version == 2


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


# ===========================================================================
# v1→v2 migration fixtures (ADR-0006 / ti-gxpt.1.1)
# ===========================================================================

_V1_VERSIONED_DDL = """
CREATE TABLE IF NOT EXISTS _schema_version (
    id      INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO _schema_version (id, version) VALUES (1, 1);

CREATE TABLE IF NOT EXISTS contacts (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name       TEXT    NOT NULL,
    phone_e164         TEXT,
    handling_rule      TEXT    NOT NULL DEFAULT 'normal',
    trust_tier         TEXT    NOT NULL DEFAULT 'demo',
    relationship_notes TEXT    NOT NULL DEFAULT '',
    summary            TEXT    NOT NULL DEFAULT '',
    created_at         REAL    NOT NULL,
    updated_at         REAL    NOT NULL
);

CREATE TABLE IF NOT EXISTS contact_addresses (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    channel    TEXT    NOT NULL,
    value      TEXT    NOT NULL,
    label      TEXT    NOT NULL DEFAULT '',
    created_at REAL    NOT NULL,
    UNIQUE (channel, value)
);
"""


def _v1_db(path):
    """v1 database with contacts using all five legacy handling_rule values."""
    conn = sqlite3.connect(str(path))
    conn.executescript(_V1_VERSIONED_DDL)
    now = time.time()
    for name, phone, rule in [
        ("Alice",   "+12025550011", "normal"),
        ("Bob",     "+12025550012", "vip"),
        ("Charlie", "+12025550013", "block"),
        ("Dave",    "+12025550014", "screen"),
        ("Eve",     "+12025550015", "take_message"),
    ]:
        conn.execute(
            "INSERT INTO contacts (display_name, phone_e164, handling_rule, created_at, updated_at)"
            " VALUES (?,?,?,?,?)",
            (name, phone, rule, now, now),
        )
    conn.commit()
    conn.close()
    return path


def _v1_db_with_unknown_enum(path):
    """v1 database with a contact whose handling_rule is a legacy unknown value."""
    conn = sqlite3.connect(str(path))
    conn.executescript(_V1_VERSIONED_DDL)
    now = time.time()
    conn.execute(
        "INSERT INTO contacts (display_name, phone_e164, handling_rule, created_at, updated_at)"
        " VALUES (?,?,?,?,?)",
        ("Zara", "+12025550099", "urgent", now, now),
    )
    conn.commit()
    conn.close()
    return path


def _raw_handling_rules(db_path):
    """Return {display_name: handling_rule} for all non-sentinel contacts."""
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT display_name, handling_rule FROM contacts WHERE id > 0"
    ).fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}


# ---------------------------------------------------------------------------
# F-COV-04: v2 migration runs cleanly on fresh db
# ---------------------------------------------------------------------------

def test_v2_migration_runs_on_fresh_db_sets_version_to_2(tmp_path):
    """Opening RosterStore on a new path runs the full migration chain to v2."""
    db = tmp_path / "roster.db"
    RosterStore(db).all()
    conn = sqlite3.connect(str(db))
    version = conn.execute("SELECT version FROM _schema_version WHERE id=1").fetchone()[0]
    conn.close()
    assert version == 2


def test_v2_migration_fresh_db_no_prior_schema_creates_all_tables(tmp_path):
    """All three new tables (posture, handling_schedules) exist after fresh-db open."""
    db = tmp_path / "roster.db"
    RosterStore(db).all()
    conn = sqlite3.connect(str(db))
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    conn.close()
    assert "posture" in tables
    assert "handling_schedules" in tables


# ---------------------------------------------------------------------------
# F-COV-05: v2 migration is idempotent
# ---------------------------------------------------------------------------

def test_v2_migration_idempotent_second_open_stays_at_2(tmp_path):
    db = _v1_db(tmp_path / "roster.db")
    RosterStore(db).all()   # first open — migrates v1→v2
    RosterStore(db).all()   # second open — must not corrupt anything
    conn = sqlite3.connect(str(db))
    version = conn.execute("SELECT version FROM _schema_version WHERE id=1").fetchone()[0]
    conn.close()
    assert version == 2


def test_v2_migration_idempotent_enum_values_stable_on_second_open(tmp_path):
    db = _v1_db(tmp_path / "roster.db")
    RosterStore(db).all()
    RosterStore(db).all()
    rules = _raw_handling_rules(db)
    assert rules["Alice"] == "ring_through"
    assert rules["Bob"] == "ring_with_announcement"
    assert rules["Charlie"] == "ignore"


# ---------------------------------------------------------------------------
# F-COV-06: all three enum renames applied
# ---------------------------------------------------------------------------

def test_v2_migration_normal_renamed_to_ring_through(tmp_path):
    db = _v1_db(tmp_path / "roster.db")
    RosterStore(db).all()
    assert _raw_handling_rules(db)["Alice"] == "ring_through"


def test_v2_migration_vip_renamed_to_ring_with_announcement(tmp_path):
    db = _v1_db(tmp_path / "roster.db")
    RosterStore(db).all()
    assert _raw_handling_rules(db)["Bob"] == "ring_with_announcement"


def test_v2_migration_block_renamed_to_ignore(tmp_path):
    db = _v1_db(tmp_path / "roster.db")
    RosterStore(db).all()
    assert _raw_handling_rules(db)["Charlie"] == "ignore"


def test_v2_migration_screen_and_take_message_preserved(tmp_path):
    """Enum values not in the rename list must not be changed."""
    db = _v1_db(tmp_path / "roster.db")
    RosterStore(db).all()
    rules = _raw_handling_rules(db)
    assert rules["Dave"] == "screen"
    assert rules["Eve"] == "take_message"


# ---------------------------------------------------------------------------
# F-COV-07: unknown legacy enum falls back to ring_through
# ---------------------------------------------------------------------------

def test_v2_migration_unknown_enum_falls_back_to_ring_through(tmp_path):
    db = _v1_db_with_unknown_enum(tmp_path / "roster.db")
    RosterStore(db).all()
    assert _raw_handling_rules(db)["Zara"] == "ring_through"


# ---------------------------------------------------------------------------
# F-COV-08: WARNING logged with contact ID for unknown legacy enum
# ---------------------------------------------------------------------------

def test_v2_migration_unknown_enum_logs_warning_with_contact_id(tmp_path, caplog):
    db = _v1_db_with_unknown_enum(tmp_path / "roster.db")
    conn = sqlite3.connect(str(db))
    zara_id = conn.execute(
        "SELECT id FROM contacts WHERE display_name='Zara'"
    ).fetchone()[0]
    conn.close()

    with caplog.at_level(logging.WARNING, logger="iris.roster"):
        RosterStore(db).all()

    warning_msgs = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert any(str(zara_id) in m for m in warning_msgs), (
        f"No WARNING mentioning contact id={zara_id}. Records: {warning_msgs}"
    )


# ---------------------------------------------------------------------------
# F-COV-09: posture table created by migration
# ---------------------------------------------------------------------------

def test_v2_posture_table_created_after_v1_migration(tmp_path):
    db = _v1_db(tmp_path / "roster.db")
    RosterStore(db).all()
    conn = sqlite3.connect(str(db))
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    conn.close()
    assert "posture" in tables


def test_v2_posture_table_has_required_columns(tmp_path):
    db = _v1_db(tmp_path / "roster.db")
    RosterStore(db).all()
    conn = sqlite3.connect(str(db))
    col_names = {r[1] for r in conn.execute("PRAGMA table_info(posture)").fetchall()}
    conn.close()
    assert {"id", "dnd", "dnd_source", "dnd_expires", "busy", "busy_source", "updated_at"} <= col_names


def test_v2_posture_table_empty_after_migration(tmp_path):
    """The migration creates the posture table but does NOT pre-seed any rows."""
    db = _v1_db(tmp_path / "roster.db")
    RosterStore(db).all()
    conn = sqlite3.connect(str(db))
    count = conn.execute("SELECT COUNT(*) FROM posture").fetchone()[0]
    conn.close()
    assert count == 0


# ---------------------------------------------------------------------------
# F-COV-10: posture id=1 default row inserted at daemon first-start
# ---------------------------------------------------------------------------

def test_v2_posture_ensure_defaults_inserts_id1_row(tmp_path):
    from iris.roster import PostureStore

    db = _v1_db(tmp_path / "roster.db")
    RosterStore(db).all()  # run migration first

    PostureStore(db).ensure_defaults()

    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT id FROM posture WHERE id=1").fetchone()
    conn.close()
    assert row is not None, "posture id=1 row must exist after ensure_defaults()"


def test_v2_posture_ensure_defaults_row_has_dnd_zero_by_default(tmp_path):
    from iris.roster import PostureStore

    db = _v1_db(tmp_path / "roster.db")
    RosterStore(db).all()
    PostureStore(db).ensure_defaults()

    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT dnd FROM posture WHERE id=1").fetchone()
    conn.close()
    assert row[0] == 0


# ---------------------------------------------------------------------------
# F-COV-11: posture id=1 row NOT re-inserted on second ensure_defaults call
# ---------------------------------------------------------------------------

def test_v2_posture_ensure_defaults_idempotent(tmp_path):
    from iris.roster import PostureStore

    db = _v1_db(tmp_path / "roster.db")
    RosterStore(db).all()
    store = PostureStore(db)
    store.ensure_defaults()
    store.ensure_defaults()  # second call must not raise or duplicate

    conn = sqlite3.connect(str(db))
    count = conn.execute("SELECT COUNT(*) FROM posture WHERE id=1").fetchone()[0]
    conn.close()
    assert count == 1


# ---------------------------------------------------------------------------
# F-COV-12: handling_schedules table created and empty after migration
# ---------------------------------------------------------------------------

def test_v2_handling_schedules_table_created(tmp_path):
    db = _v1_db(tmp_path / "roster.db")
    RosterStore(db).all()
    conn = sqlite3.connect(str(db))
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    conn.close()
    assert "handling_schedules" in tables


def test_v2_handling_schedules_table_empty_after_migration(tmp_path):
    db = _v1_db(tmp_path / "roster.db")
    RosterStore(db).all()
    conn = sqlite3.connect(str(db))
    count = conn.execute("SELECT COUNT(*) FROM handling_schedules").fetchone()[0]
    conn.close()
    assert count == 0


def test_v2_handling_schedules_table_has_required_columns(tmp_path):
    db = _v1_db(tmp_path / "roster.db")
    RosterStore(db).all()
    conn = sqlite3.connect(str(db))
    col_names = {r[1] for r in conn.execute(
        "PRAGMA table_info(handling_schedules)"
    ).fetchall()}
    conn.close()
    required = {"id", "name", "schedule_type", "days_of_week", "start_time",
                "end_time", "action", "enabled", "created_at"}
    assert required <= col_names


# ---------------------------------------------------------------------------
# F-COV-13: migration is transactional — db unchanged on failure
# ---------------------------------------------------------------------------

def test_v2_migration_transactional_rollback_on_failure(tmp_path, monkeypatch):
    """If _migrate_v1_to_v2 raises, the db must remain at version 1."""
    import iris.roster as roster_mod

    db = _v1_db(tmp_path / "roster.db")
    def _explode(conn):
        raise RuntimeError("injected")
    monkeypatch.setattr(roster_mod, "_migrate_v1_to_v2", _explode)

    with pytest.raises(RuntimeError, match="injected"):
        RosterStore(db).all()

    conn = sqlite3.connect(str(db))
    version = conn.execute("SELECT version FROM _schema_version WHERE id=1").fetchone()[0]
    rules = {r[0] for r in conn.execute(
        "SELECT handling_rule FROM contacts WHERE id > 0"
    ).fetchall()}
    conn.close()
    assert version == 1, "rollback must leave _schema_version at 1"
    assert "normal" in rules or "vip" in rules or "block" in rules, (
        "rollback must leave original enum values intact"
    )
