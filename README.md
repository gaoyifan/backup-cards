# SD Backup

CLI managed backups with automated device monitoring and a Textual UI.

## Running the app

Install dependencies with `uv sync` and launch:

```
uv run python main.py --headless --listen-addr 127.0.0.1 --listen-port 0 --log-path sd-backup.log --db-path ~/.config/sd-backup/config.db
```

- `--listen-addr` / `--listen-port` choose the GraphQL endpoint (port `0` selects a free port).
- `--log-path` writes all logs to a file; omit it to log to stderr.
- `--db-path` points to the SQLite database that stores runtime templates.
- Drop `--headless` to start the Textual frontend after the backend is ready.

## Runtime configuration

`src/backend/config.py` now stores `mount_point_template` and `target_path_template` inside the SQLite DB. They can be edited through the GraphQL mutation exposed in the UI, and updates persist immediately.

