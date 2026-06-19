"""Tests for iris.audio.assets — shared model-asset resolution.

Precedence: explicit env override → repo-local (if it exists) → shared asset
home (if it exists) → repo-local default. These let any clone work without
per-clone provisioning while keeping existing per-clone installs unchanged.
"""
from __future__ import annotations

from pathlib import Path

from iris.audio.assets import asset_home, resolve_asset


def test_env_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("IRIS_WHISPER_DIR", "/explicit/override")
    # repo-local exists, but the explicit env var still wins
    (tmp_path / "models" / "whisper").mkdir(parents=True)
    assert resolve_asset("IRIS_WHISPER_DIR", "models/whisper", tmp_path) == "/explicit/override"


def test_repo_local_used_when_present(monkeypatch, tmp_path):
    monkeypatch.delenv("IRIS_WHISPER_DIR", raising=False)
    rel = "models/whisper/small.en"
    (tmp_path / rel).mkdir(parents=True)
    assert resolve_asset("IRIS_WHISPER_DIR", rel, tmp_path) == str(tmp_path / rel)


def test_shared_used_when_repo_local_absent(monkeypatch, tmp_path):
    monkeypatch.delenv("IRIS_WHISPER_DIR", raising=False)
    repo = tmp_path / "repo"
    shared = tmp_path / "shared"
    rel = "models/whisper/small.en"
    (shared / rel).mkdir(parents=True)        # only the shared copy exists
    monkeypatch.setenv("IRIS_ASSET_HOME", str(shared))
    assert resolve_asset("IRIS_WHISPER_DIR", rel, repo) == str(shared / rel)


def test_repo_local_wins_over_shared_when_both_exist(monkeypatch, tmp_path):
    monkeypatch.delenv("IRIS_KOKORO_DIR", raising=False)
    repo = tmp_path / "repo"
    shared = tmp_path / "shared"
    rel = "models/kokoro"
    (repo / rel).mkdir(parents=True)
    (shared / rel).mkdir(parents=True)
    monkeypatch.setenv("IRIS_ASSET_HOME", str(shared))
    # backward-compat: an existing per-clone install keeps being used
    assert resolve_asset("IRIS_KOKORO_DIR", rel, repo) == str(repo / rel)


def test_falls_back_to_repo_local_default_when_nothing_exists(monkeypatch, tmp_path):
    monkeypatch.delenv("IRIS_WHISPER_PYTHON", raising=False)
    monkeypatch.setenv("IRIS_ASSET_HOME", str(tmp_path / "shared-empty"))
    repo = tmp_path / "repo"
    rel = ".venv-whisper/bin/python"
    # nothing exists anywhere -> repo-local default, for a clean "run setup" error
    assert resolve_asset("IRIS_WHISPER_PYTHON", rel, repo) == str(repo / rel)


def test_asset_home_iris_asset_home_override(monkeypatch):
    monkeypatch.setenv("IRIS_ASSET_HOME", "/custom/assets")
    assert asset_home() == Path("/custom/assets")


def test_asset_home_xdg(monkeypatch):
    monkeypatch.delenv("IRIS_ASSET_HOME", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", "/xdg/data")
    assert asset_home() == Path("/xdg/data/iris")


def test_asset_home_default(monkeypatch):
    monkeypatch.delenv("IRIS_ASSET_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert asset_home() == Path.home() / ".local" / "share" / "iris"
