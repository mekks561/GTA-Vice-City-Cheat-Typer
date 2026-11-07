# -*- coding: utf-8 -*-
"""1.7：发送引擎——把一段代码按节奏敲出去，且随时可以停。

设计约束
--------
本模块**与平台无关**：不 import ctypes、不直接调用 Win32。
所有按键动作与时间推进都由调用方注入（`send_key` / `sleep` / `lookup_vk`），
这样单元测试可以用假函数断言"发了哪几个键、什么顺序、取消后有没有漏抬起"，
不需要真实键盘，也不需要 Windows。

为什么要单独抽出来
------------------
1.6 之前发送逻辑写在 `CheatApp._send_worker` 里，与 tk 变量、前台校验、
IME 守卫、统计上报缠在一起，无法单测；「取消」也就无处下钩子。

六条硬约定（每条都有对应单测）
------------------------------
1. 睡眠一律切片（≤`SLEEP_SLICE_MS`），停止标志最多 20ms 内被看到；
2. 每个字符发送前检查停止标志，取消不会多发一个字符；
3. 按下与抬起成对出现，抬起放在 `finally`——取消/异常都不会留残键；
4. 非法字符抛 `SendError`（`ValueError` 子类），此时无按键处于按下状态；
5. `pre_delay` 阶段同样可中断（这条最容易被漏：触发后 180ms 里按暂停必须立刻停）；
6. 不直接调用 Win32：键码解析由 `lookup_vk` 注入。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

SLEEP_SLICE_MS = 20     # 可中断睡眠的切片长度：越小越灵敏，越小唤醒越频繁
_VK_LSHIFT = 0xA0       # 左 Shift 的虚拟键码（只在 sender 内部用，不依赖 winapi）


@dataclass(frozen=True)
class SendParams:
    """一次发送的全部参数（纯数据，不可变，可安全跨线程传递）。"""

    code: str
    interval_ms: int = 45      # 每个字符的总间隔（含 hold）
    hold_ms: int = 25          # 按下到抬起的保持时间，必须大于游戏帧间隔
    pre_delay_ms: int = 180    # 触发后先等一会，让手指离开修饰键
    uppercase: bool = False    # 是否按住 Shift 发送（大写）

    @classmethod
    def for_code(cls, code: str, interval_ms: int = 45, pre_delay_ms: int = 180,
                 uppercase: bool = False, hold_ms: Optional[int] = None) -> "SendParams":
        """由"代码 + 间隔"构造参数，把 hold 的换算规则收在一处。

        hold 取间隔的一半并夹在 8~60ms：太短会被低帧率漏掉，
        太长则独占按键、影响连打速度。1.6 在 `_send_worker` 里手写过同样的式子。
        """
        interval = max(10, int(interval_ms))
        return cls(
            code=str(code),
            interval_ms=interval,
            hold_ms=default_hold(interval) if hold_ms is None else max(0, int(hold_ms)),
            pre_delay_ms=max(0, int(pre_delay_ms)),
            uppercase=bool(uppercase),
        )


def default_hold(interval_ms: int) -> int:
    """间隔 -> 保持时间（8~60ms，取一半）。"""
    return min(max(8, int(interval_ms) // 2), 60)


class SendCancelled(Exception):
    """发送被取消（用户点停止 / 暂停 / 关闭程序）。

    带上进度信息，便于日志与悬浮提示说明"停在第几个字符"。
    """

    def __init__(self, sent: int, total: int) -> None:
        super().__init__(f"已取消 {sent}/{total}")
        self.sent = sent
        self.total = total


class SendError(ValueError):
    """发送失败（前台不匹配、非法字符、注入被拒）。

    继承 `ValueError`：非法字符本质是"参数不合法"，
    调用方既可按 `SendError` 精确捕获，也可按 `ValueError` 粗粒度兜底。
    """

    def __init__(self, reason: str, sent: int = 0, total: int = 0) -> None:
        super().__init__(reason)
        self.reason = reason
        self.sent = sent
        self.total = total


class _Cancelled(Exception):
    """内部信号：睡眠切片里发现停止标志。

    只携带"已完整发送的字符数"，由 `type_text` 统一转成 `SendCancelled`，
    避免在每个睡眠点复制 total 的拼接逻辑。
    """

    def __init__(self, sent: int) -> None:
        self.sent = sent


def _sleep_ms(ms: float, stop, sleep: Callable[[float], None], sent: int) -> None:
    """可中断睡眠：按 ≤20ms 切片推进，每片前检查停止标志。

    `sleep` 接收秒（与 `time.sleep` 一致），便于生产环境直接注入。
    """
    remain = max(0.0, float(ms))
    while remain > 0:
        if stop is not None and stop.is_set():
            raise _Cancelled(sent)
        step = min(SLEEP_SLICE_MS, remain)
        sleep(step / 1000.0)
        remain -= step


def type_text(params: SendParams, stop=None, *,
              send_key: Callable[[int, bool], None],
              sleep: Callable[[float], None],
              lookup_vk: Callable[[str], Optional[int]],
              check_target: Optional[Callable[[], bool]] = None,
              on_progress: Optional[Callable[[int, int], None]] = None) -> int:
    """按 `params` 敲出整段代码，返回实际发送的字符数。

    参数
    ----
    stop          : `threading.Event`（或任何有 `.is_set()` 的对象），置位即停；
    send_key      : `(vk, keyup) -> None`，生产环境注入 `winapi` 的按键原语；
    sleep         : `(seconds) -> None`，生产环境注入 `time.sleep`；
    lookup_vk     : `(char) -> vk | None`，字符到虚拟键码，None 表示不可输入；
    check_target  : 每字符前调用，返回 False 则中止（前台校验用）；
    on_progress   : `(sent, total)`，每成功一个字符回调一次。

    异常
    ----
    SendCancelled : 停止标志被置位（含 `pre_delay` 与字符间隔期间）；
    SendError     : 非法字符 / 目标窗口失焦 / 注入失败。

    无论走哪条路径退出，都不会留下按下的键（含 Shift）。
    """
    code = params.code or ""
    total = len(code)
    interval = max(10, int(params.interval_ms))
    hold = max(0, int(params.hold_ms))
    sent = 0
    shift_down = False
    try:
        # pre_delay 也要可中断：触发后这 180ms 里按暂停，必须立刻停手
        _sleep_ms(params.pre_delay_ms, stop, sleep, 0)

        if params.uppercase:
            send_key(_VK_LSHIFT, False)
            shift_down = True

        for ch in code:
            if stop is not None and stop.is_set():
                raise _Cancelled(sent)
            if check_target is not None and not check_target():
                raise SendError("目标窗口失去焦点，已中止输入", sent, total)

            vk = lookup_vk(ch)
            if vk is None:
                raise SendError(f"代码里有无法输入的字符：{ch!r}", sent, total)

            send_key(vk, False)
            try:
                # 保持时间可中断：取消时就地抬起，不留残键
                _sleep_ms(hold, stop, sleep, sent)
            finally:
                send_key(vk, True)

            sent += 1
            if on_progress is not None:
                on_progress(sent, total)
            _sleep_ms(max(0, interval - hold), stop, sleep, sent)

        return sent
    except _Cancelled as exc:
        raise SendCancelled(exc.sent, total) from None
    finally:
        if shift_down:
            send_key(_VK_LSHIFT, True)
