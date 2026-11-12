# -*- coding: utf-8 -*-
"""2.0：命令行入口（零第三方依赖）。

    python -m vcct.cli version
    python -m vcct.cli list [--profile NAME]
    python -m vcct.cli targets
    python -m vcct.cli strategies
    python -m vcct.cli pack info <file.vcpack>
    python -m vcct.cli send <CODE> [--target NAME] [--execute] [--interval MS]
    python -m vcct.cli export-v2 [path]

安全约定：`send` 默认只**预演**参数，不碰键盘；必须显式 `--execute` 才会真正注入，
避免脚本误触发时把代码打进当前正在编辑的窗口。带 `--target` 时会校验前台窗口。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from .const import APP_NAME, APP_VER, STORE_VERSION
from .core.strategy import describe_plan, normalize_strategy, plan_send, resolve_strategy
from .core.targets import evaluate_targets
from .packs import auto_avoid_hotkeys, diff_pack, merge_pack, pack_record, validate_pack
from .store import export_v2, load_store


def _store():
    return load_store()


def _profiles(store):
    return store.get("profiles") or []


def _cheats(store, profile: str | None = None):
    name = profile or store.get("active_profile", "默认")
    prof = next((p for p in _profiles(store) if p.get("name") == name), None)
    if prof is None:
        names = "、".join(p.get("name", "") for p in _profiles(store))
        raise ValueError(f"方案「{name}」不存在。可用方案：{names}")
    return prof.get("cheats") or []


def cmd_version(_args) -> int:
    print(f"{APP_NAME} v{APP_VER}  (config v{STORE_VERSION})")
    return 0


def cmd_list(args) -> int:
    store = _store()
    cheats = _cheats(store, args.profile)
    print(f"方案「{args.profile or store.get('active_profile')}」共 {len(cheats)} 条：")
    for c in cheats:
        print(f"  {c.get('hotkey') or '—':<18} {c.get('code', ''):<30} {c.get('name', '')}")
    return 0


def cmd_targets(_args) -> int:
    targets = _store().get("targets") or []
    if not targets:
        print("未配置 targets（可在 cheats.json 里添加；旧 games 规则仍照常生效）。")
        return 0
    print(f"共 {len(targets)} 条目标规则：")
    for t in targets:
        flag = "启用" if t.get("enabled") else "停用"
        print(
            f"  [{flag}] {t.get('name')}  {t.get('match_type')}:{t.get('pattern')}"
            f"  → 方案={t.get('profile_ref') or '沿用'} 策略={t.get('strategy_ref') or '沿用'}"
            f"  IME={t.get('ime_policy')} 前台={t.get('require_foreground')}"
        )
    return 0


def cmd_strategies(_args) -> int:
    named = _store().get("strategies") or {}
    print(f"具名策略 {len(named)} 个（默认 fixed，与 1.9.1 参数一致）：")
    for name, spec in named.items():
        print(f"  {name}: {json.dumps(spec, ensure_ascii=False)}")
    return 0


def cmd_pack_info(args) -> int:
    with open(args.file, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    pack, warns, err = validate_pack(raw, APP_VER)
    if err:
        print(f"✖ {err}")
        return 1
    print(f"包：{pack['name']}  v{pack['pack_version']}  作者={pack['author'] or '—'}  游戏={pack['game'] or '—'}")
    print(f"条目 {len(pack['cheats'])} 条；导出时间 {pack['exported_at'] or '—'}")
    print("前 10 条：" if len(pack["cheats"]) > 10 else "全部条目：")
    for c in pack["cheats"][:10]:
        print(f"  {c['code']:<30} {c['name']}  hotkey={c['hotkey'] or '—'}")
    for w in warns:
        print(f"⚠ {w}")
    return 0


def cmd_pack_validate(args) -> int:
    """严格校验：格式 / 条目 / 校验和。exit 0 = 干净；1 = 不可用；2 = 有警告但仍可用。"""
    with open(args.file, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    pack, warns, err = validate_pack(raw, APP_VER)
    if args.json:
        out = {"ok": err == "", "warnings": warns, "error": err or None}
        if pack is not None:
            out["pack"] = {
                "name": pack["name"],
                "pack_version": pack["pack_version"],
                "cheat_count": len(pack["cheats"]),
                "sha256": pack["sha256"],
            }
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if not err else 1
    if err:
        print(f"✖ {err}")
        return 1
    if warns:
        for w in warns:
            print(f"⚠ {w}")
        return 2
    print(f"✔ 包校验通过：{pack['name']}  v{pack['pack_version']}  {len(pack['cheats'])} 条")
    return 0


def cmd_pack_diff(args) -> int:
    """对比包与本地 active profile，统计 new / conflict / same。"""
    with open(args.file, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    pack, warns, err = validate_pack(raw, APP_VER)
    if err:
        print(f"✖ {err}")
        return 1
    store = _store()
    cheats = _cheats(store, args.profile)
    rows = diff_pack(pack, cheats)
    counts = {"new": 0, "conflict": 0, "same": 0}
    for r in rows:
        counts[r["status"]] += 1
    print(f"包 {pack['name']} vs 方案「{args.profile or store.get('active_profile')}」：")
    print(f"  新增 {counts['new']}  冲突 {counts['conflict']}  相同 {counts['same']}  共 {len(rows)}")
    if counts["new"]:
        print("新增：")
        for r in rows:
            if r["status"] == "new":
                print(f"  + {r['code']:<30} {r['name']}")
    if counts["conflict"]:
        print("冲突：")
        for r in rows:
            if r["status"] == "conflict":
                print(f"  ≠ {r['code']:<30} 本地={r['existing'].get('name', '')}  包={r['incoming'].get('name', '')}")
    return 0


def cmd_pack_import(args) -> int:
    """把包合并进 active profile。默认覆盖冲突；加 --dry-run 只打印不落盘。"""
    with open(args.file, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    pack, warns, err = validate_pack(raw, APP_VER)
    if err:
        print(f"✖ {err}")
        return 1
    store = _store()
    cheats = _cheats(store, args.profile)
    rows = diff_pack(pack, cheats)

    overwrite = not args.no_overwrite
    if overwrite and args.avoid_hotkeys:
        pack, changed = auto_avoid_hotkeys(pack, cheats)
        for c in changed:
            print(f"  自动改键：{c['code']} {c['old']} → {c['new'] or '(空)'}")

    selected = [r["code"] for r in rows]
    new_list, counts = merge_pack(cheats, pack, selected, overwrite=overwrite)

    if args.dry_run:
        print(f"（dry-run，未写盘）新增 {counts['added']}  更新 {counts['updated']}  跳过 {counts['skipped']}")
        return 0

    name = args.profile or store.get("active_profile", "默认")
    for p in store["profiles"]:
        if p.get("name") == name:
            p["cheats"] = new_list
            break
    store["packs"] = store.get("packs") or []
    rec = pack_record(pack)
    existing = next((i for i, r in enumerate(store["packs"]) if r.get("name") == rec["name"]), None)
    if existing is None:
        store["packs"].append(rec)
    else:
        store["packs"][existing] = rec

    from .store import save_store

    save_store(store)
    print(f"✔ 已导入 {pack['name']}：新增 {counts['added']}  更新 {counts['updated']}  跳过 {counts['skipped']}")
    return 0


def cmd_send(args) -> int:
    store = _store()
    code = args.code.strip().upper()
    if not code or not code.isalnum():
        print("✖ 代码只能包含字母/数字。")
        return 1
    target = None
    if args.target:
        targets = store.get("targets") or []
        target = next((t for t in targets if t.get("name") == args.target), None)
        if target is None:
            print(f"✖ 目标「{args.target}」不存在（用 `vcct.cli targets` 查看）。")
            return 1

    cheat = next((c for c in _cheats(store) if c.get("code") == code), None)
    strategy = resolve_strategy(store.get("strategies"), cheat or {})
    base_interval = args.interval or int(store["settings"].get("char_interval_ms", 45))
    base_pre = int(store["settings"].get("pre_delay_ms", 180))
    if args.strategy:
        strategy = normalize_strategy(dict(strategy, kind=args.strategy))
    plan = describe_plan(strategy, code, base_interval, base_pre)
    print("发送计划：" + json.dumps(plan, ensure_ascii=False))

    if target:
        from .winapi import foreground_info

        title, exe = foreground_info()
        hit = evaluate_targets([target], title, exe)
        if not hit:
            print(f"✖ 前台窗口不匹配目标规则（当前 {title!r} / {exe}）。")
            return 1
        print(f"✔ 前台匹配：{title!r} / {exe}")

    if not args.execute:
        print("（预演模式，未发送任何按键。确认无误后加 --execute 真正注入。）")
        return 0

    from .winapi import ImeGuard, release_modifiers, send_key, user32, vk_for_char
    from .sender import type_text

    hwnd = user32.GetForegroundWindow() or 0
    sp = plan_send(strategy, code, base_interval, base_pre, attempt=0)
    release_modifiers()
    with ImeGuard(hwnd, True):
        sent = type_text(sp, None, send_key=send_key, sleep=time.sleep, lookup_vk=vk_for_char)
    print(f"✔ 已发送 {sent}/{len(code)} 字符")
    return 0


def cmd_export_v2(args) -> int:
    path = args.path or os.path.join(os.path.dirname(sys.argv[0]), "cheats.v2.json")
    export_v2(_store(), path)
    print(f"已导出 v2 兼容配置：{path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vcct", description=f"{APP_NAME} CLI")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("version", help="显示版本").set_defaults(func=cmd_version)
    q = sub.add_parser("list", help="列出秘籍")
    q.add_argument("--profile")
    q.set_defaults(func=cmd_list)
    sub.add_parser("targets", help="列出目标规则").set_defaults(func=cmd_targets)
    sub.add_parser("strategies", help="列出具名发送策略").set_defaults(func=cmd_strategies)
    pk = sub.add_parser("pack", help="秘籍包")
    pk_sub = pk.add_subparsers(dest="pack_command", required=True)
    inf = pk_sub.add_parser("info", help="查看包信息")
    inf.add_argument("file")
    inf.set_defaults(func=cmd_pack_info)
    val = pk_sub.add_parser("validate", help="严格校验包（exit 0=干净 / 1=不可用 / 2=有警告）")
    val.add_argument("file")
    val.add_argument("--json", action="store_true", help="机器可读 JSON 输出")
    val.set_defaults(func=cmd_pack_validate)
    dif = pk_sub.add_parser("diff", help="对比包与本地方案，统计 new/conflict/same")
    dif.add_argument("file")
    dif.add_argument("--profile")
    dif.set_defaults(func=cmd_pack_diff)
    imp = pk_sub.add_parser("import", help="真正导入包进本地方案（默认覆盖冲突）")
    imp.add_argument("file")
    imp.add_argument("--profile")
    imp.add_argument("--no-overwrite", action="store_true", help="不覆盖冲突，只导入新增")
    imp.add_argument("--avoid-hotkeys", action="store_true", help="自动改键避免冲突（覆盖模式下）")
    imp.add_argument("--dry-run", action="store_true", help="只打印不落盘")
    imp.set_defaults(func=cmd_pack_import)
    s = sub.add_parser("send", help="发送一条代码（默认预演）")
    s.add_argument("code")
    s.add_argument("--target", help="目标规则名（校验前台）")
    s.add_argument("--strategy", choices=("fixed", "adaptive", "burst"))
    s.add_argument("--interval", type=int)
    s.add_argument("--execute", action="store_true", help="真正注入按键（默认只预演）")
    s.set_defaults(func=cmd_send)
    e = sub.add_parser("export-v2", help="导出 v2 兼容配置")
    e.add_argument("path", nargs="?")
    e.set_defaults(func=cmd_export_v2)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except Exception as exc:
        print(f"✖ {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
