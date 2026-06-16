"""iris-arm / iris-disarm — CLI tools for out-of-band trust arming.

The running iris-console opens a Unix-domain socket at _SOCKET_PATH.
These CLI tools write a single command word to that socket and exit.

Usage:
    iris-arm [--ttl=<seconds>]
    iris-disarm

If no console is running (socket absent), both print an error and exit 1.
If the console is already armed (iris-arm), it is a no-op (idempotent).
"""
from __future__ import annotations

import argparse
import socket
import sys
from pathlib import Path

_SOCKET_PATH = Path.home() / ".local" / "run" / "iris" / "console.sock"


def _send(command: str) -> None:
    """Send a command string to the running console socket. Exits on error."""
    if not _SOCKET_PATH.exists():
        print(
            f"iris console not running (socket not found: {_SOCKET_PATH})",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(5)
            sock.connect(str(_SOCKET_PATH))
            sock.sendall((command + "\n").encode())
    except (OSError, ConnectionRefusedError) as exc:
        print(
            f"no console is running or connection refused: {exc}",
            file=sys.stderr,
        )
        sys.exit(1)


def arm_main() -> None:
    """Entry point for iris-arm."""
    parser = argparse.ArgumentParser(
        prog="iris-arm",
        description="Arm the running iris-console trust session.",
    )
    parser.add_argument(
        "--ttl",
        type=int,
        default=None,
        metavar="SECONDS",
        help="Auto-disarm after this many seconds.",
    )
    args = parser.parse_args()

    cmd = "arm"
    if args.ttl is not None:
        cmd = f"arm --ttl={args.ttl}"
    _send(cmd)


def disarm_main() -> None:
    """Entry point for iris-disarm."""
    argparse.ArgumentParser(
        prog="iris-disarm",
        description="Disarm the running iris-console trust session.",
    ).parse_args()
    _send("disarm")
