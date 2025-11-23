# SD Backup Tool - Technical Documentation

## Overview

The SD Backup Tool is a Python application designed to automatically back up storage cards (USB drives) when inserted. It provides both manual and automatic backup functionality through a separated backend and frontend architecture.

## Architecture

### High-Level Design

```
┌─────────────────┐
│   Textual UI    │ ← Frontend (Optional)
│   (Frontend)    │
└────────┬────────┘
         │ WebSocket/HTTP
         │ (GraphQL)
┌────────▼────────┐
│   FastAPI       │ ← Backend
│   + GraphQL     │
└────────┬────────┘
         │
    ┌────┴────┬─────────┬──────────┐
    │         │         │          │
┌───▼───┐ ┌──▼───┐ ┌───▼────┐ ┌──▼────┐
│ pyudev│ │rsync │ │ config │ │ logs  │
│monitor│ │backup│ │ YAML   │ │ file  │
└───────┘ └──────┘ └────────┘ └───────┘
```

### Component Overview

#### 1. Entry Point (`src/main.py`)
- Single entry point for the application
- Parses command-line arguments (`--headless` flag, optional `--host`/`--port` overrides)
- Loads configuration from `config.yaml`
- Configures logging (file or stderr)
- Allocates dynamic port (if configured as 0)
- Starts backend in a separate thread
- Optionally starts frontend (Textual UI)

#### 2. Backend (`src/backend/`)

**`server.py`**
- FastAPI application with GraphQL endpoint
- Manages application lifecycle (startup/shutdown)
- Initializes device monitor on startup

**`monitor.py`**
- Uses `pyudev` to detect USB storage devices
- Filters for:
  - Block devices
  - Partitions (partition #1)
  - USB bus
  - Filesystems: exfat, fat32, udf
- Triggers automatic backup on device insertion

**`backup.py`**
- Manages backup operations using `rsync`
- Handles device mounting
- Resolves target paths with template variables
- Supports backup cancellation

**`schema.py`**
- Strawberry GraphQL schema definition
- Queries: `config`, `logs`, `currentStatus`
- Mutations: `startManualBackup`, `cancelBackup`, `updateConfig`
- Subscriptions: `backupProgress`

#### 3. Frontend (`src/frontend/`)

**`app.py`**
- Textual application main entry point
- Receives host/port from `main.py`
- Creates GraphQL client

**`client.py`**
- GraphQL client using `gql` library
- WebSocket transport for subscriptions
- HTTP transport for queries/mutations

**`screens.py`**
- Dashboard: Shows status, logs, manual backup controls
- Settings: Configuration editor
- ManualBackupDialog: Input dialog for manual backups

#### 4. Configuration (`src/config.py`)
- YAML-based configuration management
- Default values for all settings
- Provides `load_config()`, `save_config()`, `update_config()`

## Data Flow

### Automatic Backup Flow

```
1. USB device inserted
2. pyudev detects event → DeviceMonitor.match_device()
3. If match: device_callback() triggered
4. Mount device → get mount point
5. Resolve target path (with templates)
6. Execute rsync backup
7. Log completion
8. Emit GraphQL subscription event
```

### Manual Backup Flow

```
1. User enters source/target in UI
2. GraphQL mutation: startManualBackup
3. Mutation handler starts backup in thread
4. rsync executes
5. Logs emitted via subscription
6. UI updates in real-time
```

## Configuration

### Configuration File (`config.yaml`)

All configuration is stored in `config.yaml` in the project root.

**Fields:**
- `graphql_host` (default: `127.0.0.1`) - Backend listen address
- `graphql_port` (default: `0`) - Backend port (0 = dynamic allocation)
- `log_path` (default: `null`) - Log file path (null = stderr)
- `mount_point_template` (default: `/media/sd-backup-{uuid}`) - Mount point template
- `target_path_template` (default: `~/backups/{date}`) - Backup target template

### Template Variables

The following variables can be used in `target_path_template`:

- `{date}` - Date in YYYYMMDD format (earliest file mtime)
- `{hour}` - Hour in HH format (earliest file mtime)
- `{minute}` - Minute in MM format (earliest file mtime)
- `{uuid}` - Filesystem UUID
- `{uuid_short}` - First 4 characters of UUID

## Device Matching Logic

The `match_device()` function filters device events based on:

```python
all([
    d.subsystem == "block",
    d.action == "add",
    d.device_type == "partition",
    d.get("ID_BUS") == "usb",
    d.sys_number == "1",  # First partition only
    d.get("ID_FS_TYPE", "").lower() in {"exfat", "fat32", "udf"},
])
```

## Logging

Logging is configured in `main.py`:

- If `log_path` is set: All logs go to file, stdout/stderr are silent
- If `log_path` is null: Logs go to stderr with timestamps

All Python loggers inherit from the root logger configuration.

## Dynamic Port Allocation

When `graphql_port` is set to `0`:

1. `get_free_port()` finds an available port
2. Port is passed to both backend and frontend
3. Tests can set a port explicitly with `--port` to avoid collisions

## Running the Application

### Full Mode (Backend + Frontend)
```bash
uv run python src/main.py
```

### Headless Mode (Backend Only)
```bash
uv run python src/main.py --headless
```

## Development

### Project Structure
```
sd-backup/
├── src/
│   ├── backend/       # Backend code
│   ├── frontend/      # Frontend code
│   ├── config.py      # Configuration management
│   └── main.py        # Entry point
├── tests/             # Test files
├── docs/              # Documentation
├── config.yaml        # Configuration file
└── pyproject.toml     # Project metadata
```

### Testing

**E2E Test:**
```bash
uv run python tests/e2e_test.py
```

**Auto Backup Test:**
```bash
uv run python tests/auto_backup_test.py
```

**Log Test:**
```bash
uv run python tests/log_test.py
```

## Dependencies

Core dependencies:
- `fastapi` - Web framework
- `strawberry-graphql` - GraphQL library
- `uvicorn` - ASGI server
- `pyudev` - Device detection
- `textual` - Terminal UI
- `gql[websockets]` - GraphQL client
- `pyyaml` - YAML parsing

## Security Considerations

**Root Privileges:**
- The application must run with root privileges for:
  - `pyudev` device monitoring
  - `mount` operations
  - Accessing `/proc/mounts`

**File Permissions:**
- Backup files inherit source permissions
- Config file should be readable only by root

## Performance

- Backup uses `rsync -av --info=progress2`
- No output parsing (minimal overhead)
- Async GraphQL subscriptions for real-time updates
- Backend runs in separate thread from frontend

## Troubleshooting

**Device not detected:**
- Check if device is USB and partition #1
- Verify filesystem type (exfat/fat32/udf)
- Check pyudev permissions

**Mount fails:**
- Ensure mount point directory exists
- Check if device already mounted
- Verify root privileges

**GraphQL connection fails:**
- Check backend is running and port is correct
- If using dynamic ports, ensure the chosen port is passed to the frontend/startup command
- Check firewall/network settings
