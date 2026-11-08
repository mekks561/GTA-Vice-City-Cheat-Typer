# -*- coding: utf-8 -*-
"""
VC-Cheat-Typer — GTA: Vice City 秘籍一键输入器（Windows / 单文件 / 零第三方依赖）
================================================================

功能
----
1. 全局快捷键触发：在游戏窗口处于前台时，按下预设快捷键，自动"打字"输入对应秘籍；
2. 秘籍列表：可查看、按分组切换、按使用次数排序；
3. 增删改：可添加/编辑/删除秘籍（名称、代码、备注、分组）；
4. 独立快捷键：每条秘籍可单独绑定/解绑，冲突（同程序内重复或被系统/其他软件占用）实时提示；
5. 前台校验：默认只在目标窗口（标题关键字/游戏进程自动检测）在前台时才发送，避免误输入到别的窗口；
6. 方案组：多套秘籍方案（如「默认」「速通」）一键切换，各自独立快捷键；
7. 游戏内悬浮提示：发送结果以不抢焦点的 toast 直接显示在屏幕右下角；
8. 导入/导出：一键分享整份方案；
9. 配置持久化：方案、设置、使用统计保存在同目录 cheats.json（v2 格式，自动迁移 v1）。

技术要点（为什么这样实现）
--------------------------
* 注入用 SendInput + **扫描码(KEYEVENTF_SCANCODE)**：GTA VC 经典版通过 DirectInput 轮询键盘设备状态，
  PostMessage/SendKeys 这类"消息级"输入它读不到，扫描码注入走的是驱动层，DirectInput 才能识别。
* 每个字符的按下与抬起**分两次调用**并留出保持时间：游戏按帧轮询，按键在同一帧内下抬会被整帧漏掉，
  这是"自动打字丢字"的最常见原因（见设置里的"按键保持时间"）。
* 全局热键用 RegisterHotKey：它天然具备独占性——若组合键已被别的程序注册，注册会失败并返回
  1409(ERROR_HOTKEY_ALREADY_REGISTERED)，这就是"冲突提示"的来源，而不是靠猜。
* **绕开中文输入法**：中文键盘布局会给每个窗口挂一个 IME 输入上下文，把注入的击键转成
  VK_PACKET 吞掉（实测：不处理时目标窗口只收到 WM_KEYDOWN 229，一个字符都不出）。
  所以发送前用 ImmAssociateContext(hwnd, NULL) 临时摘掉目标窗口的输入法关联，发完再挂回去。
* **悬浮提示不抢焦点**：toast 窗口带 WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW 扩展样式，
  在游戏里弹提示时不会把游戏切到后台——这对"正在打秘籍"的场景是硬需求。

仅支持 Windows。运行环境与使用前提见同目录 README.md。
"""

from __future__ import annotations

import ctypes
import json
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
import uuid
from tkinter import filedialog, messagebox, simpledialog, ttk

# --- 1.7 兼容层：实现已搬入 vcct/，此处按名导入以保持既有调用与测试不变 ---
from vcct.const import (  # noqa: F401
    APP_NAME, APP_VER, C, DEFAULT_GAME, DEFAULT_SETTINGS, IS_WIN, PAUSE_HID, PAUSE_ID,
    PRESETS, STORE_APP, STORE_VERSION, WIN_H, WIN_W,
)
from vcct.winapi import (  # noqa: F401
    ERROR_ACCESS_DENIED, ERROR_HOTKEY_ALREADY_REGISTERED, GA_ROOT, GWL_EXSTYLE, INPUT,
    KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE, MODIFIER_VKS, MOD_ALT, MOD_CONTROL,
    MOD_NOREPEAT, MOD_SHIFT, MOD_WIN, VK_BY_NAME, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW,
    WS_EX_TOPMOST, ImeGuard, _key_item, _send, add_window_exstyle, enable_dpi_awareness,
    find_game_window, force_foreground, foreground_info, get_window_exstyle, imm32,
    is_key_down, kernel32, press_key, raw_char_probe, release_modifiers, send_key,
    ui_scale, user32, vk_for_char,
)
from vcct.winapi import (  # noqa: F401
    process_elevated, self_elevated, shell_execute_runas, window_pid,
)
from vcct.hotkeys import (  # noqa: F401
    HotkeyEngine, build_bindings, candidate_combos, combo_signature, format_combo,
    is_safe_binding, parse_combo, pick_free_combo,
)
from vcct.store import (  # noqa: F401
    _norm_cheat, _norm_history, _safe_int, bump_stats, bundle_payload, default_cheats, default_store,
    evaluate_game_rules, export_v2, filter_cheats, last_load_warning, load_store,
    migrate_store, normalize_store, parse_bundle, save_store, sorted_cheats, touch_today,
)
from vcct.packs import (  # noqa: F401
    auto_avoid_hotkeys, compare_pack_record, diff_pack, make_pack, merge_pack,
    pack_record, validate_pack,
)
from vcct.importer import parse_pasted  # noqa: F401
from vcct.templates import (  # noqa: F401
    TEMPLATE_INFO, TEMPLATE_NAMES, template_cheats, template_preset,
)
# 2.0：通用输入平台能力（纯逻辑，零 tkinter）
from vcct.core.strategy import (  # noqa: F401
    normalize_strategy, plan_send, resolve_strategy, should_retry,
)
from vcct.core.targets import (  # noqa: F401
    evaluate_targets, normalize_targets, resolve_target, targets_from_games,
)
from vcct.core.hooks import HookBus  # noqa: F401
from vcct.loggingx import (  # noqa: F401
    append_log, backup_path, data_path, install_crash_hooks, log_dir, log_file,
)
from vcct.sender import SendCancelled, SendError, SendParams, type_text
from vcct.tray import TrayIcon


