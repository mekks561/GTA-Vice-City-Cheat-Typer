# -*- mode: python ; coding: utf-8 -*-
# P0 构建加固：
# * upx=False —— UPX 压缩常被杀软误报，且会破坏 Authenticode 签名
# * version  —— 由 build.ps1 生成版本资源并通过环境变量传入（缺失时退回无版本资源）
import os

_VERSION_FILE = os.environ.get("VCCT_VERSION_FILE", "")


a = Analysis(
    ['vc_cheat_typer.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
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
    a.binaries,
    a.datas,
    [],
    name='VC-Cheat-Typer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=_VERSION_FILE or None,
)
