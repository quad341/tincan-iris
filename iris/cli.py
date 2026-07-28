"""A text REPL to exercise the brain before voice I/O exists.

    python -m iris.cli        # or, once installed:  iris-chat

Type a line; Iris responds, and the per-lane latency is printed so the timing
budget stays visible while we build. If a lane lags, randomized filler lines
appear (the text stand-in for the spoken "umm, one sec"); if it blows the
deadline she falls back gracefully. Requires a local llama-server (see
``iris/config.py``).
"""
from __future__ import annotations

import sys

from .brain import Brain
from .fillers import filler_picker


def main() -> int:
    brain = Brain()
    pick = filler_picker()
    print("Iris brain REPL — type a message (Ctrl-D to quit).")
    examples = brain.tier0.examples()
    print("Try: " + " · ".join(examples[:5]) + ' · or "what can you do" for the full list.')
    print("(I'm an AI.)\n")
    while True:
        try:
            text = input("you › ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye!")
            brain.close()
            return 0
        if not text:
            continue
        try:
            reply = brain.respond(
                text, on_filler=lambda i: print(f"iris … ({pick()})", flush=True)
            )
        except Exception as exc:  # REPL: surface errors, don't crash
            print(f"iris ✗ {type(exc).__name__}: {exc}\n")
            continue
        tag = reply.lane + (f"/{reply.skill}" if reply.skill else "")
        print(f"iris › {reply.text}")
        print(f"      ⟮{tag} · {reply.timeline.summary()}⟯\n")


if __name__ == "__main__":
    sys.exit(main())
