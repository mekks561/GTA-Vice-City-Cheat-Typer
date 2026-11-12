# -*- coding: utf-8 -*-
"""秘籍条目的唯一 schema：字段归一化与校验。

所有入口（配置加载、秘籍包、文本导入、编辑对话框）都应该走这里，
避免"某个入口多/少字段"造成的数据丢失（例如 2.0 的 strategy 字段）。

本模块只依赖标准库，属于最底层，供 store / packs / importer / UI 共用。
`normalize_strategy` 的字段与范围必须与 `vcct/core/strategy.py` 保持一致，
由 tests/test_core.py 的往返用例守护。
"""

from __future__ import annotations

import re
import uuid

# 与游戏内秘籍一致：字母/数字，2~40 位（不含空格与符号）
CODE_RE = re.compile(r"^[A-Z0-9]{2,40}$")

DEFAULT_GROUP = "自定义"
STRATEGY_KINDS = ("fixed", "adaptive", "burst")


def clean_code(value) -> str:
    """去掉所有空白并大写：兼容从网页/聊天窗口粘贴出的空格与换行。"""
    return re.sub(r"\s+", "", str(value or "")).upper()


def is_valid_code(code) -> bool:
    """严格校验：只允许 2~40 位字母/数字。"""
    return bool(CODE_RE.fullmatch(str(code or "")))


def _clamp_int(value, lo: int, hi: int, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(lo, n), hi)


def _bounded_or(value, lo: int, hi: int, default: int = 0) -> int:
    """越界/脏值一律回落 default（秘籍级 interval 沿用 1.6 的"越界=跟随全局"语义）。"""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return n if lo <= n <= hi else default


def normalize_strategy(raw) -> dict | None:
    """单条秘籍的策略覆盖；空/非法输入返回 None（= 跟随全局策略）。"""
    if not isinstance(raw, dict) or not raw:
        return None
    kind = str(raw.get("kind") or "fixed").strip().lower()
    if kind not in STRATEGY_KINDS:
        kind = "fixed"
    return {
        "kind": kind,
        "interval_ms": _clamp_int(raw.get("interval_ms"), 10, 300),
        "hold_ms": _clamp_int(raw.get("hold_ms"), 0, 200),
        "pre_delay_ms": _clamp_int(raw.get("pre_delay_ms"), 0, 2000),
        "retries": int(_clamp_int(raw.get("retries"), 0, 3, 0) or 0),
    }


def normalize_cheat(item, *, strict_code: bool = False, source: bool = False) -> dict | None:
    """任意输入 → 规范秘籍字典；缺少代码返回 None。

    strict_code=True 时非法代码直接拒绝（新建/导入入口）；
    False 时只做去空白与大写（读取旧配置，避免静默丢数据）。
    source=True 时附带 game / source_pack 字段（store 专用）。
    """
    if not isinstance(item, dict):
        return None
    code = clean_code(item.get("code"))
    if not code:
        return None
    if strict_code and not is_valid_code(code):
        return None
    out = {
        "id": str(item.get("id") or uuid.uuid4().hex[:8]),
        "name": str(item.get("name") or "").strip() or code,
        "code": code,
        "hotkey": str(item.get("hotkey") or "").strip(),
        "group": str(item.get("group") or DEFAULT_GROUP).strip() or DEFAULT_GROUP,
        "note": str(item.get("note") or "").strip(),
        # 单条发送速度覆盖：0 = 跟随全局（1.6 新增，可选字段）
        "interval_ms": _bounded_or(item.get("interval_ms"), 0, 300, 0),
        # 1.9：游戏模板 / 来源包 / 是否实机验证（全部可选，缺省 = 旧行为）
        "verified": bool(item.get("verified", True)),
    }
    strategy = normalize_strategy(item.get("strategy"))
    if strategy:
        out["strategy"] = strategy
    ref = str(item.get("strategy_ref") or "").strip()
    if ref:
        out["strategy_ref"] = ref
    if source:
        out["game"] = str(item.get("game") or "")
        out["source_pack"] = str(item.get("source_pack") or "")
    return out
