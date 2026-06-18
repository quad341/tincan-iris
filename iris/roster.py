"""Contact roster — ADR-0005 data model and storage.

Each contact has: display_name, phone_e164 (nullable after v1), handling_rule,
trust_tier, relationship_notes, and summary.  Multi-channel addresses live in
contact_addresses (channel, value pairs keyed by UNIQUE(channel, value)).

Schema versioning: _schema_version tracks the migration level. _connect() runs
versioned migrations once on each connection. Migration is forward-only and
transactional; the version counter updates only on commit.

Import semantics: additive only — contacts already on the roster by phone
number are skipped. The caller receives a conflict summary so the console
can display 'N contacts skipped — different display names, review in Contacts'.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

_DEFAULT_PATH = Path.home() / ".local" / "share" / "iris" / "roster.db"

# v1 DDL — phone_e164 nullable; contact_addresses + _schema_version tables added.
# Applied to fresh databases; migration runner handles existing v0 databases.
_DDL_V1 = """
CREATE TABLE IF NOT EXISTS _schema_version (
    id      INTEGER PRIMARY KEY CHECK (id = 1),
    version INTEGER NOT NULL DEFAULT 0
);

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
CREATE INDEX IF NOT EXISTS contacts_phone ON contacts(phone_e164);

CREATE TABLE IF NOT EXISTS contact_addresses (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    channel    TEXT    NOT NULL,
    value      TEXT    NOT NULL,
    label      TEXT    NOT NULL DEFAULT '',
    created_at REAL    NOT NULL,
    UNIQUE (channel, value)
);
CREATE INDEX IF NOT EXISTS ca_by_channel_value ON contact_addresses(channel, value);
CREATE INDEX IF NOT EXISTS ca_by_contact       ON contact_addresses(contact_id);
"""

_HANDLING_RULES = ("normal", "vip", "screen", "take_message", "block")
_TRUST_TIERS = ("demo", "full")

# Reserved contact id for the "unknown / private" sentinel.  id=0 is never
# issued by AUTOINCREMENT (which starts at 1) so this slot is permanently free.
SENTINEL_CONTACT_ID = 0


@dataclass
class Contact:
    id: int
    display_name: str
    phone_e164: str | None  # nullable after v1; may be None for non-phone contacts
    handling_rule: str  # 'normal' | 'vip' | 'screen' | 'take_message' | 'block'
    trust_tier: str     # 'demo' | 'full'
    relationship_notes: str
    created_at: float
    updated_at: float


@dataclass
class ImportResult:
    added: int
    skipped: int
    conflicts: list[tuple[str, str, str]]  # (phone, existing_name, incoming_name)


@runtime_checkable
class RosterProvider(Protocol):
    def get_by_phone(self, phone: str) -> Contact | None: ...
    def get(self, contact_id: int) -> Contact | None: ...
    def all(self) -> list[Contact]: ...
    def add(
        self,
        display_name: str,
        phone_e164: str,
        handling_rule: str = "normal",
        trust_tier: str = "demo",
        relationship_notes: str = "",
    ) -> Contact: ...
    def update(
        self,
        contact_id: int,
        *,
        display_name: str | None = None,
        handling_rule: str | None = None,
        trust_tier: str | None = None,
        relationship_notes: str | None = None,
    ) -> bool: ...
    def delete(self, contact_id: int) -> bool: ...
    def import_contacts(self, contacts: list[dict]) -> ImportResult: ...


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Apply forward-only schema migrations.  Called once per _connect()."""
    conn.execute(
        "INSERT OR IGNORE INTO _schema_version (id, version) VALUES (1, 0)"
    )
    conn.commit()
    row = conn.execute("SELECT version FROM _schema_version WHERE id=1").fetchone()
    version = row[0] if row else 0
    if version < 1:
        _migrate_v0_to_v1(conn)


