"""ci_driftwatch — detect main-CI drift with no new commit (ti-4tq52).

ruff 0.16.0 (2026-07-23) broke `ruff check .` repo-wide with zero commits to
main; GitHub Actions has no reason to re-evaluate an already-merged tip
without a trigger, so main's CI can go silently red for days. This script
pairs with a `schedule:` cron trigger added to .github/workflows/ci.yml: each
tick it asks whether the latest schedule-triggered run is still at the same
commit last observed and, if so, whether it's still failing. A single
transient runner flake is ruled out with one automatic rerun before anything
pages a human. See ti-pcqj4 for the full design (state machine, trade-offs).

Env vars:
  GC_CITY_ROOT           city root for gc bd/mail invocations (cwd is `/`
                         under systemd, so this can't be inferred from cwd —
                         passed as subprocess cwd=, matching main-ci-watcher)
  XDG_STATE_HOME         overrides where the state file lives (tests only;
                         defaults to ~/.local/state)
  CI_DRIFTWATCH_DRY_RUN  "1" skips gc bd/mail/notify-fanout side effects

Unlike sibling main-ci-watcher, a `gh` CLI failure here is treated as a
script-level failure (non-zero exit, trips systemd OnFailure=) rather than
being swallowed — this watcher covers exactly one repo, so there's no other
repo to protect from one bad call, and a broken `gh` should be loud.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time
from datetime import UTC, datetime

REPO = "quad341/tincan-iris"
RIG = "tincan-iris"
BRANCH = "main"
WORKFLOW = "ci.yml"
CHECK_NAME = "test"  # the sole job in ci.yml; matches the GitHub check-run name

FAILED_CONCLUSIONS = {"failure", "cancelled", "timed_out", "action_required"}

SCHEDULE_INTERVAL_SECONDS = 6 * 60 * 60  # matches the `17 */6 * * *` cron
STALE_THRESHOLD_SECONDS = 2 * SCHEDULE_INTERVAL_SECONDS  # FR-8

POLL_INTERVAL_SECONDS = 15
MAX_POLL_ATTEMPTS = 40  # ~10 minutes, roughly one CI run's duration

CITY = pathlib.Path(os.environ.get("GC_CITY_ROOT", os.getcwd()))
DRY_RUN = os.environ.get("CI_DRIFTWATCH_DRY_RUN") == "1"

STATE_DIR = pathlib.Path(
    os.environ.get("XDG_STATE_HOME", str(pathlib.Path.home() / ".local" / "state"))
)
STATE_FILE = STATE_DIR / "ci-driftwatch" / "state.json"


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def load_state() -> dict | None:
    if not STATE_FILE.exists():
        return None
    try:
        return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))


def gh_json(args: list[str]):
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    out = result.stdout.strip()
    if not out:
        return None
    return json.loads(out)


def latest_schedule_run() -> dict | None:
    data = gh_json([
        "gh", "run", "list",
        "--repo", REPO,
        "--workflow", WORKFLOW,
        "--branch", BRANCH,
        "--event", "schedule",
        "--limit", "1",
        "--json", "databaseId,headSha,conclusion,status,createdAt,url",
    ])
    if not isinstance(data, list) or not data:
        return None
    return data[0]


def trigger_rerun(run_id) -> None:
    subprocess.run(
        ["gh", "run", "rerun", str(run_id), "--failed", "--repo", REPO],
        capture_output=True, text=True, check=True,
    )


def poll_until_complete(run_id) -> tuple[str, bool]:
    for _ in range(MAX_POLL_ATTEMPTS):
        data = gh_json([
            "gh", "run", "view", str(run_id), "--repo", REPO,
            "--json", "status,conclusion",
        ])
        if isinstance(data, dict) and data.get("status") == "completed":
            return data.get("conclusion") or "", True
        time.sleep(POLL_INTERVAL_SECONDS)
    return "", False


def _extract_bead_id(stdout: str) -> str:
    for line in stdout.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("created"):
            for token in stripped.split():
                if "-" in token and token.replace("-", "").isalnum():
                    return token
    return ""


def file_bead(sha: str, conclusion: str, run_url: str) -> str | None:
    """File a P1 bead in RIG and sling to <RIG>/investigator.

    Returns the new bead id on success, None on failure. Title contract
    matches sibling main-ci-watcher: "main CI red: {check} on {repo}".
    """
    title = f"main CI red: {CHECK_NAME} on {REPO}"
    description = "\n".join([
        f"Schedule-triggered CI on `{REPO}`'s `{BRANCH}` branch is red with",
        "no new commit since the last observation — push-triggered CI (and",
        "main-ci-watcher) can't see this, since nothing pushed to re-run it.",
        "",
        f"- check: `{CHECK_NAME}`",
        f"- conclusion: `{conclusion}`",
        f"- sha (unchanged since last observation): `{sha}`",
        f"- run url: {run_url}" if run_url else "- run url: (none)",
        "",
        "Filed by ci_driftwatch.py (ti-4tq52). Confirmed via one automatic",
        "rerun before filing — not a single-shot flake.",
    ])

    if DRY_RUN:
        sys.stdout.write(f"[dry-run] would file bead: {title}\n")
        return "dry-run"

    try:
        create = subprocess.run(
            ["gc", "bd", "--rig", RIG, "create",
             "--title", title, "--description", description,
             "--type", "bug", "--priority", "p1"],
            capture_output=True, text=True, check=True, cwd=str(CITY),
        )
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(f"[ci-driftwatch] bd create failed: {exc.stderr.strip()[:300]}\n")
        return None

    new_id = _extract_bead_id(create.stdout)
    if not new_id:
        sys.stderr.write(
            f"[ci-driftwatch] bd create succeeded but could not parse id from: {create.stdout!r}\n"
        )
        return None

    try:
        subprocess.run(
            ["gc", "sling", f"{RIG}/investigator", new_id],
            capture_output=True, text=True, check=True, cwd=str(CITY),
        )
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(f"[ci-driftwatch] gc sling failed for {new_id}: {exc.stderr.strip()[:300]}\n")
        return new_id

    # Per sling-leave-assignee-blank precedent (main-ci-watcher): clear
    # assignee so the worker hook query finds the bead via gc.routed_to.
    subprocess.run(
        ["gc", "bd", "--rig", RIG, "update", new_id, "--assignee="],
        capture_output=True, text=True, check=False, cwd=str(CITY),
    )
    return new_id


def send_mail_alert(subject: str, body: str) -> bool:
    if DRY_RUN:
        sys.stdout.write(f"[dry-run] would gc mail send mayor: {subject}\n")
        return True
    try:
        subprocess.run(
            ["gc", "mail", "send", "mayor", "-s", subject, "-m", body],
            capture_output=True, text=True, check=True, cwd=str(CITY),
        )
        return True
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(f"[ci-driftwatch] gc mail send failed: {exc.stderr.strip()[:300]}\n")
        return False


def send_desktop_alert(urgency: str, title: str, body: str) -> bool:
    if DRY_RUN:
        sys.stdout.write(f"[dry-run] would notify-fanout {urgency}: {title}\n")
        return True
    try:
        subprocess.run(
            ["notify-fanout", urgency, title, body],
            capture_output=True, text=True, check=True,
        )
        return True
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(f"[ci-driftwatch] notify-fanout failed: {exc.stderr.strip()[:300]}\n")
        return False


def _fresh_state(now: datetime) -> dict:
    return {
        "repo": REPO,
        "branch": BRANCH,
        "last_checked_sha": None,
        "last_conclusion": None,
        "last_schedule_run_id": None,
        "last_schedule_run_seen_at": None,
        "alerted_for_sha": False,
        "alerted_at": None,
        "rerun_issued_for_sha": None,
        "stale_alerted": False,
        "updated_at": now.isoformat(),
    }


def bootstrap(latest: dict | None, now: datetime) -> dict:
    state = _fresh_state(now)
    if latest is not None:
        state["last_schedule_run_id"] = latest.get("databaseId")
        state["last_schedule_run_seen_at"] = now.isoformat()
        if latest.get("status") == "completed":
            state["last_checked_sha"] = latest.get("headSha")
            state["last_conclusion"] = latest.get("conclusion") or ""
    save_state(state)
    return state


def check_staleness(state: dict, latest: dict | None, now: datetime) -> bool:
    """True if a stale-schedule condition should alert on this tick (FR-8)."""
    reference = _parse_iso(latest["createdAt"]) if latest is not None else _parse_iso(state["updated_at"])
    age_seconds = (now - reference).total_seconds()
    if age_seconds <= STALE_THRESHOLD_SECONDS:
        return False
    return not state.get("stale_alerted")


def _fire_stale_alert(now: datetime) -> bool:
    subject = f"ci-driftwatch: no recent schedule-triggered CI run observed on {REPO}"
    body = (
        f"No schedule-triggered CI run on {REPO}/{BRANCH} newer than "
        f"{STALE_THRESHOLD_SECONDS // 3600}h was observed as of {now.isoformat()}. "
        "The schedule: trigger itself may have stopped firing."
    )
    mail_ok = send_mail_alert(subject, body)
    fanout_ok = send_desktop_alert("normal", "CI drift-watch: schedule may be stalled", body)
    return mail_ok and fanout_ok


def run(now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    had_failure = False

    state = load_state()
    if state is None:
        bootstrap(latest_schedule_run(), now)
        return 0

    latest = latest_schedule_run()

    if check_staleness(state, latest, now):
        had_failure = had_failure or not _fire_stale_alert(now)
        state["stale_alerted"] = True
    elif latest is not None and (now - _parse_iso(latest["createdAt"])).total_seconds() <= STALE_THRESHOLD_SECONDS:
        state["stale_alerted"] = False

    if latest is None:
        state["updated_at"] = now.isoformat()
        save_state(state)
        return 1 if had_failure else 0

    state["last_schedule_run_id"] = latest.get("databaseId")
    state["last_schedule_run_seen_at"] = now.isoformat()

    if latest.get("status") != "completed":
        state["updated_at"] = now.isoformat()
        save_state(state)
        return 1 if had_failure else 0

    sha = latest["headSha"]
    conclusion = latest.get("conclusion") or ""
    run_url = latest.get("url", "")

    if sha != state.get("last_checked_sha"):
        state["last_checked_sha"] = sha
        state["last_conclusion"] = conclusion
        state["alerted_for_sha"] = False
        state["rerun_issued_for_sha"] = None
        state["updated_at"] = now.isoformat()
        save_state(state)
        return 1 if had_failure else 0

    if conclusion not in FAILED_CONCLUSIONS:
        state["last_conclusion"] = conclusion
        state["alerted_for_sha"] = False
        state["rerun_issued_for_sha"] = None
        state["updated_at"] = now.isoformat()
        save_state(state)
        return 1 if had_failure else 0

    # Same sha, still failing.
    if state.get("alerted_for_sha"):
        state["updated_at"] = now.isoformat()
        save_state(state)
        return 1 if had_failure else 0

    if state.get("rerun_issued_for_sha") != sha:
        trigger_rerun(latest["databaseId"])
        state["rerun_issued_for_sha"] = sha
        confirmed_conclusion, completed = poll_until_complete(latest["databaseId"])
        if not completed:
            state["updated_at"] = now.isoformat()
            save_state(state)
            return 1 if had_failure else 0
        effective_conclusion = confirmed_conclusion or ""
    else:
        effective_conclusion = conclusion

    if effective_conclusion not in FAILED_CONCLUSIONS:
        state["alerted_for_sha"] = False
        state["last_conclusion"] = effective_conclusion
        state["updated_at"] = now.isoformat()
        save_state(state)
        return 1 if had_failure else 0

    # Confirmed real drift — one flake-ruling-out rerun still failed.
    bead_id = file_bead(sha, effective_conclusion, run_url)
    subject = f"main CI red: {CHECK_NAME} on {REPO}"
    body = (
        f"Schedule-triggered CI is red with no new commit on {REPO}/{BRANCH}.\n"
        f"check: {CHECK_NAME}\nconclusion: {effective_conclusion}\nsha: {sha}\n"
        f"run: {run_url}\nbead: {bead_id or '(bead filing failed)'}"
    )
    mail_ok = send_mail_alert(subject, body)
    fanout_ok = send_desktop_alert("critical", subject, body)
    if not (bool(bead_id) and mail_ok and fanout_ok):
        had_failure = True

    state["alerted_for_sha"] = True
    state["alerted_at"] = now.isoformat()
    state["last_conclusion"] = effective_conclusion
    state["updated_at"] = now.isoformat()
    save_state(state)
    return 1 if had_failure else 0


def main() -> int:
    try:
        return run()
    except Exception as exc:  # gh/JSON failures are fatal by design — see ti-pcqj4
        sys.stderr.write(f"[ci-driftwatch] fatal: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
