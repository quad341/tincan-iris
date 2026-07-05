"""iris doctor — health-check CLI for Iris's setup assets + systemd services.

Two layers, because they fail at different times:

  * **Assets** (:func:`check_assets`) — the setup layer the console resolves on
    startup: the whisper STT and kokoro TTS venvs + models. This is the most
    common first-run / fresh-clone failure (``python -m iris.console`` dies
    before any service exists). Reuses the providers' own path resolution so
    what the doctor reports is exactly what the runtime will use.
  * **Services** (:func:`check_services`) — the runtime layer: the systemd
    user units (llama/whisper/kokoro/brain/tincand) and their /health endpoints.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from . import settings
from .config import DEFAULT


class DoctorStatus(Enum):
    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"
    ABSENT = "absent"
    UNKNOWN = "unknown"


_SYMBOL = {
    DoctorStatus.OK:       "✓",
    DoctorStatus.DEGRADED: "!",
    DoctorStatus.DOWN:     "✗",
    DoctorStatus.ABSENT:   "–",
    DoctorStatus.UNKNOWN:  "?",
}


@dataclass
class ServiceDescriptor:
    name: str
    unit: str
    health_url: str | None
    required: bool = True
    deep_check: object = None


@dataclass
class ServiceCheckResult:
    name: str
    unit: str
    status: DoctorStatus
    required: bool
    note: str = ""
    round_trip_ms: float | None = None
    sentinel_hint: bool = False
    deep_lines: list[str] = field(default_factory=list)


@dataclass
class AssetCheckResult:
    name: str
    status: DoctorStatus
    required: bool
    detail: str = ""   # short, table-friendly (resolved path, or what's missing)
    fix: str = ""       # full remediation; shown in the Setup block, not the table


def _tincand_get_status() -> dict:
    import dbus  # noqa: PLC0415
    bus = dbus.SessionBus()
    obj = bus.get_object("im.tincan.Daemon", "/im/tincan")
    iface = dbus.Interface(obj, "im.tincan.Daemon")
    return {str(k): v for k, v in dict(iface.GetStatus()).items()}


def _tincand_deep_check(svc_name: str, unit: str) -> list[str]:  # noqa: ARG001
    lines: list[str] = []

    try:
        with urllib.request.urlopen(
            urllib.request.Request("http://127.0.0.1:9001/health"), timeout=2
        ) as resp:
            data = json.loads(resp.read())
        lines.append("✓ health endpoint" if _health_ready(data) else "✗ health endpoint (not ready)")
    except (urllib.error.URLError, OSError, ValueError):
        lines.append("✗ health endpoint (unreachable)")

    try:
        st = _tincand_get_status()
        if st.get("call_setup_ready"):
            lines.append("✓ SELinux loaded")
        else:
            lines.append("✗ SELinux NOT loaded — run: sudo semodule -i /usr/share/tincan/tincan.pp")
        warn = str(st.get("adapter_warning") or "")
        if warn:
            lines.append(f"✗ BT adapter mismatch: {warn}")
        else:
            lines.append("✓ adapter correct")
        connected = bool(st.get("connected"))
        lines.append(f"⟳ iPhone {'connected' if connected else 'not connected'} (informational)")
    except Exception as exc:  # noqa: BLE001
        lines.append(f"? D-Bus GetStatus() unavailable: {exc}")

    return lines


EXPECTED_SERVICES: list[ServiceDescriptor] = [
    ServiceDescriptor("iris-llama",   "iris-llama.service",   "http://127.0.0.1:8080/health", required=True),
    ServiceDescriptor("iris-whisper", "iris-whisper.service", "http://127.0.0.1:8082/health", required=True),
    ServiceDescriptor("iris-kokoro",  "iris-kokoro.service",  "http://127.0.0.1:8083/health", required=True),
    ServiceDescriptor("tincand",      "tincand.service",      "http://127.0.0.1:9001/health",  required=False, deep_check=_tincand_deep_check),
]


def _health_ready(data: object) -> bool:
    """Interpret a /health JSON body across server flavors.

    Accepts iris's own ``{"ready": true}`` and llama.cpp's ``{"status": "ok"}``;
    any other valid-JSON 200 body counts as ready (it answered). Only an explicit
    not-ready signal (``ready: false`` / a non-ok ``status``) is treated as down.
    """
    if isinstance(data, dict):
        if "ready" in data:
            return bool(data["ready"])
        if "status" in data:
            return str(data["status"]).lower() in ("ok", "ready", "healthy", "up", "200")
    return True


def check_services(
    services: list[ServiceDescriptor],
    *,
    timeout_s: float = 2.0,
    deep: bool = False,
) -> list[ServiceCheckResult]:
    results: list[ServiceCheckResult] = []
    for svc in services:
        # 1. systemd unit state (a managed unit is the common case)
        try:
            proc = subprocess.run(
                ["systemctl", "--user", "is-active", svc.unit],
                capture_output=True,
                text=True,
            )
            unit = {0: "active", 4: "absent"}.get(proc.returncode, "down")
        except OSError:
            unit = "unknown"

        # 2. probe the health endpoint if one exists — independent of the unit,
        #    so a server run by hand (e.g. a bare llama.cpp on :8080) still counts.
        health: bool | None = None
        rtt_ms: float | None = None
        if svc.health_url:
            try:
                t0 = time.monotonic()
                with urllib.request.urlopen(urllib.request.Request(svc.health_url), timeout=timeout_s) as resp:
                    data = json.loads(resp.read())
                if deep:
                    rtt_ms = (time.monotonic() - t0) * 1000
                health = _health_ready(data)
            except (urllib.error.URLError, OSError, ValueError):
                health = False

        # 3. combine — a healthy port wins, managed or not.
        note = ""
        if health is True:
            status = DoctorStatus.OK
            if unit == "absent":
                note = "running (no systemd unit)"
            elif unit != "active":
                note = "running (unit inactive)"
        elif unit == "active":
            status = DoctorStatus.DEGRADED if svc.health_url else DoctorStatus.OK
        elif unit == "absent":
            status = DoctorStatus.ABSENT
        elif unit == "down":
            status = DoctorStatus.DOWN
        else:
            status = DoctorStatus.UNKNOWN

        sentinel = svc.name == "tincand" and status == DoctorStatus.DOWN
        result = ServiceCheckResult(svc.name, svc.unit, status, svc.required, note=note, round_trip_ms=rtt_ms, sentinel_hint=sentinel)
        if deep and callable(svc.deep_check):
            try:
                result.deep_lines = svc.deep_check(svc.name, svc.unit)
            except Exception as exc:  # noqa: BLE001
                result.deep_lines = [f"? deep check error: {exc}"]
        results.append(result)

    return results


def _exit_code(results: list[ServiceCheckResult]) -> int:
    code = 0
    for r in results:
        if not r.required:
            continue
        if r.status == DoctorStatus.DOWN:
            code = max(code, 2)
        elif r.status == DoctorStatus.DEGRADED:
            code = max(code, 1)
    return code


def _missing(*pairs: tuple[str, str]) -> list[str]:
    """Return the labels whose paths don't exist (for a short 'missing: …' detail)."""
    return [label for label, path in pairs if not Path(path).exists()]


