"""Assemble the optional ("offline") skills the Brain registers when available.

The Brain always has the Tier-0/default skills (time, echo). On top of those it
registers the optional lanes here — each gated on its dependency being present
(a local store, config, or daemon), so qwen gets exactly the skills that can
actually work. Because the HomeApp drives the same Brain, surfacing a skill here
makes it usable from Home too.

Lanes:
  * notes      — local store, always on
  * roster     — local sqlite contacts store, always on
  * web_search — no credentials, always on
  * email      — only when host+user+password are configured (env or secrets.toml)
  * dial       — only when a TincanCallControl is provided (D-Bus + tincand required)

(messages/calendar register elsewhere once their daemon/token is present.)
"""
from __future__ import annotations


def optional_skills(notes_store=None, roster=None, ctrl=None) -> list:
    """Return the optional skill instances available in this environment.

    ``notes_store`` / ``roster`` may be injected (tests); otherwise the default
    local stores are used. Imports are lazy so the Brain only pulls in a lane's
    deps when this is called. Pass ``ctrl`` (a ``TincanCallControl``) to also
    register the dial skills (operator_only, requires tincand D-Bus).
    """
    skills: list = []

    # Notes — local store, always available.
    from .notes import NotesStore, notes_skills
    skills += notes_skills(notes_store or NotesStore())

    # Roster (contacts) — local sqlite store, always available. Shared with the
    # email lane so SendEmail can resolve contact names.
    from .roster import RosterStore
    from .roster_skill import RosterVoiceSkills
    roster = roster or RosterStore()
    skills += RosterVoiceSkills(roster).skills()

    # Web search — no credentials.
    from .web_search import WebSearchSkill
    skills.append(WebSearchSkill())

    # Email — only when fully configured (host+user+password).
    from .email_skill import configured_email_skills
    skills += configured_email_skills(roster=roster)

    # Calendar — only when a Google OAuth token exists (run `iris auth gcal`).
    from .calendar import configured_calendar_skills
    skills += configured_calendar_skills()

    # Dial — only when a TincanCallControl is provided (D-Bus + tincand required).
    if ctrl is not None:
        from .dial_skill import DialVoiceSkills
        skills += DialVoiceSkills(ctrl, roster).skills()

    return skills
