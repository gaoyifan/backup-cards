# Repository Guidelines

## Project Structure & Module Organization
- Single entry: `app.py` configures logging, allocates port (0 for dynamic), starts FastAPI/GraphQL backend and Textual UI. Run only via `uv run python app.py`.
- Backend in `src/backend/` (`server.py`, `schema.py`, `backup.py`, `monitor.py`, `config.py`, `db.py`); frontend in `src/frontend/` (`app.py`, `screens.py`, `client.py`). Config store: `src/backend/config.py` (SQLite via `--db-path`). Docs in `docs/`, tests in `tests/`.

## Build, Test, and Development Commands
- Install deps: `uv sync`.
- Run: `uv run python app.py` (UI) or `--headless` (backend only); specify `--port 0` for free port. Frontend never reads config directly—host/port passed from `app.py`.
- Tests: `uv run python tests/e2e_test.py`, `uv run python tests/auto_backup_test.py`, `uv run python tests/log_test.py`. Tail log file if `log_path` set (e.g., `tail -f backend.log`).

## Coding Style & Naming Conventions
- Python 3.12+, imports ordered stdlib → third-party → local; prefer relative imports within packages.
- Logging: always `logging.getLogger(__name__)`; configure logging only in `app.py`; avoid prints when logging to file; no `basicConfig` elsewhere.
- Avoid hardcoded ports; keep schema thin in `schema.py`, delegate logic to modules; don’t run backend/frontend modules directly.

## Testing Guidelines
- Add/adjust tests with behavior changes; clean temp files/dirs in `finally`. Mock `pyudev.Device` for unit tests; ensure subprocesses terminate in e2e.
- Validate config persistence and logging destinations when changing those areas.

## Commit & Pull Request Guidelines
- Commit messages: short, imperative, scoped (e.g., `Add auto-backup retry`).
- PRs: explain behavior changes, linked issues, tests run, and logging/config impacts; include UI screenshots only when applicable.

## Security & Configuration Tips
- Root required for pyudev monitoring, mounts, and `/proc/mounts` reads.
- Expand `~` before rsync, handle subprocess errors, and store process handles for cancellation. Keep monitor loop non-blocking and use daemon threads.
