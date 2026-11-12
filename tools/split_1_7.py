# -*- coding: utf-8 -*-
"""1.7 一次性迁移工具：把 vc_cheat_typer.py 的顶层块按符号切分到 vcct/ 各模块。

用法：python tools/split_1_7.py
原则：
  * 按 ast 顶层节点切块，块文本原样搬运（不做任何重排/改写）；
  * 无名节点（for 循环、_reg(...) 调用、if IS_WIN: 原型块）跟随**前一个**有名节点的目标模块；
  * 例外：`if IS_WIN:` 的 DLL 加载/原型块强制归入 winapi（其前一个节点是 const 的 IS_WIN）；
  * 主文件保留 UI 与入口，并插入显式 import 作为兼容层。
"""

from __future__ import annotations

import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "vc_cheat_typer.py")

TARGET = {}
for _n in (
    "APP_NAME",
    "APP_VER",
    "IS_WIN",
    "STORE_VERSION",
    "STORE_APP",
    "DEFAULT_SETTINGS",
    "PRESETS",
    "PAUSE_ID",
    "PAUSE_HID",
    "C",
    "WIN_W",
):
    TARGET[_n] = "const"

for _n in (
    "ULONG_PTR",
    "KEYBDINPUT",
    "MOUSEINPUT",
    "HARDWAREINPUT",
    "_INPUTUNION",
    "INPUT",
    "INPUT_KEYBOARD",
    "KEYEVENTF_KEYUP",
    "KEYEVENTF_SCANCODE",
    "WM_HOTKEY",
    "WM_QUIT",
    "WM_APP",
    "WM_APP_RELOAD",
    "MOD_ALT",
    "ERROR_HOTKEY_ALREADY_REGISTERED",
    "ERROR_ACCESS_DENIED",
    "WS_EX_TOPMOST",
    "WS_EX_TOOLWINDOW",
    "WS_EX_NOACTIVATE",
    "GWL_EXSTYLE",
    "GA_ROOT",
    "get_window_exstyle",
    "add_window_exstyle",
    "_key_item",
    "_send",
    "press_key",
    "foreground_info",
    "is_key_down",
    "KNOWN_GAME_EXES",
    "find_game_window",
    "ImeGuard",
    "force_foreground",
    "_RAW_PROBE_CLASS",
    "raw_char_probe",
    "enable_dpi_awareness",
    "ui_scale",
    # VK 表属于 Win32 虚拟键码域；且 raw_char_probe 需要它，
    # 放 hotkeys 会让 hotkeys <-> winapi 循环导入
    "VK_BY_NAME",
    "NAME_BY_VK",
    "_reg",
    "MODIFIER_VKS",
    "BARE_SAFE_VKS",
):
    TARGET[_n] = "winapi"

for _n in (
    "format_combo",
    "parse_combo",
    "combo_signature",
    "is_safe_binding",
    "HotkeyEngine",
    "build_bindings",
    "candidate_combos",
    "pick_free_combo",
):
    TARGET[_n] = "hotkeys"

for _n in (
    "_c",
    "default_cheats",
    "LAST_LOAD_WARNING",
    "_safe_int",
    "_norm_cheat",
    "_norm_stats",
    "_norm_today",
    "touch_today",
    "normalize_store",
    "default_store",
    "quarantine_corrupt",
    "load_store",
    "save_store",
    "bundle_payload",
    "parse_bundle",
    "bump_stats",
    "filter_cheats",
    "sorted_cheats",
):
    TARGET[_n] = "store"

for _n in (
    "LOG_MAX_BYTES",
    "LOG_KEEP",
    "_log_dir_cache",
    "_crash_dialog_open",
    "app_dir",
    "data_path",
    "backup_path",
    "_writable",
    "log_dir",
    "log_file",
    "_rotate_log",
    "append_log",
    "_show_crash_dialog",
    "install_crash_hooks",
):
    TARGET[_n] = "loggingx"

