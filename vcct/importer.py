# -*- coding: utf-8 -*-
"""1.9-E：文本 / CSV 粘贴导入（纯函数，逐行报错，可单测）。

支持的行格式（逗号或 Tab 分隔）：

    代码                                      → 名称 = 代码
    名称,代码                                  → 例如 满血,ASPIRINE
    名称,代码,热键                             → 例如 满血,ASPIRINE,F4
    名称,代码,热键,备注                        → 备注里不再出现分隔符
    代码,名称                                  → 兼容写法：首列纯代码时自动交换

空行与 `#` 开头的注释行跳过。任何不合法行都带**行号 + 原文 + 原因**返回，
不影响其他行。解析结果只是候选，UI 预览确认后才真正写入方案。
"""

from __future__ import annotations

import re
import uuid

from .hotkeys import is_safe_binding, parse_combo
from .schema import CODE_RE, clean_code


def _split(line: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"[,，\t]", line)]
    return [p for p in parts if p != ""]


def parse_pasted(text: str) -> tuple[list[dict], list[dict]]:
    """返回 (候选条目, 错误列表)。不写盘、不改入参。

    错误项形如 {"line": 3, "raw": "...", "reason": "..."}。
    """
    items: list[dict] = []
    errors: list[dict] = []
    seen: set[str] = set()
    for lineno, raw in enumerate(str(text or "").splitlines(), 1):
        line = raw.strip().lstrip("\ufeff")
        if not line or line.startswith("#"):
            continue
        parts = _split(line)
        if not parts:
            continue
        note = ""
        if len(parts) >= 4:
            name, code, hotkey, note = parts[0], parts[1], parts[2], ",".join(parts[3:])
        elif len(parts) == 3:
            name, code, hotkey = parts
        elif len(parts) == 2:
            first, second = parts
            # 兼容 "代码,名称"：首列是纯代码、第二列不是 → 交换
            if CODE_RE.fullmatch(first.upper()) and not CODE_RE.fullmatch(second.upper()):
                code, name = first, second
            else:
                name, code = first, second
            hotkey = ""
        else:
            code = parts[0]
            name = code
            hotkey = ""

        code = clean_code(code)
        if not CODE_RE.fullmatch(code):
            errors.append({"line": lineno, "raw": raw, "reason": "秘籍代码只能是字母/数字（2~40 位），如 ASPIRINE"})
            continue
        if hotkey:
            parsed = parse_combo(hotkey)
            if not parsed or not is_safe_binding(*parsed):
                errors.append({"line": lineno, "raw": raw, "reason": f"热键 {hotkey!r} 非法或不安全（单字母键需带 Ctrl/Alt/Shift）"})
                continue
            from .hotkeys import format_combo

            hotkey = format_combo(*parsed)
        if code in seen:
            errors.append({"line": lineno, "raw": raw, "reason": f"本批中代码 {code} 重复"})
            continue
        seen.add(code)
        items.append(
            {
                "id": uuid.uuid4().hex[:8],
                "name": name or code,
                "code": code,
                "hotkey": hotkey,
                "group": "导入",
                "note": note,
                "interval_ms": 0,
                "verified": False,
                "game": "",
                "source_pack": "",
            }
        )
    return items, errors
