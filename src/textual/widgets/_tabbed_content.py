from __future__ import annotations

from itertools import zip_longest

from rich.text import Text, TextType

from ..app import ComposeResult
from ..reactive import reactive
from ..widget import Widget
from ._content_switcher import ContentSwitcher
from ._tabs import Tab, Tabs

__all__ = [
    "ContentTab",
    "TabbedContent",
    "TabPane",
]


class ContentTab(Tab):
    """A Tab with an associated content id."""

    def __init__(self, label: Text, content_id: str):
        """Initialize a ContentTab.

        Args:
            label: The label to be displayed within the tab.
            content_id: The id of the content associated with the tab.
        """
        super().__init__(label, id=content_id)


class TabPane(Widget):
    """A container for switchable content, with additional title.

    This widget is intended to be used with [TabbedContent][textual.widgets.TabbedContent].

    """

    DEFAULT_CSS = """
    TabPane {
        height: auto;
        padding: 1 2;
    }
    """

    def __init__(
        self,
        title: TextType,
        *children: Widget,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ):
        """Initialize a TabPane.

        Args:
            title: Title of the TabPane (will be displayed in a tab label).
            name: Optional name for the TabPane.
            id: Optional ID for the TabPane.
            classes: Optional initial classes for the widget.
            disabled: Whether the TabPane is disabled or not.
        """
        self._title = self.render_str(title)
        super().__init__(
            *children, name=name, id=id, classes=classes, disabled=disabled
        )


class TabbedContent(Widget):
    """A container with associated tabs to toggle content visibility."""

    DEFAULT_CSS = """
    TabbedContent {
        height: auto;
    }
    TabbedContent > ContentSwitcher {
        height: auto;
    }
    """

    active: reactive[str] = reactive("", init=False)
    """The ID of the active tab, or empty string if none are active."""

    def __init__(self, *titles: TextType, initial: str = "") -> None:
        """Initialize a TabbedContent widgets.

        Args:
            *titles: Positional argument will be used as title.
            initial: The id of the initial tab, or empty string to select the first tab.
        """
        self.titles = [self.render_str(title) for title in titles]
        self._tab_content: list[Widget] = []
        self._initial = initial
        super().__init__()

    def compose(self) -> ComposeResult:
        """Compose the tabbed content."""

        def set_id(content: TabPane, new_id: str) -> TabPane:
            """Set an id on the content, if not already present."""
            if content.id is None:
                content.id = new_id
            return content

        # Wrap content in a `TabPane` if required.
        pane_content = [
            (
                set_id(content, f"tab-{index}")
                if isinstance(content, TabPane)
                else TabPane(
                    title or self.render_str(f"Tab {index}"), content, id=f"tab-{index}"
                )
            )
            for index, (title, content) in enumerate(
                zip_longest(self.titles, self._tab_content), 1
            )
        ]
        # Get a tab for each pane
        tabs = [
            ContentTab(content._title, content.id or "") for content in pane_content
        ]
        # Yield the tabs
        yield Tabs(*tabs, active=self._initial)
        # Yield the content switcher and panes
        with ContentSwitcher(initial=self._initial):
            yield from pane_content

    def compose_add_child(self, widget: Widget) -> None:
        """When using the context manager compose syntax, we want to attach nodes to the switcher."""
        self._tab_content.append(widget)

    def _on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        """User clicked a tab."""
        self.log("on_tabs_tab_activated", event)
        event.stop()
        switcher = self.query_one(ContentSwitcher)
        assert isinstance(event.tab, ContentTab)
        switcher.current = event.tab.id

    def _on_tabs_tabs_cleared(self, event: Tabs.TabsCleared) -> None:
        """All tabs were removed."""
        event.stop()

    def watch_active(self, active: str) -> None:
        """Switch tabs when the active attributes changes."""
        self.query_one(Tabs).active = active
