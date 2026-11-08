# -*- coding: utf-8 -*-
"""1.9-D：多游戏模板（内容侧）。

重要：GTA III / GTA SA 模板只录入**公开流传的秘籍文本**，未在本工具上实机验证，
每条 `verified=False`，UI 灰显标注。切模板 = 换整套秘籍 + 参数，方案之间互不污染。
"""
from __future__ import annotations

import uuid

from .store import default_cheats

TEMPLATE_NAMES = ("VC 经典版", "VC 决定版", "GTA III（未验证）", "GTA SA（未验证）")

TEMPLATE_INFO = {
    "VC 经典版": {
        "preset": "经典版",
        "description": "内置 28 条已核对秘籍，参数预设 45ms / 180ms，F1–F11 全预绑定。",
        "verified": True,
        "differences": [],
    },
    "VC 决定版": {
        "preset": "决定版",
        "description": "与经典版同一套代码，但按 Unreal 引擎的输入窗口整体放慢到 70ms / 250ms。",
        "verified": True,
        "differences": [
            "决定版部分秘籍效果有差异，个别代码可能无效（以游戏内提示为准）",
            "读档 / 过场动画期间输入会被吞，建议在可自由行动的画面触发",
            "帧率不固定，丢字请把每字间隔再调大到 90ms 以上",
        ],
    },
    "GTA III（未验证）": {
        "preset": None,
        "description": "GTA III 公开秘籍文本（未在 VC 输入器上实机验证），默认不绑定热键。",
        "verified": False,
        "differences": ["所有条目均标注「未实机验证」，请自行确认效果后再绑定热键"],
    },
    "GTA SA（未验证）": {
        "preset": None,
        "description": "GTA: San Andreas 公开秘籍文本（未实机验证），默认不绑定热键。",
        "verified": False,
        "differences": ["所有条目均标注「未实机验证」，请自行确认效果后再绑定热键"],
    },
}

# GTA III：公开秘籍文本（仅字母数字代码），未实机验证
_GTA3 = [
    ("全部武器", "GUNSGUNSGUNS", "武器"),
    ("满血", "GESUNDHEIT", "生存"),
    ("满护甲", "TURTOISE", "生存"),
    ("$250000", "IFIWEREARICHMAN", "生存"),
    ("清除通缉", "NOPOLICEPLEASE", "通缉"),
    ("通缉 +2 星", "MOREPOLICEPLEASE", "通缉"),
    ("坦克", "GIVEUSATANK", "载具"),
    ("炸毁附近车辆", "BANGBANGBANG", "载具"),
    ("飞行汽车", "CHITTYCHITTYBANGBANG", "改装"),
    ("操控改善", "CORNERSLIKEMAD", "改装"),
    ("隐形车", "ANICESETOFWHEELS", "改装"),
    ("行人持枪", "WEAPONSFORALL", "市民"),
    ("行人攻击", "NOBODYLIKESME", "市民"),
    ("行人暴动", "ITSALLGOINGMAAAD", "市民"),
    ("晴天", "SKINCANCERFORME", "天气"),
    ("多云", "APLEASANTDAY", "天气"),
    ("暴雨", "MADWEATHER", "天气"),
    ("时间加速", "TIMEFLIESWHENYOU", "天气"),
]

# GTA SA：公开秘籍文本（仅字母数字代码），未实机验证
_GTASA = [
    ("满血满甲+$250k", "HESOYAM", "生存"),
    ("无限护甲", "BAGUVIX", "生存"),
    ("无限氧气", "CVWKXAM", "生存"),
    ("永不饥饿", "AEDUWNV", "生存"),
    ("全部武器", "LXGIWYL", "武器"),
    ("武器套装 2", "PROFESSIONALKILLER", "武器"),
    ("武器套装 3", "UZUMYMW", "武器"),
    ("无限弹药", "FULLCLIP", "武器"),
    ("清除通缉", "ASNAEB", "通缉"),
    ("通缉 +2 星", "BAGOWPG", "通缉"),
    ("永不被通缉", "AEZAKMI", "通缉"),
    ("坦克", "AIYPWZQP", "载具"),
    ("喷射背包", "JUMPJET", "载具"),
    ("飞行汽车", "URKQSRK", "载具"),
    ("赛车", "PDNEJOH", "载具"),
    ("加长车", "KRIJEBR", "载具"),
    ("完美操控", "JHMCFCQ", "改装"),
    ("晴天", "PLEASANTLYWARM", "天气"),
    ("暴雨", "AUIFRVQS", "天气"),
    ("阴天", "ALNSFMZO", "天气"),
    ("快动作", "PPGWJTON", "天气"),
    ("慢动作", "LIYOAAY", "天气"),
    ("行人持枪", "FOOOXFT", "市民"),
    ("行人暴动", "AJLOJYQY", "市民"),
]


def _entry(name: str, code: str, group: str, game: str, verified: bool,
           note: str = "") -> dict:
    return {"id": uuid.uuid4().hex[:8], "name": name, "code": code, "hotkey": "",
            "group": group, "note": note, "interval_ms": 0,
            "verified": verified, "game": game, "source_pack": ""}


def template_cheats(name: str) -> list[dict]:
    """返回一套**全新 id** 的秘籍列表（纯函数，每次调用互不共享引用）。"""
    info = TEMPLATE_INFO.get(name)
    if info is None:
        return []
    if name in ("VC 经典版", "VC 决定版"):
        out = []
        for c in default_cheats():
            item = dict(c)
            item["verified"] = True
            item["game"] = name
            item["source_pack"] = ""
            if name == "VC 决定版":
                item["note"] = (item.get("note") or "") + "　【决定版：效果可能有差异】"
            out.append(item)
        return out
    rows = _GTA3 if name.startswith("GTA III") else _GTASA
    note = "未实机验证：公开秘籍文本，请先自行确认效果；默认未绑定热键"
    return [_entry(n, code, g, name, False, note) for n, code, g in rows]


def template_preset(name: str) -> dict:
    """模板对应的参数预设覆盖（空 dict = 不改参数）。"""
    from .const import PRESETS
    info = TEMPLATE_INFO.get(name) or {}
    preset = info.get("preset")
    return dict(PRESETS[preset]) if preset in PRESETS else {}
