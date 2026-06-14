"""``python -m iris.console`` — boots the Textual operator console."""
from __future__ import annotations

import sys


def main() -> int:
    try:
        from .app import main as run
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.split(".")[0] == "textual":
            print("The console needs Textual:  pip install --user textual")
            print("(or, with the project:  pip install -e '.[console]')")
            return 1
        raise
    return run()


if __name__ == "__main__":
    sys.exit(main())
