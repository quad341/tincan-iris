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
    assert names == {"time"}
    time_entry = next(e for e in mf if e["name"] == "time")
    assert time_entry["params"] == []

    # EchoSkill class still works; it's just not in the default registry
    echo_reg = SkillRegistry([EchoSkill()])
    echo_mf = echo_reg.manifest()
    echo_entry = next(e for e in echo_mf if e["name"] == "echo")
    assert echo_entry["params"][0]["name"] == "text"
    assert echo_entry["params"][0]["type"] == "string"


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


def test_tier1_proposes_skill_for_the_daemon_to_run():
    # The lane proposes (ADR-0005 §4); the daemon authorizes + runs it. Execution
    # and the permission gate are covered in test_permission_gate.py.
    # Use an explicit registry with EchoSkill — it's no longer in default_registry.
    reg = SkillRegistry([EchoSkill()])
    t1 = _qwen(skills=reg)
    dispatch_resp = json.dumps({"skill": "echo", "args": {"text": "hello"}})
    with patch("urllib.request.urlopen", return_value=_fake_urlopen(dispatch_resp)):
        result = t1.handle("echo hello")
    assert result.proposal is not None
    assert result.proposal.skill == "echo"
    assert result.proposal.args == {"text": "hello"}
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
    assert t1._grammar_cache is not None
    assert reg.grammar_dirty is False  # cleared after rebuild
