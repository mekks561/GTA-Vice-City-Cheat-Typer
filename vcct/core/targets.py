# -*- coding: utf-8 -*-
"""2.0：目标应用规则化（纯逻辑，零 Win32 / 零 tkinter）。

设计取舍
--------
1.8 的 `games` 规则表只描述「进程/标题 → 切方案」。2.0 把它泛化成 `Target`：
除了切方案，还带上前台要求、IME 策略、发送策略引用——新增一个目标应用
（记事本、模拟器、老游戏）只需改配置，不改代码。

兼容性：`targets` 是 v3 可选字段，缺省空 = 完全沿用 1.8/1.9 的 games 行为；
`targets_from_games` 提供单向升级（纯函数，不写盘）。
"""

from __future__ import annotations

import re

from dataclasses import dataclass, asdict

MATCH_TYPES = ("exe", "title", "class")
IME_POLICIES = ("disable", "keep")


@dataclass(frozen=True)
class Target:
    """一个目标应用的规则（不可变，可安全跨线程传递）。"""

    name: str
    match_type: str = "exe"
    pattern: str = ""
    require_foreground: bool = True
    ime_policy: str = "disable"
    strategy_ref: str = ""
    profile_ref: str = ""
    enabled: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


def normalize_targets(raw) -> list[dict]:
    """脏数据逐条丢弃；未知字段忽略（对第三方手写配置宽容）。"""
    out: list[dict] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        pattern = str(item.get("pattern") or "").strip()
        if not pattern:
            continue
        match_type = str(item.get("match_type") or "exe").strip().lower()
        if match_type not in MATCH_TYPES:
            match_type = "exe"
        ime = str(item.get("ime_policy") or "disable").strip().lower()
        if ime not in IME_POLICIES:
            ime = "disable"
        out.append(
            Target(
                name=str(item.get("name") or pattern),
                match_type=match_type,
                pattern=pattern,
                require_foreground=bool(item.get("require_foreground", True)),
                ime_policy=ime,
                strategy_ref=str(item.get("strategy_ref") or ""),
                profile_ref=str(item.get("profile_ref") or ""),
                enabled=bool(item.get("enabled", True)),
            ).to_dict()
        )
    return out


def match_target(target: dict, title: str = "", exe: str = "", class_name: str = "") -> bool:
    """单条规则匹配（大小写不敏感子串）。class 需要调用方提供窗口类名。"""
    if not target.get("enabled"):
        return False
    kind = target.get("match_type", "exe")
    hay = {"exe": exe, "title": title, "class": class_name}.get(kind, exe) or ""
    pattern = str(target.get("pattern") or "")
    return bool(pattern) and pattern.lower() in str(hay).lower()


def evaluate_targets(targets: list[dict], title: str = "", exe: str = "", class_name: str = "") -> dict | None:
    """返回第一条命中的启用规则（纯函数）。"""
    for t in targets or []:
        if match_target(t, title, exe, class_name):
            return t
    return None


def targets_from_games(games) -> list[dict]:
    """1.8 games → 2.0 targets 单向升级（纯函数）。"""
    out = []
    for g in games or []:
        if not isinstance(g, dict):
            continue
        out.append(
            {
                "name": str(g.get("name") or g.get("pattern") or "目标"),
                "match_type": str(g.get("match_type") or "exe"),
                "pattern": str(g.get("pattern") or ""),
                "require_foreground": True,
                "ime_policy": "disable",
                "strategy_ref": "",
                "profile_ref": str(g.get("profile") or ""),
                "enabled": bool(g.get("enabled", True)),
            }
        )
    return normalize_targets(out)


def resolve_target(target: dict, store: dict | None = None) -> dict:
    """把规则解析成发送所需的具体参数（纯函数；不存在的方案/策略名回落默认）。

    返回 {profile, strategy, require_foreground, disable_ime}。
    `strategy` 为空字符串表示「沿用现有全局参数」，这是保证默认行为一致的关键。
    """
    store = store or {}
    names = {p.get("name") for p in (store.get("profiles") or [])}
    strategies = store.get("strategies") or {}
    profile = str(target.get("profile_ref") or "")
    if profile and profile not in names:
        profile = ""
    ref = str(target.get("strategy_ref") or "")
    return {
        "profile": profile,
        "strategy": ref if ref in strategies else "",
        "require_foreground": bool(target.get("require_foreground", True)),
        "disable_ime": str(target.get("ime_policy") or "disable") != "keep",
    }


def parse_target_spec(text: str) -> dict | None:
    """CLI 辅助：解析 `exe:gta-vc` / `title:Vice City` 这样的简短描述。"""
    m = re.match(r"^(exe|title|class)\s*[:=]\s*(.+)$", str(text or "").strip(), re.I)
    if not m:
        return None
    return {"match_type": m.group(1).lower(), "pattern": m.group(2).strip()}
