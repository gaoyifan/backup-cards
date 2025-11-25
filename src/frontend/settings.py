"""Settings screen - Configuration for SD Backup."""

from __future__ import annotations

import asyncio

from textual import containers, on
from textual.app import ComposeResult
from textual.widgets import Button, Checkbox, Footer, Input, Label, Markdown

from frontend.page import PageScreen


SETTINGS_MD = """\
# Settings

Configure your SD Backup preferences.

"""

CONFIG_MD = """\
## Auto Backup Configuration

Enable automatic backups when SD cards are inserted, and configure the target path template.

### Target Path Template Variables

- `{device}` - Device name (e.g., sda1)
- `{date}` - Current date (YYYY-MM-DD)
- `{time}` - Current time (HH-MM-SS)

Example: `/backups/{device}/{date}` → `/backups/sda1/2024-01-15`
"""


class ConfigForm(containers.VerticalGroup):
    """Configuration form widget."""

    DEFAULT_CSS = """
    ConfigForm {
        height: auto;
        padding: 1 2;
        background: $boost;
        margin: 1 0;
        
        .form-row {
            height: auto;
            margin-bottom: 1;
        }
        
        .form-label {
            margin-bottom: 0;
        }
        
        Input {
            width: 100%;
        }
        
        Checkbox {
            margin: 1 0;
        }
        
        #button-row {
            margin-top: 1;
        }
        
        #status-label {
            margin-top: 1;
            text-style: italic;
        }
    }
    """

    def compose(self) -> ComposeResult:
        yield Markdown(CONFIG_MD)
        yield Checkbox(
            "Enable automatic backups",
            id="auto-backup-checkbox",
            tooltip="Automatically start backup when SD card is inserted",
        )
        with containers.VerticalGroup(classes="form-row"):
            yield Label("Target Path Template", classes="form-label")
            yield Input(
                placeholder="/backups/{device}/{date}",
                id="target-template-input",
            )
        with containers.HorizontalGroup(id="button-row"):
            yield Button(
                "Save Settings",
                id="save-btn",
                variant="primary",
                tooltip="Save configuration changes",
            )
            yield Button(
                "Reset",
                id="reset-btn",
                variant="default",
                tooltip="Reset to last saved values",
            )
        yield Label("", id="status-label")


class SettingsScreen(PageScreen):
    """Settings screen for configuration."""

    DEFAULT_CSS = """
    SettingsScreen {
        align-horizontal: center;
        
        #content {
            width: 100%;
            max-width: 100;
            padding: 1 2;
            height: 1fr;
            overflow-y: auto;
        }
        
        Markdown {
            background: transparent;
            margin: 0;
            padding: 0;
        }
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._original_config: dict = {}

    def compose(self) -> ComposeResult:
        with containers.VerticalScroll(id="content"):
            yield Markdown(SETTINGS_MD)
            yield ConfigForm()
        yield Footer()

    def on_mount(self) -> None:
        asyncio.create_task(self._load_config())

    async def _load_config(self) -> None:
        """Load current configuration."""
        client = self.app.client

        query = """
        query {
            config {
                autoBackupEnabled
                autoBackupTargetPath
            }
        }
        """
        try:
            result = await client.execute(query)
            config = result.get("config", {})
            self._original_config = config

            # Update form fields
            checkbox = self.query_one("#auto-backup-checkbox", Checkbox)
            checkbox.value = config.get("autoBackupEnabled", False)

            input_field = self.query_one("#target-template-input", Input)
            input_field.value = config.get("autoBackupTargetPath", "")

            status_label = self.query_one("#status-label", Label)
            status_label.update("Configuration loaded")
        except Exception as e:
            status_label = self.query_one("#status-label", Label)
            status_label.update(f"[red]Failed to load config: {e}[/red]")

    @on(Button.Pressed, "#save-btn")
    async def on_save_pressed(self) -> None:
        """Handle save button press."""
        checkbox = self.query_one("#auto-backup-checkbox", Checkbox)
        input_field = self.query_one("#target-template-input", Input)
        status_label = self.query_one("#status-label", Label)

        auto_enabled = checkbox.value
        target_template = input_field.value.strip()

        status_label.update("Saving...")

        client = self.app.client
        mutation = """
        mutation UpdateConfig($config: ConfigInput!) {
            updateConfig(config: $config)
        }
        """
        config_input = {
            "autoBackupEnabled": auto_enabled,
            "autoBackupTargetPath": target_template,
        }
        try:
            result = await client.execute(
                mutation, variable_values={"config": config_input}
            )
            if result.get("updateConfig"):
                self._original_config = {
                    "autoBackupEnabled": auto_enabled,
                    "autoBackupTargetPath": target_template,
                }
                status_label.update("[green]Settings saved successfully![/green]")
                self.notify("Settings saved", title="Success", severity="information")
            else:
                status_label.update("[yellow]Settings may not have been saved[/yellow]")
        except Exception as e:
            status_label.update(f"[red]Failed to save: {e}[/red]")
            self.notify(f"Failed to save settings: {e}", title="Error", severity="error")

    @on(Button.Pressed, "#reset-btn")
    def on_reset_pressed(self) -> None:
        """Handle reset button press."""
        checkbox = self.query_one("#auto-backup-checkbox", Checkbox)
        input_field = self.query_one("#target-template-input", Input)
        status_label = self.query_one("#status-label", Label)

        checkbox.value = self._original_config.get("autoBackupEnabled", False)
        input_field.value = self._original_config.get("autoBackupTargetPath", "")
        status_label.update("Reset to last saved values")

