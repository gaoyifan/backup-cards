"""Shared utilities for frontend screens."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from frontend.client import GraphQLClient

logger = logging.getLogger(__name__)


def fmt_bytes(size: int) -> str:
    """Format bytes to human readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def shorten_path(path: str, max_len: int = 28) -> str:
    """Truncate path from the start if too long."""
    return path if len(path) <= max_len else f"...{path[-(max_len - 3):]}"


def calc_percent(completed: int | None, total: int | None) -> float:
    """Calculate percentage, handling None/zero values."""
    completed, total = completed or 0, total or 1
    return (completed / total) * 100 if total > 0 else 0


def fmt_progress(completed: int | None, total: int | None) -> str:
    """Format progress as 'X / Y (Z%)'."""
    completed, total = completed or 0, total or 0
    if total > 0:
        percent = (completed / total) * 100
        return f"{fmt_bytes(completed)} / {fmt_bytes(total)} ({percent:.1f}%)"
    return "0 bytes"


class ProgressSubscriptionManager:
    """Manages progress subscriptions for multiple active tasks."""

    def __init__(self, client_getter: Callable[[], GraphQLClient], on_progress: Callable[[str, int, int], None]):
        self._client_getter = client_getter
        self._on_progress = on_progress
        self._subs: dict[str, asyncio.Task] = {}

    def sync(self, tasks: list[dict]) -> None:
        """Sync subscriptions with current active tasks."""
        active_ids = {t["backupId"] for t in tasks if t.get("status") == "IN_PROGRESS"}

        # Stop subscriptions for tasks no longer active
        for backup_id in list(self._subs.keys()):
            if backup_id not in active_ids:
                self._subs.pop(backup_id).cancel()

        # Start subscriptions for new active tasks
        for backup_id in active_ids:
            if backup_id not in self._subs:
                self._subs[backup_id] = asyncio.create_task(self._subscribe(backup_id))

    def cancel_all(self) -> None:
        """Cancel all active subscriptions."""
        for sub in self._subs.values():
            sub.cancel()
        self._subs.clear()

    async def _subscribe(self, backup_id: str) -> None:
        """Subscribe to progress updates for a task."""
        query = """subscription($id: ID!) { progress(backupId: $id) { sizeCompleted sizeTotal }}"""
        try:
            async for payload in self._client_getter().subscribe(query, variable_values={"id": backup_id}):
                p = payload.get("progress", {})
                self._on_progress(backup_id, p.get("sizeCompleted", 0), p.get("sizeTotal", 0))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning("Progress subscription error for %s: %s", backup_id, e)
        finally:
            self._subs.pop(backup_id, None)
