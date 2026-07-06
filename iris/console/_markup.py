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

    Textual's tokenizer checks only the single character immediately before
    ``[`` (not backslash *parity*), and its text-extraction step consumes
    exactly one backslash per adjacent bracket via a plain
    ``.replace("\\[", "[")``. So — unlike ``rich.markup.escape()``, which
    doubles pre-existing backslashes before adding its own — the correct
    escape here is to add exactly one backslash to whatever run already
    precedes a ``[``, not double it; doubling over-escapes by one character
    every time the input already contains a backslash before a bracket.

    A text that *ends* in a backslash with nothing else following in this
    string is a genuine edge case no self-contained escaper can fully close:
    if the caller concatenates more markup immediately after (the common
    ``f"[dim]{escape_for_content(x)}[/dim]"`` pattern), that trailing
    backslash will still consume one backslash from whatever the caller
    appends, potentially leaking a closing tag as literal text. Textual's own
    first-party ``textual.markup.escape()`` has the identical limitation for
    the same reason. The trailing pad below only guarantees the backslash
    *character itself* survives into the rendered text; it cannot guarantee
    tag-boundary correctness across content it never sees.
    """

    def _add_one(match: "re.Match[str]") -> str:
        return f"{match.group(1)}\\["

    escaped = _ESCAPE_RE.sub(_add_one, text)
    if escaped.endswith("\\"):
        escaped += "\\"
    return escaped
