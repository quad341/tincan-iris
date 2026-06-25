"""iris daemon and iris dnd CLI subcommands (ADR-0006, ti-gxpt.6).

Commands:
  iris daemon start|stop|status
  iris dnd on|off|until <time>
"""
from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import NoReturn

from ._socket_path import daemon_socket_path
from .proxy import DaemonNotRunning, DaemonProxy

_PID_PATH = Path.home() / ".local" / "run" / "iris" / "daemon.pid"
_LOG_PATH = Path.home() / ".local" / "state" / "iris" / "daemon.log"

_NO_COLOR = os.environ.get("NO_COLOR") is not None or not sys.stdout.isatty()


def _green(s: str) -> str:
    return s if _NO_COLOR else f"\033[32m{s}\033[0m"


def _yellow(s: str) -> str:
    return s if _NO_COLOR else f"\033[33m{s}\033[0m"


def _red(s: str) -> str:
    return s if _NO_COLOR else f"\033[31m{s}\033[0m"


def _ok(msg: str) -> None:
    print(f"  {_green('✓')}  {msg}")


def _warn(msg: str) -> None:
    print(f"  {_yellow('⚠')}  {msg}")


def _err(msg: str) -> None:
    print(f"  {_red('✗')}  {msg}")


# ---------------------------------------------------------------------------
# PID file helpers
# ---------------------------------------------------------------------------


def _read_pid() -> int | None:
    try:
        text = _PID_PATH.read_text().strip()
        return int(text) if text else None
    except (FileNotFoundError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _daemon_running() -> int | None:
    pid = _read_pid()
    if pid is None:
        return None
    return pid if _pid_alive(pid) else None


# ---------------------------------------------------------------------------
# iris daemon start
# ---------------------------------------------------------------------------


def _daemon_start() -> int:
    running_pid = _daemon_running()
    if running_pid is not None:
        _warn(f"Iris daemon is already running (pid {running_pid})")
        return 0

    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_file = _LOG_PATH.open("a")

    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "iris.daemon"],
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
        )
    except OSError as exc:
        _err(f"Failed to start: {exc}")
        log_file.close()
        return 3

    sock_path = daemon_socket_path()
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        time.sleep(0.1)
        if sock_path.exists():
            break
    else:
        _err(f"Failed to start: socket not ready. Check {_LOG_PATH}")
        log_file.close()
        return 3

    print(f"Starting iris daemon…  {_green('✓')}  pid {proc.pid}")
    log_file.close()
    return 0


# ---------------------------------------------------------------------------
# iris daemon stop
# ---------------------------------------------------------------------------


def _daemon_stop() -> int:
    pid = _daemon_running()
    if pid is None:
        _warn("Daemon is not running")
        return 1

    print(f"Sending SIGTERM to pid {pid}…", end=" ", flush=True)
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        print()
        _warn("Process already gone")
        return 0

    deadline = time.monotonic() + 5.0
    reported_waiting = False
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            print(_green("✓  stopped"))
            return 0
        if not reported_waiting and time.monotonic() - (deadline - 5) > 1.0:
            print()
            print("  Waiting for daemon to finish in-flight call…", end=" ", flush=True)
            reported_waiting = True
        time.sleep(0.2)

    print()
    _err(f"Daemon (pid {pid}) did not stop in 5s — send SIGKILL manually")
    return 3


# ---------------------------------------------------------------------------
# iris daemon status
# ---------------------------------------------------------------------------


def _daemon_status() -> int:
    pid = _daemon_running()
    sock_path = daemon_socket_path()

    if pid is None:
        print(f"  Iris daemon  ○  not running")
        print(f"  Start with:  iris daemon start")
        return 1

    dot = _green("●") if not _NO_COLOR else "●"
    print(f"\n  Iris daemon  {dot}  running  (pid {pid})")
    print(f"  Socket:   {sock_path}")

    proxy = DaemonProxy(socket_path=sock_path)
    try:
        proxy.connect()
        ack = proxy.send({"cmd": "status"})
    except DaemonNotRunning:
        print("  (socket not responding)")
        return 1
    finally:
        proxy.close()

    if not ack.get("ok"):
        print("  (status request failed)")
        return 3

    state = ack.get("state", {})
    posture = state.get("posture", {})
    clients = state.get("clients", 0)
    call = state.get("call", "unknown")
    dnd = posture.get("dnd", False)
    busy = posture.get("busy", False)

    dnd_str = _red("DND ON") if dnd else "DND OFF"
    print(f"  Clients:  {clients} connected")
    print(f"  Posture:  {dnd_str}  ·  busy: {'true' if busy else 'false'}")
    print(f"  Call:     {call}")
    print()
    return 0


