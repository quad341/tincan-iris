import re
from pathlib import Path

CI_YML = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"


def _install_step_block():
    lines = CI_YML.read_text().splitlines()
    start = next(i for i, l in enumerate(lines) if "Install package" in l and "test deps" in l)
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("- name:")),
        len(lines),
    )
    return "\n".join(lines[start:end])


def test_ruff_is_pinned_to_an_exact_version():
    block = _install_step_block()
    assert re.search(r"ruff==\d+\.\d+(\.\d+)?", block), (
        f"ruff must be pinned to an exact version (ruff==X.Y.Z) in the CI "
        f"install step, got:\n{block}"
    )


def test_ruff_pin_has_rationale_and_followup_bead_referenced():
    block = _install_step_block()
    assert "#" in block, "expected a comment explaining the ruff pin"
    assert re.search(r"\bti-[a-z0-9]{4,}\b", block), (
        "expected the pin's comment to reference a follow-up bead id (ti-xxxxx)"
    )
