"""``iris up`` — one-command stack bring-up.

Ensures whisper+kokoro are running (starts them via systemctl if needed),
checks llama is reachable on :8080 (operator-managed; warns but does not block),
checks tincand reachability (optional; warns but does not block), then hands
off to the console.

Llama is intentionally NOT started here — the operator shares a single llama
instance across multiple tools; starting a competing one would break things.
"""
from __future__ import annotations

import sys
import time
import urllib.request
import subprocess


_MANAGED_SERVICES = ["iris-whisper", "iris-kokoro"]
_LLAMA_URL = "http://127.0.0.1:8080/health"
_TINCAND_URL = "http://127.0.0.1:9001/health"
_HEALTH_TIMEOUT = 5.0


def _is_active(unit: str) -> bool:
    try:
        proc = subprocess.run(
            ["systemctl", "--user", "is-active", f"{unit}.service"],
            capture_output=True, text=True,
        )
        return proc.returncode == 0
    except OSError:
        return False


def _start_service(unit: str) -> bool:
    print(f"  Starting {unit}…", end="", flush=True)
    try:
        proc = subprocess.run(
            ["systemctl", "--user", "start", f"{unit}.service"],
            capture_output=True, text=True,
        )
        if proc.returncode == 0:
            print(" ✓")
            return True
        print(f" FAILED (exit {proc.returncode})")
        print(f"    journalctl --user -u {unit} -n 20   ← diagnose")
        return False
    except OSError as exc:
        print(f" FAILED ({exc})")
        return False


def _health_ok(url: str, timeout: float = _HEALTH_TIMEOUT) -> bool:
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url), timeout=timeout
        ) as resp:
            return resp.status < 400
    except Exception:  # noqa: BLE001
        return False


def _wait_healthy(url: str, label: str, retries: int = 6, delay: float = 2.0) -> bool:
    for attempt in range(retries):
        if _health_ok(url):
            return True
        if attempt < retries - 1:
            print(f"  {label}: waiting for health endpoint…", end="\r")
            time.sleep(delay)
    return False


def bring_up(*, launch_console: bool = True) -> int:
    """Ensure services are ready, then optionally launch the console. Returns 0 on success."""
    print("\niris up — bringing the stack online\n")

    # 1. Managed services: whisper + kokoro (start if not active)
    failed: list[str] = []
    for svc in _MANAGED_SERVICES:
        if _is_active(svc):
            print(f"  {svc}: already active ✓")
        else:
            if not _start_service(svc):
                failed.append(svc)

    if failed:
        print(f"\n✗ Required services failed to start: {', '.join(failed)}")
        print("  Run 'iris doctor' to diagnose.\n")
        return 1

    # 2. Llama — operator-managed; check reachability, warn but don't block.
    print("  checking iris-llama (:8080)…", end="", flush=True)
    if _health_ok(_LLAMA_URL):
        print(" ✓")
    else:
        print(" not reachable")
        print("    ⚠ llama-server is not running on :8080 — Iris brain needs it.")
        print("      Start it manually before using Iris.  (Iris will launch but won't respond.)")

    # 3. Tincand — optional; warn if absent.
    print("  checking tincand (:9001)…", end="", flush=True)
    if _health_ok(_TINCAND_URL):
        print(" ✓")
    else:
        print(" not reachable (optional — needed only for phone calls)")

    print()

    if not launch_console:
        return 0

    from iris.console.app import main as console_main
    return console_main()


def main() -> int:
    return bring_up(launch_console=True)