def daemon_main(argv: list[str] | None = None) -> int:
    """Entry point for ``iris daemon <subcommand>``."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print("usage: iris daemon <start|stop|status>")
        return 0
    sub = args[0]
    if sub == "start":
        return _daemon_start()
    if sub == "stop":
        return _daemon_stop()
    if sub == "status":
        return _daemon_status()
    sys.stderr.write(f"iris daemon: unknown subcommand {sub!r}\n")
    sys.stderr.write("usage: iris daemon <start|stop|status>\n")
    return 2


# ---------------------------------------------------------------------------
# iris dnd — time parsing
# ---------------------------------------------------------------------------


def _parse_until(token: str) -> float | None:
    """Return Unix timestamp from a human time token, or None on failure.

    Accepted formats (v1 subset; natural-language follow-up in a future bead):
      <N>m                   minutes from now (e.g. "30m")
      <N>h                   hours from now
      <N>h<M>m               hours + minutes
      HH:MM                  today at that time (24h)
      <N>am / <N>pm          today at that hour (12h)
    """
    now = time.time()
    import datetime

    token = token.strip().lower()

    # <N>h<M>m — must try before plain <N>h
    m = re.fullmatch(r"(\d+)h(\d+)m", token)
    if m:
        return now + int(m.group(1)) * 3600 + int(m.group(2)) * 60

    # <N>m
    m = re.fullmatch(r"(\d+)m", token)
    if m:
        return now + int(m.group(1)) * 60

    # <N>h
    m = re.fullmatch(r"(\d+)h", token)
    if m:
        return now + int(m.group(1)) * 3600

    # HH:MM
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", token)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            today = datetime.date.today()
            dt = datetime.datetime(today.year, today.month, today.day, hour, minute)
            return dt.timestamp()

    # <N>pm / <N>am  (e.g. "6pm", "9am")
    m = re.fullmatch(r"(\d{1,2})(am|pm)", token)
    if m:
        hour = int(m.group(1))
        if m.group(2) == "pm" and hour != 12:
            hour += 12
        elif m.group(2) == "am" and hour == 12:
            hour = 0
        if 0 <= hour <= 23:
            today = datetime.date.today()
            dt = datetime.datetime(today.year, today.month, today.day, hour, 0)
            return dt.timestamp()

    return None


def _format_duration(seconds: float) -> str:
    """Format a positive duration into human-readable string."""
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m" if s == 0 else f"{m}m {s}s"
    h, m = divmod(m, 60)
    return f"{h}h {m}m" if m else f"{h}h"


# ---------------------------------------------------------------------------
# iris dnd on / off / until
# ---------------------------------------------------------------------------


def _with_proxy(fn):
    """Connect proxy, call fn(proxy), close proxy.  Handles DaemonNotRunning."""
    proxy = DaemonProxy()
    try:
        proxy.connect()
    except DaemonNotRunning as exc:
        _err(str(exc))
        return 1
    try:
        return fn(proxy)
    finally:
        proxy.close()


def _dnd_on() -> int:
    def _call(proxy: DaemonProxy) -> int:
        ack = proxy.send({"cmd": "dnd", "action": "on"})
        if not ack.get("ok"):
            _err(ack.get("error", "unknown error"))
            return 3
        print("DND ON  (manual, indefinite)")
        print("Calls will be screened or taken as messages.")
        return 0
    return _with_proxy(_call)


def _dnd_off() -> int:
    def _call(proxy: DaemonProxy) -> int:
        ack = proxy.send({"cmd": "dnd", "action": "off"})
        if not ack.get("ok"):
            _err(ack.get("error", "unknown error"))
            return 3
        print("DND OFF")
        return 0
    return _with_proxy(_call)


def _dnd_until(token: str) -> int:
    import datetime

    until_ts = _parse_until(token)
    if until_ts is None:
        _err(f"Cannot parse time {token!r}.")
        print("  Accepted: 30m, 2h, 2h30m, 18:00, 6pm")
        return 2

    now = time.time()
    if until_ts <= now:
        dt = datetime.datetime.fromtimestamp(until_ts)
        ago = _format_duration(now - until_ts)
        _err(f"Time {token!r} is in the past ({dt:%H:%M} is {ago} ago).")
        print("  Use \"iris dnd on\" for indefinite DND, or specify a future time.")
        return 2

    def _call(proxy: DaemonProxy) -> int:
        ack = proxy.send({"cmd": "dnd", "action": "until", "until": until_ts})
        if not ack.get("ok"):
            _err(ack.get("error", "unknown error"))
            return 3
        dt = datetime.datetime.fromtimestamp(until_ts)
        remaining = _format_duration(until_ts - time.time())
        print(f"DND ON until {dt:%H:%M}  (manual, expires in {remaining})")
        return 0
    return _with_proxy(_call)


def dnd_main(argv: list[str] | None = None) -> int:
    """Entry point for ``iris dnd <on|off|until>``."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print("usage: iris dnd <on|off|until <time>>")
        print("time formats: 30m  2h  2h30m  18:00  6pm")
        return 0
    sub = args[0]
    if sub == "on":
        return _dnd_on()
    if sub == "off":
        return _dnd_off()
    if sub == "until":
        if len(args) < 2:
            sys.stderr.write("iris dnd until: missing <time> argument\n")
            return 2
        return _dnd_until(args[1])
    sys.stderr.write(f"iris dnd: unknown subcommand {sub!r}\n")
    sys.stderr.write("usage: iris dnd <on|off|until <time>>\n")
    return 2
