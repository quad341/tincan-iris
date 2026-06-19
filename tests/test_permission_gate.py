"""The permission gate (ADR-0005): the default-closed authorizer + the daemon's
propose -> authorize -> execute split. The model only proposes; the daemon runs.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from iris.authz import Authorizer, AuthzContext
from iris.brain import Brain
from iris.config import Config
from iris.lanes import LaneResult, SkillProposal
from iris.skills import SkillParam, SkillRegistry


class _DialSkill:
    """A privileged (operator_only) skill — must never run for the far party."""

    name = "dial"
    description = "Place a call."
    operator_only = True
    params = [SkillParam(name="number", type="string", description="number")]

    def __init__(self) -> None:
        self.called_with = None

    def run(self, *, number, **_):
        self.called_with = number
        return f"calling {number}"


class _NoteSkill:
    """A non-privileged skill."""

    name = "note"
    description = "Take a note."
    operator_only = False
    params = [SkillParam(name="text", type="string", description="text")]

    def __init__(self) -> None:
        self.called_with = None

    def run(self, *, text, **_):
        self.called_with = text
        return f"noted: {text}"


# ---------------------------------------------------------------------------
# Authorizer — default-closed
# ---------------------------------------------------------------------------

def test_authorizer_allows_operator_only_for_operator():
    assert Authorizer().authorize(_DialSkill(), AuthzContext(is_operator=True)).allowed


def test_authorizer_denies_operator_only_for_non_operator():
    d = Authorizer().authorize(_DialSkill(), AuthzContext(is_operator=False))
    assert not d.allowed and d.reason


def test_authorizer_allows_non_privileged_for_anyone():
    assert Authorizer().authorize(_NoteSkill(), AuthzContext(is_operator=False)).allowed


# ---------------------------------------------------------------------------
# Soft layer — the far party is never even OFFERED an operator_only skill
# ---------------------------------------------------------------------------

def test_registry_hides_operator_only_from_far():
    reg = SkillRegistry([_DialSkill(), _NoteSkill()])
    assert "dial" in reg.names("operator")
    assert "dial" in reg.names("")          # unknown: soft layer stays open (hard gate is the boundary)
    assert "dial" not in reg.names("far")   # far is never offered it
    assert "note" in reg.names("far")


# ---------------------------------------------------------------------------
# The daemon spine — propose -> authorize -> execute
# ---------------------------------------------------------------------------

def _brain_with(*skills):
    """A Brain whose registry is exactly these skills, with the qwen lane mocked
    so we can hand it a proposal directly (no model / no masking)."""
    b = Brain(Config(), skills=SkillRegistry(list(skills)))
    b.tier1 = MagicMock()
    return b


def _propose(b, skill_name, args):
    b.tier1.handle.return_value = LaneResult(
        "", "tier1-qwen", skill=skill_name, proposal=SkillProposal(skill_name, args),
    )


def _dispatch(b, *, speaker):
    return b._dispatch("x", speaker=speaker, hint="", demo_mode=False)


def test_daemon_executes_authorized_proposal():
    note = _NoteSkill()
    b = _brain_with(note)
    _propose(b, "note", {"text": "hi"})
    r = _dispatch(b, speaker="operator")
    assert note.called_with == "hi"
    assert r.text == "noted: hi"


def test_daemon_refuses_operator_only_for_far():
    dial = _DialSkill()
    b = _brain_with(dial)
    _propose(b, "dial", {"number": "555"})
    r = _dispatch(b, speaker="far")
    assert dial.called_with is None                 # NEVER executed for the far party
    assert "can't" in r.text.lower() or "sorry" in r.text.lower()


def test_daemon_runs_operator_only_for_operator():
    dial = _DialSkill()
    b = _brain_with(dial)
    _propose(b, "dial", {"number": "555"})
    _dispatch(b, speaker="operator")
    assert dial.called_with == "555"


def test_daemon_degrades_on_missing_required_arg():
    note = _NoteSkill()
    b = _brain_with(note)
    _propose(b, "note", {})                         # missing required 'text'
    r = _dispatch(b, speaker="operator")
    assert note.called_with is None
    assert "another way" in r.text.lower() or "didn't catch" in r.text.lower()


def test_daemon_collapses_tuple_reply():
    class _Cal:
        name = "cal"
        description = "cal"
        operator_only = False
        params = [SkillParam(name="when", type="string", description="when")]

        def run(self, *, when, **_):
            return ("That time looks free.", f"[calendar: {when}]")

    b = _brain_with(_Cal())
    _propose(b, "cal", {"when": "2026-06-19T15:00:00"})
    r = _dispatch(b, speaker="operator")
    assert r.text == "That time looks free."
    assert "[calendar" not in r.text                # console annotation never spoken


# ---------------------------------------------------------------------------
# Principal resolution — default-closed
# ---------------------------------------------------------------------------

def test_principal_default_closed_in_call():
    b = _brain_with(_NoteSkill())
    b.call_context = "contact-123"                  # in a call
    assert b._resolve_is_operator("") is False      # unknown speaker in a call -> NOT operator
    assert b._resolve_is_operator("far") is False
    assert b._resolve_is_operator("operator") is True


def test_principal_operator_when_not_in_call():
    b = _brain_with(_NoteSkill())
    b.call_context = ""                             # not in a call (console / mic-only)
    assert b._resolve_is_operator("") is True       # the operator is the only party present


# ---------------------------------------------------------------------------
# Adversarial — try to BREAK the gate
# ---------------------------------------------------------------------------

def test_attack_soft_layer_leak_is_caught_by_the_hard_gate():
    """Even if offered-set scoping fails and the model proposes an operator_only
    skill to the far party, the daemon gate still refuses it. The hard gate — not
    the grammar — is the boundary."""
    dial = _DialSkill()
    b = _brain_with(dial)
    _propose(b, "dial", {"number": "555"})          # the 'leaked' proposal
    r = _dispatch(b, speaker="far")
    assert dial.called_with is None                 # blocked at execution
    assert "sorry" in r.text.lower() or "can't" in r.text.lower()


def test_attack_unthreaded_speaker_in_a_call_defaults_closed():
    """If the speaker tag fails to thread (speaker="") *during a call*, an
    operator_only proposal must still be refused — never assume operator."""
    dial = _DialSkill()
    b = _brain_with(dial)
    b.call_context = "contact-xyz"                  # we are in a call
    _propose(b, "dial", {"number": "555"})
    r = _dispatch(b, speaker="")                    # tag missing
    assert dial.called_with is None
    assert "sorry" in r.text.lower() or "can't" in r.text.lower()


def test_attack_far_cannot_even_name_operator_only_skill():
    """Soft layer: the far party's dispatch grammar never contains the
    operator_only skill name, so the model can't even propose it."""
    from iris.lanes import Tier1Qwen
    tier = Tier1Qwen(Config(), skills=SkillRegistry([_DialSkill(), _NoteSkill()]))
    far_grammar = tier._build_grammar("far")
    assert '"dial"' not in far_grammar
    assert '"note"' in far_grammar
    assert '"dial"' in tier._build_grammar("operator")


