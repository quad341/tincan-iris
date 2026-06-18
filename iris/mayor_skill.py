"""mayor_skill — delegate operator requests to the gascity mayor for triage.

iris as a LIGHT front door into the city: the operator can ask iris to hand a
task to the mayor, and check for the mayor's replies. Deliberately minimal —
this is NOT a full gascity client (see bead ti-h9di); it is two skills plus a
thin mail channel, nothing more.

  DelegateToMayorSkill   — send a request to the mayor (``gc mail send mayor``).
  CheckMayorRepliesSkill — poll iris's mailbox for replies from the mayor.

Transport is the ``gc mail`` CLI, a *direct* API (per ADR-0001 — no MCP server,
no marketplace surface). iris sends with ``--from iris`` and reads
``gc mail inbox iris`` so the mayor's replies land in a stable mailbox named
``iris`` (the alias is configurable). This is the chosen answer to "how does
iris *receive* from the mayor": an explicit poll over a dedicated mailbox. The
receive path here is a manual check ("any word from the mayor?"); auto-polling
and surfacing replies in the out-of-call console dashboard is the ti-6qsb
(out-of-call experience) integration, intentionally out of scope for this crack.

FULL-trust / operator-channel only: delegating to the city is a privileged
action. Rely on Brain.respond()'s ``allow_skills=not demo_mode`` gate (as the
SMS/email skills do) and do not register these on a far-party-reachable path.

Usage (inject via the brain's skill registry, mirroring messages_skill):
    ch = MayorChannel()
    for s in mayor_skills(ch):
        brain.skills.register(s)
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

from .skills import SkillParam

_MAYOR = "mayor"
_DEFAULT_ALIAS = "iris"


@dataclass
class MayorReply:
    sender: str
    subject: str
    body: str
    id: str = ""


class MayorChannel:
    """Thin wrapper over the ``gc mail`` CLI for talking to the mayor.

    Sends are attributed to ``alias`` (``--from``) and replies are read from that
    same mailbox (``gc mail inbox <alias>``), so the conversation has a stable
    identity. CLI/timeout errors propagate to the skill layer, which turns them
    into a spoken line rather than crashing the brain.
    """

    def __init__(self, alias: str = _DEFAULT_ALIAS, gc_bin: str = "gc",
                 timeout_s: float = 15.0) -> None:
        self.alias = alias
        self.gc_bin = gc_bin
        self.timeout_s = timeout_s

    def _run(self, args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [self.gc_bin, "mail", *args],
            capture_output=True, text=True, timeout=self.timeout_s,
        )

    def send(self, subject: str, body: str, *, notify: bool = True) -> bool:
        """Send a message to the mayor. Returns True on a zero exit code."""
        args = ["send", _MAYOR, "-s", subject, "-m", body, "--from", self.alias]
        if notify:
            args.append("--notify")
        return self._run(args).returncode == 0

    def replies_from_mayor(self) -> list[MayorReply]:
        """Return unread inbox messages whose sender is the mayor."""
        cp = self._run(["inbox", self.alias, "--json"])
        if cp.returncode != 0 or not cp.stdout.strip():
            return []
        try:
            data = json.loads(cp.stdout)
        except json.JSONDecodeError:
            return []
        if isinstance(data, dict):
            msgs = data.get("messages", [])
        elif isinstance(data, list):
            msgs = data
        else:
            msgs = []
        out: list[MayorReply] = []
        for m in msgs:
            if not isinstance(m, dict):
                continue
            sender = str(m.get("sender") or m.get("from") or "")
            if _MAYOR not in sender.lower():
                continue
            out.append(MayorReply(
                sender=sender,
                subject=str(m.get("subject") or m.get("summary") or ""),
                body=str(m.get("body") or m.get("text") or ""),
                id=str(m.get("id") or ""),
            ))
        return out


class DelegateToMayorSkill:
    """Hand a task/question to the city's mayor for triage."""

    name = "delegate_to_mayor"
    description = (
        "Hand a task or question to the city's mayor for triage (e.g. 'ask the "
        "mayor to look into the red CI'). Operator-only; sends mail to the mayor."
    )
    params: list[SkillParam] = [
        SkillParam(
            name="request",
            type="string",
            description="What to ask the mayor to do or look into.",
        ),
        SkillParam(
            name="subject",
            type="string",
            description="Optional short subject; a summary is derived if omitted.",
            required=False,
            default="",
        ),
    ]

    def __init__(self, channel: MayorChannel) -> None:
        self._ch = channel

    def run(self, *, request: str = "", subject: str = "", **_kwargs: object) -> str:
        request = request.strip()
        if not request:
            return "What would you like me to ask the mayor?"
        subj = subject.strip() or _summarize(request)
        try:
            ok = self._ch.send(subj, request)
        except Exception as exc:  # noqa: BLE001 — degrade to a spoken line
            return f"I couldn't reach the city mail: {exc}"
        if ok:
            return f'Sent to the mayor — "{subj}". I\'ll let you know when there\'s a reply.'
        return "I couldn't send that to the mayor just now."


class CheckMayorRepliesSkill:
    """Check for replies from the city's mayor."""

    name = "mayor_replies"
    description = "Check for replies from the city's mayor."
    params: list[SkillParam] = []

    def __init__(self, channel: MayorChannel) -> None:
        self._ch = channel

    def run(self, **_kwargs: object) -> str:
        try:
            replies = self._ch.replies_from_mayor()
        except Exception as exc:  # noqa: BLE001 — degrade to a spoken line
            return f"I couldn't check the city mail: {exc}"
        if not replies:
            return "No replies from the mayor yet."
        lines = []
        for r in replies:
            head = r.subject or "(no subject)"
            body = r.body[:200] + ("…" if len(r.body) > 200 else "")
            lines.append(f"Mayor — {head}: {body}")
        return "\n".join(lines)


def _summarize(text: str, limit: int = 60) -> str:
    """Collapse whitespace and trim to a one-line subject."""
    one = " ".join(text.split())
    return one if len(one) <= limit else one[:limit].rstrip() + "…"


def mayor_skills(channel: MayorChannel | None = None) -> list:
    """Return the mayor-delegation skills, backed by a MayorChannel."""
    ch = channel or MayorChannel()
    return [DelegateToMayorSkill(ch), CheckMayorRepliesSkill(ch)]
