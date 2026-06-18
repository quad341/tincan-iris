"""Desktop notification sink — wraps notify-send for out-of-call proactive delivery."""
from __future__ import annotations

import subprocess


class DesktopNotifySink:
    """Sends desktop notifications via notify-send.

    FileNotFoundError (notify-send not installed) and TimeoutExpired are silently
    swallowed — the daemon must not crash if the desktop is absent.
    """

    def notify(self, title: str, body: str, *, urgency: str = "normal") -> None:
        """Fire a desktop notification. urgency: 'low' | 'normal' | 'critical'."""
        try:
            subprocess.run(
                ["notify-send", "-u", urgency, "-a", "Iris", "--", title, body],
                check=False,
                timeout=2.0,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
