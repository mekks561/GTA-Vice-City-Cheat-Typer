# -*- coding: utf-8 -*-
"""1.7：全局常量。本模块**零内部依赖**，任何模块都可以安全导入。"""
from __future__ import annotations

import os

APP_NAME = "VC-Cheat-Typer"
APP_VER = "1.6"
IS_WIN = os.name == "nt"


# ----------------------------------------------------------------------------
# 数据（v2：多方案组 + 使用统计；自动迁移 v1 单列表格式）
# ----------------------------------------------------------------------------
STORE_VERSION = 2
STORE_APP = "vc-cheat-typer"

DEFAULT_SETTINGS = {
    "char_interval_ms": 45,   # 每字总间隔
    "key_hold_ms": 25,        # 每个键按下后保持多久（必须大于游戏帧间隔）
    "pre_delay_ms": 180,      # 触发后先等一下，让手指离开修饰键
    "require_foreground": True,
    "target_keywords": "Vice City",
    "release_modifiers": True,
    "uppercase": False,
    "disable_ime": True,      # 发送期间临时摘掉目标窗口的输入法关联（绕开中文 IME 吞字）
    "show_toast": True,       # 游戏内悬浮提示（不抢焦点）
    "pause_hotkey": "Ctrl+Alt+P",  # 全局暂停：一键关掉全部秘籍热键（防止在别的窗口误触）
}

# 参数预设：经典版按帧率 30fps 调优；决定版(Unreal)输入窗口更宽但帧率不定，整体放慢
PRESETS = {
    "经典版": {"char_interval_ms": 45, "pre_delay_ms": 180},
    "决定版": {"char_interval_ms": 70, "pre_delay_ms": 250},
}


# ----------------------------------------------------------------------------
# 纯函数：列表过滤 / 热键表构建（不依赖 Tk，便于单元测试）
# ----------------------------------------------------------------------------
PAUSE_ID = "__pause__"   # 暂停键在热键表里的虚拟条目 id
PAUSE_HID = 9000         # 避开 1..N 的秘籍热键 id


# ----------------------------------------------------------------------------
# 主窗口
# ----------------------------------------------------------------------------
C = {
    "bg": "#f5f6f8", "panel": "#ffffff", "line": "#e3e7ee",
    "text": "#1a1f29", "muted": "#6b7280", "accent": "#2563eb",
    "ok": "#067647", "warn": "#b42318", "soft": "#eef4ff",
}
WIN_W, WIN_H = 1120, 700   # 96 DPI 下的基准尺寸，实际按 ui 比例放大
