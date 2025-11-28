"""Settings screen - Configuration for SD Backup."""

from __future__ import annotations

import asyncio
import logging

from textual import containers, on
from textual.app import ComposeResult
from textual.widgets import Button, Checkbox, Footer, Input, Label, Markdown, Rule, Switch

from frontend.page import PageScreen

logger = logging.getLogger(__name__)


SETTINGS_MD = """\
# ⚙️  Settings

Configure your SD Backup preferences and automation rules.

"""

AUTO_BACKUP_MD = """\
## Auto Backup

Automatically start backups when SD cards are inserted.
"""

TEMPLATE_HELP_MD = """\
### Path Template Variables

Use these placeholders in your target path. Date/time values are based on the \
earliest file modification time found on the SD card (or current time if empty).

| Variable | Description | Example |
|----------|-------------|---------|
| `{date}` | Date (YYYYMMDD) | 20240115 |
| `{hour}` | Hour (HH) | 14 |
| `{minute}` | Minute (MM) | 30 |
| `{uuid}` | Full partition UUID | 1234-ABCD |
| `{uuid_short}` | First 4 chars of UUID | 1234 |
| `{fs_label}` | Filesystem label | SD_CARD |

**Example:** `~/sd-backups/{date}-{uuid_short}` → `~/sd-backups/20240115-1234`
"""


class AutoBackupToggle(containers.HorizontalGroup):
    """Auto backup toggle with status."""

    DEFAULT_CSS = """
    AutoBackupToggle {
        height: auto;
        padding: 1 2;
        background: $boost;
        margin: 1 0;
        border-left: thick $primary;
        
        #toggle-info {
            width: 1fr;
        }
        
        #toggle-title {
            text-style: bold;
        }
        
        #toggle-status {
            color: $text-muted;
        }
        
        Switch {
            margin-left: 2;
        }
    }
    """

    def __init__(self, enabled: bool = False) -> None:
        super().__init__()
        self._enabled = enabled

    def compose(self) -> ComposeResult:
        with containers.VerticalGroup(id="toggle-info"):
            yield Label("Enable Auto Backup", id="toggle-title")
            yield Label("Automatically backup when devices connect", id="toggle-status")
        yield Switch(value=self._enabled, id="auto-backup-switch", animate=True)


