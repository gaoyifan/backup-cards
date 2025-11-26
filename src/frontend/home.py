"""Home screen - Dashboard overview for SD Backup."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Optional

from textual import containers, on
from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widgets import Footer, Label, Markdown, ProgressBar, Rule, Static

from frontend.page import PageScreen

logger = logging.getLogger(__name__)


WELCOME_MD = """\
# 💾 SD Backup Dashboard

Your SD card backup companion. Monitor backups, view connected devices, and manage your data safely.

"""


class QuickStats(containers.HorizontalGroup):
    """Quick stats bar showing key metrics."""

    DEFAULT_CSS = """
    QuickStats {
        height: auto;
        width: 100%;
        margin: 1 0;
        
        .stat-box {
            width: 1fr;
            height: auto;
            padding: 1 2;
            margin: 0 1 0 0;
            background: $surface;
            border: tall $primary 30%;
            
            &:last-child { margin-right: 0; }
        }
        
        .stat-value {
            text-style: bold;
            color: $text-accent;
        }
        
        .stat-label {
            color: $text-muted;
        }
    }
    """

    devices_count: reactive[int] = reactive(0)
    auto_backup: reactive[bool] = reactive(False)
    active_tasks: reactive[int] = reactive(0)

    def compose(self) -> ComposeResult:
        with containers.VerticalGroup(classes="stat-box"):
            yield Label("0", id="devices-value", classes="stat-value")
            yield Label("Devices Connected", classes="stat-label")
        with containers.VerticalGroup(classes="stat-box"):
            yield Label("", id="auto-value", classes="stat-value")
            yield Label("Auto Backup", classes="stat-label")
        with containers.VerticalGroup(classes="stat-box"):
            yield Label("0", id="tasks-value", classes="stat-value")
            yield Label("Active Tasks", classes="stat-label")

    def watch_devices_count(self, value: int) -> None:
        self.query_one("#devices-value", Label).update(str(value))

    def watch_auto_backup(self, value: bool) -> None:
        label = self.query_one("#auto-value", Label)
        if value:
            label.update("[green]ON[/green]")
        else:
            label.update("[dim]OFF[/dim]")

    def watch_active_tasks(self, value: int) -> None:
        label = self.query_one("#tasks-value", Label)
        if value > 0:
            label.update(f"[yellow]{value}[/yellow]")
        else:
            label.update("0")


class ActiveBackupPanel(containers.VerticalGroup):
    """Shows active backup progress."""

    DEFAULT_CSS = """
    ActiveBackupPanel {
        height: auto;
        padding: 1 2;
        background: $boost;
        margin: 1 0;
        border: wide $accent 50%;
        
        #backup-title {
            text-style: bold;
            margin-bottom: 1;
        }
        
        #backup-info {
            margin-bottom: 1;
        }
        
        #progress-text {
            text-align: right;
            color: $text-muted;
            margin-top: 0;
        }
        
        ProgressBar {
            padding: 0;
            margin: 0;
        }
        
        &.hidden {
            display: none;
        }
    }
    """

    backup_id: reactive[Optional[str]] = reactive(None)
    progress: reactive[float] = reactive(0.0)
    progress_text: reactive[str] = reactive("")

    def compose(self) -> ComposeResult:
        yield Label("📦 Active Backup", id="backup-title")
        yield Label("", id="backup-info")
        yield ProgressBar(total=100, show_eta=False, id="progress-bar")
        yield Label("", id="progress-text")

    def watch_backup_id(self, value: Optional[str]) -> None:
        self.set_class(value is None, "hidden")
        if value:
            self.query_one("#backup-info", Label).update(f"Backup ID: [cyan]{value[:12]}...[/cyan]")

    def watch_progress(self, value: float) -> None:
        bar = self.query_one("#progress-bar", ProgressBar)
        bar.progress = value

    def watch_progress_text(self, value: str) -> None:
        self.query_one("#progress-text", Label).update(value)


class DeviceCard(containers.HorizontalGroup):
    """Individual device card."""

    DEFAULT_CSS = """
    DeviceCard {
        height: auto;
        padding: 1 2;
        margin: 0 0 1 0;
        background: $surface;
        border-left: thick $success;
        
        &.unmounted {
            border-left: thick $warning;
            opacity: 0.7;
        }
        
        .device-icon {
            width: 4;
            text-align: center;
        }
        
        .device-info {
            width: 1fr;
        }
        
        .device-path {
            text-style: bold;
        }
        
        .device-mount {
            color: $text-muted;
        }
    }
    """

    def __init__(self, device_path: str, mount_point: str | None) -> None:
        super().__init__()
        self.device_path = device_path
        self.mount_point = mount_point

    def compose(self) -> ComposeResult:
        yield Label("💿", classes="device-icon")
        with containers.VerticalGroup(classes="device-info"):
            yield Label(self.device_path, classes="device-path")
            if self.mount_point:
                yield Label(f"→ {self.mount_point}", classes="device-mount")
            else:
                yield Label("[dim]Not mounted[/dim]", classes="device-mount")

    def on_mount(self) -> None:
        if not self.mount_point:
            self.add_class("unmounted")


class DeviceList(containers.VerticalGroup):
    """Displays available devices."""

    DEFAULT_CSS = """
    DeviceList {
        height: auto;
        padding: 1 2;
        background: $boost;
        margin: 1 0;
        
        #devices-title {
            text-style: bold;
            margin-bottom: 1;
        }
        
        #no-devices {
            color: $text-muted;
            text-style: italic;
            padding: 1;
        }
        
        #device-container {
            height: auto;
        }
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("🔌 Connected Devices", id="devices-title")
        yield containers.VerticalGroup(id="device-container")

    def update_devices(self, devices: list[dict]) -> None:
        container = self.query_one("#device-container", containers.VerticalGroup)
        container.remove_children()
        
        if not devices:
            container.mount(Label("No devices detected", id="no-devices"))
            return

        for device in devices:
            path = device.get("devicePath", "Unknown")
            mount = device.get("mountPoint")
            container.mount(DeviceCard(path, mount))


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

    def __init__(self) -> None:
        super().__init__()
        self._refresh_task: Optional[asyncio.Task] = None
        self._progress_task: Optional[asyncio.Task] = None
        self._active_backup_id: Optional[str] = None

    def compose(self) -> ComposeResult:
        with containers.VerticalScroll(id="content"):
            yield Markdown(WELCOME_MD)
            yield QuickStats()
            yield Rule()
            yield ActiveBackupPanel()
            yield DeviceList()
        yield Footer()

    def on_mount(self) -> None:
        logger.debug("HomeScreen mounted, starting refresh loop")
        self._refresh_task = asyncio.create_task(self._refresh_loop())

    def on_unmount(self) -> None:
        logger.debug("HomeScreen unmounting, cancelling tasks")
        if self._refresh_task:
            self._refresh_task.cancel()
        if self._progress_task:
            self._progress_task.cancel()

    async def _refresh_loop(self) -> None:
        """Periodically refresh dashboard data."""
        logger.debug("HomeScreen refresh loop started")
        while True:
            if self.app.auto_refresh_enabled:
                await self._refresh_data()
            await asyncio.sleep(2)

    async def _refresh_data(self) -> None:
        """Fetch and update dashboard data."""
        client = self.app.client

        query = """
        query Dashboard {
            config {
                autoBackupEnabled
            }
            backupTasks(limit: 5) {
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
            logger.debug("Executing dashboard query")
            result = await client.execute(query)
            logger.debug("Dashboard query result: %s", result)
        except Exception as e:
            logger.warning("Failed to fetch dashboard data: %s", e)
            return

        # Update quick stats
        stats = self.query_one(QuickStats)
        config = result.get("config", {})
        devices = result.get("availableDevices", [])
        tasks = result.get("backupTasks", [])
        
        stats.devices_count = len(devices)
        stats.auto_backup = config.get("autoBackupEnabled", False)
        stats.active_tasks = sum(1 for t in tasks if t.get("status") in {"PENDING", "IN_PROGRESS"})

        # Update devices
        device_list = self.query_one(DeviceList)
        device_list.update_devices(devices)

        # Check for active backup
        active = next(
            (t for t in tasks if t.get("status") in {"PENDING", "IN_PROGRESS"}), None
        )
        active_id = active.get("backupId") if active else None

        # Update active backup panel
        backup_panel = self.query_one(ActiveBackupPanel)
        backup_panel.backup_id = active_id

        if active_id != self._active_backup_id:
            self._active_backup_id = active_id
            await self._restart_progress_subscription(active_id)

        if active:
            completed = active.get("sizeCompleted", 0) or 0
            total = active.get("sizeTotal", 1) or 1
            percent = (completed / total) * 100 if total > 0 else 0
            backup_panel.progress = percent
            backup_panel.progress_text = f"{self._format_bytes(completed)} / {self._format_bytes(total)} ({percent:.1f}%)"

    def _format_bytes(self, size: int) -> str:
        """Format bytes to human readable string."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

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
        logger.debug("Starting progress subscription for backup %s", backup_id)
        client = self.app.client
        query = """
        subscription($id: ID!) {
            progress(backupId: $id) {
                sizeCompleted
                sizeTotal
            }
        }
        """
        backup_panel = self.query_one(ActiveBackupPanel)
        try:
            async for payload in client.subscribe(query, variable_values={"id": backup_id}):
                progress = payload.get("progress", {})
                completed = progress.get("sizeCompleted", 0) or 0
                total = progress.get("sizeTotal", 1) or 1
                percent = (completed / total) * 100 if total > 0 else 0
                backup_panel.progress = percent
                backup_panel.progress_text = f"{self._format_bytes(completed)} / {self._format_bytes(total)} ({percent:.1f}%)"
        except asyncio.CancelledError:
            logger.debug("Progress subscription cancelled for backup %s", backup_id)
        except Exception as e:
            logger.warning("Progress subscription error for backup %s: %s", backup_id, e)
