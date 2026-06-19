"""The Tier-0 command table exposes (name, example) pairs for the console's
command dump. Also covers SkillRegistry manifest + param schema, and Tier1Qwen
grammar-constrained dispatch."""
from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch

from iris.config import Config
from iris.lanes import Tier0Rules, Tier1Qwen
from iris.skills import EchoSkill, SkillParam, SkillRegistry, TimeSkill, default_registry


def test_commands_lists_name_example_pairs():
    cmds = dict(Tier0Rules(default_registry()).commands())
    assert {"introduce", "time", "stop"} <= set(cmds)
    assert cmds["time"]            # has an example phrasing
    assert cmds["introduce"]


def test_commands_match_examples():
    t0 = Tier0Rules(default_registry())
    assert [ex for _n, ex in t0.commands()] == t0.examples()


# --- SkillParam schema + registry manifest ---

def test_skill_params_time_has_no_params():
    assert TimeSkill().params == []


def test_skill_params_echo_declares_text():
    params = EchoSkill().params
    assert len(params) == 1
    p = params[0]
    assert p.name == "text" and p.type == "string" and p.required is True


def test_registry_manifest_shape():
    reg = default_registry()
    mf = reg.manifest()
    names = {e["name"] for e in mf}
    assert names == {"time", "echo"}
    echo_entry = next(e for e in mf if e["name"] == "echo")
    assert echo_entry["params"][0]["name"] == "text"
    assert echo_entry["params"][0]["type"] == "string"
    time_entry = next(e for e in mf if e["name"] == "time")
    assert time_entry["params"] == []


def test_registry_grammar_dirty_flag():
    reg = SkillRegistry()
    assert reg.grammar_dirty is False
    reg.register(TimeSkill())
    assert reg.grammar_dirty is True


# --- Tier1Qwen grammar-constrained dispatch ---

def _fake_urlopen(response_content: str):
    """Return a context manager whose .read() gives JSON content bytes."""
    body = json.dumps({"content": response_content}).encode()
    cm = MagicMock()
    cm.__enter__ = lambda s: MagicMock(read=lambda: body)
    cm.__exit__ = MagicMock(return_value=False)
    return cm


def _qwen(skills=None) -> Tier1Qwen:
    cfg = Config()
    return Tier1Qwen(cfg, skills=skills)


def test_tier1_dispatches_skill_and_runs_it():
    reg = default_registry()
    t1 = _qwen(skills=reg)
    dispatch_resp = json.dumps({"skill": "echo", "args": {"text": "hello"}})
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(dispatch_resp)):
        result = t1.handle("echo hello")
    assert result.text == "hello"
    assert result.skill == "echo"
    assert result.lane == "tier1-qwen"


def test_tier1_falls_back_to_chat_on_none_skill():
    reg = default_registry()
    t1 = _qwen(skills=reg)
    none_resp = json.dumps({"skill": "none", "args": {}})
    chat_resp = "I'm Iris, a voice assistant."
    responses = [none_resp, chat_resp]
    call_count = 0

    def fake_urlopen(req, timeout):
        nonlocal call_count
        resp = responses[call_count]
        call_count += 1
        return _fake_urlopen(resp)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = t1.handle("who are you")
    assert result.text == chat_resp
    assert result.skill is None
    assert call_count == 2


def test_tier1_allow_skills_false_skips_dispatch():
    reg = default_registry()
    t1 = _qwen(skills=reg)
    chat_resp = "Just chatting."
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(chat_resp)) as mock_open:
        result = t1.handle("hi", allow_skills=False)
    assert result.text == chat_resp
    assert result.skill is None
    # only one HTTP call — no dispatch pass
    assert mock_open.call_count == 1


def test_tier1_grammar_rebuilt_when_dirty():
    reg = SkillRegistry()
    reg.register(EchoSkill())
    t1 = _qwen(skills=reg)
    reg.grammar_dirty = True  # simulate new skill registered after init
    dispatch_resp = json.dumps({"skill": "echo", "args": {"text": "x"}})
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(dispatch_resp)):
        t1.handle("say x")
    assert t1._grammar_cache  # populated after the dispatch pass
    assert reg.grammar_dirty is False  # cleared after rebuild


# --- operator_only privilege gating (registry + lane) ---

class _PrivSkill:
    """A privileged (operator-only) skill that records whether it ran."""

    name = "secret_action"
    description = "A privileged action."
    operator_only = True
    params = [SkillParam(name="speaker", type="string", description="caller",
                         required=False, default="operator")]

    def __init__(self) -> None:
        self.ran_for: list[str] = []

    def run(self, *, speaker="operator", **_):
        self.ran_for.append(speaker)
        return f"did it for {speaker}"


def test_registry_filters_operator_only_for_far_party():
    reg = SkillRegistry([EchoSkill(), _PrivSkill()])
    # default (no speaker) and operator see everything
    assert "secret_action" in reg.names()
    assert "secret_action" in reg.names("operator")
    # far party never sees the privileged skill
    assert "secret_action" not in reg.names("far")
    assert "echo" in reg.names("far")
    far_manifest = {e["name"] for e in reg.manifest("far")}
    assert "secret_action" not in far_manifest
    assert "echo" in far_manifest


def test_grammar_omits_operator_only_skill_for_far_party():
    reg = SkillRegistry([EchoSkill(), _PrivSkill()])
    t1 = _qwen(skills=reg)
    assert "secret_action" in t1._build_grammar("operator")
    assert "secret_action" not in t1._build_grammar("far")


def test_lane_refuses_operator_only_skill_named_for_far_party():
    """Defence in depth: even if the model names a privileged skill, the lane
    must not run it for a non-operator speaker — it falls through to chat.

    A non-privileged skill is also registered so the far party still gets a
    dispatch pass (otherwise there's nothing to dispatch and the question is
    moot); the model is then made to (wrongly) name the operator-only skill."""
    priv = _PrivSkill()
    reg = SkillRegistry([EchoSkill(), priv])
    t1 = _qwen(skills=reg)
    dispatch_resp = json.dumps({"skill": "secret_action", "args": {}})
    chat_resp = "Let's just chat."
    responses = [dispatch_resp, chat_resp]
    idx = 0

    def fake_urlopen(req, timeout):
        nonlocal idx
        resp = responses[min(idx, len(responses) - 1)]
        idx += 1
        return _fake_urlopen(resp)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = t1.handle("do the secret thing", speaker="far")
    assert priv.ran_for == []          # never executed for the far party
    assert result.skill is None        # fell through to chat
    assert result.text == chat_resp


def test_lane_injects_speaker_into_skill_on_dispatch():
    """A skill declaring a ``speaker`` param receives the real channel on the
    dispatch path (so its own operator-gate works there, not just on direct calls)."""
    priv = _PrivSkill()
    reg = SkillRegistry([priv])
    t1 = _qwen(skills=reg)
    dispatch_resp = json.dumps({"skill": "secret_action", "args": {}})
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(dispatch_resp)):
        result = t1.handle("do the secret thing", speaker="operator")
    assert priv.ran_for == ["operator"]
    assert result.skill == "secret_action"
