"""Settings screen - Configuration for SD Backup."""

from __future__ import annotations

import asyncio
import logging

from textual import containers, on
from textual.events import Click, Enter, Leave
from textual.app import ComposeResult
from textual.widgets import Button, Footer, Input, Label, Markdown, Rule, Static, Switch

from frontend.page import PageScreen

logger = logging.getLogger(__name__)


def _encode_pattern_token(pattern: str) -> str:
    """Encode a pattern into a hex-only token safe for Textual IDs."""
    return pattern.encode("utf-8").hex()


def _decode_pattern_token(token: str) -> str | None:
    """Decode a previously encoded pattern token."""
    try:
        return bytes.fromhex(token).decode("utf-8")
    except ValueError:
        logger.warning("Invalid pattern token: %s", token)
        return None


SETTINGS_MD = """\
# ⚙️  Settings

Configure your SD Backup preferences and automation rules.

"""

AUTO_BACKUP_MD = """\
## Auto Backup

Automatically start backups when SD cards are inserted.
"""

AUTO_BACKUP_UNSUPPORTED_MD = """\
⚠️ Auto backup requires the backend to run on Linux. This instance is running on an unsupported platform, so the toggle and path template are hidden.
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
| `{model}` | Camera model from EXIF (spaces → `-`) | Alpha-7C |

**Example:** `~/sd-backups/{date}-{uuid_short}` → `~/sd-backups/20240115-1234`
"""

FILTER_RULES_MD = """\
## Filter Rules

Control which files are included or excluded from backups using rsync patterns.
"""

FILTER_HELP_MD = """\
### Pattern Syntax

| Pattern | Matches |
|---------|---------|
| `*.tmp` | All .tmp files |
| `.DS_Store` | Exact filename |
| `Thumbs.db` | Exact filename |
| `/DCIM/` | DCIM folder at root |
| `*.CR2` | All Canon RAW files |
| `**/*.jpg` | All JPG files in any subfolder |

**Include rules** are processed first, then **exclude rules**. \
If you want to only backup certain files, add them to includes and add `*` to excludes.
"""


class PatternItem(containers.HorizontalGroup):
    """A pattern item row that highlights on hover."""

    def on_enter(self, event: Enter) -> None:
        self.add_class("--hovered")

    def on_leave(self, event: Leave) -> None:
        self.remove_class("--hovered")


