"""Tasks screen - Backup history for SD Backup."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from textual import containers, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import Button, DataTable, Footer, Label, Markdown, ProgressBar, Rule
from textual.widgets._data_table import RowDoesNotExist

from frontend.page import PageScreen
from frontend.utils import ProgressSubscriptionManager, calc_percent, fmt_progress

logger = logging.getLogger(__name__)

TASKS_MD = """\
# 📋 Backup Tasks

View your backup history and manage running tasks. Select a row to see details.

"""

STATUS_STYLES = {
    "COMPLETED": "[green]✓ Completed[/green]",
    "IN_PROGRESS": "[yellow]● Running[/yellow]",
    "PENDING": "[cyan]○ Pending[/cyan]",
    "FAILED": "[red]✗ Failed[/red]",
    "CANCELLED": "[dim]◌ Cancelled[/dim]",
}


class TaskDetail(containers.VerticalGroup):
    """Displays details for a selected task."""

    DEFAULT_CSS = """
    TaskDetail {
        height: auto;
        padding: 1 2;
        background: $boost;
        margin: 1 0;
        border: wide $primary 30%;
        
        &.hidden { display: none; }
        #detail-header { height: auto; margin-bottom: 1; }
        #detail-title { text-style: bold; width: 1fr; }
        #detail-status { width: auto; }
        .detail-section { height: auto; margin-bottom: 1; padding: 1; background: $surface; }
        .detail-label { color: $text-muted; margin-bottom: 0; }
        .detail-value { text-style: bold; }
        #progress-section { margin-top: 1; }
        #cancel-btn { margin-top: 1; }
    }
    """

    def compose(self) -> ComposeResult:
        with containers.HorizontalGroup(id="detail-header"):
            yield Label("Task Details", id="detail-title")
            yield Label("", id="detail-status")
        with containers.VerticalGroup(classes="detail-section"):
            yield Label("Source", classes="detail-label")
            yield Label("", id="detail-source", classes="detail-value")
        with containers.VerticalGroup(classes="detail-section"):
            yield Label("Target", classes="detail-label")
            yield Label("", id="detail-target", classes="detail-value")
        with containers.HorizontalGroup():
            with containers.VerticalGroup(classes="detail-section"):
                yield Label("Backup ID", classes="detail-label")
                yield Label("", id="detail-id", classes="detail-value")
            with containers.VerticalGroup(classes="detail-section"):
                yield Label("Type", classes="detail-label")
                yield Label("", id="detail-type", classes="detail-value")
        with containers.VerticalGroup(id="progress-section"):
            yield Label("Progress", classes="detail-label")
            yield ProgressBar(total=100, show_eta=False, id="detail-progress-bar")
            yield Label("", id="detail-progress-text")
        yield Button("Cancel Backup", id="cancel-btn", variant="error", disabled=True, tooltip="Cancel this backup task")

    def on_mount(self) -> None:
        self.add_class("hidden")

    def update_task(self, task: Optional[dict]) -> None:
        if not task:
            self.add_class("hidden")
            return

        self.remove_class("hidden")
        status = task.get("status", "")

        self.query_one("#detail-id", Label).update(task.get("backupId", "")[:16] + "...")
        self.query_one("#detail-status", Label).update(STATUS_STYLES.get(status, status))
        self.query_one("#detail-type", Label).update(task.get("type", ""))
        self.query_one("#detail-source", Label).update(task.get("source", ""))
        self.query_one("#detail-target", Label).update(task.get("target", ""))

        completed, total = task.get("sizeCompleted", 0) or 0, task.get("sizeTotal", 0) or 0
        self.query_one("#detail-progress-bar", ProgressBar).progress = calc_percent(completed, total)
        self.query_one("#detail-progress-text", Label).update(fmt_progress(completed, total))
        self.query_one("#cancel-btn", Button).disabled = status not in {"PENDING", "IN_PROGRESS"}


class TasksScreen(PageScreen):
    """Tasks screen showing backup history."""

    DEFAULT_CSS = """
    TasksScreen {
        align-horizontal: center;
        
        #content {
            width: 100%;
            max-width: 120;
            padding: 1 2;
            height: 1fr;
            overflow-y: auto;
            scrollbar-gutter: stable;
        }
        Markdown { background: transparent; margin: 0; padding: 0; }
        #controls { height: auto; margin: 1 0; }
        #refresh-btn { margin-right: 1; }
        #task-count { width: 1fr; text-align: right; color: $text-muted; }
        DataTable { height: 14; margin: 1 0; background: $surface; }
        Rule { margin: 1 0; }
    }
    """

    BINDINGS = [Binding("r", "refresh", "Refresh", tooltip="Refresh task list")]

    def __init__(self) -> None:
        super().__init__()
        self._tasks_sub: Optional[asyncio.Task] = None
        self._progress_mgr: Optional[ProgressSubscriptionManager] = None
        self._tasks: list[dict] = []
        self._selected_task: Optional[dict] = None

    def compose(self) -> ComposeResult:
        with containers.VerticalScroll(id="content"):
            yield Markdown(TASKS_MD)
            with containers.HorizontalGroup(id="controls"):
                yield Button("↻ Refresh", id="refresh-btn", variant="primary", tooltip="Refresh task list")
                yield Label("", id="task-count")
            yield DataTable(id="tasks-table", cursor_type="row", zebra_stripes=True)
            yield Rule()
            yield TaskDetail()
        yield Footer()

    def on_mount(self) -> None:
        self._progress_mgr = ProgressSubscriptionManager(lambda: self.app.client, self._on_progress_update)
        self.query_one("#tasks-table", DataTable).add_columns("Status", "Type", "Source", "Target", "Progress")
        self._tasks_sub = asyncio.create_task(self._subscribe_tasks())

    def on_unmount(self) -> None:
        if self._tasks_sub:
            self._tasks_sub.cancel()
        if self._progress_mgr:
            self._progress_mgr.cancel_all()

    def _on_progress_update(self, backup_id: str, completed: int, total: int) -> None:
        for task in self._tasks:
            if task.get("backupId") == backup_id:
                task["sizeCompleted"], task["sizeTotal"] = completed, total
                break
        self._update_table()
        if self._selected_task and self._selected_task.get("backupId") == backup_id:
            self._selected_task["sizeCompleted"], self._selected_task["sizeTotal"] = completed, total
            self.query_one(TaskDetail).update_task(self._selected_task)

    async def _subscribe_tasks(self) -> None:
        query = """subscription { backupTasksUpdated { backupId status type source target sizeCompleted sizeTotal }}"""
        while True:
            try:
                async for payload in self.app.client.subscribe(query):
                    self._tasks = payload.get("backupTasksUpdated", [])
                    self._update_table()
                    self._update_task_count()
                    self._progress_mgr.sync(self._tasks)
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning("Tasks subscription error: %s, retrying...", e)
                await asyncio.sleep(1)

    def _update_task_count(self) -> None:
        active = sum(1 for t in self._tasks if t.get("status") in {"PENDING", "IN_PROGRESS"})
        text = f"[yellow]{active} active[/yellow] · {len(self._tasks)} total" if active else f"{len(self._tasks)} tasks"
        self.query_one("#task-count", Label).update(text)

    async def _refresh_data(self) -> None:
        query = """query { backupTasks(limit: 50) { backupId status type source target sizeCompleted sizeTotal }}"""
        try:
            result = await self.app.client.execute(query)
            self._tasks = result.get("backupTasks", [])
            self._update_table()
            self._update_task_count()
        except Exception as e:
            logger.warning("Failed to fetch tasks: %s", e)

    def _update_table(self) -> None:
        table = self.query_one("#tasks-table", DataTable)
        selected_id = self._selected_task.get("backupId") if self._selected_task else None
        previous_index = table.cursor_row if table.row_count else None
        table.clear()

        for task in self._tasks:
            status = task.get("status", "")
            completed, total = task.get("sizeCompleted", 0) or 0, task.get("sizeTotal", 0) or 0

            if total > 0:
                pct = (completed / total) * 100
                progress = "[green]100%[/green]" if pct >= 100 else f"[yellow]{pct:.0f}%[/yellow]" if pct > 0 else "[dim]0%[/dim]"
            else:
                progress = "[dim]—[/dim]"

            table.add_row(
                STATUS_STYLES.get(status, status), f"[cyan]{task.get('type', '')}[/cyan]", task.get("source", ""), task.get("target", ""), progress
            )

        if not self._tasks:
            self._set_selected_task(None)
            return

        if not selected_id and previous_index is None:
            return

        target_index = None
        if selected_id:
            target_index = next((i for i, t in enumerate(self._tasks) if t.get("backupId") == selected_id), None)
        if target_index is None and previous_index is not None:
            target_index = min(previous_index, len(self._tasks) - 1)
        if target_index is None:
            self._set_selected_task(None)
            return

        table.move_cursor(row=target_index)
        self._set_selected_task(self._tasks[target_index])

    def _set_selected_task(self, task: Optional[dict]) -> None:
        self._selected_task = task
        self.query_one(TaskDetail).update_task(task)

    def _update_selected_from_row(self, row_key) -> None:
        if row_key is None:
            self._set_selected_task(None)
            return

        table = self.query_one("#tasks-table", DataTable)
        try:
            idx = table.get_row_index(row_key)
        except (KeyError, RowDoesNotExist):
            self._set_selected_task(None)
            return

        self._set_selected_task(self._tasks[idx] if 0 <= idx < len(self._tasks) else None)

    @on(DataTable.RowHighlighted)
    def on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._update_selected_from_row(event.row_key)

    @on(DataTable.RowSelected)
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        self._update_selected_from_row(event.row_key)

    @on(Button.Pressed, "#refresh-btn")
    async def on_refresh_pressed(self) -> None:
        await self._refresh_data()
        self.notify("Task list refreshed", severity="information")

    @on(Button.Pressed, "#cancel-btn")
    async def on_cancel_pressed(self) -> None:
        if not self._selected_task:
            return
        backup_id = self._selected_task.get("backupId")
        if not backup_id:
            return

        try:
            result = await self.app.client.execute("mutation($id: ID!) { cancelBackup(backupId: $id) }", variable_values={"id": backup_id})
            if result.get("cancelBackup"):
                self.notify(f"Cancelled backup {backup_id[:8]}", title="Success")
                self._set_selected_task(None)
            else:
                self.notify("Could not cancel backup", severity="warning")
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")
        await self._refresh_data()

    def action_refresh(self) -> None:
        asyncio.create_task(self._run_refresh())

    async def _run_refresh(self) -> None:
        await self._refresh_data()
        self.notify("Task list refreshed", severity="information")
