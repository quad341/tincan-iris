"""Web-search skill — hardened HTTP fetch + Q&A for the operator.

Security model (PM decision; see ti-ccc.15.1 design):
  - Far-party gate: only the operator may trigger a lookup.
  - SSRF guard: ``is_private_url()`` rejects RFC1918, loopback, link-local.
  - Content cap: 64 KiB read / 8000 chars passed to Q&A.
  - Injection detection: ``_qa()`` flags suspicious instruction-override text.
  - 2-second "Still fetching…" spoken TTS if the fetch is slow.
  - URL always shown in the console transcript (via ``on_annotation``).
"""
from __future__ import annotations

import ipaddress
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

from .skills import SkillParam

_CONTENT_CAP_BYTES = 65536   # 64 KB
_CONTENT_CAP_CHARS = 8000
_FETCH_TIMEOUT_S = 5
_STILL_FETCHING_DELAY_S = 2.0

_INJECTION_RE = re.compile(
    r"ignore\s.{0,40}(previous|prior|above|earlier|system).{0,40}(instruct|prompt|rule)",
    re.I,
)


def is_private_url(url: str) -> bool:
    """Return True if ``url`` resolves to a private/reserved IP address.

    Checks RFC1918 private ranges, loopback (127.x / ::1), and link-local
    (169.254.x). Only inspects literal IP addresses in the URL — domain names
    are not resolved here (DNS rebinding is out-of-scope for v1).
    """
    try:
        host = urllib.parse.urlparse(url).hostname or ""
        addr = ipaddress.ip_address(host)
        return addr.is_private or addr.is_loopback or addr.is_link_local
    except ValueError:
        return False


class WebSearchSkill:
    """Fetch a public URL and answer a question from its content.

    Internal seams ``_fetch`` and ``_qa`` are replaceable for testing.
    """

    name = "web_search"
    description = (
        "Fetch a public URL and answer the operator's question from the page content. "
        "Far party is blocked. Private addresses are rejected."
    )
    params: list[SkillParam] = [
        SkillParam(
            name="url",
            type="string",
            description="Public URL to fetch.",
        ),
        SkillParam(
            name="question",
            type="string",
            description="Question to answer from the fetched page.",
        ),
    ]

    # ------------------------------------------------------------------
    # Public interface

    def run(
        self,
        *,
        url: str,
        question: str,
        speaker: str = "operator",
        on_annotation: Callable[[str], None] | None = None,
        on_tts: Callable[[str], None] | None = None,
    ) -> str:
        """Fetch ``url`` and answer ``question``. Returns spoken reply string.

        Parameters
        ----------
        speaker:
            Caller identity. Only ``"operator"`` is allowed; any other value
            returns an operator-only notice.
        on_annotation:
            Console callback — receives ``str`` messages for the transcript panel.
        on_tts:
            TTS callback — receives spoken strings (e.g. "Still fetching…").
        """
        if speaker != "operator":
            return "This feature is only available to the operator."

        if is_private_url(url):
            return "I can't fetch that — it's a private address."

        if on_annotation:
            on_annotation(f"[fetch: {url}]")

        # Fetch with 2-second "still fetching" spoken notice.
        result: list = [None]
        exc: list[Exception | None] = [None]
        done = threading.Event()

        def _do_fetch() -> None:
            try:
                result[0] = self._fetch(url)
            except Exception as e:  # noqa: BLE001
                exc[0] = e
            finally:
                done.set()

        t = threading.Thread(target=_do_fetch, daemon=True, name="iris-web-fetch")
        t.start()

        if not done.wait(timeout=_STILL_FETCHING_DELAY_S):
            if on_tts:
                on_tts("Still fetching…")
            done.wait()

        if exc[0] is not None:
            if isinstance(exc[0], TimeoutError):
                return "I couldn't get that — the page took too long to respond."
            return "I couldn't access that page."

        content, fetch_annotations = result[0]
        for ann in fetch_annotations or []:
            if on_annotation:
                on_annotation(ann)

        answer, injected = self._qa(content, question)

        if injected and on_annotation is not None:
            on_annotation("⚠ Possible instruction injection detected — ignored.")

        if answer is None:
            return "I couldn't get a useful answer from that page."

        return f"From the page: {answer}"

    # ------------------------------------------------------------------
    # Seams (replaced by monkeypatch in tests)

    def _fetch(self, url: str) -> tuple[str, list[str]]:
        """HTTP GET ``url`` — 5s timeout, 64 KB / 8000 char cap."""
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Iris/1.0 (+https://github.com/gastownhall/tincan-iris)"},
        )
        try:
            with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT_S) as resp:
                raw = resp.read(_CONTENT_CAP_BYTES)
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise TimeoutError(str(exc)) from exc
            raise PermissionError(str(exc)) from exc
        content = raw.decode("utf-8", errors="replace")[:_CONTENT_CAP_CHARS]
        return content, []

    def _qa(self, content: str, question: str) -> tuple[str | None, bool]:
        """Answer ``question`` from ``content``.

        Returns ``(answer, injection_flagged)``.  ``answer`` is ``None`` when
        no clear answer can be extracted.

        Production implementation (ti-ccc.15.1.2): isolated Qwen call with
        DATA block markers.  Stub here returns ``(None, injection_check)``.
        """
        injected = bool(_INJECTION_RE.search(content))
        return None, injected
