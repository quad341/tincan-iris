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
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
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


@dataclass
class AssetCheckResult:
    name: str
    status: DoctorStatus
    required: bool
    detail: str = ""   # short, table-friendly (resolved path, or what's missing)
    fix: str = ""       # full remediation; shown in the Setup block, not the table


EXPECTED_SERVICES: list[ServiceDescriptor] = [
    ServiceDescriptor("iris-llama",   "iris-llama.service",   "http://127.0.0.1:8080/health", required=True),
    ServiceDescriptor("iris-whisper", "iris-whisper.service", "http://127.0.0.1:8082/health", required=True),
    ServiceDescriptor("iris-kokoro",  "iris-kokoro.service",  "http://127.0.0.1:8083/health", required=True),
    ServiceDescriptor("iris-brain",   "iris-brain.service",   None,                            required=True),
    ServiceDescriptor("tincand",      "tincand.service",      "http://127.0.0.1:9001/health",  required=False),
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

        results.append(ServiceCheckResult(svc.name, svc.unit, status, svc.required, note=note, round_trip_ms=rtt_ms))

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

    timeout_s = DEFAULT.doctor_deep_timeout_s if ns.deep else DEFAULT.doctor_timeout_s
    results = check_services(services, timeout_s=timeout_s, deep=ns.deep)
    exit_code = max(_exit_code(results), _asset_exit_code(assets))

    if ns.json:
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
            "services": [
                {"name": r.name, "status": r.status.value, "required": r.required,
                 "round_trip_ms": r.round_trip_ms}
                for r in results
            ],
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

    advisory = _sco_advisory()
    if advisory:
        print()
        print(f"note: {advisory}")

    return exit_code


def main() -> int:
    return doctor_main()


if __name__ == "__main__":
    raise SystemExit(main())