def test_attack_demo_far_is_never_offered_skills():
    """A far party in DEMO never reaches the dispatch path — allow_skills=False,
    so no proposal can even form."""
    from iris.trust import TrustMode
    b = _brain_with(_DialSkill())
    b.tier1.handle.return_value = LaneResult("chat", "tier1-qwen")   # no proposal
    with patch("iris.brain.run_with_masking", side_effect=lambda work, **k: work()):
        b.respond("dial 555", speaker="far", far_trust=TrustMode.DEMO)
    _, kwargs = b.tier1.handle.call_args
    assert kwargs.get("allow_skills") is False


def test_invariant_no_tools_in_qwen_payload():
    """Guard for ADR-0005 invariant #1: the model is never handed tools — the
    dispatch request must carry no tool/function surface."""
    import json as _json

    from iris.lanes import Tier1Qwen
    tier = Tier1Qwen(Config(), skills=SkillRegistry([_NoteSkill()]))
    captured = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"content": "{\\"skill\\":\\"none\\",\\"args\\":{}}"}'

    def _fake_urlopen(req, timeout):
        captured["body"] = req.data
        return _Resp()

    with patch("iris.lanes.urllib.request.urlopen", _fake_urlopen):
        tier._complete("hi", 16)
    payload = _json.loads(captured["body"])
    assert "tools" not in payload
    assert "functions" not in payload
    assert "tool_choice" not in payload
