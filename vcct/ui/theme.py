# -*- coding: utf-8 -*-
"""2.2 Nova UI：设计令牌、双主题与对比度计算。

这是**唯一允许出现颜色字面量的 UI 模块**（它就是令牌源）。
其余 `vcct/ui/` 模块必须从这里取色，由 `tests/test_v2_2.py` 守住。

设计取舍：不换 UI 工具包、不引入第三方依赖。`vcct.const.C` 是可变字典且被
主程序按引用导入，因此 `apply_theme()` 只需**原地更新**它，1.7～2.1 的
上百处 `C["bg"]` 用法无需改动即可跟随新主题——这也是"核心零改动"的关键。
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

THEMES = ("light", "dark")
DENSITIES = ("comfortable", "compact")

_LIGHT = {
    "bg": "#f4f6fa", "panel": "#ffffff", "line": "#dfe4ec",
    "text": "#161c28", "muted": "#5b6472", "accent": "#2f61e8",
    "ok": "#0b7147", "warn": "#b42318", "soft": "#eaf1ff",
    # Nova 扩展令牌
    "sidebar": "#eef2f9", "sidebar_active": "#dde8ff", "topbar": "#ffffff",
    "card": "#ffffff", "card_border": "#dde3ed", "pill": "#eef2f8",
    "pill_text": "#3b4657", "on_accent": "#ffffff", "hover": "#e6edff",
    "status_ok": "#e7f6ee", "status_warn": "#fdeceb", "status_idle": "#edf0f5",
    "shadow": "#c9d2e0",
}

# 深色为独立完整定义，避免任何键缺失（V3 验收）
_DARK = {
    "bg": "#0e1420", "panel": "#182131", "line": "#2b3a4f",
    "text": "#e8edf5", "muted": "#9aa8bd", "accent": "#6b9bff",
    "ok": "#4ade9b", "warn": "#ff8a80", "soft": "#1e2d47",
    "sidebar": "#131c2b", "sidebar_active": "#26395a", "topbar": "#182131",
    "card": "#1b2637", "card_border": "#2b3a4f", "pill": "#233149",
    "pill_text": "#c8d4e6", "on_accent": "#0e1420", "hover": "#26395a",
    "status_ok": "#173c30", "status_warn": "#452322", "status_idle": "#233149",
    "shadow": "#080d16",
}

PALETTES = {"light": _LIGHT, "dark": _DARK}

# 经典配色（1.7～2.1），用于 classic 回退
_CLASSIC = {
    "bg": "#f5f6f8", "panel": "#ffffff", "line": "#e3e7ee",
    "text": "#1a1f29", "muted": "#6b7280", "accent": "#2563eb",
    "ok": "#067647", "warn": "#b42318", "soft": "#eef4ff",
}

_SPACING = {"xs": 4, "sm": 8, "md": 12, "lg": 18, "xl": 26}
_FONTS = {"family": "Microsoft YaHei UI", "size": 10, "small": 9, "h1": 16, "h2": 12}
_DENSITY_FACTOR = {"comfortable": 1.0, "compact": 0.72}


@dataclass(frozen=True)
class Tokens:
    """一次渲染所需的全部设计参数（不可变，可安全传递）。"""

    theme: str
    density: str
    colors: dict
    spacing: dict
    fonts: dict

    def __getitem__(self, key: str):
        return self.colors[key]

    def space(self, key: str) -> int:
        return int(round(self.spacing[key] * _DENSITY_FACTOR[self.density]))

    def font(self, key: str = "size") -> tuple:
        return (self.fonts["family"], self.fonts[key])

    def to_dict(self) -> dict:
        return asdict(self)


def tokens(theme: str = "light", density: str = "comfortable") -> Tokens:
    """取一套完整令牌；非法取值回落到默认（对脏配置宽容）。"""
    t = theme if theme in THEMES else "light"
    d = density if density in DENSITIES else "comfortable"
    return Tokens(t, d, dict(PALETTES[t]), dict(_SPACING), dict(_FONTS))


def apply_theme(theme: str = "light", classic: bool = False) -> dict:
    """把主题**原地**写入 `vcct.const.C`，让全部既有配色引用自动跟随。

    返回写入后的调色板副本。classic=True 时恢复 1.7～2.1 原配色（回退路径）。
    """
    from .. import const  # 延迟导入，避免 UI 层在 core 导入路径里被牵连
    palette = dict(_CLASSIC) if classic else dict(PALETTES.get(theme, _LIGHT))
    const.C.clear()
    const.C.update(palette)
    return dict(palette)


def classic_palette() -> dict:
    return dict(_CLASSIC)


def _luminance(color: str) -> float:
    rgb = [int(color.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast_ratio(fg: str, bg: str) -> float:
    """WCAG 2.1 相对对比度（1.0 ~ 21.0）。"""
    a, b = _luminance(fg), _luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def check_contrast(palette: dict, minimum: float = 4.5) -> dict:
    """验收 V2：返回每对关键前景/背景的对比度与是否达标。"""
    pairs = {
        "text_on_bg": (palette["text"], palette["bg"]),
        "muted_on_bg": (palette["muted"], palette["bg"]),
        "text_on_panel": (palette["text"], palette["panel"]),
        "on_accent": (palette["on_accent"], palette["accent"]),
        "pill_text_on_pill": (palette["pill_text"], palette["pill"]),
    }
    return {name: {"ratio": round(contrast_ratio(fg, bg), 2),
                   "pass": contrast_ratio(fg, bg) >= minimum}
            for name, (fg, bg) in pairs.items()}
