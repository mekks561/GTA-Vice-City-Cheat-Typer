# -*- coding: utf-8 -*-
"""2.2 Nova UI：主窗口骨架（侧栏 + 顶栏 + 内容区 + 状态中心）。

**关键约束**：本类只搭外壳，不重建业务控件树。主程序把原有的 `outer`
挂到 `content_host` 上即可，所有 `self.tree` / `self.btn_send` / 事件绑定
保持原样 —— 这是"核心业务流程稳定"与"可回退"的实现基础。
"""

from __future__ import annotations

import tkinter as tk

from . import components as ui
from .theme import Tokens

STATUS_KEYS = ("game", "hotkeys", "send", "config", "locale")
STATUS_LABELS = {"game": "游戏 ●", "hotkeys": "热键 ●", "send": "发送 ●", "config": "配置 ●", "locale": "中文 ●"}
NAV_ITEMS = (
    ("秘籍", "cheat.add"),
    ("热键", "hotkey.overview"),
    ("内容", "content.pack"),
    ("数据", "data.settings"),
    ("帮助", "help.wizard"),
)


class NovaShell:
    """新版外壳。`classic=True` 时主程序不会创建本类，直接把内容挂到 root。"""

    def __init__(self, root, app, tk_tokens: Tokens, registry, on_command_panel, on_theme, title: str):
        self.root = root
        self.app = app
        self.tk_tokens = tk_tokens
        self.registry = registry
        self._targets: list[tuple] = []  # (widget, option, token_key) 供换肤

        # pack 顺序很重要：先占上下两条固定带，再放可伸缩的内容区，
        # 否则 expand=True 的 body 会把底部状态中心挤成 0 高。
        self.status_bar, self.pills = ui.status_center(root, tk_tokens, [STATUS_LABELS[k] for k in STATUS_KEYS])
        self.status_bar.pack(fill="x", side="bottom")
        self._remember(self.status_bar, "bg", "bg")
        self._pill_by_key = dict(zip(STATUS_KEYS, self.pills.values()))

        self.top = ui.top_bar(root, tk_tokens, on_command_panel, on_theme, title)
        self.top.pack(fill="x", side="top")

        self.body = tk.Frame(root, bg=tk_tokens["bg"])
        self.body.pack(fill="both", expand=True, side="top")

        self.sidebar = tk.Frame(self.body, bg=tk_tokens["sidebar"], width=int(168 * tk_tokens.space("md") / 12))
        self.sidebar.pack(fill="y", side="left")
        self.sidebar.pack_propagate(False)
        self._remember(self.sidebar, "bg", "sidebar")

        self.nav_buttons: list[tk.Button] = []
        for label, cmd_id in NAV_ITEMS:
            btn = ui.nav_button(self.sidebar, tk_tokens, "  " + label, lambda c=cmd_id: self._nav(c))
            btn.pack(fill="x", padx=tk_tokens.space("sm"), pady=(tk_tokens.space("xs") if self.nav_buttons else tk_tokens.space("md"), 0))
            self.nav_buttons.append(btn)

        ui.separator(self.body, tk_tokens).pack(fill="y", side="left")

        self.content_host = tk.Frame(self.body, bg=tk_tokens["bg"], padx=tk_tokens.space("md"), pady=tk_tokens.space("sm"))
        self.content_host.pack(fill="both", expand=True, side="left")
        self._remember(self.content_host, "bg", "bg")

    # -- 换肤 / 状态 ---------------------------------------------------------
    def _remember(self, widget, option: str, key: str):
        self._targets.append((widget, option, key))

    def refresh_theme(self, tk_tokens: Tokens):
        """换主题：只改色，不重建任何业务控件（验收 I3）。"""
        self.tk_tokens = tk_tokens
        for widget, option, key in self._targets:
            try:
                widget.configure(**{option: tk_tokens[key]})
            except Exception:
                pass
        for btn in self.nav_buttons:
            try:
                btn.configure(bg=tk_tokens["sidebar"], fg=tk_tokens["text"], activebackground=tk_tokens["hover"])
            except Exception:
                pass
        for pill in self._pill_by_key.values():
            try:
                pill.configure(bg=tk_tokens["status_idle"], fg=tk_tokens["pill_text"])
            except Exception:
                pass
        try:
            self.sidebar.configure(bg=tk_tokens["sidebar"])
        except Exception:
            pass

    def set_status(self, key: str, text: str, kind: str = "idle"):
        pill = self._pill_by_key.get(key)
        if pill is None:
            return
        bg = {"ok": "status_ok", "warn": "status_warn"}.get(kind, "status_idle")
        fg = {"ok": "ok", "warn": "warn"}.get(kind, "pill_text")
        try:
            pill.configure(text=text, bg=self.tk_tokens[bg], fg=self.tk_tokens[fg])
        except Exception:
            pass

    def _nav(self, cmd_id: str):
        cmd = next((c for c in self.registry.all() if c.id == cmd_id), None)
        if cmd:
            self.registry.execute(cmd)

    def active_nav(self, index: int):
        for i, btn in enumerate(self.nav_buttons):
            try:
                btn.configure(
                    bg=self.tk_tokens["sidebar_active"] if i == index else self.tk_tokens["sidebar"],
                    fg=self.tk_tokens["accent"] if i == index else self.tk_tokens["text"],
                )
            except Exception:
                pass
