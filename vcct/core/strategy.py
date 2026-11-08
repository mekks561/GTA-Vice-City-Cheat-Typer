# -*- coding: utf-8 -*-
"""2.0：发送策略引擎（纯逻辑，零 Win32 / 零 tkinter）。

只暴露 5 个参数（路线图 R2.0.2 的反过度设计约束）：
`kind` / `interval_ms` / `hold_ms` / `pre_delay_ms` / `retries`。

三种策略
--------
* `fixed`    —— 固定间隔（**默认**，行为与 1.9.1 逐项一致，不重试）
* `burst`    —— 整串尽量快（间隔夹到下限、保持时间最短），不重试
* `adaptive` —— 丢字/注入失败时按剩余字符**自动加长间隔**并重试（最多 retries 次）

策略可以放在 `store["strategies"]`（具名，供 target.strategy_ref 引用），
也可以直接写在单条秘籍的 `strategy` 字段上。任何缺省都回落到 fixed + 现有参数。
"""
from __future__ import annotations

from dataclasses import dataclass

from ..sender import SendParams

STRATEGY_KINDS = ("fixed", "adaptive", "burst")
DEFAULT_STRATEGY = "fixed"


@dataclass(frozen=True)
class SendStrategy:
    """一次发送的策略（不可变）。None 值 = 沿用调用方的现有参数。"""

    kind: str = DEFAULT_STRATEGY
    interval_ms: int | None = None
    hold_ms: int | None = None
    pre_delay_ms: int | None = None
    retries: int = 0

    def to_dict(self) -> dict:
        return {"kind": self.kind, "interval_ms": self.interval_ms,
                "hold_ms": self.hold_ms, "pre_delay_ms": self.pre_delay_ms,
                "retries": self.retries}


def _clamp_int(value, lo: int, hi: int, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(lo, n), hi)


def normalize_strategy(raw) -> dict:
    """任意输入 → 合法策略字典（纯函数）。非法 kind 回落 fixed。"""
    raw = raw if isinstance(raw, dict) else {}
    kind = str(raw.get("kind") or DEFAULT_STRATEGY).strip().lower()
    if kind not in STRATEGY_KINDS:
        kind = DEFAULT_STRATEGY
    return SendStrategy(
        kind=kind,
        interval_ms=_clamp_int(raw.get("interval_ms"), 10, 300),
        hold_ms=_clamp_int(raw.get("hold_ms"), 0, 200),
        pre_delay_ms=_clamp_int(raw.get("pre_delay_ms"), 0, 2000),
        retries=int(_clamp_int(raw.get("retries"), 0, 3, 0) or 0),
    ).to_dict()


def normalize_strategies(raw, limit: int = 20) -> dict:
    """具名策略表（store['strategies']），保留白名单内的名字。"""
    if not isinstance(raw, dict):
        return {}
    out = {}
    for name, spec in list(raw.items())[:limit]:
        key = str(name).strip()
        if key:
            out[key] = normalize_strategy(spec)
    return out


def resolve_strategy(named: dict | None, cheat: dict | None = None) -> dict:
    """秘籍级覆盖 > 具名策略 > fixed 默认（纯函数）。"""
    base = normalize_strategy(cheat.get("strategy") if isinstance(cheat, dict) else None)
    if base["kind"] != DEFAULT_STRATEGY or any(
            base[k] is not None for k in ("interval_ms", "hold_ms", "pre_delay_ms")):
        return base
    ref = str((cheat or {}).get("strategy_ref") or "") if isinstance(cheat, dict) else ""
    if ref and isinstance(named, dict) and ref in named:
        return normalize_strategy(named[ref])
    return normalize_strategy(None)


def plan_send(strategy: dict, code: str, base_interval: int, base_pre: int,
              uppercase: bool = False, attempt: int = 0) -> SendParams:
    """把策略 + 现有参数合成 `SendParams`（纯函数，不碰键盘）。

    `attempt > 0` 表示自适应重试：不再重复前置延迟，且间隔按次数加长。
    """
    s = normalize_strategy(strategy)
    interval = int(s["interval_ms"] if s["interval_ms"] is not None else base_interval)
    pre = int(s["pre_delay_ms"] if s["pre_delay_ms"] is not None else base_pre)
    hold = s["hold_ms"]
    if s["kind"] == "burst":
        interval = min(interval, max(10, 20))
        hold = 8 if hold is None else min(int(hold), 12)
    elif s["kind"] == "adaptive" and attempt > 0:
        interval = min(300, interval + 15 * attempt)
        hold = None if hold is None else min(200, int(hold) + 5 * attempt)
    if attempt > 0:
        pre = 0     # 重试不该再等一次"手指离开修饰键"的前置延迟
    return SendParams.for_code(code, interval, pre, uppercase, hold_ms=hold)


def should_retry(strategy: dict, attempt: int, sent: int, total: int) -> bool:
    """是否还有重试额度（纯函数）。fixed / burst 永不重试。"""
    s = normalize_strategy(strategy)
    if s["kind"] != "adaptive" or sent >= total:
        return False
    return attempt < int(s["retries"] or 0)


def describe_plan(strategy: dict, code: str, base_interval: int, base_pre: int) -> dict:
    """CLI 预演用：返回一次发送计划的纯数据（不执行）。"""
    p = plan_send(strategy, code, base_interval, base_pre)
    return {"code": p.code, "kind": normalize_strategy(strategy)["kind"],
            "interval_ms": p.interval_ms, "hold_ms": p.hold_ms,
            "pre_delay_ms": p.pre_delay_ms,
            "planned_seconds": round(
                (p.pre_delay_ms + len(p.code) * p.interval_ms) / 1000.0, 3),
            "chars": len(p.code), "retries": normalize_strategy(strategy)["retries"]}
