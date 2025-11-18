#!/usr/bin/env python3

"""Backup Cards GUI implemented with NiceGUI."""

from __future__ import annotations

import asyncio
import json
import os
import queue
import shlex
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional, Tuple

from nicegui import app, ui

try:
    import webview  # type: ignore
except Exception:  # pragma: no cover - optional dependency is guaranteed in prod but keep safety
    webview = None

APP_NAME = "Backup Cards"
SENTINEL_DONE = "__RSYNC_DONE__"
APP_SUPPORT_DIR = os.path.join(
    os.path.expanduser("~/Library/Application Support"), APP_NAME
)
CONFIG_FILE = "config.json"
SAVE_DEBOUNCE_SECONDS = 0.6


def get_config_path() -> str:
    try:
        os.makedirs(APP_SUPPORT_DIR, exist_ok=True)
    except Exception:
        pass
    return os.path.join(APP_SUPPORT_DIR, CONFIG_FILE)


def load_settings() -> dict:
    path = get_config_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            obj = json.load(fh)
            if isinstance(obj, dict):
                return obj
    except FileNotFoundError:
        return {}
    except Exception:
        return {}
    return {}


def save_settings(settings: dict) -> None:
    path = get_config_path()
    try:
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(settings, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        pass


def find_rsync() -> str:
    candidates = [
        "/usr/local/bin/rsync",
        "/opt/homebrew/bin/rsync",
        "/usr/bin/rsync",
        shutil.which("rsync"),
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return ""


def normalize_ext_list(raw: str) -> list[str]:
    if not raw:
        return []
    text = raw
    for sep in [",", ";", " "]:
        text = text.replace(sep, ",")
    tokens = [token.strip() for token in text.split(",")]
    out: list[str] = []
    for token in tokens:
        if not token:
            continue
        if token.startswith("*."):
            token = token[2:]
        if token.startswith("."):
            token = token[1:]
        if token:
            out.append(token)
    return out


def make_case_insensitive_glob_for_extension(ext: str) -> str:
    if not ext:
        return "*.*"
    parts: list[str] = []
    for ch in ext:
        if ch.isalpha():
            parts.append(f"[{ch.lower()}{ch.upper()}]")
        else:
            parts.append(ch)
    return f"*.{''.join(parts)}"


def abspath(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def is_subpath(child: str, parent: str) -> bool:
    try:
        return os.path.commonpath([abspath(child), abspath(parent)]) == abspath(parent)
    except Exception:
        return False


def resolve_initial_dir(current_value: Optional[str]) -> str:
    value = (current_value or "").strip()
    if value and os.path.isdir(value):
        return value
    volumes = "/Volumes"
    if os.path.isdir(volumes):
        return volumes
    return os.path.expanduser("~")


def list_directories(root: Path) -> list[Path]:
    try:
        entries = [p for p in root.iterdir() if p.is_dir()]
    except Exception:
        return []
    entries.sort(key=lambda p: p.name.lower())
    return entries


class DirectoryDialog:
    def __init__(self, label: str, current_value: str, on_select: Callable[[str], None]):
        self.on_select = on_select
        self.current_path = Path(resolve_initial_dir(current_value))
        self.dialog = ui.dialog()
        with self.dialog, ui.card().classes("min-w-[460px] gap-3"):
            ui.label(label).classes("text-lg font-medium")
            self.path_label = ui.label(str(self.current_path)).classes(
                "text-sm text-gray-500 break-all"
            )
            with ui.row().classes("w-full justify-between"):
                ui.button(
                    "Select This Folder",
                    on_click=self.select_current,
                ).props("color=primary")
                ui.button("Go Up", on_click=self.go_up).props("flat color=primary")
            self.entries_column = ui.column().classes(
                "max-h-[320px] overflow-y-auto w-full gap-1"
            )
            self._render_entries()
        self.dialog.open()

    def select_current(self) -> None:
        self.on_select(str(self.current_path))
        self.dialog.close()

    def go_up(self) -> None:
        parent = self.current_path.parent
        if parent == self.current_path:
            return
        self.current_path = parent
        self.path_label.text = str(self.current_path)
        self._render_entries()

    def enter(self, path: Path) -> None:
        self.current_path = path
        self.path_label.text = str(self.current_path)
        self._render_entries()

    def _render_entries(self) -> None:
        self.entries_column.clear()
        entries = list_directories(self.current_path)
        with self.entries_column:
            if not entries:
                ui.label("No subdirectories found").classes("text-sm text-gray-500")
                return
            for entry in entries:
                ui.button(
                    entry.name or str(entry),
                    on_click=lambda e, p=entry: self.enter(p),
                ).classes("w-full justify-start").props("outline color=primary")


class NiceBackupApp:
    def __init__(self):
        settings = load_settings()
        self.source = settings.get("source", "")
        self.target = settings.get("target", "")
        self.exclude_exts = settings.get("exclude_exts", "")
        self.rsync_path = find_rsync()

        self.process: Optional[subprocess.Popen[str]] = None
        self.worker_thread: Optional[threading.Thread] = None
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.save_task: Optional[asyncio.Task[None]] = None
        self.is_running = False

        # UI handles
        self.src_input: Optional[ui.input] = None
        self.dst_input: Optional[ui.input] = None
        self.ext_input: Optional[ui.input] = None
        self.start_button: Optional[ui.element] = None
        self.stop_button: Optional[ui.element] = None
        self.output_box: Optional[ui.textarea] = None
        self.rsync_label: Optional[ui.label] = None

    def build(self) -> None:
        ui.page_title(APP_NAME)
        ui.dark_mode()
        ui.add_head_html(
            "<style>body,#q-app{background-color:#000000!important;}</style>"
        )
        with ui.row().classes(
            "w-full min-h-screen bg-black text-slate-100 items-center justify-center p-5"
        ):
            with ui.card().classes(
                "w-full max-w-4xl bg-slate-900/95 border border-white/10 rounded-[32px] p-8 gap-6 shadow-2xl"
            ):
                with ui.row().classes("items-center gap-4 flex-wrap"):
                    ui.icon("inventory_2", size="44px").classes(
                        "text-primary bg-white/10 rounded-3xl p-3"
                    )
                    with ui.column().classes("gap-1"):
                        ui.label(APP_NAME).classes("text-3xl font-semibold tracking-tight")
                        ui.label(
                            "Select folders, tune filters, and launch rsync backups with live feedback."
                        ).classes("text-sm text-slate-300")
                with ui.row().classes("items-center gap-3 flex-wrap"):
                    ui.badge("macOS native").props("color=primary")
                    ui.badge("NiceGUI + pywebview").props("outline color=white")
                    ui.badge("Live rsync log").props("color=positive")
                    self.rsync_label = ui.label().classes(
                        "text-sm font-mono text-emerald-300"
                    )
                    self._update_rsync_label()

                ui.separator().classes("opacity-30")

                with ui.row().classes("w-full gap-4 flex-col lg:flex-row"):
                    with ui.column().classes("flex-1 gap-2"):
                        ui.label("Source").classes(
                            "text-xs uppercase tracking-[0.2em] text-slate-400"
                        )
                        self.src_input = self._directory_input(
                            "Source directory", self.source, self._on_source_change
                        )
                    with ui.column().classes("flex-1 gap-2"):
                        ui.label("Target").classes(
                            "text-xs uppercase tracking-[0.2em] text-slate-400"
                        )
                        self.dst_input = self._directory_input(
                            "Target directory", self.target, self._on_target_change
                        )

                ui.separator().classes("opacity-30")

                with ui.column().classes("w-full gap-3"):
                    ui.label("Filters & Controls").classes(
                        "text-xs uppercase tracking-[0.2em] text-slate-400"
                    )
                    self.ext_input = (
                        ui.input(
                            label="Exclude file extensions",
                            value=self.exclude_exts,
                            placeholder=".tmp .bak jpg",
                        )
                        .props(
                            'clearable filled dense color=primary dark input-class="text-white placeholder-slate-400"'
                        )
                        .classes("w-full")
                        .style("color:#e2e8f0")
                    )
                    self.ext_input.on("change", self._handle_ext_change)

                    with ui.row().classes("gap-3 flex-wrap"):
                        self.start_button = ui.button(
                            "Start Backup",
                            on_click=self.start_backup,
                        ).props("unelevated color=primary")
                        self.stop_button = ui.button(
                            "Stop",
                            on_click=self.stop_backup,
                        ).props("outline color=negative")
                        self.stop_button.disable()
                        ui.button(
                            "Clear Output",
                            on_click=self.clear_output,
                        ).props("flat color=white")

                ui.separator().classes("opacity-30")

                with ui.column().classes("w-full gap-3"):
                    ui.label("rsync Output").classes(
                        "text-xs uppercase tracking-[0.2em] text-slate-400"
                    )
                    self.output_box = (
                        ui.textarea(
                            value=self._initial_output(),
                        )
                        .props(
                            'readonly autogrow dark borderless input-class="text-white placeholder-slate-400"'
                        )
                        .classes(
                            "w-full font-mono text-sm text-slate-100 placeholder-slate-500 "
                            "bg-slate-950/70 border border-white/10 rounded-2xl"
                        )
                        .style(
                            "color:#e2e8f0; min-height:220px; max-height:60vh; overflow:auto;"
                        )
                    )

        ui.timer(0.2, self.drain_log_queue)

    def _directory_input(
        self, label: str, value: str, on_change: Callable[[str], None]
    ) -> ui.input:
        with ui.row().classes("w-full items-end gap-3 flex-wrap"):
            input_el = (
                ui.input(label=label, value=value)
                .props(
                    'clearable filled dense color=primary dark input-class="text-white placeholder-slate-400"'
                )
                .classes("flex-grow")
                .style("color:#e2e8f0")
            )
            input_el.on("change", lambda e: on_change((e.value or "").strip()))

            def set_value_from_picker(selected: str) -> None:
                input_el.value = selected
                on_change(selected.strip())

            async def browse_handler() -> None:
                pick_supported, selection = await self._native_directory_dialog(
                    input_el.value
                )
                if selection:
                    set_value_from_picker(selection)
                    return
                if not pick_supported:
                    DirectoryDialog(label, input_el.value, set_value_from_picker)

            ui.button("Browse…", on_click=browse_handler).props(
                "outline color=white"
            ).classes("rounded-xl")
        return input_el

    def _initial_output(self) -> str:
        return (
            f"{APP_NAME}\n"
            "— Select a source and target, optionally enter extensions to EXCLUDE,\n"
            "  then click Backup to start rsync.\n\n"
        )

    def _handle_ext_change(self, event) -> None:
        value = (event.value or "").strip()
        self.exclude_exts = value
        self._schedule_save()

    def _on_source_change(self, value: str) -> None:
        self.source = value
        self._schedule_save()

    def _on_target_change(self, value: str) -> None:
        self.target = value
        self._schedule_save()

    def _schedule_save(self) -> None:
        loop = asyncio.get_running_loop()
        if self.save_task and not self.save_task.done():
            self.save_task.cancel()

        async def debounced() -> None:
            try:
                await asyncio.sleep(SAVE_DEBOUNCE_SECONDS)
                save_settings(self._gather_settings())
            except asyncio.CancelledError:
                pass

        self.save_task = loop.create_task(debounced())

    def _gather_settings(self) -> dict:
        return {
            "source": self._current_source(),
            "target": self._current_target(),
            "exclude_exts": self._current_exts(),
        }

    def _current_source(self) -> str:
        if self.src_input is not None:
            return (self.src_input.value or "").strip()
        return self.source.strip()

    def _current_target(self) -> str:
        if self.dst_input is not None:
            return (self.dst_input.value or "").strip()
        return self.target.strip()

    def _current_exts(self) -> str:
        if self.ext_input is not None:
            return (self.ext_input.value or "").strip()
        return self.exclude_exts.strip()

    async def _native_directory_dialog(self, current_value: str) -> Tuple[bool, Optional[str]]:
        main_window = getattr(app.native, "main_window", None)
        if not main_window or webview is None:
            return False, None
        directory = resolve_initial_dir(current_value)
        kwargs = {
            "directory": directory,
            "allow_multiple": False,
        }
        dialog_type_value = None
        if hasattr(webview, "FileDialog"):
            try:
                dialog_type_value = int(webview.FileDialog.FOLDER)
            except Exception:
                dialog_type_value = None
        if dialog_type_value is None:
            legacy = getattr(webview, "FOLDER_DIALOG", None) or getattr(
                webview, "FOLDER_SELECT_DIALOG", None
            )
            if isinstance(legacy, int):
                dialog_type_value = legacy
        if dialog_type_value is not None:
            kwargs["dialog_type"] = dialog_type_value
        try:
            result = await main_window.create_file_dialog(**kwargs)
        except Exception:
            return False, None
        if not result:
            return True, None
        selected = result[0]
        return True, selected

    def _update_rsync_label(self) -> None:
        if not self.rsync_label:
            return
        if self.rsync_path:
            self.rsync_label.text = f"rsync: {self.rsync_path}"
            self.rsync_label.classes(replace="text-sm text-green-600")
        else:
            self.rsync_label.text = "rsync: NOT FOUND"
            self.rsync_label.classes(replace="text-sm text-red-600")

    def start_backup(self) -> None:
        if self.is_running:
            return
        if not self._validate_inputs():
            return

        cmd = self._build_rsync_command()
        cmd_str = " ".join(shlex.quote(part) for part in cmd)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        self._append_output(f"\n[{ts}] Starting rsync:\n$ {cmd_str}\n\n")

        self._set_running(True)
        self.worker_thread = threading.Thread(
            target=self._rsync_worker, args=(cmd,), daemon=True
        )
        self.worker_thread.start()

    def stop_backup(self) -> None:
        if self.process and self.is_running:
            try:
                self.process.terminate()
                self._append_output("\nStopping rsync (terminate sent)…\n")
            except Exception as exc:
                self._append_output(f"\nFailed to stop rsync: {exc}\n")

    def clear_output(self) -> None:
        if self.output_box:
            self.output_box.value = ""

    def _validate_inputs(self) -> bool:
        if not self.rsync_path:
            ui.notify(
                "Could not find 'rsync'. Install via Homebrew or ensure it is on PATH.",
                color="negative",
            )
            return False
        src = self._current_source()
        dst = self._current_target()
        if not src:
            ui.notify("Please select a source directory.", color="warning")
            return False
        if not dst:
            ui.notify("Please select a target directory.", color="warning")
            return False
        if not os.path.isdir(src):
            ui.notify(f"Not a directory: {src}", color="negative")
            return False
        if not os.path.isdir(dst):
            ui.notify(f"Not a directory: {dst}", color="negative")
            return False
        src_abs, dst_abs = abspath(src), abspath(dst)
        if src_abs == dst_abs:
            ui.notify(
                "Source and target cannot be the same directory.",
                color="negative",
            )
            return False
        if is_subpath(dst_abs, src_abs):
            ui.notify(
                "Target directory is inside the source directory.",
                color="negative",
            )
            return False
        return True

    def _build_rsync_command(self) -> list[str]:
        src = abspath(self._current_source())
        dst = abspath(self._current_target())
        src_with_slash = src.rstrip(os.sep) + os.sep
        cmd = [self.rsync_path, "-avP"]
        for ext in normalize_ext_list(self._current_exts()):
            pattern = make_case_insensitive_glob_for_extension(ext)
            cmd.extend(["--exclude", pattern])
        cmd.extend([src_with_slash, dst])
        return cmd

    def _rsync_worker(self, cmd: list[str]) -> None:
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                universal_newlines=True,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError:
            self.log_queue.put("Error: rsync not found. Ensure rsync is installed.\n")
            self.log_queue.put(SENTINEL_DONE)
            return
        except Exception as exc:
            self.log_queue.put(f"Failed to start rsync: {exc}\n")
            self.log_queue.put(SENTINEL_DONE)
            return

        assert self.process.stdout is not None
        try:
            for line in self.process.stdout:
                self.log_queue.put(line)
        except Exception as exc:
            self.log_queue.put(f"\n[reader error] {exc}\n")

        rc = self.process.wait()
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        self.log_queue.put(f"\n[{ts}] rsync finished with exit code {rc}\n")
        self.log_queue.put(SENTINEL_DONE)

    def drain_log_queue(self) -> None:
        drained = False
        while True:
            try:
                msg = self.log_queue.get_nowait()
            except queue.Empty:
                break
            drained = True
            if msg == SENTINEL_DONE:
                self._set_running(False)
                self.process = None
                continue
            self._append_output(msg)

    def _append_output(self, text: str) -> None:
        if not self.output_box:
            return
        current = self.output_box.value or ""
        self.output_box.value = f"{current}{text}"

    def _set_running(self, running: bool) -> None:
        self.is_running = running
        if self.start_button:
            self.start_button.disable() if running else self.start_button.enable()
        if self.stop_button:
            self.stop_button.enable() if running else self.stop_button.disable()

    def shutdown(self) -> None:
        if self.save_task and not self.save_task.done():
            try:
                self.save_task.cancel()
            except Exception:
                pass
        save_settings(self._gather_settings())
        if self.process and self.is_running:
            try:
                self.process.terminate()
            except Exception:
                pass


def main() -> None:
    backup_app = NiceBackupApp()

    def build_ui():
        backup_app.build()

    try:
        ui.run(
            title=APP_NAME,
            root=build_ui,
            native=True,
            window_size=(1024, 720),
            reload=False,
            show=False,
        )
    finally:
        backup_app.shutdown()


if __name__ == "__main__":
    main()
