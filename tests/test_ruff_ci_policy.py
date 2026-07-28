import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CI_YAML = REPO_ROOT / ".github" / "workflows" / "ci.yml"
VALID_PATHS = {"fix-and-unpin", "adopt-deliberately", "permanent-pin"}


def _ci_yaml_text():
    return CI_YAML.read_text()


def _declared_ruff_spec():
    """Extract the ruff install spec (e.g. 'ruff' or 'ruff==0.15.22') ci.yml uses."""
    match = re.search(r"pip install[^\n]*?\b(ruff(?:==[\w.]+)?)\b", _ci_yaml_text())
    assert match, "ci.yml has no 'pip install ... ruff' line to inspect"
    return match.group(1)


def test_ci_yaml_declares_ruff_policy():
    match = re.search(r"#\s*ruff-policy:\s*(\S+)\s*--\s*\S", _ci_yaml_text())
    assert match, (
        "ci.yml must document the deliberately-chosen ruff-0.16.0 resolution "
        "path via a '# ruff-policy: <path> -- <rationale>' comment"
    )
    chosen = match.group(1)
    assert chosen in VALID_PATHS, (
        f"ruff-policy {chosen!r} is not one of the sanctioned paths: {sorted(VALID_PATHS)}"
    )


def test_declared_ruff_invocation_passes_clean():
    """Runs the exact ruff spec ci.yml installs, not whatever is cached locally.

    An ambient/pre-cached ruff install can mask CI drift (an unpinned or
    stale-pinned ruff in ci.yml passing locally while a fresh CI install
    would fail) -- this is what let ruff 0.16.0's new default rules break
    CI unnoticed. Route through uvx so the version actually matches what
    ci.yml's install step would resolve to.
    """
    spec = _declared_ruff_spec()
    version = spec.split("==")[1] if "==" in spec else "latest"
    result = subprocess.run(
        ["uvx", f"ruff@{version}", "check", "."],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"ruff@{version} check . (the exact spec ci.yml installs) did not pass "
        f"clean:\n{result.stdout}\n{result.stderr}"
    )
