"""Tasks screen - Backup history for SD Backup."""

from __future__ import annotations

import asyncio
from typing import Optional

from textual import containers, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import Button, DataTable, Footer, Label, Markdown, Static

from frontend.page import PageScreen


TASKS_MD = """\
# Backup Tasks

View and manage your backup history. Select a task to see details or cancel active backups.

"""


class TaskDetail(containers.VerticalGroup):
    """Displays details for a selected task."""

    DEFAULT_CSS = """
    TaskDetail {
        height: auto;
        padding: 1 2;
        background: $boost;
        margin: 1 0;
        
        #detail-title {
            text-style: bold;
            margin-bottom: 1;
        }
        
        .detail-row {
            height: auto;
        }
        
        .detail-label {
            width: 15;
            text-style: bold;
        }
        
        .detail-value {
            width: 1fr;
        }
        
        #cancel-btn {
            margin-top: 1;
        }
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("Task Details", id="detail-title")
        with containers.HorizontalGroup(classes="detail-row"):
            yield Label("ID:", classes="detail-label")
            yield Label("", id="detail-id", classes="detail-value")
        with containers.HorizontalGroup(classes="detail-row"):
            yield Label("Status:", classes="detail-label")
            yield Label("", id="detail-status", classes="detail-value")
        with containers.HorizontalGroup(classes="detail-row"):
            yield Label("Type:", classes="detail-label")
            yield Label("", id="detail-type", classes="detail-value")
        with containers.HorizontalGroup(classes="detail-row"):
            yield Label("Source:", classes="detail-label")
            yield Label("", id="detail-source", classes="detail-value")
        with containers.HorizontalGroup(classes="detail-row"):
            yield Label("Target:", classes="detail-label")
            yield Label("", id="detail-target", classes="detail-value")
        with containers.HorizontalGroup(classes="detail-row"):
            yield Label("Progress:", classes="detail-label")
            yield Label("", id="detail-progress", classes="detail-value")
        yield Button(
            "Cancel Backup",
            id="cancel-btn",
            variant="error",
            disabled=True,
            tooltip="Cancel this backup task",
        )

    def update_task(self, task: Optional[dict]) -> None:
        """Update displayed task details."""
        if not task:
            self.query_one("#detail-id", Label).update("")
            self.query_one("#detail-status", Label).update("")
            self.query_one("#detail-type", Label).update("")
            self.query_one("#detail-source", Label).update("")
            self.query_one("#detail-target", Label).update("")
            self.query_one("#detail-progress", Label).update("")
            self.query_one("#cancel-btn", Button).disabled = True
            return

        self.query_one("#detail-id", Label).update(task.get("backupId", ""))
        status = task.get("status", "")
        self.query_one("#detail-status", Label).update(status)
        self.query_one("#detail-type", Label).update(task.get("type", ""))
        self.query_one("#detail-source", Label).update(task.get("source", ""))
        self.query_one("#detail-target", Label).update(task.get("target", ""))

        completed = task.get("sizeCompleted", 0) or 0
        total = task.get("sizeTotal", 0) or 0
        if total > 0:
            percent = (completed / total) * 100
            self.query_one("#detail-progress", Label).update(
                f"{completed}/{total} bytes ({percent:.1f}%)"
            )
        else:
            self.query_one("#detail-progress", Label).update("0 bytes")

        # Enable cancel button for active tasks
        can_cancel = status in {"PENDING", "IN_PROGRESS"}
        self.query_one("#cancel-btn", Button).disabled = not can_cancel


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
        }
        
        Markdown {
            background: transparent;
            margin: 0;
            padding: 0;
        }
        
        DataTable {
            height: 16;
            margin: 1 0;
        }
        
        #controls {
            height: auto;
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
                    "Refresh",
                    id="refresh-btn",
                    variant="primary",
                    tooltip="Refresh task list",
                )
            yield DataTable(id="tasks-table", cursor_type="row")
            yield TaskDetail()
        yield Footer()

    def on_mount(self) -> None:
        # Set up the data table
        table = self.query_one("#tasks-table", DataTable)
        table.add_columns("ID", "Status", "Type", "Source", "Target", "Progress")
        
        # Start refresh loop
        self._refresh_task = asyncio.create_task(self._refresh_loop())

    def on_unmount(self) -> None:
        if self._refresh_task:
            self._refresh_task.cancel()

    async def _refresh_loop(self) -> None:
        """Periodically refresh task list."""
        while True:
            await self._refresh_data()
            await asyncio.sleep(5)

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
            result = await client.execute(query, variable_values={"limit": 50})
        except Exception:
            return

        self._tasks = result.get("backupTasks", [])
        self._update_table()

    def _update_table(self) -> None:
        """Update the data table with current tasks."""
        table = self.query_one("#tasks-table", DataTable)
        table.clear()

        for task in self._tasks:
            backup_id = task.get("backupId", "")[:8]
            status = task.get("status", "")
            task_type = task.get("type", "")
            source = task.get("source", "")
            target = task.get("target", "")

            completed = task.get("sizeCompleted", 0) or 0
            total = task.get("sizeTotal", 0) or 0
            if total > 0:
                percent = (completed / total) * 100
                progress = f"{percent:.1f}%"
            else:
                progress = "0%"

            # Truncate long paths
            if len(source) > 25:
                source = "..." + source[-22:]
            if len(target) > 25:
                target = "..." + target[-22:]

            table.add_row(backup_id, status, task_type, source, target, progress)

    @on(DataTable.RowSelected)
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle row selection in the tasks table."""
        if event.row_key is not None and event.row_key.value is not None:
            row_index = event.row_key.value
            if 0 <= row_index < len(self._tasks):
                self._selected_task = self._tasks[row_index]
                detail = self.query_one(TaskDetail)
                detail.update_task(self._selected_task)

    @on(Button.Pressed, "#refresh-btn")
    async def on_refresh_pressed(self) -> None:
        """Handle refresh button press."""
        await self._refresh_data()

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
                self.notify(f"Cancelled backup {backup_id[:8]}", title="Backup Cancelled")
            else:
                self.notify("Could not cancel backup", title="Cancel Failed", severity="warning")
        except Exception as e:
            self.notify(f"Error: {e}", title="Cancel Failed", severity="error")

        await self._refresh_data()

    def action_refresh(self) -> None:
        """Action to refresh task list."""
        asyncio.create_task(self._refresh_data())

