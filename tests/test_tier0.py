"""The Tier-0 command table exposes (name, example) pairs for the console's
command dump."""
from __future__ import annotations

from iris.lanes import Tier0Rules
from iris.skills import default_registry


def test_commands_lists_name_example_pairs():
    cmds = dict(Tier0Rules(default_registry()).commands())
    assert {"introduce", "time", "stop"} <= set(cmds)
    assert cmds["time"]            # has an example phrasing
    assert cmds["introduce"]


def test_commands_match_examples():
    t0 = Tier0Rules(default_registry())
    assert [ex for _n, ex in t0.commands()] == t0.examples()
