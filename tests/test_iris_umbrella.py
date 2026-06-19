"""Tests for the ``iris`` umbrella dispatcher (iris/__main__.py)."""
from __future__ import annotations

import sys
from unittest.mock import patch

from iris import __main__ as cli


def test_help_lists_commands(capsys):
    rc = cli.main(["--help"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "iris auth" in out
    assert "iris doctor" in out
    assert "iris console" in out


def test_no_args_prints_usage(capsys):
    rc = cli.main([])
    assert rc == 0
    assert "usage: iris" in capsys.readouterr().out


def test_unknown_command_errors(capsys):
    rc = cli.main(["frobnicate"])
    assert rc == 2
    assert "unknown command" in capsys.readouterr().err


def test_dispatches_to_target_main():
    with patch("iris.doctor.main", return_value=0) as m:
        rc = cli.main(["doctor"])
    m.assert_called_once()
    assert rc == 0


def test_forwards_nested_args_via_argv():
    seen = {}

    def fake_auth_main():
        seen["argv"] = list(sys.argv)
        return 0

    with patch("iris.auth.main", side_effect=fake_auth_main):
        rc = cli.main(["auth", "gcal", "/tmp/x.json"])
    assert rc == 0
    # iris.auth:main reads sys.argv[1:] -> must see just its own args
    assert seen["argv"] == ["iris auth", "gcal", "/tmp/x.json"]


def test_restores_sys_argv():
    before = list(sys.argv)
    with patch("iris.doctor.main", return_value=0):
        cli.main(["doctor", "--whatever"])
    assert sys.argv == before


def test_non_int_return_is_zero():
    # a target main that returns None (e.g. the TUIs) -> exit code 0
    with patch("iris.email_check.main", return_value=None):
        assert cli.main(["email-check"]) == 0
