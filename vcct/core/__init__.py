# -*- coding: utf-8 -*-
"""2.0：`vcct.core` —— 零 tkinter 的公共 API 门面。

**兼容式抽库**（关键实现决策）
------------------------------
路线图 2.0-A 要求把核心从业务里剥出来。直接把 `vcct/*.py` 搬进 `vcct/core/`
会让 1.7～1.9 的全部 import、PyInstaller spec 和 CLI 同时失效，属于"抽库演变成
重写"（风险 R2.0.1）。因此这里采用**门面 + 实现层保留**：

* 既有 `vcct/*.py` 原地不动，继续作为实现层（1.7 拆包成果完整保留）；
* 本包只导出公共 API，并在 `core/` 下新增平台无关的新能力
  （`targets` / `strategy` / `hooks`）；
* UI 仍从 `vcct.*` 导入，行为逐项不变；新的通用能力一律走 `vcct.core`。

架构约束（由 `tests/test_core_boundary.py` 用 AST 守住）
-------------------------------------------------------
1. `vcct/core/` 内任何模块不得 `import tkinter`（含函数内延迟导入）；
2. `vcct/core/` 内不得出现 `ctypes.WinDLL` / `windll` 等 Win32 直接调用；
3. 实现层（const/store/sender/packs/loggingx/templates/targets/strategy/hooks）
   的 import 图中同样不得出现 tkinter。

平台相关模块（`winapi` / `hotkeys` / `tray` / `importer`）用 PEP 562 惰性导出，
因此 `import vcct.core` 在无桌面、甚至非 Windows 环境下也不会去加载 Win32 DLL。
"""

from __future__ import annotations

from ..const import APP_NAME, APP_VER, DEFAULT_GAME, DEFAULT_SETTINGS, PRESETS, STORE_VERSION
from ..sender import SendCancelled, SendError, SendParams, default_hold, type_text
from ..store import (
    bundle_payload,
    default_store,
    evaluate_game_rules,
    export_v2,
    load_store,
    match_game_rule,
    migrate_store,
    normalize_store,
    parse_bundle,
    save_store,
    to_v2,
)
from ..packs import auto_avoid_hotkeys, compare_pack_record, diff_pack, make_pack, merge_pack, validate_pack
from ..templates import TEMPLATE_INFO, TEMPLATE_NAMES, template_cheats, template_preset
from .targets import (
    MATCH_TYPES,
    Target,
    evaluate_targets,
    match_target,
    normalize_targets,
    parse_target_spec,
    resolve_target,
    targets_from_games,
)
from .strategy import (
    STRATEGY_KINDS,
    SendStrategy,
    describe_plan,
    normalize_strategies,
    normalize_strategy,
    plan_send,
    resolve_strategy,
    should_retry,
)
from .hooks import HookBus, HookEvent, make_log_hook, make_switch_window_hook

# 惰性导出：只有真正用到时才加载平台相关模块
_LAZY = {
    "find_game_window": ("..winapi", "find_game_window"),
    "foreground_info": ("..winapi", "foreground_info"),
    "release_modifiers": ("..winapi", "release_modifiers"),
    "send_key": ("..winapi", "send_key"),
    "build_bindings": ("..hotkeys", "build_bindings"),
    "parse_combo": ("..hotkeys", "parse_combo"),
    "format_combo": ("..hotkeys", "format_combo"),
    "parse_pasted": ("..importer", "parse_pasted"),
    "TrayIcon": ("..tray", "TrayIcon"),
}


def __getattr__(name: str):
    if name not in _LAZY:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module_name, attr = _LAZY[name]
    return getattr(importlib.import_module(module_name, __name__), attr)


def core_modules() -> tuple[str, ...]:
    """供架构守卫测试使用：core 依赖的实现层模块清单。"""
    return (
        "vcct.const",
        "vcct.sender",
        "vcct.store",
        "vcct.packs",
        "vcct.loggingx",
        "vcct.templates",
        "vcct.core.targets",
        "vcct.core.strategy",
        "vcct.core.hooks",
    )


__all__ = [
    "APP_NAME",
    "APP_VER",
    "DEFAULT_GAME",
    "DEFAULT_SETTINGS",
    "PRESETS",
    "STORE_VERSION",
    "SendCancelled",
    "SendError",
    "SendParams",
    "default_hold",
    "type_text",
    "bundle_payload",
    "default_store",
    "evaluate_game_rules",
    "export_v2",
    "load_store",
    "match_game_rule",
    "migrate_store",
    "normalize_store",
    "parse_bundle",
    "save_store",
    "to_v2",
    "auto_avoid_hotkeys",
    "compare_pack_record",
    "diff_pack",
    "make_pack",
    "merge_pack",
    "validate_pack",
    "TEMPLATE_INFO",
    "TEMPLATE_NAMES",
    "template_cheats",
    "template_preset",
    "MATCH_TYPES",
    "Target",
    "evaluate_targets",
    "match_target",
    "normalize_targets",
    "parse_target_spec",
    "resolve_target",
    "targets_from_games",
    "STRATEGY_KINDS",
    "SendStrategy",
    "describe_plan",
    "normalize_strategies",
    "normalize_strategy",
    "plan_send",
    "resolve_strategy",
    "should_retry",
    "HookBus",
    "HookEvent",
    "make_log_hook",
    "make_switch_window_hook",
    "core_modules",
    *_LAZY.keys(),
]
