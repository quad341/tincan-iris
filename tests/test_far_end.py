"""Tests for FarEndIdentity state machine (ti-fzhp F-COV-01).

Covers: bind/make_private transitions, archival_contact_id for all 3 states,
SENTINEL_ID constant, and immutability (frozen dataclass).
"""
from __future__ import annotations

from iris.far_end import SENTINEL_ID, FarEndIdentity, FarEndState

# ---------------------------------------------------------------------------
# Constant
# ---------------------------------------------------------------------------

def test_sentinel_id_is_zero():
    assert SENTINEL_ID == 0


# ---------------------------------------------------------------------------
# bind() transitions
# ---------------------------------------------------------------------------

def test_bind_on_unidentified_returns_identified():
    fe = FarEndIdentity()
    result = fe.bind(1, "Alice")
    assert result.state is FarEndState.IDENTIFIED
    assert result.contact_id == 1
    assert result.display_name == "Alice"


def test_bind_on_unidentified_does_not_mutate_original():
    fe = FarEndIdentity()
    fe.bind(1, "Alice")
    assert fe.state is FarEndState.UNIDENTIFIED


def test_bind_on_identified_rebinds_to_new_contact():
    fe = FarEndIdentity().bind(1, "Alice").bind(2, "Bob")
    assert fe.state is FarEndState.IDENTIFIED
    assert fe.contact_id == 2
    assert fe.display_name == "Bob"


def test_bind_on_private_is_noop_returns_same_state():
    private = FarEndIdentity().make_private()
    result = private.bind(99, "Alice")
    assert result.state is FarEndState.PRIVATE
    assert result.contact_id == SENTINEL_ID


# ---------------------------------------------------------------------------
# make_private() transitions
# ---------------------------------------------------------------------------

def test_make_private_from_unidentified_returns_private():
    fe = FarEndIdentity().make_private()
    assert fe.state is FarEndState.PRIVATE
    assert fe.contact_id == SENTINEL_ID
    assert fe.display_name == "(private)"


def test_make_private_from_identified_returns_private():
    fe = FarEndIdentity().bind(1, "Alice").make_private()
    assert fe.state is FarEndState.PRIVATE
    assert fe.contact_id == SENTINEL_ID


def test_make_private_from_private_returns_private():
    private = FarEndIdentity().make_private()
    result = private.make_private()
    assert result.state is FarEndState.PRIVATE


# ---------------------------------------------------------------------------
# archival_contact_id
# ---------------------------------------------------------------------------

def test_archival_contact_id_identified_returns_str_of_contact_id():
    fe = FarEndIdentity().bind(42, "Alice")
    assert fe.archival_contact_id == "42"


def test_archival_contact_id_unidentified_returns_none():
    fe = FarEndIdentity()
    assert fe.archival_contact_id is None


def test_archival_contact_id_private_returns_none():
    fe = FarEndIdentity().make_private()
    assert fe.archival_contact_id is None