class TargetTemplateForm(containers.VerticalGroup):
    """Target template configuration."""

    DEFAULT_CSS = """
    TargetTemplateForm {
        height: auto;
        padding: 1 2;
        background: $boost;
        margin: 1 0;
        
        #template-title {
            text-style: bold;
            margin-bottom: 1;
        }
        
        #template-label {
            color: $text-muted;
            margin-bottom: 0;
        }
        
        Input {
            width: 100%;
            margin-top: 0;
        }
        
        #preview-section {
            margin-top: 1;
            padding: 1;
            background: $surface;
        }
        
        #preview-label {
            color: $text-muted;
        }
        
        #preview-value {
            color: $text-accent;
            text-style: bold;
        }
        
        Markdown {
            background: transparent;
            margin-top: 1;
            padding: 0;
        }
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("📁 Target Path Template", id="template-title")
        yield Label("Where backups will be saved", id="template-label")
        yield Input(
            placeholder="~/sd-backups/{date}-{uuid_short}",
            id="target-template-input",
        )
        with containers.VerticalGroup(id="preview-section"):
            yield Label("Preview:", id="preview-label")
            yield Label("", id="preview-value")
        yield Markdown(TEMPLATE_HELP_MD)

    def update_preview(self, template: str) -> None:
        """Update the preview with example values."""
        if not template:
            self.query_one("#preview-value", Label).update("[dim]Enter a template above[/dim]")
            return
        
        # Replace template variables with example values matching backend format
        preview = template.replace("{date}", "20240115")
        preview = preview.replace("{hour}", "14")
        preview = preview.replace("{minute}", "30")
        preview = preview.replace("{uuid}", "1234-ABCD")
        preview = preview.replace("{uuid_short}", "1234")
        preview = preview.replace("{fs_label}", "SD_CARD")
        self.query_one("#preview-value", Label).update(f"[cyan]{preview}[/cyan]")


class SettingsScreen(PageScreen):
    """Settings screen for configuration."""

    DEFAULT_CSS = """
    SettingsScreen {
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
        
        #button-row {
            height: auto;
            margin: 2 0 1 0;
        }
        
        #save-btn {
            margin-right: 1;
        }
        
        #status-container {
            height: auto;
            margin-top: 1;
            padding: 1;
            background: $surface;
            
            &.hidden { display: none; }
            &.success { border-left: thick $success; }
            &.error { border-left: thick $error; }
            &.info { border-left: thick $accent; }
        }
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._original_config: dict = {}

    def compose(self) -> ComposeResult:
        with containers.VerticalScroll(id="content"):
            yield Markdown(SETTINGS_MD)
            yield Markdown(AUTO_BACKUP_MD)
            yield AutoBackupToggle()
            yield Rule()
            yield TargetTemplateForm()
            with containers.HorizontalGroup(id="button-row"):
                yield Button(
                    "💾 Save Settings",
                    id="save-btn",
                    variant="primary",
                    tooltip="Save configuration changes",
                )
                yield Button(
                    "↺ Reset",
                    id="reset-btn",
                    variant="default",
                    tooltip="Reset to last saved values",
                )
            with containers.VerticalGroup(id="status-container", classes="hidden"):
                yield Label("", id="status-label")
        yield Footer()

    def on_mount(self) -> None:
        logger.debug("SettingsScreen mounted, loading config")
        asyncio.create_task(self._load_config())

    async def _load_config(self) -> None:
        """Load current configuration."""
        client = self.app.client

        query = """
        query {
            config {
                autoBackupEnabled
                autoBackupTargetPath
            }
        }
        """
        try:
            logger.debug("Loading configuration")
            result = await client.execute(query)
            config = result.get("config", {})
            logger.debug("Loaded config: %s", config)
            self._original_config = config

            switch = self.query_one("#auto-backup-switch", Switch)
            switch.value = config.get("autoBackupEnabled", False)

            input_field = self.query_one("#target-template-input", Input)
            template = config.get("autoBackupTargetPath", "")
            input_field.value = template

            # Update preview
            template_form = self.query_one(TargetTemplateForm)
            template_form.update_preview(template)

            self._show_status("✓ Configuration loaded", "success")
            # Auto-hide after 2 seconds
            asyncio.create_task(self._auto_hide_status())
        except Exception as e:
            logger.error("Failed to load config: %s", e)
            self._show_status(f"✗ Failed to load config: {e}", "error")

    async def _auto_hide_status(self) -> None:
        """Auto-hide status after delay."""
        await asyncio.sleep(2)
        self._hide_status()

    def _show_status(self, message: str, status_type: str = "info") -> None:
        """Show status message."""
        container = self.query_one("#status-container", containers.VerticalGroup)
        label = self.query_one("#status-label", Label)
        
        container.remove_class("hidden", "success", "error", "info")
        container.add_class(status_type)
        label.update(message)

    def _hide_status(self) -> None:
        """Hide status message."""
        container = self.query_one("#status-container", containers.VerticalGroup)
        container.add_class("hidden")

    @on(Input.Changed, "#target-template-input")
    def on_template_changed(self, event: Input.Changed) -> None:
        """Update preview when template changes."""
        template_form = self.query_one(TargetTemplateForm)
        template_form.update_preview(event.value)

    @on(Button.Pressed, "#save-btn")
    async def on_save_pressed(self) -> None:
        """Handle save button press."""
        switch = self.query_one("#auto-backup-switch", Switch)
        input_field = self.query_one("#target-template-input", Input)

        auto_enabled = switch.value
        target_template = input_field.value.strip()

        self._show_status("⏳ Saving...", "info")
        logger.info("Saving config: autoBackupEnabled=%s, autoBackupTargetPath=%s", 
                    auto_enabled, target_template)

        client = self.app.client
        mutation = """
        mutation UpdateConfig($config: ConfigInput!) {
            updateConfig(config: $config)
        }
        """
        config_input = {
            "autoBackupEnabled": auto_enabled,
            "autoBackupTargetPath": target_template,
        }
        try:
            result = await client.execute(
                mutation, variable_values={"config": config_input}
            )
            if result.get("updateConfig"):
                logger.info("Config saved successfully")
                self._original_config = {
                    "autoBackupEnabled": auto_enabled,
                    "autoBackupTargetPath": target_template,
                }
                self._show_status("✓ Settings saved successfully!", "success")
                self.notify("Settings saved", title="Success", severity="information")
            else:
                logger.warning("Config mutation returned False")
                self._show_status("⚠️ Settings may not have been saved", "info")
        except Exception as e:
            logger.error("Failed to save config: %s", e)
            self._show_status(f"✗ Failed to save: {e}", "error")
            self.notify(f"Failed: {e}", title="Error", severity="error")

    @on(Button.Pressed, "#reset-btn")
    def on_reset_pressed(self) -> None:
        """Handle reset button press."""
        switch = self.query_one("#auto-backup-switch", Switch)
        input_field = self.query_one("#target-template-input", Input)

        switch.value = self._original_config.get("autoBackupEnabled", False)
        template = self._original_config.get("autoBackupTargetPath", "")
        input_field.value = template

        template_form = self.query_one(TargetTemplateForm)
        template_form.update_preview(template)

        self._show_status("↺ Reset to last saved values", "info")
