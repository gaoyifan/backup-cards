"""Backup screen - Manual backup form for SD Backup."""

from __future__ import annotations

import asyncio
import logging

from textual import containers, events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.validation import Length
from textual.widgets import Button, Footer, Input, Label, Markdown, Rule, Select

from frontend.page import PageScreen
from frontend.path_hints import PathHintBox, PathHintManager

logger = logging.getLogger(__name__)


BACKUP_MD = """\
# 🚀 Start Manual Backup

Create a new backup by selecting a source and target location.

"""


class DeviceSelector(containers.VerticalGroup):
    """Device selection widget."""

    DEFAULT_CSS = """
    DeviceSelector {
        height: auto;
        padding: 1 2;
        background: $boost;
        margin: 1 0;
        border-left: thick $accent;
        
        #device-title {
            text-style: bold;
            margin-bottom: 1;
        }
        
        #device-hint {
            color: $text-muted;
            margin-bottom: 1;
        }
        
        Select {
            width: 100%;
        }
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("💿 Quick Select Device", id="device-title")
        yield Label("Choose a connected device to auto-fill the source path", id="device-hint")
        yield Select(
            [],
            prompt="Select a device...",
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
                label = f"💿 {path}  →  {mount}"
                value = mount
            else:
                label = f"💿 {path}  [dim](not mounted)[/dim]"
                value = path
            options.append((label, value))

        if not options:
            options = [("No devices available", "")]
        select.set_options(options)


class BackupForm(containers.VerticalGroup):
    """Backup form widget."""

    DEFAULT_CSS = """
    BackupForm {
        height: auto;
        padding: 1 2;
        background: $boost;
        margin: 1 0;
        
        #form-title {
            text-style: bold;
            margin-bottom: 1;
        }
        
        .form-field {
            height: auto;
            margin-bottom: 1;
        }
        
        .field-label {
            margin-bottom: 0;
            color: $text;
        }
        
        .field-hint {
            color: $text-muted;
            text-style: italic;
            margin-bottom: 0;
        }
        
        Input {
            width: 100%;
            margin-top: 0;
        }
        
        Input.-valid {
            border: tall $success;
        }
        
        Input.-invalid {
            border: tall $error;
        }
        
        #button-row {
            margin-top: 2;
        }
        
        #start-btn {
            margin-right: 1;
        }
        
        #status-container {
            height: auto;
            margin-top: 1;
            padding: 1;
            background: $surface;
            
            &.hidden { display: none; }
            &.success { border-left: thick $success; }
            &.error { border-left: thick $error; }
            &.info { border-left: thick $accent; }
        }
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("📝 Backup Details", id="form-title")
        with containers.VerticalGroup(classes="form-field"):
            yield Label("Source Path", classes="field-label")
            yield Label("Directory or mount point to backup", classes="field-hint")
            yield Input(
                placeholder="/media/sdcard or /home/user/data",
                id="source-input",
                validators=[Length(minimum=1)],
            )
            yield PathHintBox(id="source-hints", classes="hidden")
        with containers.VerticalGroup(classes="form-field"):
            yield Label("Target Path", classes="field-label")
            yield Label("Where to save the backup", classes="field-hint")
            yield Input(
                placeholder="/backups/my-backup",
                id="target-input",
                validators=[Length(minimum=1)],
            )
            yield PathHintBox(id="target-hints", classes="hidden")
        with containers.HorizontalGroup(id="button-row"):
            yield Button(
                "▶ Start Backup",
                id="start-btn",
                variant="success",
                tooltip="Start the backup process",
            )
            yield Button(
                "Clear",
                id="clear-btn",
                variant="default",
                tooltip="Clear all fields",
            )
        with containers.VerticalGroup(id="status-container", classes="hidden"):
            yield Label("", id="status-label")


