# -*- coding: utf-8 -*-
"""
GTA: Vice City 秘籍一键输入器  (Windows / 单文件 / 零第三方依赖)
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
import ctypes.wintypes as wt
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

APP_NAME = "Vice City 秘籍一键输入器"
APP_VER = "1.5"
IS_WIN = os.name == "nt"

# ----------------------------------------------------------------------------
# Win32 基础
# ----------------------------------------------------------------------------
if IS_WIN:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    try:
        imm32 = ctypes.WinDLL("imm32")
    except OSError:  # 极少数精简系统没有 imm32，降级为不处理输入法
        imm32 = None

ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wt.WORD),
        ("wScan", wt.WORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wt.LONG),
        ("dy", wt.LONG),
        ("mouseData", wt.DWORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_APP = 0x8000
WM_APP_RELOAD = WM_APP + 1

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x0001, 0x0002, 0x0004, 0x0008, 0x4000

ERROR_HOTKEY_ALREADY_REGISTERED = 1409
ERROR_ACCESS_DENIED = 5

WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
GWL_EXSTYLE = -20
GA_ROOT = 2

if IS_WIN:
    user32.SendInput.argtypes = (wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
    user32.SendInput.restype = wt.UINT
    user32.MapVirtualKeyW.argtypes = (wt.UINT, wt.UINT)
    user32.MapVirtualKeyW.restype = wt.UINT
    user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.GetForegroundWindow.restype = wt.HWND
    user32.GetWindowTextLengthW.argtypes = (wt.HWND,)
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = (wt.HWND, wt.LPWSTR, ctypes.c_int)
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = (wt.HWND, ctypes.POINTER(wt.DWORD))
    user32.GetWindowThreadProcessId.restype = wt.DWORD
    user32.RegisterHotKey.argtypes = (wt.HWND, ctypes.c_int, wt.UINT, wt.UINT)
    user32.RegisterHotKey.restype = wt.BOOL
    user32.UnregisterHotKey.argtypes = (wt.HWND, ctypes.c_int)
    user32.UnregisterHotKey.restype = wt.BOOL
    user32.GetMessageW.argtypes = (ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT)
    user32.GetMessageW.restype = ctypes.c_int
    user32.PostThreadMessageW.argtypes = (wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM)
    user32.PostThreadMessageW.restype = wt.BOOL
    user32.PeekMessageW.argtypes = (ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT)
    user32.PeekMessageW.restype = wt.BOOL
    kernel32.GetCurrentThreadId.restype = wt.DWORD
    kernel32.OpenProcess.argtypes = (wt.DWORD, wt.BOOL, wt.DWORD)
    kernel32.OpenProcess.restype = wt.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = (
        wt.HANDLE,
        wt.DWORD,
        wt.LPWSTR,
        ctypes.POINTER(wt.DWORD),
    )
    kernel32.QueryFullProcessImageNameW.restype = wt.BOOL
    kernel32.CloseHandle.argtypes = (wt.HANDLE,)
    kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, wt.BOOL, wt.LPCWSTR)
    kernel32.CreateMutexW.restype = wt.HANDLE
    user32.GetFocus.argtypes = (wt.HWND,)
    user32.GetFocus.restype = wt.HWND
    user32.SetForegroundWindow.argtypes = (wt.HWND,)
    user32.SetForegroundWindow.restype = wt.BOOL
    user32.BringWindowToTop.argtypes = (wt.HWND,)
    user32.BringWindowToTop.restype = wt.BOOL
    user32.AttachThreadInput.argtypes = (wt.DWORD, wt.DWORD, wt.BOOL)
    user32.AttachThreadInput.restype = wt.BOOL
    user32.GetAncestor.argtypes = (wt.HWND, wt.UINT)
    user32.GetAncestor.restype = wt.HWND
    if imm32:
        imm32.ImmAssociateContext.argtypes = (wt.HWND, wt.HANDLE)
        imm32.ImmAssociateContext.restype = wt.HANDLE
        imm32.ImmGetContext.argtypes = (wt.HWND,)
        imm32.ImmGetContext.restype = wt.HANDLE
    user32.IsWindowVisible.argtypes = (wt.HWND,)
    user32.IsWindowVisible.restype = wt.BOOL
    user32.EnumWindows.argtypes = (ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM), wt.LPARAM)
    user32.EnumWindows.restype = wt.BOOL
    user32.DefWindowProcW.restype = ctypes.c_ssize_t
    user32.DefWindowProcW.argtypes = (wt.HWND, wt.UINT, ctypes.c_size_t, ctypes.c_ssize_t)
    user32.TranslateMessage.argtypes = (ctypes.POINTER(wt.MSG),)
    user32.TranslateMessage.restype = wt.BOOL
    user32.DispatchMessageW.argtypes = (ctypes.POINTER(wt.MSG),)
    user32.DispatchMessageW.restype = ctypes.c_ssize_t
    user32.DestroyWindow.argtypes = (wt.HWND,)
    user32.DestroyWindow.restype = wt.BOOL
    user32.UpdateWindow.argtypes = (wt.HWND,)
    user32.UpdateWindow.restype = wt.BOOL
    kernel32.GetCurrentProcessId.restype = wt.DWORD
    # GetWindowLongPtrW 在 64 位 python 上存在；32 位回退到 GetWindowLongW
    _GetLongPtr = getattr(user32, "GetWindowLongPtrW", None)
    _SetLongPtr = getattr(user32, "SetWindowLongPtrW", None)
    if _GetLongPtr is not None and _SetLongPtr is not None:
        _GetLongPtr.argtypes = (wt.HWND, ctypes.c_int)
        _GetLongPtr.restype = ctypes.c_ssize_t
        _SetLongPtr.argtypes = (wt.HWND, ctypes.c_int, ctypes.c_ssize_t)
        _SetLongPtr.restype = ctypes.c_ssize_t
    else:
        user32.GetWindowLongW.argtypes = (wt.HWND, ctypes.c_int)
        user32.GetWindowLongW.restype = ctypes.c_long
        user32.SetWindowLongW.argtypes = (wt.HWND, ctypes.c_int, ctypes.c_long)
        user32.SetWindowLongW.restype = ctypes.c_long


def get_window_exstyle(hwnd: int) -> int:
    fn = getattr(user32, "GetWindowLongPtrW", None)
    if fn is not None:
        return int(fn(hwnd, GWL_EXSTYLE))
    return int(user32.GetWindowLongW(hwnd, GWL_EXSTYLE))


def add_window_exstyle(hwnd: int, bits: int) -> None:
    fn = getattr(user32, "SetWindowLongPtrW", None)
    cur = get_window_exstyle(hwnd)
    if fn is not None:
        fn(hwnd, GWL_EXSTYLE, cur | bits)
    else:
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, cur | bits)


# ----------------------------------------------------------------------------
# 键名 / 键码
# ----------------------------------------------------------------------------
VK_BY_NAME: dict[str, int] = {}
NAME_BY_VK: dict[int, str] = {}


def _reg(name: str, vk: int, pretty: str | None = None) -> None:
    VK_BY_NAME[name.lower()] = vk
    NAME_BY_VK.setdefault(vk, pretty or name.upper())


for _i in range(1, 25):
    _reg(f"F{_i}", 0x6F + _i, f"F{_i}")
for _c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    _reg(_c, ord(_c), _c)
for _d in "0123456789":
    _reg(_d, ord(_d), _d)
for _i in range(10):
    _reg(f"NUM{_i}", 0x60 + _i, f"小键盘{_i}")
_reg("SPACE", 0x20, "空格")
_reg("TAB", 0x09, "Tab")
_reg("ENTER", 0x0D, "回车")
_reg("ESC", 0x1B, "Esc")
_reg("BACKSPACE", 0x08, "退格")
_reg("INSERT", 0x2D, "Insert")
_reg("DELETE", 0x2E, "Delete")
_reg("HOME", 0x24, "Home")
_reg("END", 0x23, "End")
_reg("PAGEUP", 0x21, "PageUp")
_reg("PAGEDOWN", 0x22, "PageDown")
_reg("UP", 0x26, "↑")
_reg("DOWN", 0x28, "↓")
_reg("LEFT", 0x25, "←")
_reg("RIGHT", 0x27, "→")
_reg("MINUS", 0xBD, "-")
_reg("EQUAL", 0xBB, "=")
_reg("COMMA", 0xBC, ",")
_reg("PERIOD", 0xBE, ".")
_reg("SLASH", 0xBF, "/")
_reg("SEMICOLON", 0xBA, ";")
_reg("QUOTE", 0xDE, "'")
_reg("LBRACKET", 0xDB, "[")
_reg("RBRACKET", 0xDD, "]")
_reg("BACKSLASH", 0xDC, "\\")
_reg("GRAVE", 0xC0, "`")

MODIFIER_VKS = {
    0x11: "ctrl", 0xA2: "ctrl", 0xA3: "ctrl",
    0x10: "shift", 0xA0: "shift", 0xA1: "shift",
    0x12: "alt", 0xA4: "alt", 0xA5: "alt",
    0x5B: "win", 0x5C: "win",
}
BARE_SAFE_VKS = set(range(0x70, 0x88))  # F1-F24：不需要修饰键也不会被当成打字吞掉


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
# 键盘注入
# ----------------------------------------------------------------------------
def _key_item(vk: int, keyup: bool) -> INPUT:
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.ki.wVk = 0
    inp.ki.wScan = user32.MapVirtualKeyW(vk, 0)  # MAPVK_VK_TO_VSC
    flags = KEYEVENTF_SCANCODE
    if keyup:
        flags |= KEYEVENTF_KEYUP
    inp.ki.dwFlags = flags
    return inp


def _send(items: list[INPUT]) -> None:
    n = len(items)
    arr = (INPUT * n)(*items)
    sent = user32.SendInput(n, arr, ctypes.sizeof(INPUT))
    if sent != n:
        raise OSError(ctypes.get_last_error(), "SendInput 被拒绝（可能目标程序权限更高）")


def press_key(vk: int, hold_ms: int) -> None:
    """按下 -> 保持 -> 抬起。保持时间是关键：游戏按帧轮询，同帧内下抬会被漏掉。"""
    _send([_key_item(vk, False)])
    time.sleep(max(0, hold_ms) / 1000.0)
    _send([_key_item(vk, True)])


def foreground_info() -> tuple[str, str]:
    """返回 (窗口标题, 进程文件名)"""
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return "", ""
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        exe = ""
        pid = wt.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value:
            h = kernel32.OpenProcess(0x1000, False, pid.value)  # QUERY_LIMITED_INFORMATION
            if h:
                try:
                    size = wt.DWORD(1024)
                    pbuf = ctypes.create_unicode_buffer(1024)
                    if kernel32.QueryFullProcessImageNameW(h, 0, pbuf, ctypes.byref(size)):
                        exe = os.path.basename(pbuf.value)
                finally:
                    kernel32.CloseHandle(h)
        return buf.value, exe
    except Exception:
        return "", ""


def is_key_down(vk: int) -> bool:
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


# --- 游戏窗口自动检测 --------------------------------------------------------
KNOWN_GAME_EXES = (
    "gta-vc.exe", "gta3-vc.exe", "gtavc.exe", "vicecity.exe", "playgtavc.exe",
    "gtavc-wing64-shipping.exe", "grand theft auto vice city.exe",
)


def find_game_window() -> tuple[int, str, str]:
    """枚举顶层窗口，按进程名/标题找 GTA VC；返回 (hwnd, title, exe)，找不到为 (0, '', '')"""
    result = [0, "", ""]
    my_pid = kernel32.GetCurrentProcessId()
    proc_cache: dict[int, str] = {}

    def _exe_of(hwnd) -> str:
        pid = wt.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""
        if pid.value in proc_cache:
            return proc_cache[pid.value]
        exe = ""
        h = kernel32.OpenProcess(0x1000, False, pid.value)
        if h:
            try:
                size = wt.DWORD(1024)
                pbuf = ctypes.create_unicode_buffer(1024)
                if kernel32.QueryFullProcessImageNameW(h, 0, pbuf, ctypes.byref(size)):
                    exe = os.path.basename(pbuf.value)
            finally:
                kernel32.CloseHandle(h)
        proc_cache[pid.value] = exe
        return exe

    def _enum(hwnd, _lparam):
        if result[0]:
            return False
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value
        pid = wt.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == my_pid:
            return True  # 跳过自己（本工具窗口标题也含 "Vice City"）
        exe = _exe_of(hwnd)
        el, tl = exe.lower(), title.lower()
        if el in KNOWN_GAME_EXES or "vice city" in tl or "vicecity" in el:
            result[:] = [int(hwnd), title, exe]
            return False
        return True

    try:
        user32.EnumWindows(ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)(_enum), 0)
    except Exception:
        return 0, "", ""
    return tuple(result) if result[0] else (0, "", "")


# --- 输入法（IME）处理 -------------------------------------------------------
# 中文键盘布局会给窗口挂一个输入上下文，把注入击键变成 VK_PACKET 吞掉。
# 发送期间临时摘掉关联，发送结束再挂回去；任何一步失败都只是降级，不影响主流程。
class ImeGuard:
    def __init__(self, hwnd: int, enable: bool = True):
        self.hwnd = hwnd
        self.enable = enable
        self.old = None
        self.applied = False

    def __enter__(self):
        if not (self.enable and imm32 and self.hwnd):
            return self
        try:
            ctx = imm32.ImmGetContext(self.hwnd)
            if ctx:
                self.old = imm32.ImmAssociateContext(self.hwnd, None)
                self.applied = True
        except Exception:
            self.applied = False
        return self

    def __exit__(self, *exc):
        if self.applied and self.old:
            try:
                imm32.ImmAssociateContext(self.hwnd, self.old)
            except Exception:
                pass
        return False


def force_foreground(hwnd: int) -> bool:
    """仅供自检使用：把自己的窗口顶到前台（普通用户点击窗口时不需要）"""
    if not hwnd:
        return False
    fg = user32.GetForegroundWindow()
    fg_tid = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    my_tid = kernel32.GetCurrentThreadId()
    if fg_tid:
        user32.AttachThreadInput(my_tid, fg_tid, True)
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if fg_tid:
            user32.AttachThreadInput(my_tid, fg_tid, False)
    time.sleep(0.12)
    return user32.GetForegroundWindow() == hwnd


# --- 注入自检（原生 Win32 窗口） ---------------------------------------------
# 为什么不用 Tk 的文本框做验证：Tk 的窗口会自己管理输入法上下文，在中文 IME 环境下
# 注入的扫描码会被转成 VK_PACKET（WM_KEYDOWN wParam=229），一个字符都收不到——这是
# Tk 显示层的问题，不代表注入失效（游戏走 DirectInput 读设备状态，两者是不同通道）。
# 原生窗口没有这层干扰，能确定性验证"扫描码 → 虚拟键 → WM_CHAR"全链路。
_RAW_PROBE_CLASS = "VC_CheatTool_RawProbe"


def raw_char_probe(text: str, hold_ms: int = 25, gap_ms: int = 45) -> tuple[bool, str]:
    """隐藏原生窗口上验证注入。返回 (是否取得前台, 实际收到的字符串)。阻塞调用。"""
    if not IS_WIN:
        return False, ""
    events: list[str] = []
    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
    proto_holder = {}

    def _wndproc(h, m, wp, lp):
        if m == 0x0102:  # WM_CHAR
            events.append(chr(int(wp)))
            return 0
        if m == 0x0010:  # WM_CLOSE
            user32.DestroyWindow(h)
            return 0
        if m == 0x0002:  # WM_DESTROY
            u32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(h, m, wp, lp)

    u32 = user32
    cb = WNDPROC(_wndproc)
    proto_holder["cb"] = cb  # 防止回调被 GC

    class _WC(ctypes.Structure):
        _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                    ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH),
                    ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR)]

    wc = _WC()
    wc.lpfnWndProc = cb
    wc.lpszClassName = _RAW_PROBE_CLASS
    wc.hbrBackground = 6
    user32.RegisterClassW.argtypes = (ctypes.POINTER(_WC),)
    if not user32.RegisterClassW(ctypes.byref(wc)):
        if ctypes.get_last_error() != 1410:  # class already exists
            return False, ""
    user32.CreateWindowExW.restype = wt.HWND
    user32.CreateWindowExW.argtypes = (wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU,
                                       wt.HINSTANCE, ctypes.c_void_p)
    hwnd = user32.CreateWindowExW(0, _RAW_PROBE_CLASS, "注入自检", 0x00CF0000,
                                  220, 220, 360, 96, None, None, None, None)
    if not hwnd:
        return False, ""
    user32.ShowWindow.argtypes = (wt.HWND, ctypes.c_int)
    user32.ShowWindow(hwnd, 5)
    user32.UpdateWindow(hwnd)

    got_fg = force_foreground(hwnd)
    if got_fg:
        try:
            if imm32:
                imm32.ImmAssociateContext(hwnd, None)
        except Exception:
            pass
        time.sleep(0.2)
        try:
            for ch in text:
                vk = VK_BY_NAME.get(ch.lower())
                if vk is None:
                    break
                press_key(vk, hold_ms)
                time.sleep(gap_ms / 1000.0)
        except OSError:
            pass

    # 泵消息收集 WM_CHAR
    msg = wt.MSG()
    deadline = time.time() + 1.5
    user32.GetMessageW.argtypes = (ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT)
    user32.TranslateMessage = user32.TranslateMessage
    while time.time() < deadline:
        peeked = user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1)  # PM_REMOVE
        if peeked:
            if msg.message == 0x0012:  # WM_QUIT
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        elif events and time.time() > deadline - 1.2:
            break
        else:
            time.sleep(0.01)
    try:
        user32.DestroyWindow(hwnd)
    except Exception:
        pass
    return got_fg, "".join(events)



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


# ----------------------------------------------------------------------------
# 数据（v2：多方案组 + 使用统计；自动迁移 v1 单列表格式）
# ----------------------------------------------------------------------------
STORE_VERSION = 2
STORE_APP = "vc-cheat-tool"

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
}

# 参数预设：经典版按帧率 30fps 调优；决定版(Unreal)输入窗口更宽但帧率不定，整体放慢
PRESETS = {
    "经典版": {"char_interval_ms": 45, "pre_delay_ms": 180},
    "决定版": {"char_interval_ms": 70, "pre_delay_ms": 250},
}


def _c(name, code, hotkey, group, note):
    return {"id": uuid.uuid4().hex[:8], "name": name, "code": code,
            "hotkey": hotkey, "group": group, "note": note}


def default_cheats() -> list[dict]:
    return [
        # 武器
        _c("一级武器", "THUGSTOOLS", "F1", "武器", "指虎/球棒/燃烧瓶/手枪/霰弹…重复输入可无限弹药"),
        _c("二级武器", "PROFESSIONALTOOLS", "F2", "武器", "武士刀/357/SPAS12/M4/火箭筒…"),
        _c("三级武器", "NUTTERTOOLS", "F3", "武器", "电锯/手雷/加特林…"),
        # 生存
        _c("满血", "ASPIRINE", "F4", "生存", "开车时同时修轮胎"),
        _c("满护甲", "PRECIOUSPROTECTION", "F5", "生存", "护甲补满"),
        # 通缉
        _c("清除通缉", "LEAVEMEALONE", "F6", "通缉", "通缉星级归零"),
        _c("通缉 +2 星", "YOUWONTTAKEMEALIVE", "F7", "通缉", "每次 +2 星，慎用"),
        # 载具生成（默认不使用 F12：该键常被系统/调试器占用）
        _c("犀牛坦克", "PANZER", "F8", "载具", "在最近的车辆生成点出现"),
        _c("Sabre Turbo", "GETTHEREFAST", "F9", "载具", "肌肉跑车"),
        _c("高尔夫球车", "BETTERTHANWALKING", "F10", "载具", "Caddy"),
        _c("灵车", "THELASTRIDE", "F11", "载具", "Romero's Hearse"),
        _c("Love Fist 加长车", "ROCKANDROLLCAR", "Shift+F1", "载具", "加长礼车"),
        _c("垃圾车", "RUBBISHCAR", "Shift+F2", "载具", "Trashmaster"),
        # 载具特性
        _c("水上行驶", "SEAWAYS", "Shift+F3", "改装", "车辆可在水面行驶，再输一次取消"),
        _c("飞行汽车", "COMEFLYWITHME", "Shift+F4", "改装", "低重力，空中可控；直升机操作会变怪"),
        _c("操控提升", "GRIPISEVERYTHING", "Shift+F5", "改装", "抓地力/转向改善"),
        _c("超大轮子", "LOADSOFLITTLETHINGS", "Shift+F6", "改装", "车轮变大，重复输入继续变"),
        _c("隐形车", "WHEELSAREALLINEED", "Shift+F7", "改装", "只显示车轮"),
        _c("炸毁所有车", "BIGBANG", "Shift+F8", "改装", "附近车辆全部爆炸，会波及自己"),
        # 交通
        _c("全绿灯", "GREENLIGHT", "Shift+F9", "交通", "所有红绿灯变绿"),
        _c("疯狂驾驶", "MIAMITRAFFIC", "Shift+F10", "交通", "NPC 驾驶变得激进"),
        # 天气
        _c("晴天", "ALOVELYDAY", "Shift+F11", "天气", "晴朗天气"),
        _c("多云", "APLEASANTDAY", "Ctrl+Shift+F1", "天气", "阴天/多云"),
        _c("暴雨", "CATSANDDOGS", "Ctrl+Shift+F2", "天气", "风暴天气"),
        # 市民
        _c("市民暴动", "FIGHTFIGHTFIGHT", "Ctrl+Shift+F3", "市民", "★不可撤销：存盘后会永久影响存档"),
        _c("武装女性", "CHICKSWITHGUNS", "Ctrl+Shift+F4", "市民", "比基尼女性持枪"),
        _c("人人持枪", "OURGODGIVENRIGHTTOBEARARMS", "Ctrl+Shift+F5", "市民", "★不可撤销，会严重影响任务"),
        _c("女性跟随", "FANNYMAGNET", "Ctrl+Shift+F6", "市民", "特定女性会跟随 Tommy"),
    ]


def data_path() -> str:
    base = os.path.dirname(os.path.abspath(sys.argv[0] if getattr(sys, "frozen", False) else __file__))
    return os.path.join(base, "cheats.json")


def _norm_cheat(item) -> dict | None:
    if not isinstance(item, dict):
        return None
    code = str(item.get("code") or "").strip().upper()
    if not code:
        return None
    return {
        "id": str(item.get("id") or uuid.uuid4().hex[:8]),
        "name": str(item.get("name") or code),
        "code": code,
        "hotkey": str(item.get("hotkey") or "").strip(),
        "group": str(item.get("group") or "自定义"),
        "note": str(item.get("note") or ""),
    }


def _norm_stats(raw) -> dict:
    stats = {}
    if isinstance(raw, dict):
        for code, v in raw.items():
            if isinstance(v, dict) and isinstance(v.get("count"), int):
                stats[str(code).upper()] = {"count": int(v["count"]), "last": str(v.get("last") or "")}
    return stats


def default_store() -> dict:
    return {
        "app": STORE_APP,
        "version": STORE_VERSION,
        "settings": dict(DEFAULT_SETTINGS),
        "active_profile": "默认",
        "profiles": [{"name": "默认", "cheats": default_cheats()}],
        "stats": {},
    }


def load_store(path: str | None = None) -> dict:
    """读取配置并归一化为 v2 结构；损坏/缺失字段一律回退默认，不让工具崩掉。"""
    path = path or data_path()
    if not os.path.exists(path):
        store = default_store()
        save_store(store, path)
        return store
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception:
        return default_store()
    if not isinstance(raw, dict):
        return default_store()

    settings = dict(DEFAULT_SETTINGS)
    settings.update({k: v for k, v in (raw.get("settings") or {}).items() if k in DEFAULT_SETTINGS})

    # 方案组：v2 直接读；v1（顶层 cheats）迁移为单个默认方案
    raw_profiles = raw.get("profiles")
    if isinstance(raw_profiles, list) and raw_profiles:
        profiles = []
        for p in raw_profiles:
            if not isinstance(p, dict):
                continue
            cheats = [c for c in (_norm_cheat(i) for i in (p.get("cheats") or [])) if c]
            name = str(p.get("name") or "").strip() or "未命名"
            profiles.append({"name": name, "cheats": cheats})
    else:
        cheats = [c for c in (_norm_cheat(i) for i in (raw.get("cheats") or [])) if c]
        profiles = [{"name": "默认", "cheats": cheats}] if cheats else []
    if not profiles:
        profiles = [{"name": "默认", "cheats": default_cheats()}]

    # 方案名去重
    seen_names: set[str] = set()
    for p in profiles:
        name = p["name"]
        i = 2
        while name in seen_names:
            name = f"{p['name']} ({i})"
            i += 1
        p["name"] = name
        seen_names.add(name)

    active = str(raw.get("active_profile") or "").strip()
    if active not in seen_names:
        active = profiles[0]["name"]

    return {
        "app": STORE_APP,
        "version": STORE_VERSION,
        "settings": settings,
        "active_profile": active,
        "profiles": profiles,
        "stats": _norm_stats(raw.get("stats")),
    }


def save_store(store: dict, path: str | None = None) -> None:
    path = path or data_path()
    settings = {k: v for k, v in (store.get("settings") or {}).items() if k in DEFAULT_SETTINGS}
    payload = {
        "app": STORE_APP,
        "version": STORE_VERSION,
        "settings": settings,
        "active_profile": store.get("active_profile", "默认"),
        "profiles": store.get("profiles", []),
        "stats": store.get("stats", {}),
    }
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as exc:  # 保存失败不该让工具崩掉
        print("保存配置失败:", exc, file=sys.stderr)


def bump_stats(stats: dict, code: str) -> int:
    """累计使用次数，返回新次数（纯函数，便于测试）"""
    key = str(code).upper()
    entry = stats.setdefault(key, {"count": 0, "last": ""})
    entry["count"] = int(entry.get("count", 0)) + 1
    entry["last"] = time.strftime("%Y-%m-%d %H:%M")
    return entry["count"]


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
        self.result = {
            "id": self.cheat.get("id") or uuid.uuid4().hex[:8],
            "name": name,
            "code": code,
            "hotkey": self.hotkey.strip(),
            "group": (self.var_group.get() or "自定义").strip(),
            "note": self.var_note.get().strip(),
        }
        self.destroy()


# ----------------------------------------------------------------------------
# 主窗口
# ----------------------------------------------------------------------------
C = {
    "bg": "#f5f6f8", "panel": "#ffffff", "line": "#e3e7ee",
    "text": "#1a1f29", "muted": "#6b7280", "accent": "#2563eb",
    "ok": "#067647", "warn": "#b42318", "soft": "#eef4ff",
}


class CheatApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.events: queue.Queue = queue.Queue()
        self.store = load_store()
        self.settings = self.store["settings"]
        self.stats = self.store["stats"]
        self.active_profile = self.store["active_profile"]
        prof = next(p for p in self.store["profiles"] if p["name"] == self.active_profile)
        self.cheats = prof["cheats"]  # 引用 store 内的列表，增删改即时生效
        self.conflicts: dict[str, str] = {}
        self.hotkey_owner: dict[int, str] = {}
        self.sending = threading.Lock()
        self.test_hwnd = 0
        self.game_info: tuple[int, str, str] = (0, "", "")
        self._toast: tk.Toplevel | None = None
        self.last_error = ""

        self._setup_style()
        self._build_ui()
        self.refresh_tree()

        self.engine = HotkeyEngine(self.events)
        self.apply_hotkeys()
        self.root.after(40, self._pump)
        self.root.after(1500, self._update_game_status)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # -- 外观 ---------------------------------------------------------------
    def _setup_style(self):
        self.root.title(f"{APP_NAME} v{APP_VER}")
        self.root.configure(bg=C["bg"])
        self.root.geometry("1000x680")
        self.root.minsize(880, 580)
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
        style.configure("Treeview", background=C["panel"], fieldbackground=C["panel"],
                        foreground=C["text"], rowheight=27, borderwidth=0,
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
        ttk.Label(head, text="罪恶都市 · 秘籍一键输入", style="H1.TLabel").pack(side="left")
        ttk.Label(head, text="  快捷键触发 · 自动键盘输入 · 前台校验",
                  style="Muted.TLabel").pack(side="left", pady=(6, 0))
        self.lbl_state = ttk.Label(head, text="初始化…", style="Muted.TLabel")
        self.lbl_state.pack(side="right", pady=(6, 0))
        self.lbl_game = ttk.Label(head, text="⚪ 检测游戏…", style="Muted.TLabel")
        self.lbl_game.pack(side="right", pady=(6, 0), padx=(0, 16))

        # 工具条
        bar = tk.Frame(outer, bg=C["panel"], highlightthickness=1,
                       highlightbackground=C["line"], padx=12, pady=10)
        bar.pack(fill="x", pady=(12, 10))
        bar.columnconfigure(6, weight=1)
        lbl = dict(bg=C["panel"], fg=C["muted"], font=("Microsoft YaHei UI", 9))

        tk.Label(bar, text="目标窗口关键字（逗号分隔多个）", **lbl).grid(row=0, column=0, columnspan=2, sticky="w")
        self.var_kw = tk.StringVar(value=self.settings["target_keywords"])
        ent = tk.Entry(bar, textvariable=self.var_kw, font=("Microsoft YaHei UI", 10), width=24,
                       relief="flat", bg="#f9fafb", highlightthickness=1,
                       highlightbackground=C["line"], highlightcolor=C["accent"])
        ent.grid(row=1, column=0, columnspan=2, sticky="w", ipady=4)
        ent.bind("<FocusOut>", lambda e: self._on_setting_change())

        ttk.Button(bar, text="拾取当前窗口", command=self.pick_window).grid(row=1, column=2, padx=(8, 16))

        self.var_fg = tk.BooleanVar(value=bool(self.settings["require_foreground"]))
        ttk.Checkbutton(bar, text="仅当目标窗口在前台时发送", variable=self.var_fg,
                        command=self._on_setting_change).grid(row=1, column=3, sticky="w")
        self.var_ime = tk.BooleanVar(value=bool(self.settings["disable_ime"]))
        ttk.Checkbutton(bar, text="发送时绕开中文输入法", variable=self.var_ime,
                        command=self._on_setting_change).grid(row=1, column=4, sticky="w", padx=(12, 0))

        tk.Label(bar, text="每字间隔(ms)", **lbl).grid(row=0, column=5, sticky="w", padx=(16, 0))
        self.var_delay = tk.IntVar(value=int(self.settings["char_interval_ms"]))
        sp = ttk.Spinbox(bar, from_=20, to=300, increment=5, width=6, textvariable=self.var_delay,
                         command=self._on_setting_change)
        sp.grid(row=1, column=5, padx=(16, 0), sticky="w")
        sp.bind("<FocusOut>", lambda e: self._on_setting_change())

        tk.Label(bar, text="分组", **lbl).grid(row=0, column=6, sticky="w", padx=(16, 0))
        self.var_group_filter = tk.StringVar(value="全部")
        self.cbo_group = ttk.Combobox(bar, textvariable=self.var_group_filter, width=12,
                                      state="readonly")
        self.cbo_group.grid(row=1, column=6, padx=(16, 0), sticky="w")
        self.cbo_group.bind("<<ComboboxSelected>>", lambda e: self.refresh_tree())

        ttk.Button(bar, text="重新注册快捷键", command=self.apply_hotkeys).grid(row=1, column=7, padx=(16, 0))

        # 工具条第二行：方案组 / 参数预设 / 导入导出 / 悬浮提示（pack 流式，避免网格列宽挤压）
        row2 = tk.Frame(bar, bg=C["panel"])
        row2.grid(row=2, column=0, columnspan=8, sticky="w", pady=(10, 0))
        lbl2 = dict(bg=C["panel"], fg=C["muted"], font=("Microsoft YaHei UI", 9))

        tk.Label(row2, text="方案", **lbl2).pack(side="left")
        self.var_profile = tk.StringVar(value=self.active_profile)
        self.cbo_profile = ttk.Combobox(row2, textvariable=self.var_profile, width=10, state="readonly")
        self.cbo_profile.pack(side="left", padx=(6, 4))
        self.cbo_profile.bind("<<ComboboxSelected>>", self.switch_profile)
        ttk.Button(row2, text="新建副本", width=8, command=self.new_profile).pack(side="left", padx=(4, 0))
        ttk.Button(row2, text="重命名", width=8, command=self.rename_profile).pack(side="left", padx=(6, 0))
        ttk.Button(row2, text="删除", width=6, command=self.delete_profile).pack(side="left", padx=(6, 0))

        tk.Label(row2, text="参数预设", **lbl2).pack(side="left", padx=(18, 0))
        ttk.Button(row2, text="经典版", width=7,
                   command=lambda: self.apply_preset("经典版")).pack(side="left", padx=(6, 0))
        ttk.Button(row2, text="决定版", width=7,
                   command=lambda: self.apply_preset("决定版")).pack(side="left", padx=(6, 0))

        ttk.Button(row2, text="导出方案", width=8, command=self.export_profile).pack(side="left", padx=(18, 0))
        ttk.Button(row2, text="导入方案", width=8, command=self.import_profile).pack(side="left", padx=(6, 0))

        self.var_toast = tk.BooleanVar(value=bool(self.settings["show_toast"]))
        ttk.Checkbutton(row2, text="悬浮提示", variable=self.var_toast,
                        command=self._on_setting_change).pack(side="left", padx=(18, 0))

        # 列表
        list_wrap = tk.Frame(outer, bg=C["panel"], highlightthickness=1,
                             highlightbackground=C["line"])
        list_wrap.pack(fill="both", expand=True)

        cols = ("idx", "name", "code", "hotkey", "state", "count", "note")
        self.tree = ttk.Treeview(list_wrap, columns=cols, show="headings", selectmode="browse")
        headings = {"idx": ("#", 40, "center"), "name": ("名称", 158, "w"),
                    "code": ("秘籍代码", 208, "w"), "hotkey": ("快捷键", 122, "center"),
                    "state": ("状态", 68, "center"), "count": ("次数", 52, "center"),
                    "note": ("备注", 290, "w")}
        for key, (text, width, anchor) in headings.items():
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, anchor=anchor,
                             stretch=(key in ("name", "note")))
        self.tree.heading("count", text="次数 ↓", command=self.sort_by_usage)
        vsb = ttk.Scrollbar(list_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.tag_configure("odd", background="#fbfcfe")
        self.tree.tag_configure("conflict", foreground=C["warn"])
        self.tree.tag_configure("unbound", foreground="#98a2b3")
        self.tree.bind("<Double-1>", lambda e: self.edit_selected())
        self.tree.bind("<Return>", lambda e: self.send_selected())
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._update_hint())

        # 操作区
        ops = ttk.Frame(outer)
        ops.pack(fill="x", pady=(10, 0))
        ttk.Button(ops, text="▶ 发送所选 (Enter)", style="Accent.TButton",
                   command=self.send_selected).pack(side="left")
        ttk.Button(ops, text="添加", command=self.add_cheat).pack(side="left", padx=(8, 0))
        ttk.Button(ops, text="编辑", command=self.edit_selected).pack(side="left", padx=(6, 0))
        ttk.Button(ops, text="删除", command=self.delete_selected).pack(side="left", padx=(6, 0))
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

    # -- 日志 / 事件泵 -------------------------------------------------------
    def log(self, text: str, kind: str = "info", from_thread: bool = False):
        if from_thread:
            self.events.put(("log", text, kind))
            return
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", time.strftime("[%H:%M:%S] ") + text + "\n", kind)
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

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
                elif kind == "hotkey":
                    self._on_hotkey(item[1])
                elif kind == "hotkeys":
                    self._on_hotkeys_applied(item[1], item[2])
        except queue.Empty:
            pass
        self.root.after(40, self._pump)

    def _on_hotkey(self, hid: int):
        cheat_id = self.hotkey_owner.get(hid)
        if not cheat_id:
            return
        self.send_by_id(cheat_id)

    # -- 游戏检测 / 悬浮提示 / 统计 -------------------------------------------
    def _update_game_status(self):
        try:
            self.game_info = find_game_window()
            hwnd, _title, exe = self.game_info
            if hwnd:
                self.lbl_game.configure(text=f"🟢 游戏运行中：{exe or '未知进程'}", foreground=C["ok"])
            else:
                self.lbl_game.configure(text="⚪ 未检测到游戏", foreground=C["muted"])
        except Exception:
            pass
        self.root.after(3000, self._update_game_status)

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
            if cheat_id and self.tree.exists(cheat_id):
                self.tree.set(cheat_id, "count", str(count))
            self.persist()
        except Exception:
            pass

    def _on_probe_done(self, ok: bool, got_fg: bool, got: str):
        if ok:
            self.log("注入自检：✔ 通过（原生窗口收到 ASPIRINE，全链路正常）", "ok")
            self.show_toast("✔ 注入自检通过", "ok")
        else:
            detail = "未取得前台焦点" if not got_fg else f"窗口只收到 {got!r}"
            self.log(f"注入自检：✖ {detail}。多见于杀软拦截 SendInput 或会话输入状态异常。", "warn")
            self.show_toast("✖ 注入自检未通过", "warn")

    def sort_by_usage(self):
        self.cheats.sort(key=lambda c: -self.stats.get(c.get("code", ""), {}).get("count", 0))
        self.persist()
        self.refresh_tree()
        self.log("已按使用次数排序（快捷键跟着条目走，不受影响）。", "info")

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
        g = self.var_group_filter.get()
        if g == "全部":
            return list(self.cheats)
        return [c for c in self.cheats if (c.get("group") or "自定义") == g]

    def refresh_tree(self):
        self._refresh_group_choices()
        sel = self.selected_id()
        self.tree.delete(*self.tree.get_children())
        for i, c in enumerate(self.visible_cheats(), 1):
            state = "就绪"
            tags = ["odd"] if i % 2 == 0 else []
            if c["id"] in self.conflicts:
                state = "冲突"
                tags.append("conflict")
            elif not c.get("hotkey"):
                state = "未绑定"
                tags.append("unbound")
            used = self.stats.get(c["code"], {}).get("count", 0)
            self.tree.insert("", "end", iid=c["id"], tags=tags,
                             values=(i, c.get("name", ""), c.get("code", ""),
                                     c.get("hotkey") or "—", state, used or "—",
                                     c.get("note", "")))
        if sel and self.tree.exists(sel):
            self.tree.selection_set(sel)
            self.tree.see(sel)
        elif self.tree.get_children():
            first = self.tree.get_children()[0]
            self.tree.selection_set(first)
        self._update_hint()

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
        self.lbl_hint.configure(text=f"{c['name']}　→　{c['code']}　·　快捷键 {hk}{extra}")

    def by_id(self, cid: str):
        return next((c for c in self.cheats if c["id"] == cid), None)

    def selected_id(self):
        sel = self.tree.selection()
        return sel[0] if sel else None

    # -- 热键注册 ------------------------------------------------------------
    def apply_hotkeys(self):
        self.conflicts.clear()
        bindings = []
        seen: dict[tuple[int, int], str] = {}
        hid = 1
        for c in self.cheats:
            combo = (c.get("hotkey") or "").strip()
            if not combo:
                continue
            parsed = parse_combo(combo)
            if not parsed:
                self.conflicts[c["id"]] = f"快捷键「{combo}」无法解析，已跳过"
                continue
            mods, vk = parsed
            sig = (mods, vk)
            if sig in seen:
                other = self.by_id(seen[sig])
                self.conflicts[c["id"]] = f"与「{other['name'] if other else '?'}」重复（{combo}）"
                continue
            seen[sig] = c["id"]
            bindings.append((hid, mods, vk, c["id"]))
            hid += 1
        self.engine.apply(bindings)
        self.lbl_state.configure(text="注册快捷键…")

    def _on_hotkeys_applied(self, results: dict, id_map: dict):
        self.hotkey_owner = id_map
        occupied = []
        denied = []
        for cheat_id, (ok, err) in results.items():
            if ok:
                continue
            c = self.by_id(cheat_id)
            combo = (c or {}).get("hotkey", "?")
            if err == ERROR_HOTKEY_ALREADY_REGISTERED:
                self.conflicts[cheat_id] = f"系统或其他程序已占用 {combo}"
                occupied.append(combo)
            elif err == ERROR_ACCESS_DENIED:
                self.conflicts[cheat_id] = "权限不足（目标程序可能以管理员运行）"
                denied.append(combo)
            else:
                self.conflicts[cheat_id] = f"注册失败，错误码 {err}（{combo}）"
                occupied.append(combo)
        self.refresh_tree()

        ok_count = sum(1 for ok, _ in results.values() if ok)
        if self.conflicts:
            msg = f"⚠ {len(self.conflicts)} 个快捷键不可用（{ok_count} 个生效）"
            self.lbl_state.configure(text=msg)
            for cid, reason in self.conflicts.items():
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
        if not self.sending.acquire(blocking=False):
            self.log("上一次发送还没结束，已忽略这次请求。", "warn")
            return
        # 注意：Tk 变量只能在主线程读，这里先取好参数再交给工作线程
        params = self._read_params(force)
        threading.Thread(target=self._send_worker, args=(cheat, params), daemon=True).start()

    def _read_params(self, force: bool) -> dict:
        target_hwnd = user32.GetForegroundWindow() or 0
        is_test = bool(target_hwnd) and target_hwnd == self.test_hwnd
        return {
            "interval": max(10, int(self.var_delay.get() or 45)),
            "pre": max(0, int(self.settings.get("pre_delay_ms", 180))),
            "keywords": [k.strip().lower() for k in (self.var_kw.get() or "").split(",") if k.strip()],
            "check_fg": (not force) and bool(self.var_fg.get()) and not is_test,
            "release_mods": bool(self.settings.get("release_modifiers", True)),
            "uppercase": bool(self.settings.get("uppercase", False)),
            "disable_ime": bool(self.settings.get("disable_ime", True)),
        }

    def _send_worker(self, cheat: dict, params: dict):
        try:
            code = cheat.get("code", "")
            interval, pre = params["interval"], params["pre"]
            hold = min(max(8, interval // 2), 60)
            check_fg = params["check_fg"]

            if check_fg and not self._fg_ok(params["keywords"]):
                title, _ = foreground_info()
                msg = (f"⚠ 前台窗口不是目标游戏（当前：{title or '未知'}），本次未发送。"
                       f"点「拾取当前窗口」或关闭前台校验。")
                self.log(msg, "warn", from_thread=True)
                self.events.put(("toast", f"⚠ 未在前台：{title or '未知窗口'}", "warn"))
                return

            target_hwnd = user32.GetForegroundWindow() or 0

            if params["release_mods"]:
                for vk in (0xA2, 0xA3, 0xA0, 0xA1, 0x5B, 0x5C):  # Ctrl/Shift/Win：先松手，免得变速跑
                    try:
                        _send([_key_item(vk, True)])
                    except OSError:
                        pass
            time.sleep(pre / 1000.0)

            upper = params["uppercase"]
            ime = ImeGuard(target_hwnd, params["disable_ime"])
            with ime:
                if upper:
                    _send([_key_item(0xA0, False)])  # LShift 按下
                try:
                    for ch in code:
                        if check_fg and user32.GetForegroundWindow() != target_hwnd:
                            msg = "⚠ 目标窗口失去焦点，已中止输入。"
                            self.log(msg, "warn", from_thread=True)
                            self.events.put(("toast", "⚠ 已中止：游戏失去焦点", "warn"))
                            return
                        vk = VK_BY_NAME.get(ch.lower())
                        if vk is None:
                            msg = f"⚠ 代码里有无法输入的字符：「{ch}」，已中止。"
                            self.log(msg, "warn", from_thread=True)
                            self.events.put(("toast", f"⚠ 代码含非法字符 {ch!r}", "warn"))
                            return
                        press_key(vk, hold)
                        time.sleep(max(0, interval - hold) / 1000.0)
                finally:
                    if upper:
                        _send([_key_item(0xA0, True)])

            self.log(f"✔ 已输入「{cheat['name']}」 {code}", "ok", from_thread=True)
            self.events.put(("toast", f"✔ {cheat['name']} · {code}", "ok"))
            self.events.put(("stats", cheat.get("id", ""), code))
        except OSError as exc:
            self.log(f"✖ 键盘注入失败：{exc}（若游戏以管理员运行，请同样以管理员运行本工具）",
                     "warn", from_thread=True)
        except Exception as exc:
            self.log(f"✖ 发送异常：{exc}", "warn", from_thread=True)
        finally:
            self.sending.release()

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
        self.cheats.remove(c)
        self.persist()
        self.refresh_tree()
        self.apply_hotkeys()
        self.log(f"已删除「{c['name']}」", "warn")

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
        fresh = default_cheats()
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
        self.store["profiles"].append({"name": name, "cheats": copy})
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
        self.store["profiles"] = [p for p in self.store["profiles"] if p["name"] != self.active_profile]
        self.active_profile = self.store["profiles"][0]["name"]
        self.cheats = self.store["profiles"][0]["cheats"]
        self.persist()
        self._refresh_profile_choices()
        self.var_profile.set(self.active_profile)
        self.refresh_tree()
        self.apply_hotkeys()
        self.log(f"方案已删除，当前为「{self.active_profile}」。", "warn")

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
    def pick_window(self):
        title, exe = foreground_info()
        if not title and not exe:
            messagebox.showinfo("拾取失败", "没有取到前台窗口，请先切到游戏窗口再点。", parent=self.root)
            return
        kw = title if title else os.path.splitext(exe)[0]
        self.var_kw.set(kw)
        self._on_setting_change()
        self.log(f"目标窗口设为：{kw}（进程 {exe or '未知'}）", "ok")

    def open_test_window(self):
        """注入自检：隐藏原生 Win32 窗口上跑一遍完整注入链路，结果弹窗展示"""
        self.log("注入自检运行中：会短暂弹出一个 1 秒的自检小窗…", "info")

        def worker():
            got_fg, got = raw_char_probe("ASPIRINE")
            ok = bool(got_fg and got.upper() == "ASPIRINE")
            self.events.put(("probe_done", ok, got_fg, got))

        threading.Thread(target=worker, daemon=True).start()

    def on_close(self):
        try:
            self.settings["target_keywords"] = self.var_kw.get().strip()
            self.settings["require_foreground"] = bool(self.var_fg.get())
            self.settings["disable_ime"] = bool(self.var_ime.get())
            self.settings["show_toast"] = bool(self.var_toast.get())
            self.settings["char_interval_ms"] = int(self.var_delay.get())
            self.persist()
        except Exception:
            pass
        try:
            self.engine.shutdown()
        except Exception:
            pass
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
            json.dump({"app": "vc-cheat-tool", "version": 1,
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

    print("[3] 前台窗口探测：", foreground_info())

    # 真实注入测试：隐藏原生 Win32 窗口验证"扫描码→VK→WM_CHAR"全链路
    # （不使用 Tk 文本框：Tk 自管 IME 上下文，中文环境下会收 VK_PACKET，结果不可信）
    print("[4] SendInput 实际注入测试（原生窗口）")
    got_fg, got = raw_char_probe("ASPIRINE")
    print(f"    取得前台: {got_fg} / 期望 'ASPIRINE'（不区分大小写）/ 实得 {got!r}")
    ok &= bool(got_fg and got.upper() == "ASPIRINE")
    if not ok:
        print("    ⚠ 未落字：若前台未取得则为会话问题；否则请检查杀软是否拦截 SendInput。")

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
        app_root.after(700, app.on_close)
        app_root.mainloop()
        print("    GUI 正常创建并退出")
    except Exception as exc:
        print("    GUI 异常:", exc)
        ok = False

    print("自检结果:", "全部通过" if ok else "有失败项")
    return 0 if ok else 1


def main() -> int:
    if not IS_WIN:
        print("本工具仅支持 Windows。")
        return 1
    if "--selftest" in sys.argv:
        return selftest()

    # 单实例：避免两个进程抢同一批全局热键，注册失败会让人误以为是"冲突"
    # 句柄必须保持存活直到进程退出，故赋值给变量（ruff F841 特批）
    mutex = kernel32.CreateMutexW(None, False, "Local\\VC_CheatTool_SingleInstance")  # noqa: F841
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(APP_NAME, "工具已经在运行了，请查看任务栏 / 先关掉旧窗口。")
        root.destroy()
        return 0

    root = tk.Tk()
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    CheatApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
