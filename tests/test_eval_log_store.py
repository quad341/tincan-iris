"""Tests for EvalLogStore — write-only encrypted STT eval log (ti-qi76c, ti-x46ji).

Follows the AfterStore/CallCardStore SQLite convention (see test_after_store.py):
a tmp_path-backed db_path is passed straight into the constructor, no mocking.
"""
from __future__ import annotations

import ast
import gzip
import inspect
import json
import sqlite3
import tomllib
from pathlib import Path

import nacl.public

from iris.capture import eval_log_store as eval_log_store_module
from iris.capture.eval_log_store import EvalLogStore

_REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# construction / schema
# ---------------------------------------------------------------------------

def test_construction_creates_expected_schema(tmp_path):
    db_path = tmp_path / "eval_log.db"
    EvalLogStore(db_path)

    conn = sqlite3.connect(str(db_path))
    columns = {row[1]: row[2] for row in conn.execute("PRAGMA table_info(eval_log_entries)")}
    assert columns == {
        "id": "INTEGER",
        "session_id": "TEXT",
        "key_version": "INTEGER",
        "sealed_blob": "BLOB",
        "created_at": "REAL",
    }
    index_names = {row[1] for row in conn.execute("PRAGMA index_list(eval_log_entries)")}
    assert "eval_log_by_session" in index_names


def test_construction_is_idempotent_against_existing_db(tmp_path):
    """DDL is CREATE ... IF NOT EXISTS -- a second EvalLogStore over the same
    file must not raise or clobber existing rows (AfterStore/CallCardStore
    convention; see test_after_store.py's own idempotency test)."""
    db_path = tmp_path / "eval_log.db"
    EvalLogStore(db_path).append("s1", 1, b"a")
    EvalLogStore(db_path).append("s2", 1, b"b")

    conn = sqlite3.connect(str(db_path))
    session_ids = [
        row[0] for row in conn.execute("SELECT session_id FROM eval_log_entries ORDER BY id")
    ]
    assert session_ids == ["s1", "s2"]


# ---------------------------------------------------------------------------
# append (coverage item 1)
# ---------------------------------------------------------------------------

def test_append_writes_exactly_one_row_with_expected_values(tmp_path):
    db_path = tmp_path / "eval_log.db"
    EvalLogStore(db_path).append("session-1", 3, b"sealed-bytes")

    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        "SELECT session_id, key_version, sealed_blob, created_at FROM eval_log_entries"
    ).fetchall()
    assert len(rows) == 1
    session_id, key_version, sealed_blob, created_at = rows[0]
    assert (session_id, key_version, sealed_blob) == ("session-1", 3, b"sealed-bytes")
    assert isinstance(created_at, float)


def test_append_called_twice_for_same_session_writes_two_rows(tmp_path):
    db_path = tmp_path / "eval_log.db"
    store = EvalLogStore(db_path)
    store.append("session-1", 1, b"a")
    store.append("session-1", 1, b"b")

    conn = sqlite3.connect(str(db_path))
    count = conn.execute(
        "SELECT COUNT(*) FROM eval_log_entries WHERE session_id = 'session-1'"
    ).fetchone()[0]
    assert count == 2


# ---------------------------------------------------------------------------
# hard AC: no read/select/decrypt path exists anywhere on the class
# (coverage item 2 -- AST-based, not a substring grep: the module's own
# docstring legitimately discusses "decrypt" as a concept)
# ---------------------------------------------------------------------------

def _eval_log_store_class_node():
    tree = ast.parse(inspect.getsource(eval_log_store_module))
    return next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef) and n.name == "EvalLogStore"
    )


def test_public_api_is_exactly_append():
    class_node = _eval_log_store_class_node()
    method_names = {
        n.name for n in class_node.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    public_methods = {name for name in method_names if not name.startswith("_")}
    assert public_methods == {"append"}


def test_no_select_sql_literal_anywhere_in_the_class():
    """Defense in depth alongside the public-API check: no string literal in
    the class body may contain a SELECT statement."""
    class_node = _eval_log_store_class_node()
    string_literals = [
        n.value for n in ast.walk(class_node)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]
    assert not any("select" in literal.lower() for literal in string_literals)


# ---------------------------------------------------------------------------
# crypto: full SealedBox round trip (coverage item 3)
# ---------------------------------------------------------------------------

def test_sealed_box_round_trip_recovers_original_transcript(tmp_path):
    private_key = nacl.public.PrivateKey.generate()
    turns = [
        {"turn_id": 1, "text": "hello", "speaker": "operator", "offset_s": 0.0, "trust": "none"},
        {"turn_id": 2, "text": "hi there", "speaker": "far", "offset_s": 1.5, "trust": "none"},
    ]
    compressed = gzip.compress(json.dumps(turns).encode("utf-8"))
    sealed_blob = nacl.public.SealedBox(private_key.public_key).encrypt(compressed)
    assert sealed_blob != compressed

    db_path = tmp_path / "eval_log.db"
    EvalLogStore(db_path).append("session-1", 1, sealed_blob)

    # Independently read the raw row back -- a fresh connection, no help from
    # the store under test.
    conn = sqlite3.connect(str(db_path))
    (raw_blob,) = conn.execute("SELECT sealed_blob FROM eval_log_entries").fetchone()
    assert raw_blob == sealed_blob

    recovered_compressed = nacl.public.SealedBox(private_key).decrypt(raw_blob)
    assert recovered_compressed == compressed
    assert json.loads(gzip.decompress(recovered_compressed)) == turns


# ---------------------------------------------------------------------------
# pyproject.toml: PyNaCl is an optional extra, not a core dependency
# (coverage item 7)
# ---------------------------------------------------------------------------

def test_pynacl_is_only_a_call_card_extra_not_a_core_dependency():
    data = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text())

    core_deps = data["project"]["dependencies"]
    assert not any("nacl" in dep.lower() for dep in core_deps)

    call_card_extra = data["project"]["optional-dependencies"]["call-card"]
    assert any(dep.lower().startswith("pynacl") for dep in call_card_extra)
