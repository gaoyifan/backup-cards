# SD Backup

CLI managed backups with automated device monitoring and a Textual UI.

## Running the app

Install dependencies with `uv sync` and launch:

```
uv run python app.py --headless --listen-addr 127.0.0.1 --listen-port 0 --log-path sd-backup.log --db-path ~/.config/sd-backup/config.db
```

- `--listen-addr` / `--listen-port` choose the GraphQL endpoint (port `0` selects a free port).
- `--log-path` writes all logs to a file; omit it to log to stderr.
- `--db-path` points to the SQLite database that stores runtime templates.
- Drop `--headless` to start the Textual frontend after the backend is ready.
- Pass `--web` to serve the Textual UI through the browser using `textual serve`. This always runs the backend locally; `--frontend-only` can't be combined with `--web`.

### Browser UI mode

Run the UI in a browser tab instead of the terminal:

```
uv run python app.py --web --listen-addr 127.0.0.1 --listen-port 0 --web-host 0.0.0.0 --web-port 8080
```

- The GraphQL backend always runs in the same process when `--web` is used.
- `--web` cannot be combined with `--frontend-only`; use the terminal UI if you need to connect to a remote backend.
- Use `--web-dev` to turn on textual devtools and verbose logging, or `--web-public-url` when exposing the server over a tunnel/proxy so that asset links resolve correctly.

## Runtime configuration

`src/backend/config.py` now stores `mount_point_template` and `target_path_template` inside the SQLite DB. They can be edited through the GraphQL mutation exposed in the UI, and updates persist immediately.

