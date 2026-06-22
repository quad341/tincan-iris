"""Entry point for `iris install-services`."""
from __future__ import annotations

import argparse
import sys

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
    try:
        args = parser.parse_args()
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1
    return install(dry_run=args.dry_run)
