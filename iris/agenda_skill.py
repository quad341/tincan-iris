"""Agenda skill — read the day's calendar agenda, event by event.

The first *streaming* skill (``run_stream``): it yields a short preamble then one
chunk per event, so the conductor can speak the first event while the rest are
still being read out (low time-to-first-audio). ``run`` is the complete-result
fallback for non-streaming callers (HomeApp, tests).

It is ``operator_only`` — it reads the operator's personal calendar — so the
permission gate (ADR-0005) only authorizes it for the operator principal, and
the dispatch grammar never even offers it to the far party. Streaming changes
none of that: the gate authorizes once, before the first chunk.

The event source is injected (``events_provider``) so the skill is testable
without a live calendar; real wiring would query the calendar backend.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator

from .skills import SkillParam

# events_provider(day) -> list of {"time": str, "title": str}
EventsProvider = Callable[[str], "list[dict[str, str]]"]


def _demo_events(day: str) -> list[dict[str, str]]:
    if day == "tomorrow":
        return [
            {"time": "9 a.m.", "title": "team standup"},
            {"time": "1 p.m.", "title": "dentist"},
        ]
    return [
        {"time": "10 a.m.", "title": "call with Bob"},
        {"time": "noon", "title": "lunch with Sam"},
        {"time": "3 p.m.", "title": "design review"},
    ]


class AgendaSkill:
    name = "agenda"
    description = "Read the day's calendar agenda, event by event."
    params: list[SkillParam] = [
        SkillParam(
            name="day", type="string",
            description="Which day to read, e.g. 'today' or 'tomorrow'.",
            required=False, default="today",
        ),
    ]
    operator_only = True

    def __init__(self, events_provider: EventsProvider | None = None) -> None:
        self._events: EventsProvider = events_provider or _demo_events

    def run(self, *, day: str = "today", **_kwargs: object) -> str:
        """Complete-result fallback — the whole agenda as one line."""
        events = self._events(day)
        if not events:
            return f"Nothing on your calendar {day}."
        parts = ", ".join(f"{e['title']} at {e['time']}" for e in events)
        noun = "thing" if len(events) == 1 else "things"
        return f"You have {len(events)} {noun} {day}: {parts}."

    def run_stream(self, *, day: str = "today", **_kwargs: object) -> Iterator[str]:
        """Streaming variant — a preamble, then one speakable chunk per event."""
        events = self._events(day)
        if not events:
            yield f"Nothing on your calendar {day}."
            return
        noun = "thing" if len(events) == 1 else "things"
        yield f"You've got {len(events)} {noun} {day}."
        for e in events:
            yield f"{e['time']}: {e['title']}."