# ----------------------------------------------------------------------------
# 快捷键捕获对话框
# ----------------------------------------------------------------------------
class HotkeyCapture(tk.Toplevel):
    def __init__(self, master, current: str, callback):
        super().__init__(master)
        self.callback = callback
        self.done = False
        self._prev: dict[int, bool] = {}
        self._polled = 0

        self.title("绑定快捷键")
        self.resizable(False, False)
        self.transient(master)
        self.configure(bg="#ffffff")
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        wrap = tk.Frame(self, bg="#ffffff", padx=26, pady=20)
        wrap.pack(fill="both", expand=True)
        tk.Label(wrap, text="请按下新的组合键", bg="#ffffff", fg="#1a1f29",
                 font=("Microsoft YaHei UI", 13, "bold")).pack(anchor="w")
        self.var = tk.StringVar(value=current or "（当前未绑定）")
        tk.Label(wrap, textvariable=self.var, bg="#eef4ff", fg="#1d4ed8",
                 font=("Consolas", 15, "bold"), padx=14, pady=10).pack(fill="x", pady=(12, 10))
        tk.Label(wrap, text="Esc 取消 · Backspace 清除绑定\n"
                            "单字母/数字必须加 Ctrl 或 Alt 或 Shift，否则会吞掉正常按键",
                 bg="#ffffff", fg="#6b7280", justify="left",
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w")

        self.update_idletasks()
        w, h = 380, 210
        x = master.winfo_rootx() + (master.winfo_width() - w) // 2
        y = master.winfo_rooty() + (master.winfo_height() - h) // 3
        self.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")
        self.grab_set()
        self.focus_force()
        self.after(30, self._tick)

    def _cancel(self):
        self.done = True
        self._close()

    def _close(self):
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()

    def _mods(self) -> int:
        mods = 0
        if is_key_down(0x11) or is_key_down(0xA2) or is_key_down(0xA3):
            mods |= MOD_CONTROL
        if is_key_down(0x10) or is_key_down(0xA0) or is_key_down(0xA1):
            mods |= MOD_SHIFT
        if is_key_down(0x12) or is_key_down(0xA4) or is_key_down(0xA5):
            mods |= MOD_ALT
        if is_key_down(0x5B) or is_key_down(0x5C):
            mods |= MOD_WIN
        return mods

    def _tick(self):
        if self.done:
            return
        if not self.winfo_exists():
            return
        self._polled += 1
        mods = self._mods()
        first_tick = self._polled == 1
        hit = None
        for vk in set(VK_BY_NAME.values()):
            down = is_key_down(vk)
            was = self._prev.get(vk, False)
            self._prev[vk] = down
            if first_tick or not down or was:
                continue
            if vk in MODIFIER_VKS:
                continue
            hit = vk
            break

        if hit is None:
            names = []
            if mods & MOD_CONTROL:
                names.append("Ctrl")
            if mods & MOD_ALT:
                names.append("Alt")
            if mods & MOD_SHIFT:
                names.append("Shift")
            if mods & MOD_WIN:
                names.append("Win")
            self.var.set("+".join(names) + "+ …" if names else "等待按键…")
            self.after(30, self._tick)
            return

        if hit == 0x1B:  # Esc
            self.done = True
            self._close()
            return
        if hit == 0x08:  # Backspace：清除
            self.done = True
            self.callback("")
            self._close()
            return
        if not is_safe_binding(mods, hit):
            self.var.set("需加 Ctrl/Alt/Shift（或改用 F1-F12）")
            self.after(30, self._tick)
            return

        self.done = True
        self.callback(format_combo(mods, hit))
        self._close()


# ----------------------------------------------------------------------------
# 秘籍编辑对话框
# ----------------------------------------------------------------------------
class CheatDialog(tk.Toplevel):
    GROUPS = ["武器", "生存", "通缉", "载具", "改装", "交通", "天气", "市民", "自定义"]

    def __init__(self, master, app: "CheatApp", cheat: dict | None):
        super().__init__(master)
        self.app = app
        self.result: dict | None = None
        self.cheat = cheat or {}
        self.hotkey = self.cheat.get("hotkey", "")

        self.title("编辑秘籍" if cheat else "添加秘籍")
        self.resizable(False, False)
        self.transient(master)
        bind_dialog_keys(self, self._on_cancel)      # 1.8-G
        self.configure(bg="#f5f6f8")
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        body = tk.Frame(self, bg="#ffffff", padx=22, pady=18,
                        highlightthickness=1, highlightbackground="#e3e7ee")
        body.pack(fill="both", expand=True, padx=12, pady=12)
        body.columnconfigure(1, weight=1)

        self.var_name = tk.StringVar(value=self.cheat.get("name", ""))
        self.var_code = tk.StringVar(value=self.cheat.get("code", ""))
        self.var_hot = tk.StringVar(value=self.hotkey or "（未绑定）")
        self.var_group = tk.StringVar(value=self.cheat.get("group", "自定义"))
        self.var_note = tk.StringVar(value=self.cheat.get("note", ""))

        rows = [
            ("名称", tk.Entry(body, textvariable=self.var_name, font=("Microsoft YaHei UI", 10))),
            ("秘籍代码", tk.Entry(body, textvariable=self.var_code, font=("Consolas", 12, "bold"))),
            ("分组", ttk.Combobox(body, textvariable=self.var_group, values=self.GROUPS,
                                 font=("Microsoft YaHei UI", 10))),
            ("备注", tk.Entry(body, textvariable=self.var_note, font=("Microsoft YaHei UI", 10))),
        ]
        for i, (label, widget) in enumerate(rows):
            tk.Label(body, text=label, bg="#ffffff", fg="#374151",
                     font=("Microsoft YaHei UI", 10)).grid(row=i, column=0, sticky="w", pady=7, padx=(0, 12))
            widget.grid(row=i, column=1, sticky="ew", pady=7, ipady=3)

        # 快捷键行
        r = len(rows)
        tk.Label(body, text="快捷键", bg="#ffffff", fg="#374151",
                 font=("Microsoft YaHei UI", 10)).grid(row=r, column=0, sticky="w", pady=7, padx=(0, 12))
        hk = tk.Frame(body, bg="#ffffff")
        hk.grid(row=r, column=1, sticky="ew", pady=7)
        self.hot_entry = tk.Entry(hk, textvariable=self.var_hot, state="readonly",
                                  font=("Consolas", 11), readonlybackground="#f9fafb")
        self.hot_entry.pack(side="left", fill="x", expand=True, ipady=3)
        ttk.Button(hk, text="捕获", width=7, command=self._capture).pack(side="left", padx=(8, 0))
        ttk.Button(hk, text="清除", width=7, command=self._clear_hot).pack(side="left", padx=(6, 0))

        hint = tk.Label(body, text="代码只填字母/数字（区分大小写无关，游戏内不区分）。"
                                   "例：ASPIRINE",
                        bg="#ffffff", fg="#9aa3ae", font=("Microsoft YaHei UI", 9))
        hint.grid(row=r + 1, column=1, sticky="w")

        # 单条速度覆盖（1.6）：默认跟随全局，个别秘籍可单独放慢
        own = int(self.cheat.get("interval_ms") or 0)
        self.var_follow = tk.BooleanVar(value=own <= 0)
        self.var_interval = tk.IntVar(
            value=own or int((getattr(app, "settings", {}) or {}).get("char_interval_ms", 45)))
        row_s = r + 2
        tk.Label(body, text="发送间隔", bg="#ffffff", fg="#374151",
                 font=("Microsoft YaHei UI", 10)).grid(row=row_s, column=0, sticky="w", pady=7, padx=(0, 12))
        spd = tk.Frame(body, bg="#ffffff")
        spd.grid(row=row_s, column=1, sticky="ew", pady=7)
        self.spin_interval = ttk.Spinbox(spd, from_=20, to=300, increment=5, width=6,
                                         textvariable=self.var_interval)
        self.spin_interval.pack(side="left")
        tk.Label(spd, text="ms / 字", bg="#ffffff", fg="#6b7280",
                 font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(6, 0))
        ttk.Checkbutton(spd, text="跟随全局", variable=self.var_follow,
                        command=self._sync_interval).pack(side="left", padx=(12, 0))
        self._sync_interval()

        bar = tk.Frame(self, bg="#ffffff")
        bar.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(bar, text="保存", style="Accent.TButton", command=self._on_ok).pack(side="right")
        ttk.Button(bar, text="取消", command=self._on_cancel).pack(side="right", padx=(0, 8))

        self.var_name.trace_add("write", lambda *_: None)
        self.bind("<Escape>", lambda e: self._on_cancel())
        self.update_idletasks()
        w = 520
        h = self.winfo_reqheight()
        x = master.winfo_rootx() + (master.winfo_width() - w) // 2
        y = master.winfo_rooty() + (master.winfo_height() - h) // 3
        self.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")
        self.grab_set()
        (body.winfo_children()[1]).focus_set()

    def _capture(self):
        HotkeyCapture(self, self.hotkey, self._set_hot)

    def _sync_interval(self):
        self.spin_interval.configure(state="disabled" if self.var_follow.get() else "normal")

    def _set_hot(self, combo: str):
        self.hotkey = combo
        self.var_hot.set(combo or "（未绑定）")

    def _clear_hot(self):
        self._set_hot("")

    def _on_cancel(self):
        self.result = None
        self.destroy()

    def _on_ok(self):
        name = self.var_name.get().strip()
        code = re.sub(r"\s+", "", self.var_code.get()).upper()
        if not name:
            messagebox.showwarning("缺少名称", "请给这条秘籍起个名字。", parent=self)
            return
        if not re.fullmatch(r"[A-Z0-9]{2,40}", code):
            messagebox.showwarning("代码不合法",
                                   "秘籍代码只能是字母或数字（2~40 位），请检查是否含空格或符号。",
                                   parent=self)
            return
        if self.hotkey:
            parsed = parse_combo(self.hotkey)
            if parsed and not is_safe_binding(*parsed):
                messagebox.showwarning("快捷键不安全",
                                       "无修饰键的单键会拦截正常打字，请加 Ctrl/Alt/Shift 或改用 F1-F12。",
                                       parent=self)
                return
        interval = 0
        if not self.var_follow.get():
            try:
                interval = int(self.var_interval.get())
            except (tk.TclError, ValueError):
                interval = -1
            if not 20 <= interval <= 300:
                messagebox.showwarning("间隔不合法", "单条发送间隔需在 20–300 ms 之间。", parent=self)
                return
        self.result = {
            "id": self.cheat.get("id") or uuid.uuid4().hex[:8],
            "name": name,
            "code": code,
            "hotkey": self.hotkey.strip(),
            "group": (self.var_group.get() or "自定义").strip(),
            "note": self.var_note.get().strip(),
            "interval_ms": interval,
            # 1.9：编辑时保留模板 / 来源包 / 验证标记，别把"未实机验证"洗成"已验证"
            "verified": bool(self.cheat.get("verified", True)),
            "game": str(self.cheat.get("game") or ""),
            "source_pack": str(self.cheat.get("source_pack") or ""),
        }
        self.destroy()


# ----------------------------------------------------------------------------
# 1.8 游戏切换规则编辑对话框
# ----------------------------------------------------------------------------
class GameRuleDialog(tk.Toplevel):
    def __init__(self, master, app: "CheatApp", rule: dict | None):
        super().__init__(master)
        self.app = app
        self.result: dict | None = None
        rule = rule or {}
        self.title("编辑切换规则" if rule else "添加切换规则")
        self.resizable(False, False)
        self.transient(master)
        bind_dialog_keys(self)                       # 1.8-G
        self.configure(bg="#f5f6f8")
        self.grab_set()

        body = tk.Frame(self, bg="#ffffff", padx=20, pady=16)
        body.pack(fill="both", expand=True, padx=12, pady=12)
        body.columnconfigure(1, weight=1)

        self.var_name = tk.StringVar(value=rule.get("name", ""))
        self.var_type = tk.StringVar(value=rule.get("match_type", "exe"))
        self.var_pattern = tk.StringVar(value=rule.get("pattern", ""))
        self.var_profile = tk.StringVar(value=rule.get("profile") or app.active_profile)
        self.var_enabled = tk.BooleanVar(value=bool(rule.get("enabled", True)))

        names = [p["name"] for p in app.store["profiles"]]
        rows = [
            ("规则名称", tk.Entry(body, textvariable=self.var_name,
                                  font=("Microsoft YaHei UI", 10))),
            ("匹配方式", ttk.Combobox(body, textvariable=self.var_type, state="readonly",
                                      values=["exe", "title"], width=10)),
            ("匹配内容", tk.Entry(body, textvariable=self.var_pattern, font=("Consolas", 11))),
            ("目标方案", ttk.Combobox(body, textvariable=self.var_profile, state="readonly",
                                      values=names)),
        ]
        for i, (label, widget) in enumerate(rows):
            tk.Label(body, text=label, bg="#ffffff", fg="#374151",
                     font=("Microsoft YaHei UI", 10)).grid(row=i, column=0, sticky="w",
                                                           pady=6, padx=(0, 12))
            widget.grid(row=i, column=1, sticky="ew", pady=6, ipady=3)
        ttk.Checkbutton(body, text="启用这条规则", variable=self.var_enabled)\
            .grid(row=len(rows), column=1, sticky="w", pady=(8, 0))
        tk.Label(body, text="exe = 按进程名匹配（推荐，如 gta-vc）；\n"
                            "title = 按窗口标题匹配（易误判浏览器标签，慎用）。",
                 bg="#ffffff", fg="#6b7280", justify="left",
                 font=("Microsoft YaHei UI", 9)).grid(row=len(rows) + 1, column=0,
                                                      columnspan=2, sticky="w", pady=(10, 0))

        btns = tk.Frame(self, bg="#f5f6f8")
        btns.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(btns, text="确定", style="Accent.TButton", command=self._ok).pack(side="right")
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right", padx=(0, 8))
        self.update_idletasks()
        self.geometry(f"+{master.winfo_rootx() + 80}+{master.winfo_rooty() + 80}")

    def _ok(self):
        pattern = self.var_pattern.get().strip()
        if not pattern:
            messagebox.showwarning("缺少内容", "请填写匹配内容（进程名或标题关键字）。", parent=self)
            return
        profile = self.var_profile.get().strip()
        if not profile:
            messagebox.showwarning("缺少方案", "请选择命中后要切换到的方案。", parent=self)
            return
        self.result = {
            "name": self.var_name.get().strip() or pattern,
            "match_type": self.var_type.get(),
            "pattern": pattern,
            "profile": profile,
            "enabled": bool(self.var_enabled.get()),
        }
        self.destroy()


# ----------------------------------------------------------------------------
# 1.8 设置对话框（常规 / 输入 / 游戏 / 数据）
# ----------------------------------------------------------------------------
class SettingsDialog(tk.Toplevel):
    def __init__(self, master, app: "CheatApp"):
        super().__init__(master)
        self.app = app
        self.title(f"设置 — {APP_NAME}")
        self.configure(bg=C["bg"])
        self.transient(master)
        bind_dialog_keys(self, self._close)          # 1.8-G：Esc 关窗也要保存设置
        self.geometry(f"{int(640 * app.ui)}x{int(500 * app.ui)}")
        self.protocol("WM_DELETE_WINDOW", self._close)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        nb.add(self._page_general(nb), text="  常规  ")
        nb.add(self._page_input(nb), text="  输入  ")
        nb.add(self._page_games(nb), text="  游戏  ")
        nb.add(self._page_data(nb), text="  数据  ")
        ttk.Button(self, text="关闭", command=self._close).pack(pady=(2, 10))

    def _close(self):
        self.app._on_setting_change()
        self.destroy()

    def _page(self, nb):
        frm = ttk.Frame(nb, padding=18)
        return frm

    # -- 常规 ---------------------------------------------------------------
    def _page_general(self, nb):
        frm = self._page(nb)
        ttk.Checkbutton(frm, text="游戏内悬浮提示（发送结果显示在右下角，不抢焦点）",
                        variable=self.app.var_toast,
                        command=self.app._on_setting_change).pack(anchor="w", pady=4)
        ttk.Checkbutton(frm, text="关闭窗口时最小化到托盘（取消勾选 = 关闭即退出）",
                        variable=self.app.var_tray,
                        command=self.app._on_setting_change).pack(anchor="w", pady=4)
        ttk.Checkbutton(frm, text="按游戏自动切换方案（规则在「游戏」页配置）",
                        variable=self.app.var_auto_switch,
                        command=self.app._on_setting_change).pack(anchor="w", pady=4)
        ttk.Checkbutton(frm, text="启用扩展点（前置/后置钩子，高级功能，默认关闭）",
                        variable=self.app.var_hooks,
                        command=self.app._on_setting_change).pack(anchor="w", pady=4)

        box = ttk.LabelFrame(frm, text=" 全局暂停热键 ", padding=12)
        box.pack(fill="x", pady=(14, 0))
        row = ttk.Frame(box)
        row.pack(fill="x")
        self.var_pause = tk.StringVar(value=self.app.settings.get("pause_hotkey", ""))
        tk.Entry(row, textvariable=self.var_pause, state="readonly", width=18,
                 font=("Consolas", 11), readonlybackground="#f9fafb").pack(side="left", ipady=3)
        ttk.Button(row, text="捕获", width=7, command=self._capture_pause).pack(side="left", padx=(8, 0))
        ttk.Label(box, text="在任何窗口按这个键可一键暂停/恢复全部秘籍热键。",
                  style="Muted.TLabel").pack(anchor="w", pady=(8, 0))

        box2 = ttk.LabelFrame(frm, text=" 维护 ", padding=12)
        box2.pack(fill="x", pady=(14, 0))
        ttk.Button(box2, text="重新运行首次启动向导", command=self.app.open_wizard)\
            .pack(side="left", padx=(0, 8))
        ttk.Button(box2, text="环境诊断", command=self.app.run_diagnose).pack(side="left")
        ttk.Button(box2, text="以管理员身份重启", command=self.app.relaunch_as_admin)\
            .pack(side="left", padx=(8, 0))
        return frm

    def _capture_pause(self):
        HotkeyCapture(self, self.var_pause.get(), self._set_pause)

    def _set_pause(self, combo: str):
        if combo:
            self.var_pause.set(combo)
            self.app.settings["pause_hotkey"] = combo
            self.app.persist()
            self.app.apply_hotkeys()
            self.app.log(f"全局暂停热键已改为 {combo}。", "ok")

    # -- 输入 ---------------------------------------------------------------
    def _page_input(self, nb):
        frm = self._page(nb)
        app = self.app
        box = ttk.LabelFrame(frm, text=" 目标窗口 ", padding=12)
        box.pack(fill="x")
        row = ttk.Frame(box)
        row.pack(fill="x")
        tk.Label(row, text="窗口关键字（逗号分隔）", bg=C["panel"], fg=C["muted"],
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        # FocusOut 必须绑在真正拿焦点的控件上：绑到容器 Frame 上永远不会触发，
        # 结果就是「改了关键字/间隔、没点别处就关窗」时设置不落盘（1.9.1 修）。
        ent_kw = tk.Entry(row, textvariable=app.var_kw, width=26, relief="flat", bg="#f9fafb",
                          highlightthickness=1, highlightbackground=C["line"],
                          highlightcolor=C["accent"])
        ent_kw.pack(side="left", padx=(8, 8), ipady=3)
        ent_kw.bind("<FocusOut>", lambda e: app._on_setting_change())
        ent_kw.bind("<Return>", lambda e: app._on_setting_change())
        ttk.Button(row, text="拾取当前窗口", command=app.pick_window).pack(side="left")
        ttk.Checkbutton(box, text="仅当目标窗口在前台时才发送（强烈建议开启）",
                        variable=app.var_fg, command=app._on_setting_change)\
            .pack(anchor="w", pady=(8, 0))
        ttk.Checkbutton(box, text="发送时绕开中文输入法（中文 IME 会吞掉注入的字符）",
                        variable=app.var_ime, command=app._on_setting_change)\
            .pack(anchor="w", pady=2)

        box2 = ttk.LabelFrame(frm, text=" 发送速度 ", padding=12)
        box2.pack(fill="x", pady=(14, 0))
        row2 = ttk.Frame(box2)
        row2.pack(fill="x")
        tk.Label(row2, text="每字间隔 (ms)", bg=C["panel"], fg=C["muted"],
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        sp_delay = ttk.Spinbox(row2, from_=20, to=300, increment=5, width=7,
                               textvariable=app.var_delay, command=app._on_setting_change)
        sp_delay.pack(side="left", padx=(8, 0))
        sp_delay.bind("<FocusOut>", lambda e: app._on_setting_change())
        ttk.Button(box2, text="套用「经典版」预设", width=16,
                   command=lambda: app.apply_preset("经典版")).pack(side="left", padx=(0, 8), pady=(8, 0))
        ttk.Button(box2, text="套用「决定版」预设", width=16,
                   command=lambda: app.apply_preset("决定版")).pack(side="left", pady=(8, 0))
        ttk.Label(box2, text="丢字 → 调大间隔；输入太慢 → 调小。单条秘籍可在编辑对话框里单独覆盖。",
                  style="Muted.TLabel").pack(anchor="w", pady=(6, 0))

        box3 = ttk.LabelFrame(frm, text=" 快捷键与自检 ", padding=12)
        box3.pack(fill="x", pady=(14, 0))
        ttk.Button(box3, text="重新注册全部快捷键", command=app.apply_hotkeys)\
            .pack(side="left", padx=(0, 8))
        ttk.Button(box3, text="快捷键总览", command=app.open_hotkey_overview).pack(side="left")
        ttk.Button(box3, text="注入自检", command=app.open_test_window)\
            .pack(side="left", padx=(8, 0))
        return frm

    # -- 游戏（自动切方案规则表） ---------------------------------------------
    def _page_games(self, nb):
        frm = self._page(nb)
        ttk.Label(frm, text="游戏窗口在前台且稳定 0.8 秒后，自动切换到规则指定的方案。\n"
                            "推荐按进程名（exe）匹配；发送过程中绝不切换。",
                  style="Muted.TLabel", justify="left").pack(anchor="w", pady=(0, 8))

        wrap = tk.Frame(frm, bg=C["panel"], highlightthickness=1, highlightbackground=C["line"])
        wrap.pack(fill="both", expand=True)
        cols = ("name", "match", "pattern", "profile", "enabled")
        self.games_tree = ttk.Treeview(wrap, columns=cols, show="headings", height=7)
        for key, (text, width, anchor) in {
            "name": ("规则名称", 120, "w"), "match": ("方式", 60, "center"),
            "pattern": ("匹配内容", 140, "w"), "profile": ("目标方案", 110, "w"),
            "enabled": ("启用", 50, "center")}.items():
            self.games_tree.heading(key, text=text)
            self.games_tree.column(key, width=width, anchor=anchor)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.games_tree.yview)
        self.games_tree.configure(yscrollcommand=vsb.set)
        self.games_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.games_tree.bind("<Double-1>", lambda e: self._edit_rule())

        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="添加", command=self._add_rule).pack(side="left")
        ttk.Button(btns, text="编辑", command=self._edit_rule).pack(side="left", padx=(6, 0))
        ttk.Button(btns, text="删除", command=self._del_rule).pack(side="left", padx=(6, 0))
        self._reload_games()

        # 2.0：通用目标规则（配置驱动，优先级高于 games）
        tbox = ttk.LabelFrame(frm, text=" 目标规则（v2.0，配置驱动） ", padding=10)
        tbox.pack(fill="x", pady=(10, 0))
        self.lbl_targets = ttk.Label(tbox, text="", style="Muted.TLabel", justify="left")
        self.lbl_targets.pack(anchor="w")
        trow = ttk.Frame(tbox)
        trow.pack(fill="x", pady=(6, 0))
        ttk.Button(trow, text="从 games 规则生成 targets", command=self._migrate_targets)\
            .pack(side="left")
        self._reload_targets_info()
        return frm

    def _reload_targets_info(self):
        targets = self.app.store.get("targets") or []
        self.lbl_targets.configure(
            text=f"当前 {len(targets)} 条通用目标规则"
                 + (f"（示例：{targets[0]['name']} → {targets[0]['match_type']}:"
                    f"{targets[0]['pattern']}）" if targets else "")
                 + "\n非空时优先于上方 games 规则；可带方案 / 发送策略 / IME 策略 / 前台要求。"
                 + "\n更多字段见 docs/PACK-FORMAT.md 与 CLI：python -m vcct.cli targets")

    def _migrate_targets(self):
        app = self.app
        converted = targets_from_games(app.store.get("games") or [])
        if not converted:
            messagebox.showinfo("没有可迁移的规则", "请先在上方添加 games 规则。", parent=self)
            return
        existing = list(app.store.get("targets") or [])
        names = {t["name"] for t in existing}
        added = [t for t in converted if t["name"] not in names]
        if not added:
            messagebox.showinfo("无需迁移", "这些 games 规则都已存在对应的目标规则。", parent=self)
            return
        app.store["targets"] = existing + added
        app.persist()
        self._reload_targets_info()
        app.log(f"已生成 {len(added)} 条通用目标规则（targets），优先级高于 games。", "ok")

    def _reload_games(self):
        self.games_tree.delete(*self.games_tree.get_children())
        for i, g in enumerate(self.app.store.get("games") or []):
            self.games_tree.insert("", "end", iid=str(i), values=(
                g["name"], "进程" if g["match_type"] == "exe" else "标题",
                g["pattern"], g["profile"], "✔" if g["enabled"] else "—"))

    def _add_rule(self):
        dlg = GameRuleDialog(self, self.app, None)
        self.wait_window(dlg)
        if dlg.result:
            self.app.store.setdefault("games", []).append(dlg.result)
            self.app.persist()
            self._reload_games()
            self.app.log(f"已添加自动切换规则「{dlg.result['name']}」→「{dlg.result['profile']}」。", "ok")

    def _edit_rule(self):
        sel = self.games_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        games = self.app.store.get("games") or []
        if idx >= len(games):
            return
        dlg = GameRuleDialog(self, self.app, games[idx])
        self.wait_window(dlg)
        if dlg.result:
            games[idx] = dlg.result
            self.app.persist()
            self._reload_games()

    def _del_rule(self):
        sel = self.games_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        games = self.app.store.get("games") or []
        if idx < len(games):
            rule = games.pop(idx)
            self.app.persist()
            self._reload_games()
            self.app.log(f"已删除切换规则「{rule['name']}」。", "info")

    # -- 数据 ---------------------------------------------------------------
    def _page_data(self, nb):
        frm = self._page(nb)
        app = self.app
        box = ttk.LabelFrame(frm, text=" 方案管理 ", padding=12)
        box.pack(fill="x")
        grid = ttk.Frame(box)
        grid.pack()
        items = [("新建副本", app.new_profile), ("重命名", app.rename_profile),
                 ("删除当前方案", app.delete_profile), ("导出方案", app.export_profile),
                 ("导入方案…", app.import_profile), ("导出整包", app.export_bundle),
                 ("导入整包…", app.import_bundle), ("从备份恢复", app.restore_backup)]
        for i, (text, cmd) in enumerate(items):
            ttk.Button(grid, text=text, width=14, command=cmd)\
                .grid(row=i // 3, column=i % 3, sticky="w", padx=4, pady=4)

        box2 = ttk.LabelFrame(frm, text=" 使用统计 ", padding=12)
        box2.pack(fill="x", pady=(14, 0))
        ttk.Label(box2, text=f"今日已发送 {app.today_count()} 次（按秘籍代码累计）",
                  style="Muted.TLabel").pack(side="left")
        ttk.Button(box2, text="清空统计", command=app.clear_stats).pack(side="right")

        box3 = ttk.LabelFrame(frm, text=" 配置与日志 ", padding=12)
        box3.pack(fill="x", pady=(14, 0))
        ttk.Label(box3, text=f"配置文件：{data_path()}", style="Muted.TLabel").pack(anchor="w")
        ttk.Label(box3, text=f"日志文件：{log_file()}", style="Muted.TLabel").pack(anchor="w", pady=(2, 6))
        ttk.Button(box3, text="打开日志目录", command=app.open_log).pack(side="left")
        ttk.Button(box3, text="发送历史", command=app.open_history).pack(side="left", padx=(8, 0))
        ttk.Button(box3, text="恢复默认秘籍表", command=app.reset_defaults).pack(side="left", padx=(8, 0))
        return frm


# ----------------------------------------------------------------------------
# 1.8 首次启动向导（3 步，可跳过）
# ----------------------------------------------------------------------------
class OnboardWizard(tk.Toplevel):
    def __init__(self, app: "CheatApp"):
        super().__init__(app.root)
        self.app = app
        self.title(f"欢迎使用 {APP_NAME}")
        self.configure(bg=C["bg"])
        self.resizable(False, False)
        self.transient(app.root)
        bind_dialog_keys(self, self._skip)           # 1.8-G：Esc = 跳过向导
        self.protocol("WM_DELETE_WINDOW", self._skip)
        self.step = 0
        self.var_preset = tk.StringVar(value="经典版")
        self.var_rule = tk.BooleanVar(value=True)
        self.probe_ok: bool | None = None

        wrap = tk.Frame(self, bg=C["bg"], padx=26, pady=20)
        wrap.pack(fill="both", expand=True)
        self.lbl_title = tk.Label(wrap, text="", bg=C["bg"], fg=C["text"],
                                  font=("Microsoft YaHei UI", 14, "bold"), justify="left")
        self.lbl_title.pack(anchor="w")
        self.body = tk.Frame(wrap, bg=C["bg"])
        self.body.pack(fill="both", expand=True, pady=(12, 0))
        self.btns = tk.Frame(wrap, bg=C["bg"])
        self.btns.pack(fill="x", pady=(18, 0))

        self._show(0)
        self.update_idletasks()
        self.grab_set()
        w, h = 520, 420
        x = app.root.winfo_rootx() + (app.root.winfo_width() - w) // 2
        y = app.root.winfo_rooty() + (app.root.winfo_height() - h) // 3
        self.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")

    # -- 步骤渲染 -------------------------------------------------------------
    def _show(self, step: int):
        self.step = step
        for w in self.body.winfo_children():
            w.destroy()
        for w in self.btns.winfo_children():
            w.destroy()
        if step == 0:
            self._page_preset()
        elif step == 1:
            self._page_verify()
        else:
            self._page_conflicts()

    def _nav(self, back_text=None, back_cmd=None, next_text="下一步 →", next_cmd=None,
             next_style="TButton"):
        if back_text:
            ttk.Button(self.btns, text=back_text, command=back_cmd).pack(side="left")
        ttk.Button(self.btns, text="跳过向导", command=self._skip).pack(side="right")
        ttk.Button(self.btns, text=next_text, style=next_style, command=next_cmd)\
            .pack(side="right", padx=(0, 10))

    def _page_preset(self):
        self.lbl_title.configure(text="第 1 步 / 3：选一套发送参数")
        tk.Label(self.body, text="经典版适配 GTA VC 原版（30fps 帧轮询，默认推荐）；\n"
                                 "决定版（Unreal 引擎）输入窗口更宽，整体放慢一档。\n"
                                 "之后可在 设置 → 输入 随时改。",
                 bg=C["bg"], fg="#374151", justify="left",
                 font=("Microsoft YaHei UI", 10)).pack(anchor="w")
        box = tk.Frame(self.body, bg=C["bg"])
        box.pack(anchor="w", pady=(14, 0))
        for name in ("经典版", "决定版"):
            tk.Radiobutton(box, text=name, variable=self.var_preset, value=name,
                           bg=C["bg"], font=("Microsoft YaHei UI", 11),
                           selectcolor="#ffffff").pack(anchor="w", pady=2)
        ttk.Checkbutton(self.body, text="游戏在前台时自动启用这套参数"
                                        "（按进程 gta-vc 识别，可稍后在 设置 → 游戏 修改）",
                        variable=self.var_rule).pack(anchor="w", pady=(14, 0))
        self._nav(next_text="下一步 →", next_cmd=lambda: self._show(1))

    def _page_verify(self):
        self.lbl_title.configure(text="第 2 步 / 3：验证按键能送达")
        app = self.app
        hk = next((c["hotkey"] for c in app.cheats if c["hotkey"]), "（未绑定）")
        tk.Label(self.body, text=f"当前方案「{app.active_profile}」的第一个热键是 {hk}。\n\n"
                                 "先跑一次注入自检（约 1 秒，会短暂抢一下前台）：",
                 bg=C["bg"], fg="#374151", justify="left",
                 font=("Microsoft YaHei UI", 10)).pack(anchor="w")
        row = tk.Frame(self.body, bg=C["bg"])
        row.pack(anchor="w", pady=(12, 0))
        ttk.Button(row, text="▶ 运行注入自检", command=self._run_probe).pack(side="left")
        self.lbl_probe = tk.Label(row, text="", bg=C["bg"], fg=C["muted"],
                                  font=("Microsoft YaHei UI", 10))
        self.lbl_probe.pack(side="left", padx=(12, 0))
        if self.probe_ok is not None:
            self._show_probe_result()
        tk.Label(self.body, text="提示：若游戏以管理员身份运行，本工具也需要管理员权限\n"
                                 "（否则 Windows 会静默丢弃按键，右上角会出红色告警）。",
                 bg=C["bg"], fg="#6b7280", justify="left",
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(16, 0))
        self._nav(back_text="← 上一步", back_cmd=lambda: self._show(0),
                  next_text="下一步 →", next_cmd=lambda: self._show(2))

    def _run_probe(self):
        self.lbl_probe.configure(text="自检中…")
        app = self.app

        def worker():
            try:
                got_fg, got = raw_char_probe("VCCT")
                ok = bool(got_fg and got.strip().upper() == "VCCT")
            except Exception:
                ok = False
            app.root.after(0, lambda: self._probe_done(ok))

        threading.Thread(target=worker, daemon=True).start()

    def _probe_done(self, ok: bool):
        self.probe_ok = ok
        self._show_probe_result()

    def _show_probe_result(self):
        if self.probe_ok:
            self.lbl_probe.configure(text="✔ 注入链路正常", foreground=C["ok"])
        else:
            self.lbl_probe.configure(
                text="✖ 未能收到字符（不影响试用，可点「⋯ 更多 → 环境诊断」定位）",
                foreground=C["warn"])

    def _page_conflicts(self):
        self.lbl_title.configure(text="第 3 步 / 3：快捷键冲突检查")
        conflicts = {k: v for k, v in self.app.conflicts.items()}
        if conflicts:
            names = []
            for cid, reason in conflicts.items():
                c = self.app.by_id(cid)
                names.append(f"· {c['name'] if c else cid}：{reason}")
            text = "\n".join(names[:8])
            tk.Label(self.body, text=f"检测到 {len(conflicts)} 个快捷键不可用：\n\n{text}",
                     bg=C["bg"], fg=C["warn"], justify="left",
                     font=("Microsoft YaHei UI", 10)).pack(anchor="w")
            ttk.Button(self.body, text="自动分配可用键", command=self._auto_fix)\
                .pack(anchor="w", pady=(12, 0))
        else:
            tk.Label(self.body, text="✔ 没有冲突，全部快捷键已就绪。\n\n"
                                     "切到游戏窗口按热键即可触发秘籍。",
                     bg=C["bg"], fg=C["ok"], justify="left",
                     font=("Microsoft YaHei UI", 11)).pack(anchor="w")
        ttk.Button(self.body, text="↻ 重新检测", command=self._redetect).pack(anchor="w", pady=(10, 0))
        self._nav(back_text="← 上一步", back_cmd=lambda: self._show(1),
                  next_text="完成 ✔", next_cmd=self._finish, next_style="Accent.TButton")

    def _redetect(self):
        self.app.apply_hotkeys()
        self.after(400, lambda: self._show(2))

    def _auto_fix(self):
        ids = [cid for cid in self.app.conflicts if cid != PAUSE_ID]
        if ids:
            self.app._assign_free_combos(ids)
        self.after(600, lambda: self._show(2))

    def _finish(self):
        app = self.app
        app.settings["onboarded"] = True
        if self.var_rule.get():
            games = app.store.setdefault("games", [])
            if not any(g["match_type"] == "exe" and g["pattern"] == "gta-vc" for g in games):
                games.append({"name": "GTA VC", "match_type": "exe", "pattern": "gta-vc",
                              "profile": app.active_profile, "enabled": True})
            app.settings["auto_switch"] = True
        app._on_setting_change()
        app.log("向导完成。切到游戏窗口按热键即可；设置里可随时调整全部选项。", "ok")
        self.destroy()

    def _skip(self):
        self.app.settings["onboarded"] = True
        self.app.persist()
        self.destroy()


# ----------------------------------------------------------------------------
# 1.8 快捷键总览面板
# ----------------------------------------------------------------------------
class HotkeyOverview(tk.Toplevel):
    def __init__(self, app: "CheatApp"):
        super().__init__(app.root)
        self.app = app
        self.title("快捷键总览")
        self.configure(bg=C["bg"])
        self.transient(app.root)
        bind_dialog_keys(self)                       # 1.8-G
        self.geometry(f"{int(720 * app.ui)}x{int(460 * app.ui)}")

        wrap = tk.Frame(self, bg=C["panel"], highlightthickness=1, highlightbackground=C["line"])
        wrap.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        cols = ("name", "profile", "hotkey", "state", "note")
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings")
        for key, (text, width, anchor) in {
            "name": ("条目", 200, "w"), "profile": ("所属方案", 110, "w"),
            "hotkey": ("快捷键", 120, "center"), "state": ("状态", 150, "center"),
            "note": ("说明", 260, "w")}.items():
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, anchor=anchor, stretch=(key in ("name", "note")))
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.tag_configure("conflict", foreground=C["warn"])
        self.tree.tag_configure("idle", foreground="#98a2b3")

        btns = ttk.Frame(self)   # ttk 不接受 bg=，颜色由 style 统一继承
        btns.pack(fill="x", padx=12, pady=(2, 10))
        ttk.Button(btns, text="↻ 重新检测占用", command=self._redetect).pack(side="left")
        ttk.Button(btns, text="导出为文本…", command=self._export).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="关闭", command=self.destroy).pack(side="right")

        self.reload()
        self._ticker()

    def _ticker(self):
        """发送注册结果走事件泵，异步到达——开着窗口时周期刷新即可。"""
        if self.winfo_exists():
            self.reload()
            self.after(800, self._ticker)

    def reload(self):
        app = self.app
        # 1.9.1：周期重建表格前记住选中项与滚动位置，否则每 800ms 刷新一次
        # 会把用户刚点中的行又清空，导出/复制时尤其恼人。
        keep = list(self.tree.selection())
        try:
            yview = self.tree.yview()[0]
        except Exception:
            yview = 0.0
        self.tree.delete(*self.tree.get_children())
        pause_combo = app.settings.get("pause_hotkey", "")
        if app.paused:
            state = "⏸ 已暂停（仅本键生效）"
        elif PAUSE_ID in app.conflicts:
            state = f"✖ {app.conflicts[PAUSE_ID]}"
        else:
            state = "✔ 生效"
        self.tree.insert("", "end", iid="__pause__",
                         values=("全局暂停键", "全局", pause_combo, state,
                                 "一键注销/恢复全部秘籍热键"),
                         tags=("conflict",) if "✖" in state else ())
        for prof in app.store["profiles"]:
            active = prof["name"] == app.active_profile
            for c in prof["cheats"]:
                if not c["hotkey"]:
                    continue
                iid = f"{prof['name']}:{c['id']}"
                if not active:
                    self.tree.insert("", "end", iid=iid,
                                     values=(c["name"], prof["name"], c["hotkey"],
                                             "未注册（切到该方案时生效）", c["note"]),
                                     tags=("idle",))
                    continue
                if c["id"] in app.conflicts:
                    state = f"✖ {app.conflicts[c['id']]}"
                    tags = ("conflict",)
                else:
                    state = "✔ 生效"
                    tags = ()
                self.tree.insert("", "end", iid=iid,
                                 values=(c["name"], prof["name"], c["hotkey"],
                                         state, c["note"]), tags=tags)
        alive = [i for i in keep if self.tree.exists(i)]
        if alive:
            self.tree.selection_set(*alive)
            self.tree.see(alive[0])
        else:
            self.tree.yview_moveto(yview)

    def _redetect(self):
        self.app.apply_hotkeys()
        self.app.log("正在重新检测快捷键占用…", "info")

    def _export(self):
        path = filedialog.asksaveasfilename(
            title="导出快捷键总览", defaultextension=".txt",
            initialfile="hotkeys.txt", filetypes=[("文本", "*.txt")], parent=self)
        if not path:
            return
        lines = [f"{APP_NAME} v{APP_VER} 快捷键总览（{time.strftime('%Y-%m-%d %H:%M')}）", ""]
        for item in self.tree.get_children():
            vals = self.tree.item(item, "values")
            lines.append(f"{vals[0]}\t[{vals[1]}]\t{vals[2]}\t{vals[3]}"
                         + (f"\t{vals[4]}" if vals[4] else ""))
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
            self.app.log(f"快捷键总览已导出：{path}", "ok")
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc), parent=self)


