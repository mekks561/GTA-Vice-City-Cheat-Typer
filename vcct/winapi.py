# -*- coding: utf-8 -*-
"""1.7：Win32 原语（ctypes 结构体、SendInput、前台判定、IME 守卫、DPI）。

这是唯一允许直接调用 Win32 API 的模块；其余模块通过它间接使用。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import time

from .const import IS_WIN

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


def send_key(vk: int, keyup: bool) -> None:
    """单键按下/抬起原语（供发送引擎注入，一次 SendInput 只发一个键）。"""
    _send([_key_item(vk, keyup)])


# 需要兜底松开的修饰键：左右 Ctrl / 左右 Shift / 左右 Win
RELEASE_VKS = (0xA2, 0xA3, 0xA0, 0xA1, 0x5B, 0x5C)


def release_modifiers() -> None:
    """兜底松开所有修饰键。

    用在两处：发送前（用户可能正按着 Ctrl 触发热键，不松开就变成"变速跑"）、
    退出前（异常/强杀后残留的按下状态会让角色一直跑，必须清干净）。
    """
    for vk in RELEASE_VKS:
        try:
            send_key(vk, True)
        except OSError:
            pass


def vk_for_char(ch: str) -> int | None:
    """字符 -> 虚拟键码；None 表示本工具无法输入该字符。"""
    return VK_BY_NAME.get(str(ch).lower())


def press_key(vk: int, hold_ms: int) -> None:
    """按下 -> 保持 -> 抬起。保持时间是关键：游戏按帧轮询，同帧内下抬会被漏掉。"""
    send_key(vk, False)
    try:
        time.sleep(max(0, hold_ms) / 1000.0)
    finally:
        # 抬起放 finally：中途异常/被取消时绝不留残键（角色一直跑很难受）
        send_key(vk, True)


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
_RAW_PROBE_CLASS = "VC_CheatTyper_RawProbe"


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


def enable_dpi_awareness() -> None:
    """开启 DPI 感知。必须在 tk.Tk() 之前调用：先建窗口再声明，Tk 已按 96 DPI 初始化，
    系统会把整窗位图拉伸，字就糊了（125%/150% 缩放下最明显）。"""
    if not IS_WIN:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)   # PROCESS_SYSTEM_DPI_AWARE
        return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()                      # Win7/8 回退
    except Exception:
        pass


def ui_scale(root) -> float:
    """界面缩放系数（96 DPI = 1.0）。VCCT_UI_SCALE 可强制指定，用于三档截图核对。"""
    forced = os.environ.get("VCCT_UI_SCALE", "").strip()
    if forced:
        try:
            return max(0.8, min(2.5, float(forced)))
        except ValueError:
            pass
    try:
        return max(1.0, min(2.0, root.winfo_fpixels("1i") / 96.0))
    except Exception:
        return 1.0
