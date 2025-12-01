"""Tests for backend/config.py configuration handling."""

import pytest

from backend.config import (
    DEFAULT_AUTO_TEMPLATE,
    Config,
    _parse_patterns,
    get_config,
    update_config,
)
from backend.db import Config as ConfigTable, session_scope


class TestParsePatterns:
    """Tests for _parse_patterns helper function."""

    def test_parses_valid_json_array(self):
        """Test parsing a valid JSON array."""
        result = _parse_patterns('["*.jpg", "*.png"]')
        assert result == ["*.jpg", "*.png"]

    def test_returns_empty_list_for_empty_array(self):
        """Test parsing an empty JSON array."""
        result = _parse_patterns("[]")
        assert result == []

    def test_returns_empty_list_for_invalid_json(self):
        """Test that invalid JSON returns empty list."""
        result = _parse_patterns("not valid json")
        assert result == []

    def test_returns_empty_list_for_non_array_json(self):
        """Test that non-array JSON returns empty list."""
        result = _parse_patterns('{"key": "value"}')
        assert result == []

    def test_returns_empty_list_for_none(self):
        """Test that None returns empty list."""
        result = _parse_patterns(None)
        assert result == []

    def test_parses_patterns_with_special_chars(self):
        """Test parsing patterns with special characters."""
        result = _parse_patterns('["**/node_modules/**", "*.{tmp,bak}"]')
        assert result == ["**/node_modules/**", "*.{tmp,bak}"]


@pytest.mark.asyncio
class TestConfigStore:
    """Tests for config store initialization and operations."""

    async def test_init_creates_default_config(self, fresh_db):
        """Test that init_config_store creates default config row."""
        # Create default config row
        async with session_scope() as session:
            config = ConfigTable(
                id=1,
                auto_backup_enabled=False,
                auto_backup_target_path=DEFAULT_AUTO_TEMPLATE,
                exclude_patterns="[]",
                include_patterns="[]",
            )
            session.add(config)

        result = await get_config()
        assert result.auto_backup_enabled is False
        assert result.auto_backup_target_path == DEFAULT_AUTO_TEMPLATE
        assert result.exclude_patterns == []
        assert result.include_patterns == []

    async def test_get_config_returns_current_values(self, fresh_db):
        """Test that get_config returns current configuration."""
        # Create config row
        async with session_scope() as session:
            config = ConfigTable(
                id=1,
                auto_backup_enabled=True,
                auto_backup_target_path="/test/path",
                exclude_patterns='["*.tmp"]',
                include_patterns='["*.jpg"]',
            )
            session.add(config)

        result = await get_config()
        assert isinstance(result, Config)
        assert result.auto_backup_enabled is True
        assert result.auto_backup_target_path == "/test/path"

    async def test_update_config_changes_auto_backup_enabled(self, fresh_db):
        """Test updating auto_backup_enabled setting."""
        # Create config row
        async with session_scope() as session:
            config = ConfigTable(
                id=1,
                auto_backup_enabled=False,
                auto_backup_target_path=DEFAULT_AUTO_TEMPLATE,
                exclude_patterns="[]",
                include_patterns="[]",
            )
            session.add(config)

        # Update to enabled
        updated = await update_config(auto_backup_enabled=True)
        assert updated.auto_backup_enabled is True

        # Verify persisted
        result = await get_config()
        assert result.auto_backup_enabled is True

    async def test_update_config_changes_target_path(self, fresh_db):
        """Test updating auto_backup_target_path setting."""
        # Create config row
        async with session_scope() as session:
            config = ConfigTable(
                id=1,
                auto_backup_enabled=False,
                auto_backup_target_path=DEFAULT_AUTO_TEMPLATE,
                exclude_patterns="[]",
                include_patterns="[]",
            )
            session.add(config)

        new_path = "~/my-backups/{date}"
        updated = await update_config(auto_backup_target_path=new_path)
        assert updated.auto_backup_target_path == new_path

    async def test_update_config_changes_exclude_patterns(self, fresh_db):
        """Test updating exclude_patterns setting."""
        # Create config row
        async with session_scope() as session:
            config = ConfigTable(
                id=1,
                auto_backup_enabled=False,
                auto_backup_target_path=DEFAULT_AUTO_TEMPLATE,
                exclude_patterns="[]",
                include_patterns="[]",
            )
            session.add(config)

        patterns = ["*.tmp", "*.bak", ".DS_Store"]
        updated = await update_config(exclude_patterns=patterns)
        assert updated.exclude_patterns == patterns

    async def test_update_config_changes_include_patterns(self, fresh_db):
        """Test updating include_patterns setting."""
        # Create config row
        async with session_scope() as session:
            config = ConfigTable(
                id=1,
                auto_backup_enabled=False,
                auto_backup_target_path=DEFAULT_AUTO_TEMPLATE,
                exclude_patterns="[]",
                include_patterns="[]",
            )
            session.add(config)

        patterns = ["*.jpg", "*.raw", "*.mp4"]
        updated = await update_config(include_patterns=patterns)
        assert updated.include_patterns == patterns

    async def test_update_config_partial_update(self, fresh_db):
        """Test that partial updates don't affect other fields."""
        # Create config row
        async with session_scope() as session:
            config = ConfigTable(
                id=1,
                auto_backup_enabled=False,
                auto_backup_target_path=DEFAULT_AUTO_TEMPLATE,
                exclude_patterns="[]",
                include_patterns="[]",
            )
            session.add(config)

        # First update exclude patterns
        await update_config(exclude_patterns=["*.tmp"])

        # Then update auto_backup_enabled without touching exclude_patterns
        updated = await update_config(auto_backup_enabled=True)

        assert updated.auto_backup_enabled is True
        assert updated.exclude_patterns == ["*.tmp"]