# ----------------------------------------------------------------------------
# 1.9 秘籍包管理（导入 diff 预览 / 导出 .vcpack / 已安装记录）
# ----------------------------------------------------------------------------
class PackManagerDialog(tk.Toplevel):
    def __init__(self, app: "CheatApp"):
        super().__init__(app.root)
        self.app = app
        self.pack: dict | None = None
        self.diff: list[dict] = []
        self.title("秘籍包管理（.vcpack）")
        self.configure(bg=C["bg"])
        self.transient(app.root)
        bind_dialog_keys(self)                       # 1.8-G
        self.geometry(f"{int(720 * app.ui)}x{int(520 * app.ui)}")

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        nb.add(self._page_import(nb), text="  导入包  ")
        nb.add(self._page_export(nb), text="  导出包  ")
        nb.add(self._page_installed(nb), text="  已安装  ")
        ttk.Button(self, text="关闭", command=self.destroy).pack(pady=(2, 10))

    # -- 导入 ---------------------------------------------------------------
    def _page_import(self, nb):
        frm = ttk.Frame(nb, padding=14)
        top = ttk.Frame(frm)
        top.pack(fill="x")
        ttk.Button(top, text="选择 .vcpack / .json 文件…", command=self._choose).pack(side="left")
        self.lbl_file = ttk.Label(top, text="未选择文件", style="Muted.TLabel")
        self.lbl_file.pack(side="left", padx=(10, 0))
        self.lbl_warn = tk.Label(frm, text="", bg=C["bg"], fg=C["warn"],
                                 wraplength=620, justify="left",
                                 font=("Microsoft YaHei UI", 9), anchor="w")
        self.lbl_warn.pack(fill="x", pady=(6, 0))

        wrap = tk.Frame(frm, bg=C["panel"], highlightthickness=1, highlightbackground=C["line"])
        wrap.pack(fill="both", expand=True, pady=(8, 0))
        cols = ("pick", "status", "code", "name", "hotkey", "local")
        self.diff_tree = ttk.Treeview(wrap, columns=cols, show="headings", selectmode="extended")
        for key, (text, width, anchor) in {
            "pick": ("勾选", 46, "center"), "status": ("状态", 80, "center"),
            "code": ("秘籍代码", 170, "w"), "name": ("名称", 130, "w"),
            "hotkey": ("包内热键", 100, "center"), "local": ("本地热键", 100, "center"),
        }.items():
            self.diff_tree.heading(key, text=text)
            self.diff_tree.column(key, width=width, anchor=anchor)
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.diff_tree.yview)
        self.diff_tree.configure(yscrollcommand=vsb.set)
        self.diff_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.diff_tree.tag_configure("conflict", foreground=C["warn"])
        self.diff_tree.tag_configure("same", foreground="#98a2b3")

        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="全选", width=8, command=lambda: self._select_all()).pack(side="left")
        ttk.Button(btns, text="仅选新增", width=11, command=lambda: self._select_status("new"))\
            .pack(side="left", padx=(6, 0))
        ttk.Button(btns, text="清空选择", width=10,
                   command=lambda: self.diff_tree.selection_remove(
                       *self.diff_tree.get_children())).pack(side="left", padx=(6, 0))
        self.var_overwrite = tk.BooleanVar(value=True)
        ttk.Checkbutton(btns, text="冲突项覆盖本地", variable=self.var_overwrite)\
            .pack(side="left", padx=(14, 0))
        self.var_auto_avoid = tk.BooleanVar(value=True)     # 1.9-G
        ttk.Checkbutton(btns, text="自动避让热键冲突", variable=self.var_auto_avoid)\
            .pack(side="left", padx=(10, 0))
        ttk.Button(btns, text="导入所选 →", style="Accent.TButton", command=self._do_import)\
            .pack(side="right")
        return frm

    def _choose(self):
        path = filedialog.askopenfilename(
            title="选择秘籍包", filetypes=[("秘籍包", "*.vcpack *.json"), ("所有文件", "*.*")],
            parent=self)
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except Exception as exc:
            messagebox.showerror("读取失败", str(exc), parent=self)
            return
        pack, warns, err = validate_pack(raw, APP_VER)
        if err:
            self.pack, self.diff = None, []
            self.diff_tree.delete(*self.diff_tree.get_children())
            self.lbl_warn.configure(text=err)
            return
        # 1.9-G 自动避让：只在真冲突时把包内热键改到候选空闲键
        avoid_note = ""
        if self.var_auto_avoid.get():
            pack, changed = auto_avoid_hotkeys(
                pack, self.app.cheats, self.app.settings.get("pause_hotkey", ""))
            if changed:
                pairs = "、".join(f"{x['code']}:{x['old']}→{x['new'] or '留空'}"
                                 for x in changed[:3])
                avoid_note = (f"　｜　自动避让 {len(changed)} 个热键冲突（{pairs}"
                              + ("…" if len(changed) > 3 else "") + "）")
        # 1.9-H 包版本比对（纯本地，不联网）
        status, _old = compare_pack_record(pack, self.app.store.get("packs") or [])
        version_note = {
            "new": "首次导入这个包",
            "upgrade": "检测到同名包的**新版本**，导入后将更新本地记录",
            "changed": "同名包内容与上次导入不同（校验和变化），如非预期请核对",
            "same": "与上次导入的包完全一致（重复导入不会改动数据）",
        }[status]
        self.pack = pack
        self.diff = diff_pack(pack, self.app.cheats)
        self.lbl_file.configure(text=os.path.basename(path))
        self.lbl_warn.configure(text="；".join(warns) or "校验通过")
        self._reload_diff()
        name = pack["name"]
        added = sum(1 for d in self.diff if d["status"] == "new")
        conflict = sum(1 for d in self.diff if d["status"] == "conflict")
        same = sum(1 for d in self.diff if d["status"] == "same")
        self.lbl_warn.configure(text=(self.lbl_warn.cget("text") +
                                     f"　｜　包「{name}」：新增 {added} / 冲突 {conflict} / 相同 {same}"
                                     + avoid_note + f"　｜　{version_note}"))
        self._select_status("new")

    def _reload_diff(self):
        self.diff_tree.delete(*self.diff_tree.get_children())
        labels = {"new": "新增", "conflict": "冲突", "same": "相同"}
        for d in self.diff:
            local = (d["existing"] or {}).get("hotkey") or "—"
            self.diff_tree.insert("", "end", iid=d["code"],
                                 values=("☐", labels[d["status"]], d["code"], d["name"],
                                         d["incoming"].get("hotkey") or "—", local),
                                 tags=(d["status"],) if d["status"] != "new" else ())

    def _select_all(self):
        self.diff_tree.selection_set(*self.diff_tree.get_children())

    def _select_status(self, status: str):
        ids = [d["code"] for d in self.diff if d["status"] == status]
        self.diff_tree.selection_remove(*self.diff_tree.get_children())
        if ids:
            self.diff_tree.selection_set(*ids)

    def _do_import(self):
        if not self.pack:
            return
        codes = list(self.diff_tree.selection())
        if not codes:
            messagebox.showinfo("未选择", "请在差异表里勾选要导入的条目（行可多选）。", parent=self)
            return
        merged, counts = merge_pack(self.app.cheats, self.pack, codes,
                                    overwrite=bool(self.var_overwrite.get()))
        self.app.cheats[:] = merged       # 原地替换，保持与 store 内列表的引用
        packs = self.app.store.setdefault("packs", [])
        rec = pack_record(self.pack)
        packs[:] = [p for p in packs if p.get("name") != rec["name"]] + [rec]
        self.app.persist()
        self.app.refresh_tree()
        self.app.apply_hotkeys()
        self.app.log(f"导入秘籍包「{self.pack['name']}」：新增 {counts['added']} / "
                     f"覆盖 {counts['updated']} / 跳过 {counts['skipped']}。", "ok")
        self._load_installed()
        self.pack, self.diff = None, []
        self.diff_tree.delete(*self.diff_tree.get_children())
        self.lbl_warn.configure(text="导入完成，可继续选择下一个包。")

    # -- 导出 ---------------------------------------------------------------
    def _page_export(self, nb):
        frm = ttk.Frame(nb, padding=18)
        ttk.Label(frm, text="把当前方案的秘籍导出成一个可分享的 .vcpack 文件。",
                  style="Muted.TLabel").pack(anchor="w")
        box = ttk.LabelFrame(frm, text=" 包信息 ", padding=12)
        box.pack(fill="x", pady=(14, 0))
        self.var_name = tk.StringVar(value=f"{self.app.active_profile} · 秘籍包")
        self.var_author = tk.StringVar(value="")
        self.var_game = tk.StringVar(value=self._current_game())
        for i, (label, var) in enumerate((("名称", self.var_name), ("作者", self.var_author),
                                          ("适用游戏", self.var_game))):
            ttk.Label(box, text=label).grid(row=i, column=0, sticky="w", pady=5, padx=(0, 12))
            tk.Entry(box, textvariable=var, width=38).grid(row=i, column=1, sticky="ew", pady=5)
        ttk.Button(frm, text="导出为 .vcpack…", style="Accent.TButton",
                   command=self._do_export).pack(anchor="w", pady=(18, 0))
        ttk.Label(frm, text=f"当前方案「{self.app.active_profile}」共 {len(self.app.cheats)} 条；"
                            "包内含 sha256 校验，手工修改后仍可导入（会提示校验不符）。",
                  style="Muted.TLabel", wraplength=560, justify="left").pack(anchor="w", pady=(12, 0))
        return frm

    def _current_game(self) -> str:
        prof = next((p for p in self.app.store["profiles"]
                     if p["name"] == self.app.active_profile), {})
        return str(prof.get("game") or DEFAULT_GAME)

    def _do_export(self):
        path = filedialog.asksaveasfilename(
            title="导出秘籍包", defaultextension=".vcpack", initialfile="cheats.vcpack",
            filetypes=[("秘籍包", "*.vcpack"), ("JSON", "*.json")], parent=self)
        if not path:
            return
        pack = make_pack(self.var_name.get(), self.app.cheats,
                         author=self.var_author.get(), game=self.var_game.get())
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(pack, fh, ensure_ascii=False, indent=2)
            self.app.log(f"已导出秘籍包：{os.path.basename(path)}（{len(pack['cheats'])} 条）", "ok")
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc), parent=self)

    # -- 已安装 -------------------------------------------------------------
    def _page_installed(self, nb):
        frm = ttk.Frame(nb, padding=14)
        self.inst_tree = ttk.Treeview(frm, columns=("name", "author", "game", "ver", "time"),
                                      show="headings", height=10)
        for key, (text, width) in {"name": ("包名", 200), "author": ("作者", 110),
                                   "game": ("游戏", 130), "ver": ("包版本", 70),
                                   "time": ("导入时间", 150)}.items():
            self.inst_tree.heading(key, text=text)
            self.inst_tree.column(key, width=width)
        self.inst_tree.pack(fill="both", expand=True)
        ttk.Button(frm, text="移除选中记录", command=self._remove_record).pack(anchor="w", pady=(8, 0))
        self._load_installed()
        return frm

    def _load_installed(self):
        if not hasattr(self, "inst_tree"):
            return
        self.inst_tree.delete(*self.inst_tree.get_children())
        for i, p in enumerate(self.app.store.get("packs") or []):
            self.inst_tree.insert("", "end", iid=str(i), values=(
                p["name"], p["author"], p["game"], p["pack_version"], p["imported_at"]))

    def _remove_record(self):
        sel = self.inst_tree.selection()
        if not sel:
            return
        packs = self.app.store.get("packs") or []
        for iid in sorted(sel, key=int, reverse=True):
            if int(iid) < len(packs):
                packs.pop(int(iid))
        self.app.persist()
        self._load_installed()


# ----------------------------------------------------------------------------
# 1.9 文本 / CSV 粘贴导入（预览 + 逐行报错）
# ----------------------------------------------------------------------------
class TextImportDialog(tk.Toplevel):
    def __init__(self, app: "CheatApp"):
        super().__init__(app.root)
        self.app = app
        self.items: list[dict] = []
        self.title("从文本 / CSV 粘贴导入")
        self.configure(bg=C["bg"])
        self.transient(app.root)
        bind_dialog_keys(self)                       # 1.8-G
        self.geometry(f"{int(700 * app.ui)}x{int(540 * app.ui)}")

        hint = ("每行一条：代码  |  名称,代码  |  名称,代码,热键  |  名称,代码,热键,备注\n"
                "（逗号或 Tab 分隔；# 开头为注释；热键需带 Ctrl/Alt/Shift 或 F1–F12）")
        ttk.Label(self, text=hint, style="Muted.TLabel", justify="left").pack(anchor="w", padx=12, pady=(12, 4))
        self.txt = tk.Text(self, height=8, font=("Consolas", 10), wrap="none", relief="flat",
                           bg="#ffffff", highlightthickness=1, highlightbackground=C["line"])
        self.txt.pack(fill="x", padx=12)
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=12, pady=(6, 0))
        ttk.Button(bar, text="解析预览", command=self._parse).pack(side="left")
        self.var_skip = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="跳过与当前方案重复的代码", variable=self.var_skip).pack(side="left", padx=(12, 0))
        ttk.Button(bar, text="导入有效行 →", style="Accent.TButton", command=self._do_import).pack(side="right")
        self.lbl_result = ttk.Label(bar, text="", style="Muted.TLabel")
        self.lbl_result.pack(side="right", padx=(0, 12))

        self.tree = ttk.Treeview(self, columns=("line", "code", "name", "hotkey", "msg"),
                                 show="headings", selectmode="extended")
        for key, (text, width) in {"line": ("行号", 60), "code": ("代码", 160),
                                   "name": ("名称", 140), "hotkey": ("热键", 100),
                                   "msg": ("说明", 300)}.items():
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width)
        self.tree.tag_configure("error", foreground=C["warn"])
        self.tree.pack(fill="both", expand=True, padx=12, pady=(8, 6))
        ttk.Button(self, text="关闭", command=self.destroy).pack(pady=(0, 10))

    def _parse(self):
        items, errors = parse_pasted(self.txt.get("1.0", "end"))
        existing = {c["code"].upper() for c in self.app.cheats}
        self.tree.delete(*self.tree.get_children())
        self.items = []
        skipped = 0
        for i, item in enumerate(items, 1):
            if self.var_skip.get() and item["code"] in existing:
                skipped += 1
                continue
            self.items.append(item)
            self.tree.insert("", "end", values=(i, item["code"], item["name"],
                                                item["hotkey"] or "—", "可导入"))
        for err in errors:
            self.tree.insert("", "end", values=(err["line"], "—", err["raw"][:30], "—",
                                                err["reason"]), tags=("error",))
        self.lbl_result.configure(text=f"可导入 {len(self.items)} 条 · 跳过重复 {skipped} · 报错 {len(errors)} 行")

    def _do_import(self):
        if not self.items:
            messagebox.showinfo("没有可导入的行", "请先粘贴内容并点「解析预览」。", parent=self)
            return
        added = 0
        for item in self.items:
            if any(c["code"] == item["code"] for c in self.app.cheats):
                continue
            self.app.cheats.append(item)
            added += 1
        self.app.persist()
        self.app.refresh_tree()
        self.app.apply_hotkeys()
        self.app.log(f"文本导入完成：新增 {added} 条（未验证，默认不绑定或按文本指定热键）。", "ok")
        messagebox.showinfo("导入完成", f"已导入 {added} 条。\n导入条目默认标注「未实机验证」，"
                                        "请核对后在列表里绑定热键。", parent=self)
        self.destroy()


