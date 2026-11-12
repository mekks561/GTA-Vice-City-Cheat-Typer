# -*- coding: utf-8 -*-
"""2.2 Nova UI：命令面板（Ctrl+K）——纯标准库、零第三方依赖。

命令只绑定到 `CheatApp` **已存在**的公开方法；注册表不新增任何业务入口，
这是"核心业务流程零改动"的边界。所有方法用 `getattr` 惰性解析，找不到时
命令自动禁用而不是抛异常（对旧配置/回退模式宽容）。
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass

from .theme import Tokens


@dataclass(frozen=True)
class Command:
    id: str
    title: str
    group: str
    keywords: str
    action_name: str  # CheatApp 上的方法名
    haystack: str  # 预计算的小写检索串（R3 性能）


class CommandRegistry:
    def __init__(self, app=None):
        self.app = app
        self._items: list[Command] = []

    def add(self, id_: str, title: str, group: str, action_name: str, keywords: str = "") -> None:
        hay = f"{id_} {title} {group} {keywords}".lower()
        self._items.append(Command(id_, title, group, keywords, action_name, hay))

    def all(self) -> list[Command]:
        return list(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def search(self, query: str, limit: int = 12) -> list[Command]:
        """子序列模糊匹配；空查询返回前 limit 条。输入到出结果不碰 UI（可计时）。"""
        q = (query or "").strip().lower()
        if not q:
            return self._items[:limit]
        out = []
        for c in self._items:
            if q in c.haystack or _subsequence(q, c.haystack):
                out.append(c)
                if len(out) >= limit:
                    break
        return out

    def execute(self, cmd: Command) -> bool:
        if self.app is None:
            return False
        fn = getattr(self.app, cmd.action_name, None)
        if not callable(fn):
            return False
        fn()
        return True


def _subsequence(needle: str, haystack: str) -> bool:
    it = iter(haystack)
    return all(ch in it for ch in needle)


def default_commands(app) -> CommandRegistry:
    """覆盖 ≥20 个既有动作；名称与 1.7～2.1 菜单/按钮一一对应。"""
    reg = CommandRegistry(app)
    items = [
        ("cheat.add", "添加秘籍", "秘籍", "add_cheat", "new create 新建"),
        ("cheat.edit", "编辑选中秘籍", "秘籍", "edit_selected", "modify 修改"),
        ("cheat.delete", "删除选中秘籍", "秘籍", "delete_selected", "remove 移除"),
        ("cheat.send", "发送所选", "秘籍", "send_selected", "fire trigger enter"),
        ("cheat.stop", "停止发送", "秘籍", "stop_send", "cancel esc 取消"),
        ("cheat.reset", "恢复默认秘籍表", "秘籍", "reset_defaults", "restore 还原"),
        ("hotkey.pause", "暂停 / 恢复热键", "热键", "toggle_pause", "pause resume"),
        ("hotkey.register", "重新注册全部快捷键", "热键", "apply_hotkeys", "rebind refresh"),
        ("hotkey.overview", "快捷键总览", "热键", "open_hotkey_overview", "list bindings"),
        ("content.pack", "秘籍包管理", "内容", "open_pack_manager", "vcpack import export"),
        ("content.paste", "从文本 / CSV 粘贴导入", "内容", "open_text_import", "csv paste"),
        ("content.template", "套用游戏模板", "内容", "open_template_dialog", "preset game"),
        ("content.bundle", "导入整包", "内容", "import_bundle", "backup restore"),
        ("content.export", "导出整包", "内容", "export_bundle", "backup save"),
        ("data.history", "发送历史", "数据", "open_history", "log recent 50"),
        ("data.settings", "设置", "数据", "open_settings", "preferences config"),
        ("data.stats", "清空使用统计", "数据", "clear_stats", "reset count"),
        ("data.log", "打开日志目录", "数据", "open_log", "logs folder"),
        ("data.diagnose", "环境诊断", "帮助", "run_diagnose", "diagnose privilege uipi"),
        ("help.wizard", "首次启动向导", "帮助", "open_wizard", "onboarding tutorial"),
        ("help.test", "注入自检", "帮助", "open_test_window", "selftest probe"),
        ("help.admin", "以管理员身份重启", "帮助", "relaunch_as_admin", "uipi elevate"),
        ("help.update", "检查更新", "帮助", "check_updates", "release browser"),
    ]
    for row in items:
        reg.add(*row)
    return reg


class CommandPalette(tk.Toplevel):
    """Ctrl+K 面板：输入即筛、↑↓ 选择、Enter 执行、Esc 关闭；不阻塞主线程。"""

    def __init__(self, master, registry: CommandRegistry, tk_tokens: Tokens, on_status=None, scale: float = 1.0):
        super().__init__(master)
        self.registry = registry
        self.tk_tokens = tk_tokens
        self.on_status = on_status
        self.results: list[Command] = []
        self.title("命令面板")
        self.configure(bg=tk_tokens["panel"])
        self.transient(master)
        self.resizable(False, False)
        w = int(560 * scale)
        self.geometry(f"{w}x360")
        pad = tk_tokens.space("md")

        self.var_query = tk.StringVar()
        self.entry = tk.Entry(
            self,
            textvariable=self.var_query,
            relief="flat",
            font=tk_tokens.font(),
            bg=tk_tokens["card"],
            fg=tk_tokens["text"],
            insertbackground=tk_tokens["accent"],
            highlightthickness=1,
            highlightbackground=tk_tokens["line"],
            highlightcolor=tk_tokens["accent"],
        )
        self.entry.pack(fill="x", padx=pad, pady=(pad, tk_tokens.space("sm")), ipady=6)

        self.listbox = tk.Listbox(
            self,
            relief="flat",
            bd=0,
            bg=tk_tokens["card"],
            fg=tk_tokens["text"],
            selectbackground=tk_tokens["sidebar_active"],
            selectforeground=tk_tokens["text"],
            font=tk_tokens.font(),
            activestyle="none",
        )
        self.listbox.pack(fill="both", expand=True, padx=pad, pady=(0, pad))

        tk.Label(
            self, text="↑↓ 选择 · Enter 执行 · Esc 关闭", bg=tk_tokens["panel"], fg=tk_tokens["muted"], font=tk_tokens.font("small")
        ).pack(anchor="w", padx=pad, pady=(0, tk_tokens.space("sm")))

        self.var_query.trace_add("write", lambda *_: self._refresh())
        self.entry.bind("<Return>", lambda e: self._run())
        self.entry.bind("<Escape>", lambda e: self.destroy())
        self.entry.bind("<Up>", lambda e: self._move(-1))
        self.entry.bind("<Down>", lambda e: self._move(1))
        self.listbox.bind("<Double-Button-1>", lambda e: self._run())
        self.bind("<Escape>", lambda e: self.destroy())

        self._refresh()
        self.after_idle(self.entry.focus_set)

    def _refresh(self):
        self.results = self.registry.search(self.var_query.get())
        self.listbox.delete(0, "end")
        for cmd in self.results:
            self.listbox.insert("end", f"  {cmd.title}    · {cmd.group}")
        if self.results:
            self.listbox.selection_set(0)
            self.listbox.activate(0)

    def _move(self, delta: int):
        if not self.results:
            return "break"
        cur = self.listbox.curselection()[0] if self.listbox.curselection() else 0
        nxt = min(max(0, cur + delta), len(self.results) - 1)
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(nxt)
        self.listbox.see(nxt)
        return "break"

    def _run(self):
        if not self.results:
            return "break"
        sel = self.listbox.curselection()
        cmd = self.results[sel[0] if sel else 0]
        ok = self.registry.execute(cmd)
        if self.on_status:
            self.on_status(f"{'✔' if ok else '⚠'} {cmd.title}")
        self.destroy()
        return "break"
