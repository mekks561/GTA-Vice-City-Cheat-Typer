# -*- coding: utf-8 -*-
"""1.7：日志与崩溃钩子。模块级不导入 tkinter（崩溃弹窗内部延迟导入）。"""
from __future__ import annotations

import os
import sys
import threading
import time
import traceback

from .const import APP_NAME

def app_dir() -> str:
    """程序所在目录：打包后是 exe 所在目录，源码运行时是项目根目录（vcct/ 的上一级）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_path() -> str:
    return os.path.join(app_dir(), "cheats.json")


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
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write-test")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        return True
    except Exception:
        return False


def log_dir() -> str:
    """优先 exe 同目录 logs/；不可写（如装在 Program Files）则退到 %LOCALAPPDATA%。"""
    global _log_dir_cache
    if _log_dir_cache:
        return _log_dir_cache
    preferred = os.path.join(app_dir(), "logs")
    if _writable(preferred):
        _log_dir_cache = preferred
        return preferred
    fallback = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
                            APP_NAME, "logs")
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


def _show_crash_dialog(title: str, detail: str) -> None:
    global _crash_dialog_open
    if _crash_dialog_open:  # 防止异常里再弹异常，无限递归
        return
    _crash_dialog_open = True
    # 延迟导入：本模块要能在无 tkinter / 无桌面环境（含 CI）下被导入
    import tkinter as tk
    from tkinter import messagebox
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, detail)
        root.destroy()
    except Exception:
        pass
    finally:
        _crash_dialog_open = False


def install_crash_hooks() -> None:
    """未捕获异常（主线程 + 子线程）落盘，并告知用户日志位置。"""
    def handle(exc_type, exc, tb, thread_name="main"):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        append_log(f"未捕获异常（{thread_name}）\n{text}", "ERROR")
        _show_crash_dialog(
            f"{APP_NAME} 遇到问题",
            f"程序捕获到未处理的异常，已写入日志：\n{log_file()}\n\n{exc_type.__name__}: {exc}")

    def main_hook(exc_type, exc, tb):
        handle(exc_type, exc, tb, "main")

    def thread_hook(args):
        handle(args.exc_type, args.exc_value, args.exc_traceback,
               getattr(args.thread, "name", "thread"))

    sys.excepthook = main_hook
    if hasattr(threading, "excepthook"):
        threading.excepthook = thread_hook