# ----------------------------------------------------------------------------
# 1.9 游戏模板选择
# ----------------------------------------------------------------------------
class TemplateDialog(tk.Toplevel):
    def __init__(self, app: "CheatApp"):
        super().__init__(app.root)
        self.app = app
        self.title("套用游戏模板")
        self.configure(bg=C["bg"])
        self.transient(app.root)
        bind_dialog_keys(self)                       # 1.8-G
        self.geometry(f"{int(560 * app.ui)}x{int(430 * app.ui)}")

        ttk.Label(self, text="选择一套模板：会替换秘籍表并（若有）套用对应发送参数。",
                  style="Muted.TLabel").pack(anchor="w", padx=14, pady=(14, 6))
        row = ttk.Frame(self)
        row.pack(fill="both", expand=True, padx=14)
        self.var_choice = tk.StringVar(value=DEFAULT_GAME)
        self.lst = tk.Listbox(row, font=("Microsoft YaHei UI", 10), exportselection=False)
        for name in TEMPLATE_NAMES:
            self.lst.insert("end", name)
        self.lst.pack(side="left", fill="y")
        self.lst.selection_set(0)
        self.lbl_info = tk.Label(row, text="", bg=C["bg"], fg=C["text"], justify="left",
                                 anchor="nw", wraplength=330, font=("Microsoft YaHei UI", 10))
        self.lbl_info.pack(side="left", fill="both", expand=True, padx=(12, 0))
        self.lst.bind("<<ListboxSelect>>", lambda e: self._show_info())
        self._show_info()

        self.var_new = tk.BooleanVar(value=True)
        ttk.Checkbutton(self, text="新建方案存放（取消勾选 = 替换当前方案内容，可 Ctrl+Z 之外不可撤销）",
                        variable=self.var_new).pack(anchor="w", padx=14, pady=(10, 0))
        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=14, pady=(8, 12))
        ttk.Button(btns, text="套用", style="Accent.TButton", command=self._apply).pack(side="right")
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right", padx=(0, 8))

    def _choice(self) -> str:
        sel = self.lst.curselection()
        return TEMPLATE_NAMES[sel[0]] if sel else DEFAULT_GAME

    def _show_info(self):
        name = self._choice()
        info = TEMPLATE_INFO.get(name, {})
        lines = [name, "", info.get("description", "")]
        diffs = info.get("differences") or []
        if diffs:
            lines += ["", "已知差异 / 提示："] + [f"· {d}" for d in diffs]
        if not info.get("verified", True):
            lines += ["", "⚠ 全部条目未实机验证，UI 会灰显并标注；默认不绑定热键。"]
        lines += ["", f"条目数：{len(template_cheats(name))}（每次套用生成全新 id）"]
        self.lbl_info.configure(text="\n".join(lines))

    def _apply(self):
        app = self.app
        name = self._choice()
        cheats = template_cheats(name)
        preset = template_preset(name)
        if not cheats:
            return
        if not info_verified(name) and not messagebox.askyesno(
                "未验证模板",
                f"「{name}」的秘籍均为公开文本、未在本工具实机验证。\n"
                "仍要套用吗？（会灰显标注，默认不绑定热键）", parent=self):
            return
        if self.var_new.get():
            base = name.replace("（未验证）", "")
            new_name, i = base, 2
            while any(p["name"] == new_name for p in app.store["profiles"]):
                new_name, i = f"{base} ({i})", i + 1
            app.store["profiles"].append({"name": new_name, "cheats": cheats, "game": name})
            app.var_profile.set(new_name)
            app.switch_profile()
            app._refresh_profile_choices()
        else:
            prof = next((p for p in app.store["profiles"] if p["name"] == app.active_profile), None)
            if prof is not None:
                prof["game"] = name
            app.cheats[:] = cheats
        if preset:
            app.settings.update(preset)
            app.var_delay.set(int(preset["char_interval_ms"]))
        app.persist()
        app.refresh_tree()
        app.apply_hotkeys()
        app.log(f"已套用游戏模板「{name}」（{len(cheats)} 条"
                + (f"，参数 {preset['char_interval_ms']}ms" if preset else "") + "）。", "ok")
        self.destroy()


def bind_dialog_keys(win: tk.Toplevel, on_escape=None):
    """1.8-G：Toplevel 统一 Esc 关闭（主窗口 Esc = 停发送/清搜索 的语义不变）。

    Tab 顺序沿用控件创建顺序；列表 ↑↓ / Enter 发送由 Treeview 与既有绑定负责。
    """
    win.bind("<Escape>", lambda e: (on_escape() if on_escape else win.destroy()))


# ----------------------------------------------------------------------------
# 1.8-I 发送历史面板（最近 50 次，可重发）
# ----------------------------------------------------------------------------
class HistoryDialog(tk.Toplevel):
    LABELS = {"ok": "✔ 成功", "cancel": "⏹ 已停止", "fail": "✖ 失败"}

    def __init__(self, app: "CheatApp"):
        super().__init__(app.root)
        self.app = app
        self.title("发送历史（最近 50 次）")
        self.configure(bg=C["bg"])
        self.transient(app.root)
        self.geometry(f"{int(820 * app.ui)}x{int(440 * app.ui)}")
        bind_dialog_keys(self)                      # 1.8-G

        wrap = tk.Frame(self, bg=C["panel"], highlightthickness=1, highlightbackground=C["line"])
        wrap.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        cols = ("at", "name", "code", "profile", "result", "elapsed", "detail")
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings")
        for key, (text, width) in {
            "at": ("时间", 140), "name": ("名称", 120), "code": ("代码", 160),
            "profile": ("方案", 100), "result": ("结果", 90),
            "elapsed": ("耗时(s)", 80), "detail": ("说明", 300),
        }.items():
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, anchor="w" if key in ("name", "code", "detail") else "center")
        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.tag_configure("ok", foreground=C["ok"])
        self.tree.tag_configure("cancel", foreground="#b45309")
        self.tree.tag_configure("fail", foreground=C["warn"])
        self.tree.bind("<Double-1>", lambda e: self._resend())

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=12, pady=(2, 10))
        ttk.Button(btns, text="↻ 重发所选", command=self._resend).pack(side="left")
        ttk.Button(btns, text="清空历史", command=self._clear).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="关闭", command=self.destroy).pack(side="right")
        ttk.Label(btns, text="双击一行也可重发；重发按当前方案中的代码查找。",
                  style="Muted.TLabel").pack(side="right", padx=(0, 12))
        self.reload()

    def reload(self):
        self.tree.delete(*self.tree.get_children())
        for i, h in enumerate(self.app.store.get("history") or []):
            self.tree.insert("", "end", iid=str(i),
                             values=(h["at"], h["name"], h["code"], h["profile"],
                                     self.LABELS.get(h["result"], h["result"]),
                                     f"{h['elapsed']:.3f}", h["detail"]),
                             tags=(h["result"],) if h["result"] in self.LABELS else ())

    def _resend(self):
        sel = self.tree.selection()
        if not sel:
            return
        hist = self.app.store.get("history") or []
        idx = int(sel[0])
        if idx >= len(hist):
            return
        code = hist[idx]["code"]
        cheat = next((c for c in self.app.cheats if c["code"] == code), None)
        if cheat is None:
            messagebox.showinfo("当前方案没有这条",
                                f"代码 {code} 不在当前方案「{self.app.active_profile}」里。\n"
                                f"记录所属方案：{hist[idx]['profile'] or '未知'}，请先切换方案。",
                                parent=self)
            return
        self.app.send_by_id(cheat["id"])
        self.app.log(f"从发送历史重发：{code}", "info")

    def _clear(self):
        if not messagebox.askyesno("清空历史", "清空全部发送历史？（不影响使用统计）", parent=self):
            return
        self.app.store["history"] = []
        self.app.persist()
        self.reload()


def info_verified(name: str) -> bool:
    return bool(TEMPLATE_INFO.get(name, {}).get("verified", True))


class CheatApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.events: queue.Queue = queue.Queue()
        self.store = load_store()
        self.load_warning = last_load_warning()
        self.settings = self.store["settings"]
        self.stats = self.store["stats"]
        self.active_profile = self.store["active_profile"]
        prof = next(p for p in self.store["profiles"] if p["name"] == self.active_profile)
        self.cheats = prof["cheats"]  # 引用 store 内的列表，增删改即时生效
        self.conflicts: dict[str, str] = {}
        self.hotkey_owner: dict[int, str] = {}
        self.sending = threading.Lock()
        self._stop = threading.Event()   # 置位即停：用户点停止 / 暂停 / 关闭程序
        self._inflight = ""              # 正在发送的秘籍 id（空 = 空闲）
        self._last_send: dict[str, float] = {}   # 去抖：秘籍 id -> 上次发送时刻
        self.test_hwnd = 0
        self.game_info: tuple[int, str, str] = (0, "", "")
        self.game_is_admin: bool | None = None    # 游戏进程是否管理员运行
        self.is_admin = self_elevated()           # 本工具是否管理员运行
        self._toast: tk.Toplevel | None = None
        self.last_error = ""
        self.paused = False              # 暂停状态不持久化：重启即恢复工作（安全侧）
        self._undo: dict | None = None   # 仅保留最近一步删除
        self._avoid: set[str] = set()    # 注册时报"已被占用"的键，自动分配时跳过
        self._auto_fix: dict | None = None
        self._last_foreign: tuple[int, str, str] = (0, "", "")   # 最近一个非本工具的前台窗口
        self._kw_fixed = self._heal_target_keywords()
        self._switch_pending = None      # 1.8 自动切方案防抖：((rule_name, profile), first_seen)
        self._switch_warned: set[str] = set()   # 规则指向不存在方案：只警告一次
        self._tray_hinted = False        # 首次最小化到托盘的提示只给一次
        self._active_target: dict | None = None   # 2.0 当前命中的目标规则解析结果
        self.hooks = HookBus(enabled=False)      # 2.0 扩展点，默认关闭
        self._make_vars()
        self.hooks.enabled = bool(self.settings.get("hooks_enabled", False))

        self._setup_style()
        self._build_ui()
        self.refresh_tree()

        self.engine = HotkeyEngine(self.events)
        self.apply_hotkeys()
        self.root.after(40, self._pump)
        self.root.after(500, self._poll_foreign_foreground)
        self.root.after(1500, self._update_game_status)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # 1.8 托盘常驻：失败不碍事（available=False 时自动回落"关闭即退出"）
        self.tray = TrayIcon(
            tooltip=f"{APP_NAME} v{APP_VER}",
            emit=lambda action: self.events.put(("tray", action)),
            is_paused=lambda: self.paused,
            on_error=lambda msg: append_log(msg, "WARN"))
        if self.tray.available:
            self.root.bind("<Unmap>", self._on_unmap)   # 最小化也进托盘
        # 1.8 首次启动向导：空配置（或从未走过）必弹；设置里可重新打开
        if not self.settings.get("onboarded", False):
            self.root.after(800, self.open_wizard)
        self.root.bind("<Control-F1>", lambda e: self.open_wizard())

        append_log(f"启动 {APP_NAME} v{APP_VER}；配置文件 {data_path()}；日志 {log_file()}")
        append_log(f"权限：本工具{'已' if self.is_admin else '未'}提权")
        if self._kw_fixed:
            self.log("目标窗口关键字原本指向本工具自身，已重置为「Vice City」。"
                     "正确做法：切到游戏停 1 秒，再点「拾取当前窗口」。", "warn")
        if self.load_warning:
            self.log("⚠ " + self.load_warning, "warn")
            self.root.after(300, lambda: messagebox.showwarning(
                "配置文件已隔离", self.load_warning + "\n\n可从「从备份恢复」找回上一版配置。",
                parent=self.root))

    # -- 外观 ---------------------------------------------------------------
    def _make_vars(self):
        """Tk 变量统一在此创建：主界面、设置对话框、退出保存共用同一份。

        1.8 把设置控件搬进对话框后，变量必须与控件解耦——
        对话框关着时 _read_params / on_close 也照常读写。
        """
        s = self.settings
        self.var_kw = tk.StringVar(value=s["target_keywords"])
        self.var_fg = tk.BooleanVar(value=bool(s["require_foreground"]))
        self.var_ime = tk.BooleanVar(value=bool(s["disable_ime"]))
        self.var_delay = tk.IntVar(value=int(s["char_interval_ms"]))
        self.var_toast = tk.BooleanVar(value=bool(s["show_toast"]))
        self.var_tray = tk.BooleanVar(value=bool(s.get("close_to_tray", True)))
        self.var_auto_switch = tk.BooleanVar(value=bool(s.get("auto_switch", True)))
        self.var_hooks = tk.BooleanVar(value=bool(s.get("hooks_enabled", False)))

    def _on_unmap(self, _event=None):
        """用户点了任务栏/标题栏的「最小化」→ 收进托盘（withdraw 不触发本回调二次入托）。"""
        try:
            if self.root.state() == "iconic" and self.tray.available \
                    and self.settings.get("close_to_tray", True):
                self.root.withdraw()
                self._tray_hint_once()
        except Exception:
            pass

    def _tray_hint_once(self):
        if not self._tray_hinted:
            self._tray_hinted = True
            self.log("已最小化到托盘：点托盘图标恢复，右键可退出"
                     "（设置 → 常规 可改回「关闭即退出」）。", "info")

    def _setup_style(self):
        self.ui = ui_scale(self.root)
        self.root.title(f"{APP_NAME} v{APP_VER}")
        self.root.configure(bg=C["bg"])
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        w = min(int(WIN_W * self.ui), max(640, sw - 40))
        h = min(int(WIN_H * self.ui), max(480, sh - 90))
        self.root.geometry(f"{w}x{h}")
        self.root.minsize(min(int(900 * self.ui), w), min(int(600 * self.ui), h))
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", font=("Microsoft YaHei UI", 10), background=C["bg"], foreground=C["text"])
        style.configure("TFrame", background=C["bg"])
        style.configure("Panel.TFrame", background=C["panel"])
        style.configure("TLabel", background=C["bg"], foreground=C["text"])
        style.configure("Muted.TLabel", background=C["bg"], foreground=C["muted"],
                        font=("Microsoft YaHei UI", 9))
        style.configure("H1.TLabel", background=C["bg"], foreground=C["text"],
                        font=("Microsoft YaHei UI", 15, "bold"))
        style.configure("TButton", padding=(10, 5))
        style.configure("Accent.TButton", padding=(14, 6), background=C["accent"],
                        foreground="#ffffff", borderwidth=0)
        style.map("Accent.TButton", background=[("active", "#1d4ed8"), ("pressed", "#1e40af")])
        style.configure("Danger.TButton", padding=(12, 5), background="#dc2626",
                        foreground="#ffffff", borderwidth=0)
        style.map("Danger.TButton", background=[("active", "#b91c1c"), ("pressed", "#991b1b")])
        style.configure("Treeview", background=C["panel"], fieldbackground=C["panel"],
                        foreground=C["text"], rowheight=int(27 * self.ui), borderwidth=0,
                        font=("Microsoft YaHei UI", 10))
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"),
                        background="#eef1f6", foreground="#374151", relief="flat", padding=(6, 6))
        style.map("Treeview", background=[("selected", "#dbe7ff")],
                  foreground=[("selected", C["text"])])
        style.configure("TCheckbutton", background=C["bg"])
        style.configure("TCombobox", padding=3)
        style.configure("TSpinbox", padding=3)

    # -- 布局 ---------------------------------------------------------------
    def _build_ui(self):
        root = self.root
        outer = ttk.Frame(root, padding=(16, 14, 16, 10))
        outer.pack(fill="both", expand=True)

        head = ttk.Frame(outer)
        head.pack(fill="x")
        ttk.Label(head, text=APP_NAME, style="H1.TLabel").pack(side="left")
        ttk.Label(head, text=f"  v{APP_VER} · 快捷键触发 · 自动键盘输入 · 前台校验",
                  style="Muted.TLabel").pack(side="left", pady=(6, 0))
        self.btn_pause = ttk.Button(head, text="⏸ 暂停热键", width=12, command=self.toggle_pause)
        self.btn_pause.pack(side="right", pady=(2, 0))
        self.lbl_state = ttk.Label(head, text="初始化…", style="Muted.TLabel")
        self.lbl_state.pack(side="right", pady=(6, 0), padx=(0, 12))
        self.lbl_game = ttk.Label(head, text="⚪ 检测游戏…", style="Muted.TLabel")
        self.lbl_game.pack(side="right", pady=(6, 0), padx=(0, 16))
        # 权限不匹配时才出现：UIPI 会静默拦掉注入，必须给一个一键修复的入口
        self.btn_admin = ttk.Button(head, text="⚠ 以管理员身份重启", style="Danger.TButton",
                                    command=self.relaunch_as_admin)

        # 工具条（1.8 收敛：只留常用项，其余进「设置」对话框）
        bar = tk.Frame(outer, bg=C["panel"], highlightthickness=1,
                       highlightbackground=C["line"], padx=12, pady=8)
        bar.pack(fill="x", pady=(12, 10))
        lbl = dict(bg=C["panel"], fg=C["muted"], font=("Microsoft YaHei UI", 9))

        tk.Label(bar, text="方案", **lbl).pack(side="left")
        self.var_profile = tk.StringVar(value=self.active_profile)
        self.cbo_profile = ttk.Combobox(bar, textvariable=self.var_profile, width=12,
                                        state="readonly")
        self.cbo_profile.pack(side="left", padx=(6, 0))
        self.cbo_profile.bind("<<ComboboxSelected>>", self.switch_profile)
        self.lbl_autoswitch = ttk.Label(bar, text="", style="Muted.TLabel")
        self.lbl_autoswitch.pack(side="left", padx=(14, 0))

        ttk.Button(bar, text="⚙ 设置…", command=self.open_settings).pack(side="right")
        ttk.Button(bar, text="⌨ 热键总览", command=self.open_hotkey_overview)\
            .pack(side="right", padx=(0, 8))
        ttk.Button(bar, text="↻ 重新注册快捷键", command=self.apply_hotkeys)\
            .pack(side="right", padx=(0, 8))

        # 搜索（与分组筛选叠加生效）
        srow = tk.Frame(outer, bg=C["bg"])
        srow.pack(fill="x", pady=(0, 8))
        tk.Label(srow, text="搜索", bg=C["bg"], fg=C["muted"],
                 font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.var_search = tk.StringVar()
        self.ent_search = tk.Entry(srow, textvariable=self.var_search, font=("Microsoft YaHei UI", 10),
                                   relief="flat", bg="#ffffff", highlightthickness=1,
                                   highlightbackground=C["line"], highlightcolor=C["accent"], width=34)
        self.ent_search.pack(side="left", ipady=3, padx=(8, 8))
        self.ent_search.bind("<KeyRelease>", lambda e: self.refresh_tree())
        self.lbl_count = ttk.Label(srow, text="", style="Muted.TLabel")
        self.lbl_count.pack(side="left")
        ttk.Button(srow, text="清空", width=5, command=self.clear_search).pack(side="left", padx=(10, 0))

        tk.Label(srow, text="分组", bg=C["bg"], fg=C["muted"],
                 font=("Microsoft YaHei UI", 9)).pack(side="left", padx=(16, 0))
        self.var_group_filter = tk.StringVar(value="全部")
        self.cbo_group = ttk.Combobox(srow, textvariable=self.var_group_filter, width=12,
                                      state="readonly")
        self.cbo_group.pack(side="left", padx=(6, 0))
        self.cbo_group.bind("<<ComboboxSelected>>", lambda e: self.refresh_tree())

        mb = ttk.Menubutton(srow, text="⋯ 更多")
        mb.pack(side="right")
        more = tk.Menu(mb, tearoff=0)
        more.add_command(label="设置…", command=self.open_settings)
        more.add_command(label="快捷键总览", command=self.open_hotkey_overview)
        more.add_command(label="发送历史（最近 50 次）", command=self.open_history)
        more.add_command(label="首次启动向导（Ctrl+F1）", command=self.open_wizard)
        more.add_separator()
        more.add_command(label="秘籍包管理（.vcpack）…", command=self.open_pack_manager)
        more.add_command(label="从文本/CSV 粘贴导入…", command=self.open_text_import)
        more.add_command(label="套用游戏模板…", command=self.open_template_dialog)
        more.add_command(label="导出 v2 兼容配置…", command=self.export_v2_compat)
        more.add_separator()
        more.add_command(label="导出整包（设置 + 全部方案 + 统计）", command=self.export_bundle)
        more.add_command(label="导入整包…", command=self.import_bundle)
        more.add_command(label="从上一版备份恢复", command=self.restore_backup)
        more.add_command(label="打开日志目录", command=self.open_log)
        more.add_separator()
        more.add_command(label="环境诊断（检查权限 / 前台 / 注入）", command=self.run_diagnose)
        more.add_command(label="以管理员身份重启", command=self.relaunch_as_admin)
        more.add_separator()
        more.add_command(label="清空使用统计", command=self.clear_stats)
        mb.configure(menu=more)

        # 列表
        list_wrap = tk.Frame(outer, bg=C["panel"], highlightthickness=1,
                             highlightbackground=C["line"])
        list_wrap.pack(fill="both", expand=True)

        cols = ("idx", "name", "code", "hotkey", "state", "count", "last", "note")
        self.tree = ttk.Treeview(list_wrap, columns=cols, show="headings", selectmode="extended")
        headings = {"idx": ("#", 36, "center"), "name": ("名称", 148, "w"),
                    "code": ("秘籍代码", 190, "w"), "hotkey": ("快捷键", 114, "center"),
                    "state": ("状态", 56, "center"), "count": ("次数", 48, "center"),
                    "last": ("最近", 96, "center"), "note": ("备注", 250, "w")}
        for key, (text, width, anchor) in headings.items():
            self.tree.heading(key, text=text)
            self.tree.column(key, width=int(width * self.ui), minwidth=int(width * self.ui * 0.6),
                             anchor=anchor, stretch=(key in ("name", "note")))
        self._sort_key, self._sort_desc = "count", True
        self.tree.heading("count", text="次数 ↓", command=lambda: self.sort_by("count"))
        self.tree.heading("last", text="最近", command=lambda: self.sort_by("last"))
        self.tree.heading("name", text="名称", command=lambda: self.sort_by("name"))
        vsb = ttk.Scrollbar(list_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.tag_configure("odd", background="#fbfcfe")
        self.tree.tag_configure("conflict", foreground=C["warn"])
        self.tree.tag_configure("unbound", foreground="#98a2b3")
        self.tree.tag_configure("unverified", foreground="#94a3b8")  # 1.9 未实机验证
        self.tree.bind("<Double-1>", lambda e: self.edit_selected())
        self.tree.bind("<Return>", lambda e: self.send_selected())
        self.tree.bind("<Home>", lambda e: self._select_edge(0))    # 1.8-G 键盘全导航
        self.tree.bind("<End>", lambda e: self._select_edge(-1))
        self.tree.bind("<Button-3>", self._popup_row_menu)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._update_hint())

        self.menu_row = tk.Menu(self.root, tearoff=0)
        self.menu_row.add_command(label="换一个可用键（本行）", command=self.fix_selected_conflict)
        self.menu_row.add_command(label="自动分配全部冲突项", command=self.auto_fix_conflicts)
        self.menu_row.add_separator()
        self.menu_row.add_command(label="复制秘籍代码", command=self.copy_code)
        # 1.9-C 批量操作（列表已是 extended 多选）
        self.menu_batch = tk.Menu(self.menu_row, tearoff=0)
        self.menu_batch.add_command(label="批量改分组…", command=self.batch_set_group)
        self.menu_batch.add_command(label="批量分配空闲热键", command=self.batch_assign_hotkeys)
        self.menu_batch.add_command(label="批量设置发送间隔…", command=self.batch_set_interval)
        self.menu_batch.add_command(label="批量删除…", command=self.batch_delete)
        self.menu_row.add_cascade(label="批量操作（选中多条时可用）", menu=self.menu_batch)

        # 操作区
        ops = ttk.Frame(outer)
        ops.pack(fill="x", pady=(10, 0))
        self.btn_send = ttk.Button(ops, text="▶ 发送所选 (Enter)", style="Accent.TButton",
                                   command=self.on_send_button)
        self.btn_send.pack(side="left")
        ttk.Button(ops, text="添加", command=self.add_cheat).pack(side="left", padx=(8, 0))
        ttk.Button(ops, text="编辑", command=self.edit_selected).pack(side="left", padx=(6, 0))
        ttk.Button(ops, text="删除", command=self.delete_selected).pack(side="left", padx=(6, 0))
        ttk.Button(ops, text="撤销", command=self.undo_last).pack(side="left", padx=(6, 0))
        ttk.Button(ops, text="注入自检", command=self.open_test_window).pack(side="left", padx=(18, 0))
        ttk.Button(ops, text="↑", width=3, command=lambda: self.move(-1)).pack(side="right")
        ttk.Button(ops, text="↓", width=3, command=lambda: self.move(1)).pack(side="right", padx=(0, 6))
        ttk.Button(ops, text="恢复默认", command=self.reset_defaults).pack(side="right", padx=(0, 14))

        # 日志
        self.txt_log = tk.Text(outer, height=5, bg="#0f172a", fg="#cbd5e1", relief="flat",
                               font=("Consolas", 9), padx=10, pady=6, wrap="word",
                               insertbackground="#cbd5e1")
        self.txt_log.pack(fill="x", pady=(10, 0))
        self.txt_log.tag_configure("ok", foreground="#6ee7b7")
        self.txt_log.tag_configure("warn", foreground="#fca5a5")
        self.txt_log.tag_configure("info", foreground="#cbd5e1")
        self.txt_log.configure(state="disabled")
        self.lbl_hint = ttk.Label(outer, text="", style="Muted.TLabel")
        self.lbl_hint.pack(fill="x", pady=(6, 0))

        self.log("工具已启动。请在游戏里切到前台，按 F1 试试「满血」。", "info")
        self._refresh_group_choices()
        self._refresh_profile_choices()

        # 全局快捷键（界面内）：搜索 / 撤销 / 清空搜索
        self.root.bind("<Control-f>", lambda e: self._focus_search())
        self.root.bind("<Control-z>", lambda e: self.undo_last())
        self.root.bind("<Escape>", lambda e: self._on_escape())

    def _select_edge(self, which: int):
        """1.8-G：Home / End 跳到列表首尾（↑↓ 选中、Enter 发送沿用既有行为）。"""
        kids = self.tree.get_children()
        if kids:
            iid = kids[0] if which == 0 else kids[-1]
            self.tree.selection_set(iid)
            self.tree.see(iid)
            self._update_hint()
        return "break"

    def _focus_search(self):
        self.ent_search.focus_set()
        self.ent_search.select_range(0, "end")
        return "break"

    # -- 日志 / 事件泵 -------------------------------------------------------
    def log(self, text: str, kind: str = "info", from_thread: bool = False):
        if from_thread:
            self.events.put(("log", text, kind))
            return
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", time.strftime("[%H:%M:%S] ") + text + "\n", kind)
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")
        append_log(text, "WARN" if kind == "warn" else "INFO")

    def _pump(self):
        try:
            while True:
                item = self.events.get_nowait()
                kind = item[0]
                if kind == "log":
                    self.log(item[1], item[2])
                elif kind == "status":
                    self.lbl_state.configure(text=item[1])
                elif kind == "toast":
                    self.show_toast(item[1], item[2])
                elif kind == "stats":
                    self._bump_stats(item[1], item[2])
                elif kind == "probe_done":
                    self._on_probe_done(item[1], item[2], item[3])
                elif kind == "diag_done":
                    self._show_diag(item[1])
                elif kind == "hotkey":
                    self._on_hotkey(item[1])
                elif kind == "send_done":
                    # 只在没有新发送接管时才恢复按钮，避免"旧任务结束把新任务按钮改回去"
                    if self._inflight == item[1]:
                        self._inflight = ""
                        self._set_sending_ui(False)
                elif kind == "hotkeys":
                    self._on_hotkeys_applied(item[1], item[2])
                elif kind == "tray":
                    self._on_tray_action(item[1])
                elif kind == "history":
                    self._record_history(item[1])
        except queue.Empty:
            pass
        self.root.after(40, self._pump)

    def _record_history(self, rec: dict):
        """1.8-I：主线程里写历史（工作线程只投递纯 dict，不碰 store / Tk）。"""
        hist = self.store.setdefault("history", [])
        hist.insert(0, rec)
        del hist[50:]
        self.persist()

    def _on_hotkey(self, hid: int):
        cheat_id = self.hotkey_owner.get(hid)
        if not cheat_id:
            return
        if cheat_id == PAUSE_ID:
            self.toggle_pause()
            return
        self.send_by_id(cheat_id)

    # -- 1.8 托盘 -------------------------------------------------------------
    def _on_tray_action(self, action: str):
        if action == "show":
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        elif action == "pause":
            self.toggle_pause()
        elif action == "exit":
            self.on_close(force=True)

    # -- 游戏检测 / 悬浮提示 / 统计 -------------------------------------------
    def _update_game_status(self):
        try:
            self.game_info = find_game_window()
            hwnd, _title, exe = self.game_info
            self.game_is_admin = process_elevated(window_pid(hwnd)) if hwnd else None
            if hwnd and self.permission_blocks_input():
                self.lbl_game.configure(
                    text=f"🔴 游戏以管理员运行 → 按键会被拦截（{exe or '未知进程'}）",
                    foreground=C["warn"])
                self._show_admin_button(True)
            elif hwnd:
                self.lbl_game.configure(text=f"🟢 游戏运行中：{exe or '未知进程'}", foreground=C["ok"])
                self._show_admin_button(False)
            else:
                self.lbl_game.configure(text="⚪ 未检测到游戏", foreground=C["muted"])
                self._show_admin_button(False)
        except Exception:
            pass
        # 1.9.1：放在 try 外面——游戏检测抛异常不该连带跳过自动切方案
        self._auto_switch_tick()
        self.root.after(3000, self._update_game_status)

    # -- 1.8 按游戏自动切方案 ---------------------------------------------------
    def _auto_switch_tick(self):
        """3s 轮询顺带跑：前台命中规则且稳定 800ms → 自动切方案。

        2.0：优先用通用 `targets` 规则（可带方案/策略/IME 策略），没有 targets
        时**完全沿用 1.8 的 games 行为**——缺省即旧行为，Gate G2.0 要求。
        防抖 800ms：Alt+Tab 掠过的窗口不触发；发送中不切（1.8-B 硬约束）。
        """
        try:
            if not self.settings.get("auto_switch", True):
                return
            targets = self.store.get("targets") or []
            games = self.store.get("games") or []
            if not targets and not games:
                return
            if self.sending.locked() or self._inflight:
                self._switch_pending = None
                return
            title, exe = foreground_info()
            resolved = None
            if targets:
                hit = evaluate_targets(targets, title, exe)
                if hit is None:
                    self._switch_pending = None
                    self._active_target = None
                    return
                resolved = resolve_target(hit, self.store)
                # 兼容旧的 debounce/切换流程：统一成 {name, profile}
                rule = {"name": hit["name"], "profile": resolved["profile"]}
                self._active_target = resolved
            else:
                hit = evaluate_game_rules(games, title, exe)
                if hit is None:
                    self._switch_pending = None
                    self._active_target = None
                    return
                rule = {"name": hit["name"], "profile": hit.get("profile", "")}
                self._active_target = None

            now = time.time()
            if not rule["profile"] or rule["profile"] == self.active_profile:
                self._switch_pending = None
                return
            names = {p["name"] for p in self.store["profiles"]}
            if rule["profile"] not in names:
                if rule["name"] not in self._switch_warned:
                    self._switch_warned.add(rule["name"])
                    self.log(f"⚠ 自动切换规则「{rule['name']}」指向不存在的方案"
                             f"「{rule['profile']}」，已跳过。可在 设置 → 游戏 修正。", "warn")
                return
            key = (rule["name"], rule["profile"])
            if self._switch_pending and self._switch_pending[0] == key:
                if now - self._switch_pending[1] >= 0.8:
                    self._switch_pending = None
                    self._do_auto_switch(rule)
            else:
                self._switch_pending = (key, now)
        except Exception:
            pass

    def _do_auto_switch(self, rule: dict):
        self.var_profile.set(rule["profile"])
        self.switch_profile()
        self.log(f"🎯 前台命中规则「{rule['name']}」→ 已自动切到方案「{rule['profile']}」。", "ok")
        self.show_toast(f"🎯 已自动切换方案：{rule['profile']}", "ok")

    def permission_blocks_input(self) -> bool:
        """游戏以管理员运行而本工具不是 → UIPI 会静默丢弃注入，发送必然无效。"""
        return bool(self.game_is_admin) and not self.is_admin

    def _permission_mismatch_live(self) -> bool:
        """发送前实时复核一次（UI 里的 game_is_admin 可能已过期 3 秒）。"""
        if self.is_admin:
            return False
        hwnd = self.game_info[0]
        if not hwnd:
            return False
        val = process_elevated(window_pid(hwnd))
        if val is not None:
            self.game_is_admin = val
        return bool(val)

    def _heal_target_keywords(self) -> bool:
        """目标关键字指向本工具自己是配置错误——前台校验永远不会通过。

        这是「拾取当前窗口」的经典误操作（点按钮时前台就是本工具）。
        直接重置为默认值，否则用户会一直以为"游戏没反应"。
        """
        kw = str(self.settings.get("target_keywords") or "").strip()
        if kw and APP_NAME.lower() in kw.lower():
            self.settings["target_keywords"] = DEFAULT_SETTINGS["target_keywords"]
            return True
        return False

    def _show_admin_button(self, show: bool):
        try:
            if show and not self.btn_admin.winfo_ismapped():
                # before= 让按钮在 pack 顺序里排在状态文字之前：
                # 否则头部空间不足时，后 pack 的按钮会被压成 0 宽（这次踩到了）
                self.btn_admin.pack(side="right", pady=(2, 0), padx=(0, 8), before=self.lbl_game)
            elif not show and self.btn_admin.winfo_ismapped():
                self.btn_admin.pack_forget()
        except Exception:
            pass

    def relaunch_as_admin(self):
        """以管理员身份重启自身（会弹 UAC）。"""
        try:
            if getattr(sys, "frozen", False):
                exe, params = sys.executable, ""
            else:
                exe = sys.executable
                params = " ".join(f'"{a}"' for a in [os.path.abspath(sys.argv[0]), *sys.argv[1:]])
            rc = shell_execute_runas(exe, params, os.getcwd())
            if rc > 32:
                append_log("请求以管理员身份重启（UAC）")
                self.on_close(force=True)   # 提权重启必须真退出，不能缩进托盘
            else:
                messagebox.showwarning("提权失败", f"无法以管理员身份重启（代码 {rc}）。\n"
                                       f"可手动右键 exe →「以管理员身份运行」。", parent=self.root)
        except Exception as exc:
            messagebox.showerror("提权失败", str(exc), parent=self.root)

    def show_toast(self, text: str, kind: str = "ok"):
        """游戏内悬浮提示：无边框置顶 + NOACTIVATE，绝不抢走游戏焦点"""
        if not self.var_toast.get():
            return
        if self._toast is not None and self._toast.winfo_exists():
            self._toast.destroy()
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        bg = "#065f46" if kind == "ok" else "#7f1d1d"
        fg = "#ecfdf5" if kind == "ok" else "#fee2e2"
        frm = tk.Frame(win, bg=bg, padx=18, pady=10,
                       highlightthickness=1, highlightbackground="#334155")
        frm.pack()
        tk.Label(frm, text=text, bg=bg, fg=fg,
                 font=("Microsoft YaHei UI", 11, "bold")).pack()
        win.update_idletasks()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        win.geometry(f"+{sw - w - 28}+{sh - h - 96}")
        try:
            win.attributes("-alpha", 0.94)
        except tk.TclError:
            pass
        try:
            hwnd = user32.GetAncestor(win.winfo_id(), GA_ROOT)
            add_window_exstyle(hwnd, WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST)
        except Exception:
            pass
        self._toast = win
        win.after(2400, lambda: self._fade_toast(win))

    def _fade_toast(self, win: tk.Toplevel):
        if not win.winfo_exists():
            return
        try:
            alpha = float(win.attributes("-alpha"))
        except tk.TclError:
            win.destroy()
            return
        if alpha <= 0.15:
            win.destroy()
            return
        win.attributes("-alpha", max(0.0, alpha - 0.12))
        win.after(40, lambda: self._fade_toast(win))

    def _bump_stats(self, cheat_id: str, code: str):
        try:
            count = bump_stats(self.stats, code)
            self.store["today"] = touch_today(self.store.get("today"))
            if cheat_id and self.tree.exists(cheat_id):
                self.tree.set(cheat_id, "count", str(count))
                self.tree.set(cheat_id, "last", time.strftime("%m-%d %H:%M"))
            self._update_count_label(len(self.tree.get_children()))
            self.persist()
        except Exception:
            pass

    def clear_stats(self):
        if not messagebox.askyesno("清空统计",
                                   "将把「次数 / 最近使用 / 今日次数」全部归零，不影响秘籍与快捷键。继续？",
                                   parent=self.root):
            return
        self.stats.clear()
        self.store["today"] = {"date": "", "count": 0}
        self.persist()
        self.refresh_tree()
        self.log("使用统计已清空。", "ok")

    def _on_probe_done(self, ok: bool, got_fg: bool, got: str):
        if ok:
            self.log("注入自检：✔ 通过（原生窗口收到 ASPIRINE，全链路正常）", "ok")
            self.show_toast("✔ 注入自检通过", "ok")
        else:
            detail = "未取得前台焦点" if not got_fg else f"窗口只收到 {got!r}"
            self.log(f"注入自检：✖ {detail}。多见于杀软拦截 SendInput 或会话输入状态异常。", "warn")
            self.show_toast("✖ 注入自检未通过", "warn")

    def sort_by(self, key: str):
        """点击表头排序：次数 / 最近 / 名称；再点一次反向。"""
        if getattr(self, "_sort_key", "") == key:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_key, self._sort_desc = key, key != "name"
        self.cheats[:] = sorted_cheats(self.cheats, key, self._sort_desc, self.stats)
        self.persist()
        self.refresh_tree()
        labels = {"count": "次数", "last": "最近", "name": "名称"}
        arrow = " ↓" if self._sort_desc else " ↑"
        for k, text in labels.items():
            self.tree.heading(k, text=text + (arrow if k == key else ""))
        self.log(f"已按「{labels.get(key, key)}」{'降序' if self._sort_desc else '升序'}排序（快捷键跟着条目走）。",
                 "info")

    # -- 列表渲染 ------------------------------------------------------------
    def _refresh_group_choices(self):
        groups = ["全部"]
        for c in self.cheats:
            g = c.get("group") or "自定义"
            if g not in groups:
                groups.append(g)
        self.cbo_group.configure(values=groups)
        if self.var_group_filter.get() not in groups:
            self.var_group_filter.set("全部")

    def visible_cheats(self) -> list[dict]:
        return filter_cheats(self.cheats, self.var_group_filter.get(), self.var_search.get())

    def refresh_tree(self):
        self._refresh_group_choices()
        sel = self.selected_id()
        self.tree.delete(*self.tree.get_children())
        items = self.visible_cheats()
        self._update_count_label(len(items))
        for i, c in enumerate(items, 1):
            state = "就绪"
            tags = ["odd"] if i % 2 == 0 else []
            if self.paused:
                state = "暂停"
            if c["id"] in self.conflicts:
                state = "冲突"
                tags.append("conflict")
            elif not c.get("hotkey"):
                state = "未绑定"
                tags.append("unbound")
            if not c.get("verified", True):       # 1.9-D 未实机验证模板
                tags.append("unverified")
            entry = self.stats.get(c["code"], {})
            used = entry.get("count", 0)
            last = str(entry.get("last") or "")
            if len(last) >= 16:
                last = last[5:]          # 去掉年份，保持列窄
            note = str(c.get("note") or "")
            if not c.get("verified", True):
                note = "⚠ 未实机验证 · " + note
            self.tree.insert("", "end", iid=c["id"], tags=tags,
                             values=(i, c.get("name", ""), c.get("code", ""),
                                     c.get("hotkey") or "—", state, used or "—",
                                     last or "—", note))
        if sel and self.tree.exists(sel):
            self.tree.selection_set(sel)
            self.tree.see(sel)
        elif self.tree.get_children():
            first = self.tree.get_children()[0]
            self.tree.selection_set(first)
        self._update_hint()

    def _update_count_label(self, shown: int):
        if self.var_search.get().strip() or self.var_group_filter.get() != "全部":
            text = f"匹配 {shown} / 共 {len(self.cheats)} 条"
        else:
            text = f"共 {shown} 条"
        self.lbl_count.configure(text=f"{text} · 今日 {self.today_count()} 次")

    def today_count(self) -> int:
        t = self.store.get("today") or {}
        if str(t.get("date") or "") != time.strftime("%Y-%m-%d"):
            return 0
        return max(0, _safe_int(t.get("count"), 0))

    def _update_hint(self):
        cid = self.selected_id()
        if not cid:
            self.lbl_hint.configure(text="")
            return
        c = self.by_id(cid)
        if not c:
            self.lbl_hint.configure(text="")
            return
        hk = c.get("hotkey") or "未绑定"
        extra = ""
        if c["id"] in self.conflicts:
            extra = f"　⚠ {self.conflicts[c['id']]}"
        speed = c.get("interval_ms") or 0
        speed_text = f"　·　单条间隔 {speed}ms" if speed else ""
        if not c.get("verified", True):
            speed_text += "　·　⚠ 未实机验证"
        self.lbl_hint.configure(text=f"{c['name']}　→　{c['code']}　·　快捷键 {hk}{speed_text}{extra}")

    def by_id(self, cid: str):
        return next((c for c in self.cheats if c["id"] == cid), None)

    def selected_id(self):
        sel = self.tree.selection()
        return sel[0] if sel else None

    def selected_ids(self) -> list[str]:
        """1.9-C：多选批量操作用；返回当前选中的秘籍 id 列表。"""
        return list(self.tree.selection())

    # -- 热键注册 ------------------------------------------------------------
    def apply_hotkeys(self):
        """统一入口：先清冲突，再整体注销/重注册（暂停时只留暂停键）。"""
        self.conflicts.clear()
        bindings, conflicts = build_bindings(
            self.cheats, self.settings.get("pause_hotkey", ""), include_cheats=not self.paused)
        self.conflicts.update(conflicts)
        self.engine.apply(bindings)
        self.lbl_state.configure(text="已暂停 · 仅暂停键生效…" if self.paused else "注册快捷键…")

    def _on_hotkeys_applied(self, results: dict, id_map: dict):
        self.hotkey_owner = id_map
        occupied = []
        denied = []
        occupied_ids = []
        cheat_results = {k: v for k, v in results.items() if k != PAUSE_ID}
        for cheat_id, (ok, err) in cheat_results.items():
            if ok:
                continue
            c = self.by_id(cheat_id)
            combo = (c or {}).get("hotkey", "?")
            if err == ERROR_HOTKEY_ALREADY_REGISTERED:
                self.conflicts[cheat_id] = f"系统或其他程序已占用 {combo}"
                occupied.append(combo)
                occupied_ids.append(cheat_id)
                if combo:
                    self._avoid.add(combo)   # 记住它真的被占着，后续自动分配不再选它
            elif err == ERROR_ACCESS_DENIED:
                self.conflicts[cheat_id] = "权限不足（目标程序可能以管理员运行）"
                denied.append(combo)
            else:
                self.conflicts[cheat_id] = f"注册失败，错误码 {err}（{combo}）"
                occupied.append(combo)

        pause_res = results.get(PAUSE_ID)
        pause_combo = self.settings.get("pause_hotkey", "")
        if pause_res and not pause_res[0]:
            self.conflicts[PAUSE_ID] = f"暂停键 {pause_combo} 注册失败（错误码 {pause_res[1]}）"
        self.refresh_tree()

        ok_count = sum(1 for ok, _ in cheat_results.values() if ok)
        cheat_conflicts = {k: v for k, v in self.conflicts.items() if k != PAUSE_ID}
        if PAUSE_ID in self.conflicts:
            self.log(f"暂停键不可用：{self.conflicts[PAUSE_ID]}。"
                     f"请换一个组合（如 Ctrl+Alt+Shift+P）。", "warn")
        if self.paused:
            self.lbl_state.configure(text=f"⏸ 已暂停（{pause_combo} 恢复）")
        elif cheat_conflicts:
            msg = f"⚠ {len(cheat_conflicts)} 个快捷键不可用（{ok_count} 个生效）"
            self.lbl_state.configure(text=msg)
            for cid, reason in cheat_conflicts.items():
                c = self.by_id(cid)
                self.log(f"快捷键冲突：{c['name'] if c else cid} — {reason}", "warn")
            if occupied:
                self.log("提示：被占用的组合键通常是输入法、显卡/录屏软件或另一个同类工具占着，"
                         "双击该行换成别的键即可。", "info")
            if denied:
                self.log("提示：权限不足 → 请右键本工具以管理员身份运行一次。", "warn")
        else:
            self.lbl_state.configure(text=f"✔ {ok_count} 个快捷键全部生效")
            self.log(f"快捷键注册完成，共 {ok_count} 个生效。", "ok")

        # 自动分配后仍有键被系统占着 → 换下一批候选键，最多 2 轮（避免死循环）
        fix, self._auto_fix = self._auto_fix, None
        if fix and fix["round"] < 2 and occupied_ids:
            targets = [cid for cid in occupied_ids if self.by_id(cid)]
            if targets:
                rnd = fix["round"] + 1
                self.log(f"仍有 {len(targets)} 个键被系统占用，自动换下一批候选（第 {rnd} 轮）。", "info")
                self.root.after(10, lambda t=targets, r=rnd: self._assign_free_combos(t, r))

    # -- 冲突处置 -----------------------------------------------------------
    def _popup_row_menu(self, event):
        row = self.tree.identify_row(event.y)
        # 1.9-C：右键已选中的行时保留多选，别把批量选择打回单行
        if row and row not in self.tree.selection():
            self.tree.selection_set(row)
        try:
            n = len(self.selected_ids())
            self.menu_row.entryconfigure(self.menu_row.index("end"),
                                         label=f"批量操作（已选 {n} 条）" if n > 1
                                         else "批量操作（选中多条时可用）")
            self.menu_row.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu_row.grab_release()

    def copy_code(self):
        cid = self.selected_id()
        c = self.by_id(cid) if cid else None
        if not c:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(c["code"])
        self.log(f"已复制代码 {c['code']}", "ok")

    def fix_selected_conflict(self):
        cid = self.selected_id()
        if not cid or not self.by_id(cid):
            return
        if not self._assign_free_combos([cid], 0):
            messagebox.showinfo("没有空闲键",
                                "候选组合键（F1–F11 及 Shift/Ctrl/Ctrl+Shift/Alt 组合）都已被占用，"
                                "请双击该行手动指定一个。", parent=self.root)

    def auto_fix_conflicts(self):
        ids = [cid for cid in self.conflicts if cid != PAUSE_ID and self.by_id(cid)]
        if not ids:
            self.log("当前没有需要处置的快捷键冲突。", "info")
            self.show_toast("没有冲突项", "ok")
            return
        changed = self._assign_free_combos(ids, 0)
        if changed:
            self.log(f"为 {len(changed)} 个冲突项分配了空闲键，正在重新注册…", "info")
        else:
            self.log("没有可用的空闲组合键了。", "warn")

    def _assign_free_combos(self, ids, round_no: int = 0):
        """给指定条目挑空闲键并重注册；返回 [(名称, 新键)]。"""
        changed = []
        for cid in ids:
            c = self.by_id(cid)
            if not c:
                continue
            avoid = list(self._avoid)
            if cid in self.conflicts:      # 已知有问题的键必须换掉，不能原地打转
                avoid.append(c.get("hotkey") or "")
            combo = pick_free_combo(self.cheats, self.settings.get("pause_hotkey", ""),
                                    avoid, exclude_id=cid)
            if not combo:
                break
            if combo == (c.get("hotkey") or ""):
                continue
            changed.append((c["name"], combo))
            c["hotkey"] = combo
        if not changed:
            return changed
        self._auto_fix = {"ids": list(ids), "round": round_no}
        self.persist()
        self.apply_hotkeys()
        for name, combo in changed:
            self.log(f"冲突处置：「{name}」→ {combo}", "ok")
        return changed

    # -- 暂停 / 恢复 ---------------------------------------------------------
    def toggle_pause(self):
        self.paused = not self.paused
        self._update_pause_ui()
        if self.paused:
            # 暂停 = 立刻停手：先中止在飞发送，再注销热键。
            # 1.6 只注销热键，正在打的那条会继续打完——"暂停"语义不成立。
            self._stop.set()
        self.apply_hotkeys()
        combo = self.settings.get("pause_hotkey", "Ctrl+Alt+P")
        if self.paused:
            self.log(f"⏸ 已暂停：全部秘籍热键已注销（按 {combo} 恢复）。", "warn")
            self.show_toast(f"⏸ 已暂停热键 · {combo} 恢复", "warn")
        else:
            self.log(f"▶ 已恢复：秘籍热键重新生效（按 {combo} 可再次暂停）。", "ok")
            self.show_toast("▶ 热键已恢复", "ok")

    def _update_pause_ui(self):
        if self.paused:
            self.btn_pause.configure(text="▶ 恢复热键", style="Danger.TButton")
        else:
            self.btn_pause.configure(text="⏸ 暂停热键", style="TButton")
        try:
            self.tray.update_tip(self.paused)   # 托盘悬停文字同步暂停态
        except Exception:
            pass

    # -- 发送 ---------------------------------------------------------------
    def _fg_ok(self, keywords: list[str]) -> bool:
        fg = user32.GetForegroundWindow() or 0
        if fg and self.game_info[0] and fg == self.game_info[0]:
            return True  # 游戏窗口自动检测命中（进程名匹配），优先于关键字
        if not keywords:
            return True
        title, exe = foreground_info()
        hay = f"{title} {exe}".lower()
        return any(k in hay for k in keywords)

    def send_by_id(self, cheat_id: str):
        c = self.by_id(cheat_id)
        if c:
            self._start_send(c, force=False, from_hotkey=True)

    def send_selected(self):
        cid = self.selected_id()
        if not cid:
            return
        c = self.by_id(cid)
        if c:
            self._start_send(c, force=False, from_hotkey=False)

    def _start_send(self, cheat: dict, force: bool, from_hotkey: bool):
        # 去抖：同一秘籍在 debounce_ms 内连按只发一次（手抖/键盘连击不该打两遍）
        cid = cheat.get("id", "")
        gap_ms = _safe_int(self.settings.get("debounce_ms"), 250, 0, 2000)
        now = time.time()
        last = self._last_send.get(cid, 0.0)
        if gap_ms and now - last < gap_ms / 1000.0:
            self.log(f"↺ 忽略连击：「{cheat.get('name', '')}」{int((now - last) * 1000)}ms 内重复触发",
                     "info")
            return

        if not self.sending.acquire(blocking=False):
            # 静默丢弃是 1.6 的坑：用户以为没反应，其实是被丢掉了。改为双通道提示。
            msg = "上一次发送还没结束，已忽略这次请求（按 Esc 可停止正在发送的那条）。"
            self.log(msg, "warn")
            self.show_toast("⚠ 正在发送，已忽略本次请求", "warn")
            return

        self._last_send[cid] = now
        self._stop.clear()
        # 注意：Tk 变量只能在主线程读，这里先取好参数再交给工作线程
        params = self._read_params(force)
        self._inflight = cid
        self._set_sending_ui(True)
        try:
            threading.Thread(target=self._send_worker, args=(cheat, params), daemon=True).start()
        except Exception as exc:
            # 线程没起来必须还锁，否则此后所有发送都会静默丢弃
            self.sending.release()
            self._inflight = ""
            self._set_sending_ui(False)
            self.log(f"✖ 无法启动发送线程：{exc}", "warn")

    def on_send_button(self):
        """发送中按钮变成「停止」，同一位置切换，不新增控件（工具栏宽度很紧）。"""
        if self._inflight or self.sending.locked():
            self.stop_send()
        else:
            self.send_selected()

    def stop_send(self):
        if not (self._inflight or self.sending.locked()):
            return
        self._stop.set()
        self.log("⏹ 正在停止发送…", "warn")

    def _on_escape(self):
        """Esc 优先用于停发送；没有发送时才清空搜索（1.6 的行为保留）。"""
        if self._inflight or self.sending.locked():
            self.stop_send()
            return
        self.clear_search()

    def _set_sending_ui(self, active: bool):
        try:
            if active:
                self.btn_send.configure(text="■ 停止 (Esc)", style="Danger.TButton")
            else:
                self.btn_send.configure(text="▶ 发送所选 (Enter)", style="Accent.TButton")
        except Exception:
            pass

    def _read_params(self, force: bool) -> dict:
        target_hwnd = user32.GetForegroundWindow() or 0
        is_test = bool(target_hwnd) and target_hwnd == self.test_hwnd
        t = self._active_target or {}       # 2.0：目标规则解析结果，缺省空 = 旧行为
        return {
            "interval": max(10, int(self.var_delay.get() or 45)),
            "pre": max(0, int(self.settings.get("pre_delay_ms", 180))),
            "keywords": [k.strip().lower() for k in (self.var_kw.get() or "").split(",") if k.strip()],
            "check_fg": ((not force) and bool(self.var_fg.get())
                         and bool(t.get("require_foreground", True)) and not is_test),
            "release_mods": bool(self.settings.get("release_modifiers", True)),
            "uppercase": bool(self.settings.get("uppercase", False)),
            "disable_ime": bool(t.get("disable_ime", self.settings.get("disable_ime", True))),
            "strategy_ref": str(t.get("strategy") or ""),
        }

    def _send_worker(self, cheat: dict, params: dict):
        """工作线程：只负责校验 + IME 守卫 + 调用发送引擎 + 上报结果。

        真正的按键循环在 `vcct.sender.type_text`（可单测、可中断）。
        本函数绝不碰 Tk 控件——结果一律走 events 队列回主线程。
        """
        code = cheat.get("code", "")
        name = cheat.get("name", code)
        cid = cheat.get("id", "")
        total = len(code)
        check_fg = params["check_fg"]
        # 单条覆盖优先（1.6）：0 = 跟随全局
        interval = _safe_int(cheat.get("interval_ms"), 0, 20, 300) or params["interval"]
        # 2.0 策略引擎：默认 fixed 且所有覆盖值为 None → 与 1.9.1 参数逐项一致
        named = self.settings.get("strategies") or {}
        strategy = resolve_strategy(named, cheat)
        ref = params.get("strategy_ref")
        if ref and not cheat.get("strategy") and ref in named:
            strategy = normalize_strategy(named[ref])   # 目标规则引用的具名策略
        sp = plan_send(strategy, code, interval, params["pre"], params["uppercase"])
        t0 = time.perf_counter()

        def history(result: str, detail: str):
            """1.8-I：只往队列投一条纯数据记录，绝不在这里碰 store / Tk。"""
            self.events.put(("history", {
                "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "name": name, "code": code, "profile": self.active_profile,
                "elapsed": round(time.perf_counter() - t0, 3),
                "result": result, "detail": detail,
            }))

        sent = 0
        try:
            # 权限不匹配时 SendInput 会"成功但不生效"，是最难自查的失败模式：必须提前拦下并说明
            if self._permission_mismatch_live():
                msg = ("⚠ 游戏以管理员身份运行，本工具不是：Windows 会**静默丢弃**注入的按键"
                       "（SendInput 仍报成功，所以看起来毫无反应）。"
                       "请点右上角「以管理员身份重启」，或右键 exe →「以管理员身份运行」。")
                self.log(msg, "warn", from_thread=True)
                self.events.put(("toast", "⚠ 权限不匹配：请以管理员身份重启工具", "warn"))
                append_log(f"SEND fail code={code} reason=uipi_blocked "
                           f"game_admin=1 self_admin=0", "WARN")
                history("fail", "权限不匹配（UIPI 静默拦截）")
                return

            if check_fg and not self._fg_ok(params["keywords"]):
                title, _ = foreground_info()
                msg = (f"⚠ 前台窗口不是目标游戏（当前：{title or '未知'}；"
                       f"目标关键字：{'、'.join(params['keywords']) or '未设置'}），本次未发送。"
                       f"点「拾取当前窗口」或关闭前台校验。")
                self.log(msg, "warn", from_thread=True)
                self.events.put(("toast", f"⚠ 未在前台：{title or '未知窗口'}", "warn"))
                append_log(f"SEND fail code={code} reason=not_foreground title={title!r}", "WARN")
                history("fail", f"前台不匹配（当前 {title or '未知'}）")
                return

            target_hwnd = user32.GetForegroundWindow() or 0

            # 2.0 前置钩子：默认关闭；启用时返回 False 可否决本次发送
            if not self.hooks.fire_before({"hwnd": target_hwnd}, cheat):
                self.log("⏹ 前置钩子否决了本次发送。", "warn", from_thread=True)
                history("fail", "前置钩子否决")
                return

            if params["release_mods"]:
                release_modifiers()

            sent_total = 0
            attempt = 0
            with ImeGuard(target_hwnd, params["disable_ime"]):
                while True:
                    remaining = code[sent_total:]
                    sp = plan_send(strategy, remaining, interval, params["pre"],
                                   params["uppercase"], attempt)
                    try:
                        sent = type_text(
                            sp, self._stop,
                            send_key=send_key, sleep=time.sleep, lookup_vk=vk_for_char,
                            check_target=(lambda: user32.GetForegroundWindow() == target_hwnd)
                            if check_fg else None,
                        )
                        sent_total += sent
                        break
                    except SendError as exc:
                        # 2.0 adaptive：只对"丢字/失焦"这类失败补发剩余字符，
                        # 固定/爆发策略永不重试（should_retry 恒 False）。
                        sent_total += exc.sent
                        if not should_retry(strategy, attempt, sent_total, total):
                            raise
                        attempt += 1
                        self.log(f"⟳ 自适应重试 {attempt}：已发 {sent_total}/{total}，"
                                 f"间隔自动加长…", "warn", from_thread=True)
            sent = sent_total

            elapsed = time.perf_counter() - t0
            self._log_send_quality(code, sent, total, sp, elapsed)
            self.log(f"✔ 已输入「{name}」 {code}", "ok", from_thread=True)
            self.events.put(("toast", f"✔ {name} · {code}", "ok"))
            self.events.put(("stats", cid, code))
            history("ok", f"已发 {sent}/{total} 字符")
        except SendCancelled as exc:
            elapsed = time.perf_counter() - t0
            self.log(f"⏹ 已停止「{name}」：发到第 {exc.sent}/{exc.total} 个字符。", "warn",
                     from_thread=True)
            self.events.put(("toast", f"⏹ 已停止 {exc.sent}/{exc.total}", "warn"))
            append_log(f"SEND cancel code={code} sent={exc.sent}/{exc.total} "
                       f"elapsed={elapsed:.3f}s", "WARN")
            history("cancel", f"停在第 {exc.sent}/{exc.total} 字符")
        except SendError as exc:
            self.log(f"⚠ {exc.reason}（已发 {exc.sent}/{exc.total}）", "warn", from_thread=True)
            self.events.put(("toast", f"⚠ {exc.reason}", "warn"))
            append_log(f"SEND fail code={code} reason={exc.reason} "
                       f"sent={exc.sent}/{exc.total}", "WARN")
            history("fail", f"{exc.reason}（已发 {exc.sent}/{exc.total}）")
        except OSError as exc:
            self.log(f"✖ 键盘注入失败：{exc}（若游戏以管理员运行，请同样以管理员运行本工具）",
                     "warn", from_thread=True)
            append_log(f"SEND fail code={code} reason=oserror {exc}", "WARN")
            history("fail", f"键盘注入失败：{exc}")
        except Exception as exc:
            self.log(f"✖ 发送异常：{exc}", "warn", from_thread=True)
            append_log(f"SEND fail code={code} reason=exception {exc}", "WARN")
            history("fail", str(exc))
        finally:
            self.events.put(("send_done", cid))
            self.sending.release()
            # 2.0 后置钩子：成功与所有失败路径都会走到这里（幂等由钩子自身保证）
            self.hooks.fire_after({"code": code, "profile": self.active_profile,
                                   "sent": sent, "total": total})

    @staticmethod
    def _log_send_quality(code: str, sent: int, total: int, sp: SendParams, elapsed: float):
        """记录计划时长与实际时长；偏差过大说明节奏被系统拖慢（游戏卡 / CPU 忙）。"""
        planned = (sp.pre_delay_ms + total * sp.interval_ms) / 1000.0
        dev = (elapsed - planned) / planned if planned > 0 else 0.0
        append_log(f"SEND ok code={code} sent={sent}/{total} planned={planned:.3f}s "
                   f"actual={elapsed:.3f}s dev={dev:+.0%}")
        if abs(dev) > 0.15:
            append_log(f"SEND WARN 节奏偏差 {dev:+.0%}（计划 {planned:.3f}s / "
                       f"实际 {elapsed:.3f}s），若出现丢字请调大间隔", "WARN")

    # -- 增删改 -------------------------------------------------------------
    def add_cheat(self):
        dlg = CheatDialog(self.root, self, None)
        self.root.wait_window(dlg)
        if not dlg.result:
            return
        if any(c["code"] == dlg.result["code"] for c in self.cheats):
            messagebox.showwarning("代码重复", "已存在同一条秘籍代码。", parent=self.root)
            return
        self.cheats.append(dlg.result)
        self.persist()
        self.refresh_tree()
        self.apply_hotkeys()
        self.log(f"已添加「{dlg.result['name']}」", "ok")

    def edit_selected(self):
        cid = self.selected_id()
        c = self.by_id(cid) if cid else None
        if not c:
            return
        idx = self.cheats.index(c)
        dlg = CheatDialog(self.root, self, c)
        self.root.wait_window(dlg)
        if not dlg.result:
            return
        dup = [x for x in self.cheats if x["code"] == dlg.result["code"] and x["id"] != c["id"]]
        if dup:
            messagebox.showwarning("代码重复", f"「{dup[0]['name']}」已使用该代码。", parent=self.root)
            return
        self.cheats[idx] = dlg.result
        self.persist()
        self.refresh_tree()
        self.apply_hotkeys()

    def delete_selected(self):
        cid = self.selected_id()
        c = self.by_id(cid) if cid else None
        if not c:
            return
        if not messagebox.askyesno("删除秘籍", f"确定删除「{c['name']}」？", parent=self.root):
            return
        self._undo = {"kind": "cheat", "profile": self.active_profile,
                      "index": self.cheats.index(c), "cheat": dict(c)}
        self.cheats.remove(c)
        self.persist()
        self.refresh_tree()
        self.apply_hotkeys()
        self.log(f"已删除「{c['name']}」（可点「撤销」或 Ctrl+Z 恢复）", "warn")

    def clear_search(self):
        if self.var_search.get():
            self.var_search.set("")
            self.refresh_tree()
        return "break"

    def undo_last(self):
        """撤销最近一次删除（仅保留一步）。"""
        if isinstance(self.root.focus_get(), (tk.Entry, ttk.Entry)):
            return  # 正在输入框里，交给文本框自己的撤销
        u = self._undo
        if not u:
            self.log("没有可撤销的操作（只保留最近一次删除）。", "info")
            return
        self._undo = None
        if u["kind"] == "batch_cheats":
            # 1.9-C：恢复整份方案快照（批量删除一步全回来）
            prof = next((p for p in self.store["profiles"] if p["name"] == u["profile"]), None)
            if prof is None:
                self.log("撤销失败：原方案已不存在。", "warn")
                return
            prof["cheats"][:] = u["snapshot"]
            self.active_profile = prof["name"]
            self.cheats = prof["cheats"]
            self.var_profile.set(self.active_profile)
            self._refresh_profile_choices()
            self.persist()
            self.refresh_tree()
            self.apply_hotkeys()
            self.log(f"已撤销批量删除：方案「{prof['name']}」恢复 {len(u['snapshot'])} 条。", "ok")
        elif u["kind"] == "cheat":
            prof = next((p for p in self.store["profiles"] if p["name"] == u["profile"]), None)
            if prof is None:
                self.log("撤销失败：原方案已不存在。", "warn")
                return
            if prof["name"] != self.active_profile:
                self.active_profile = prof["name"]
                self.cheats = prof["cheats"]
                self.var_profile.set(self.active_profile)
                self._refresh_profile_choices()
            idx = min(u["index"], len(prof["cheats"]))
            prof["cheats"].insert(idx, u["cheat"])
            self.persist()
            self.refresh_tree()
            self.apply_hotkeys()
            self.log(f"已撤销删除：「{u['cheat']['name']}」已恢复。", "ok")
        elif u["kind"] == "profile":
            prof = u["profile"]
            name, i = prof["name"], 2
            while any(p["name"] == name for p in self.store["profiles"]):
                name = f"{prof['name']} ({i})"
                i += 1
            prof["name"] = name
            self.store["profiles"].append(prof)
            self.active_profile = name
            self.cheats = prof["cheats"]
            self.persist()
            self.var_profile.set(name)
            self._refresh_profile_choices()
            self.refresh_tree()
            self.apply_hotkeys()
            self.log(f"已撤销删除：方案「{name}」已恢复。", "ok")

    def move(self, delta: int):
        cid = self.selected_id()
        c = self.by_id(cid) if cid else None
        if not c:
            return
        i = self.cheats.index(c)
        j = i + delta
        if 0 <= j < len(self.cheats):
            self.cheats[i], self.cheats[j] = self.cheats[j], self.cheats[i]
            self.persist()
            self.refresh_tree()

    def reset_defaults(self):
        if not messagebox.askyesno("恢复默认",
                                   "将用内置的 28 条常用秘籍替换当前方案，自定义内容会丢失。继续？",
                                   parent=self.root):
            return
        fresh = template_cheats(DEFAULT_GAME)   # 1.9：带上 verified / game 字段
        self.cheats[:] = fresh  # 原地替换，保持与 store 内列表的引用关系
        self.persist()
        self.refresh_tree()
        self.apply_hotkeys()
        self.log("已恢复默认秘籍表。", "ok")

    # -- 方案组 -------------------------------------------------------------
    def _refresh_profile_choices(self):
        names = [p["name"] for p in self.store["profiles"]]
        self.cbo_profile.configure(values=names)
        if self.var_profile.get() != self.active_profile:
            self.var_profile.set(self.active_profile)

    def switch_profile(self, *_):
        name = self.var_profile.get()
        if name == self.active_profile:
            return
        prof = next((p for p in self.store["profiles"] if p["name"] == name), None)
        if not prof:
            return
        self.active_profile = name
        self.cheats = prof["cheats"]
        self.var_group_filter.set("全部")
        self._undo = None  # 撤销栈绑定当前方案，切换即清空，避免恢复到别的方案
        self.persist()
        self.refresh_tree()
        self.apply_hotkeys()
        self.log(f"已切换到方案「{name}」（{len(self.cheats)} 条，快捷键已重新注册）。", "ok")

    def new_profile(self):
        name = simpledialog.askstring("新建方案", "方案名称：",
                                      initialvalue=f"方案 {len(self.store['profiles']) + 1}",
                                      parent=self.root)
        if not name:
            return
        name = name.strip()
        if not name:
            return
        if any(p["name"] == name for p in self.store["profiles"]):
            messagebox.showwarning("名称重复", "已有同名方案。", parent=self.root)
            return
        copy = [dict(c) for c in self.cheats]
        current = next((p for p in self.store["profiles"] if p["name"] == self.active_profile), {})
        self.store["profiles"].append({"name": name, "cheats": copy,
                                       "game": current.get("game") or DEFAULT_GAME})
        self.persist()
        self.var_profile.set(name)
        self.switch_profile()
        self._refresh_profile_choices()

    def rename_profile(self):
        if self.active_profile == "默认":
            messagebox.showinfo("不可重命名", "内置「默认」方案请用「新建副本」复制后再改。",
                                parent=self.root)
            return
        name = simpledialog.askstring("重命名方案", "新名称：",
                                      initialvalue=self.active_profile, parent=self.root)
        if not name or name.strip() == self.active_profile:
            return
        name = name.strip()
        if any(p["name"] == name for p in self.store["profiles"]):
            messagebox.showwarning("名称重复", "已有同名方案。", parent=self.root)
            return
        prof = next(p for p in self.store["profiles"] if p["name"] == self.active_profile)
        prof["name"] = name
        self.active_profile = name
        self.persist()
        self._refresh_profile_choices()
        self.log(f"方案已重命名为「{name}」。", "ok")

    def delete_profile(self):
        if len(self.store["profiles"]) <= 1:
            messagebox.showinfo("不能删除", "至少保留一个方案。", parent=self.root)
            return
        if not messagebox.askyesno("删除方案",
                                   f"确定删除方案「{self.active_profile}」？", parent=self.root):
            return
        prof = next(p for p in self.store["profiles"] if p["name"] == self.active_profile)
        self._undo = {"kind": "profile",
                      "profile": {"name": prof["name"], "cheats": [dict(c) for c in prof["cheats"]]}}
        self.store["profiles"] = [p for p in self.store["profiles"] if p["name"] != self.active_profile]
        self.active_profile = self.store["profiles"][0]["name"]
        self.cheats = self.store["profiles"][0]["cheats"]
        self.persist()
        self._refresh_profile_choices()
        self.var_profile.set(self.active_profile)
        self.refresh_tree()
        self.apply_hotkeys()
        self.log(f"方案已删除，当前为「{self.active_profile}」（可 Ctrl+Z 撤销）。", "warn")

    # -- 参数预设 / 导入导出 --------------------------------------------------
    def apply_preset(self, name: str):
        preset = PRESETS.get(name)
        if not preset:
            return
        self.settings.update(preset)
        self.var_delay.set(int(preset["char_interval_ms"]))
        self.persist()
        self.log(f"已套用「{name}」预设：每字间隔 {preset['char_interval_ms']}ms、"
                 f"前置延迟 {preset['pre_delay_ms']}ms。", "ok")

    def export_profile(self):
        path = filedialog.asksaveasfilename(
            title="导出方案", defaultextension=".json",
            initialfile=f"{self.active_profile}.json",
            filetypes=[("JSON", "*.json")], parent=self.root)
        if not path:
            return
        payload = {
            "app": STORE_APP,
            "version": STORE_VERSION,
            "profile": {"name": self.active_profile, "cheats": self.cheats},
            "settings": self.settings,
        }
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
            self.log(f"已导出方案到 {path}", "ok")
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc), parent=self.root)

    def export_bundle(self):
        stamp = time.strftime("%Y%m%d")
        path = filedialog.asksaveasfilename(
            title="导出整包", defaultextension=".json",
            initialfile=f"VC-Cheat-Typer-整包-{stamp}.json",
            filetypes=[("JSON", "*.json")], parent=self.root)
        if not path:
            return
        payload = bundle_payload({
            "settings": self.settings, "active_profile": self.active_profile,
            "profiles": self.store["profiles"], "stats": self.stats,
            "today": self.store.get("today"),
        })
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc), parent=self.root)
            return
        total = sum(len(p["cheats"]) for p in self.store["profiles"])
        self.log(f"已导出整包：{len(self.store['profiles'])} 个方案 / {total} 条秘籍 → {path}", "ok")
        self.show_toast("✔ 整包已导出", "ok")

    def import_bundle(self):
        path = filedialog.askopenfilename(title="导入整包（覆盖当前全部方案与设置）",
                                          filetypes=[("JSON", "*.json")], parent=self.root)
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except Exception as exc:
            messagebox.showerror("导入失败", f"文件不是有效的 JSON：{exc}", parent=self.root)
            return
        store, err = parse_bundle(raw)
        if store is None:
            messagebox.showwarning("导入失败", err, parent=self.root)
            return
        total = sum(len(p["cheats"]) for p in store["profiles"])
        if not messagebox.askyesno(
                "确认覆盖",
                f"将用整包内容覆盖当前所有方案与设置：\n\n"
                f"方案 {len(store['profiles'])} 个 / 秘籍 {total} 条\n"
                f"导出时间：{raw.get('exported_at') or '未知'}\n\n"
                f"当前内容会先记入 cheats.bak.json，可再回滚。继续？",
                parent=self.root):
            return
        self._undo = None
        self._adopt_store(store)
        self.persist()
        self.log(f"整包导入完成：{len(store['profiles'])} 个方案 / {total} 条秘籍，"
                 f"当前「{self.active_profile}」。", "ok")

    def import_profile(self):
        path = filedialog.askopenfilename(title="导入方案",
                                          filetypes=[("JSON", "*.json")], parent=self.root)
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except Exception as exc:
            messagebox.showerror("导入失败", f"文件不是有效的 JSON：{exc}", parent=self.root)
            return
        src = raw.get("profile") if isinstance(raw.get("profile"), dict) else raw
        cheats = [c for c in (_norm_cheat(i) for i in (src.get("cheats") or [])) if c]
        if not cheats:
            messagebox.showwarning("导入失败", "文件里没有可用的秘籍条目。", parent=self.root)
            return
        name = str(src.get("name") or "导入的方案").strip()
        base, i = name, 2
        while any(p["name"] == name for p in self.store["profiles"]):
            name = f"{base} ({i})"
            i += 1
        self.store["profiles"].append({"name": name, "cheats": cheats})
        self.persist()
        self._refresh_profile_choices()
        self.var_profile.set(name)
        self.switch_profile()
        self.log(f"已导入方案「{name}」（{len(cheats)} 条）。", "ok")

    # -- 设置持久化 ---------------------------------------------------------
    def _on_setting_change(self):
        self.settings["target_keywords"] = self.var_kw.get().strip()
        self.settings["require_foreground"] = bool(self.var_fg.get())
        self.settings["disable_ime"] = bool(self.var_ime.get())
        self.settings["show_toast"] = bool(self.var_toast.get())
        self.settings["close_to_tray"] = bool(self.var_tray.get())
        self.settings["auto_switch"] = bool(self.var_auto_switch.get())
        self.settings["hooks_enabled"] = bool(self.var_hooks.get())
        self.hooks.enabled = self.settings["hooks_enabled"]
        try:
            self.settings["char_interval_ms"] = int(self.var_delay.get())
        except Exception:
            pass
        self.persist()

    def persist(self):
        self.store["settings"] = self.settings
        self.store["stats"] = self.stats
        self.store["active_profile"] = self.active_profile
        save_store(self.store)

    # -- 其他交互 -----------------------------------------------------------
    def open_log(self):
        try:
            os.startfile(log_dir())  # noqa: S606 - 打开自己写的日志目录
            self.log(f"日志目录：{log_dir()}", "info")
        except Exception as exc:
            messagebox.showinfo("日志位置", f"{log_dir()}\n\n（自动打开失败：{exc}）", parent=self.root)

    def _adopt_store(self, store: dict):
        """整体接管一份 store（备份恢复用），保持 cheats 与 store 内列表的引用关系。"""
        self.store = store
        self.settings = store["settings"]
        self.stats = store["stats"]
        self.active_profile = store["active_profile"]
        prof = next((p for p in store["profiles"] if p["name"] == self.active_profile),
                    store["profiles"][0])
        self.active_profile = prof["name"]
        self.cheats = prof["cheats"]
        self.var_kw.set(self.settings.get("target_keywords", ""))
        self.var_fg.set(bool(self.settings.get("require_foreground", True)))
        self.var_ime.set(bool(self.settings.get("disable_ime", True)))
        self.var_delay.set(int(self.settings.get("char_interval_ms", 45)))
        self.var_toast.set(bool(self.settings.get("show_toast", True)))
        self.var_tray.set(bool(self.settings.get("close_to_tray", True)))
        self.var_auto_switch.set(bool(self.settings.get("auto_switch", True)))
        self.var_hooks.set(bool(self.settings.get("hooks_enabled", False)))
        self.hooks.enabled = bool(self.var_hooks.get())
        self.var_profile.set(self.active_profile)
        self.var_group_filter.set("全部")
        self._refresh_profile_choices()
        self.refresh_tree()
        self.apply_hotkeys()

    def restore_backup(self):
        bak = backup_path()
        if not os.path.exists(bak):
            messagebox.showinfo("没有备份",
                                f"还没有备份文件：\n{bak}\n\n"
                                f"备份会在每次保存配置时自动生成（保留上一版）。",
                                parent=self.root)
            return
        if not messagebox.askyesno("从备份恢复",
                                   f"将用上一版配置覆盖当前内容：\n{bak}\n\n"
                                   f"当前配置会先被备份，可再次回滚。继续？",
                                   parent=self.root):
            return
        store = load_store(bak)
        if last_load_warning():
            messagebox.showerror("备份不可用", last_load_warning(), parent=self.root)
            return
        self._undo = None
        self._adopt_store(store)
        self.persist()
        self.log(f"已从备份恢复（方案 {len(store['profiles'])} 个，"
                 f"当前「{self.active_profile}」{len(self.cheats)} 条）。", "ok")

    def pick_window(self):
        """拾取目标窗口。

        注意：点这个按钮的一瞬间，前台必然是**本工具自己**（按钮被点击就会激活窗口），
        所以不能用"当前前台"——那样永远拾到自己，前台校验必然失败。
        改为：优先用进程检测到的游戏窗口，其次用后台轮询记住的"最近一个非本工具前台窗口"。
        """
        hwnd, title, exe = self.game_info
        if not hwnd:
            hwnd, title, exe = self._last_foreign
        if not hwnd:
            messagebox.showinfo(
                "拾取失败",
                "还没有记录到游戏窗口。\n\n请先切到游戏窗口停留一两秒，再回来点这个按钮。",
                parent=self.root)
            return
        if self._is_own_window(hwnd):
            messagebox.showinfo("拾取失败", "取到的是本工具自己的窗口，请先切到游戏再试。",
                                parent=self.root)
            return
        kw = title if title else os.path.splitext(exe)[0]
        self.var_kw.set(kw)
        self._on_setting_change()
        self.log(f"目标窗口设为：{kw}（进程 {exe or '未知'}）", "ok")

    def _is_own_window(self, hwnd: int) -> bool:
        try:
            return bool(hwnd) and hwnd == user32.GetAncestor(self.root.winfo_id(), GA_ROOT)
        except Exception:
            return False

    def _poll_foreign_foreground(self):
        """后台记录"最近一个不是本工具的前台窗口"，供「拾取当前窗口」使用。"""
        try:
            fg = user32.GetForegroundWindow() or 0
            if fg and not self._is_own_window(fg):
                title, exe = foreground_info()
                if title or exe:
                    self._last_foreign = (fg, title, exe)
        except Exception:
            pass
        self.root.after(500, self._poll_foreign_foreground)

    def open_test_window(self):
        """注入自检：隐藏原生 Win32 窗口上跑一遍完整注入链路，结果弹窗展示"""
        self.log("注入自检运行中：会短暂弹出一个 1 秒的自检小窗…", "info")

        def worker():
            got_fg, got = raw_char_probe("ASPIRINE")
            ok = bool(got_fg and got.upper() == "ASPIRINE")
            self.events.put(("probe_done", ok, got_fg, got))

        threading.Thread(target=worker, daemon=True).start()

    def run_diagnose(self):
        """环境诊断：权限 / 前台 / 注入逐环节检查，结果弹窗展示。"""
        self.log("环境诊断运行中：会短暂弹出一个 1 秒的自检小窗…", "info")

        def worker():
            try:
                text = "\n".join(diagnose_report(include_probe=True))
                self.events.put(("diag_done", text))
            except Exception as exc:
                self.events.put(("diag_done", f"诊断失败：{exc}"))

        threading.Thread(target=worker, daemon=True).start()

    def _show_diag(self, text: str):
        win = tk.Toplevel(self.root)
        win.title("环境诊断")
        win.geometry("760x520")
        txt = tk.Text(win, wrap="word", font=("Consolas", 10), padx=10, pady=8,
                      bg="#f8fafc", relief="flat")
        txt.pack(fill="both", expand=True, padx=10, pady=(10, 4))
        txt.insert("1.0", text)
        txt.configure(state="disabled")
        ttk.Button(win, text="关闭", command=win.destroy).pack(pady=(4, 10))

    # -- 1.8 设置 / 向导 / 热键总览 -------------------------------------------
    def open_settings(self):
        if getattr(self, "_settings_dlg", None) and self._settings_dlg.winfo_exists():
            self._settings_dlg.lift()
            return
        self._settings_dlg = SettingsDialog(self.root, self)

    def open_wizard(self):
        try:
            OnboardWizard(self)
        except Exception as exc:
            self.log(f"向导打开失败：{exc}", "warn")

    def open_hotkey_overview(self):
        try:
            HotkeyOverview(self)
        except Exception as exc:
            self.log(f"热键总览打开失败：{exc}", "warn")

    def open_history(self):
        try:
            HistoryDialog(self)
        except Exception as exc:
            self.log(f"发送历史打开失败：{exc}", "warn")

    # -- 1.9 内容侧 -----------------------------------------------------------
    def open_pack_manager(self):
        PackManagerDialog(self)

    def open_text_import(self):
        TextImportDialog(self)

    def open_template_dialog(self):
        TemplateDialog(self)

    def export_v2_compat(self):
        """显式导出 v2 兼容配置（不覆盖当前 v3 文件，供旧版程序 / 回退使用）。"""
        path = filedialog.asksaveasfilename(
            title="导出 v2 兼容配置", defaultextension=".json", initialfile="cheats.v2.json",
            filetypes=[("JSON", "*.json")], parent=self.root)
        if not path:
            return
        try:
            export_v2(self.store, path)
            self.log(f"已导出 v2 兼容配置：{path}（1.6/1.7/1.8 可直接读取，v3 新字段已剥离）", "ok")
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc), parent=self.root)

    # -- 1.9-C 批量操作（多选） ------------------------------------------------
    def _batch_targets(self) -> list[dict]:
        ids = self.selected_ids()
        return [c for c in self.cheats if c["id"] in ids]

    def batch_set_group(self):
        targets = self._batch_targets()
        if not targets:
            self.log("请先选中至少一条秘籍（Ctrl/Shift 可多选）。", "info")
            return
        group = simpledialog.askstring("批量改分组",
                                       f"把选中的 {len(targets)} 条设为分组：\n"
                                       "（武器/生存/通缉/载具/改装/交通/天气/市民/自定义，可自填）",
                                       initialvalue=targets[0].get("group") or "自定义",
                                       parent=self.root)
        if not group or not group.strip():
            return
        group = group.strip()
        for c in targets:
            c["group"] = group
        self.persist()
        self.refresh_tree()
        self.log(f"批量分组：{len(targets)} 条 → 「{group}」。", "ok")

    def batch_assign_hotkeys(self):
        targets = self._batch_targets()
        if not targets:
            self.log("请先选中至少一条秘籍（Ctrl/Shift 可多选）。", "info")
            return
        # 1.9.1：只给「未绑定 / 已冲突」的条目换键。
        # 全选后若把 28 条正常热键也重排一遍，用户精心配过的键位会被无声打乱。
        ids = [c["id"] for c in targets
               if not c.get("hotkey") or c["id"] in self.conflicts]
        skipped = len(targets) - len(ids)
        if not ids:
            self.log(f"选中的 {skipped} 条都已有可用热键，无需重新分配。", "info")
            return
        changed = self._assign_free_combos(ids, 0)
        self.log(f"批量分配空闲热键：{len(changed)} 条已更新"
                 + (f"，另有 {skipped} 条已有可用热键保持不变" if skipped else "") + "。", "ok")

    def batch_set_interval(self):
        targets = self._batch_targets()
        if not targets:
            self.log("请先选中至少一条秘籍（Ctrl/Shift 可多选）。", "info")
            return
        value = simpledialog.askinteger("批量发送间隔",
                                        f"给选中的 {len(targets)} 条设置每字间隔 (ms)：\n"
                                        "0 = 跟随全局；范围 0–300",
                                        initialvalue=int(targets[0].get("interval_ms") or 0),
                                        minvalue=0, maxvalue=300, parent=self.root)
        if value is None:
            return
        for c in targets:
            c["interval_ms"] = int(value)
        self.persist()
        self.refresh_tree()
        self.log(f"批量间隔：{len(targets)} 条 → {value}ms。", "ok")

    def batch_delete(self):
        targets = self._batch_targets()
        if not targets:
            self.log("请先选中至少一条秘籍（Ctrl/Shift 可多选）。", "info")
            return
        names = [c["name"] for c in targets]
        preview = "\n".join(f"· {n}" for n in names[:10])
        if len(names) > 10:
            preview += f"\n· … 另有 {len(names) - 10} 条"
        if not messagebox.askyesno("批量删除",
                                   f"确定删除选中的 {len(targets)} 条秘籍？\n\n{preview}\n\n"
                                   "可点「撤销」一次性恢复（保留完整快照）。", parent=self.root):
            return
        # 完整快照而非逐条记录：批量删除必须一步全恢复
        self._undo = {"kind": "batch_cheats", "profile": self.active_profile,
                      "snapshot": [dict(c) for c in self.cheats]}
        ids = {c["id"] for c in targets}
        self.cheats[:] = [c for c in self.cheats if c["id"] not in ids]
        self.persist()
        self.refresh_tree()
        self.apply_hotkeys()
        self.log(f"批量删除 {len(targets)} 条（可点「撤销」恢复整个方案）。", "warn")

    def on_close(self, force: bool = False):
        """关窗：1.8 起默认最小化到托盘；force=True（托盘退出/提权重启）才真正退出。"""
        if not force and self.settings.get("close_to_tray", True) and self.tray.available:
            self.root.withdraw()
            self._tray_hint_once()
            return
        # 取消所有待执行的 after（事件泵 / 向导 / 轮询）：窗口销毁后它们再触发
        # 只会刷出一堆 "invalid command name" 的 Tcl 错误
        try:
            for aid in self.root.tk.call("after", "info"):
                try:
                    self.root.after_cancel(aid)
                except Exception:
                    pass
        except Exception:
            pass
        # 先停发送：不能让线程在窗口销毁后还往系统里注入按键
        self._stop.set()
        if self.sending.locked():
            deadline = time.time() + 0.3     # 20ms 切片下 300ms 足够走完一次取消
            while self.sending.locked() and time.time() < deadline:
                time.sleep(0.02)
        try:
            release_modifiers()               # 兜底松开修饰键：关掉程序也要能正常走路
        except Exception:
            pass
        try:
            self.settings["target_keywords"] = self.var_kw.get().strip()
            self.settings["require_foreground"] = bool(self.var_fg.get())
            self.settings["disable_ime"] = bool(self.var_ime.get())
            self.settings["show_toast"] = bool(self.var_toast.get())
            self.settings["close_to_tray"] = bool(self.var_tray.get())
            self.settings["auto_switch"] = bool(self.var_auto_switch.get())
            self.settings["hooks_enabled"] = bool(self.var_hooks.get())
            self.settings["char_interval_ms"] = int(self.var_delay.get())
            self.persist()
        except Exception:
            pass
        try:
            self.engine.shutdown()
        except Exception:
            pass
        try:
            self.tray.close()
        except Exception:
            pass
        append_log(f"退出 {APP_NAME} v{APP_VER}")
        self.root.destroy()


