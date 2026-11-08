# -*- coding: utf-8 -*-
"""1.9：.vcpack 秘籍包——格式构造 / 校验 / diff / 合并。

**纯函数、零第三方依赖、与 store.py 解耦**（2.0 抽 vcct-core 时可直接带走）。

格式（单 JSON 文件）：

    {
      "format": "vcct-pack",
      "pack_version": 1,
      "name": "VC 经典版 · 社区补全",
      "author": "someone",
      "game": "VC 经典版",
      "min_app": "1.9.0",
      "exported_at": "2026-11-08 09:30:00",
      "cheats": [ {id/name/code/hotkey/group/note/interval_ms/verified/game} ],
      "sha256": "<规范化 JSON 的 sha256>"
    }

设计决策
--------
* `pack_version` 独立于程序版本：将来改结构不动程序版本号。
* 解析器对**未知字段宽容**（忽略而非报错），便于第三方手写包。
* `sha256` 是**完整性提示而非强制门禁**：不匹配只产生 warning，不阻断导入——
  否则"导出 → 手工改两条 → 再导入"的往返流程会把自己锁死。
* diff 预览分三类：新增 / 冲突（同 code 内容不同）/ 相同；仅导入勾选的条目。
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid

PACK_FORMAT = "vcct-pack"
PACK_VERSION = 1
PACK_CHEAT_KEYS = ("id", "name", "code", "hotkey", "group", "note",
                   "interval_ms", "verified")


def _version_tuple(text: str) -> tuple[int, ...]:
    parts = []
    for bit in str(text or "").split("."):
        try:
            parts.append(int(bit))
        except (TypeError, ValueError):
            parts.append(0)
    return tuple(parts) or (0,)


def _norm_pack_cheat(item) -> dict | None:
    """包内秘籍归一化（不依赖 store，避免模块耦合）。"""
    if not isinstance(item, dict):
        return None
    code = str(item.get("code") or "").strip().upper()
    if not code or not all(ch.isalnum() for ch in code):
        return None
    try:
        interval = int(item.get("interval_ms") or 0)
    except (TypeError, ValueError):
        interval = 0
    if not 0 <= interval <= 300:
        interval = 0
    return {
        "id": str(item.get("id") or ""),
        "name": str(item.get("name") or code),
        "code": code,
        "hotkey": str(item.get("hotkey") or "").strip(),
        "group": str(item.get("group") or "自定义"),
        "note": str(item.get("note") or ""),
        "interval_ms": interval,
        "verified": bool(item.get("verified", True)),
    }


def _canonical(pack: dict) -> bytes:
    """sha256 计算用的规范化字节（剔除 sha256 字段，键排序、无多余空白）。"""
    payload = {k: v for k, v in pack.items() if k != "sha256"}
    return json.dumps(payload, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def pack_signature(pack: dict) -> str:
    return hashlib.sha256(_canonical(pack)).hexdigest()


def make_pack(name: str, cheats: list[dict], author: str = "", game: str = "",
              min_app: str = "1.9.0") -> dict:
    """构造一个合法包（纯函数）；cheats 里的 id 保留但不参与去重。"""
    norm = [c for c in (_norm_pack_cheat(x) for x in cheats) if c]
    pack = {
        "format": PACK_FORMAT,
        "pack_version": PACK_VERSION,
        "name": str(name or "未命名秘籍包").strip(),
        "author": str(author or ""),
        "game": str(game or ""),
        "min_app": str(min_app or ""),
        "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cheats": norm,
    }
    pack["sha256"] = pack_signature(pack)
    return pack


def validate_pack(raw, app_ver: str = "1.9.0") -> tuple[dict | None, list[str], str]:
    """校验并返回 (归一化包, 警告列表, 错误说明)。

    错误说明非空 = 不可用；警告只是提示（如校验和不匹配 / min_app 更高）。
    """
    if not isinstance(raw, dict):
        return None, [], "文件顶层不是 JSON 对象。"
    if str(raw.get("format") or "") != PACK_FORMAT:
        return None, [], f"不是 .vcpack 格式（format={raw.get('format')!r}）。"
    try:
        pv = int(raw.get("pack_version"))
    except (TypeError, ValueError):
        return None, [], "缺少或非法的 pack_version。"
    if pv < 1 or pv > PACK_VERSION:
        return None, [], f"包版本 v{pv} 不受支持（本程序最高 v{PACK_VERSION}）。"
    raw_cheats = raw.get("cheats")
    if not isinstance(raw_cheats, list) or not raw_cheats:
        return None, [], "包里没有任何秘籍。"
    cheats = [c for c in (_norm_pack_cheat(x) for x in raw_cheats) if c]
    if not cheats:
        return None, [], "包里的秘籍都不合法（code 必须是字母数字）。"
    codes = [c["code"] for c in cheats]
    if len(codes) != len(set(codes)):
        return None, [], "包内存在重复秘籍代码，请修正后再导入。"

    warnings: list[str] = []
    if raw.get("sha256"):
        if str(raw["sha256"]) != pack_signature(raw):
            warnings.append("校验和不匹配：包可能被手工修改过（仍可导入，请核对内容）。")
    else:
        warnings.append("包未附校验和（手写包常见）。")
    min_app = str(raw.get("min_app") or "")
    if min_app and _version_tuple(min_app) > _version_tuple(app_ver):
        warnings.append(f"包要求程序版本 ≥ {min_app}，当前 {app_ver}，部分字段可能被忽略。")

    pack = {
        "format": PACK_FORMAT,
        "pack_version": pv,
        "name": str(raw.get("name") or "未命名秘籍包"),
        "author": str(raw.get("author") or ""),
        "game": str(raw.get("game") or ""),
        "min_app": min_app,
        "exported_at": str(raw.get("exported_at") or ""),
        "cheats": cheats,
        "sha256": str(raw.get("sha256") or ""),
    }
    return pack, warnings, ""


def diff_pack(pack: dict, cheats: list[dict]) -> list[dict]:
    """预览差异（纯函数）：每条标 new / conflict / same，供 UI 勾选。"""
    existing = {str(c.get("code") or "").upper(): c for c in cheats}
    out = []
    for inc in pack.get("cheats") or []:
        old = existing.get(inc["code"])
        if old is None:
            status = "new"
        elif any((old.get(k) or "") != (inc.get(k) or "")
                 for k in ("name", "hotkey", "group", "note", "interval_ms")):
            status = "conflict"
        else:
            status = "same"
        out.append({"code": inc["code"], "name": inc["name"], "status": status,
                    "incoming": inc, "existing": old})
    return out


def merge_pack(cheats: list[dict], pack: dict, selected_codes: list[str],
               overwrite: bool = True) -> tuple[list[dict], dict]:
    """把勾选条目并入秘籍表（返回**新列表**，不改入参）。

    冲突项：overwrite=True 时保留原 id 就地替换；False 时跳过。
    new 项分配新 id，并标注 source_pack / game / verified。
    """
    chosen = set(selected_codes or [])
    result = [dict(c) for c in cheats]
    counts = {"added": 0, "updated": 0, "skipped": 0}
    for inc in pack.get("cheats") or []:
        if inc["code"] not in chosen:
            continue
        idx = next((i for i, c in enumerate(result)
                    if str(c.get("code") or "").upper() == inc["code"]), None)
        if idx is None:
            item = {k: inc.get(k) for k in PACK_CHEAT_KEYS}
            item["id"] = uuid.uuid4().hex[:8]
            item["game"] = str(pack.get("game") or "")
            item["source_pack"] = str(pack.get("name") or "")
            result.append(item)
            counts["added"] += 1
        elif overwrite:
            old_id = result[idx].get("id")
            item = {k: inc.get(k) for k in PACK_CHEAT_KEYS}
            item["id"] = old_id or uuid.uuid4().hex[:8]
            item["game"] = str(pack.get("game") or "")
            item["source_pack"] = str(pack.get("name") or "")
            result[idx] = item
            counts["updated"] += 1
        else:
            counts["skipped"] += 1
    return result, counts


def pack_record(pack: dict) -> dict:
    """生成写入 store["packs"] 的安装记录。"""
    return {
        "name": str(pack.get("name") or ""),
        "author": str(pack.get("author") or ""),
        "game": str(pack.get("game") or ""),
        "pack_version": int(pack.get("pack_version") or 1),
        "sha256": str(pack.get("sha256") or ""),
        "imported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