def _migrate_v0_to_v1(conn: sqlite3.Connection) -> None:
    """v0 → v1: make phone_e164 nullable; add contact_addresses; backfill; insert sentinel."""
    # Detect old schema by checking whether phone_e164 has NOT NULL.
    # PRAGMA table_info columns: cid, name, type, notnull, dflt_value, pk
    col_info = {
        row[1]: row[3]
        for row in conn.execute("PRAGMA table_info(contacts)").fetchall()
    }
    if col_info.get("phone_e164") == 1:
        # Old schema — recreate contacts table without NOT NULL UNIQUE on phone_e164.
        conn.executescript("""
            BEGIN;

            CREATE TABLE contacts_new (
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

            INSERT INTO contacts_new
                (id, display_name, phone_e164, handling_rule, trust_tier,
                 relationship_notes, created_at, updated_at)
            SELECT
                id, display_name, phone_e164, handling_rule, trust_tier,
                relationship_notes, created_at, updated_at
            FROM contacts;

            DROP TABLE contacts;
            ALTER TABLE contacts_new RENAME TO contacts;

            CREATE INDEX IF NOT EXISTS contacts_phone ON contacts(phone_e164);

            COMMIT;
        """)

    # contact_addresses is created by _DDL_V1 (CREATE TABLE IF NOT EXISTS), but
    # for v0 databases that skipped _DDL_V1's new tables, ensure it exists.
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS contact_addresses (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
            channel    TEXT    NOT NULL,
            value      TEXT    NOT NULL,
            label      TEXT    NOT NULL DEFAULT '',
            created_at REAL    NOT NULL,
            UNIQUE (channel, value)
        );
        CREATE INDEX IF NOT EXISTS ca_by_channel_value ON contact_addresses(channel, value);
        CREATE INDEX IF NOT EXISTS ca_by_contact       ON contact_addresses(contact_id);
    """)

    now = time.time()

    # Backfill existing phone_e164 values into contact_addresses.
    rows = conn.execute(
        "SELECT id, phone_e164 FROM contacts WHERE phone_e164 IS NOT NULL AND phone_e164 != ''"
    ).fetchall()
    for contact_id, phone in rows:
        conn.execute(
            "INSERT OR IGNORE INTO contact_addresses"
            " (contact_id, channel, value, created_at) VALUES (?,?,?,?)",
            (contact_id, "phone", phone, now),
        )

    # Insert the unknown sentinel (id=0) if it isn't already there.
    conn.execute(
        "INSERT OR IGNORE INTO contacts"
        " (id, display_name, handling_rule, trust_tier, relationship_notes,"
        "  summary, created_at, updated_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (SENTINEL_CONTACT_ID, "(unknown)", "normal", "demo", "", "", 0.0, 0.0),
    )

    # Mark migration complete.
    conn.execute("UPDATE _schema_version SET version=1 WHERE id=1")
    conn.commit()


class RosterStore:
    """SQLite-backed contact roster.  Follows the list_store.py ``_connect()`` pattern."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else _DEFAULT_PATH

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(_DDL_V1)
        _run_migrations(conn)
        return conn

    @staticmethod
    def _row_to_contact(row: sqlite3.Row) -> Contact:
        return Contact(
            id=row["id"],
            display_name=row["display_name"],
            phone_e164=row["phone_e164"],
            handling_rule=row["handling_rule"],
            trust_tier=row["trust_tier"],
            relationship_notes=row["relationship_notes"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def get_by_phone(self, phone: str) -> Contact | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM contacts WHERE phone_e164=?", (phone,)
            ).fetchone()
        return self._row_to_contact(row) if row else None

    def get(self, contact_id: int) -> Contact | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM contacts WHERE id=?", (contact_id,)
            ).fetchone()
        return self._row_to_contact(row) if row else None

    def all(self) -> list[Contact]:
        """Return all contacts except the internal sentinel (id=0)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM contacts WHERE id != ?"
                " ORDER BY display_name COLLATE NOCASE",
                (SENTINEL_CONTACT_ID,),
            ).fetchall()
        return [self._row_to_contact(r) for r in rows]

    def add(
        self,
        display_name: str,
        phone_e164: str,
        handling_rule: str = "normal",
        trust_tier: str = "demo",
        relationship_notes: str = "",
    ) -> Contact:
        now = time.time()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO contacts"
                " (display_name, phone_e164, handling_rule, trust_tier,"
                "  relationship_notes, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?)",
                (display_name, phone_e164, handling_rule, trust_tier,
                 relationship_notes, now, now),
            )
            contact_id = cur.lastrowid
            if phone_e164:
                # Mirror phone into contact_addresses; UNIQUE(channel,value) enforces
                # no two contacts share the same phone number.
                conn.execute(
                    "INSERT INTO contact_addresses"
                    " (contact_id, channel, value, created_at) VALUES (?,?,?,?)",
                    (contact_id, "phone", phone_e164, now),
                )
            return Contact(
                contact_id, display_name, phone_e164,
                handling_rule, trust_tier, relationship_notes, now, now,
            )

    def update(
        self,
        contact_id: int,
        *,
        display_name: str | None = None,
        handling_rule: str | None = None,
        trust_tier: str | None = None,
        relationship_notes: str | None = None,
    ) -> bool:
        now = time.time()
        fields: list[str] = []
        vals: list = []
        if display_name is not None:
            fields.append("display_name=?"); vals.append(display_name)
        if handling_rule is not None:
            fields.append("handling_rule=?"); vals.append(handling_rule)
        if trust_tier is not None:
            fields.append("trust_tier=?"); vals.append(trust_tier)
        if relationship_notes is not None:
            fields.append("relationship_notes=?"); vals.append(relationship_notes)
        if not fields:
            return False
        fields.append("updated_at=?"); vals.append(now)
        vals.append(contact_id)
        with self._connect() as conn:
            n = conn.execute(
                f"UPDATE contacts SET {', '.join(fields)} WHERE id=?", vals
            ).rowcount
        return n > 0

    def delete(self, contact_id: int) -> bool:
        with self._connect() as conn:
            n = conn.execute(
                "DELETE FROM contacts WHERE id=?", (contact_id,)
            ).rowcount
        return n > 0

    def import_contacts(self, contacts: list[dict]) -> ImportResult:
        """Additive import: skip entries already on roster by phone_e164.

        Returns ImportResult with counts and per-conflict detail so the console
        can show 'N contacts skipped — different display names, review in Contacts'.
        """
        added = 0
        skipped = 0
        conflicts: list[tuple[str, str, str]] = []
        for entry in contacts:
            phone = entry.get("phone_e164", "").strip()
            name = entry.get("display_name", "").strip()
            if not phone or not name:
                continue
            existing = self.get_by_phone(phone)
            if existing is not None:
                skipped += 1
                if existing.display_name != name:
                    conflicts.append((phone, existing.display_name, name))
                continue
            self.add(
                display_name=name,
                phone_e164=phone,
                handling_rule=entry.get("handling_rule", "normal"),
                trust_tier=entry.get("trust_tier", "demo"),
                relationship_notes=entry.get("relationship_notes", ""),
            )
            added += 1
        return ImportResult(added=added, skipped=skipped, conflicts=conflicts)
