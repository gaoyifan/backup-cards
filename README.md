# SD Backup

Automation-friendly backups for removable media. SD Backup continuously watches for newly attached SD cards or USB drives, mounts them, and uses `rsync` to copy their contents to predictable directories. A FastAPI + Strawberry GraphQL backend powers both a Textual terminal UI and a browser-based UI so you can monitor progress, trigger manual jobs, and tweak configuration without touching shell scripts.

---

## Highlights

- **Automatic device monitoring:** `pyudev` detects supported devices, mounts them, and kicks off `rsync` with smart retry and cancellation logic.
- **Unified backend:** FastAPI + GraphQL (`/graphql`) exposes queries, mutations, and subscriptions for real-time status updates.
- **Rich frontends:** Choose between the terminal-native Textual dashboard, a browser UI served via `textual-serve`, or headless daemon mode.
- **Template-driven targets:** Build destination paths with variables such as `{date}`, `{uuid}`, or `{uuid_short}`, persisted in SQLite for durability.
- **Batteries-included CLI:** `app.py` (Typer) configures logging, ports, and database paths, ensuring consistent startup on macOS and Linux.

## Architecture at a Glance

- `app.py` — single entry point that configures logging, spins up the backend, and launches the desired UI mode.
- `src/backend/` — FastAPI app (`server.py`), GraphQL schema (`schema.py`), device monitor (`monitor.py`), backup engine (`backup.py`), and SQLite config store (`config.py`, `db.py`).
- `src/frontend/` — Textual UI (`app.py`, `screens.py`) plus GraphQL client helpers.
- `docs/` — API schema, PRD, packaging notes, and deep-dive technical docs.

See `docs/technical.md` for full diagrams and `docs/api.md` for schema details.

## Requirements

- Python 3.12+ (managed via [`uv`](https://github.com/astral-sh/uv)).
- `rsync`, `mount`, and (on Linux) `pyudev` with permissions to watch USB events. Automatic backups typically require root or equivalent privileges.
- macOS 14+ or a recent Linux distribution. The browser UI relies on `textual-serve`; the optional desktop WebView wrapper currently targets macOS.

## Installation

```bash
uv sync
```

This installs runtime and development dependencies into `.venv`. All commands below assume you run them with `uv run ...` from the repository root.

## Running the App

Launch SD Backup with Typer CLI commands:

```bash
uv run python app.py [OPTIONS] [COMMAND]
```

- The default command chooses the most appropriate UI for your platform (browser UI on macOS, terminal UI on Linux).
- Subcommands such as `tui`, `web`, `connect`, and `daemon` are available for explicit control—run `uv run python app.py --help` to see every mode and flag.
- Persistent flags like `--db-path`, `--log-path`, `--listen-port`, `--web-port`, and `--with-webview` can be combined with any command as needed.

### Docker Compose

The included `docker-compose.yml` builds the same application image defined in `Dockerfile`, exposes the web UI on port `8080`, and mounts a `./data` directory from the host for persistent state/logs.

```bash
docker compose up -d --build
```

- Use `-d` to run in the background and `docker compose logs -f sd-backup` to follow output.
- The container defaults to the web mode (`textual-serve`) listening on `0.0.0.0:8080`. Adjust the published port (`HOST:CONTAINER`) in `docker-compose.yml` if you need a different host port.
- Mount additional host paths under `volumes:` when you want backups to land somewhere outside `./data`.
- USB device passthrough and automatic mounts require running Docker with the right privileges on Linux (e.g., `--privileged` or explicit device mapping); macOS/Windows Docker Desktop cannot monitor local USB buses directly, so Compose is best suited for headless/manual backups on a Linux host.

### Logging & storage options

- `--log-path /path/to/backend.log` writes structured logs to a file; omit for stderr.
- `--log-level DEBUG|INFO|...` adjusts verbosity.
- `--db-path /path/to/sd-backup.db` controls where runtime configuration is persisted. The folder is created automatically if needed.

## Using `just`

Common workflows are encapsulated in the `Justfile`. Run `just <recipe>` (install [just](https://github.com/casey/just) first).

| Recipe | Description |
| --- | --- |
| `just tui` | Launch Textual UI with logging suppressed. |
| `just web` | Start browser UI with an embedded WebView. |
| `just daemon` | Backend-only mode on the default settings. |
| `just connect <host> <port>` | Attach the UI to an existing backend. |
| `just build` | Build a macOS app bundle via PyInstaller. |
| `just clean` / `just rebuild` | Remove `dist/` artifacts, optionally rebuild immediately. |
| `just fmt` | Run autoflake, isort, and black over `src/` and `tests/`. |

Every recipe maps to the equivalent `uv run python app.py ...` command, so you can copy/paste them into CI as needed.

## Configuration

### CLI flags

- `--listen-addr` / `--listen-port` (daemon mode) control the FastAPI bind address. Port `0` asks the OS for a free port.
- `--web-host` / `--web-port` tune the HTTP server that renders the Textual UI.
- `--with-webview` launches a native wrapper window on macOS.

### Runtime templates

`src/backend/config.py` stores the `mount_point_template` and `target_path_template` inside a SQLite DB referenced by `--db-path`. The GraphQL mutation `updateConfig(key, value)` or the UI settings panel let you change them without restarting.

Available template variables:

| Variable | Description |
| --- | --- |
| `{date}` | `YYYYMMDD` from the earliest file timestamp on/after 2020-01-01 (fallback: current date). |
| `{hour}` / `{minute}` | Earliest modification time components. |
| `{uuid}` | Full filesystem UUID. |
| `{uuid_short}` | First four characters of the UUID. |

## GraphQL API

- Endpoint: `http://<backend-host>:<port>/graphql`
- Queries: `config`, `logs`, `currentStatus`
- Mutations: `startManualBackup`, `cancelBackup`, `updateConfig`
- Subscriptions: `backupProgress` (streams log lines and status updates)

Refer to `docs/api.md` or `docs/api.gql` for the full schema. You can interactively explore it via the built-in GraphQL Playground once the backend is running.

## Development & Testing

- **Project manager:** `uv` (see `pyproject.toml` / `uv.lock` for dependencies).
- **Formatting:** `just fmt` (autoflake → isort → black).
- **Tests:**
  - `uv run python tests/e2e_test.py`
  - `uv run python tests/auto_backup_test.py`
  - `uv run python tests/log_test.py`
  - Additional focused suites live under `tests/` (e.g., `devices_test.py`, `web_mode_test.py`).

Logs are best observed via `--log-path` or `tail -f backend.log` while tests run.

## Troubleshooting

- **Device not detected:** Confirm it enumerates as USB partition #1 (exFAT/FAT32/UDF) and that `pyudev` has permission to watch `/dev`.
- **Mount failures:** Ensure the process runs with sufficient privileges and that the mount point path exists or can be created.
- **Port conflicts:** Use port `0` (auto) for both backend and Textual servers to avoid clashes, particularly when running tests in parallel.
- **Web UI blank:** When tunneling, set `--web-public-url` to the externally visible URL so assets load correctly.

## Documentation & Resources

- `docs/technical.md` — architecture deep dive, sequence diagrams, and operational notes.
- `docs/PRD.md` — product requirements and user flows.
- `docs/api.md` / `docs/api.gql` — GraphQL schema.
- `docs/packaging.md` — PyInstaller packaging checklist.

## License

A license file has not yet been published. Until one is added, treat the code as "all rights reserved" and contact the maintainers before redistributing.

