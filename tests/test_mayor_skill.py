"""Tests for mayor_skill — iris -> mayor delegation (ti-h9di)."""
from __future__ import annotations

import json
from unittest import mock

from iris.mayor_skill import (
    CheckMayorRepliesSkill,
    DelegateToMayorSkill,
    MayorChannel,
    MayorReply,
    _summarize,
    mayor_skills,
)


class _FakeChannel:
    """In-memory MayorChannel stand-in for skill-level tests."""

    def __init__(self, send_ok=True, replies=None, raise_on=None):
        self.send_ok = send_ok
        self._replies = replies or []
        self.raise_on = raise_on or set()
        self.sent: list[tuple[str, str]] = []

    def send(self, subject, body, *, notify=True):
        if "send" in self.raise_on:
            raise RuntimeError("boom")
        self.sent.append((subject, body))
        return self.send_ok

    def replies_from_mayor(self):
        if "replies" in self.raise_on:
            raise RuntimeError("boom")
        return list(self._replies)


# --- DelegateToMayorSkill ---------------------------------------------------

def test_delegate_empty_request_prompts():
    out = DelegateToMayorSkill(_FakeChannel()).run(request="")
    assert "ask the mayor" in out.lower()


def test_delegate_sends_and_acks():
    ch = _FakeChannel(send_ok=True)
    out = DelegateToMayorSkill(ch).run(request="look into the red CI on gascity main")
    assert ch.sent and ch.sent[0][1] == "look into the red CI on gascity main"
    assert "mayor" in out.lower()


def test_delegate_derives_subject_when_omitted():
    ch = _FakeChannel()
    DelegateToMayorSkill(ch).run(request="please triage the deploy backlog")
    subj = ch.sent[0][0]
    assert subj and len(subj) <= 61


def test_delegate_uses_explicit_subject():
    ch = _FakeChannel()
    DelegateToMayorSkill(ch).run(request="x", subject="Deploy backlog")
    assert ch.sent[0][0] == "Deploy backlog"


def test_delegate_send_failure_message():
    out = DelegateToMayorSkill(_FakeChannel(send_ok=False)).run(request="hi")
    assert "couldn't send" in out.lower()


def test_delegate_channel_exception_is_graceful():
    out = DelegateToMayorSkill(_FakeChannel(raise_on={"send"})).run(request="hi")
    assert "couldn't reach" in out.lower()


# --- CheckMayorRepliesSkill -------------------------------------------------

def test_replies_none():
    assert "no replies" in CheckMayorRepliesSkill(_FakeChannel(replies=[])).run().lower()


def test_replies_formatted():
    r = MayorReply(sender="mayor", subject="CI", body="looking into it")
    out = CheckMayorRepliesSkill(_FakeChannel(replies=[r])).run()
    assert "CI" in out and "looking into it" in out


def test_replies_truncates_long_body():
    r = MayorReply(sender="mayor", subject="s", body="x" * 500)
    assert "…" in CheckMayorRepliesSkill(_FakeChannel(replies=[r])).run()


def test_replies_exception_is_graceful():
    out = CheckMayorRepliesSkill(_FakeChannel(raise_on={"replies"})).run()
    assert "couldn't check" in out.lower()


# --- _summarize -------------------------------------------------------------

def test_summarize_short_passthrough():
    assert _summarize("hello there") == "hello there"


def test_summarize_truncates():
    out = _summarize("word " * 50, limit=20)
    assert len(out) <= 21 and out.endswith("…")


# --- mayor_skills factory ---------------------------------------------------

def test_factory_returns_both_skills():
    names = {s.name for s in mayor_skills(_FakeChannel())}
    assert names == {"delegate_to_mayor", "mayor_replies"}


# --- MayorChannel (mock subprocess) -----------------------------------------

def _cp(returncode=0, stdout=""):
    return mock.Mock(returncode=returncode, stdout=stdout, stderr="")


def test_channel_send_builds_argv():
    with mock.patch("iris.mayor_skill.subprocess.run", return_value=_cp(0)) as run:
        ok = MayorChannel(alias="iris").send("Subj", "Body")
    assert ok is True
    argv = run.call_args[0][0]
    assert argv[:3] == ["gc", "mail", "send"]
    assert "mayor" in argv and "--from" in argv and "iris" in argv
    assert "-s" in argv and "Subj" in argv and "-m" in argv and "Body" in argv


def test_channel_replies_parses_and_filters():
    payload = json.dumps({"messages": [
        {"id": "1", "sender": "mayor", "subject": "re: ci", "body": "on it"},
        {"id": "2", "sender": "someone-else", "subject": "spam", "body": "hi"},
    ], "ok": True})
    with mock.patch("iris.mayor_skill.subprocess.run", return_value=_cp(0, payload)):
        replies = MayorChannel().replies_from_mayor()
    assert len(replies) == 1
    assert replies[0].sender == "mayor" and replies[0].subject == "re: ci"


def test_channel_replies_handles_nonzero_and_nonjson():
    with mock.patch("iris.mayor_skill.subprocess.run", return_value=_cp(1, "")):
        assert MayorChannel().replies_from_mayor() == []
    with mock.patch("iris.mayor_skill.subprocess.run", return_value=_cp(0, "not json")):
        assert MayorChannel().replies_from_mayor() == []


def test_channel_replies_reads_iris_mailbox():
    with mock.patch("iris.mayor_skill.subprocess.run", return_value=_cp(0, '{"messages":[]}')) as run:
        MayorChannel(alias="iris").replies_from_mayor()
    argv = run.call_args[0][0]
    assert argv == ["gc", "mail", "inbox", "iris", "--json"]
