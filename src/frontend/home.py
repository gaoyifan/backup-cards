"""Home screen - Dashboard overview for SD Backup."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Optional

from textual import containers, on, work
from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widgets import Digits, Footer, Label, Markdown, Static

from frontend.page import PageScreen


WELCOME_MD = """\
# SD Backup Dashboard

Welcome to SD Backup! This application helps you backup SD cards and directories.

Use the keyboard shortcuts shown in the footer to navigate between screens.

"""

STATUS_MD = """\
## System Status

Current configuration and active backup status.
"""

DEVICES_MD = """\
## Connected Devices

Available SD cards and storage devices detected on the system.
"""


class StatusPanel(containers.VerticalGroup):
    """Displays current config and active backup status."""

    DEFAULT_CSS = """
    StatusPanel {
        height: auto;
        padding: 1 2;
        background: $boost;
        margin: 1 0;
        
        .status-row {
            height: auto;
            margin: 0 0 1 0;
        }
        
        .status-label {
            width: 20;
            text-style: bold;
        }
        
        .status-value {
            width: 1fr;
        }
        
        #progress-section {
            margin-top: 1;
            padding: 1;
            background: $surface;
            height: auto;
        }
        
        #progress-label {
            text-style: italic;
            color: $text-muted;
        }
        
        Digits {
            width: auto;
        }
    }
    """

    auto_backup_enabled: reactive[bool] = reactive(False)
    auto_backup_target: reactive[str] = reactive("")
    active_backup_id: reactive[Optional[str]] = reactive(None)
    progress_percent: reactive[float] = reactive(0.0)
    progress_text: reactive[str] = reactive("No active backup")

    def compose(self) -> ComposeResult:
        yield Markdown(STATUS_MD)
        with containers.HorizontalGroup(classes="status-row"):
            yield Label("Auto Backup:", classes="status-label")
            yield Label(id="auto-status", classes="status-value")
        with containers.HorizontalGroup(classes="status-row"):
            yield Label("Target Template:", classes="status-label")
            yield Label(id="target-template", classes="status-value")
        with containers.VerticalGroup(id="progress-section"):
            yield Label("Active Backup Progress", classes="status-label")
            yield Label(id="progress-label")
            yield Digits("0.0%", id="progress-digits")

    def watch_auto_backup_enabled(self, value: bool) -> None:
        label = self.query_one("#auto-status", Label)
        label.update("Enabled" if value else "Disabled")

    def watch_auto_backup_target(self, value: str) -> None:
        label = self.query_one("#target-template", Label)
        label.update(value or "(not set)")

    def watch_progress_text(self, value: str) -> None:
        label = self.query_one("#progress-label", Label)
        label.update(value)

    def watch_progress_percent(self, value: float) -> None:
        digits = self.query_one("#progress-digits", Digits)
        digits.update(f"{value:.1f}%")


class DeviceList(containers.VerticalGroup):
    """Displays available devices."""

    DEFAULT_CSS = """
    DeviceList {
        height: auto;
        padding: 1 2;
        background: $boost;
        margin: 1 0;
        
        .device-item {
            height: auto;
            padding: 0 1;
            margin: 0 0 1 0;
            background: $surface;
        }
        
        .device-path {
            text-style: bold;
            color: $text-primary;
        }
        
        .mount-point {
            color: $text-muted;
            text-style: italic;
        }
        
        #no-devices {
            color: $text-muted;
            text-style: italic;
            padding: 1;
        }
    }
    """

    def compose(self) -> ComposeResult:
        yield Markdown(DEVICES_MD)
        yield Static("Loading devices...", id="device-container")

    def update_devices(self, devices: list[dict]) -> None:
        container = self.query_one("#device-container", Static)
        if not devices:
            container.update("No devices detected.")
            return

        lines = []
        for device in devices:
            path = device.get("devicePath", "Unknown")
            mount = device.get("mountPoint", "Not mounted")
            lines.append(f"[bold]{path}[/bold] → {mount}")
        container.update("\n".join(lines))


class HomeScreen(PageScreen):
    """Home screen showing dashboard overview."""

    DEFAULT_CSS = """
    HomeScreen {
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
        self._refresh_task: Optional[asyncio.Task] = None
        self._progress_task: Optional[asyncio.Task] = None
        self._active_backup_id: Optional[str] = None

    def compose(self) -> ComposeResult:
        with containers.VerticalScroll(id="content"):
            yield Markdown(WELCOME_MD)
            yield StatusPanel()
            yield DeviceList()
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_task = asyncio.create_task(self._refresh_loop())

    def on_unmount(self) -> None:
        if self._refresh_task:
            self._refresh_task.cancel()
        if self._progress_task:
            self._progress_task.cancel()

    async def _refresh_loop(self) -> None:
        """Periodically refresh dashboard data."""
        while True:
            await self._refresh_data()
            await asyncio.sleep(3)

    async def _refresh_data(self) -> None:
        """Fetch and update dashboard data."""
        client = self.app.client

        # Fetch config and tasks
        query = """
        query Dashboard {
            config {
                autoBackupEnabled
                autoBackupTargetPath
            }
            backupTasks(limit: 1) {
                backupId
                status
                sizeCompleted
                sizeTotal
            }
            availableDevices {
                devicePath
                mountPoint
            }
        }
        """
        try:
            result = await client.execute(query)
        except Exception:
            return

        # Update status panel
        status_panel = self.query_one(StatusPanel)
        config = result.get("config", {})
        status_panel.auto_backup_enabled = config.get("autoBackupEnabled", False)
        status_panel.auto_backup_target = config.get("autoBackupTargetPath", "")

        # Update devices
        device_list = self.query_one(DeviceList)
        devices = result.get("availableDevices", [])
        device_list.update_devices(devices)

        # Check for active backup
        tasks = result.get("backupTasks", [])
        active = next(
            (t for t in tasks if t.get("status") in {"PENDING", "IN_PROGRESS"}), None
        )
        active_id = active.get("backupId") if active else None

        if active_id != self._active_backup_id:
            self._active_backup_id = active_id
            status_panel.active_backup_id = active_id
            await self._restart_progress_subscription(active_id)

        # Update progress from query result if available
        if active:
            completed = active.get("sizeCompleted", 0) or 0
            total = active.get("sizeTotal", 1) or 1
            percent = (completed / total) * 100 if total > 0 else 0
            status_panel.progress_percent = percent
            status_panel.progress_text = f"Backup {active_id[:8]}... ({completed}/{total} bytes)"
        elif not self._active_backup_id:
            status_panel.progress_percent = 0.0
            status_panel.progress_text = "No active backup"

    async def _restart_progress_subscription(self, backup_id: Optional[str]) -> None:
        """Start or stop progress subscription."""
        if self._progress_task:
            self._progress_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._progress_task
            self._progress_task = None

        if backup_id:
            self._progress_task = asyncio.create_task(
                self._consume_progress(backup_id)
            )

    async def _consume_progress(self, backup_id: str) -> None:
        """Subscribe to progress updates for active backup."""
        client = self.app.client
        query = """
        subscription($id: ID!) {
            progress(backupId: $id) {
                sizeCompleted
                sizeTotal
            }
        }
        """
        status_panel = self.query_one(StatusPanel)
        try:
            async for payload in client.subscribe(query, variable_values={"id": backup_id}):
                progress = payload.get("progress", {})
                completed = progress.get("sizeCompleted", 0) or 0
                total = progress.get("sizeTotal", 1) or 1
                percent = (completed / total) * 100 if total > 0 else 0
                status_panel.progress_percent = percent
                status_panel.progress_text = f"Backup {backup_id[:8]}... ({completed}/{total} bytes)"
        except Exception:
            pass