# ----------------------------------------------------------------------------
# 自检
# ----------------------------------------------------------------------------
def selftest() -> int:
    print(f"[1] {APP_NAME} v{APP_VER}  自检")
    ok = True

    size = ctypes.sizeof(INPUT)
    print(f"    sizeof(INPUT) = {size} (期望 40, 32 位下为 28)")
    ok &= size in (40, 28)

    for text, expect in [("F1", "F1"), ("Shift+F1", "Shift+F1"),
                         ("ctrl+shift+F12", "Ctrl+Shift+F12"), ("Alt+3", "Alt+3")]:
        parsed = parse_combo(text)
        got = format_combo(*parsed) if parsed else None
        print(f"    组合键 {text!r} -> {got!r}")
        ok &= got == expect
    ok &= parse_combo("Hello") is None
    print(f"    非法组合 'Hello' -> {parse_combo('Hello')}")

    store = load_store()
    cheats = next(p for p in store["profiles"] if p["name"] == store["active_profile"])["cheats"]
    print(f"[2] 默认秘籍 {len(cheats)} 条 / {len(store['profiles'])} 个方案，数据文件 {data_path()}")
    bad = [c["code"] for c in cheats if not re.fullmatch(r"[A-Z0-9]+", c["code"])]
    ok &= not bad
    hk = [c["hotkey"] for c in cheats if c["hotkey"]]
    dup = {h for h in hk if hk.count(h) > 1}
    print(f"    已绑定 {len(hk)} 条，重复快捷键 {dup or '无'}")
    ok &= not dup
    badbind = [h for h in hk if parse_combo(h) and not is_safe_binding(*parse_combo(h))]
    print(f"    不安全绑定 {badbind or '无'}")
    ok &= not badbind

    print("[2b] v1→v2 迁移 / 统计")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        legacy = os.path.join(td, "v1.json")
        with open(legacy, "w", encoding="utf-8") as fh:
            json.dump({"app": "vc-cheat-typer", "version": 1,
                       "settings": {"char_interval_ms": 80},
                       "cheats": [{"id": "x1", "name": "满血", "code": "ASPIRINE",
                                   "hotkey": "F4", "group": "生存", "note": ""}]}, fh, ensure_ascii=False)
        mig = load_store(legacy)
        mig_cheats = mig["profiles"][0]["cheats"]
        print(f"    迁移后: version={mig['version']} 方案={mig['active_profile']} "
              f"条目={len(mig_cheats)} 间隔={mig['settings']['char_interval_ms']}")
        ok &= (mig["version"] == STORE_VERSION and len(mig_cheats) == 1
               and mig_cheats[0]["code"] == "ASPIRINE"
               and mig["settings"]["char_interval_ms"] == 80)
        stats: dict = {}
        n1 = bump_stats(stats, "aspirine")
        n2 = bump_stats(stats, "ASPIRINE")
        print(f"    统计累计: {n1} -> {n2}（同一秘籍按 code 合并，大小写不敏感）")
        ok &= n1 == 1 and n2 == 2

    print("[2c] 配置容错与备份")
    with tempfile.TemporaryDirectory() as td:
        bad = os.path.join(td, "cheats.json")
        with open(bad, "w", encoding="utf-8") as fh:
            fh.write("{ this is not valid json")
        st = load_store(bad)
        quarantined = [n for n in os.listdir(td) if n.startswith("cheats.corrupt-")]
        print(f"    损坏文件隔离: {quarantined or '未生成'}；载入条目 {len(st['profiles'][0]['cheats'])}")
        ok &= bool(quarantined) and bool(last_load_warning())

        good = os.path.join(td, "cheats2.json")
        save_store(default_store(), good)
        save_store(default_store(), good)
        has_bak = os.path.exists(os.path.join(td, "cheats.bak.json"))
        print(f"    上一版备份: {'已生成 cheats.bak.json' if has_bak else '缺失'}")
        ok &= has_bak

    print("[2d] 暂停热键表 / 搜索过滤")
    bp, cp = build_bindings(default_cheats(), "Ctrl+Alt+P", include_cheats=False)
    print(f"    暂停时热键表 {len(bp)} 条（应为 1 条 = 暂停键）")
    ok &= len(bp) == 1 and bp[0][3] == PAUSE_ID and not cp
    bn, cn = build_bindings(default_cheats(), "Ctrl+Alt+P", include_cheats=True)
    print(f"    正常时热键表 {len(bn)} 条，冲突 {len(cn)}")
    ok &= len(bn) > 20 and not cn
    hits = filter_cheats(default_cheats(), "全部", "aspirine")
    print(f"    搜索 'aspirine'（代码）命中 {len(hits)} 条")
    ok &= len(hits) == 1
    hits2 = filter_cheats(default_cheats(), "全部", "满血")
    print(f"    搜索 '满血'（名称）命中 {len(hits2)} 条")
    ok &= len(hits2) >= 1
    both = filter_cheats(default_cheats(), "武器", "tools")
    print(f"    分组+搜索叠加（武器/tools）命中 {len(both)} 条，且全部属于武器组")
    ok &= len(both) == 3 and all((c.get("group") or "") == "武器" for c in both)
    only_car = filter_cheats(default_cheats(), "载具", "panzer")
    print(f"    分组+搜索叠加（载具/panzer）命中 {len(only_car)} 条")
    ok &= len(only_car) == 1 and only_car[0]["code"] == "PANZER"
    hits = filter_cheats(default_cheats(), "武器", "")
    print(f"    分组「武器」筛选 {len(hits)} 条")
    ok &= len(hits) >= 1

    print("[2e] 1.9 数据层：v1→v3 迁移 / 秘籍包 / 文本导入 / 模板")
    legacy = {"version": 1, "settings": {"char_interval_ms": 80},
              "cheats": [{"code": "ASPIRINE", "name": "满血"}]}
    v3 = migrate_store(legacy)
    print(f"    迁移链: v1 → v{v3['version']}，条目 {len(v3['profiles'][0]['cheats'])}")
    ok &= v3["version"] == STORE_VERSION and v3["settings"]["char_interval_ms"] == 80
    pack = make_pack("自检包", default_cheats()[:2])
    checked, _warns, err = validate_pack(pack, APP_VER)
    diff = diff_pack(pack, default_cheats())
    print(f"    秘籍包: 校验={'通过' if checked and not err else err}，diff {len(diff)} 条")
    ok &= bool(checked) and not err and len(diff) == 2
    parsed_items, parsed_errs = parse_pasted("满血,ASPIRINE,F4\n坏行!\n")
    print(f"    文本导入: 有效 {len(parsed_items)} 条 / 报错 {len(parsed_errs)} 行（行号 {[e['line'] for e in parsed_errs]}）")
    ok &= len(parsed_items) == 1 and len(parsed_errs) == 1 and parsed_errs[0]["line"] == 2
    print(f"    游戏模板: {len(TEMPLATE_NAMES)} 套 / VC 经典版 {len(template_cheats('VC 经典版'))} 条")
    ok &= len(TEMPLATE_NAMES) == 4 and len(template_cheats("VC 经典版")) == 28

    print("[2f] 1.9.1 新增：包热键避让 / 包版本比对 / 发送历史")
    conflict_pack = make_pack("自检包2", [{"code": "NEWA", "hotkey": "F4"}])
    fixed_pack, moves = auto_avoid_hotkeys(conflict_pack, default_cheats(), "Ctrl+Alt+P")
    print(f"    热键避让: {len(moves)} 条（F4→{moves[0]['new'] if moves else '无需改'}）")
    ok &= len(moves) == 1 and fixed_pack["cheats"][0]["hotkey"] != "F4"
    status, _ = compare_pack_record(conflict_pack, [])
    print(f"    包版本比对: 首次导入={status}")
    ok &= status == "new"
    hist = _norm_history([{"result": "ok", "elapsed": "bad"}, None] * 30)
    hist2 = _norm_history([{"result": "ok"}] * 60)
    print(f"    发送历史: 脏记录过滤后 {len(hist)} 条 / 60 条有效记录截断为 {len(hist2)} 条")
    ok &= len(hist) == 30 and len(hist2) == 50

    print("[2g] 2.0 通用输入平台：core / 目标 / 策略 / 钩子")
    import vcct.core as core_mod
    print(f"    core 公共 API {len(core_mod.__all__)} 项，配置 v{core_mod.STORE_VERSION}")
    ok &= hasattr(core_mod, "Target") and hasattr(core_mod, "plan_send")
    ts = normalize_targets([{"name": "VC", "match_type": "exe", "pattern": "gta-vc",
                             "profile_ref": "默认"}])
    hit = evaluate_targets(ts, "GTA", "gta-vc.exe")
    print(f"    目标规则: 命中 {hit['name'] if hit else '无'} → 方案 {resolve_target(hit or {}, default_store())['profile']}")
    ok &= bool(hit) and resolve_target(hit, default_store())["profile"] == "默认"
    p_fixed = plan_send(normalize_strategy(None), "ASPIRINE", 45, 180)
    p_retry = plan_send(normalize_strategy({"kind": "adaptive", "retries": 2}),
                        "RINE", 45, 180, attempt=1)
    print(f"    策略: fixed {p_fixed.interval_ms}ms/hold {p_fixed.hold_ms}ms；"
          f"adaptive 重试 {p_retry.interval_ms}ms")
    ok &= (p_fixed.interval_ms, p_fixed.hold_ms, p_fixed.pre_delay_ms) == (45, 22, 180)
    ok &= p_retry.interval_ms > p_fixed.interval_ms and p_retry.pre_delay_ms == 0
    bus = HookBus(enabled=False)
    bus.register_before("veto", lambda t, c: False)
    print(f"    钩子: 默认关闭时 fire_before={bus.fire_before({}, {})}（应为 True）")
    ok &= bus.fire_before({}, {}) is True

    print("[3] 前台窗口探测：", foreground_info())

    # 真实注入测试：隐藏原生 Win32 窗口验证"扫描码→VK→WM_CHAR"全链路
    # （不使用 Tk 文本框：Tk 自管 IME 上下文，中文环境下会收 VK_PACKET，结果不可信）
    print("[4] SendInput 实际注入测试（原生窗口）")
    got_fg, got = False, ""
    for attempt in range(3):
        got_fg, got = raw_char_probe("ASPIRINE")
        if got_fg and got.strip().upper() == "ASPIRINE":
            break
        if attempt < 2:
            time.sleep(0.3)      # 1.9.1：前台被抢时重试，避免自检偶发误报
    print(f"    取得前台: {got_fg} / 期望 'ASPIRINE'（不区分大小写）/ 实得 {got!r}")
    probe_ok = bool(got_fg and got.strip().upper() == "ASPIRINE")
    if not got_fg:
        # 前台被别的程序锁住时，探针根本没发送字符——这是"环境不允许"，
        # 不是注入失效，不能把它算成失败（1.9.1 修）。
        print("    ⚠ 未取得前台：本次探针未验证（其他窗口占用前台时常见），可在空闲桌面重跑。")
    elif not probe_ok:
        print("    ⚠ 未落字：请检查杀软是否拦截 SendInput、以及中文输入法是否被绕开。")
    ok &= (probe_ok or not got_fg)

    print("[5] 热键注册与冲突检测")
    events: queue.Queue = queue.Queue()
    engine = HotkeyEngine(events)
    engine.apply([(1, MOD_CONTROL | MOD_ALT, VK_BY_NAME["f1"], "a"),
                  (2, MOD_CONTROL | MOD_ALT, VK_BY_NAME["f1"], "b")])
    res = None
    deadline = time.time() + 3
    while time.time() < deadline:
        try:
            item = events.get(timeout=0.2)
        except queue.Empty:
            continue
        if item[0] == "hotkeys":
            res = item[1]
            break
    print(f"    结果 {res}")
    ok &= bool(res) and res.get("a", (False,))[0] is True and res.get("b") == (False, 1409)
    engine.shutdown()

    # GUI 冒烟
    print("[6] GUI 启动/关闭")
    try:
        app_root = tk.Tk()
        app = CheatApp(app_root)
        # 1.8 起 on_close 默认是"最小化到托盘"，自检要真正退出必须 force=True
        app_root.after(700, lambda: app.on_close(force=True))
        app_root.mainloop()
        print("    GUI 正常创建并退出")
    except Exception as exc:
        print("    GUI 异常:", exc)
        ok = False

    print("自检结果:", "全部通过" if ok else "有失败项")
    return 0 if ok else 1


