"""CallCardPanel event routing (ti-913rw).

Verifies the panel maps daemon call_card_* broadcasts to the right card widgets,
using the ACTUAL daemon payload keys (fact / item / caller_number / contact_name).
Stubs the mount hooks so no Textual App is required.
"""
from __future__ import annotations

from iris.console.call_card import (
    ActionItemCard,
    CallCardPanel,
    CriticalFactCard,
    DisclosureCard,
    FactCard,
)


def _panel(monkeypatch):
    panel = CallCardPanel()
    cards: list = []
    monkeypatch.setattr(panel, "_prepend", lambda c: cards.append(c))
    monkeypatch.setattr(panel, "show_panel", lambda: None)
    return panel, cards


def test_critical_fact_routes_to_critical_card(monkeypatch):
    panel, cards = _panel(monkeypatch)
    panel.handle_event({
        "event": "call_card_fact", "session_id": "s1",
        "fact": {"session_id": "s1", "fact_type": "case_id", "raw_text": "case AB123",
                 "normalized_value": "AB123", "critical": True, "confidence": 0.95},
    })
    assert len(cards) == 1
    assert isinstance(cards[0], CriticalFactCard)


def test_normal_fact_routes_to_fact_card(monkeypatch):
    panel, cards = _panel(monkeypatch)
    panel.handle_event({
        "event": "call_card_fact", "session_id": "s1",
        "fact": {"session_id": "s1", "fact_type": "amount", "raw_text": "$47.50",
                 "normalized_value": "$47.50", "critical": False, "confidence": 0.9},
    })
    assert len(cards) == 1
    assert isinstance(cards[0], FactCard)


def test_action_item_uses_the_item_key(monkeypatch):
    # The daemon broadcasts the action item under "item" (NOT "action_item").
    panel, cards = _panel(monkeypatch)
    panel.handle_event({
        "event": "call_card_action_item", "session_id": "s1",
        "item": {"session_id": "s1", "description": "call back on the 15th", "owner": "far"},
    })
    assert len(cards) == 1
    assert isinstance(cards[0], ActionItemCard)


def test_disclosure_needed_shows_disclosure_card(monkeypatch):
    panel, cards = _panel(monkeypatch)
    panel.handle_event({
        "event": "call_card_disclosure_needed", "session_id": "s1", "script": "AI is listening.",
    })
    assert len(cards) == 1
    assert isinstance(cards[0], DisclosureCard)


def test_started_reads_daemon_caller_keys(monkeypatch):
    # The daemon sends caller_number + contact_name (NOT caller_phone / topic).
    panel, _ = _panel(monkeypatch)
    panel.handle_event({
        "event": "call_card_started", "session_id": "s1",
        "caller_number": "+15551234567", "contact_name": "Mom",
    })
    assert panel._session_id == "s1"
    assert "Mom" in panel.border_title


def test_malformed_fact_is_ignored(monkeypatch):
    panel, cards = _panel(monkeypatch)
    panel.handle_event({"event": "call_card_fact", "session_id": "s1", "fact": {"bogus": 1}})
    assert cards == []


def test_unknown_event_is_ignored(monkeypatch):
    panel, cards = _panel(monkeypatch)
    panel.handle_event({"event": "totally_unrelated"})
    assert cards == []
