"""SD Backup Application - Main App with MODES-based navigation."""

from __future__ import annotations

import logging

from textual.app import App
from textual.binding import Binding

from frontend.backup import BackupScreen
from frontend.client import GraphQLClient
from frontend.home import HomeScreen
from frontend.settings import SettingsScreen
from frontend.tasks import TasksScreen

logger = logging.getLogger(__name__)


class SDBackupApp(App):
    """SD Backup Application with mode-based screen navigation."""

    TITLE = "SD Backup"
    SUB_TITLE = "Backup your SD cards with ease"

    CSS = """
    /* Global styles */
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
    
    /* Toast notifications */
    Toast {
        margin: 1 2;
    }
    
    /* Footer styling */
    Footer {
        background: $surface;
    }
    
    FooterKey {
        background: transparent;
        .footer-key--key {
            background: $primary;
            color: $text;
        }
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
            tooltip="Dashboard overview",
        ),
        Binding(
            "t",
            "app.switch_mode('tasks')",
            "Tasks",
            tooltip="Backup history",
        ),
        Binding(
            "b",
            "app.switch_mode('backup')",
            "Backup",
            tooltip="Start manual backup",
        ),
        Binding(
            "s",
            "app.switch_mode('settings')",
            "Settings",
            tooltip="Configuration",
        ),
        Binding(
            "a",
            "toggle_auto_refresh",
            "Auto-Refresh",
            tooltip="Toggle auto-refresh",
        ),
        Binding(
            "ctrl+q",
            "quit",
            "Quit",
            tooltip="Exit application",
        ),
    ]

    def __init__(self, host: str | None = None, port: int | None = None, **kwargs):
        super().__init__(**kwargs)
        self.host = host or "127.0.0.1"
        self.port = port or 8000
        logger.info("Initializing SDBackupApp with GraphQL endpoint at %s:%s", self.host, self.port)
        self.client = GraphQLClient(host=self.host, port=self.port)
        self.auto_refresh_enabled: bool = True
        self.theme = "gruvbox"

    def action_toggle_auto_refresh(self) -> None:
        """Toggle auto-refresh on/off globally."""
        self.auto_refresh_enabled = not self.auto_refresh_enabled
        status = "enabled" if self.auto_refresh_enabled else "disabled"
        logger.debug("Global auto-refresh toggled: %s", status)
        self.notify(f"Auto-refresh {status}", title="Auto-Refresh")

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
