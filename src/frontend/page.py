"""Base PageScreen class for SD Backup frontend screens."""

from __future__ import annotations

from textual.screen import Screen


class PageScreen(Screen):
    """Base screen class for all page screens in the application."""

    DEFAULT_CSS = """
    PageScreen {
        width: 100%;
        height: 1fr;
        overflow-y: auto;
    }
    """

