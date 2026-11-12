# -*- coding: utf-8 -*-
"""2.0：扩展点（前置 / 后置钩子），纯逻辑、零 Win32、默认关闭。

设计约束
--------
* `HookBus` 本身不 import 任何平台 API：切窗口这类动作由调用方**注入函数**
  后通过工厂 `make_switch_window_hook` 生成，因此 core 层保持可移植。
* 默认没有任何钩子注册 → 发送行为与 1.9.1 完全一致（G2.0 gate）。
* 前置钩子返回 False 可以否决本次发送；钩子自身抛异常不会影响发送（只记录）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

BeforeHook = Callable[[dict, dict], bool | None]
AfterHook = Callable[[dict], None]


@dataclass
class HookEvent:
    """钩子调用记录（便于 CLI / 日志排查，不写盘）。"""

    phase: str
    hook: str
    ok: bool
    detail: str = ""


@dataclass
class HookBus:
    enabled: bool = False
    _before: list[tuple[str, BeforeHook]] = field(default_factory=list)
    _after: list[tuple[str, AfterHook]] = field(default_factory=list)
    events: list[HookEvent] = field(default_factory=list)

    def register_before(self, name: str, fn: BeforeHook) -> None:
        self._before.append((name, fn))

    def register_after(self, name: str, fn: AfterHook) -> None:
        self._after.append((name, fn))

    def clear(self) -> None:
        self._before.clear()
        self._after.clear()

    def fire_before(self, target: dict, cheat: dict) -> bool:
        """返回 True = 允许发送。没启用 / 没钩子时恒为 True。"""
        if not self.enabled or not self._before:
            return True
        for name, fn in self._before:
            try:
                veto = fn(target or {}, cheat or {})
                self.events.append(HookEvent("before", name, veto is not False))
                if veto is False:
                    return False
            except Exception as exc:
                self.events.append(HookEvent("before", name, False, str(exc)))
        return True

    def fire_after(self, result: dict) -> None:
        if not self.enabled or not self._after:
            return
        for name, fn in self._after:
            try:
                fn(result or {})
                self.events.append(HookEvent("after", name, True))
            except Exception as exc:
                self.events.append(HookEvent("after", name, False, str(exc)))


def make_switch_window_hook(
    get_hwnd: Callable[[], int], activate: Callable[[int], bool], get_foreground: Callable[[], int] | None = None
) -> tuple[BeforeHook, AfterHook]:
    """内置示例①：发送前切到目标窗口、发送后回切（**默认不注册**）。

    三个函数全部由调用方注入，hooks 模块因此不 import ctypes / winapi。
    """
    state: dict = {"previous": 0}

    def before(_target: dict, _cheat: dict):
        hwnd = int(get_hwnd() or 0)
        if not hwnd:
            return None
        state["previous"] = int(get_foreground() or 0) if get_foreground else 0
        return None if activate(hwnd) else False

    def after(_result: dict):
        prev = int(state.get("previous") or 0)
        if prev:
            activate(prev)
            state["previous"] = 0

    return before, after


def make_log_hook(sink: Callable[[str], None]) -> tuple[BeforeHook, AfterHook]:
    """内置示例②：纯日志钩子（不碰窗口，适合 CLI / 无桌面环境）。"""

    def before(_target: dict, cheat: dict):
        sink(f"准备发送：{cheat.get('code', '')}")
        return None

    def after(result: dict):
        sink(f"发送结束：result={result.get('result')} sent={result.get('sent')}")

    return before, after
