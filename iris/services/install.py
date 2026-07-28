"""iris install-services — write systemd user unit files and start the services."""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_TMPL_DIR = Path(__file__).resolve().parent
_SYSTEMD_USER = Path.home() / ".config" / "systemd" / "user"
_REPO_PATH = Path(__file__).resolve().parents[2]


@dataclass
class UnitSpec:
    name: str
    template: str
    restart_on_update: bool = True


UNITS: list[UnitSpec] = [
    UnitSpec("iris-llama",   "iris-llama.service.tmpl"),
    UnitSpec("iris-whisper", "iris-whisper.service.tmpl"),
    UnitSpec("iris-kokoro",  "iris-kokoro.service.tmpl"),
    UnitSpec("iris-brain",   "iris-brain.service.tmpl"),
]

# iris-brain.service originally ran `python -m iris.voice` (interactive REPL)
# under systemd, which exits immediately on EOF from stdin — crash-loop — so it
# was dropped from managed units and retired here. That crash-loop bug is fixed
# (iris-brain.service.tmpl now targets `python -m iris.daemon`; see the
# regression guard in _validate_exec_starts()) and the daemon is reinstated in
# UNITS above (ti-omwom). Left empty rather than deleted so a future retirement
# has a ready-made mechanism.
_RETIRED_UNITS: list[str] = []


def _python_main() -> Path:
    return _REPO_PATH / ".venv" / "bin" / "python"


def _validate_exec_starts() -> list[str]:
    """Return a list of error strings; empty means all checks passed."""
    errors: list[str] = []
    py_main = _python_main()
    py_whisper = _REPO_PATH / ".venv-whisper" / "bin" / "python"
    py_kokoro = _REPO_PATH / ".venv-kokoro" / "bin" / "python"

    for label, path in [
        ("brain .venv python", py_main),
        ("whisper .venv-whisper python", py_whisper),
        ("kokoro .venv-kokoro python", py_kokoro),
    ]:
        if not path.exists():
            errors.append(f"  ✗ {label} not found: {path}")

    if py_main.exists():
        try:
            result = subprocess.run(
                [str(py_main), "-c", "import iris"],
                capture_output=True, text=True, timeout=10, check=False,
            )
            if result.returncode != 0:
                errors.append(
                    f"  ✗ brain python cannot import iris: {result.stderr.strip()}"
                )
        except Exception as exc:
            errors.append(f"  ✗ brain python import check failed: {exc}")

    # Regression guard for the original crash-loop bug: iris-brain must launch
    # the daemon, not the old `python -m iris.voice` REPL (which exits on EOF
    # from stdin and crash-loops under systemd).
    brain_exec_start = next(
        (line for line in _render("iris-brain.service.tmpl").splitlines()
         if line.startswith("ExecStart=")),
        "",
    )
    if "-m iris.daemon" not in brain_exec_start:
        errors.append(
            f"  ✗ iris-brain.service.tmpl ExecStart does not target iris.daemon: "
            f"{brain_exec_start!r}"
        )

    return errors


def _render(template: str) -> str:
    home = str(Path.home())
    return (
        (_TMPL_DIR / template)
        .read_text()
        .replace("{REPO_PATH}", str(_REPO_PATH))
        .replace("{USER_HOME}", home)
        .replace("{PYTHON_WHISPER}", str(_REPO_PATH / ".venv-whisper" / "bin" / "python"))
        .replace("{PYTHON_KOKORO}", str(_REPO_PATH / ".venv-kokoro" / "bin" / "python"))
    )


def _run(cmd: list[str], *, dry_run: bool) -> bool:
    if dry_run:
        print(f"  [dry-run] {' '.join(cmd)}")
        return True
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError:
        return False


def _linger_enabled() -> bool:
    user = os.environ.get("USER", "")
    return (Path("/var/lib/systemd/linger") / user).exists()


