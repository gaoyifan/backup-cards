from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Header, Footer, Button, Static, Log, Input, Label
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from frontend.client import GraphQLClient
import asyncio

class DashboardScreen(Screen):
    BINDINGS = [("s", "go_settings", "Settings")]

    def __init__(self, client: GraphQLClient):
        super().__init__()
        self.client = client
        self.log_widget = Log()
        self.status_label = Label("Status: Unknown")

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Vertical(
                Label("SD Card Backup Tool", classes="title"),
                self.status_label,
                Horizontal(
                    Button("Start Manual Backup", id="start_btn", variant="success"),
                    Button("Cancel Backup", id="cancel_btn", variant="error"),
                    classes="buttons"
                ),
                Label("Logs:", classes="log-title"),
                self.log_widget,
            )
        )
        yield Footer()

    def on_mount(self):
        asyncio.create_task(self.monitor_logs())
        asyncio.create_task(self.refresh_status())

    async def monitor_logs(self):
        query = """
        subscription {
            backupProgress
        }
        """
        try:
            async for result in self.client.subscribe(query):
                message = result.get("backupProgress")
                self.log_widget.write_line(message)
                # Also refresh status when logs come in
                asyncio.create_task(self.refresh_status())
        except Exception as e:
            self.log_widget.write_line(f"Connection error: {e}")

    async def refresh_status(self):
        query = """
        query {
            currentStatus {
                active
                message
            }
        }
        """
        try:
            result = await self.client.execute(query)
            status = result["currentStatus"]
            self.status_label.update(f"Status: {status['message']}")
            
            start_btn = self.query_one("#start_btn", Button)
            cancel_btn = self.query_one("#cancel_btn", Button)
            
            if status["active"]:
                start_btn.disabled = True
                cancel_btn.disabled = False
            else:
                start_btn.disabled = False
                cancel_btn.disabled = True
                
        except Exception as e:
            self.status_label.update(f"Status Error: {e}")

    async def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "start_btn":
            # For now hardcode source/target or ask user?
            # User didn't specify UI for inputting source/target for manual backup.
            # But "Manual Backup" usually implies selecting something.
            # For simplicity, let's assume we trigger a backup of a connected device?
            # Or maybe just a test backup?
            # The mutation requires source/target.
            # Let's use a default for now or maybe add inputs?
            # User said "manual backup tasks", implying parameters.
            # Let's add a simple input dialog or just inputs on screen.
            # For now, I'll just trigger with dummy values or ask user in next iteration if needed.
            # Wait, the user said "process manually backup task in prepared src_dir environment" for E2E.
            # Let's add inputs for Source and Target.
            self.app.push_screen(ManualBackupDialog(self.client))
            
        elif event.button.id == "cancel_btn":
            query = """
            mutation {
                cancelBackup
            }
            """
            await self.client.execute(query)

    def action_go_settings(self):
        self.app.push_screen(SettingsScreen(self.client))

class ManualBackupDialog(Screen):
    def __init__(self, client: GraphQLClient):
        super().__init__()
        self.client = client

    def compose(self) -> ComposeResult:
        yield Container(
            Label("Manual Backup"),
            Label("Source Path:"),
            Input(placeholder="/path/to/source", id="source_input"),
            Label("Target Path:"),
            Input(placeholder="/path/to/target", id="target_input"),
            Horizontal(
                Button("Start", id="confirm_btn", variant="success"),
                Button("Cancel", id="close_btn"),
            )
        )

    async def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "confirm_btn":
            source = self.query_one("#source_input", Input).value
            target = self.query_one("#target_input", Input).value
            if source and target:
                query = """
                mutation($source: String!, $target: String!) {
                    startManualBackup(source: $source, target: $target)
                }
                """
                await self.client.execute(query, variable_values={"source": source, "target": target})
                self.app.pop_screen()
        elif event.button.id == "close_btn":
            self.app.pop_screen()

class SettingsScreen(Screen):
    BINDINGS = [("b", "back", "Back")]

    def __init__(self, client: GraphQLClient):
        super().__init__()
        self.client = client

    def compose(self) -> ComposeResult:
        yield Header()
        yield Container(
            Label("Configuration", classes="title"),
            Label("Mount Point Template:"),
            Input(id="mount_template"),
            Label("Target Path Template:"),
            Input(id="target_template"),
            Button("Save", id="save_btn", variant="primary"),
            Label("", id="msg_label")
        )
        yield Footer()

    def on_mount(self):
        asyncio.create_task(self.load_config())

    async def load_config(self):
        query = """
        query {
            config {
                mountPointTemplate
                targetPathTemplate
            }
        }
        """
        try:
            result = await self.client.execute(query)
            conf = result["config"]
            self.query_one("#mount_template", Input).value = conf["mountPointTemplate"]
            self.query_one("#target_template", Input).value = conf["targetPathTemplate"]
        except Exception as e:
            self.query_one("#msg_label", Label).update(f"Error loading config: {e}")

    async def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "save_btn":
            mount_tmpl = self.query_one("#mount_template", Input).value
            target_tmpl = self.query_one("#target_template", Input).value
            
            try:
                # Update one by one
                query = """
                mutation($key: String!, $value: String!) {
                    updateConfig(key: $key, value: $value)
                }
                """
                await self.client.execute(query, variable_values={"key": "mount_point_template", "value": mount_tmpl})
                await self.client.execute(query, variable_values={"key": "target_path_template", "value": target_tmpl})
                self.query_one("#msg_label", Label).update("Configuration saved!")
            except Exception as e:
                self.query_one("#msg_label", Label).update(f"Error saving: {e}")

    def action_back(self):
        self.app.pop_screen()