def diagnose_report(include_probe: bool = True) -> list[str]:
    """生成环境诊断报告（纯文本行，供 CLI 打印或 GUI 弹窗展示）。

    典型用途：游戏不响应时先看这份报告——权限、前台、热键、注入逐环节定位。
    """
    out: list[str] = []

    def add(key: str, value) -> None:
        out.append(f"{key:<14}{value}")

    add("版本", f"{APP_NAME} v{APP_VER}")
    try:
        ver = sys.getwindowsversion()
        add("系统", f"Windows {ver.major}.{ver.minor} build {ver.build}")
    except Exception:
        add("系统", "未知")
    add("本工具", f"管理员={self_elevated()}　pid={os.getpid()}")
    add("配置", data_path())
    add("日志", log_file())

    hwnd, title, exe = find_game_window()
    pid = window_pid(hwnd) if hwnd else 0
    if hwnd:
        add("游戏窗口", f"{title!r} / {exe or '未知'} / hwnd={hwnd}")
        add("游戏进程", f"pid={pid}　管理员={process_elevated(pid)}")
        try:
            add("窗口状态", f"可见={bool(user32.IsWindowVisible(hwnd))}　"
                            f"最小化={bool(user32.IsIconic(hwnd))}")
        except Exception:
            pass
    else:
        add("游戏窗口", "未检测到（进程名需包含 gta-vc / vice）")

    fg_title, fg_exe = foreground_info()
    add("当前前台", f"{fg_title!r} / {fg_exe or '未知'}")

    settings = load_store()["settings"]
    kws = [k.strip().lower() for k in str(settings.get("target_keywords") or "").split(",") if k.strip()]
    add("目标关键字", "、".join(kws) or "未设置")
    if kws:
        hay = f"{fg_title} {fg_exe}".lower()
        add("前台是否匹配", any(k in hay for k in kws) or (bool(hwnd) and hwnd == user32.GetForegroundWindow()))

    # 关键结论：UIPI 静默拦截
    game_admin = process_elevated(pid) if pid else None
    me_admin = self_elevated()
    if game_admin and not me_admin:
        out.append("")
        out.append("⚠ 结论：游戏以管理员运行，本工具不是。")
        out.append("  Windows 的 UIPI 会静默丢弃注入的按键（SendInput 仍返回成功），")
        out.append("  表现就是「按了完全没反应、日志里也没有错误」。")
        out.append("  修复：右键 exe →「以管理员身份运行」（或用界面右上角的一键重启按钮）。")

    if include_probe:
        out.append("")
        out.append("注入探针（会抢前台约 1 秒）…")
        try:
            got_fg, got = raw_char_probe("VCCT")
            add("探针结果", f"取得前台={got_fg}　收到={got!r}（期望 'VCCT' 或不区分大小写）")
        except Exception as exc:
            add("探针结果", f"失败：{exc}")
    return out


