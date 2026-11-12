# -*- coding: utf-8 -*-
"""2.1：数据目录选择（便携 / 用户目录），零第三方依赖。

设计约束
--------
* **默认 portable**（exe 同目录）——与 1.6～2.0 行为逐项一致，升级零感知。
* 模式不写进 `cheats.json`（否则读配置前要先知道配置在哪，鸡生蛋），而是写
  exe 旁一个极小的 `path-mode.txt`；纯文本、不含用户数据。
* 切换模式**只影响下次启动**，绝不自动搬运/删除配置文件；搬运是用户显式
  触发的一次性复制（`copy_config_to`），且目标已存在时拒绝覆盖。
* 只读目录（Program Files）写不了 marker 时仍在本进程内生效，并给出提示。
"""

from __future__ import annotations

import os
import shutil
import sys

DATA_MODE_FILE = "path-mode.txt"
DATA_MODES = ("portable", "user")
APP_DATA_DIRNAME = "VC-Cheat-Typer"

_mode_cache: str | None = None
_mode_writable = True


def app_dir() -> str:
    """程序所在目录：打包后是 exe 所在目录，源码运行时是项目根目录（vcct/ 的上一级）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def mode_file() -> str:
    return os.path.join(app_dir(), DATA_MODE_FILE)


def read_data_mode() -> str:
    global _mode_cache
    if _mode_cache:
        return _mode_cache
    mode = "portable"
    try:
        with open(mode_file(), "r", encoding="utf-8") as fh:
            raw = fh.read().strip().lower()
        if raw in DATA_MODES:
            mode = raw
    except OSError:
        pass
    _mode_cache = mode
    return mode


def set_data_mode(mode: str) -> bool:
    """设置模式；返回 marker 是否成功落盘（失败则仅本次进程有效）。"""
    global _mode_cache, _mode_writable
    if mode not in DATA_MODES:
        raise ValueError(f"未知数据模式：{mode}（可选 {DATA_MODES}）")
    _mode_cache = mode
    try:
        with open(mode_file(), "w", encoding="utf-8") as fh:
            fh.write(mode + "\n")
        _mode_writable = True
    except OSError:
        _mode_writable = False
    return _mode_writable


def mode_persisted() -> bool:
    return _mode_writable


def user_data_root() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_DATA_DIRNAME)


def _writable(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        return os.access(path, os.W_OK)
    except OSError:
        return False


def data_root(mode: str | None = None) -> str:
    """当前（或指定）模式下的数据根目录。用户目录不可写时回落 portable。"""
    m = mode or read_data_mode()
    if m == "user":
        root = user_data_root()
        if _writable(root):
            return root
    return app_dir()


def data_path(mode: str | None = None) -> str:
    return os.path.join(data_root(mode), "cheats.json")


def other_mode(mode: str | None = None) -> str:
    return "user" if (mode or read_data_mode()) == "portable" else "portable"


def copy_config_to(mode: str) -> tuple[bool, str]:
    """把当前配置**复制**到指定模式的数据目录（不移动、不删除、不覆盖）。"""
    if mode not in DATA_MODES:
        return False, f"未知数据模式：{mode}"
    src = data_path()
    if not os.path.exists(src):
        return False, f"当前配置文件不存在：{src}"
    dest_dir = data_root(mode)
    dest = os.path.join(dest_dir, "cheats.json")
    if os.path.abspath(src) == os.path.abspath(dest):
        return False, "源与目标相同，无需复制。"
    if os.path.exists(dest):
        return False, f"目标已存在配置，拒绝覆盖：{dest}"
    try:
        os.makedirs(dest_dir, exist_ok=True)
        shutil.copy2(src, dest)
    except OSError as exc:
        return False, str(exc)
    return True, dest


def describe() -> dict:
    """给设置页 / 诊断用的纯数据快照。"""
    mode = read_data_mode()
    return {
        "mode": mode,
        "mode_file": mode_file(),
        "mode_persisted": _mode_writable,
        "root": data_root(),
        "config": data_path(),
        "other_root": data_root(other_mode(mode)),
        "other_mode": other_mode(mode),
    }
