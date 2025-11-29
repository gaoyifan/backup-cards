"""Utilities for showing path typing hints in Textual inputs."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from textual.screen import Screen
from textual.widgets import Input, Static

logger = logging.getLogger(__name__)

LIST_DIRECTORY_QUERY = """
query ListDirectory($path: String!) {
  listDirectory(path: $path)
}
"""


@dataclass(slots=True)
class HintContext:
    """Resolved context for a hint lookup."""

    query_path: str
    display_base: str
    partial: str


@dataclass(slots=True)
class HintState:
    """Cached hint results for an input."""

    suggestions: list[str]
    context: HintContext
    selected: int = 0


def _split_path_prefix(value: str) -> tuple[str, str]:
    """Return base (always ending with slash) and partial component."""
    if value.endswith("/"):
        return value, ""
    idx = value.rfind("/")
    if idx == -1:
        return "", value
    return value[: idx + 1], value[idx + 1 :]


def _base_to_query_path(base: str) -> str:
    """Convert a display base into a filesystem path used for querying."""
    if base == "/":
        return "/"
    normalized = base[:-1] if base.endswith("/") else base
    if not normalized:
        normalized = "~"
    expanded = os.path.expanduser(normalized)
    return str(Path(expanded))


def derive_hint_context(raw_value: str) -> HintContext | None:
    """Prepare a hint lookup context from user-provided text."""
    value = (raw_value or "").strip()
    if not value or value == "~":
        base = "~/"
        return HintContext(query_path=str(Path.home()), display_base=base, partial="")

    if not value.startswith(("~", "/")):
        return None

    base, partial = _split_path_prefix(value)
    if not base:
        if value.startswith("~"):
            base = "~/"
            partial = value[1:]
        else:
            # Paths that are neither absolute nor home-relative are not supported
            return None

    query_path = _base_to_query_path(base)
    return HintContext(query_path=query_path, display_base=base, partial=partial)


class PathHintBox(Static):
    """Simple container that renders hint suggestions."""

    DEFAULT_CSS = """
    PathHintBox {
        height: auto;
        padding: 0 1 1 1;
        margin-top: 0;
        background: $boost;
        border-left: tall $accent;
        color: $text;
        &.hidden { display: none; }
    }
    
    PathHintBox .hint-line {
        color: $text;
    }
    
    PathHintBox .hint-helper {
        color: $text-muted;
    }
    """

    def show_loading(self) -> None:
        self.update("[dim]Looking up matching entries...[/dim]")
        self.remove_class("hidden")

    def show_hints(self, suggestions: list[str], selected_index: int = 0) -> None:
        if not suggestions:
            self.hide_hints()
            return

        lines = []
        total = len(suggestions)
        if total == 1:
            selected_index = 0
        else:
            selected_index = max(0, min(selected_index, total - 1))

        for idx, hint in enumerate(suggestions):
            marker = "→" if idx == selected_index else "  "
            line = f"{marker} {hint}"
            if idx == selected_index:
                line = f"[reverse]{line}[/reverse]"
            lines.append(line)

        lines.append("[dim]Use ↑/↓ to choose, Tab to insert[/dim]")
        self.update("\n".join(lines))
        self.remove_class("hidden")

    def hide_hints(self) -> None:
        self.update("")
        self.add_class("hidden")


class PathHintManager:
    """Manage asynchronous lookup of path hints for one or more inputs."""

    def __init__(self, screen: Screen, max_results: int = 5, debounce: float = 0.25) -> None:
        self._screen = screen
        self._max_results = max_results
        self._debounce = debounce
        self._registrations: dict[str, str] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._states: dict[str, HintState] = {}

    def register(self, input_id: str, hint_box_id: str) -> None:
        """Attach an input to a hint container."""
        self._registrations[input_id] = hint_box_id

    def handle_change(self, input_id: str, value: str) -> None:
        """Debounce hint lookups when the input value changes."""
        if input_id not in self._registrations:
            return

        if not value.strip():
            self._cancel_task(input_id)
            self._clear_state(input_id)
            return

        box = self._get_box(input_id)
        box.show_loading()

        task = self._tasks.get(input_id)
        if task:
            task.cancel()

        self._tasks[input_id] = asyncio.create_task(self._update_hints(input_id, value))

    def handle_blur(self, input_id: str) -> None:
        """Hide hints when focus leaves the input."""
        if input_id not in self._registrations:
            return
        self._cancel_task(input_id)
        self._clear_state(input_id)

    def apply_tab_completion(self, widget: Input) -> bool:
        """Apply the first hint to the focused input when Tab is pressed."""
        widget_id = widget.id
        if not widget_id:
            return False

        state = self._states.get(widget_id)
        if not state or not state.suggestions:
            return False

        suggestion = state.suggestions[state.selected]
        widget.value = suggestion
        widget.cursor_position = len(suggestion)

        box = self._get_box(widget_id)
        box.hide_hints()
        return True

    def adjust_selection(self, input_id: str, delta: int) -> bool:
        """Move the highlighted suggestion up/down when hints are visible."""
        state = self._states.get(input_id)
        if not state or not state.suggestions:
            return False

        count = len(state.suggestions)
        if count == 0:
            return False

        state.selected = (state.selected + delta) % count
        self._render_state(input_id)
        return True

    def reset(self) -> None:
        """Cancel any pending lookups and clear UI state."""
        for input_id in list(self._tasks.keys()):
            self._cancel_task(input_id)
        for input_id in list(self._states.keys()):
            self._clear_state(input_id)

    async def _update_hints(self, input_id: str, raw_value: str) -> None:
        try:
            await asyncio.sleep(self._debounce)
            context = derive_hint_context(raw_value)
            if context is None:
                self._clear_state(input_id)
                return

            suggestions = await self._fetch_suggestions(context)
            self._states[input_id] = HintState(
                suggestions=suggestions,
                context=context,
                selected=0,
            )
            self._render_state(input_id)
        except asyncio.CancelledError:
            logger.debug("Cancelled hint lookup for %s", input_id)
        except Exception as exc:
            logger.debug("Hint lookup failed for %s: %s", input_id, exc)
            self._clear_state(input_id)
        finally:
            self._tasks.pop(input_id, None)

    async def _fetch_suggestions(self, context: HintContext) -> list[str]:
        client = self._screen.app.client
        try:
            result = await client.execute(
                LIST_DIRECTORY_QUERY,
                variable_values={"path": context.query_path},
            )
        except Exception as exc:
            logger.debug("GraphQL directory lookup failed: %s", exc)
            return []

        entries = result.get("listDirectory", []) or []

        suggestions: list[str] = []
        fragment = context.partial.lower()
        for entry in entries:
            entry_name = str(entry)
            if fragment and not entry_name.lower().startswith(fragment):
                continue
            suggestions.append(f"{context.display_base}{entry_name}")
            if len(suggestions) >= self._max_results:
                break
        return suggestions

    def _clear_state(self, input_id: str) -> None:
        self._states.pop(input_id, None)
        box = self._get_box(input_id, suppress_errors=True)
        if box:
            box.hide_hints()

    def _cancel_task(self, input_id: str) -> None:
        task = self._tasks.pop(input_id, None)
        if task:
            task.cancel()

    def _get_box(self, input_id: str, suppress_errors: bool = False) -> PathHintBox | None:
        hint_id = self._registrations.get(input_id)
        if hint_id is None:
            raise KeyError(f"No hint box registered for {input_id}")
        try:
            return self._screen.query_one(f"#{hint_id}", PathHintBox)
        except Exception:
            if suppress_errors:
                return None
            raise

    def _render_state(self, input_id: str) -> None:
        state = self._states.get(input_id)
        box = self._get_box(input_id, suppress_errors=True)
        if not box:
            return
        if not state or not state.suggestions:
            box.hide_hints()
            return
        box.show_hints(state.suggestions, state.selected)


__all__ = [
    "derive_hint_context",
    "PathHintBox",
    "PathHintManager",
]

