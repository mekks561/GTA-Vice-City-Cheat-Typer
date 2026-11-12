# -*- coding: utf-8 -*-
"""1.7 日志与崩溃钩子；2.0 起实现层零 tkinter；2.1 起数据目录由 paths.py 统一决定。"""

from __future__ import annotations

import os
import sys
import threading
import time
import traceback

from .const import APP_NAME
from .paths import app_dir, data_path, data_root, read_data_mode  # noqa: F401


def backup_path(path: str | None = None) -> str:
    """上一版配置的备份路径（与配置文件同目录）。"""
    return os.path.join(os.path.dirname(path or data_path()), "cheats.bak.json")


# ----------------------------------------------------------------------------
# 日志（1.6）
# windowed 模式没有控制台，崩溃/异常若不落盘就等于不可诊断
# ----------------------------------------------------------------------------
LOG_MAX_BYTES = 1024 * 1024
LOG_KEEP = 3
_log_dir_cache: str | None = None
_crash_dialog_open = False


def _writable(path: str) -> bool:
    """只建目录 + 检查权限，不创建/删除探针文件（避免受管环境的回收站钩子误伤）。"""
    try:
        os.makedirs(path, exist_ok=True)
        return os.access(path, os.W_OK)
    except OSError:
        return False


def log_dir() -> str:
    """跟随数据模式：portable 用 exe 旁 logs/，user 用用户目录 logs/；不可写则退到 %LOCALAPPDATA%。"""
    global _log_dir_cache
    if _log_dir_cache:
        return _log_dir_cache
    preferred = os.path.join(data_root(), "logs")
    if _writable(preferred):
        _log_dir_cache = preferred
        return preferred
    fallback = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), APP_NAME, "logs")
    _writable(fallback)
    _log_dir_cache = fallback
    return fallback


def log_file() -> str:
    return os.path.join(log_dir(), "app.log")


def _rotate_log(path: str) -> None:
    try:
        if os.path.getsize(path) < LOG_MAX_BYTES:
            return
    except OSError:
        return
    for i in range(LOG_KEEP - 1, 0, -1):
        src = f"{path}.{i}"
        if os.path.exists(src):
            try:
                os.replace(src, f"{path}.{i + 1}")
            except OSError:
                pass
    try:
        os.replace(path, f"{path}.1")
    except OSError:
        pass


def append_log(text: str, level: str = "INFO") -> None:
    """写文件日志；失败一律吞掉——日志不能反过来把程序搞崩。"""
    try:
        path = log_file()
        _rotate_log(path)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{stamp} [{level}] {text}\n")
    except Exception:
        pass


def _fallback_crash_notice(title: str, detail: str) -> None:
    """core 默认行为：只落 stderr，不依赖 tkinter / 桌面。"""
    try:
        print(f"{title}: {detail}", file=sys.stderr)
    except Exception:
        pass


def install_crash_hooks(show_dialog=None) -> None:
    """未捕获异常（主线程 + 子线程）落盘，并告知用户日志位置。

    2.0：弹窗 UI 由调用方注入（`show_dialog(title, detail)`）。
    实现层因此**零 tkinter 依赖**，core 可在无桌面环境导入；不注入时只写 stderr。
    """
    notify = show_dialog or _fallback_crash_notice

    def handle(exc_type, exc, tb, thread_name="main"):
        global _crash_dialog_open
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        append_log(f"未捕获异常（{thread_name}）\n{text}", "ERROR")
        if _crash_dialog_open:  # 防止异常里再弹异常，无限递归
            return
        _crash_dialog_open = True
        try:
            notify(f"{APP_NAME} 遇到问题", f"程序捕获到未处理的异常，已写入日志：\n{log_file()}\n\n{exc_type.__name__}: {exc}")
        except Exception:
            pass
        finally:
            _crash_dialog_open = False

    def main_hook(exc_type, exc, tb):
        handle(exc_type, exc, tb, "main")

    def thread_hook(args):
        handle(args.exc_type, args.exc_value, args.exc_traceback, getattr(args.thread, "name", "thread"))

    sys.excepthook = main_hook
    if hasattr(threading, "excepthook"):
        threading.excepthook = thread_hook
