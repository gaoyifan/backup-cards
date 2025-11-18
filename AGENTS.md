# Repository Guidelines

## Project Structure & Module Organization
- `main.py` hosts the NiceGUI + pywebview app and owns backup logic, rsync invocations, and persistent settings. Extend UI flows here by composing new NiceGUI components next to the existing `ui.card` definitions.
- `justfile` centralizes developer automation (setup, run, build, clean). Treat it as the canonical reference for task wiring.
- Distribution artifacts land under `build/` (PyInstaller cache) and `dist/` (shipping `.app`). Keep these directories out of PRs unless you change packaging scripts.
- Reference assets such as `screenshot.png` live at repo root; new static files should stay alongside `README.md` unless bundled into the PyInstaller spec (`Backup Cards.spec`).

## Build, Test, and Development Commands
- `uv sync` installs runtime and dev dependencies declared in `pyproject.toml`.
- `uv run main.py` launches the GUI directly for iterative development.
- `just setup | run | build | open-app | clean` mirror the raw `uv`/PyInstaller commands; prefer `just run` for day-to-day work and `just build` before shipping a macOS `.app`.
- `just rebuild` performs a clean build, ensuring stale artifacts do not leak into releases.

## Coding Style & Naming Conventions
- Target Python 3.12, 4-space indentation, and PEP 8 defaults. Keep UI callbacks small and pure; push rsync helpers into top-level functions within `main.py`.
- Use descriptive snake_case for variables/functions and PascalCase for classes or dataclasses.
- Include docstrings for any helpers touching filesystem safety (rsync flags, exclusion parsing). Inline comments should explain non-obvious GUI or subprocess behavior only.

## Testing Guidelines
- Automated tests are not yet wired; validate changes by running `uv run main.py` (or `just run`) and exercising backups with sample folders.
- When touching rsync options, perform a dry run first by cloning the existing subprocess call and passing `--dry-run`, then capture observations in the PR description.
- Name future tests `test_<feature>.py` under a new `tests/` directory so `uv run pytest` can be adopted without reconfiguration.

## Commit & Pull Request Guidelines
- Follow the Conventional Commits style already in history (`feat:`, `chore(just):`, `docs(README):`, etc.). Scope optional, lowercase imperative subject, body only when necessary.
- Each PR should summarize user-facing changes, list manual test steps (commands/output), and link related issues. Include screenshots if UI shifts are visible.
- Keep PRs focused: UI tweaks, build tooling, and documentation updates are easier to review when isolated.

## Security & Configuration Tips
- Confirm the desired `rsync` binary through the settings pane or by updating the PATH before launch; Homebrew builds live at `/opt/homebrew/bin/rsync`.
- User preferences persist in `~/Library/Application Support/Backup Cards/config.json`. Avoid committing sample configs; redact paths in bug reports.
