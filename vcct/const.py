# -*- coding: utf-8 -*-
"""1.7：全局常量。本模块**零内部依赖**，任何模块都可以安全导入。"""

from __future__ import annotations

import os

APP_NAME = "VC-Cheat-Typer"
APP_VER = "2.2.1"
IS_WIN = os.name == "nt"


# ----------------------------------------------------------------------------
# 数据（v3：v2 + packs / ui / 方案游戏绑定；自动迁移 v1 → v2 → v3）
# ----------------------------------------------------------------------------
STORE_VERSION = 3
STORE_APP = "vc-cheat-typer"
DEFAULT_GAME = "VC 经典版"  # 1.9-D：方案默认绑定的游戏模板

DEFAULT_SETTINGS = {
    "char_interval_ms": 45,  # 每字总间隔
    "key_hold_ms": 25,  # 每个键按下后保持多久（必须大于游戏帧间隔）
    "pre_delay_ms": 180,  # 触发后先等一下，让手指离开修饰键
    "require_foreground": True,
    "target_keywords": "Vice City",
    "release_modifiers": True,
    "uppercase": False,
    "disable_ime": True,  # 发送期间临时摘掉目标窗口的输入法关联（绕开中文 IME 吞字）
    "show_toast": True,  # 游戏内悬浮提示（不抢焦点）
    "pause_hotkey": "Ctrl+Alt+P",  # 全局暂停：一键关掉全部秘籍热键（防止在别的窗口误触）
    "debounce_ms": 250,  # 同一秘籍连按去抖（手抖连按两下不该打两遍）
    # --- 1.8 新增（全部可选：缺省 = 旧行为，v2 配置直接兼容） ---
    "close_to_tray": True,  # 关闭窗口 = 最小化到托盘；False = 关闭即退出（1.7 及以前的行为）
    "auto_switch": True,  # 按游戏自动切方案总开关（games 规则表逐条还有自己的 enabled）
    "onboarded": False,  # 首次启动向导是否已完成/跳过
    # --- 2.0 新增（可选，缺省 = 旧行为） ---
    "hooks_enabled": False,  # 扩展点（前置/后置钩子）总开关，默认关闭
    # --- 2.1 新增（可选，缺省 = 旧行为） ---
    "locale": "zh",  # 界面语言 zh/en；默认中文
    "check_updates": False,  # 菜单显示「检查更新」入口，默认关闭
    # --- 2.2 Nova UI（可选；ui_mode=classic 时其余两项被忽略） ---
    "ui_mode": "nova",  # nova（新骨架）/ classic（1.7~2.1 原布局，一键回退）
    "theme": "light",  # light / dark
    "density": "comfortable",  # comfortable / compact
}

# 参数预设：经典版按帧率 30fps 调优；决定版(Unreal)输入窗口更宽但帧率不定，整体放慢
PRESETS = {"经典版": {"char_interval_ms": 45, "pre_delay_ms": 180}, "决定版": {"char_interval_ms": 70, "pre_delay_ms": 250}}


# ----------------------------------------------------------------------------
# 纯函数：列表过滤 / 热键表构建（不依赖 Tk，便于单元测试）
# ----------------------------------------------------------------------------
PAUSE_ID = "__pause__"  # 暂停键在热键表里的虚拟条目 id
PAUSE_HID = 9000  # 避开 1..N 的秘籍热键 id


# ----------------------------------------------------------------------------
# 主窗口
# ----------------------------------------------------------------------------
C = {
    "bg": "#f5f6f8",
    "panel": "#ffffff",
    "line": "#e3e7ee",
    "text": "#1a1f29",
    "muted": "#6b7280",
    "accent": "#2563eb",
    "ok": "#067647",
    "warn": "#b42318",
    "soft": "#eef4ff",
}
WIN_W, WIN_H = 1120, 700  # 96 DPI 下的基准尺寸，实际按 ui 比例放大
