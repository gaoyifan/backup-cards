"""Home screen - Dashboard overview for SD Backup."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from textual import containers
from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widgets import Footer, Label, Markdown, ProgressBar, Rule

from frontend.page import PageScreen
from frontend.utils import ProgressSubscriptionManager, fmt_progress, shorten_path

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
        .stat-value { text-style: bold; color: $text-accent; }
        .stat-label { color: $text-muted; }
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
        self.query_one("#auto-value", Label).update("[green]ON[/green]" if value else "[dim]OFF[/dim]")

    def watch_active_tasks(self, value: int) -> None:
        self.query_one("#tasks-value", Label).update(f"[yellow]{value}[/yellow]" if value > 0 else "0")


class ActiveTaskCard(containers.VerticalGroup):
    """Shows a single active task with progress."""

    DEFAULT_CSS = """
    ActiveTaskCard {
        height: auto;
        padding: 1 2;
        background: $surface;
        margin: 0 0 1 0;
        border-left: thick $accent;
        
        .task-header { height: auto; }
        .task-id { color: $text-muted; text-style: italic; }
        .task-path { margin: 0 0 1 0; }
        .progress-text { text-align: right; color: $text-muted; }
        ProgressBar { padding: 0; margin: 0; }
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
        yield Label(f"{shorten_path(self.source, 30)} → {shorten_path(self.target, 30)}", classes="task-path")
        yield ProgressBar(total=100, show_eta=False, id=f"progress-{self.backup_id}")
        yield Label("0%", id=f"text-{self.backup_id}", classes="progress-text")

    def update_progress(self, completed: int, total: int) -> None:
        percent = (completed / total) * 100 if total > 0 else 0
        self.query_one(f"#progress-{self.backup_id}", ProgressBar).progress = percent
        self.query_one(f"#text-{self.backup_id}", Label).update(fmt_progress(completed, total))


class ActiveTasksList(containers.VerticalGroup):
    """Container for all active tasks."""

    DEFAULT_CSS = """
    ActiveTasksList {
        height: auto;
        padding: 1 2;
        background: $boost;
        margin: 1 0;
        
        &.hidden { display: none; }
        #active-title { text-style: bold; margin-bottom: 1; }
        #active-container { height: auto; }
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("📦 Active Tasks", id="active-title")
        yield containers.VerticalGroup(id="active-container")

    def update_tasks(self, tasks: list[dict]) -> None:
        container = self.query_one("#active-container", containers.VerticalGroup)
        container.remove_children()

        active = [t for t in tasks if t.get("status") in {"PENDING", "IN_PROGRESS"}]
        if not active:
            self.add_class("hidden")
            return

        self.remove_class("hidden")
        for task in active:
            card = ActiveTaskCard(task.get("backupId", ""), task.get("source", ""), task.get("target", ""))
            container.mount(card)
            card.update_progress(task.get("sizeCompleted", 0) or 0, task.get("sizeTotal", 0) or 0)

    def update_progress(self, backup_id: str, completed: int, total: int) -> None:
        try:
            card = self.query_one(f"#progress-{backup_id}", ProgressBar).parent
            if isinstance(card, ActiveTaskCard):
                card.update_progress(completed, total)
        except Exception:
            pass


class DeviceCard(containers.HorizontalGroup):
    """Individual device card."""

    DEFAULT_CSS = """
    DeviceCard {
        height: auto;
        padding: 1 2;
        margin: 0 0 1 0;
        background: $surface;
        border-left: thick $success;
        
        &.unmounted { border-left: thick $warning; opacity: 0.7; }
        .device-icon { width: 4; text-align: center; }
        .device-info { width: 1fr; }
        .device-path { text-style: bold; }
        .device-mount { color: $text-muted; }
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
            yield Label(f"→ {self.mount_point}" if self.mount_point else "[dim]Not mounted[/dim]", classes="device-mount")

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
        
        #devices-title { text-style: bold; margin-bottom: 1; }
        #no-devices { color: $text-muted; text-style: italic; padding: 1; }
        #device-container { height: auto; }
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
        for d in devices:
            container.mount(DeviceCard(d.get("devicePath", "Unknown"), d.get("mountPoint")))


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
        Markdown { background: transparent; margin: 0; padding: 0; }
        Rule { margin: 1 0; }
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._tasks_sub: Optional[asyncio.Task] = None
        self._devices_sub: Optional[asyncio.Task] = None
        self._progress_mgr: Optional[ProgressSubscriptionManager] = None

    def compose(self) -> ComposeResult:
        with containers.VerticalScroll(id="content"):
            yield Markdown(WELCOME_MD)
            yield QuickStats()
            yield Rule()
            yield ActiveTasksList()
            yield DeviceList()
        yield Footer()

    def on_mount(self) -> None:
        self._progress_mgr = ProgressSubscriptionManager(
            lambda: self.app.client, lambda bid, c, t: self.query_one(ActiveTasksList).update_progress(bid, c, t)
        )
        asyncio.create_task(self._load_config())
        self._tasks_sub = asyncio.create_task(self._subscribe_tasks())
        self._devices_sub = asyncio.create_task(self._subscribe_devices())

    def on_screen_resume(self) -> None:
        """Reload config when screen becomes active again (e.g., after settings change)."""
        asyncio.create_task(self._load_config())

    def on_unmount(self) -> None:
        for task in (self._tasks_sub, self._devices_sub):
            if task:
                task.cancel()
        if self._progress_mgr:
            self._progress_mgr.cancel_all()

    async def _load_config(self) -> None:
        for attempt in range(10):
            try:
                result = await self.app.client.execute("query { config { autoBackupEnabled } }")
                self.query_one(QuickStats).auto_backup = result.get("config", {}).get("autoBackupEnabled", False)
                return
            except asyncio.CancelledError:
                return
            except Exception as e:
                if attempt == 9:
                    logger.warning("Failed to load config: %s", e)
                await asyncio.sleep(0.5)

    async def _subscribe_tasks(self) -> None:
        query = """subscription { backupTasksUpdated { backupId status sizeCompleted sizeTotal source target }}"""
        while True:
            try:
                async for payload in self.app.client.subscribe(query):
                    tasks = payload.get("backupTasksUpdated", [])
                    self.query_one(QuickStats).active_tasks = sum(1 for t in tasks if t.get("status") in {"PENDING", "IN_PROGRESS"})
                    self.query_one(ActiveTasksList).update_tasks(tasks)
                    self._progress_mgr.sync(tasks)
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning("Tasks subscription error: %s, retrying...", e)
                await asyncio.sleep(1)

    async def _subscribe_devices(self) -> None:
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
