# -*- mode: python ; coding: utf-8 -*-
# 2.0-F：onedir 产物（启动更快，供"不介意文件夹"的用户；onefile 仍为默认便携形态）
# P0：upx 默认关闭（避免误报 / 签名启发式），build.ps1 -EnableUPX 置 VCCT_UPX=1 才启用
# 版本资源由 build.ps1 通过 VCCT_VERSION_FILE 传入
import os

_VERSION_FILE = os.environ.get("VCCT_VERSION_FILE", "")
_UPX = os.environ.get("VCCT_UPX") == "1"

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
    [],
    exclude_binaries=True,
    name='VC-Cheat-Typer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=_UPX,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=_VERSION_FILE or None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=_UPX,
    upx_exclude=[],
    name='VC-Cheat-Typer-onedir',
)
