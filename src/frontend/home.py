"""Home screen - Dashboard overview for SD Backup."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Optional

from textual import containers
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
    transfer_text: reactive[str] = reactive("")
    progress: reactive[float] = reactive(0.0)
    progress_text: reactive[str] = reactive("")

    def compose(self) -> ComposeResult:
        yield Label("📦 Active Backup", id="backup-title")
        yield Label("", id="backup-info")
        yield ProgressBar(total=100, show_eta=False, id="progress-bar")
        yield Label("", id="progress-text")

    def watch_backup_id(self, value: Optional[str]) -> None:
        self.set_class(value is None, "hidden")

    def watch_transfer_text(self, value: str) -> None:
        self.query_one("#backup-info", Label).update(value)

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
        self._tasks_sub: Optional[asyncio.Task] = None
        self._devices_sub: Optional[asyncio.Task] = None
        self._progress_sub: Optional[asyncio.Task] = None
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
        logger.debug("HomeScreen mounted, starting subscriptions")
        asyncio.create_task(self._load_config())
        self._tasks_sub = asyncio.create_task(self._subscribe_tasks())
        self._devices_sub = asyncio.create_task(self._subscribe_devices())

    def on_unmount(self) -> None:
        for task in (self._tasks_sub, self._devices_sub, self._progress_sub):
            if task:
                task.cancel()

    async def _load_config(self) -> None:
        """Load config (no subscription available for config)."""
        try:
            result = await self.app.client.execute(
                "query { config { autoBackupEnabled } }"
            )
            self.query_one(QuickStats).auto_backup = result.get("config", {}).get(
                "autoBackupEnabled", False
            )
        except Exception as e:
            logger.warning("Failed to load config: %s", e)

    async def _subscribe_tasks(self) -> None:
        """Subscribe to task list updates."""
        query = """subscription { backupTasksUpdated {
            backupId status sizeCompleted sizeTotal source target
        }}"""
        try:
            async for payload in self.app.client.subscribe(query):
                await self._update_from_tasks(payload.get("backupTasksUpdated", []))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning("Tasks subscription error: %s", e)

    async def _subscribe_devices(self) -> None:
        """Subscribe to device list updates."""
        query = """subscription { devicesUpdated { devicePath mountPoint }}"""
        try:
            async for payload in self.app.client.subscribe(query):
                devices = payload.get("devicesUpdated", [])
                self.query_one(QuickStats).devices_count = len(devices)
                self.query_one(DeviceList).update_devices(devices)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning("Devices subscription error: %s", e)

    async def _update_from_tasks(self, tasks: list[dict]) -> None:
        """Update UI from task list."""
        active_statuses = {"PENDING", "IN_PROGRESS"}
        active = next((t for t in tasks if t.get("status") in active_statuses), None)
        active_id = active.get("backupId") if active else None

        self.query_one(QuickStats).active_tasks = sum(
            1 for t in tasks if t.get("status") in active_statuses
        )

        panel = self.query_one(ActiveBackupPanel)
        panel.backup_id = active_id
        if active:
            src, tgt = active.get("source", ""), active.get("target", "")
            panel.transfer_text = f"{self._shorten(src)} -> {self._shorten(tgt)}"
            self._update_progress(panel, active.get("sizeCompleted"), active.get("sizeTotal"))
        else:
            panel.transfer_text = ""

        if active_id != self._active_backup_id:
            self._active_backup_id = active_id
            if self._progress_sub:
                self._progress_sub.cancel()
                with suppress(asyncio.CancelledError):
                    await self._progress_sub
            if active_id:
                self._progress_sub = asyncio.create_task(self._subscribe_progress(active_id))

    def _update_progress(self, panel: ActiveBackupPanel, completed: int | None, total: int | None) -> None:
        completed, total = completed or 0, total or 1
        percent = (completed / total) * 100 if total > 0 else 0
        panel.progress = percent
        panel.progress_text = f"{self._fmt_bytes(completed)} / {self._fmt_bytes(total)} ({percent:.1f}%)"

    def _fmt_bytes(self, size: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    def _shorten(self, path: str, max_len: int = 32) -> str:
        return path if len(path) <= max_len else f"...{path[-(max_len - 3):]}"

    async def _subscribe_progress(self, backup_id: str) -> None:
        """Subscribe to progress updates for active backup."""
        query = """subscription($id: ID!) { progress(backupId: $id) { sizeCompleted sizeTotal }}"""
        panel = self.query_one(ActiveBackupPanel)
        try:
            async for payload in self.app.client.subscribe(query, variable_values={"id": backup_id}):
                p = payload.get("progress", {})
                self._update_progress(panel, p.get("sizeCompleted"), p.get("sizeTotal"))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning("Progress subscription error: %s", e)
