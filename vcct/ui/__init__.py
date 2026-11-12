# -*- coding: utf-8 -*-
"""2.2 `vcct.ui` —— 自研 UI 基础设施层（令牌驱动 / 声明式 / 命令优先）。

与 `vcct.core` 的边界：

* `core` 零 GUI 依赖，可独立安装；
* `ui` 只依赖 tkinter/ttk 标准库与 `vcct.const.C` 调色板引用，**零第三方依赖**；
* `ui` 不直接调用任何 Win32 API，也不新增业务方法，只调用 `CheatApp` 既有入口。

因此引入本层不破坏 `CONTRIBUTING.md` 的三条架构硬约束，也不改变
「零运行时依赖 / 配置不丢 / 发布必带 SHA256 / 暂停可中断 / 不联网」五条不变量。
"""

from .theme import DENSITIES, THEMES, PALETTES, Tokens, apply_theme, check_contrast, classic_palette, contrast_ratio, tokens
from .components import card, empty_state, nav_button, pill, separator, status_center, top_bar
from .commands import Command, CommandPalette, CommandRegistry, default_commands
from .shell import NAV_ITEMS, STATUS_KEYS, STATUS_LABELS, NovaShell

__all__ = [
    "DENSITIES",
    "THEMES",
    "PALETTES",
    "Tokens",
    "apply_theme",
    "check_contrast",
    "classic_palette",
    "contrast_ratio",
    "tokens",
    "card",
    "empty_state",
    "nav_button",
    "pill",
    "separator",
    "status_center",
    "top_bar",
    "Command",
    "CommandPalette",
    "CommandRegistry",
    "default_commands",
    "NAV_ITEMS",
    "STATUS_KEYS",
    "STATUS_LABELS",
    "NovaShell",
]