def _daemon_python() -> str:
    """Return the interpreter the iris-brain unit runs, else this one.

    Parsed from the unit's ExecStart so the enrichment check probes the env
    that actually executes PostCallEnricher. iris-brain
    (iris-services/iris-brain.service.tmpl) isn't auto-installed by
    `iris-install-services` today (ti-2fiv dropped daemon units from the
    managed set) — until an operator installs it by hand, this falls through
    to sys.executable, same as any other unmatched unit.
    """
    try:
        r = subprocess.run(
            ["systemctl", "--user", "show", "-p", "ExecStart", "--value", "iris-brain"],
            capture_output=True, text=True, timeout=5,
        )
        m = re.search(r"path=(\S+)", r.stdout)
        if m and Path(m.group(1)).exists():
            return m.group(1)
    except Exception:  # noqa: BLE001 — fall through to this interpreter
        pass
    return sys.executable


def _daemon_path() -> str | None:
    """Return the PATH the iris-brain unit's Environment= sets, else None.

    None means "no unit-specific override found" — callers fall back to
    shutil.which's own default (this process's PATH), same spirit as
    _daemon_python's fallback-to-self behavior.
    """
    try:
        r = subprocess.run(
            ["systemctl", "--user", "show", "-p", "Environment", "--value", "iris-brain"],
            capture_output=True, text=True, timeout=5,
        )
        m = re.search(r"PATH=(\S+)", r.stdout)
        if m:
            return m.group(1)
    except Exception:  # noqa: BLE001 — fall through to shutil.which's default
        pass
    return None


