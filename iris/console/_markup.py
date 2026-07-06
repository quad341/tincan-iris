"""Markup escaping safe for Textual's Content.from_markup — no Textual dependency, importable standalone."""
from __future__ import annotations

import re

_ESCAPE_RE = re.compile(r"(\\*)(\[)")


def escape_for_content(text: str) -> str:
    r"""Escape ``text`` so it survives Textual's ``Content.from_markup`` unchanged.

    ``rich.markup.escape()`` only escapes ``[`` when followed by a lowercase
    letter, ``#``, ``/``, or ``@`` (Rich's own tag grammar). Textual's tokenizer
    opens a tag on *any* unescaped ``[`` (``open_tag = r"(?<!\\)\["`` in
    ``textual.markup``), so bracketed content shaped like a token it recognizes
    — ``[$50]``, ``[50%]`` — sails past ``rich.markup.escape()`` and is then
    silently swallowed by ``Content.from_markup`` as an unrecognized style tag:
    not mis-styled, deleted. Escaping every ``[`` unconditionally closes the
    gap regardless of what follows the bracket.
    """

    def _double_and_escape(match: "re.Match[str]") -> str:
        backslashes = match.group(1)
        return f"{backslashes}{backslashes}\\["

    escaped = _ESCAPE_RE.sub(_double_and_escape, text)
    if escaped.endswith("\\") and not escaped.endswith("\\\\"):
        escaped += "\\"
    return escaped
