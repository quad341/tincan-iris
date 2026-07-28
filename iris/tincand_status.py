"""Shared primitive for querying tincand over D-Bus.

``iris/doctor.py`` and ``iris/up.py`` each kept their own copy of this exact
call; the baseline heartbeat (``iris/daemon/heartbeat.py``) is a third call
site, which is the point to consolidate rather than compound the duplication.
"""
from __future__ import annotations


def get_tincand_status() -> dict:
    import dbus
    bus = dbus.SessionBus()
    obj = bus.get_object("im.tincan.Daemon", "/im/tincan")
    iface = dbus.Interface(obj, "im.tincan.Daemon")
    return {str(k): v for k, v in dict(iface.GetStatus()).items()}