def check_assets() -> list[AssetCheckResult]:
    """Check the local model assets the console/voice loop resolves at startup.

    Instantiates the real providers so resolution (env override → repo-local →
    shared XDG home; see ``iris/audio/assets.py``) matches the runtime exactly,
    then reports each via its own ``.available()``. Never raises — a provider
    import/instantiation failure is reported as UNKNOWN so the doctor still runs.
    """
    results: list[AssetCheckResult] = []

    # --- Whisper STT — the console's ears. Required: the console has no text
    #     fallback for input, so a missing whisper venv/model is a hard failure.
    try:
        from .audio.stt import FasterWhisperSTT
        stt = FasterWhisperSTT()
        if stt.available():
            results.append(AssetCheckResult("whisper-stt", DoctorStatus.OK, True, detail=stt.model))
        else:
            miss = _missing(("venv", stt.python), ("model", stt.model))
            results.append(AssetCheckResult(
                "whisper-stt", DoctorStatus.DOWN, True,
                detail="missing: " + ("+".join(miss) or "transcribe worker"),
                fix="scripts/setup_whisper.sh  (add --shared to serve every clone)  "
                    "OR set IRIS_WHISPER_DIR=<…/models/whisper/SIZE> "
                    "IRIS_WHISPER_PYTHON=<…/.venv-whisper/bin/python>"))
    except Exception as e:  # noqa: BLE001 — doctor must survive a broken provider
        results.append(AssetCheckResult("whisper-stt", DoctorStatus.UNKNOWN, True, detail=str(e)))

    # --- Kokoro TTS — the natural voice. Not required: espeak-ng is the
    #     automatic fallback, so a miss is DEGRADED (robotic), not DOWN.
    try:
        from .audio.tts import KokoroTTS
        tts = KokoroTTS()
        if tts.available():
            results.append(AssetCheckResult("kokoro-tts", DoctorStatus.OK, False, detail=tts.model))
        else:
            miss = _missing(("venv", tts.python), ("model", tts.model), ("voices", tts.voices))
            results.append(AssetCheckResult(
                "kokoro-tts", DoctorStatus.DEGRADED, False,
                detail="missing: " + ("+".join(miss) or "synth worker") + " (espeak-ng fallback)",
                fix="scripts/setup_kokoro.sh  (add --shared to serve every clone)  "
                    "OR set IRIS_KOKORO_DIR=<…/models/kokoro> "
                    "IRIS_KOKORO_PYTHON=<…/.venv-kokoro/bin/python>"))
    except Exception as e:  # noqa: BLE001
        results.append(AssetCheckResult("kokoro-tts", DoctorStatus.UNKNOWN, False, detail=str(e)))

    # --- call-card L3 enrichment deps — pydantic (ti-0c90n / ti-pkt2r.1).
    #     Probed with the DAEMON's interpreter, not this one: the daemon runs
    #     on system python and skipping enrichment there is exactly the silent
    #     gap the doctor exists to catch. Optional: L1 capture works without
    #     it, so a miss is DEGRADED (facts arrive uncontextualized), not DOWN.
    daemon_python = _daemon_python()
    try:
        probe = subprocess.run(
            [daemon_python, "-c", "import pydantic"],
            capture_output=True, text=True, timeout=20,
        )
        if probe.returncode == 0:
            results.append(AssetCheckResult(
                "call-card-enrichment", DoctorStatus.OK, False,
                detail=f"pydantic importable by {daemon_python}"))
        else:
            results.append(AssetCheckResult(
                "call-card-enrichment", DoctorStatus.DEGRADED, False,
                detail=f"L3 enrichment deps missing for {daemon_python} — "
                       "every call ends with 'enrichment skipped'",
                fix=f"{daemon_python} -m pip install --user 'pydantic>=2'"))
    except Exception as e:  # noqa: BLE001
        results.append(AssetCheckResult(
            "call-card-enrichment", DoctorStatus.UNKNOWN, False, detail=str(e)))

    # --- call-card L3 tmux/claude resolution (ti-pkt2r.1). The daemon's warm
    #     ClaudeTuiSession needs both on ITS PATH — a systemd user unit's
    #     minimal default env often lacks them even when an interactive shell
    #     has them. Probed against the same Environment=PATH= the unit itself
    #     would resolve from. Optional, same reasoning as the check above.
    daemon_path = _daemon_path()
    for exe, check_name in (("tmux", "call-card-tmux"), ("claude", "call-card-claude")):
        found = shutil.which(exe, path=daemon_path)
        if found:
            results.append(AssetCheckResult(
                check_name, DoctorStatus.OK, False, detail=f"resolved: {found}"))
        else:
            results.append(AssetCheckResult(
                check_name, DoctorStatus.DEGRADED, False,
                detail=f"{exe} not found on the daemon unit's PATH — Call Card "
                       "LLM passes can't start the warm session",
                fix=f"add {exe}'s directory to iris-brain.service.tmpl's "
                    f"Environment=PATH=, or install {exe} where the daemon can see it"))

    # --- espeak-ng — the zero-setup fallback TTS. OK if on PATH.
    if shutil.which("espeak-ng"):
        results.append(AssetCheckResult("espeak-ng", DoctorStatus.OK, False, detail="fallback TTS present"))
    else:
        results.append(AssetCheckResult(
            "espeak-ng", DoctorStatus.ABSENT, False,
            detail="fallback TTS not installed",
            fix="install espeak-ng (your package manager) for a no-setup voice fallback"))

    return results