class PatternListEditor(containers.VerticalGroup):
    """Editable list of rsync patterns (for include/exclude rules)."""

    DEFAULT_CSS = """
    PatternListEditor {
        height: auto;
        padding: 1 2;
        background: $boost;
        margin: 1 0;
        
        .pattern-title { text-style: bold; margin-bottom: 1; }
        .pattern-description { color: $text-muted; margin-bottom: 1; }
        .pattern-input-row { height: auto; margin-bottom: 1; }
        .pattern-input { width: 1fr; }
        .pattern-add-btn { margin-left: 1; min-width: 8; }
        .pattern-list { height: auto; max-height: 12; overflow-y: auto; background: $surface; padding: 1; }
        .pattern-item { height: auto; }
        .pattern-text { width: 1fr; }
        .empty-message { color: $text-muted; text-style: italic; }
        
        .pattern-remove-btn {
            width: 3;
            color: $text-muted;
            text-align: center;
        }
        .pattern-item.--hovered .pattern-text { color: $error; }
        .pattern-item.--hovered .pattern-remove-btn { color: $error; }
    }
    """

    def __init__(self, title: str, description: str, pattern_id: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._title = title
        self._description = description
        self._pattern_id = pattern_id
        self._patterns: list[str] = []

    def compose(self) -> ComposeResult:
        yield Label(self._title, classes="pattern-title")
        yield Label(self._description, classes="pattern-description")
        with containers.HorizontalGroup(classes="pattern-input-row"):
            yield Input(placeholder="Enter pattern (e.g., *.tmp)", classes="pattern-input", id=f"{self._pattern_id}-input")
            yield Button("+ Add", classes="pattern-add-btn", variant="primary", id=f"{self._pattern_id}-add-btn")
        yield containers.VerticalGroup(classes="pattern-list", id=f"{self._pattern_id}-list")

    def on_mount(self) -> None:
        self._refresh_list()

    @property
    def patterns(self) -> list[str]:
        return list(self._patterns)

    @patterns.setter
    def patterns(self, value: list[str]) -> None:
        self._patterns = list(value)
        if self.is_mounted:
            self._refresh_list()

    def add_pattern(self, pattern: str) -> bool:
        """Add a pattern if valid and not duplicate. Returns True if added."""
        pattern = pattern.strip()
        if not pattern or pattern in self._patterns:
            return False
        self._patterns.append(pattern)
        self._refresh_list()
        return True

    def remove_pattern(self, pattern: str) -> bool:
        """Remove a pattern. Returns True if removed."""
        if pattern not in self._patterns:
            return False
        self._patterns.remove(pattern)
        self._refresh_list()
        return True

    def _create_pattern_item(self, pattern: str) -> PatternItem:
        """Create a pattern item widget with remove button."""
        item = PatternItem(classes="pattern-item")
        item.compose_add_child(Label(f"  {pattern}", classes="pattern-text"))
        encoded_pattern = _encode_pattern_token(pattern)
        item.compose_add_child(Static("✕", classes="pattern-remove-btn", id=f"remove-{self._pattern_id}-{encoded_pattern}"))
        return item

    def _refresh_list(self) -> None:
        """Rebuild the pattern list UI."""
        container = self.query_one(f"#{self._pattern_id}-list", containers.VerticalGroup)
        container.remove_children()
        if self._patterns:
            for pattern in self._patterns:
                container.mount(self._create_pattern_item(pattern))
        else:
            container.mount(Label("No patterns configured", classes="empty-message"))


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

    def __init__(self, enabled: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
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
        preview = preview.replace("{model}", "Alpha-7C")
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
        self._auto_backup_supported = True

    def compose(self) -> ComposeResult:
        with containers.VerticalScroll(id="content"):
            yield Markdown(SETTINGS_MD)
            yield Markdown(AUTO_BACKUP_MD)
            yield AutoBackupToggle(id="auto-backup-toggle")
            unsupported_msg = Markdown(AUTO_BACKUP_UNSUPPORTED_MD, id="auto-backup-unsupported")
            unsupported_msg.display = False
            yield unsupported_msg
            yield Rule(id="target-template-divider")
            yield TargetTemplateForm(id="target-template-form")
            yield Rule()
            yield Markdown(FILTER_RULES_MD)
            yield PatternListEditor(
                title="📂 Include Patterns",
                description="Files matching these patterns will be included (processed first)",
                pattern_id="include-patterns",
                id="include-patterns-editor",
            )
            yield PatternListEditor(
                title="🚫 Exclude Patterns",
                description="Files matching these patterns will be excluded from backup",
                pattern_id="exclude-patterns",
                id="exclude-patterns-editor",
            )
            yield Markdown(FILTER_HELP_MD)
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
        query = """
        query {
            autoBackupSupported
            config {
                autoBackupEnabled
                autoBackupTargetPath
                excludePatterns
                includePatterns
            }
        }
        """
        try:
            logger.debug("Loading configuration")
            result = await self.app.client.execute(query)
            config = result.get("config", {})
            self._auto_backup_supported = result.get("autoBackupSupported", True)
            self._original_config = config
            logger.debug("Loaded config: %s, autoBackupSupported: %s", config, self._auto_backup_supported)

            switch = self.query_one("#auto-backup-switch", Switch)
            switch.value = config.get("autoBackupEnabled", False)
            switch.disabled = not self._auto_backup_supported
            self._update_auto_backup_visibility(self._auto_backup_supported)

            template = config.get("autoBackupTargetPath", "")
            self.query_one("#target-template-input", Input).value = template
            self.query_one(TargetTemplateForm).update_preview(template)

            self.query_one("#include-patterns-editor", PatternListEditor).patterns = config.get("includePatterns", [])
            self.query_one("#exclude-patterns-editor", PatternListEditor).patterns = config.get("excludePatterns", [])

            self._show_status("✓ Configuration loaded", "success")
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
        """Save all settings to backend."""
        config_input = {
            "autoBackupEnabled": self.query_one("#auto-backup-switch", Switch).value if self._auto_backup_supported else False,
            "autoBackupTargetPath": self.query_one("#target-template-input", Input).value.strip(),
            "includePatterns": self.query_one("#include-patterns-editor", PatternListEditor).patterns,
            "excludePatterns": self.query_one("#exclude-patterns-editor", PatternListEditor).patterns,
        }
        self._show_status("⏳ Saving...", "info")
        logger.info("Saving config: %s", config_input)

        mutation = "mutation UpdateConfig($config: ConfigInput!) { updateConfig(config: $config) }"
        try:
            result = await self.app.client.execute(mutation, variable_values={"config": config_input})
            if result.get("updateConfig"):
                logger.info("Config saved successfully")
                self._original_config = {**config_input, "autoBackupSupported": self._auto_backup_supported}
                self._show_status("✓ Settings saved successfully!", "success")
                self.notify("Settings saved", title="Success", severity="information")
            else:
                self._show_status("⚠️ Settings may not have been saved", "info")
        except Exception as e:
            logger.error("Failed to save config: %s", e)
            self._show_status(f"✗ Failed to save: {e}", "error")
            self.notify(f"Failed: {e}", title="Error", severity="error")

    @on(Button.Pressed, "#reset-btn")
    def on_reset_pressed(self) -> None:
        """Reset all fields to last saved values."""
        self.query_one("#auto-backup-switch", Switch).value = self._original_config.get("autoBackupEnabled", False) and self._auto_backup_supported
        template = self._original_config.get("autoBackupTargetPath", "")
        self.query_one("#target-template-input", Input).value = template
        self.query_one(TargetTemplateForm).update_preview(template)
        self.query_one("#include-patterns-editor", PatternListEditor).patterns = self._original_config.get("includePatterns", [])
        self.query_one("#exclude-patterns-editor", PatternListEditor).patterns = self._original_config.get("excludePatterns", [])
        self._show_status("↺ Reset to last saved values", "info")

    @on(Button.Pressed, ".pattern-add-btn")
    def on_pattern_add_pressed(self, event: Button.Pressed) -> None:
        """Handle adding a pattern to include or exclude list."""
        editor = event.button.ancestors_with_self[2]  # Button -> HorizontalGroup -> PatternListEditor
        if not isinstance(editor, PatternListEditor):
            return
        input_field = editor.query_one(".pattern-input", Input)
        if editor.add_pattern(input_field.value):
            input_field.value = ""
        elif input_field.value.strip():
            self.notify("Pattern already exists", severity="warning")

    @on(Click, ".pattern-remove-btn")
    def on_pattern_remove_clicked(self, event: Click) -> None:
        """Handle removing a pattern from include or exclude list."""
        widget = event.widget
        widget_id = widget.id or ""
        for prefix in ("remove-include-patterns-", "remove-exclude-patterns-"):
            if widget_id.startswith(prefix):
                token = widget_id[len(prefix) :]
                pattern = _decode_pattern_token(token)
                if pattern is None:
                    return
                editor_id = "#" + prefix.replace("remove-", "").rstrip("-") + "-editor"
                self.query_one(editor_id, PatternListEditor).remove_pattern(pattern)
                break

    def _update_auto_backup_visibility(self, supported: bool) -> None:
        """Toggle auto backup UI based on backend support."""
        toggle = self.query_one(AutoBackupToggle)
        notice = self.query_one("#auto-backup-unsupported", Markdown)
        divider = self.query_one("#target-template-divider", Rule)
        template_form = self.query_one(TargetTemplateForm)
        toggle.display = supported
        notice.display = not supported
        divider.display = supported
        template_form.display = supported
