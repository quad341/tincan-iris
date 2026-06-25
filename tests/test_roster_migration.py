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


# ---------------------------------------------------------------------------
# F-COV-04: v2 migration on a fresh DB
# ---------------------------------------------------------------------------

def test_v2_migration_runs_on_fresh_db_sets_version_to_2(tmp_path):
    db = tmp_path / "roster.db"
    RosterStore(db).all()
    conn = sqlite3.connect(str(db))
    version = conn.execute("SELECT version FROM _schema_version WHERE id=1").fetchone()[0]
    conn.close()
    assert version == 2


def test_v2_migration_fresh_db_no_prior_schema_creates_all_tables(tmp_path):
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
# F-COV-05: v2 idempotent
# ---------------------------------------------------------------------------

def test_v2_migration_idempotent_second_open_stays_at_2(tmp_path):
    db = tmp_path / "roster.db"
    RosterStore(db).all()
    RosterStore(db).all()
    conn = sqlite3.connect(str(db))
    version = conn.execute("SELECT version FROM _schema_version WHERE id=1").fetchone()[0]
    conn.close()
    assert version == 2


def test_v2_migration_idempotent_enum_values_stable_on_second_open(tmp_path):
    db = _v0_db(tmp_path / "roster.db")
    RosterStore(db).all()
    first_rules = {c.handling_rule for c in RosterStore(db).all()}
    second_rules = {c.handling_rule for c in RosterStore(db).all()}
    assert first_rules == second_rules


# ---------------------------------------------------------------------------
# F-COV-06: enum renames
# ---------------------------------------------------------------------------

