"""Mayor-reply SSE listener — delivers async mayor responses to iris (ti-h9di.3).

Background listener that subscribes to the gascity SSE channel and fires
``mayor_reply`` events when the mayor responds to a delegation.

STUB until ga-ty8cfb ships the server-side SSE endpoint.  In stub mode the
listener thread starts but never delivers events — the operator sees no impact.

When ga-ty8cfb lands:
  - Set _SSE_URL to the real gascity endpoint.
  - Fill in _listen() to open an ``http.client`` (or ``urllib``) connection to
    the SSE stream and parse ``data:`` lines.
  - Each ``mail.delivered`` event with ``from=mayor`` fires ``deliver()``.

Security: reply text is displayed/spoken on the local channel only.  Far-party
audio is not involved.  Mayor reply text is treated as display data — no command
parsing, no city dispatch.
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .delegate_skill import _DelegateState

# Set to the real gascity SSE endpoint when ga-ty8cfb ships.
_SSE_URL: str | None = None


class MayorReplyListener:
    """Background SSE listener that posts mayor replies to the iris event queue.

    One instance per session; ``start(entry_id)`` is called for each confirmed
    delegation.  In stub mode (``_SSE_URL is None``) the per-delegation thread
    starts and exits immediately — no error, no events, no operator impact.
    """

    def __init__(
        self,
        state: "_DelegateState",
        emit: Callable[[tuple], None],
    ) -> None:
        self._state = state
        self._emit = emit

    def start(self, entry_id: str) -> None:
        """Spawn a daemon listener thread for this delegation entry."""
        t = threading.Thread(
            target=self._listen,
            args=(entry_id,),
            name=f"mayor-reply-{entry_id}",
            daemon=True,
        )
        t.start()

    def _listen(self, entry_id: str) -> None:
        """SSE listener body — stub until ga-ty8cfb ships."""
        if _SSE_URL is None:
            # Stub mode: endpoint TBD.  Start silently, do nothing.
            return
        # Live mode (requires ga-ty8cfb): open SSE stream, wait for
        # mail.delivered event where from==mayor, then call deliver().
        # Implementation deferred to ga-ty8cfb.
        pass  # noqa: PIE790  (placeholder; not dead code)

    def deliver(self, entry_id: str, reply_text: str) -> None:
        """Post mayor reply to the iris conversation stream.

        Dequeues the pending delegation and emits a ``mayor_reply`` event.
        The app's ``_drain()`` handler writes the reply to the transcript and
        triggers TTS.  Reply is local-only: never forwarded to far-party.
        """
        self._state.dequeue(entry_id)
        self._emit(("mayor_reply", reply_text, entry_id))
