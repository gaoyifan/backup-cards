#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Backup Cards GUI (macOS-friendly)
- Select source directory
- Select target directory
- Exclusive extension filtering (exclude by file extension)
- Live rsync output during backup
- Backup button

- Remembers last used settings between launches

Requires: Python 3 (tkinter included on macOS), rsync available on PATH.
Tip: macOS ships an older rsync. For speed/new features you can install a newer one via Homebrew.
"""

import os
import shlex
import shutil
import threading
import subprocess
import queue
import time
import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

SENTINEL_DONE = "__RSYNC_DONE__"
APP_NAME = "Backup Cards"


APP_SUPPORT_DIR = os.path.join(
    os.path.expanduser("~/Library/Application Support"), APP_NAME
)
CONFIG_FILE = "config.json"


def get_config_path() -> str:
    try:
        os.makedirs(APP_SUPPORT_DIR, exist_ok=True)
    except Exception:
        # Best-effort directory creation; fall back to user home if it fails
        pass
    return os.path.join(APP_SUPPORT_DIR, CONFIG_FILE)


def load_settings() -> dict:
    path = get_config_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except FileNotFoundError:
        return {}
    except Exception:
        return {}
    return {}


def save_settings(settings: dict) -> None:
    path = get_config_path()
    try:
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        # Best-effort save; ignore failures
        pass


def find_rsync() -> str:
    # Prefer homebrew rsync; fall back to PATH.
    candidates = [
        "/usr/local/bin/rsync",    # Homebrew (Intel)
        "/opt/homebrew/bin/rsync", # Homebrew (Apple Silicon)
        "/usr/bin/rsync",          # macOS built-in (older)
        shutil.which("rsync"),     # PATH
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return ""


def normalize_ext_list(raw: str):
    """
    Convert user text like '.tmp, .bak;log  JPG' -> ['tmp','bak','log','JPG']
    Empty/invalid tokens are ignored.
    """
    if not raw:
        return []
    seps = [',', ';', ' ']
    text = raw
    for s in seps:
        text = text.replace(s, ',')
    tokens = [t.strip() for t in text.split(',')]
    out = []
    for t in tokens:
        if not t:
            continue
        if t.startswith("*."):
            t = t[2:]
        if t.startswith("."):
            t = t[1:]
        # keep case as typed; rsync pattern matching is case-sensitive
        if t:
            out.append(t)
    return out


def make_case_insensitive_glob_for_extension(ext: str) -> str:
    """
    Build a case-insensitive glob for an extension token.
    Example: "jpg" -> "*.[jJ][pP][gG]"
    """
    if not ext:
        return "*.*"
    parts = []
    for ch in ext:
        if ch.isalpha():
            parts.append(f"[{ch.lower()}{ch.upper()}]")
        else:
            parts.append(ch)
    return f"*.{''.join(parts)}"


def abspath(p: str) -> str:
    return os.path.abspath(os.path.expanduser(p))


def is_subpath(child: str, parent: str) -> bool:
    try:
        return os.path.commonpath([abspath(child), abspath(parent)]) == abspath(parent)
    except Exception:
        return False


class BackupApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        # Nice default size; Menlo is standard on macOS
        self.geometry("820x560")
        self.minsize(740, 480)

        # State
        self.log_q = queue.Queue()
        self.worker_thread = None
        self.rsync_path = find_rsync()
        self.process = None
        self.is_running = False
        self._save_job = None
        self.settings = load_settings()

        self._build_ui()
        self._apply_settings(self.settings)
        self._bind_autosave()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        pad = {"padx": 10, "pady": 8}

        main = ttk.Frame(self)
        main.pack(fill="both", expand=True)

        # Source selector
        row = ttk.Frame(main)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="Source directory").pack(side="left")
        self.src_var = tk.StringVar()
        src_entry = ttk.Entry(row, textvariable=self.src_var)
        src_entry.pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(row, text="Browse…", command=self._pick_src).pack(side="left")

        # Target selector
        row = ttk.Frame(main)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="Target directory").pack(side="left")
        self.dst_var = tk.StringVar()
        dst_entry = ttk.Entry(row, textvariable=self.dst_var)
        dst_entry.pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(row, text="Browse…", command=self._pick_dst).pack(side="left")

        # Exclusion extensions
        row = ttk.Frame(main)
        row.pack(fill="x", **pad)
        ttk.Label(
            row,
            text="Exclude file extensions (comma/space separated, e.g. .tmp .bak jpg):",
        ).pack(side="left")
        self.ext_var = tk.StringVar()
        ext_entry = ttk.Entry(row, textvariable=self.ext_var)
        ext_entry.pack(side="left", fill="x", expand=True, padx=8)

        # Buttons row
        row = ttk.Frame(main)
        row.pack(fill="x", **pad)
        self.start_btn = ttk.Button(row, text="Backup", command=self._start_backup)
        self.start_btn.pack(side="left")

        self.stop_btn = ttk.Button(
            row, text="Stop", command=self._stop_backup, state="disabled"
        )
        self.stop_btn.pack(side="left", padx=(10, 0))

        ttk.Button(row, text="Clear Output", command=self._clear_output).pack(
            side="right"
        )

        # Output
        out_frame = ttk.LabelFrame(main, text="rsync output")
        out_frame.pack(fill="both", expand=True, **pad)
        self.output = ScrolledText(
            out_frame, wrap="none", height=20, font=("Menlo", 11)
        )
        self.output.pack(fill="both", expand=True)
        self.output.insert(
            "end",
            f"{APP_NAME}\n"
            "— Select a source and target, optionally enter extensions to EXCLUDE,\n"
            "  then click Backup to start rsync.\n\n",
        )
        self.output.configure(state="disabled")

        # Footer info
        bar = ttk.Frame(main)
        bar.pack(fill="x", pady=(0, 6), padx=10)
        self.rsync_label = ttk.Label(
            bar,
            text=f"rsync: {self.rsync_path or 'NOT FOUND'}",
            foreground="green" if self.rsync_path else "red",
        )
        self.rsync_label.pack(side="left")

    def _apply_settings(self, settings: dict):
        if not isinstance(settings, dict):
            return
        src = settings.get("source")
        dst = settings.get("target")
        exts = settings.get("exclude_exts")
        geom = settings.get("geometry")
        if isinstance(src, str):
            self.src_var.set(src)
        if isinstance(dst, str):
            self.dst_var.set(dst)
        if isinstance(exts, str):
            self.ext_var.set(exts)
        if isinstance(geom, str):
            try:
                self.geometry(geom)
            except Exception:
                pass

    def _bind_autosave(self):
        # Save when fields change, debounced to avoid excessive writes
        def cb(*_):
            self._on_field_change()

        self.src_var.trace_add("write", lambda *_: cb())
        self.dst_var.trace_add("write", lambda *_: cb())
        self.ext_var.trace_add("write", lambda *_: cb())

    def _gather_settings(self) -> dict:
        return {
            "source": self.src_var.get().strip(),
            "target": self.dst_var.get().strip(),
            "exclude_exts": self.ext_var.get().strip(),
            "geometry": self.geometry(),
        }

    def _on_field_change(self):
        if self._save_job is not None:
            try:
                self.after_cancel(self._save_job)
            except Exception:
                pass
            self._save_job = None
        self._save_job = self.after(600, self._save_settings_now)

    def _save_settings_now(self):
        self._save_job = None
        try:
            save_settings(self._gather_settings())
        except Exception:
            pass

    def _on_close(self):
        try:
            save_settings(self._gather_settings())
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            os._exit(0)

    def _resolve_initial_dir(self, current_value: str) -> str:
        try:
            path = (current_value or "").strip()
        except Exception:
            path = ""
        if path and os.path.isdir(path):
            return path
        volumes = "/Volumes"
        if os.path.isdir(volumes):
            return volumes
        return os.path.expanduser("~")

    def _pick_src(self):
        init_dir = self._resolve_initial_dir(self.src_var.get())
        p = filedialog.askdirectory(title="Choose Source Directory", initialdir=init_dir)
        if p:
            self.src_var.set(p)

    def _pick_dst(self):
        init_dir = self._resolve_initial_dir(self.dst_var.get())
        p = filedialog.askdirectory(title="Choose Target Directory", initialdir=init_dir)
        if p:
            self.dst_var.set(p)

    def _append_output(self, text: str):
        self.output.configure(state="normal")
        self.output.insert("end", text)
        self.output.see("end")
        self.output.configure(state="disabled")

    def _clear_output(self):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.configure(state="disabled")

    def _validate_inputs(self):
        if not self.rsync_path:
            messagebox.showerror(
                "rsync not found",
                "Could not find 'rsync'. Install via Homebrew (recommended) or ensure it's on your PATH.",
            )
            return False

        src = self.src_var.get().strip()
        dst = self.dst_var.get().strip()

        if not src:
            messagebox.showwarning("Missing source", "Please select a source directory.")
            return False
        if not dst:
            messagebox.showwarning("Missing target", "Please select a target directory.")
            return False

        if not os.path.isdir(src):
            messagebox.showerror("Invalid source", f"Not a directory: {src}")
            return False
        if not os.path.isdir(dst):
            messagebox.showerror("Invalid target", f"Not a directory: {dst}")
            return False

        # Protect against recursive copies (dst within src) or copying into itself
        src_abs, dst_abs = abspath(src), abspath(dst)
        if src_abs == dst_abs:
            messagebox.showerror(
                "Same directories",
                "Source and target are the same directory. Choose different folders.",
            )
            return False
        if is_subpath(dst_abs, src_abs):
            messagebox.showerror(
                "Invalid target",
                "Target directory is inside the source directory. Choose a different target.",
            )
            return False
        return True

    def _build_rsync_command(self):
        src = abspath(self.src_var.get().strip())
        dst = abspath(self.dst_var.get().strip())

        # Copy CONTENTS of source dir (trailing slash). Remove it if you want to copy the folder itself.
        src_with_slash = src.rstrip(os.sep) + os.sep

        cmd = [self.rsync_path, "-avP"]

        # Exclude extensions
        exts = normalize_ext_list(self.ext_var.get())
        for ext in exts:
            pattern = make_case_insensitive_glob_for_extension(ext)
            cmd += ["--exclude", pattern]

        cmd += [src_with_slash, dst]
        return cmd

    def _set_running(self, running: bool):
        self.is_running = running
        state = "disabled" if running else "normal"
        self.start_btn.configure(state="disabled" if running else "normal")
        self.stop_btn.configure(state="normal" if running else "disabled")

    def _start_backup(self):
        if self.is_running:
            return
        if not self._validate_inputs():
            return

        cmd = self._build_rsync_command()

        # Show the exact command being run
        cmd_str = " ".join(shlex.quote(p) for p in cmd)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        self._append_output(f"\n[{ts}] Starting rsync:\n$ {cmd_str}\n\n")

        self._set_running(True)
        self.worker_thread = threading.Thread(
            target=self._rsync_worker, args=(cmd,), daemon=True
        )
        self.worker_thread.start()
        self.after(80, self._drain_log_queue)

    def _stop_backup(self):
        if self.process and self.is_running:
            try:
                self.process.terminate()
                self._append_output("\nStopping rsync (terminate sent)…\n")
            except Exception as e:
                self._append_output(f"\nFailed to stop rsync: {e}\n")

    def _rsync_worker(self, cmd):
        try:
            # Merge stderr into stdout so lines display in order
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
            self.log_q.put("Error: rsync not found. Ensure rsync is installed and on PATH.\n")
            self.log_q.put(SENTINEL_DONE)
            return
        except Exception as e:
            self.log_q.put(f"Failed to start rsync: {e}\n")
            self.log_q.put(SENTINEL_DONE)
            return

        # Stream output lines
        try:
            assert self.process.stdout is not None
            for line in self.process.stdout:
                self.log_q.put(line)
        except Exception as e:
            self.log_q.put(f"\n[reader error] {e}\n")

        rc = self.process.wait()
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        self.log_q.put(f"\n[{ts}] rsync finished with exit code {rc}\n")
        self.log_q.put(SENTINEL_DONE)

    def _drain_log_queue(self):
        drained_any = False
        while True:
            try:
                msg = self.log_q.get_nowait()
            except queue.Empty:
                break
            drained_any = True
            if msg == SENTINEL_DONE:
                self._set_running(False)
                self.process = None
                continue
            self._append_output(msg)

        if self.is_running or drained_any:
            # Keep polling while running or while there may still be messages coming
            self.after(80, self._drain_log_queue)


def main():
    app = BackupApp()
    # macOS menubar nicer app name
    try:
        from ctypes import cdll
        appId = "com.example.backupcards"
        cdll.LoadLibrary("/System/Library/Frameworks/AppKit.framework/AppKit")
        # Note: setting the bundle id at runtime is non-trivial; keeping here as a placeholder
    except Exception:
        pass
    app.mainloop()


if __name__ == "__main__":
    main()
