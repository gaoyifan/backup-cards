# macOS .app Packaging

This bundles the SD Backup web UI inside a PyInstaller `.app` using PyWebview.

## Prerequisites
- macOS with Xcode command line tools installed
- Project dependencies installed via `uv sync` (includes `pyinstaller` and `pywebview`)

## Build the bundle
Run from the repository root:

```bash
uv run python -m PyInstaller -y "SD Backup.spec"
```

The bundle appears at `dist/SD Backup.app`.

## What the app does
- Starts the FastAPI backend and Textual web server in a background process
- Serves the UI on a random free localhost port
- Opens a PyWebview window pointed at that local URL

## Notes for macOS users
- The app stores its runtime SQLite DB at `~/.local/share/sd-backup/sd-backup.db`.
- If launched from Finder, give the app 10–15 seconds on first run while macOS gatekeeper finishes verification.
- For troubleshooting, you can run the binary directly: `dist/SD\ Backup.app/Contents/MacOS/SD\ Backup` to see console output.