HEADERS = {
    "const": '''# -*- coding: utf-8 -*-
"""1.7：全局常量。本模块**零内部依赖**，任何模块都可以安全导入。"""
from __future__ import annotations

import os

''',
    "winapi": '''# -*- coding: utf-8 -*-
"""1.7：Win32 原语（ctypes 结构体、SendInput、前台判定、IME 守卫、DPI）。

这是唯一允许直接调用 Win32 API 的模块；其余模块通过它间接使用。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import sys
import time

from .const import IS_WIN

''',
    "hotkeys": '''# -*- coding: utf-8 -*-
"""1.7：按键域——组合键解析、合法性校验、注册引擎、候选键分配。

键名/键码表属 Win32 域，放在 winapi 里（raw_char_probe 也要用）。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import queue
import re
import threading
import time

from .const import PAUSE_HID, PAUSE_ID
from .winapi import (
    BARE_SAFE_VKS, ERROR_ACCESS_DENIED, ERROR_HOTKEY_ALREADY_REGISTERED, MODIFIER_VKS,
    MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, MOD_SHIFT, MOD_WIN, NAME_BY_VK, VK_BY_NAME,
    WM_APP_RELOAD, WM_HOTKEY, WM_QUIT, kernel32, user32,
)

''',
    "store": '''# -*- coding: utf-8 -*-
"""1.7：配置数据层——归一化、加载/保存、备份、整包导入导出、统计、过滤。

不依赖 tkinter，可在无桌面环境下测试。
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
import uuid

from .const import APP_NAME, DEFAULT_SETTINGS, STORE_APP, STORE_VERSION
from .loggingx import append_log, backup_path, data_path

''',
    "loggingx": '''# -*- coding: utf-8 -*-
"""1.7：日志与崩溃钩子。模块级不导入 tkinter（崩溃弹窗内部延迟导入）。"""
from __future__ import annotations

import os
import sys
import threading
import time
import traceback

from .const import APP_NAME

''',
}


def node_names(node):
    """返回节点绑定的所有顶层名字（支持 a, b = ... 与注解赋值）。"""
    out = []

    def walk(t):
        if isinstance(t, ast.Name):
            out.append(t.id)
        elif isinstance(t, (ast.Tuple, ast.List)):
            for e in t.elts:
                walk(e)

    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    if isinstance(node, ast.Assign):
        for t in node.targets:
            walk(t)
    elif isinstance(node, ast.AnnAssign):
        walk(node.target)
    return out