def _asset_exit_code(results: list[AssetCheckResult]) -> int:
    code = 0
    for r in results:
        if not r.required:
            continue
        if r.status in (DoctorStatus.DOWN, DoctorStatus.ABSENT):
            code = max(code, 2)
        elif r.status == DoctorStatus.DEGRADED:
            code = max(code, 1)
    return code


def _sco_advisory() -> str | None:
    """When IRIS_AUDIO rides live call audio, warn if no SCO node is present yet.

    The bluez HFP/SCO PipeWire nodes only exist *during* an active call, so a
    console launched before the call connects can't find them — the #1 gotcha.
    Returns a one-line advisory, or None when not applicable / nodes are present.
    """
    if settings.get("IRIS_AUDIO", "").lower() not in ("tincan-sco", "sco"):
        return None
    try:
        from .audio.endpoint import discover_sco_nodes
        sink, _source = discover_sco_nodes()
    except Exception:  # noqa: BLE001 — advisory only
        sink = None
    if sink:
        return None
    return ("IRIS_AUDIO=tincan-sco but no SCO sink found — the bluez nodes only exist "
            "during an active call. Launch the console AFTER the call connects.")


def doctor_main(args: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="iris doctor")
    parser.add_argument("--fix", action="store_true", help="restart DOWN services")
    parser.add_argument("--json", action="store_true", help="output JSON")
    parser.add_argument("--check", metavar="NAME", help="narrow to one asset or service")
    parser.add_argument("--deep", action="store_true", help="add round-trip check")
    ns = parser.parse_args(args if args is not None else sys.argv[1:])

    services = list(EXPECTED_SERVICES)
    assets = check_assets()
    if ns.check:
        services = [s for s in services if s.name == ns.check]
        assets = [a for a in assets if a.name == ns.check]

    # --check tincand auto-runs deep check even without --deep
    run_deep = ns.deep or ns.check == "tincand"
    timeout_s = DEFAULT.doctor_deep_timeout_s if run_deep else DEFAULT.doctor_timeout_s
    results = check_services(services, timeout_s=timeout_s, deep=run_deep)
    exit_code = max(_exit_code(results), _asset_exit_code(assets))

    if ns.json:
        tincand_detail = None
        if run_deep and any(r.name == "tincand" for r in results):
            try:
                st = _tincand_get_status()
                tincand_detail = {
                    "call_setup_ready": bool(st.get("call_setup_ready")),
                    "adapter_warning": str(st.get("adapter_warning") or ""),
                    "connected": bool(st.get("connected")),
                    "device_discovered": bool(st.get("device_discovered")),
                }
            except Exception:  # noqa: BLE001
                pass

        def _svc_entry(r: ServiceCheckResult) -> dict:
            entry: dict = {
                "name": r.name, "status": r.status.value, "required": r.required,
                "round_trip_ms": r.round_trip_ms, "sentinel_hint": r.sentinel_hint,
            }
            if r.name == "tincand" and tincand_detail is not None:
                entry["tincand_detail"] = tincand_detail
            return entry

        print(json.dumps({
            "config": {
                "path": str(settings.config_path()),
                "found": settings.config_path().exists(),
                "home": str(settings.iris_home()),
            },
            "assets": [
                {"name": a.name, "status": a.status.value, "required": a.required,
                 "detail": a.detail}
                for a in assets
            ],
            "services": [_svc_entry(r) for r in results],
            "exit_code": exit_code,
        }))
        return exit_code

    cols = shutil.get_terminal_size().columns

    cfg_path = settings.config_path()
    cfg_src = "loaded" if cfg_path.exists() else "not found — built-in defaults + env"
    print(f"config: {cfg_path}  ({cfg_src})")
    print()

    if assets:
        print("Assets")
        print(f"{'Asset':<14} {'Status':<12} {'Req':<5} Detail")
        print("-" * min(cols, 72))
        for a in assets:
            sym = _SYMBOL[a.status]
            req_str = "yes" if a.required else "no"
            print(f"{a.name:<14} {sym + ' ' + a.status.value:<12} {req_str:<5} {a.detail}".rstrip())
        print()
        print("Services")

    show_rtt = ns.deep
    show_notes = cols >= (84 if show_rtt else 72)

    if show_rtt:
        if show_notes:
            print(f"{'Service':<22} {'Status':<12} {'Req':<5} {'Round-trip':<12} Notes")
            print("-" * min(cols, 78))
        else:
            print(f"{'Service':<22} {'Status':<12} {'Req':<5} {'Round-trip':<12}")
            print("-" * 51)
    elif show_notes:
        print(f"{'Service':<22} {'Status':<12} {'Req':<5} Notes")
        print("-" * min(cols, 65))
    else:
        print(f"{'Service':<22} {'Status':<12} {'Req':<5}")
        print("-" * 39)

    for r in results:
        sym = _SYMBOL[r.status]
        req_str = "yes" if r.required else "no"
        status_cell = f"{sym} {r.status.value}"
        if show_rtt:
            rtt_cell = f"{r.round_trip_ms:.0f}ms" if r.round_trip_ms is not None else "—"
            if show_notes:
                print(f"{r.name:<22} {status_cell:<12} {req_str:<5} {rtt_cell:<12} {r.note}".rstrip())
            else:
                print(f"{r.name:<22} {status_cell:<12} {req_str:<5} {rtt_cell:<12}".rstrip())
        elif show_notes:
            print(f"{r.name:<22} {status_cell:<12} {req_str:<5} {r.note}".rstrip())
        else:
            print(f"{r.name:<22} {status_cell:<12} {req_str:<5}".rstrip())

    for r in results:
        if r.deep_lines:
            for line in r.deep_lines:
                print(f"  {line}")
            print()

    if ns.fix:
        for r in results:
            if r.status == DoctorStatus.DOWN:
                subprocess.run(
                    ["systemctl", "--user", "start", r.unit],
                    capture_output=True,
                    text=True,
                )

    # Asset remediation is intentionally manual — provisioning downloads models
    # and builds venvs (slow, network), so --fix never auto-runs it. Surface the
    # exact commands instead.
    fixes = [a for a in assets if a.fix and a.status is not DoctorStatus.OK]
    if fixes:
        print()
        print("Setup — provision the items flagged above:")
        for a in fixes:
            print(f"  {a.name}: {a.fix}")

    for r in results:
        if r.sentinel_hint:
            print()
            print(f"Run: journalctl --user -u {r.unit} -n 20")
            print("Note: if you intentionally stopped tincand, /run/tincan/want-down suppresses auto-restart. Remove it to re-enable.")

    advisory = _sco_advisory()
    if advisory:
        print()
        print(f"note: {advisory}")

    return exit_code


def main() -> int:
    return doctor_main()


if __name__ == "__main__":
    raise SystemExit(main())
