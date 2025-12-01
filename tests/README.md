# Test Suite

This directory contains the test suite for the SD Backup application, organized using pytest.

## Test Structure

All tests follow pytest conventions and are organized by functionality:

- **Unit Tests** (fast, no backend required):
  - `auto_backup_test.py` - Auto-backup functionality with mocked components
  - `path_hints_test.py` - Path hint context derivation
  - `rsync_parser_test.py` - Rsync output parser
  - `devices_test.py` - Device listing (mocked)
  - `web_mode_test.py` - CLI command help tests

- **Integration Tests** (slower, require backend):
  - `e2e_test.py` - End-to-end manual backup flow via GraphQL
  - `log_test.py` - Logging configuration and output
  - `subscription_test.py` - GraphQL subscriptions (WebSocket)

## Running Tests

### Prerequisites

```bash
# Install dependencies (including dev dependencies)
uv sync
```

### Quick Commands

```bash
# Run all tests
just test

# Run unit tests only (fast, no backend required)
just test-unit

# Run integration tests only (slower, starts backend)
just test-integration

# Run specific test file
just test-file auto_backup_test.py

# Run with coverage report
just test-cov

# Run in verbose mode
just test-v

# Stop on first failure
just test-x
```

### Direct pytest Commands

```bash
# Run all tests
uv run pytest

# Run specific test file
uv run pytest tests/auto_backup_test.py

# Run specific test function
uv run pytest tests/auto_backup_test.py::test_handle_device_triggers_backup

# Run with pattern matching
uv run pytest -k "backup"

# Skip integration tests
uv run pytest -m "not integration"

# Run only integration tests
uv run pytest -m integration

# Show print statements
uv run pytest -s

# Show full diff on failures
uv run pytest -vv
```

## Test Markers

Tests are marked with custom markers for easy filtering:

- `@pytest.mark.integration` - Integration tests that require the backend
- `@pytest.mark.asyncio` - Async tests (automatically handled by pytest-asyncio)

## Configuration

Test configuration is stored in:
- `pytest.ini` - pytest settings, markers, and defaults
- `conftest.py` - Shared fixtures and utilities

## Writing New Tests

### Unit Tests

```python
"""Tests for module functionality."""

def test_something():
    """Test description."""
    assert something() == expected
```

### Async Tests

```python
import pytest

@pytest.mark.asyncio
async def test_async_function():
    """Test async functionality."""
    result = await async_function()
    assert result == expected
```

### Integration Tests

```python
import pytest

@pytest.mark.asyncio
@pytest.mark.integration
async def test_with_backend(free_port):
    """Test requiring backend."""
    # Use free_port fixture for backend
    ...
```

## Shared Fixtures

Available fixtures from `conftest.py`:
- `free_port` - Returns an available port number for testing

## CI/CD

To run tests in CI environments:

```bash
# Run unit tests (fast feedback)
uv run pytest -m "not integration" --tb=short

# Run all tests
uv run pytest --tb=short
```

## Troubleshooting

**Tests hang or timeout:**
- Check if backend processes are still running: `ps aux | grep "app.py"`
- Integration tests start backend processes; they should clean up automatically

**Import errors:**
- Ensure you've run `uv sync` to install all dependencies
- The `conftest.py` adds `src/` to the Python path automatically

**Port conflicts:**
- Integration tests use dynamic port allocation (port 0)
- If tests fail with port errors, check for zombie processes

