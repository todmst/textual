from __future__ import annotations

from textual.app import App, ComposeResult
from textual.command_palette import (
    CommandMatches,
    CommandPalette,
    CommandSource,
    CommandSourceHit,
)
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Input


class SimpleSource(CommandSource):
    environment: set[tuple[App, Screen, Widget | None]] = set()

    async def hunt_for(self, _: str) -> CommandMatches:
        def gndn() -> None:
            pass

        SimpleSource.environment.add((self.app, self.screen, self.focused))
        yield CommandSourceHit(1, "Hit", gndn, "Hit")


class CommandPaletteApp(App[None]):
    COMMAND_SOURCES = {SimpleSource}

    def compose(self) -> ComposeResult:
        yield Input()

    def on_mount(self) -> None:
        self.action_command_palette()


async def test_command_source_environment() -> None:
    """The command source should see the app and default screen."""
    async with CommandPaletteApp().run_test() as pilot:
        base_screen = pilot.app.query_one(CommandPalette)._calling_screen
        assert base_screen is not None
        await pilot.press(*"test")
        assert len(SimpleSource.environment) == 1
        assert SimpleSource.environment == {
            (pilot.app, base_screen, base_screen.query_one(Input))
        }