def diagnose() -> int:
    """CLI 一键体检。会短暂抢占前台约 1 秒（注入探针需要一个真实窗口接收字符）。"""
    print("\n".join(diagnose_report()))
    return 0


def show_crash_dialog(title: str, detail: str) -> None:
    """2.0：崩溃弹窗的 UI 实现，注入给 core 的日志模块（实现层不依赖 tkinter）。"""
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, detail)
        root.destroy()
    except Exception:
        pass


def main() -> int:
    if not IS_WIN:
        print("本工具仅支持 Windows。")
        return 1
    if "--diagnose" in sys.argv:
        return diagnose()
    if "--selftest" in sys.argv:
        return selftest()
    if "--cli" in sys.argv:
        # 2.0-E：把 --cli 之后的参数原样转给 vcct.cli
        from vcct.cli import main as cli_main
        return cli_main(sys.argv[sys.argv.index("--cli") + 1:])
    if "--export-v2" in sys.argv:
        # 1.9：给仍用 1.6/1.7/1.8 的人留下显式降级出口（不覆盖当前 v3 配置）
        idx = sys.argv.index("--export-v2")
        out = (sys.argv[idx + 1] if len(sys.argv) > idx + 1
               and not sys.argv[idx + 1].startswith("--")
               else os.path.join(os.path.dirname(data_path()), "cheats.v2.json"))
        try:
            export_v2(load_store(), out)
            print(f"已导出 v2 兼容配置：{out}")
            return 0
        except Exception as exc:
            print(f"导出失败：{exc}")
            return 1

    install_crash_hooks(show_dialog=show_crash_dialog)   # 之后任何未捕获异常都会落盘到 logs/app.log
    append_log(f"===== 进程启动 pid={os.getpid()} =====")

    # 单实例：避免两个进程抢同一批全局热键，注册失败会让人误以为是"冲突"
    # 句柄必须保持存活直到进程退出，故赋值给变量（ruff F841 特批）
    mutex = kernel32.CreateMutexW(None, False, "Local\\VC_Cheat_Typer_SingleInstance")  # noqa: F841
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(APP_NAME, "工具已经在运行了，请查看任务栏 / 先关掉旧窗口。")
        root.destroy()
        return 0

    enable_dpi_awareness()   # 必须在 tk.Tk() 之前

    root = tk.Tk()
    forced = os.environ.get("VCCT_UI_SCALE", "").strip()
    if forced:  # 仅供三档缩放截图核对：让字体的像素尺寸按比例放大
        try:
            root.tk.call("tk", "scaling", 96.0 / 72.0 * float(forced))
        except Exception:
            pass
    CheatApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
