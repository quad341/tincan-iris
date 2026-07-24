"""BaselineHeartbeat — periodic background health check for iris.daemon (ti-pugo3.1).

Runs the checks named in FR-1.1 every 90s on a daemon thread (mirrors
PostureWatcher's threading.Thread + threading.Event.wait() shape) and caches
the aggregated result in-process. DaemonAPI's `status` command exposes it
read-only. degradation_notify.py (ti-pugo3.2) hooks the `on_transition`
callback to decide when a change is worth notifying about — this module only
computes and caches; it has no opinion on notification policy.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable

from ..doctor import (
    EXPECTED_SERVICES,
    AssetCheckResult,
    DoctorStatus,
    ServiceCheckResult,
    check_baseline_capabilities,
    check_call_card_enrichment,
    check_services,
)

_HEARTBEAT_INTERVAL_S: float = 90.0
_ENRICHMENT_TIMEOUT_S: float = 3.0
_SERVICE_TIMEOUT_S: float = 2.0

# FR-1.1 item 3 names iris-whisper/iris-kokoro/tincand only — iris-llama is
# operator-managed and shared across tools (see iris/up.py's own docstring),
# not something this daemon's baseline health should speak for.
_HEARTBEAT_SERVICE_NAMES = frozenset({"iris-whisper", "iris-kokoro", "tincand"})


@dataclass(frozen=True)
class BaselineStatus:
    level: str              # "green" | "yellow" | "red"
    checks: list[AssetCheckResult]
    checked_at: float       # time.time(), for "as of" display


def _aggregate(checks: list[AssetCheckResult]) -> str:
    required = [c for c in checks if c.required]
    if any(c.status in (DoctorStatus.DOWN, DoctorStatus.ABSENT, DoctorStatus.UNKNOWN) for c in required):
        return "red"
    if any(c.status == DoctorStatus.DEGRADED for c in required):
        return "yellow"
    return "green"


def _service_to_asset(r: ServiceCheckResult) -> AssetCheckResult:
    fix = f"journalctl --user -u {r.unit} -n 20" if r.status == DoctorStatus.DOWN else ""
    return AssetCheckResult(name=r.name, status=r.status, required=r.required, detail=r.note, fix=fix)


def _daemon_socket_check(is_healthy: Callable[[], bool]) -> AssetCheckResult:
    try:
        healthy = is_healthy()
    except Exception as exc:  # noqa: BLE001 — NFR-3: one check's exception never crashes the heartbeat
        return AssetCheckResult("daemon-socket", DoctorStatus.UNKNOWN, True, detail=str(exc))
    return AssetCheckResult(
        "daemon-socket",
        DoctorStatus.OK if healthy else DoctorStatus.DOWN,
        required=True,
        detail="listening" if healthy else "socket missing or server not accepting connections",
    )


def _collect_checks(is_daemon_socket_healthy: Callable[[], bool]) -> list[AssetCheckResult]:
    services = [s for s in EXPECTED_SERVICES if s.name in _HEARTBEAT_SERVICE_NAMES]
    checks: list[AssetCheckResult] = []

    with ThreadPoolExecutor(max_workers=6) as pool:
        f_caps = pool.submit(check_baseline_capabilities)
        f_svcs = pool.submit(check_services, services, timeout_s=_SERVICE_TIMEOUT_S, deep=False)
        f_enrich = pool.submit(check_call_card_enrichment, timeout_s=_ENRICHMENT_TIMEOUT_S)

        try:
            checks.extend(f_caps.result())
        except Exception as exc:  # noqa: BLE001 — NFR-3
            checks.append(AssetCheckResult("baseline-capabilities", DoctorStatus.UNKNOWN, True, detail=str(exc)))

        try:
            checks.extend(_service_to_asset(r) for r in f_svcs.result())
        except Exception as exc:  # noqa: BLE001
            checks.append(AssetCheckResult("services", DoctorStatus.UNKNOWN, True, detail=str(exc)))

        try:
            checks.append(f_enrich.result())
        except Exception as exc:  # noqa: BLE001
            checks.append(AssetCheckResult("call-card-enrichment", DoctorStatus.UNKNOWN, False, detail=str(exc)))

    checks.append(_daemon_socket_check(is_daemon_socket_healthy))
    return checks


class BaselineHeartbeat:
    """Background thread that computes + caches BaselineStatus every 90s."""

    def __init__(
        self,
        *,
        is_daemon_socket_healthy: Callable[[], bool],
        on_transition: Callable[[BaselineStatus, BaselineStatus | None], None] | None = None,
    ) -> None:
        self._is_daemon_socket_healthy = is_daemon_socket_healthy
        self._on_transition = on_transition
        self._lock = threading.Lock()
        self._latest: BaselineStatus | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="baseline-heartbeat", daemon=True)

    def start(self) -> None:
        self._run_once()          # populate immediately — don't leave /status empty for the first 90s
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def latest(self) -> BaselineStatus | None:
        with self._lock:
            return self._latest

    def _run(self) -> None:
        while not self._stop.wait(_HEARTBEAT_INTERVAL_S):
            self._run_once()

    def _run_once(self) -> None:
        checks = _collect_checks(self._is_daemon_socket_healthy)
        status = BaselineStatus(level=_aggregate(checks), checks=checks, checked_at=time.time())
        with self._lock:
            previous, self._latest = self._latest, status
        if self._on_transition is not None:
            self._on_transition(status, previous)
