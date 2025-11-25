"""Backup screen - Manual backup form for SD Backup."""

from __future__ import annotations

import asyncio
from typing import Optional

from textual import containers, on
from textual.app import ComposeResult
from textual.widgets import Button, Footer, Input, Label, Markdown, Select, Static

from frontend.page import PageScreen


BACKUP_MD = """\
# Start Manual Backup

Create a new backup by selecting a source device or directory and specifying a target location.

"""

FORM_MD = """\
## Backup Configuration

Fill in the source and target paths below, then click Start Backup.
"""


class DeviceSelector(containers.VerticalGroup):
    """Device selection widget."""

    DEFAULT_CSS = """
    DeviceSelector {
        height: auto;
        padding: 1 2;
        background: $boost;
        margin: 1 0;
        
        Label { margin-bottom: 1; }
        Select { width: 100%; }
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("Select Source Device (optional)")
        yield Select(
            [],
            prompt="Choose a device...",
            id="device-select",
            allow_blank=True,
        )

    def update_devices(self, devices: list[dict]) -> None:
        """Update the device selector options."""
        select = self.query_one("#device-select", Select)
        options = []
        for device in devices:
            path = device.get("devicePath", "")
            mount = device.get("mountPoint", "")
            if mount:
                label = f"{path} ({mount})"
                value = mount  # Use mount point as source
            else:
                label = f"{path} (not mounted)"
                value = path
            options.append((label, value))
        select.set_options(options)


class BackupForm(containers.VerticalGroup):
    """Backup form widget."""

    DEFAULT_CSS = """
    BackupForm {
        height: auto;
        padding: 1 2;
        background: $boost;
        margin: 1 0;
        
        .form-row {
            height: auto;
            margin-bottom: 1;
        }
        
        .form-label {
            width: 100%;
            margin-bottom: 0;
        }
        
        Input {
            width: 100%;
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
        yield Markdown(FORM_MD)
        with containers.VerticalGroup(classes="form-row"):
            yield Label("Source Path", classes="form-label")
            yield Input(
                placeholder="/path/to/source/directory",
                id="source-input",
            )
        with containers.VerticalGroup(classes="form-row"):
            yield Label("Target Path", classes="form-label")
            yield Input(
                placeholder="/path/to/target/directory",
                id="target-input",
            )
        with containers.HorizontalGroup(id="button-row"):
            yield Button(
                "Start Backup",
                id="start-btn",
                variant="success",
                tooltip="Start the backup process",
            )
            yield Button(
                "Clear",
                id="clear-btn",
                variant="default",
                tooltip="Clear the form",
            )
        yield Label("", id="status-label")


class BackupScreen(PageScreen):
    """Backup screen for starting manual backups."""

    DEFAULT_CSS = """
    BackupScreen {
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
        self._devices: list[dict] = []

    def compose(self) -> ComposeResult:
        with containers.VerticalScroll(id="content"):
            yield Markdown(BACKUP_MD)
            yield DeviceSelector()
            yield BackupForm()
        yield Footer()

    def on_mount(self) -> None:
        asyncio.create_task(self._load_devices())

    async def _load_devices(self) -> None:
        """Load available devices."""
        client = self.app.client

        query = """
        query {
            availableDevices {
                devicePath
                mountPoint
            }
        }
        """
        try:
            result = await client.execute(query)
            self._devices = result.get("availableDevices", [])
            selector = self.query_one(DeviceSelector)
            selector.update_devices(self._devices)
        except Exception:
            pass

    @on(Select.Changed, "#device-select")
    def on_device_selected(self, event: Select.Changed) -> None:
        """Handle device selection - populate source input."""
        if event.value and event.value != Select.BLANK:
            source_input = self.query_one("#source-input", Input)
            source_input.value = str(event.value)

    @on(Button.Pressed, "#start-btn")
    async def on_start_pressed(self) -> None:
        """Handle start backup button press."""
        source_input = self.query_one("#source-input", Input)
        target_input = self.query_one("#target-input", Input)
        status_label = self.query_one("#status-label", Label)

        source = source_input.value.strip()
        target = target_input.value.strip()

        if not source:
            status_label.update("[red]Error: Source path is required[/red]")
            return

        if not target:
            status_label.update("[red]Error: Target path is required[/red]")
            return

        status_label.update("Starting backup...")

        client = self.app.client
        mutation = """
        mutation StartBackup($source: String!, $target: String!) {
            startManualBackup(source: $source, target: $target)
        }
        """
        try:
            result = await client.execute(
                mutation, variable_values={"source": source, "target": target}
            )
            backup_id = result.get("startManualBackup")
            if backup_id:
                status_label.update(
                    f"[green]Backup started! ID: {backup_id[:8]}...[/green]"
                )
                self.notify(
                    f"Backup started: {backup_id[:8]}",
                    title="Backup Started",
                    severity="information",
                )
            else:
                status_label.update("[yellow]Backup queued[/yellow]")
        except Exception as e:
            status_label.update(f"[red]Error: {e}[/red]")
            self.notify(f"Failed to start backup: {e}", title="Error", severity="error")

    @on(Button.Pressed, "#clear-btn")
    def on_clear_pressed(self) -> None:
        """Handle clear button press."""
        self.query_one("#source-input", Input).value = ""
        self.query_one("#target-input", Input).value = ""
        self.query_one("#status-label", Label).update("")
        self.query_one("#device-select", Select).value = Select.BLANK

