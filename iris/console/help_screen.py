"""Help screen for the Iris operator console — ti-00jr4.1.

On-demand full reference pushed via [?], the universal "how do I use this"
bootstrap key. Leads with copy/bug-filing (this PRD's reason for existing),
then the existing TALK/CALL/OTHER groups.
"""
from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, RichLog, Static

_HELP_TEXT = """\
IRIS CONSOLE — HELP                        [Esc] / [q] closes

COPY & BUG-FILING — start here if something looks wrong
  y  copy last reply        -> clipboard
  e  copy last error        -> clipboard
  b  file a bug             -> snapshots recent output + last
                                error to a file, shows the path
  ·  session log (this run) -> {logpath}
  ·  can't mouse-select? your terminal's native modifier still
     works: Shift (GNOME Terminal / Konsole)
                Option/Alt (iTerm2 / kitty)

TALK
  space talk/stop   l hear you   f hear them
  i interrupt       m mute

CALL
  g grant   a approve   V call card   K contacts   d toggle DND

OTHER
  L list panel   c what you can ask Iris   n next notification
  q quit"""


class HelpScreen(Screen):
    """Full-width, on-demand reference — pushed via [?] from the main console.

    Parameters
    ----------
    logpath:
        The current session's log file path (``IrisConsole._logpath``), or
        a falsy value if logging failed to open.
    """

    TITLE = "Iris — Help"

    CSS = """
    HelpScreen {
        background: #0f1624;
        color: #cce0ff;
    }
    #help-body {
        height: 1fr;
        padding: 1 2;
    }
    """

    # priority=True (matches ContactsScreen/PostCallListView): IrisConsole's
    # own "q" is ALSO priority=True (bound to "quit"), and Textual checks
    # priority bindings App-first — without IrisConsole.check_action's
    # "quit" gate (see app.py), pressing "q" here would quit the whole app
    # instead of closing this screen.
    BINDINGS: ClassVar = [
        Binding("q", "app.pop_screen", "close", priority=True),
        Binding("escape", "app.pop_screen", "close", priority=True),
    ]

    def __init__(self, logpath: str) -> None:
        super().__init__()
        self._logpath = logpath

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll(id="help-body"):
            yield Static(
                _HELP_TEXT.format(logpath=self._logpath or "(disabled)"),
                markup=False,
            )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#help-body", VerticalScroll).focus()

    def on_unmount(self) -> None:
        self.app.query_one("#log", RichLog).focus()