def main() -> int:
    # 防误触发：本脚本会按 git 中的原始单文件重建 vcct/，覆盖后续所有手改。
    # 迁移完成后重跑必须显式 --force，且应先把 SRC 还原到迁移前的提交。
    pkg_dir = os.path.join(ROOT, "vcct")
    if os.path.isdir(pkg_dir) and "--force" not in sys.argv:
        print(
            "vcct/ 已存在：本脚本是一次性迁移工具，重跑会覆盖手写改动。\n"
            "如确需重跑：git checkout <迁移前提交> -- vc_cheat_typer.py && python tools/split_1_7.py --force",
            file=sys.stderr,
        )
        return 2

    with open(SRC, encoding="utf-8") as fh:
        text = fh.read()
    lines = text.splitlines(keepends=True)
    nodes = sorted((n for n in ast.parse(text).body if hasattr(n, "lineno")), key=lambda n: n.lineno)

    owners = []
    prev_owner = None
    for nd in nodes:
        names = node_names(nd)
        seg = ast.get_source_segment(text, nd) or ""
        if isinstance(nd, ast.If) and "IS_WIN" in seg.split("\n")[0]:
            owners.append("winapi")  # DLL 加载 / ctypes 原型块
            prev_owner = "winapi"
            continue
        if names:
            owner = None
            for nm in names:
                if nm in TARGET:
                    owner = TARGET[nm]
                    break
            prev_owner = owner
            owners.append(owner)
        else:
            owners.append(prev_owner)

    blocks = []
    for i, nd in enumerate(nodes):
        start = 1 if i == 0 else nodes[i - 1].end_lineno + 1
        blocks.append((start, nd.end_lineno, owners[i]))

    buckets = {"const": [], "winapi": [], "hotkeys": [], "store": [], "loggingx": [], None: []}
    for start, end, owner in blocks:
        buckets[owner].append("".join(lines[start - 1 : end]))

    # --- 搬运后必须的语义保持适配（每条都断言命中，防止源码漂移后静默失效）---
    ADAPT = {
        "loggingx": [
            # 1) app_dir：移入 vcct/ 后 __file__ 深了一层，源码运行时必须回到项目根
            (
                "def app_dir() -> str:\n"
                '    """程序所在目录：打包后是 exe 所在目录，源码运行时是本文件所在目录。"""\n'
                "    return os.path.dirname(os.path.abspath("
                'sys.argv[0] if getattr(sys, "frozen", False) else __file__))',
                "def app_dir() -> str:\n"
                '    """程序所在目录：打包后是 exe 所在目录，源码运行时是项目根目录（vcct/ 的上一级）。"""\n'
                '    if getattr(sys, "frozen", False):\n'
                "        return os.path.dirname(os.path.abspath(sys.executable))\n"
                "    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))",
            ),
            # 2) 崩溃弹窗延迟导入 tkinter：本模块要能在无桌面环境被导入
            (
                "    _crash_dialog_open = True\n    try:\n        root = tk.Tk()",
                "    _crash_dialog_open = True\n"
                "    # 延迟导入：本模块要能在无 tkinter / 无桌面环境（含 CI）下被导入\n"
                "    import tkinter as tk\n"
                "    from tkinter import messagebox\n"
                "    try:\n        root = tk.Tk()",
            ),
        ],
        "store": [
            # 3) 可变全局不能用 from-import 取值，补一个读取函数
            (
                'LAST_LOAD_WARNING = ""   # 最近一次读取配置时的异常说明（供界面提示）',
                'LAST_LOAD_WARNING = ""   # 最近一次读取配置时的异常说明（供界面提示）\n'
                "\n"
                "\n"
                "def last_load_warning() -> str:\n"
                '    """读取最近一次加载告警。\n'
                "\n"
                "    必须用函数而不是 `from vcct.store import LAST_LOAD_WARNING`：\n"
                "    load_store 会重新绑定这个全局，按值导入拿到的永远是导入那一刻的空串。\n"
                '    """\n'
                "    return LAST_LOAD_WARNING",
            )
        ],
        "main": [
            ("self.load_warning = LAST_LOAD_WARNING", "self.load_warning = last_load_warning()"),
            (
                'if LAST_LOAD_WARNING:\n            messagebox.showerror("备份不可用", LAST_LOAD_WARNING, parent=self.root)',
                'if last_load_warning():\n            messagebox.showerror("备份不可用", last_load_warning(), parent=self.root)',
            ),
            ("bool(quarantined) and bool(LAST_LOAD_WARNING)", "bool(quarantined) and bool(last_load_warning())"),
        ],
    }

    def adapt(text: str, key: str) -> str:
        for old, new in ADAPT.get(key, []):
            if old not in text:
                raise SystemExit(f"ERROR: 适配点未命中（{key}）：{old.splitlines()[0][:70]!r}")
            text = text.replace(old, new, 1)
        return text

    pkg = os.path.join(ROOT, "vcct")
    os.makedirs(pkg, exist_ok=True)
    for mod in ("const", "winapi", "hotkeys", "store", "loggingx"):
        body = adapt("".join(buckets[mod]).lstrip("\n"), mod)
        with open(os.path.join(pkg, f"{mod}.py"), "w", encoding="utf-8") as fh:
            fh.write(HEADERS[mod] + body)
        print(f"  vcct/{mod}.py: {len(buckets[mod])} blocks, {body.count(chr(10)) + 1} lines")

    init = os.path.join(pkg, "__init__.py")
    if not os.path.exists(init):
        with open(init, "w", encoding="utf-8") as fh:
            fh.write('# -*- coding: utf-8 -*-\n"""VC-Cheat-Typer 内部包（1.7 起）。"""\n')
        print("  vcct/__init__.py")

    rest = adapt("".join(buckets[None]).lstrip("\n"), "main")
    marker = "from tkinter import filedialog, messagebox, simpledialog, ttk\n"
    if marker not in rest:
        print("ERROR: 未找到 import 锚点", file=sys.stderr)
        return 1

    shim = (
        marker
        + """
# --- 1.7 兼容层：实现已搬入 vcct/，此处按名导入以保持既有调用与测试不变 ---
from vcct.const import (  # noqa: F401
    APP_NAME, APP_VER, C, DEFAULT_SETTINGS, IS_WIN, PAUSE_HID, PAUSE_ID, PRESETS,
    STORE_APP, STORE_VERSION, WIN_H, WIN_W,
)
from vcct.winapi import (  # noqa: F401
    ERROR_ACCESS_DENIED, ERROR_HOTKEY_ALREADY_REGISTERED, GA_ROOT, GWL_EXSTYLE, INPUT,
    KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE, MODIFIER_VKS, MOD_ALT, MOD_CONTROL,
    MOD_NOREPEAT, MOD_SHIFT, MOD_WIN, VK_BY_NAME, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW,
    WS_EX_TOPMOST, ImeGuard, _key_item, _send, add_window_exstyle, enable_dpi_awareness,
    find_game_window, force_foreground, foreground_info, get_window_exstyle, imm32,
    is_key_down, kernel32, press_key, raw_char_probe, ui_scale, user32,
)
from vcct.hotkeys import (  # noqa: F401
    HotkeyEngine, build_bindings, candidate_combos, combo_signature, format_combo,
    is_safe_binding, parse_combo, pick_free_combo,
)
from vcct.store import (  # noqa: F401
    _norm_cheat, _safe_int, bump_stats, bundle_payload, default_cheats, default_store,
    filter_cheats, last_load_warning, load_store, normalize_store, parse_bundle,
    save_store, sorted_cheats, touch_today,
)
from vcct.loggingx import (  # noqa: F401
    append_log, backup_path, data_path, install_crash_hooks, log_dir, log_file,
)
"""
    )

    rest = rest.replace(marker, shim, 1)
    with open(SRC, "w", encoding="utf-8") as fh:
        fh.write(rest)
    print(f"  vc_cheat_typer.py: {rest.count(chr(10)) + 1} lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
