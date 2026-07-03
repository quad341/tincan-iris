"""Unix socket path resolution for the iris daemon (ADR-0006).

Precedence:
  1. $IRIS_DAEMON_SOCK (explicit override)
  2. $XDG_RUNTIME_DIR/iris/daemon.sock
  3. ~/.local/run/iris/daemon.sock  (XDG default)
"""
from __future__ import annotations

import os
from pathlib import Path

_IRIS_DAEMON_SOCK = "IRIS_DAEMON_SOCK"


def daemon_socket_path() -> Path:
    """Return the canonical path for the daemon's Unix socket."""
    env = os.environ.get(_IRIS_DAEMON_SOCK)
    if env:
        return Path(env)
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return Path(runtime) / "iris" / "daemon.sock"
    return Path.home() / ".local" / "run" / "iris" / "daemon.sock"


def daemon_pid_path() -> Path:
    """Return the canonical path for the daemon's exclusivity lock/pid file.

    Always derived from daemon_socket_path() — same directory, same
    precedence — so the lock and the socket it guards can never drift to
    different scopes again.
    """
    return daemon_socket_path().with_name("daemon.pid")
