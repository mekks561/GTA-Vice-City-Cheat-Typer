# -*- coding: utf-8 -*-
"""2.2 Nova UI：声明式组件工厂。

约束（验收 V1/V4）：本模块**不得出现任何颜色字面量**，所有配色与间距
必须来自 `Tokens`；组件只负责搭结构，不持有业务状态。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .theme import Tokens


def card(parent, tk_tokens: Tokens, padding: str = "md") -> tk.Frame:
    """圆角感的卡片容器（tk 用 1px 描边 + 内边距模拟，无需第三方库）。"""
    f = tk.Frame(
        parent,
        bg=tk_tokens["card"],
        highlightthickness=1,
        highlightbackground=tk_tokens["card_border"],
        highlightcolor=tk_tokens["card_border"],
        padx=tk_tokens.space(padding),
        pady=tk_tokens.space(padding),
    )
    return f


def pill(parent, tk_tokens: Tokens, text: str, kind: str = "idle") -> tk.Label:
    """状态胶囊：idle / ok / warn 三态，色值全部来自令牌。"""
    bg = {"ok": "status_ok", "warn": "status_warn"}.get(kind, "status_idle")
    fg = {"ok": "ok", "warn": "warn"}.get(kind, "pill_text")
    return tk.Label(
        parent,
        text=text,
        bg=tk_tokens[bg],
        fg=tk_tokens[fg],
        font=tk_tokens.font("small"),
        padx=tk_tokens.space("sm"),
        pady=tk_tokens.space("xs"),
    )


def nav_button(parent, tk_tokens: Tokens, text: str, command, active: bool = False) -> tk.Button:
    """侧栏导航项：扁平、无边框、悬停高亮；active 态用强调色。"""
    b = tk.Button(
        parent,
        text=text,
        command=command,
        anchor="w",
        relief="flat",
        bd=0,
        cursor="hand2",
        bg=tk_tokens["sidebar_active"] if active else tk_tokens["sidebar"],
        fg=tk_tokens["accent"] if active else tk_tokens["text"],
        activebackground=tk_tokens["hover"],
        font=tk_tokens.font(),
        padx=tk_tokens.space("md"),
        pady=tk_tokens.space("sm"),
    )
    b.bind("<Enter>", lambda e: b.configure(bg=tk_tokens["hover"]))
    b.bind("<Leave>", lambda e: b.configure(bg=tk_tokens["sidebar_active"] if active else tk_tokens["sidebar"]))
    return b


def top_bar(parent, tk_tokens: Tokens, on_command_panel, on_theme, title: str) -> tk.Frame:
    """顶栏：标题 + 命令面板入口 + 主题切换。"""
    bar = tk.Frame(parent, bg=tk_tokens["topbar"], padx=tk_tokens.space("lg"), pady=tk_tokens.space("sm"))
    tk.Label(
        bar, text=title, bg=tk_tokens["topbar"], fg=tk_tokens["text"], font=(tk_tokens.fonts["family"], tk_tokens.fonts["h2"], "bold")
    ).pack(side="left")
    ttk.Button(bar, text="切换主题", command=on_theme).pack(side="right", padx=(6, 0))
    tk.Button(
        bar,
        text="⌘K  命令面板",
        command=on_command_panel,
        relief="flat",
        bd=0,
        cursor="hand2",
        bg=tk_tokens["pill"],
        fg=tk_tokens["pill_text"],
        activebackground=tk_tokens["hover"],
        font=tk_tokens.font("small"),
        padx=tk_tokens.space("md"),
        pady=tk_tokens.space("xs"),
    ).pack(side="right", padx=(6, 0))
    return bar


def status_center(parent, tk_tokens: Tokens, labels: list[str]) -> tuple[tk.Frame, dict]:
    """底部状态中心：返回容器与 {label: pill} 映射，供运行时更新。"""
    bar = tk.Frame(parent, bg=tk_tokens["bg"], padx=tk_tokens.space("lg"), pady=tk_tokens.space("sm"))
    pills = {}
    for label in labels:
        p = pill(bar, tk_tokens, label)
        p.pack(side="left", padx=(0, tk_tokens.space("sm")))
        pills[label] = p
    return bar, pills


def empty_state(parent, tk_tokens: Tokens, title: str, hint: str) -> tk.Frame:
    """空状态占位（列表无结果 / 首次使用）。"""
    box = tk.Frame(parent, bg=tk_tokens["card"], padx=tk_tokens.space("xl"), pady=tk_tokens.space("xl"))
    tk.Label(
        box, text=title, bg=tk_tokens["card"], fg=tk_tokens["text"], font=(tk_tokens.fonts["family"], tk_tokens.fonts["h2"], "bold")
    ).pack()
    tk.Label(box, text=hint, bg=tk_tokens["card"], fg=tk_tokens["muted"], font=tk_tokens.font("small")).pack(
        pady=(tk_tokens.space("sm"), 0)
    )
    return box


def separator(parent, tk_tokens: Tokens) -> tk.Frame:
    return tk.Frame(parent, bg=tk_tokens["line"], height=1)
