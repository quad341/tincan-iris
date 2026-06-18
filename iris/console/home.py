"""HomeApp — text-first out-of-call Textual dashboard (iris/console/home.py).

Bindings: n=cycle notifications, c=scope modal, K=dismiss notification,
          m=mark-all-read, q=quit.
"""
from __future__ import annotations

from textual.app import App, ComposeResult, Screen
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Footer, Input, Label, RichLog, Static

from ..mode import IrisMode
from ..scope import ScopeManifest


class MessagesPanel(Widget):
    """Badge count of unread voice messages."""

    DEFAULT_CSS = "MessagesPanel { height: auto; }"

    def __init__(self, store=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._store = store
        self.unread_count: int = 0

    def on_mount(self) -> None:
        if self._store:
            self.unread_count = len(self._store.unread())
        self.update_label()

    def update_label(self) -> None:
        self.query("Label").remove()
        self.mount(Label(f"Messages: {self.unread_count} unread"))


class NotificationsPanel(Widget):
    """Scrollable list of pending proactive notifications."""

    DEFAULT_CSS = "NotificationsPanel { height: 1fr; }"

    def __init__(self, store=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._store = store
        self.focused_index: int = 0
        self._focused_id: int | None = None
        self.item_count: int = 0

    def on_mount(self) -> None:
        self._refresh_items()

    def _refresh_items(self) -> None:
        if self._store:
            item = self._store.next_pending((), 4)
            self.item_count = 1 if item else 0

    def cycle_focus(self) -> None:
        self.focused_index = (self.focused_index + 1) % max(1, self.item_count + 1)

    def dismiss_focused(self) -> None:
        if self._focused_id is not None and self._store:
            self._store.dismiss(self._focused_id)
            self._focused_id = None


class CalendarPanel(Widget):
    """Upcoming calendar events (stub)."""

    DEFAULT_CSS = "CalendarPanel { height: auto; }"

    def compose(self) -> ComposeResult:
        yield Label("Calendar: no upcoming events")


class SidebarColumn(Vertical):
    """320px sidebar with Messages, Notifications, Calendar panels."""

    DEFAULT_CSS = "SidebarColumn { width: 32; border-right: solid $accent; }"

    def __init__(self, message_store=None, proactive_store=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._message_store = message_store
        self._proactive_store = proactive_store

    def compose(self) -> ComposeResult:
        yield MessagesPanel(store=self._message_store, id="messages-panel")
        yield NotificationsPanel(store=self._proactive_store, id="notifications-panel")
        yield CalendarPanel(id="calendar-panel")


class ResponsePanel(RichLog):
    """Main response area — shows Brain replies and status messages."""

    DEFAULT_CSS = "ResponsePanel { height: 1fr; }"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._text_buffer: str = ""

    def write(self, content, width=None, expand=False, shrink=True, scroll_end=None, animate=False):  # type: ignore[override]
        self._text_buffer += str(content) + "\n"
        return super().write(content, width=width, expand=expand, shrink=shrink, scroll_end=scroll_end, animate=animate)

    @property
    def renderable(self) -> str:
        return self._text_buffer


class ScopeManifestModal(Screen):
    """Full-screen modal showing ScopeManifest.what_i_do()."""

    BINDINGS = [Binding("escape,c", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        domains = ScopeManifest.what_i_do()
        lines = ["What Iris can do:\n"]
        for domain, items in domains.items():
            lines.append(f"  {domain}")
            for cap in items:
                lines.append(f"    • {cap}")
        yield Static("\n".join(lines), id="scope-content")
        yield Footer()

    def action_dismiss(self) -> None:
        self.app.pop_screen()


class HomeApp(App):
    """Text-first out-of-call Textual dashboard."""

    CSS = """
    HomeApp {
        layout: horizontal;
    }
    ResponsePanel {
        width: 1fr;
        height: 1fr;
    }
    #input-bar {
        dock: bottom;
        height: 3;
    }
    """

    BINDINGS = [
        Binding("n", "cycle_notifications", "Next notification"),
        Binding("c", "scope_modal", "Capabilities"),
        Binding("K", "dismiss_notification", "Dismiss notification"),
        Binding("m", "mark_all_read", "Mark all read"),
        Binding("q", "quit", "Quit"),
        Binding("d", "dismiss_notification", "Dismiss notification", show=False),
    ]

    def __init__(
        self,
        brain=None,
        message_store=None,
        proactive_store=None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._brain = brain
        self._message_store = message_store
        self._proactive_store = proactive_store
        self._iris_mode = IrisMode.OUT_OF_CALL

    def compose(self) -> ComposeResult:
        yield SidebarColumn(
            message_store=self._message_store,
            proactive_store=self._proactive_store,
        )
        with Vertical():
            yield ResponsePanel(id="response-panel")
            yield Input(placeholder="Ask Iris…", id="input-bar")
        yield Footer()

    def on_mount(self) -> None:
        if self._brain and not self._brain.is_reachable():
            self.query_one(ResponsePanel).write("[bold red]Brain unavailable[/] — check iris-brain service")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.clear()
        if self._brain and self._brain.is_reachable():
            self.run_worker(self._send_to_brain(text))

    async def _send_to_brain(self, text: str) -> None:
        panel = self.query_one(ResponsePanel)
        try:
            result = self._brain.respond(text)
            panel.write(result.text if hasattr(result, "text") else str(result))
        except Exception as exc:
            panel.write(f"[red]Error: {exc}[/]")

    def action_cycle_notifications(self) -> None:
        panel = self.query_one(NotificationsPanel)
        panel.cycle_focus()

    def action_scope_modal(self) -> None:
        if isinstance(self.screen, ScopeManifestModal):
            self.pop_screen()
        else:
            self.push_screen(ScopeManifestModal())

    def action_dismiss_notification(self) -> None:
        panel = self.query_one(NotificationsPanel)
        panel.dismiss_focused()

    def action_mark_all_read(self) -> None:
        if self._message_store:
            self._message_store.mark_all_read()

    def action_quit(self) -> None:
        self.exit()


def main() -> None:
    HomeApp().run()


if __name__ == "__main__":
    main()
