"""Entry point for `iris install-services`."""
from __future__ import annotations

import sys

from .install import install


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    return install(dry_run=dry_run)
