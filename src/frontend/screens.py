import asyncio
from contextlib import suppress
from typing import Any, Dict, List, Optional

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Footer, Header, Input, Label, Log, Static

from frontend.client import GraphQLClient


class DashboardScreen(Screen):
    BINDINGS = [("s", "go_settings", "Settings"), ("r", "refresh_now", "Refresh")]

    def __init__(self, client: GraphQLClient):
        super().__init__()
        self.client = client
        self.log_widget = Log()
        self.config_label = Label("Config: loading...")
        self.progress_label = Label("Progress: n/a")
        self.tasks_panel = Static("No tasks yet.")
        self.active_backup_id: Optional[str] = None
        self._refresh_task: Optional[asyncio.Task] = None
        self._progress_task: Optional[asyncio.Task] = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Vertical(
                Label("SD Backup Dashboard", classes="title"),
                self.config_label,
                self.progress_label,
                Horizontal(
                    Button("Start Manual Backup", id="start_btn", variant="success"),
                    Button("Cancel Active Backup", id="cancel_btn", variant="error", disabled=True),
                    Button("Refresh Now", id="refresh_btn", variant="primary"),
                ),
                Label("Recent Tasks", classes="log-title"),
                self.tasks_panel,
                Label("Events", classes="log-title"),
                self.log_widget,
            ),
            classes="dashboard",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_task = asyncio.create_task(self._refresh_loop())

    def on_unmount(self) -> None:
        if self._refresh_task:
            self._refresh_task.cancel()
        if self._progress_task:
            self._progress_task.cancel()

    async def _refresh_loop(self) -> None:
        while True:
            await self.refresh_state()
            await asyncio.sleep(2)

    async def refresh_state(self) -> None:
        query = """
        query Dashboard($limit: Int!) {
            config {
                autoBackupEnabled
                autoBackupTargetPath
            }
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
            result = await self.client.execute(query, variable_values={"limit": 10})
        except Exception as exc:
            self.log_widget.write_line(f"Refresh failed: {exc}")
            return

        config = result["config"]
        self.config_label.update(
            f"Auto Backup: {'enabled' if config['autoBackupEnabled'] else 'disabled'} | Target Template: {config['autoBackupTargetPath']}"
        )

        tasks = result["backupTasks"]
        self._render_tasks(tasks)

        active = next(
            (task for task in tasks if task["status"] in {"PENDING", "IN_PROGRESS"}), None
        )
        active_id = active["backupId"] if active else None
        cancel_btn = self.query_one("#cancel_btn", Button)
        cancel_btn.disabled = active_id is None

        if active_id != self.active_backup_id:
            self.active_backup_id = active_id
            await self._restart_progress_subscription(active_id)

    async def _restart_progress_subscription(self, backup_id: Optional[str]) -> None:
        if self._progress_task:
            self._progress_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._progress_task
            self._progress_task = None

        if not backup_id:
            self.progress_label.update("Progress: idle")
            return

        self.progress_label.update(f"Progress: listening ({backup_id})")
        self._progress_task = asyncio.create_task(self._consume_progress(backup_id))

    async def _consume_progress(self, backup_id: str) -> None:
        query = """
        subscription($id: ID!) {
            progress(backupId: $id) {
                sizeCompleted
                sizeTotal
            }
        }
        """
        try:
            async for payload in self.client.subscribe(query, variable_values={"id": backup_id}):
                progress = payload["progress"]
                completed = progress["sizeCompleted"]
                total = progress["sizeTotal"] or 1
                percent = (completed / total) * 100 if total else 0
                self.progress_label.update(
                    f"Progress [{backup_id[:8]}]: {completed}/{total} bytes ({percent:.1f}%)"
                )
        except Exception as exc:
            self.log_widget.write_line(f"Progress subscription error: {exc}")

    def _render_tasks(self, tasks: List[Dict[str, Any]]) -> None:
        if not tasks:
            self.tasks_panel.update("No tasks recorded.")
            return

        lines = []
        for task in tasks:
            total = task["sizeTotal"] or 0
            done = task["sizeCompleted"] or 0
            percent = (done / total) * 100 if total else 0
            lines.append(
                f"{task['backupId'][:8]} | {task['status']} | {task['type']} | "
                f"{done}/{total} bytes ({percent:.1f}%)"
            )
            lines.append(f"  {task['source']} -> {task['target']}")
        self.tasks_panel.update("\n".join(lines))

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start_btn":
            dialog = ManualBackupDialog(
                self.client, self._manual_backup_started, self._manual_backup_failed
            )
            self.app.push_screen(dialog)
        elif event.button.id == "cancel_btn" and self.active_backup_id:
            await self._cancel_active_backup()
        elif event.button.id == "refresh_btn":
            await self.refresh_state()

    async def _cancel_active_backup(self) -> None:
        query = """
        mutation($id: ID!) {
            cancelBackup(backupId: $id)
        }
        """
        try:
            result = await self.client.execute(
                query, variable_values={"id": self.active_backup_id}
            )
            if result["cancelBackup"]:
                self.log_widget.write_line(f"Cancelled backup {self.active_backup_id}")
            else:
                self.log_widget.write_line("No running backup to cancel.")
        except Exception as exc:
            self.log_widget.write_line(f"Cancel failed: {exc}")
        await self.refresh_state()

    def _manual_backup_started(self, backup_id: str) -> None:
        self.log_widget.write_line(f"Manual backup scheduled: {backup_id}")
        asyncio.create_task(self.refresh_state())

    def _manual_backup_failed(self, message: str) -> None:
        self.log_widget.write_line(f"Manual backup failed: {message}")

    def action_go_settings(self) -> None:
        self.app.push_screen(SettingsScreen(self.client))

    async def action_refresh_now(self) -> None:
        await self.refresh_state()


class ManualBackupDialog(Screen):
    def __init__(self, client: GraphQLClient, on_success=None, on_error=None):
        super().__init__()
        self.client = client
        self.on_success = on_success
        self.on_error = on_error

    def compose(self) -> ComposeResult:
        yield Container(
            Label("Manual Backup"),
            Label("Source Path"),
            Input(placeholder="/path/to/source", id="source_input"),
            Label("Target Path"),
            Input(placeholder="/path/to/target", id="target_input"),
            Horizontal(
                Button("Start", id="confirm_btn", variant="success"),
                Button("Cancel", id="close_btn"),
            ),
            classes="modal",
        )

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm_btn":
            await self._start_backup()
        elif event.button.id == "close_btn":
            self.app.pop_screen()

    async def _start_backup(self) -> None:
        source = self.query_one("#source_input", Input).value
        target = self.query_one("#target_input", Input).value
        if not source or not target:
            return

        mutation = """
        mutation($source: String!, $target: String!) {
            startManualBackup(source: $source, target: $target)
        }
        """
        try:
            result = await self.client.execute(
                mutation, variable_values={"source": source, "target": target}
            )
            backup_id = result["startManualBackup"]
            if self.on_success:
                self.on_success(backup_id)
        except Exception as exc:
            if self.on_error:
                self.on_error(str(exc))
        finally:
            self.app.pop_screen()


class SettingsScreen(Screen):
    BINDINGS = [("b", "back", "Back")]

    def __init__(self, client: GraphQLClient):
        super().__init__()
        self.client = client
        self.auto_checkbox = Checkbox("Enable automatic backups", id="auto_checkbox")
        self.target_input = Input(id="target_input")
        self.message_label = Label("")

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Vertical(
                Label("Configuration", classes="title"),
                self.auto_checkbox,
                Label("Auto Backup Target Template"),
                self.target_input,
                Button("Save", id="save_btn", variant="primary"),
                self.message_label,
            )
        )
        yield Footer()

    def on_mount(self) -> None:
        asyncio.create_task(self._load_config())

    async def _load_config(self) -> None:
        query = """
        query {
            config {
                autoBackupEnabled
                autoBackupTargetPath
            }
        }
        """
        try:
            result = await self.client.execute(query)
        except Exception as exc:
            self.message_label.update(f"Error loading config: {exc}")
            return
        config = result["config"]
        self.auto_checkbox.value = config["autoBackupEnabled"]
        self.target_input.value = config["autoBackupTargetPath"]

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "save_btn":
            return
        mutation = """
        mutation($config: ConfigInput!) {
            updateConfig(config: $config)
        }
        """
        payload = {
            "config": {
                "autoBackupEnabled": self.auto_checkbox.value,
                "autoBackupTargetPath": self.target_input.value,
            }
        }
        try:
            await self.client.execute(mutation, variable_values=payload)
            self.message_label.update("Configuration saved.")
        except Exception as exc:
            self.message_label.update(f"Failed to save: {exc}")

    def action_back(self) -> None:
        self.app.pop_screen()
