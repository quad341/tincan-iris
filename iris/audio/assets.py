"""Shared resolution for Iris's local model assets (whisper STT, kokoro TTS).

The heavy runtime assets — the per-model 3.12 venvs (``.venv-whisper``,
``.venv-kokoro``) and the downloaded models (``models/whisper/<size>``,
``models/kokoro``) — are large and were historically provisioned *per clone*
by ``scripts/setup_whisper.sh`` / ``setup_kokoro.sh``, which install under the
repo root. A second clone (or a fresh factory worktree) then starts dead until
you re-run setup or hand-point the ``IRIS_*_DIR`` / ``IRIS_*_PYTHON`` env vars
at a sibling clone's assets.

To make any clone work without per-clone provisioning, asset paths resolve with
this precedence (first hit wins):

  1. explicit ``IRIS_*_PYTHON`` / ``IRIS_*_DIR`` env var (operator override)
  2. repo-local path, if it exists      (``<repo>/.venv-whisper`` …)
  3. shared asset home, if it exists    (``$IRIS_ASSET_HOME`` or XDG
     ``~/.local/share/iris``)
  4. repo-local path (default)          — so a missing-asset error names the
     conventional location, and ``setup_*.sh`` without ``--shared`` still
     "just works"

Install once into the shared home with ``scripts/setup_whisper.sh --shared``
(likewise kokoro) and every clone resolves it via step 3. Existing per-clone
installs keep working unchanged via step 2.
"""
from __future__ import annotations

import os
from pathlib import Path


def asset_home() -> Path:
    """Shared, clone-independent root for Iris model assets.

    ``IRIS_ASSET_HOME`` overrides everything; otherwise XDG
    (``$XDG_DATA_HOME/iris``, default ``~/.local/share/iris``). The shared root
    mirrors a clone's sub-layout (``.venv-whisper``, ``models/whisper/<size>``,
    …) so resolution is a plain root swap.
    """
    override = os.environ.get("IRIS_ASSET_HOME")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / "iris"


def resolve_asset(env_var: str, rel_path: str, repo_root: Path) -> str:
    """Resolve a model-asset path: env override → repo-local → shared → default.

    ``rel_path`` is the asset's location relative to both ``repo_root`` and the
    shared :func:`asset_home` (they share the same sub-layout — e.g.
    ``.venv-whisper/bin/python`` or ``models/kokoro``). An explicit ``env_var``
    value wins outright. Otherwise prefer a repo-local copy that exists, then a
    shared copy that exists, then fall back to the repo-local path even if it is
    missing so callers' error messages point at the conventional spot.
    """
    override = os.environ.get(env_var)
    if override:
        return override
    repo_local = repo_root / rel_path
    if repo_local.exists():
        return str(repo_local)
    shared = asset_home() / rel_path
    if shared.exists():
        return str(shared)
    return str(repo_local)
