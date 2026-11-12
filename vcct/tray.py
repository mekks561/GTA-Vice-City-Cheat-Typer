# -*- coding: utf-8 -*-
"""1.8：托盘常驻——ctypes Shell_NotifyIconW，零第三方依赖。

设计要点
--------
* 独立线程创建隐藏 Win32 窗口 + 自跑消息循环：托盘回调消息送到该窗口，
  与 Tk 主循环完全解耦（tkinter 的窗口/message pump 不能被第二个线程碰）。
* 所有回调通过调用方注入的 `emit(action)` 投递（CheatApp 传的是往
  `self.events` 队列 put 的 lambda），托盘线程里**绝不**直接碰 tkinter。
* TaskbarCreated：Explorer 崩溃/重启后系统会广播这条消息，收到后重新
  NIM_ADD，托盘图标自动回来（1.8 风险表 R1.8.1 的缓解）。
* 右键菜单用 Win32 CreatePopupMenu/TrackPopupMenu(TPM_RETURNCMD)，
  弹出前 SetForegroundWindow（否则点外面菜单不消失，经典坑）。
* 任何一步失败都只把 `available` 置 False 并回调 on_error——托盘失败
  不该弄垮主程序，主界面自动回落"关闭即退出"。
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

from .const import IS_WIN

if IS_WIN:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)

    WM_APP_TRAY = 0x8001  # WM_APP+1：托盘回调消息
    WM_NULL = 0x0000
    WM_QUIT = 0x0012
    WM_CLOSE = 0x0010
    NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
    NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x01, 0x02, 0x04
    WM_LBUTTONDBLCLK, WM_RBUTTONUP, WM_LBUTTONUP = 0x0203, 0x0205, 0x0207
    MF_STRING, MF_SEPARATOR = 0x0000, 0x0800
    TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x0002, 0x0100, 0x0080
    IDI_APPLICATION = 32512

    # 菜单项 id
    IDM_SHOW, IDM_PAUSE, IDM_EXIT = 1001, 1002, 1003


class _NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_ubyte * 16),
        ("hBalloonIcon", wintypes.HICON),
    ]


if IS_WIN:
    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    # 64 位下 wparam/lparam 常是超 int 范围的大数，必须显式声明签名（否则 OverflowError）
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = ctypes.c_longlong
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    # 2.1：显式声明窗口类注册/注销签名，并让每个实例用唯一类名。
    # 旧实现固定 "VCCT_TrayWnd"：第二个实例 RegisterClassW 报 1410 后继续用旧类，
    # 旧类的 lpfnWndProc 指向已被回收的回调 → 消息到达时 access violation（实测复现）。
    user32.RegisterClassW.argtypes = [ctypes.c_void_p]
    user32.RegisterClassW.restype = wintypes.ATOM
    user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
    user32.UnregisterClassW.restype = wintypes.BOOL
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL

    # 2.1：补齐全部 64 位签名。旧实现只给少数函数声明了 argtypes，
    # 其余函数走 ctypes 默认的 int（32 位）转换，句柄/HWND 被截断 →
    # RegisterClassW / CreateWindowExW 处随机 access violation（faulthandler 实测）。
    _PMSG = ctypes.POINTER(wintypes.MSG)
    _PPOINT = ctypes.POINTER(wintypes.POINT)
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    kernel32.GetModuleFileNameW.argtypes = [wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
    kernel32.GetModuleFileNameW.restype = wintypes.DWORD
    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
    user32.RegisterWindowMessageW.restype = wintypes.UINT
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        ctypes.c_void_p,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.GetMessageW.argtypes = [_PMSG, wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.GetMessageW.restype = ctypes.c_int
    user32.TranslateMessage.argtypes = [_PMSG]
    user32.TranslateMessage.restype = wintypes.BOOL
    user32.DispatchMessageW.argtypes = [_PMSG]
    user32.DispatchMessageW.restype = ctypes.c_longlong
    user32.PostQuitMessage.argtypes = [ctypes.c_int]
    user32.LoadIconW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
    user32.LoadIconW.restype = wintypes.HICON
    user32.CreatePopupMenu.argtypes = []
    user32.CreatePopupMenu.restype = wintypes.HMENU
    user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
    user32.AppendMenuW.restype = wintypes.BOOL
    user32.DestroyMenu.argtypes = [wintypes.HMENU]
    user32.DestroyMenu.restype = wintypes.BOOL
    user32.GetCursorPos.argtypes = [_PPOINT]
    user32.GetCursorPos.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.TrackPopupMenu.argtypes = [
        wintypes.HMENU,
        wintypes.UINT,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        ctypes.c_void_p,
    ]
    user32.TrackPopupMenu.restype = ctypes.c_int
    shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(_NOTIFYICONDATAW)]
    shell32.Shell_NotifyIconW.restype = wintypes.BOOL
    shell32.ExtractIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT]
    shell32.ExtractIconW.restype = wintypes.HICON

    class _WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]


class TrayIcon:
    """托盘图标。用法：

        tray = TrayIcon(tooltip="…", emit=my_queue_put, is_paused=lambda: False)
        tray.update_tip(paused=True)   # 菜单/悬停文字随暂停态变化
        tray.close()                   # 真正退出前调用

    emit(action) 会在托盘线程被调用，action ∈ {"show", "pause", "exit"}，
    由调用方负责投递回 UI 线程。非 Windows 或初始化失败时 available=False。
    """

    def __init__(self, tooltip: str, emit, is_paused=lambda: False, on_error=None):
        self.tooltip = tooltip
        self.emit = emit
        self.is_paused = is_paused
        self.on_error = on_error or (lambda msg: None)
        self.available = False
        # 必须在启动线程**之前**初始化：主线程下面的轮询会立刻读 _failed，
        # 若等线程里赋值，几毫秒的竞态就会抛 AttributeError 并让托盘被判为不可用。
        self._failed = False
        self._nid = None
        self._thread: threading.Thread | None = None
        self._tid = 0
        if not IS_WIN:
            return
        try:
            self._thread = threading.Thread(target=self._run, daemon=True, name="vcct-tray")
            self._thread.start()
            # 给线程一点时间完成注册；失败信息经 on_error 异步回报
            for _ in range(50):
                if self.available or self._failed:
                    break
                threading.Event().wait(0.02)
        except Exception as exc:
            self.on_error(f"托盘初始化失败：{exc}")

    # -- 线程体 --------------------------------------------------------------
    def _run(self):  # noqa: C901 - Win32 样板代码，分支多是常态
        self._failed = False
        hinst = kernel32.GetModuleHandleW(None)
        self._taskbar_msg = user32.RegisterWindowMessageW("TaskbarCreated")

        def wnd_proc(hwnd, msg, wparam, lparam):
            try:
                if msg == WM_APP_TRAY:
                    lp = lparam & 0xFFFF
                    if lp in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                        self.emit("show")
                    elif lp == WM_RBUTTONUP:
                        self._popup_menu(hwnd)
                    return 0
                if msg == self._taskbar_msg:  # Explorer 重启 → 图标丢了，补回来
                    self._add_icon(hwnd)
                    return 0
                if msg == WM_CLOSE:
                    user32.PostQuitMessage(0)
                    return 0
            except Exception:
                pass
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._proc = WNDPROC(wnd_proc)  # 引用必须活着，否则回调变野指针
        # 类名按实例唯一：多个 CheatApp / 测试实例并存、或上一个实例刚 close 时，
        # 绝不复用别人注册过的窗口类（2.1 修复）。
        cls_name = f"VCCT_TrayWnd_{id(self):x}_{threading.get_ident()}"
        wc = _WNDCLASSW()
        wc.lpfnWndProc = self._proc
        wc.hInstance = hinst
        wc.lpszClassName = cls_name
        if not user32.RegisterClassW(ctypes.byref(wc)):
            self._failed = True
            self.on_error(f"托盘窗口类注册失败（错误码 {ctypes.get_last_error()}）")
            return

        hwnd = user32.CreateWindowExW(
            0,
            cls_name,
            "VCCT tray",
            0x00000000,  # WS_OVERLAPPED
            0,
            0,
            0,
            0,
            None,
            None,
            hinst,
            None,
        )
        if not hwnd:
            user32.UnregisterClassW(cls_name, hinst)
            self._failed = True
            self.on_error(f"托盘窗口创建失败（错误码 {ctypes.get_last_error()}）")
            return
        self._hwnd = hwnd
        self._tid = kernel32.GetCurrentThreadId()
        self._hicon = self._load_icon(hinst)
        if not self._add_icon(hwnd):
            self._failed = True
            self.on_error("托盘图标注册失败（Shell_NotifyIcon NIM_ADD）")
            user32.DestroyWindow(hwnd)
            user32.UnregisterClassW(cls_name, hinst)
            return
        self.available = True

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        self.available = False
        # 退出时销毁窗口并注销类，不给进程留下指向已回收回调的窗口类
        try:
            user32.DestroyWindow(hwnd)
        except Exception:
            pass
        user32.UnregisterClassW(cls_name, hinst)

    def _load_icon(self, hinst) -> int:
        """优先取本进程 exe 内嵌图标（打包后即产品图标），失败退回系统默认。"""
        try:
            buf = ctypes.create_unicode_buffer(260)
            if kernel32.GetModuleFileNameW(None, buf, 260):
                icon = shell32.ExtractIconW(hinst, buf.value, 0)
                if icon and icon != 1:  # 1 = 未找到图标
                    return icon
        except Exception:
            pass
        return user32.LoadIconW(None, IDI_APPLICATION)

    def _add_icon(self, hwnd) -> bool:
        nid = _NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(nid)
        nid.hWnd = hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_APP_TRAY
        nid.hIcon = self._hicon
        nid.szTip = self.tooltip[:127]
        ok = bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))
        if ok:
            self._nid = nid
        return ok

    def _popup_menu(self, hwnd):
        paused = bool(self.is_paused())
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, MF_STRING, IDM_SHOW, "显示主界面")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, IDM_PAUSE, "恢复热键" if paused else "⏸ 暂停热键")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, IDM_EXIT, "退出")
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        # 经典坑：不先 SetForegroundWindow，菜单点外面不会消失
        user32.SetForegroundWindow(hwnd)
        cmd = user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY, pt.x, pt.y, 0, hwnd, None)
        user32.PostMessageW(hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(menu)
        if cmd == IDM_SHOW:
            self.emit("show")
        elif cmd == IDM_PAUSE:
            self.emit("pause")
        elif cmd == IDM_EXIT:
            self.emit("exit")

    # -- 公共接口（线程安全） ---------------------------------------------------
    def update_tip(self, paused: bool):
        """暂停态变化后同步托盘悬停文字。失败静默（不影响主流程）。"""
        if not (IS_WIN and self.available and self._nid):
            return
        try:
            nid = self._nid
            nid.szTip = (self.tooltip + "（已暂停）")[:127] if paused else self.tooltip[:127]
            shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
        except Exception:
            pass

    def close(self):
        if not (IS_WIN and self._thread):
            return
        try:
            if self._nid:
                shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
                self._nid = None
        except Exception:
            pass
        try:
            # 线程可能还没走到 GetCurrentThreadId：短等一会儿再投递 WM_QUIT，
            # 否则 close() 会留下一个永远不自退的消息循环（2.1 修）。
            for _ in range(50):
                if self._tid:
                    break
                threading.Event().wait(0.01)
            if self._tid:
                user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            self._thread.join(timeout=1.0)
        except Exception:
            pass
        self.available = False
