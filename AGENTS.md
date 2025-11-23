# AGENTS.md - AI Agent Guide for SD Backup Tool

This document helps AI coding agents understand and work with the SD Backup Tool codebase effectively.

## Project Overview

**Purpose:** Automatic backup tool for USB storage devices using rsync, with GraphQL API and terminal UI.

**Tech Stack:** Python 3.12+, FastAPI, Strawberry GraphQL, Textual, pyudev, rsync

**Architecture:** Backend (FastAPI + GraphQL) + Frontend (Textual UI), single entry point in `src/main.py`

## Key Files & Responsibilities

### Entry Point
- **`src/main.py`** - Application entry point, logging config, port allocation, starts backend & frontend

### Backend
- **`src/backend/server.py`** - FastAPI app, GraphQL router, device monitor lifecycle
- **`src/backend/schema.py`** - GraphQL schema (queries, mutations, subscriptions)
- **`src/backend/backup.py`** - Backup operations (rsync, mounting, path resolution)
- **`src/backend/monitor.py`** - USB device detection using pyudev

### Frontend
- **`src/frontend/app.py`** - Textual app entry point
- **`src/frontend/client.py`** - GraphQL client (WebSocket + HTTP)
- **`src/frontend/screens.py`** - UI screens (Dashboard, Settings, Dialogs)

### Core
- **`src/config.py`** - Configuration management (YAML load/save/update)
- **`config.yaml`** - User configuration file (auto-generated)

### Tests
- **`tests/e2e_test.py`** - End-to-end test with subprocess
- **`tests/auto_backup_test.py`** - Unit test for automatic backup
- **`tests/log_test.py`** - Logging verification test

### Documentation
- **`docs/technical.md`** - Technical architecture and design
- **`docs/api.md`** - GraphQL API reference

## Common Tasks

### Adding a New Configuration Field

1. Update `DEFAULT_CONFIG` in `src/config.py`
2. Update GraphQL `Config` type in `src/backend/schema.py`
3. Update config query resolver if needed
4. Update `docs/technical.md` configuration section
5. Test with `tests/e2e_test.py`

### Adding a New GraphQL Mutation

1. Add mutation method to `Mutation` class in `src/backend/schema.py`
2. Implement business logic in appropriate module (`backup.py`, `monitor.py`, etc.)
3. Add example to `docs/api.md`
4. Update frontend if user-facing (add UI in `screens.py`)

### Adding a New Device Filter Criterion

1. Update `match_device()` in `src/backend/monitor.py`
2. Update device matching logic documentation in `docs/technical.md`
3. Test with actual device or update `tests/auto_backup_test.py` mock

### Modifying Logging Behavior

1. Update `configure_logging()` in `src/main.py`
2. Ensure `src/backend/server.py` doesn't call `basicConfig`
3. Test with `tests/log_test.py`
4. Update docs if changing config schema

## Project Conventions

### Import Style
- Standard library imports first
- Third-party imports second
- Local imports last
- Use relative imports within packages (`from frontend.client import ...`)

### Logging
- All modules use `logging.getLogger(__name__)`
- No `basicConfig` calls except in `main.py`
- Log levels: INFO for normal operations, ERROR for failures

### Configuration
- All config through `config.yaml`
- Frontend never reads config directly (gets values from `main.py`)
- Use `load_config()` only in `main.py` and `backend/` modules

### GraphQL Schema
- Use Strawberry decorators (`@strawberry.type`, etc.)
- Mutations return `String!` status messages
- Subscriptions use `AsyncGenerator`
- Keep schema in `backend/schema.py`, logic in other modules

### Testing
- E2E tests run `main.py` as subprocess
- Read dynamic port from `.port` file
- Clean up test files/directories in `finally` blocks
- Mock `pyudev.Device` for unit tests

## Critical Patterns

### Dynamic Port Allocation
```python
# main.py
if port == 0:
    port = get_free_port()
with open(".port", "w") as f:
    f.write(str(port))

# tests/e2e_test.py
with open(".port", "r") as f:
    port = int(f.read().strip())
```

