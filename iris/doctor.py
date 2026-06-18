"""iris doctor — health-check CLI for Iris systemd services."""
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


EXPECTED_SERVICES: list[ServiceDescriptor] = [
    ServiceDescriptor("iris-llama",   "iris-llama.service",   "http://127.0.0.1:8080/health", required=True),
    ServiceDescriptor("iris-whisper", "iris-whisper.service", "http://127.0.0.1:8082/health", required=True),
    ServiceDescriptor("iris-kokoro",  "iris-kokoro.service",  "http://127.0.0.1:8083/health", required=True),
    ServiceDescriptor("iris-brain",   "iris-brain.service",   None,                            required=True),
    ServiceDescriptor("tincand",      "tincand.service",      "http://127.0.0.1:9001/health",  required=False),
]


def check_services(
    services: list[ServiceDescriptor],
    *,
    timeout_s: float = 2.0,
    deep: bool = False,
) -> list[ServiceCheckResult]:
    results: list[ServiceCheckResult] = []
    for svc in services:
        try:
            proc = subprocess.run(
                ["systemctl", "--user", "is-active", svc.unit],
                capture_output=True,
                text=True,
            )
        except OSError:
            results.append(ServiceCheckResult(svc.name, svc.unit, DoctorStatus.UNKNOWN, svc.required))
            continue

        if proc.returncode == 4:
            results.append(ServiceCheckResult(svc.name, svc.unit, DoctorStatus.ABSENT, svc.required))
            continue

        if proc.returncode != 0:
            results.append(ServiceCheckResult(svc.name, svc.unit, DoctorStatus.DOWN, svc.required))
            continue

        # Unit is active — check health URL if present
        if not svc.health_url:
            results.append(ServiceCheckResult(svc.name, svc.unit, DoctorStatus.OK, svc.required))
            continue

        rtt_ms: float | None = None
        try:
            req = urllib.request.Request(svc.health_url)
            t0 = time.monotonic()
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                data = json.loads(resp.read())
                if deep:
                    rtt_ms = (time.monotonic() - t0) * 1000
                status = DoctorStatus.OK if data.get("ready") else DoctorStatus.DEGRADED
        except (urllib.error.URLError, OSError):
            status = DoctorStatus.DEGRADED

        results.append(ServiceCheckResult(svc.name, svc.unit, status, svc.required, round_trip_ms=rtt_ms))

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


def doctor_main(args: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="iris doctor")
    parser.add_argument("--fix", action="store_true", help="restart DOWN services")
    parser.add_argument("--json", action="store_true", help="output JSON")
    parser.add_argument("--check", metavar="SVC", help="narrow to one service")
    parser.add_argument("--deep", action="store_true", help="add round-trip check")
    ns = parser.parse_args(args if args is not None else sys.argv[1:])

    services = list(EXPECTED_SERVICES)
    if ns.check:
        services = [s for s in services if s.name == ns.check]

    timeout_s = DEFAULT.doctor_deep_timeout_s if ns.deep else DEFAULT.doctor_timeout_s
    results = check_services(services, timeout_s=timeout_s, deep=ns.deep)
    exit_code = _exit_code(results)

    if ns.json:
        print(json.dumps({
            "services": [
                {"name": r.name, "status": r.status.value, "required": r.required,
                 "round_trip_ms": r.round_trip_ms}
                for r in results
            ],
            "exit_code": exit_code,
        }))
        return exit_code

    cols = shutil.get_terminal_size().columns
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

    return exit_code


def main() -> int:
    return doctor_main()


if __name__ == "__main__":
    raise SystemExit(main())
