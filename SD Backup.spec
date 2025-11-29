# -*- mode: python ; coding: utf-8 -*-
import importlib.util
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

_ROOT = Path.cwd()
_SRC = _ROOT / "src"
for _p in (_ROOT, _SRC):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


datas = [
    (str(_SRC / "backend"), "backend"),
    (str(_SRC / "frontend"), "frontend"),
    ("main.py", "."),
]

_aiosqlite_spec = importlib.util.find_spec("aiosqlite")
if _aiosqlite_spec and _aiosqlite_spec.origin:
    datas.append((str(Path(_aiosqlite_spec.origin).parent), "aiosqlite"))

_textual_serve_spec = importlib.util.find_spec("textual_serve")
if _textual_serve_spec and _textual_serve_spec.origin:
    _ts_root = Path(_textual_serve_spec.origin).parent
    datas.append((str(_ts_root / "static"), "textual_serve/static"))
    datas.append((str(_ts_root / "templates"), "textual_serve/templates"))

hidden = collect_submodules('backend') + collect_submodules('frontend') + ['main', 'aiosqlite', 'textual.drivers.web_driver']

a = Analysis(
    ['packaging/mac_app.py'],
    pathex=['src', '.'],
    binaries=[],
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SD Backup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SD Backup',
)
app = BUNDLE(
    coll,
    name='SD Backup.app',
    icon=None,
    bundle_identifier='com.sd-backup.app',
)