def _v1_db_with_rules(path, rules: list[tuple[str, str]]):
    """Create a v1 DB with contacts having specified handling_rules."""
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            display_name TEXT NOT NULL,
            phone_e164 TEXT,
            handling_rule TEXT NOT NULL DEFAULT 'normal',
            trust_tier TEXT NOT NULL DEFAULT 'demo',
            relationship_notes TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE contact_addresses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id INTEGER NOT NULL REFERENCES contacts(id),
            channel TEXT NOT NULL,
            value TEXT NOT NULL,
            UNIQUE(channel, value)
        );
        CREATE TABLE _schema_version (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            version INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO _schema_version VALUES (1, 1);
    """)
    now = time.time()
    for name, rule in rules:
        conn.execute(
            "INSERT INTO contacts (display_name, handling_rule, created_at, updated_at)"
            " VALUES (?, ?, ?, ?)",
            (name, rule, now, now),
        )
    conn.commit()
    conn.close()
    return path


def test_v2_migration_normal_renamed_to_ring_through(tmp_path):
    db = _v1_db_with_rules(tmp_path / "roster.db", [("Alice", "normal")])
    contacts = RosterStore(db).all()
    alice = next(c for c in contacts if c.display_name == "Alice")
    assert alice.handling_rule == "ring_through"


def test_v2_migration_vip_renamed_to_ring_with_announcement(tmp_path):
    db = _v1_db_with_rules(tmp_path / "roster.db", [("Bob", "vip")])
    contacts = RosterStore(db).all()
    bob = next(c for c in contacts if c.display_name == "Bob")
    assert bob.handling_rule == "ring_with_announcement"


def test_v2_migration_block_renamed_to_ignore(tmp_path):
    db = _v1_db_with_rules(tmp_path / "roster.db", [("Carol", "block")])
    contacts = RosterStore(db).all()
    carol = next(c for c in contacts if c.display_name == "Carol")
    assert carol.handling_rule == "ignore"


def test_v2_migration_screen_and_take_message_preserved(tmp_path):
    db = _v1_db_with_rules(tmp_path / "roster.db",
                            [("Dave", "screen"), ("Eve", "take_message")])
    contacts = {c.display_name: c for c in RosterStore(db).all()}
    assert contacts["Dave"].handling_rule == "screen"
    assert contacts["Eve"].handling_rule == "take_message"


# ---------------------------------------------------------------------------
# F-COV-07: unknown enum fallback
# ---------------------------------------------------------------------------

def test_v2_migration_unknown_enum_falls_back_to_ring_through(tmp_path):
    db = _v1_db_with_rules(tmp_path / "roster.db", [("X", "legacy_weird_rule")])
    contacts = RosterStore(db).all()
    x = next(c for c in contacts if c.display_name == "X")
    assert x.handling_rule == "ring_through"


# ---------------------------------------------------------------------------
# F-COV-08: unknown enum warning
# ---------------------------------------------------------------------------

def test_v2_migration_unknown_enum_logs_warning_with_contact_id(tmp_path, caplog):
    import logging
    db = _v1_db_with_rules(tmp_path / "roster.db", [("Y", "totally_unknown")])
    with caplog.at_level(logging.WARNING, logger="iris.roster"):
        RosterStore(db).all()
    assert any("totally_unknown" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# F-COV-09: posture table shape after v1→v2
# ---------------------------------------------------------------------------

def test_v2_posture_table_created_after_v1_migration(tmp_path):
    db = _v0_db(tmp_path / "roster.db")
    RosterStore(db).all()
    conn = sqlite3.connect(str(db))
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    conn.close()
    assert "posture" in tables


def test_v2_posture_table_has_required_columns(tmp_path):
    db = tmp_path / "roster.db"
    RosterStore(db).all()
    conn = sqlite3.connect(str(db))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(posture)").fetchall()}
    conn.close()
    assert {"id", "dnd", "dnd_source", "dnd_expires", "busy", "busy_source", "updated_at"} <= cols


def test_v2_posture_table_empty_after_migration(tmp_path):
    db = tmp_path / "roster.db"
    RosterStore(db).all()
    conn = sqlite3.connect(str(db))
    count = conn.execute("SELECT COUNT(*) FROM posture").fetchone()[0]
    conn.close()
    assert count == 0


# ---------------------------------------------------------------------------
# F-COV-10: PostureStore.ensure_defaults()
# ---------------------------------------------------------------------------

def test_v2_posture_ensure_defaults_inserts_id1_row(tmp_path):
    from iris.roster import PostureStore
    db = tmp_path / "roster.db"
    PostureStore(db).ensure_defaults()
    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT id FROM posture WHERE id=1").fetchone()
    conn.close()
    assert row is not None


def test_v2_posture_ensure_defaults_row_has_dnd_zero_by_default(tmp_path):
    from iris.roster import PostureStore
    db = tmp_path / "roster.db"
    PostureStore(db).ensure_defaults()
    conn = sqlite3.connect(str(db))
    row = conn.execute("SELECT dnd FROM posture WHERE id=1").fetchone()
    conn.close()
    assert row[0] == 0


# ---------------------------------------------------------------------------
# F-COV-11: PostureStore.ensure_defaults() idempotent
# ---------------------------------------------------------------------------

def test_v2_posture_ensure_defaults_idempotent(tmp_path):
    from iris.roster import PostureStore
    db = tmp_path / "roster.db"
    store = PostureStore(db)
    store.ensure_defaults()
    store.ensure_defaults()  # must not raise or duplicate
    conn = sqlite3.connect(str(db))
    count = conn.execute("SELECT COUNT(*) FROM posture WHERE id=1").fetchone()[0]
    conn.close()
    assert count == 1


# ---------------------------------------------------------------------------
# F-COV-12: handling_schedules table shape
# ---------------------------------------------------------------------------

def test_v2_handling_schedules_table_created(tmp_path):
    db = tmp_path / "roster.db"
    RosterStore(db).all()
    conn = sqlite3.connect(str(db))
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    conn.close()
    assert "handling_schedules" in tables


def test_v2_handling_schedules_table_empty_after_migration(tmp_path):
    db = tmp_path / "roster.db"
    RosterStore(db).all()
    conn = sqlite3.connect(str(db))
    count = conn.execute("SELECT COUNT(*) FROM handling_schedules").fetchone()[0]
    conn.close()
    assert count == 0


def test_v2_handling_schedules_table_has_required_columns(tmp_path):
    db = tmp_path / "roster.db"
    RosterStore(db).all()
    conn = sqlite3.connect(str(db))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(handling_schedules)").fetchall()}
    conn.close()
    required = {"id", "name", "schedule_type", "days_of_week", "start_time",
                "end_time", "action", "enabled", "created_at"}
    assert required <= cols


# ---------------------------------------------------------------------------
# F-COV-13: v2 migration transactional rollback
# ---------------------------------------------------------------------------

def test_v2_migration_transactional_rollback_on_failure(tmp_path):
    """If v2 migration fails mid-flight, version stays at 1 (rollback)."""
    import unittest.mock
    db = _v0_db(tmp_path / "roster.db")
    # First open: run v0→v1 only, stopping before v2.
    # We simulate this by running v1 migration manually then breaking v2.
    conn = sqlite3.connect(str(db))
    # Bring to v1 state.
    conn.execute("UPDATE _schema_version SET version=1 WHERE id=1")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS contact_addresses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id INTEGER NOT NULL REFERENCES contacts(id),
            channel TEXT NOT NULL,
            value TEXT NOT NULL,
            UNIQUE(channel, value)
        )
    """)
    conn.commit()
    conn.close()

    # Patch conn.execute so the posture CREATE TABLE raises
    import iris.roster as _roster_mod
    original_migrate = _roster_mod._migrate_v1_to_v2

    def _broken_migrate(conn):
        raise sqlite3.OperationalError("simulated disk failure")

    with unittest.mock.patch.object(_roster_mod, "_migrate_v1_to_v2", _broken_migrate):
        try:
            RosterStore(db).all()
        except sqlite3.OperationalError:
            pass

    conn2 = sqlite3.connect(str(db))
    version = conn2.execute("SELECT version FROM _schema_version WHERE id=1").fetchone()[0]
    conn2.close()
    assert version == 1  # rollback: still at v1
