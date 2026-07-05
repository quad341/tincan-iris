"""iris.eval_log_keygen — one-off keypair generator for the eval log store (ti-qi76c).

Run manually: ``python -m iris.eval_log_keygen``. Prints a NaCl keypair once.
Save the private half somewhere durable and offline (password manager,
printed backup) — NOT a file on this machine, and never anywhere the daemon
reads from. Only the base64 public key goes into Config.eval_log_public_key /
the IRIS_EVAL_LOG_PUBLIC_KEY env var.

This module is never imported by the daemon or any daemon-reachable code path.
Decrypting eval-log entries is an offline, operator-only operation by design —
see iris.capture.eval_log_store.EvalLogStore, which has no read/decrypt method
at all.
"""
from __future__ import annotations

import base64
import sys


def main() -> int:
    try:
        import nacl.public
    except ImportError:
        print(
            "PyNaCl is not installed — run `pip install -e '.[call-card]'` first.",
            file=sys.stderr,
        )
        return 1

    keypair = nacl.public.PrivateKey.generate()
    public_b64 = base64.b64encode(bytes(keypair.public_key)).decode("ascii")
    private_b64 = base64.b64encode(bytes(keypair)).decode("ascii")

    print("Eval log keypair generated.\n")
    print(f"Public key  (set as IRIS_EVAL_LOG_PUBLIC_KEY): {public_b64}")
    print(f"Private key (save OFFLINE — do not put this on this machine): {private_b64}\n")
    print(
        "This is the only time the private key is shown; nothing here saves it "
        "for you. Without it, no eval log entry can ever be decrypted by "
        "anyone, including you — store it somewhere durable before closing "
        "this terminal."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
