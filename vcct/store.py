# -*- coding: utf-8 -*-
"""1.7：配置数据层——归一化、加载/保存、备份、整包导入导出、统计、过滤。

不依赖 tkinter，可在无桌面环境下测试。
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import time
import uuid

from .const import APP_NAME, DEFAULT_GAME, DEFAULT_SETTINGS, STORE_APP, STORE_VERSION
from .loggingx import append_log, backup_path, data_path
from .schema import normalize_cheat


def _c(name, code, hotkey, group, note):
    return {"id": uuid.uuid4().hex[:8], "name": name, "code": code, "hotkey": hotkey, "group": group, "note": note, "interval_ms": 0}


def default_cheats() -> list[dict]:
    return [
        # 武器
        _c("一级武器", "THUGSTOOLS", "F1", "武器", "指虎/球棒/燃烧瓶/手枪/霰弹…重复输入可无限弹药"),
        _c("二级武器", "PROFESSIONALTOOLS", "F2", "武器", "武士刀/357/SPAS12/M4/火箭筒…"),
        _c("三级武器", "NUTTERTOOLS", "F3", "武器", "电锯/手雷/加特林…"),
        # 生存
        _c("满血", "ASPIRINE", "F4", "生存", "开车时同时修轮胎"),
        _c("满护甲", "PRECIOUSPROTECTION", "F5", "生存", "护甲补满"),
        # 通缉
        _c("清除通缉", "LEAVEMEALONE", "F6", "通缉", "通缉星级归零"),
        _c("通缉 +2 星", "YOUWONTTAKEMEALIVE", "F7", "通缉", "每次 +2 星，慎用"),
        # 载具生成（默认不使用 F12：该键常被系统/调试器占用）
        _c("犀牛坦克", "PANZER", "F8", "载具", "在最近的车辆生成点出现"),
        _c("Sabre Turbo", "GETTHEREFAST", "F9", "载具", "肌肉跑车"),
        _c("高尔夫球车", "BETTERTHANWALKING", "F10", "载具", "Caddy"),
        _c("灵车", "THELASTRIDE", "F11", "载具", "Romero's Hearse"),
        _c("Love Fist 加长车", "ROCKANDROLLCAR", "Shift+F1", "载具", "加长礼车"),
        _c("垃圾车", "RUBBISHCAR", "Shift+F2", "载具", "Trashmaster"),
        # 载具特性
        _c("水上行驶", "SEAWAYS", "Shift+F3", "改装", "车辆可在水面行驶，再输一次取消"),
        _c("飞行汽车", "COMEFLYWITHME", "Shift+F4", "改装", "低重力，空中可控；直升机操作会变怪"),
        _c("操控提升", "GRIPISEVERYTHING", "Shift+F5", "改装", "抓地力/转向改善"),
        _c("超大轮子", "LOADSOFLITTLETHINGS", "Shift+F6", "改装", "车轮变大，重复输入继续变"),
        _c("隐形车", "WHEELSAREALLINEED", "Shift+F7", "改装", "只显示车轮"),
        _c("炸毁所有车", "BIGBANG", "Shift+F8", "改装", "附近车辆全部爆炸，会波及自己"),
        # 交通
        _c("全绿灯", "GREENLIGHT", "Shift+F9", "交通", "所有红绿灯变绿"),
        _c("疯狂驾驶", "MIAMITRAFFIC", "Shift+F10", "交通", "NPC 驾驶变得激进"),
        # 天气
        _c("晴天", "ALOVELYDAY", "Shift+F11", "天气", "晴朗天气"),
        _c("多云", "APLEASANTDAY", "Ctrl+Shift+F1", "天气", "阴天/多云"),
        _c("暴雨", "CATSANDDOGS", "Ctrl+Shift+F2", "天气", "风暴天气"),
        # 市民
        _c("市民暴动", "FIGHTFIGHTFIGHT", "Ctrl+Shift+F3", "市民", "★不可撤销：存盘后会永久影响存档"),
        _c("武装女性", "CHICKSWITHGUNS", "Ctrl+Shift+F4", "市民", "比基尼女性持枪"),
        _c("人人持枪", "OURGODGIVENRIGHTTOBEARARMS", "Ctrl+Shift+F5", "市民", "★不可撤销，会严重影响任务"),
        _c("女性跟随", "FANNYMAGNET", "Ctrl+Shift+F6", "市民", "特定女性会跟随 Tommy"),
    ]


def _safe_int(value, default: int = 0, lo: int = 0, hi: int = 1000) -> int:
    """宽松转 int：脏数据一律回落到 default，绝不让单条坏值毁掉整份配置。"""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return n if lo <= n <= hi else default


def _norm_cheat(item) -> dict | None:
    """配置读取入口：宽松模式（保留旧数据），唯一实现见 vcct/schema.py。"""
    return normalize_cheat(item, source=True)


def _norm_stats(raw) -> dict:
    stats = {}
    if isinstance(raw, dict):
        for code, v in raw.items():
            if isinstance(v, dict) and isinstance(v.get("count"), int):
                stats[str(code).upper()] = {"count": int(v["count"]), "last": str(v.get("last") or "")}
    return stats


def _norm_today(raw) -> dict:
    """当日使用计数（跨天自动归零，由 UI 判定日期是否过期）。"""
    if not isinstance(raw, dict):
        return {"date": "", "count": 0}
    return {"date": str(raw.get("date") or ""), "count": max(0, _safe_int(raw.get("count"), 0))}


# ----------------------------------------------------------------------------
# 1.8：按游戏自动切方案——games 规则表（纯函数，缺省空 = 旧行为）
# ----------------------------------------------------------------------------
def _norm_games(raw) -> list[dict]:
    """归一化游戏规则表。脏数据逐条丢弃，绝不让一条坏规则毁掉整份配置。"""
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
        if match_type not in ("exe", "title"):
            match_type = "exe"
        out.append(
            {
                "name": str(item.get("name") or pattern),
                "match_type": match_type,
                "pattern": pattern,
                "profile": str(item.get("profile") or "").strip(),
                "enabled": bool(item.get("enabled", True)),
            }
        )
    return out


def match_game_rule(rule: dict, title: str, exe: str) -> bool:
    """单条规则匹配（纯函数）：exe 按进程名、title 按窗口标题，均为大小写不敏感的子串匹配。"""
    if not rule.get("enabled"):
        return False
    hay = (exe if rule.get("match_type") == "exe" else title) or ""
    return str(rule.get("pattern") or "").lower() in hay.lower()


def evaluate_game_rules(games: list[dict], title: str, exe: str) -> dict | None:
    """返回第一条命中的启用规则；都不命中返回 None（纯函数）。"""
    for rule in games or []:
        if match_game_rule(rule, title, exe):
            return rule
    return None


def touch_today(raw, day: str | None = None, bump: bool = True) -> dict:
    """纯函数：把当日计数推进一天/加一次，返回新字典（便于单测）。"""
    day = day or time.strftime("%Y-%m-%d")
    entry = raw if isinstance(raw, dict) else {}
    if str(entry.get("date") or "") != day:
        entry = {"date": day, "count": 0}
    if bump:
        entry["count"] = max(0, _safe_int(entry.get("count"), 0)) + 1
    return entry


# ----------------------------------------------------------------------------
# 1.9-A：版本化迁移链（v1 → v2 → v3）
# ----------------------------------------------------------------------------
class StoreTooNew(Exception):
    """配置来自比当前程序更新的版本——绝不静默降级覆盖用户数据。"""

    def __init__(self, found: int, current: int):
        super().__init__(f"配置文件版本 v{found} 高于本程序支持的 v{current}，请升级程序。")
        self.found = found
        self.current = current


def _version_of(raw: dict) -> int:
    """推断配置版本：缺失 version 时按结构猜（v1 顶层 cheats / v2 有 profiles）。"""
    try:
        v = int(raw.get("version") or 0)
        if v >= 1:
            return v
    except (TypeError, ValueError):
        pass
    if isinstance(raw.get("profiles"), list) and raw["profiles"]:
        return 2
    return 1 if isinstance(raw.get("cheats"), list) else 2


def migrate_v1_to_v2(raw: dict) -> dict:
    """v1 单列表 → v2 多方案（纯函数，不碰磁盘）。"""
    out = copy.deepcopy(raw) if isinstance(raw, dict) else {}
    if not isinstance(out.get("profiles"), list) or not out["profiles"]:
        cheats = out.get("cheats")
        out["profiles"] = [{"name": "默认", "cheats": cheats}] if isinstance(cheats, list) and cheats else []
    out["version"] = 2
    out.setdefault("active_profile", "默认")
    return out


def migrate_v2_to_v3(raw: dict) -> dict:
    """v2 → v3：补 packs / ui / 方案 game 绑定；已有字段原样保留（纯函数）。"""
    out = copy.deepcopy(raw) if isinstance(raw, dict) else {}
    out["version"] = 3
    out.setdefault("packs", [])
    out.setdefault("ui", {})
    out.setdefault("games", [])
    for prof in out.get("profiles") or []:
        if isinstance(prof, dict):
            prof.setdefault("game", DEFAULT_GAME)
    return out


def migrate_store(raw: dict, current: int = STORE_VERSION) -> dict:
    """串行迁移链（**纯函数**：不碰磁盘、不写全局、不修改入参）。

    逐级可测：v1 → v2 → v3；读到更高版本抛 StoreTooNew，由 load_store 转成可读提示。
    """
    if not isinstance(raw, dict):
        raise ValueError("配置顶层不是对象")
    v = _version_of(raw)
    if v > current:
        raise StoreTooNew(v, current)
    out = copy.deepcopy(raw)
    if v < 2:
        out = migrate_v1_to_v2(out)
    if v < 3 <= current:
        out = migrate_v2_to_v3(out)
    out["version"] = current
    return out


def _norm_packs(raw) -> list[dict]:
    """已安装秘籍包记录（只留白名单字段，脏数据逐条丢弃）。"""
    out = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        out.append(
            {
                "name": name,
                "author": str(item.get("author") or ""),
                "game": str(item.get("game") or ""),
                "pack_version": _safe_int(item.get("pack_version"), 1, 0, 9999),
                "sha256": str(item.get("sha256") or ""),
                "imported_at": str(item.get("imported_at") or ""),
            }
        )
    return out


def _norm_targets(raw) -> list[dict]:
    """2.0 目标规则（惰性导入，避开 core.__init__ ↔ store 的循环依赖）。"""
    from .core.targets import normalize_targets

    return normalize_targets(raw)


def _norm_strategies(raw) -> dict:
    """2.0 具名发送策略表（同上）。"""
    from .core.strategy import normalize_strategies

    return normalize_strategies(raw)


def _norm_history(raw, limit: int = 50) -> list[dict]:
    """1.8-I 发送历史（最多 50 条，最新在前）。脏记录逐条丢弃。"""
    out: list[dict] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        if not isinstance(item, dict):
            continue  # 脏记录不计入上限：先过滤再截断
        try:
            elapsed = round(float(item.get("elapsed") or 0), 3)
        except (TypeError, ValueError):
            elapsed = 0.0
        out.append(
            {
                "at": str(item.get("at") or ""),
                "name": str(item.get("name") or ""),
                "code": str(item.get("code") or ""),
                "profile": str(item.get("profile") or ""),
                "result": str(item.get("result") or ""),
                "elapsed": max(0.0, elapsed),
                "detail": str(item.get("detail") or ""),
            }
        )
        if len(out) >= limit:
            break
    return out[:limit]


def _norm_ui(raw) -> dict:
    """UI 偏好（窗口位置 / 列宽），只留白名单字段。"""
    if not isinstance(raw, dict):
        return {}
    cols = raw.get("column_widths")
    geometry = str(raw.get("geometry") or "")
    widths = {str(k): _safe_int(v, 0, 0, 2000) for k, v in cols.items()} if isinstance(cols, dict) else {}
    if not geometry and not widths:
        return {}  # 空值不写进配置，保持与 default_store 一致
    return {"geometry": geometry, "column_widths": widths}


def _v2_cheat_keys() -> tuple[str, ...]:
    return ("id", "name", "code", "hotkey", "group", "note", "interval_ms")


def to_v2(store: dict) -> dict:
    """v3 → v2 降级导出（纯函数）：给仍用 1.6/1.7/1.8 的人留出口。

    丢掉的只有 v3 新字段（packs/ui/per-cheat verified/game/source_pack）；
    games 是 v2 可选字段，旧程序会安全忽略，保留即可。
    """
    keys = _v2_cheat_keys()
    profiles = [
        {"name": str(p.get("name") or "默认"), "cheats": [{k: c.get(k) for k in keys} for c in (p.get("cheats") or [])]}
        for p in (store.get("profiles") or [])
    ]
    return {
        "app": STORE_APP,
        "version": 2,
        "settings": {k: v for k, v in (store.get("settings") or {}).items() if k in DEFAULT_SETTINGS},
        "active_profile": store.get("active_profile", "默认"),
        "profiles": profiles,
        "stats": store.get("stats") or {},
        "today": _norm_today(store.get("today")),
        "games": _norm_games(store.get("games")),
    }


def export_v2(store: dict, path: str) -> None:
    """写出 v2 兼容配置（CLI `--export-v2` 用）。"""
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(to_v2(store), fh, ensure_ascii=False, indent=2)


def _norm_profiles(raw_profiles) -> list[dict]:
    """方案组归一化（纯函数）：读取与保存共用，避免写盘绕过字段清洗。"""
    if isinstance(raw_profiles, list) and raw_profiles:
        profiles = []
        for p in raw_profiles:
            if not isinstance(p, dict):
                continue
            cheats = [c for c in (_norm_cheat(i) for i in (p.get("cheats") or [])) if c]
            name = str(p.get("name") or "").strip() or "未命名"
            profiles.append({"name": name, "cheats": cheats, "game": str(p.get("game") or DEFAULT_GAME)})
    else:
        profiles = [{"name": "默认", "cheats": default_cheats(), "game": DEFAULT_GAME}]
    if not profiles:
        profiles = [{"name": "默认", "cheats": default_cheats(), "game": DEFAULT_GAME}]

    # 方案名去重
    seen_names: set[str] = set()
    for p in profiles:
        name = p["name"]
        i = 2
        while name in seen_names:
            name = f"{p['name']} ({i})"
            i += 1
        p["name"] = name
        seen_names.add(name)
    return profiles


def normalize_store(raw: dict) -> dict:
    """把任意版本的配置字典归一化为 v3（纯函数，不碰磁盘：整包导入也走这里）。"""
    if not isinstance(raw, dict):
        raw = {}
    migrated = migrate_store(raw)
    settings = dict(DEFAULT_SETTINGS)
    settings.update({k: v for k, v in (migrated.get("settings") or {}).items() if k in DEFAULT_SETTINGS})

    # 方案组：v1 已由迁移链包成 profiles；v2/v3 直接读
    profiles = _norm_profiles(migrated.get("profiles"))
    seen_names = {p["name"] for p in profiles}

    active = str(migrated.get("active_profile") or "").strip()
    if active not in seen_names:
        active = profiles[0]["name"]

    return {
        "app": STORE_APP,
        "version": STORE_VERSION,
        "settings": settings,
        "active_profile": active,
        "profiles": profiles,
        "stats": _norm_stats(migrated.get("stats")),
        "today": _norm_today(migrated.get("today")),
        "games": _norm_games(migrated.get("games")),  # 1.8：可选字段，缺省空 = 不自动切
        "packs": _norm_packs(migrated.get("packs")),  # 1.9：已安装秘籍包记录
        "ui": _norm_ui(migrated.get("ui")),  # 1.9：窗口位置 / 列宽
        "history": _norm_history(migrated.get("history")),  # 1.8-I：最近 50 次发送
        "targets": _norm_targets(migrated.get("targets")),  # 2.0：目标应用规则
        "strategies": _norm_strategies(migrated.get("strategies")),  # 2.0：具名发送策略
    }


def default_store() -> dict:
    return {
        "app": STORE_APP,
        "version": STORE_VERSION,
        "settings": dict(DEFAULT_SETTINGS),
        "active_profile": "默认",
        "profiles": [{"name": "默认", "cheats": default_cheats(), "game": DEFAULT_GAME}],
        "stats": {},
        "today": {"date": "", "count": 0},
        "games": [],
        "packs": [],
        "ui": {},
        "history": [],
        "targets": [],
        "strategies": {},
    }


LAST_LOAD_WARNING = ""  # 最近一次读取配置时的异常说明（供界面提示）
_FORBID_DEFAULT_SAVE = False  # 读到"来自更新版本"的配置时禁止回写，防止静默降级毁数据


def last_load_warning() -> str:
    """读取最近一次加载告警。

    必须用函数而不是 `from vcct.store import LAST_LOAD_WARNING`：
    load_store 会重新绑定这个全局，按值导入拿到的永远是导入那一刻的空串。
    """
    return LAST_LOAD_WARNING


def quarantine_corrupt(path: str) -> str:
    """把无法解析的配置改名留存，返回新路径；改名失败返回空串。"""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = os.path.join(os.path.dirname(path), f"cheats.corrupt-{stamp}.json")
    try:
        os.replace(path, target)
        return target
    except OSError:
        return ""


def backup_before_migration(path: str, version: int) -> str:
    """升 v3 前留一份**迁移前原件**（只留第一次，不覆盖）。返回备份路径或空串。"""
    target = os.path.join(os.path.dirname(path), f"cheats.v{version}.bak.json")
    if os.path.exists(target):
        return target
    try:
        shutil.copyfile(path, target)
        return target
    except OSError:
        return ""


def load_store(path: str | None = None) -> dict:
    """读取配置并归一化为 v3；损坏/来自更高版本的文件绝不静默丢数据。"""
    global LAST_LOAD_WARNING, _FORBID_DEFAULT_SAVE
    LAST_LOAD_WARNING = ""
    path = path or data_path()
    if path == data_path():
        _FORBID_DEFAULT_SAVE = False
    if not os.path.exists(path):
        store = default_store()
        save_store(store, path)
        return store
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception as exc:
        moved = quarantine_corrupt(path)
        LAST_LOAD_WARNING = (
            f"配置文件无法解析（{exc}）。"
            + (f"原文件已保留为 {os.path.basename(moved)}。" if moved else "原文件保留在原处。")
            + " 已载入默认秘籍表。"
        )
        append_log(LAST_LOAD_WARNING, "ERROR")
        return default_store()
    if not isinstance(raw, dict):
        moved = quarantine_corrupt(path)
        LAST_LOAD_WARNING = (
            "配置文件结构不正确（顶层不是对象）。"
            + (f"原文件已保留为 {os.path.basename(moved)}。" if moved else "")
            + " 已载入默认秘籍表。"
        )
        append_log(LAST_LOAD_WARNING, "ERROR")
        return default_store()

    found = _version_of(raw)
    if found > STORE_VERSION:
        LAST_LOAD_WARNING = (
            f"配置来自更新版本（v{found}），本程序最高支持 v{STORE_VERSION}。请升级程序；本次只载入默认数据，且**不会回写**你的配置文件。"
        )
        append_log(LAST_LOAD_WARNING, "ERROR")
        if path == data_path():
            _FORBID_DEFAULT_SAVE = True
        return default_store()
    if found < STORE_VERSION:
        saved = backup_before_migration(path, found)
        if saved:
            append_log(f"配置升级备份：{saved}（迁移前原件，v{found} → v{STORE_VERSION}）", "INFO")
    return normalize_store(raw)


def save_store(store: dict, path: str | None = None) -> None:
    """写 v3 配置；读到"来自更新版本"的配置时禁止回写默认路径（防静默降级）。"""
    if path is None and _FORBID_DEFAULT_SAVE:
        append_log("已阻止回写：配置来自更新版本，避免用默认数据覆盖用户文件。", "WARN")
        return
    path = path or data_path()
    settings = {k: v for k, v in (store.get("settings") or {}).items() if k in DEFAULT_SETTINGS}
    payload = {
        "app": STORE_APP,
        "version": STORE_VERSION,
        "settings": settings,
        "active_profile": store.get("active_profile", "默认"),
        "profiles": _norm_profiles(store.get("profiles")),
        "stats": store.get("stats", {}),
        "today": _norm_today(store.get("today")),
        "games": _norm_games(store.get("games")),
        "packs": _norm_packs(store.get("packs")),
        "ui": _norm_ui(store.get("ui")),
        "history": _norm_history(store.get("history")),
        "targets": _norm_targets(store.get("targets")),
        "strategies": _norm_strategies(store.get("strategies")),
    }
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        if os.path.exists(path):  # 覆盖前留一版，误操作/损坏可回滚
            try:
                shutil.copyfile(path, backup_path(path))
            except OSError:
                pass
        os.replace(tmp, path)
    except Exception as exc:  # 保存失败不该让工具崩掉
        print("保存配置失败:", exc, file=sys.stderr)
        append_log(f"保存配置失败: {exc}", "ERROR")


def bundle_payload(store: dict) -> dict:
    """整包备份的导出结构：设置 + 全部方案 + 统计 + 当日计数。"""
    return {
        "app": STORE_APP,
        "kind": "bundle",
        "version": STORE_VERSION,
        "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "settings": dict(store.get("settings") or {}),
        "active_profile": store.get("active_profile", "默认"),
        "profiles": store.get("profiles", []),
        "stats": store.get("stats", {}),
        "today": _norm_today(store.get("today")),
        "games": _norm_games(store.get("games")),
        "packs": _norm_packs(store.get("packs")),
        "ui": _norm_ui(store.get("ui")),
        "history": _norm_history(store.get("history")),
        "targets": _norm_targets(store.get("targets")),
        "strategies": _norm_strategies(store.get("strategies")),
    }


def parse_bundle(raw) -> tuple[dict | None, str]:
    """校验并归一化整包文件，返回 (store, 错误说明)。不写盘、不改动源文件。"""
    if not isinstance(raw, dict):
        return None, "文件顶层不是 JSON 对象。"
    app = str(raw.get("app") or "").strip()
    if app and app != STORE_APP:
        return None, f"这不是 {APP_NAME} 的备份（app={app}）。"
    if isinstance(raw.get("profile"), dict) and not raw.get("profiles"):
        return None, "这是单个方案文件，请用「导入方案」。"
    if not isinstance(raw.get("profiles"), list) or not raw["profiles"]:
        return None, "备份里没有任何方案，无法导入。"
    if _version_of(raw) > STORE_VERSION:
        return None, f"备份来自更新版本（v{_version_of(raw)}），请先升级程序再导入。"
    store = normalize_store(raw)
    if not any(p["cheats"] for p in store["profiles"]):
        return None, "备份里的方案都是空的，已取消导入。"
    return store, ""


def bump_stats(stats: dict, code: str) -> int:
    """累计使用次数，返回新次数（纯函数，便于测试）"""
    key = str(code).upper()
    entry = stats.setdefault(key, {"count": 0, "last": ""})
    entry["count"] = int(entry.get("count", 0)) + 1
    entry["last"] = time.strftime("%Y-%m-%d %H:%M")
    return entry["count"]


def filter_cheats(items: list[dict], group: str = "全部", query: str = "") -> list[dict]:
    """分组 + 关键字（名称/代码/备注/分组，大小写不敏感）叠加过滤。"""
    out = list(items)
    if group and group != "全部":
        out = [c for c in out if (c.get("group") or "自定义") == group]
    q = (query or "").strip().lower()
    if q:
        out = [c for c in out if q in " ".join(str(c.get(k) or "") for k in ("name", "code", "note", "group")).lower()]
    return out


def sorted_cheats(cheats: list[dict], key: str = "count", desc: bool = True, stats: dict | None = None) -> list[dict]:
    """按使用次数 / 最近使用排序（返回副本，不改动原列表顺序由调用方决定）。"""
    stats = stats or {}

    def metric(c: dict):
        if key == "name":
            return str(c.get("name") or "")
        entry = stats.get(str(c.get("code") or "").upper()) or {}
        return entry.get("count", 0) if key == "count" else str(entry.get("last") or "")

    return sorted(cheats, key=metric, reverse=desc)
