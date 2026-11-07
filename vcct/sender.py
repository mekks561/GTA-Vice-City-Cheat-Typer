# -*- coding: utf-8 -*-
"""1.7：发送引擎（类型与骨架；具体循环在 T-04 实现）。

设计约束
--------
本模块**与平台无关**：不 import ctypes、不直接调用 Win32。
所有按键动作与时间推进都由调用方注入（`send_key` / `sleep`），
这样单元测试可以用假函数断言"发了哪几个键、什么顺序、取消后有没有漏抬起"，
不需要真实键盘，也不需要 Windows。

为什么要单独抽出来
------------------
1.6 之前发送逻辑写在 `CheatApp._send_worker` 里，与 tk 变量、前台校验、
IME 守卫、统计上报缠在一起，无法单测；「取消」也就无处下钩子。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SendParams:
    """一次发送的全部参数（纯数据，不可变，可安全跨线程传递）。"""

    code: str
    interval_ms: int = 45      # 每个字符的总间隔（含 hold）
    hold_ms: int = 25          # 按下到抬起的保持时间，必须大于游戏帧间隔
    pre_delay_ms: int = 180    # 触发后先等一会，让手指离开修饰键
    uppercase: bool = False    # 是否按住 Shift 发送（大写）


class SendCancelled(Exception):
    """发送被取消（用户点停止 / 暂停 / 关闭程序）。

    带上进度信息，便于日志与悬浮提示说明"停在第几个字符"。
    """

    def __init__(self, sent: int, total: int) -> None:
        super().__init__(f"已取消 {sent}/{total}")
        self.sent = sent
        self.total = total


class SendError(Exception):
    """发送失败（前台不匹配、非法字符、注入被拒）。"""

    def __init__(self, reason: str, sent: int = 0, total: int = 0) -> None:
        super().__init__(reason)
        self.reason = reason
        self.sent = sent
        self.total = total
