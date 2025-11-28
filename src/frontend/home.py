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


class ActiveTaskCard(containers.VerticalGroup):
    """Shows a single active task with progress."""

    DEFAULT_CSS = """
    ActiveTaskCard {
        height: auto;
        padding: 1 2;
        background: $surface;
        margin: 0 0 1 0;
        border-left: thick $accent;
        
        .task-header {
            height: auto;
        }
        
        .task-id {
            color: $text-muted;
            text-style: italic;
        }
        
        .task-path {
            margin: 0 0 1 0;
        }
        
        .progress-text {
            text-align: right;
            color: $text-muted;
        }
        
        ProgressBar {
            padding: 0;
            margin: 0;
        }
    }
    """

    def __init__(self, backup_id: str, source: str, target: str) -> None:
        super().__init__()
        self.backup_id = backup_id
        self.source = source
        self.target = target

    def compose(self) -> ComposeResult:
        with containers.HorizontalGroup(classes="task-header"):
            yield Label(f"📦 {self.backup_id[:8]}...", classes="task-id")
        yield Label(f"{self._shorten(self.source)} → {self._shorten(self.target)}", classes="task-path")
        yield ProgressBar(total=100, show_eta=False, id=f"progress-{self.backup_id}")
        yield Label("0%", id=f"text-{self.backup_id}", classes="progress-text")

    def _shorten(self, path: str, max_len: int = 30) -> str:
        return path if len(path) <= max_len else f"...{path[-(max_len - 3):]}"

    def update_progress(self, completed: int, total: int) -> None:
        percent = (completed / total) * 100 if total > 0 else 0
        self.query_one(f"#progress-{self.backup_id}", ProgressBar).progress = percent
        self.query_one(f"#text-{self.backup_id}", Label).update(
            f"{self._fmt_bytes(completed)} / {self._fmt_bytes(total)} ({percent:.1f}%)"
        )

    def _fmt_bytes(self, size: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


class ActiveTasksList(containers.VerticalGroup):
    """Container for all active tasks."""

    DEFAULT_CSS = """
    ActiveTasksList {
        height: auto;
        padding: 1 2;
        background: $boost;
        margin: 1 0;
        
        &.hidden { display: none; }
        
        #active-title {
            text-style: bold;
            margin-bottom: 1;
        }
        
        #no-active {
            color: $text-muted;
            text-style: italic;
        }
        
        #active-container {
            height: auto;
        }
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("📦 Active Tasks", id="active-title")
        yield containers.VerticalGroup(id="active-container")

    def update_tasks(self, tasks: list[dict]) -> None:
        """Update the list of active tasks."""
        container = self.query_one("#active-container", containers.VerticalGroup)
        container.remove_children()

        active = [t for t in tasks if t.get("status") in {"PENDING", "IN_PROGRESS"}]
        
        if not active:
            self.add_class("hidden")
            return

        self.remove_class("hidden")
        for task in active:
            card = ActiveTaskCard(
                task.get("backupId", ""),
                task.get("source", ""),
                task.get("target", ""),
            )
            container.mount(card)
            # Set initial progress
            completed = task.get("sizeCompleted", 0) or 0
            total = task.get("sizeTotal", 0) or 0
            card.update_progress(completed, total)

    def update_progress(self, backup_id: str, completed: int, total: int) -> None:
        """Update progress for a specific task."""
        try:
            card = self.query_one(f"#progress-{backup_id}", ProgressBar).parent
            if isinstance(card, ActiveTaskCard):
                card.update_progress(completed, total)
        except Exception:
            pass  # Card may not exist yet


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
        self._progress_subs: dict[str, asyncio.Task] = {}

    def compose(self) -> ComposeResult:
        with containers.VerticalScroll(id="content"):
            yield Markdown(WELCOME_MD)
            yield QuickStats()
            yield Rule()
            yield ActiveTasksList()
            yield DeviceList()
        yield Footer()

    def on_mount(self) -> None:
        logger.debug("HomeScreen mounted, starting subscriptions")
        asyncio.create_task(self._load_config())
        self._tasks_sub = asyncio.create_task(self._subscribe_tasks())
        self._devices_sub = asyncio.create_task(self._subscribe_devices())

    def on_unmount(self) -> None:
        for task in (self._tasks_sub, self._devices_sub):
            if task:
                task.cancel()
        for sub in self._progress_subs.values():
            sub.cancel()

    async def _load_config(self) -> None:
        """Load config with retry (no subscription available for config)."""
        for attempt in range(10):
            try:
                result = await self.app.client.execute(
                    "query { config { autoBackupEnabled } }"
                )
                self.query_one(QuickStats).auto_backup = result.get("config", {}).get(
                    "autoBackupEnabled", False
                )
                return
            except asyncio.CancelledError:
                return
            except Exception as e:
                if attempt < 9:
                    await asyncio.sleep(0.5)
                else:
                    logger.warning("Failed to load config: %s", e)

    async def _subscribe_tasks(self) -> None:
        """Subscribe to task list updates with retry."""
        query = """subscription { backupTasksUpdated {
            backupId status sizeCompleted sizeTotal source target
        }}"""
        while True:
            try:
                async for payload in self.app.client.subscribe(query):
                    tasks = payload.get("backupTasksUpdated", [])
                    self._update_from_tasks(tasks)
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning("Tasks subscription error: %s, retrying...", e)
                await asyncio.sleep(1)

    async def _subscribe_devices(self) -> None:
        """Subscribe to device list updates with retry."""
        query = """subscription { devicesUpdated { devicePath mountPoint }}"""
        while True:
            try:
                async for payload in self.app.client.subscribe(query):
                    devices = payload.get("devicesUpdated", [])
                    self.query_one(QuickStats).devices_count = len(devices)
                    self.query_one(DeviceList).update_devices(devices)
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning("Devices subscription error: %s, retrying...", e)
                await asyncio.sleep(1)

    def _update_from_tasks(self, tasks: list[dict]) -> None:
        """Update UI from task list."""
        active_statuses = {"PENDING", "IN_PROGRESS"}
        active_count = sum(1 for t in tasks if t.get("status") in active_statuses)

        self.query_one(QuickStats).active_tasks = active_count
        self.query_one(ActiveTasksList).update_tasks(tasks)
        self._sync_progress_subscriptions(tasks)

    def _sync_progress_subscriptions(self, tasks: list[dict]) -> None:
        """Start/stop progress subscriptions for active tasks."""
        active_ids = {t["backupId"] for t in tasks if t.get("status") == "IN_PROGRESS"}

        # Stop subscriptions for tasks no longer active
        for backup_id in list(self._progress_subs.keys()):
            if backup_id not in active_ids:
                self._progress_subs.pop(backup_id).cancel()

        # Start subscriptions for new active tasks
        for backup_id in active_ids:
            if backup_id not in self._progress_subs:
                self._progress_subs[backup_id] = asyncio.create_task(
                    self._subscribe_progress(backup_id)
                )

    async def _subscribe_progress(self, backup_id: str) -> None:
        """Subscribe to progress updates for an active task."""
        query = """subscription($id: ID!) { progress(backupId: $id) { sizeCompleted sizeTotal }}"""
        try:
            async for payload in self.app.client.subscribe(query, variable_values={"id": backup_id}):
                p = payload.get("progress", {})
                self.query_one(ActiveTasksList).update_progress(
                    backup_id, p.get("sizeCompleted", 0), p.get("sizeTotal", 0)
                )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning("Progress subscription error: %s", e)
        finally:
            self._progress_subs.pop(backup_id, None)
