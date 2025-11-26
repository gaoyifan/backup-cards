"""Tasks screen - Backup history for SD Backup."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from textual import containers, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import Button, DataTable, Footer, Label, Markdown, ProgressBar, Rule

from frontend.page import PageScreen

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
        
        #detail-header {
            height: auto;
            margin-bottom: 1;
        }
        
        #detail-title {
            text-style: bold;
            width: 1fr;
        }
        
        #detail-status {
            width: auto;
        }
        
        .detail-section {
            height: auto;
            margin-bottom: 1;
            padding: 1;
            background: $surface;
        }
        
        .detail-label {
            color: $text-muted;
            margin-bottom: 0;
        }
        
        .detail-value {
            text-style: bold;
        }
        
        #progress-section {
            margin-top: 1;
        }
        
        #cancel-btn {
            margin-top: 1;
        }
    }
    """

    def compose(self) -> ComposeResult:
        with containers.HorizontalGroup(id="detail-header"):
            yield Label("Task Details", id="detail-title")
            yield Label("", id="detail-status")
        with containers.HorizontalGroup():
            with containers.VerticalGroup(classes="detail-section"):
                yield Label("Backup ID", classes="detail-label")
                yield Label("", id="detail-id", classes="detail-value")
            with containers.VerticalGroup(classes="detail-section"):
                yield Label("Type", classes="detail-label")
                yield Label("", id="detail-type", classes="detail-value")
        with containers.VerticalGroup(classes="detail-section"):
            yield Label("Source", classes="detail-label")
            yield Label("", id="detail-source", classes="detail-value")
        with containers.VerticalGroup(classes="detail-section"):
            yield Label("Target", classes="detail-label")
            yield Label("", id="detail-target", classes="detail-value")
        with containers.VerticalGroup(id="progress-section"):
            yield Label("Progress", classes="detail-label")
            yield ProgressBar(total=100, show_eta=False, id="detail-progress-bar")
            yield Label("", id="detail-progress-text")
        yield Button(
            "Cancel Backup",
            id="cancel-btn",
            variant="error",
            disabled=True,
            tooltip="Cancel this backup task",
        )

    def on_mount(self) -> None:
        self.add_class("hidden")

    def update_task(self, task: Optional[dict]) -> None:
        """Update displayed task details."""
        if not task:
            self.add_class("hidden")
            return

        self.remove_class("hidden")
        
        status = task.get("status", "")
        status_text = STATUS_STYLES.get(status, status)
        
        self.query_one("#detail-id", Label).update(task.get("backupId", "")[:16] + "...")
        self.query_one("#detail-status", Label).update(status_text)
        self.query_one("#detail-type", Label).update(task.get("type", ""))
        self.query_one("#detail-source", Label).update(task.get("source", ""))
        self.query_one("#detail-target", Label).update(task.get("target", ""))

        completed = task.get("sizeCompleted", 0) or 0
        total = task.get("sizeTotal", 0) or 0
        if total > 0:
            percent = (completed / total) * 100
            self.query_one("#detail-progress-bar", ProgressBar).progress = percent
            self.query_one("#detail-progress-text", Label).update(
                f"{self._format_bytes(completed)} / {self._format_bytes(total)} ({percent:.1f}%)"
            )
        else:
            self.query_one("#detail-progress-bar", ProgressBar).progress = 0
            self.query_one("#detail-progress-text", Label).update("0 bytes")

        can_cancel = status in {"PENDING", "IN_PROGRESS"}
        self.query_one("#cancel-btn", Button).disabled = not can_cancel

    def _format_bytes(self, size: int) -> str:
        """Format bytes to human readable string."""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"


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
        
        Markdown {
            background: transparent;
            margin: 0;
            padding: 0;
        }
        
        #controls {
            height: auto;
            margin: 1 0;
        }
        
        #refresh-btn {
            margin-right: 1;
        }
        
        #task-count {
            width: 1fr;
            text-align: right;
            color: $text-muted;
        }
        
        DataTable {
            height: 14;
            margin: 1 0;
            background: $surface;
        }
        
        Rule {
            margin: 1 0;
        }
    }
    """

    BINDINGS = [
        Binding("r", "refresh", "Refresh", tooltip="Refresh task list"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._refresh_task: Optional[asyncio.Task] = None
        self._tasks: list[dict] = []
        self._selected_task: Optional[dict] = None

    def compose(self) -> ComposeResult:
        with containers.VerticalScroll(id="content"):
            yield Markdown(TASKS_MD)
            with containers.HorizontalGroup(id="controls"):
                yield Button(
                    "↻ Refresh",
                    id="refresh-btn",
                    variant="primary",
                    tooltip="Refresh task list",
                )
                yield Label("", id="task-count")
            yield DataTable(id="tasks-table", cursor_type="row", zebra_stripes=True)
            yield Rule()
            yield TaskDetail()
        yield Footer()

    def on_mount(self) -> None:
        logger.debug("TasksScreen mounted, starting refresh loop")
        table = self.query_one("#tasks-table", DataTable)
        table.add_columns("Status", "Type", "Source", "Target", "Progress")
        self._refresh_task = asyncio.create_task(self._refresh_loop())

    def on_unmount(self) -> None:
        logger.debug("TasksScreen unmounting, cancelling refresh task")
        if self._refresh_task:
            self._refresh_task.cancel()

    async def _refresh_loop(self) -> None:
        """Periodically refresh task list."""
        logger.debug("TasksScreen refresh loop started")
        while True:
            if self.app.auto_refresh_enabled:
                await self._refresh_data()
            await asyncio.sleep(3)

    async def _refresh_data(self) -> None:
        """Fetch and update task list."""
        client = self.app.client

        query = """
        query Tasks($limit: Int!) {
            backupTasks(limit: $limit) {
                backupId
                status
                type
                source
                target
                sizeCompleted
                sizeTotal
            }
        }
        """
        try:
            logger.debug("Executing tasks query")
            result = await client.execute(query, variable_values={"limit": 50})
            logger.debug("Tasks query returned %d tasks", len(result.get("backupTasks", [])))
        except Exception as e:
            logger.warning("Failed to fetch tasks: %s", e)
            return

        self._tasks = result.get("backupTasks", [])
        self._update_table()
        
        # Update task count
        count_label = self.query_one("#task-count", Label)
        active = sum(1 for t in self._tasks if t.get("status") in {"PENDING", "IN_PROGRESS"})
        if active > 0:
            count_label.update(f"[yellow]{active} active[/yellow] · {len(self._tasks)} total")
        else:
            count_label.update(f"{len(self._tasks)} tasks")

    def _update_table(self) -> None:
        """Update the data table with current tasks."""
        table = self.query_one("#tasks-table", DataTable)
        selected_id = self._selected_task.get("backupId") if self._selected_task else None
        previous_index = table.cursor_row if table.row_count else None
        table.clear()

        for task in self._tasks:
            status = task.get("status", "")
            status_display = STATUS_STYLES.get(status, status)
            task_type = f"[cyan]{task.get('type', '')}[/cyan]"
            
            source = task.get("source", "")
            target = task.get("target", "")
            
            # Truncate long paths
            if len(source) > 28:
                source = "..." + source[-25:]
            if len(target) > 28:
                target = "..." + target[-25:]

            completed = task.get("sizeCompleted", 0) or 0
            total = task.get("sizeTotal", 0) or 0
            if total > 0:
                percent = (completed / total) * 100
                if percent >= 100:
                    progress = "[green]100%[/green]"
                elif percent > 0:
                    progress = f"[yellow]{percent:.0f}%[/yellow]"
                else:
                    progress = "[dim]0%[/dim]"
            else:
                progress = "[dim]—[/dim]"

            table.add_row(status_display, task_type, source, target, progress)

        if not self._tasks:
            self._set_selected_task(None)
            return

        if not selected_id and previous_index is None:
            return

        target_index = None
        if selected_id:
            target_index = next(
                (idx for idx, task in enumerate(self._tasks) if task.get("backupId") == selected_id),
                None,
            )

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

    def _update_selected_task_from_row_key(self, row_key) -> None:
        table = self.query_one("#tasks-table", DataTable)
        if not row_key:
            self._set_selected_task(None)
            return

        try:
            row_index = table.get_row_index(row_key)
        except KeyError:
            row_index = -1

        task = self._tasks[row_index] if 0 <= row_index < len(self._tasks) else None
        self._set_selected_task(task)

    @on(DataTable.RowHighlighted)
    def on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """Update task details whenever the highlight moves."""
        self._update_selected_task_from_row_key(event.row_key)

    @on(DataTable.RowSelected)
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection in the tasks table (e.g. Enter key)."""
        self._update_selected_task_from_row_key(event.row_key)

    @on(Button.Pressed, "#refresh-btn")
    async def on_refresh_pressed(self) -> None:
        """Handle refresh button press."""
        await self._refresh_data()
        self.notify("Task list refreshed", severity="information")

    @on(Button.Pressed, "#cancel-btn")
    async def on_cancel_pressed(self) -> None:
        """Handle cancel button press."""
        if not self._selected_task:
            return

        backup_id = self._selected_task.get("backupId")
        if not backup_id:
            return

        client = self.app.client
        mutation = """
        mutation CancelBackup($id: ID!) {
            cancelBackup(backupId: $id)
        }
        """
        try:
            result = await client.execute(mutation, variable_values={"id": backup_id})
            if result.get("cancelBackup"):
                self.notify(f"Cancelled backup {backup_id[:8]}", title="Success")
                self._selected_task = None
                self.query_one(TaskDetail).update_task(None)
            else:
                self.notify("Could not cancel backup", severity="warning")
        except Exception as e:
            self.notify(f"Error: {e}", severity="error")

        await self._refresh_data()

    def action_refresh(self) -> None:
        """Action to refresh task list."""
        asyncio.create_task(self._refresh_data())
