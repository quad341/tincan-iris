"""``iris up`` — one-command stack bring-up.

Ensures whisper+kokoro are running (starts them via systemctl if needed),
checks llama is reachable on :8080 (operator-managed; warns but does not block),
starts tincand if inactive and waits for readiness (optional; reports status
but does not block on failure), then hands off to the console.

Llama is intentionally NOT started here — the operator shares a single llama
instance across multiple tools; starting a competing one would break things.
"""
from __future__ import annotations

import time
import urllib.request
import subprocess


_MANAGED_SERVICES = ["iris-whisper", "iris-kokoro"]
_LLAMA_URL = "http://127.0.0.1:8080/health"
_TINCAND_URL = "http://127.0.0.1:9001/health"
_HEALTH_TIMEOUT = 5.0
_TINCAND_UNIT = "tincand.service"
_TINCAND_WAIT_S = 10
_DBUS_RETRIES = 3
_DBUS_RETRY_DELAY = 0.5


def _is_active(unit: str) -> bool:
    try:
        proc = subprocess.run(
            ["systemctl", "--user", "is-active", f"{unit}.service"],
            capture_output=True, text=True,
        )
        return proc.returncode == 0
    except OSError:
        return False


def _unit_known(unit: str) -> bool:
    """Return False when systemd reports the unit as not found (exit 4)."""
    try:
        proc = subprocess.run(
            ["systemctl", "--user", "is-active", unit],
            capture_output=True, text=True,
        )
        return proc.returncode != 4
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


def _tincand_dbus_status() -> dict:
    import dbus  # noqa: PLC0415
    bus = dbus.SessionBus()
    obj = bus.get_object("im.tincan.Daemon", "/im/tincan")
    iface = dbus.Interface(obj, "im.tincan.Daemon")
    return {str(k): v for k, v in dict(iface.GetStatus()).items()}


def _bring_up_tincand() -> dict:
    """Start tincand if inactive, wait for health, poll D-Bus for readiness.

    Returns dict with keys: health, connected, adapter_warning, call_setup_ready,
    device_discovered, reason ('ok'|'start-timeout'|'unit-absent'|'dbus-error').
    """
    base: dict = {
        "health": False,
        "connected": False,
        "adapter_warning": "",
        "call_setup_ready": False,
        "device_discovered": False,
        "reason": "ok",
    }

    if not _unit_known(_TINCAND_UNIT):
        base["reason"] = "unit-absent"
        return base

    if not _is_active("tincand"):
        proc = subprocess.run(
            ["systemctl", "--user", "start", _TINCAND_UNIT],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            base["reason"] = "unit-absent"
            return base

    for _ in range(_TINCAND_WAIT_S):
        if _health_ok(_TINCAND_URL, timeout=1.0):
            base["health"] = True
            break
        time.sleep(1.0)
    else:
        base["reason"] = "start-timeout"
        return base

    for _ in range(_DBUS_RETRIES):
        try:
            st = _tincand_dbus_status()
            base["call_setup_ready"] = bool(st.get("call_setup_ready"))
            base["adapter_warning"] = str(st.get("adapter_warning") or "")
            base["connected"] = bool(st.get("connected"))
            base["device_discovered"] = bool(st.get("device_discovered"))
            base["reason"] = "ok"
            return base
        except Exception:  # noqa: BLE001
            time.sleep(_DBUS_RETRY_DELAY)

    base["reason"] = "dbus-error"
    return base


def _print_tincand_readiness(result: dict) -> None:
    reason = result["reason"]
    if reason == "unit-absent":
        print("  tincand: not installed (optional — needed only for phone calls)")
        return

    if reason == "start-timeout":
        print("  tincand: ✗ did not respond within 10s")
        print("    Run: journalctl --user -u tincand.service -n 20")
        print("    tincand is optional — iris will start without it")
        return

    if reason == "dbus-error":
        print("  tincand: ⚠ health OK but D-Bus unavailable — degraded (calls may not work)")
        return

    warn = result.get("adapter_warning") or ""
    if warn:
        print(f"  tincand: ✗ BT adapter mismatch: {warn}")
        connected = result.get("connected")
        hci_note = " (connect iPhone to USB dongle for call audio)" if not connected else ""
        print(f"  ⟳ iPhone {'connected' if connected else 'not connected'}{hci_note}")
    else:
        selinux = "✓ SELinux" if result.get("call_setup_ready") else "⚠ SELinux (not loaded)"
        connected = result.get("connected")
        iphone = "✓ iPhone connected" if connected else "⟳ iPhone not connected"
        print(f"  tincand: ✓ HFP daemon, ✓ BT adapter, {selinux}, {iphone}")


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

    # 3. Tincand — optional; start if inactive, wait for readiness, report status.
    print("  checking tincand…", end="", flush=True)
    tincand_result = _bring_up_tincand()
    print()  # newline after the "checking tincand…" line
    _print_tincand_readiness(tincand_result)

    print()

    if not launch_console:
        return 0

    from iris.console.app import main as console_main
    return console_main()


def main() -> int:
    return bring_up(launch_console=True)
