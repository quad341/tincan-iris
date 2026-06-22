"""``iris`` — one umbrella entrypoint that dispatches to the per-feature mains.

``iris <command> [args...]`` routes to the same functions the individual
``iris-*`` console scripts use (which stay as back-compat aliases). Nested
commands like ``iris auth gcal`` forward the remaining argv to the target.
``python -m iris <command>`` works too.
"""
from __future__ import annotations

import importlib
import sys

# command -> "module:function".  Order here is the order shown in --help.
_COMMANDS: dict[str, str] = {
    "up": "iris.up:main",
    "doctor": "iris.doctor:main",
    "home": "iris.console.home:main",
    "console": "iris.console.app:main",
    "chat": "iris.cli:main",
    "auth": "iris.auth:main",                 # nested: auth gmail | auth gcal
    "email-check": "iris.email_check:main",
    "listen": "iris.listen:main",
    "speak": "iris.voice:main",
    "arm": "iris.console.arm:arm_main",
    "disarm": "iris.console.arm:disarm_main",
    "install-services": "iris.services._cli:main",
    "whisper-server": "iris._whisper_server:main",
    "kokoro-server": "iris._kokoro_server:main",
}


def _usage() -> str:
    lines = "\n".join(f"  iris {name}" for name in _COMMANDS)
    return (
        "usage: iris <command> [args...]\n\n"
        f"commands:\n{lines}\n\n"
        "Run 'iris <command> --help' for command-specific options "
        "(e.g. 'iris auth gcal').\n"
    )


def _resolve(spec: str):
    module_name, _, func_name = spec.partition(":")
    return getattr(importlib.import_module(module_name), func_name)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help", "help"):
        sys.stdout.write(_usage())
        return 0
    command, rest = args[0], args[1:]
    spec = _COMMANDS.get(command)
    if spec is None:
        sys.stderr.write(f"iris: unknown command {command!r}\n\n{_usage()}")
        return 2
    func = _resolve(spec)
    # Reshape argv so the target's own parser sees just its args under a sensible
    # prog name, then restore — works whether the target reads sys.argv or accepts
    # an argv list (e.g. `iris auth gcal` -> iris.auth:main sees ["gcal"]).
    saved = sys.argv
    try:
        sys.argv = [f"iris {command}", *rest]
        result = func()
    finally:
        sys.argv = saved
    return result if isinstance(result, int) else 0


if __name__ == "__main__":
    raise SystemExit(main())