### Device Matching
```python
# backend/monitor.py
def match_device(d):
    return all([
        d.subsystem == "block",
        d.action == "add",
        d.device_type == "partition",
        d.get("ID_BUS") == "usb",
        d.sys_number == "1",
        d.get("ID_FS_TYPE", "").lower() in {"exfat", "fat32", "udf"},
    ])
```

### GraphQL Client Setup
```python
# frontend/client.py
# Separate transports for queries/mutations (HTTP) and subscriptions (WebSocket)
http_transport = AIOHTTPTransport(url=self.http_url)
ws_transport = WebsocketsTransport(url=self.url)
```

## Important Constraints

### Root Privileges Required
- Device monitoring via pyudev
- Mount/unmount operations
- Reading `/proc/mounts`

### No Stdout When Logging to File
- If `log_path` is set, no output to stdout/stderr
- Even print statements are suppressed in headless mode with log file
- Uvicorn logs redirected to file

### Frontend is Optional
- Backend can run standalone in headless mode
- Frontend receives host/port from `main.py`, never reads config
- GraphQL API is fully functional without frontend

### Single Entry Point
- Always run via `uv run python src/main.py`
- Never run `backend/server.py` or `frontend/app.py` directly
- `main.py` handles all initialization

## What NOT to Do

❌ **Don't** call `logging.basicConfig()` outside `main.py`
❌ **Don't** read `config.yaml` in frontend code
❌ **Don't** hardcode ports (use 0 for dynamic allocation)
❌ **Don't** use `PYTHONPATH` (use proper package structure)
❌ **Don't** run backend/frontend modules directly (use `main.py`)
❌ **Don't** add print statements that bypass logging
❌ **Don't** block the main thread in backend (use threads for long operations)

## File Modification Guidelines

### When Editing `main.py`
- Be careful with logging configuration order
- Ensure `.port` file is written before backend starts
- Pass host/port to frontend explicitly

### When Editing `schema.py`
- Keep business logic in other modules
- Return user-friendly error messages
- Use threads for long-running mutations

### When Editing `backup.py`
- Always handle subprocess errors
- Store process handle for cancellation
- Expand `~` in paths before use

### When Editing `monitor.py`
- Don't block the monitor loop
- Log all errors in callback
- Use daemon thread

## Testing Strategy

### Before Committing
1. Run E2E test: `uv run python tests/e2e_test.py`
2. Run auto backup test: `uv run python tests/auto_backup_test.py`
3. Run log test: `uv run python tests/log_test.py`

### Manual Testing Checklist
- [ ] Backend starts in headless mode
- [ ] Frontend connects to backend
- [ ] Manual backup works from UI
- [ ] Config changes persist to YAML
- [ ] Logs go to correct destination
- [ ] Port file is created with correct port

## Useful Commands

```bash
# Run application
uv run python src/main.py              # Full mode
uv run python src/main.py --headless   # Backend only

# Run tests
uv run python tests/e2e_test.py
uv run python tests/auto_backup_test.py
uv run python tests/log_test.py

# Install dependencies
uv sync

# View dynamic port
cat .port

# Check logs (if logging to file)
tail -f backend.log
```

## Debugging Tips

### Backend Won't Start
- Check if port is already in use
- Verify `config.yaml` syntax
- Check for import errors in `backend/`

### Frontend Can't Connect
- Verify `.port` file exists and contains valid port
- Check backend is actually running
- Try hardcoded port for debugging

### Logs Not Appearing
- Check `log_path` in config
- Verify file permissions
- Ensure `main.py` configured logging before imports

### Device Not Detected
- Check `match_device()` criteria
- Use `rich.inspect(dev)` in callback to debug
- Verify device is partition #1
- Check filesystem type with `lsblk -f`

## External References

- **FastAPI Docs:** https://fastapi.tiangolo.com/
- **Strawberry GraphQL:** https://strawberry.rocks/
- **Textual:** https://textual.textualize.io/
- **pyudev:** https://pyudev.readthedocs.io/
- **gql:** https://gql.readthedocs.io/

## Version Information

- **Minimum Python:** 3.12
- **Package Manager:** uv
- **Build System:** hatchling

## Contributing

When making changes:
1. Update relevant tests
2. Update documentation (this file, `docs/`, docstrings)
3. Verify all tests pass
4. Check that logging works correctly
5. Test both headless and full mode
