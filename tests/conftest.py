"""Shared fixtures — isolate on-disk store singletons from the real $HOME.

CallCardStore, RosterStore, AfterStore, TranscriptStore, NotesStore,
PreferencesStore, and PostureManager all default to real, persistent paths
under ~/.local/share/iris/* when constructed with zero args (see each
module's own _DEFAULT_PATH / _DEFAULT_DB). IrisConsole.__init__ constructs
several of these bare, so every test that builds a plain IrisConsole() or
Store() shares real on-disk state — with the user's actual data, with other
tests, and (in this gc-rig factory setup) with other concurrent sessions
sharing the same $HOME. See ti-c4z98.

Below, monkeypatch the module-level constants directly rather than relying
on each store's optional path= param, so the ~30+ existing bare-construction
call sites are fixed retroactively with no per-test changes.

Two modules (iris.capture.after_store, iris.list_store, iris.proactive_store)
import another module's _DEFAULT_PATH under a local alias at import time
(e.g. `from iris.roster import _DEFAULT_PATH as _ROSTER_DB`) to share one
on-disk file for foreign-key/relational reasons. Patching the origin
module's constant does not retroactively change that alias — it's a
separate name bound once at import time — so each alias is patched here too,
to the *same* tmp_path file as the module it mirrors.

iris.daemon.__main__'s own singleton lock path (_PID_PATH) is a different
hazard: it's resolved once at import time from
_socket_path.daemon_pid_path(), which defaults to $XDG_RUNTIME_DIR/iris/ — a
per-*user*, not per-worktree, directory. A real concurrently-running daemon
process on the same machine holds this via a real fcntl.flock, so any test
that calls daemon_main.main() must not share it either (this is the exact
collision ti-c4z98 caught live: "another instance holds the lock").
"""
from __future__ import annotations

from pathlib import Path

import pytest

from iris import list_store, notes, prefs, proactive_store, roster, transcript
from iris.capture import after_store
from iris.capture import store as capture_store
from iris.daemon import __main__ as daemon_main
from iris.daemon import posture as daemon_posture


@pytest.fixture(autouse=True)
def _isolate_default_store_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    roster_db = tmp_path / "roster.db"
    transcripts_db = tmp_path / "transcripts.db"

    monkeypatch.setattr(capture_store, "_DEFAULT_DB", tmp_path / "call_cards.db")
    monkeypatch.setattr(roster, "_DEFAULT_PATH", roster_db)
    monkeypatch.setattr(transcript, "_DEFAULT_PATH", transcripts_db)
    monkeypatch.setattr(notes, "_DEFAULT_PATH", tmp_path / "notes.json")
    monkeypatch.setattr(prefs, "_DEFAULT_PATH", tmp_path / "prefs.json")
    monkeypatch.setattr(daemon_posture, "_DEFAULT_PATH", roster_db)
    monkeypatch.setattr(daemon_main, "_DEFAULT_DB", roster_db)

    # Import-time aliases — see module docstring above.
    monkeypatch.setattr(after_store, "_ROSTER_DB", roster_db)
    monkeypatch.setattr(list_store, "_TRANSCRIPT_DB", transcripts_db)
    monkeypatch.setattr(proactive_store, "_TRANSCRIPT_DB", transcripts_db)

    # Daemon exclusivity lock — see module docstring above.
    monkeypatch.setattr(daemon_main, "_PID_PATH", tmp_path / "daemon.pid")
