# -*- mode: python ; coding: utf-8 -*-
# 2.1-D：控制台 CLI 产物（console=True），与 onefile / onedir 并列为第三个发布资产
# P0：upx=False（避免误报 / 破坏签名）；版本资源由 build.ps1 通过 VCCT_VERSION_FILE 传入
import os

_VERSION_FILE = os.environ.get("VCCT_VERSION_FILE", "")

a = Analysis(
    ['cli_entry.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', '_tkinter'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='VC-Cheat-Typer-cli',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=_VERSION_FILE or None,
)
