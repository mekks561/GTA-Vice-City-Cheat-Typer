# -*- coding: utf-8 -*-
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
    BARE_SAFE_VKS, MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, MOD_SHIFT, MOD_WIN, NAME_BY_VK, VK_BY_NAME,
    WM_APP_RELOAD, WM_HOTKEY, WM_QUIT, kernel32, user32,
)

def format_combo(mods: int, vk: int) -> str:
    parts = []
    if mods & MOD_CONTROL:
        parts.append("Ctrl")
    if mods & MOD_ALT:
        parts.append("Alt")
    if mods & MOD_SHIFT:
        parts.append("Shift")
    if mods & MOD_WIN:
        parts.append("Win")
    parts.append(NAME_BY_VK.get(vk, f"VK_{vk:02X}"))
    return "+".join(parts)


def parse_combo(text: str):
    """'Shift+F1' -> (mods, vk)；非法返回 None"""
    if not text:
        return None
    tokens = [t for t in re.split(r"[+\s]+", str(text).strip()) if t]
    if not tokens:
        return None
    mods, vk = 0, None
    for tok in tokens:
        low = tok.lower()
        if low in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif low == "alt":
            mods |= MOD_ALT
        elif low == "shift":
            mods |= MOD_SHIFT
        elif low in ("win", "meta", "super"):
            mods |= MOD_WIN
        elif low in VK_BY_NAME:
            vk = VK_BY_NAME[low]
        else:
            return None
    if vk is None:
        return None
    return (mods, vk)


def combo_signature(text: str):
    p = parse_combo(text)
    return p  # (mods, vk) 或 None


def is_safe_binding(mods: int, vk: int) -> bool:
    """无修饰键时只允许 F1-F24，否则会把正常打字吃掉"""
    return mods != 0 or vk in BARE_SAFE_VKS



# ----------------------------------------------------------------------------
# 全局热键引擎（独立线程 + 消息泵）
# ----------------------------------------------------------------------------
class HotkeyEngine:
    """
    RegisterHotKey 注册在消息泵线程上（hWnd=None，WM_HOTKEY 投递到该线程队列），
    因此重注册、注销都必须在这个线程里完成；主线程通过 PostThreadMessage 唤醒它。
    """

    def __init__(self, events: queue.Queue):
        self.events = events
        self.thread_id = 0
        self._ready = threading.Event()
        self._pending: list[tuple[int, int, int, str]] = []
        self._registered: list[int] = []
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, name="hotkey-pump", daemon=True)
        self._thread.start()
        self._ready.wait(3.0)

    # -- 供主线程调用 --------------------------------------------------------
    def apply(self, bindings: list[tuple[int, int, int, str]]) -> None:
        """bindings: [(hotkey_id, mods, vk, cheat_id), ...]"""
        with self._lock:
            self._pending = list(bindings)
        self._wake()

    def shutdown(self) -> None:
        if self.thread_id:
            user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)

    def _wake(self) -> None:
        """投递唤醒消息；失败重试一次（线程队列刚建立时可能还没就绪）"""
        if not self.thread_id:
            return
        for _ in range(3):
            if user32.PostThreadMessageW(self.thread_id, WM_APP_RELOAD, 0, 0):
                return
            time.sleep(0.02)

    # -- 消息泵线程 ----------------------------------------------------------
    def _run(self) -> None:
        msg = wt.MSG()
        self.thread_id = kernel32.GetCurrentThreadId()
        # 先强制创建本线程的消息队列，否则主线程此刻的 PostThreadMessage 会失败丢失
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # PM_NOREMOVE
        self._ready.set()
        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret == 0 or ret == -1:
                break
            if msg.message == WM_HOTKEY:
                self.events.put(("hotkey", int(msg.wParam)))
            elif msg.message == WM_APP_RELOAD:
                self._do_apply()
        for hid in self._registered:
            user32.UnregisterHotKey(None, hid)
        self._registered.clear()

    def _do_apply(self) -> None:
        with self._lock:
            req, self._pending = self._pending, []
        for hid in self._registered:
            user32.UnregisterHotKey(None, hid)
        self._registered.clear()

        results: dict[str, tuple[bool, int]] = {}
        id_map: dict[int, str] = {}
        for hid, mods, vk, cheat_id in req:
            ok = user32.RegisterHotKey(None, hid, mods | MOD_NOREPEAT, vk)
            err = 0 if ok else ctypes.get_last_error()
            results[cheat_id] = (bool(ok), err)
            if ok:
                self._registered.append(hid)
                id_map[hid] = cheat_id
        self.events.put(("hotkeys", results, id_map))