class BackupScreen(PageScreen):
    """Backup screen for starting manual backups."""

    DEFAULT_CSS = """
    BackupScreen {
        align-horizontal: center;
        
        #content {
            width: 100%;
            max-width: 90;
            padding: 1 2;
            height: 1fr;
            overflow-y: auto;
            scrollbar-gutter: stable;
        }
        
        Markdown {
            background: transparent;
            margin: 0;
            padding: 0;
        }
        
        Rule {
            margin: 1 0;
        }
    }
    """

    BINDINGS = [
        Binding("ctrl+enter", "submit", "Start Backup", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._devices: list[dict] = []
        self._path_hints = PathHintManager(self)
        self._path_hints.register("source-input", "source-hints")
        self._path_hints.register("target-input", "target-hints")

    def compose(self) -> ComposeResult:
        with containers.VerticalScroll(id="content"):
            yield Markdown(BACKUP_MD)
            yield DeviceSelector()
            yield Rule()
            yield BackupForm()
        yield Footer()

    def on_mount(self) -> None:
        logger.debug("BackupScreen mounted, loading devices")
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
            logger.debug("Loading available devices")
            result = await client.execute(query)
            self._devices = result.get("availableDevices", [])
            logger.debug("Loaded %d devices", len(self._devices))
            selector = self.query_one(DeviceSelector)
            selector.update_devices(self._devices)
        except Exception as e:
            logger.warning("Failed to load devices: %s", e)

    def _show_status(self, message: str, status_type: str = "info") -> None:
        """Show status message."""
        container = self.query_one("#status-container", containers.VerticalGroup)
        label = self.query_one("#status-label", Label)

        container.remove_class("hidden", "success", "error", "info")
        container.add_class(status_type)
        label.update(message)

    def _hide_status(self) -> None:
        """Hide status message."""
        container = self.query_one("#status-container", containers.VerticalGroup)
        container.add_class("hidden")

    @on(Input.Changed, "#source-input")
    def on_source_input_changed(self, event: Input.Changed) -> None:
        """Update hints when the source path changes."""
        self._path_hints.handle_change("source-input", event.value)

    @on(Input.Changed, "#target-input")
    def on_target_input_changed(self, event: Input.Changed) -> None:
        """Update hints when the target path changes."""
        self._path_hints.handle_change("target-input", event.value)

    @on(Input.Blurred, "#source-input")
    def on_source_input_blurred(self, _: Input.Blurred) -> None:
        """Hide hints when the source loses focus."""
        self._path_hints.handle_blur("source-input")

    @on(Input.Blurred, "#target-input")
    def on_target_input_blurred(self, _: Input.Blurred) -> None:
        """Hide hints when the target loses focus."""
        self._path_hints.handle_blur("target-input")

    @on(Select.Changed, "#device-select")
    def on_device_selected(self, event: Select.Changed) -> None:
        """Handle device selection - populate source input."""
        if event.value and event.value != Select.BLANK and event.value != "":
            source_input = self.query_one("#source-input", Input)
            source_input.value = str(event.value)
            source_input.focus()
            self._hide_status()

    @on(Button.Pressed, "#start-btn")
    async def on_start_pressed(self) -> None:
        """Handle start backup button press."""
        await self._start_backup()

    async def _start_backup(self) -> None:
        """Start the backup process."""
        source_input = self.query_one("#source-input", Input)
        target_input = self.query_one("#target-input", Input)

        source = source_input.value.strip()
        target = target_input.value.strip()

        if not source:
            self._show_status("⚠️  Source path is required", "error")
            source_input.focus()
            return

        if not target:
            self._show_status("⚠️  Target path is required", "error")
            target_input.focus()
            return

        self._show_status("⏳ Starting backup...", "info")
        logger.info("Starting manual backup: %s -> %s", source, target)

        client = self.app.client
        mutation = """
        mutation StartBackup($source: String!, $target: String!) {
            startManualBackup(source: $source, target: $target)
        }
        """
        try:
            result = await client.execute(mutation, variable_values={"source": source, "target": target})
            backup_id = result.get("startManualBackup")
            if backup_id:
                logger.info("Backup started successfully with ID: %s", backup_id)
                self._show_status(f"✓ Backup started successfully!\n  ID: {backup_id[:16]}...", "success")
                self.notify(
                    f"Backup started: {backup_id[:8]}",
                    title="Success",
                    severity="information",
                )
            else:
                logger.warning("Backup mutation returned no ID")
                self._show_status("⚠️  Backup queued", "info")
        except Exception as e:
            logger.error("Failed to start backup: %s", e)
            self._show_status(f"✗ Failed to start backup:\n  {e}", "error")
            self.notify(f"Failed: {e}", title="Error", severity="error")

    @on(Button.Pressed, "#clear-btn")
    def on_clear_pressed(self) -> None:
        """Handle clear button press."""
        self.query_one("#source-input", Input).value = ""
        self.query_one("#target-input", Input).value = ""
        self.query_one("#device-select", Select).value = Select.BLANK
        self._hide_status()
        self.query_one("#source-input", Input).focus()

    def action_submit(self) -> None:
        """Handle Ctrl+Enter to submit form."""
        asyncio.create_task(self._start_backup())

    def on_unmount(self) -> None:
        """Ensure background hint lookups are stopped."""
        self._path_hints.reset()

    def on_key(self, event: events.Key) -> None:
        """Intercept Tab for quick autocompletion."""
        focused = self.focused
        if isinstance(focused, Input) and focused.id:
            if event.key == "tab":
                if self._path_hints.apply_tab_completion(focused):
                    event.stop()
                    return
            elif event.key in {"up", "down"}:
                delta = 1 if event.key == "down" else -1
                if self._path_hints.adjust_selection(focused.id, delta):
                    event.stop()
                    return
        parent_handler = getattr(super(), "on_key", None)
        if parent_handler is not None:
            parent_handler(event)