def install(dry_run: bool = False, with_daemon: bool = True) -> int:
    """Install or update Iris systemd user services. Returns 0 on success, 1 on any failure.

    with_daemon=False (--no-daemon) skips installing iris-brain.service only —
    it does not stop or disable an iris-brain unit left over from a prior
    install; use `iris daemon stop` / `systemctl --user disable iris-brain`
    for that.
    """
    # Retire obsolete units FIRST — cleanup is independent of the new-install
    # preflight, so a stale/retired unit is dropped even when the venvs aren't
    # ready to install the new ones yet. _RETIRED_UNITS is empty today; the
    # mechanism is kept for the next retirement.
    if not dry_run:
        _SYSTEMD_USER.mkdir(parents=True, exist_ok=True)
        for name in _RETIRED_UNITS:
            unit = f"{name}.service"
            proc = subprocess.run(
                ["systemctl", "--user", "is-active", unit],
                capture_output=True, text=True, check=False,
            )
            if proc.returncode == 0:
                print(f"  Retiring stale unit {unit}…")
                subprocess.run(["systemctl", "--user", "stop", unit], capture_output=True, check=False)
                subprocess.run(["systemctl", "--user", "disable", unit], capture_output=True, check=False)
                unit_path = _SYSTEMD_USER / unit
                if unit_path.exists():
                    unit_path.unlink()
                    print(f"    removed {unit_path} ✓")

    if not dry_run:
        errors = _validate_exec_starts()
        if errors:
            print("\nPre-flight check FAILED — aborting install (no files written):\n", file=sys.stderr)
            for e in errors:
                print(e, file=sys.stderr)
            print(
                "\nRun scripts/setup_whisper.sh, scripts/setup_kokoro.sh, and "
                "pip install -e . in a .venv first.\n",
                file=sys.stderr,
            )
            return 1

    prefix = "[dry-run] " if dry_run else ""
    print(f"\n{prefix}Installing Iris systemd user services…\n")

    units = UNITS if with_daemon else [spec for spec in UNITS if spec.name != "iris-brain"]

    changed: list[str] = []
    failed: list[str] = []
    brain_newly_installed = False

    for spec in units:
        content = _render(spec.template)
        dest = _SYSTEMD_USER / f"{spec.name}.service"

        existing = dest.read_text() if dest.exists() else None
        if existing == content:
            print(f"  Writing {dest}    ✓ (unchanged)")
        else:
            if dry_run:
                print(f"  [dry-run] Writing {dest}")
            else:
                dest.write_text(content)
                label = "(updated)" if existing else ""
                print(f"  Writing {dest}    ✓ {label}".rstrip())
            changed.append(spec.name)
            if spec.name == "iris-brain" and existing is None:
                brain_newly_installed = True

    print()

    if not changed:
        print("All services already up to date. No daemon-reload needed.\n")
        print("Note: tincand.service is managed separately — see the tincand project.")
        return 0

    print(f"  {prefix}Running: systemctl --user daemon-reload")
    if not _run(["systemctl", "--user", "daemon-reload"], dry_run=dry_run):
        print("  daemon-reload FAILED")
        return 1
    print("  ✓")

    print("\n  Enabling and starting services…")
    for spec in units:
        if spec.name not in changed:
            print(f"    {spec.name}    skipped (unchanged)")
            continue
        ok_enable = _run(["systemctl", "--user", "enable", spec.name], dry_run=dry_run)
        ok_start = _run(["systemctl", "--user", "start", spec.name], dry_run=dry_run)
        if ok_enable and ok_start:
            print(f"    {spec.name}    enabled + started ✓")
        else:
            print(f"    {spec.name}    FAILED")
            print(f"      journalctl --user -u {spec.name} -n 20   ← run this to diagnose")
            failed.append(spec.name)

    print("\n  Services installed. Run 'iris doctor' to verify health.\n")
    print("  Note: tincand.service is managed separately — see the tincand project.")

    if brain_newly_installed:
        print(
            "\n  ℹ  iris-brain was newly enabled — it has outbound network access\n"
            "     (no IPAddressDeny) for optional cloud Tier 2 (Haiku) calls,\n"
            "     calendar, and web-search APIs. Opt out next time with --no-daemon."
        )

    if not _linger_enabled() and not dry_run:
        user = os.environ.get("USER", "$USER")
        print(
            f"\n  ⚠  linger not enabled — services will stop on logout.\n"
            f"     To keep them running across sessions:\n"
            f"       loginctl enable-linger {user}"
        )

    return 1 if failed else 0
