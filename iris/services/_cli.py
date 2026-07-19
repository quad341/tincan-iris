"""Entry point for `iris install-services`."""
from __future__ import annotations

import argparse

from .install import install


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="iris-install-services",
        description="Write systemd user unit files and start the Iris services.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without writing files or running systemctl.",
    )
    parser.add_argument(
        "--no-daemon",
        action="store_true",
        help="Skip installing iris-brain.service (the always-on call-handling daemon).",
    )
    try:
        args = parser.parse_args()
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    kwargs: dict[str, bool] = {"dry_run": args.dry_run}
    if args.no_daemon:
        kwargs["with_daemon"] = False
    return install(**kwargs)
