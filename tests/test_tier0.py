"""The Tier-0 command table exposes (name, example) pairs for the console's
command dump. Also covers SkillRegistry manifest + param schema."""
from __future__ import annotations

from iris.lanes import Tier0Rules
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
