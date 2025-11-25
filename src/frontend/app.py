"""SD Backup Application - Main App with MODES-based navigation."""

from __future__ import annotations

from textual.app import App
from textual.binding import Binding

from frontend.backup import BackupScreen
from frontend.client import GraphQLClient
from frontend.home import HomeScreen
from frontend.settings import SettingsScreen
from frontend.tasks import TasksScreen


class SDBackupApp(App):
    """SD Backup Application with mode-based screen navigation."""

    TITLE = "SD Backup"
    CSS = """
    .column {
        align: center top;
        & > * { max-width: 100; }
    }
    
    Screen.-maximized {
        margin: 1 2;
        max-width: 100%;
        &.column { margin: 1 2; padding: 1 2; }
        &.column > * { max-width: 100%; }
    }
    """

    MODES = {
        "home": HomeScreen,
        "tasks": TasksScreen,
        "backup": BackupScreen,
        "settings": SettingsScreen,
    }

    DEFAULT_MODE = "home"

    BINDINGS = [
        Binding(
            "h",
            "app.switch_mode('home')",
            "Home",
            tooltip="Show the dashboard overview",
        ),
        Binding(
            "t",
            "app.switch_mode('tasks')",
            "Tasks",
            tooltip="View backup task history",
        ),
        Binding(
            "b",
            "app.switch_mode('backup')",
            "Backup",
            tooltip="Start a manual backup",
        ),
        Binding(
            "s",
            "app.switch_mode('settings')",
            "Settings",
            tooltip="Configure backup settings",
        ),
        Binding(
            "q",
            "quit",
            "Quit",
            tooltip="Exit the application",
        ),
    ]

    def __init__(self, host: str | None = None, port: int | None = None, **kwargs):
        super().__init__(**kwargs)
        self.host = host or "127.0.0.1"
        self.port = port or 8000
        self.client: GraphQLClient
        self.theme = "gruvbox"

    def on_mount(self) -> None:
        """Initialize the GraphQL client when the app mounts."""
        self.client = GraphQLClient(host=self.host, port=self.port)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Disable switching to a mode we are already on."""
        if (
            action == "switch_mode"
            and parameters
            and self.current_mode == parameters[0]
        ):
            return None
        return True


if __name__ == "__main__":
    app = SDBackupApp()
    app.run()