def build_bindings(cheats: list[dict], pause_combo: str = "",
                   include_cheats: bool = True) -> tuple[list, dict]:
    """构造热键注册表。

    返回 (bindings, conflicts)：
      bindings  = [(hotkey_id, mods, vk, owner_id), ...]
      conflicts = {owner_id: 原因}
    暂停时 include_cheats=False —— 只保留暂停键本身，其余全部不注册。
    """
    bindings: list[tuple[int, int, int, str]] = []
    conflicts: dict[str, str] = {}
    seen: dict[tuple[int, int], str] = {}

    if pause_combo:
        parsed = parse_combo(pause_combo)
        if parsed:
            bindings.append((PAUSE_HID, parsed[0], parsed[1], PAUSE_ID))
            seen[parsed] = PAUSE_ID
        else:
            conflicts[PAUSE_ID] = f"暂停键「{pause_combo}」无法解析"

    if not include_cheats:
        return bindings, conflicts

    hid = 1
    for c in cheats:
        combo = (c.get("hotkey") or "").strip()
        if not combo:
            continue
        parsed = parse_combo(combo)
        if not parsed:
            conflicts[c["id"]] = f"快捷键「{combo}」无法解析，已跳过"
            continue
        if parsed in seen:
            if seen[parsed] == PAUSE_ID:
                conflicts[c["id"]] = f"与暂停键冲突（{combo}）"
            else:
                other = next((x for x in cheats if x["id"] == seen[parsed]), None)
                conflicts[c["id"]] = f"与「{other['name'] if other else '?'}」重复（{combo}）"
            continue
        seen[parsed] = c["id"]
        bindings.append((hid, parsed[0], parsed[1], c["id"]))
        hid += 1
    return bindings, conflicts


# ----------------------------------------------------------------------------
# 纯函数：冲突处置（挑一个空闲组合键） / 排序 / DPI 比例
# ----------------------------------------------------------------------------
def candidate_combos() -> list[str]:
    """冲突迁移的候选键序列：F1–F11 → Shift → Ctrl → Ctrl+Shift → Alt。

    刻意避开 F12（系统/调试器常占），也避开字母数字裸键（会吃掉正常打字）。
    """
    out: list[str] = []
    vks = [VK_BY_NAME[f"f{i}"] for i in range(1, 12)]
    for mods in (0, MOD_SHIFT, MOD_CONTROL, MOD_CONTROL | MOD_SHIFT, MOD_ALT):
        for vk in vks:
            if not is_safe_binding(mods, vk):
                continue
            combo = format_combo(mods, vk)
            if combo not in out:
                out.append(combo)
    return out


def pick_free_combo(cheats: list[dict], pause_combo: str = "", avoid=(),
                    exclude_id: str = "") -> str:
    """按候选序列找第一个未被占用（其他秘籍 / 暂停键 / 已知不可用）的组合键。

    没有空闲键时返回空串。avoid 用于记录"注册时报 1409 说明系统真的占着"的键。
    """
    taken = set()
    for c in cheats:
        if c.get("id") == exclude_id:
            continue
        sig = combo_signature(c.get("hotkey") or "")
        if sig:
            taken.add(sig)
    pause_sig = combo_signature(pause_combo)
    if pause_sig:
        taken.add(pause_sig)
    for text in avoid or ():
        sig = combo_signature(text)
        if sig:
            taken.add(sig)
    for combo in candidate_combos():
        if combo_signature(combo) not in taken:
            return combo
    return ""
