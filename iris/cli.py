"""A text REPL to exercise the brain before voice I/O exists.

    python -m iris.cli        # or, once installed:  iris-chat

Type a line; Iris responds, and the per-lane latency is printed so the timing
budget stays visible while we build. If a lane is slow, a filler line appears
first (the text stand-in for the spoken "umm, one sec"). Requires a local
llama-server running at the configured URL (see ``iris/config.py``).
"""
from __future__ import annotations

import sys

from .brain import Brain


def main() -> int:
    brain = Brain()
    print("Iris brain REPL — type a message (Ctrl-D to quit).")
    print("(I'm an AI. Local Qwen must be serving at the configured URL.)\n")
    while True:
        try:
            text = input("you › ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye!")
            brain.close()
            return 0
        if not text:
            continue

        def on_filler() -> None:
            print("iris … (umm, one sec)", flush=True)

        try:
            reply = brain.respond(text, on_filler=on_filler)
        except Exception as exc:  # noqa: BLE001 — REPL: surface errors, don't crash
            print(f"iris ✗ {type(exc).__name__}: {exc}\n")
            continue
        tag = reply.lane + (f"/{reply.skill}" if reply.skill else "")
        print(f"iris › {reply.text}")
        print(f"      ⟮{tag} · {reply.timeline.summary()}⟯\n")


if __name__ == "__main__":
    sys.exit(main())
