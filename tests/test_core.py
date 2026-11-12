# -*- coding: utf-8 -*-
"""核心纯函数回归测试。

运行方式（二选一）：
    python -m unittest discover -s tests -v      # 零依赖，标准库
    python -m pytest tests -v                    # 若安装了 pytest

只测不依赖 GUI/游戏窗口的纯逻辑：组合键解析、安全绑定、数据层 v2 迁移、统计。
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vc_cheat_typer import (  # noqa: E402
    DEFAULT_SETTINGS,
    PAUSE_ID,
    STORE_APP,
    STORE_VERSION,
    VK_BY_NAME,
    _norm_cheat,
    build_bindings,
    bump_stats,
    bundle_payload,
    candidate_combos,
    default_store,
    filter_cheats,
    format_combo,
    is_safe_binding,
    load_store,
    normalize_store,
    parse_bundle,
    parse_combo,
    pick_free_combo,
    save_store,
    sorted_cheats,
    touch_today,
)
import vc_cheat_typer as _module  # noqa: E402
import vcct.store as _store  # noqa: E402  （需要读模块级 LAST_LOAD_WARNING）


class TestCombo(unittest.TestCase):
    def test_parse_format_roundtrip(self):
        cases = [("F1", "F1"), ("Shift+F1", "Shift+F1"),
                 ("ctrl+shift+F12", "Ctrl+Shift+F12"), ("Alt+3", "Alt+3"),
                 ("Win+Space", "Win+空格")]
        for text, expect in cases:
            parsed = parse_combo(text)
            self.assertIsNotNone(parsed, text)
            self.assertEqual(format_combo(*parsed), expect, text)

    def test_parse_invalid(self):
        for bad in ("", "   ", "Hello", "Ctrl+", "Ctrl++"):
            self.assertIsNone(parse_combo(bad), repr(bad))

    def test_all_default_hotkeys_parse(self):
        store = default_store()
        for prof in store["profiles"]:
            for c in prof["cheats"]:
                if c["hotkey"]:
                    self.assertIsNotNone(parse_combo(c["hotkey"]), c)

    def test_safe_binding(self):
        self.assertTrue(is_safe_binding(0, VK_BY_NAME["f1"]))
        self.assertFalse(is_safe_binding(0, VK_BY_NAME["a"]))       # 裸字母会吞打字
        self.assertFalse(is_safe_binding(0, VK_BY_NAME["1"]))
        self.assertTrue(is_safe_binding(0x0002, VK_BY_NAME["a"]))   # Ctrl+A 安全


class TestStore(unittest.TestCase):
    def test_default_store_shape(self):
        store = default_store()
        self.assertEqual(store["version"], STORE_VERSION)
        self.assertEqual(len(store["profiles"]), 1)
        self.assertEqual(len(store["profiles"][0]["cheats"]), 28)

    def test_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "cheats.json")
            store = default_store()
            store["profiles"][0]["cheats"][0]["name"] = "改过名"
            store["stats"]["ASPIRINE"] = {"count": 3, "last": "2026-11-03 10:00"}
            save_store(store, path)
            loaded = load_store(path)
            self.assertEqual(loaded["version"], STORE_VERSION)
            self.assertEqual(loaded["profiles"][0]["cheats"][0]["name"], "改过名")
            self.assertEqual(loaded["stats"]["ASPIRINE"]["count"], 3)

    def test_v1_migration(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "v1.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({
                    "app": "vc-cheat-tool", "version": 1,
                    "settings": {"char_interval_ms": 80},
                    "cheats": [{"id": "x1", "name": "满血", "code": "aspirine",
                                "hotkey": "F4", "group": "生存", "note": ""}],
                }, fh, ensure_ascii=False)
            store = load_store(path)
            self.assertEqual(store["version"], STORE_VERSION)
            self.assertEqual(store["active_profile"], "默认")
            self.assertEqual(len(store["profiles"][0]["cheats"]), 1)
            self.assertEqual(store["profiles"][0]["cheats"][0]["code"], "ASPIRINE")  # 自动大写
            self.assertEqual(store["settings"]["char_interval_ms"], 80)             # 未知键丢弃、已知键保留

    def test_corrupt_file_falls_back(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "broken.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{ 不是 JSON")
            store = load_store(path)
            self.assertEqual(store["version"], STORE_VERSION)
            self.assertTrue(store["profiles"][0]["cheats"])

    def test_profile_name_dedup_and_active_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "dup.json")
            store = default_store()
            store["profiles"].append({"name": "默认", "cheats": []})
            store["active_profile"] = "不存在的方案"
            save_store(store, path)
            loaded = load_store(path)
            names = [p["name"] for p in loaded["profiles"]]
            self.assertEqual(len(names), len(set(names)))
            self.assertIn(loaded["active_profile"], names)

    def test_norm_cheat_drops_empty_code(self):
        self.assertIsNone(_norm_cheat({"name": "x", "code": "  "}))
        self.assertIsNone(_norm_cheat("not a dict"))
        c = _norm_cheat({"code": " panzer "})
        self.assertEqual(c["code"], "PANZER")
        self.assertEqual(c["group"], "自定义")


class TestStats(unittest.TestCase):
    def test_bump_case_insensitive(self):
        stats = {}
        self.assertEqual(bump_stats(stats, "aspirine"), 1)
        self.assertEqual(bump_stats(stats, "ASPIRINE"), 2)
        self.assertEqual(stats["ASPIRINE"]["count"], 2)
        self.assertTrue(stats["ASPIRINE"]["last"])

    def test_settings_keys_unknown_dropped(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "s.json")
            store = default_store()
            store["settings"] = dict(DEFAULT_SETTINGS)
            store["settings"]["hack_key"] = "x"  # 不应被带进 v2
            save_store(store, path)
            with open(path, encoding="utf-8") as fh:
                raw = json.load(fh)
            self.assertNotIn("hack_key", raw["settings"])


class TestFilter(unittest.TestCase):
    """1.6：搜索与分组叠加过滤"""

    def setUp(self):
        self.cheats = default_store()["profiles"][0]["cheats"]

    def test_group_filter(self):
        got = filter_cheats(self.cheats, "武器", "")
        self.assertEqual(len(got), 3)
        self.assertTrue(all(c["group"] == "武器" for c in got))

    def test_query_matches_code_and_name(self):
        self.assertEqual([c["code"] for c in filter_cheats(self.cheats, "全部", "aspirine")],
                         ["ASPIRINE"])
        self.assertEqual([c["code"] for c in filter_cheats(self.cheats, "全部", "满血")],
                         ["ASPIRINE"])

    def test_query_case_insensitive_and_trimmed(self):
        self.assertEqual(len(filter_cheats(self.cheats, "全部", "  PANZER ")), 1)

    def test_group_and_query_stack(self):
        got = filter_cheats(self.cheats, "武器", "tools")
        self.assertEqual(len(got), 3)
        self.assertEqual(len(filter_cheats(self.cheats, "载具", "panzer")), 1)

    def test_empty_query_returns_group_copy(self):
        got = filter_cheats(self.cheats, "全部", "")
        self.assertEqual(len(got), len(self.cheats))
        self.assertIsNot(got, self.cheats)   # 返回副本，调用方改列表不影响源数据

    def test_no_match(self):
        self.assertEqual(filter_cheats(self.cheats, "全部", "不存在的字符串"), [])


class TestBindings(unittest.TestCase):
    """1.6：暂停键纳入热键表；暂停时只保留暂停键"""

    def setUp(self):
        self.cheats = default_store()["profiles"][0]["cheats"]

    def test_pause_only_when_paused(self):
        bindings, conflicts = build_bindings(self.cheats, "Ctrl+Alt+P", include_cheats=False)
        self.assertEqual(len(bindings), 1)
        self.assertEqual(bindings[0][3], PAUSE_ID)
        self.assertEqual(conflicts, {})

    def test_all_cheats_when_running(self):
        bindings, conflicts = build_bindings(self.cheats, "Ctrl+Alt+P", include_cheats=True)
        self.assertEqual(len(bindings), len(self.cheats) + 1)   # 28 条秘籍 + 暂停键
        self.assertEqual(conflicts, {})

    def test_duplicate_hotkey_detected(self):
        cheats = [dict(c) for c in self.cheats[:2]]
        cheats[0]["hotkey"] = cheats[1]["hotkey"] = "F5"
        bindings, conflicts = build_bindings(cheats, "", include_cheats=True)
        self.assertEqual(len(bindings), 1)
        self.assertIn(cheats[1]["id"], conflicts)

    def test_cheat_clashing_with_pause_is_conflict(self):
        cheats = [dict(c) for c in self.cheats[:1]]
        cheats[0]["hotkey"] = "Ctrl+Alt+P"
        bindings, conflicts = build_bindings(cheats, "Ctrl+Alt+P", include_cheats=True)
        self.assertEqual([b[3] for b in bindings], [PAUSE_ID])
        self.assertIn(cheats[0]["id"], conflicts)

    def test_unparsable_hotkey_reported(self):
        cheats = [dict(c) for c in self.cheats[:1]]
        cheats[0]["hotkey"] = "Hello"
        bindings, conflicts = build_bindings(cheats, "", include_cheats=True)
        self.assertEqual(bindings, [])
        self.assertIn(cheats[0]["id"], conflicts)


class TestResilience(unittest.TestCase):
    """1.6：配置损坏隔离 + 上一版备份"""

    def test_corrupt_file_quarantined_with_warning(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "cheats.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{ 坏掉的 JSON")
            store = load_store(path)
            self.assertTrue(store["profiles"][0]["cheats"])
            self.assertTrue(_store.last_load_warning(), "应记录可展示的告警")
            leftovers = [n for n in os.listdir(td) if n.startswith("cheats.corrupt-")]
            self.assertEqual(len(leftovers), 1, "损坏文件应改名留存而不是被覆盖")
            self.assertFalse(os.path.exists(path), "损坏文件应被移走，便于重新生成默认配置")

    def test_save_creates_previous_version_backup(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "cheats.json")
            store = default_store()
            save_store(store, path)
            self.assertFalse(os.path.exists(os.path.join(td, "cheats.bak.json")))
            store["profiles"][0]["cheats"][0]["name"] = "第二版"
            save_store(store, path)
            bak = os.path.join(td, "cheats.bak.json")
            self.assertTrue(os.path.exists(bak), "第二次保存前应留下上一版")
            with open(bak, encoding="utf-8") as fh:
                prev = json.load(fh)
            self.assertNotEqual(prev["profiles"][0]["cheats"][0]["name"], "第二版")

    def test_backup_can_be_loaded_again(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "cheats.json")
            save_store(default_store(), path)
            save_store(default_store(), path)
            bak = os.path.join(td, "cheats.bak.json")
            self.assertEqual(_store.last_load_warning(), "")
            restored = load_store(bak)
            self.assertEqual(restored["version"], STORE_VERSION)


class TestConflictFix(unittest.TestCase):
    """1.6 P1-F：冲突处置——按候选序列挑空闲键"""

    def setUp(self):
        self.cheats = default_store()["profiles"][0]["cheats"]

    def test_candidate_pool_is_safe_unique_and_avoids_f12(self):
        pool = candidate_combos()
        self.assertTrue(pool)
        self.assertEqual(pool[0], "F1")
        self.assertEqual(len(pool), len(set(pool)))
        self.assertNotIn("F12", pool)
        for combo in pool:
            parsed = parse_combo(combo)
            self.assertIsNotNone(parsed, combo)
            self.assertTrue(is_safe_binding(*parsed), combo)

    def test_pick_skips_keys_taken_by_other_cheats(self):
        cheats = [{"id": "a", "hotkey": "F1"}, {"id": "b", "hotkey": "F2"},
                  {"id": "c", "hotkey": ""}]
        self.assertEqual(pick_free_combo(cheats), "F3")

    def test_pick_skips_pause_key_and_known_bad_keys(self):
        cheats = [{"id": "a", "hotkey": "F1"}]
        self.assertEqual(pick_free_combo(cheats, "F2"), "F3")
        self.assertEqual(pick_free_combo(cheats, "F2", avoid=["F3"]), "F4")

    def test_pick_can_return_own_key_when_not_taken(self):
        cheats = [{"id": "a", "hotkey": "F1"}, {"id": "b", "hotkey": "Shift+F5"}]
        self.assertEqual(pick_free_combo(cheats, exclude_id="b"), "F2")

    def test_pick_returns_empty_when_pool_exhausted(self):
        cheats = [{"id": str(i), "hotkey": c} for i, c in enumerate(candidate_combos())]
        self.assertEqual(pick_free_combo(cheats), "")

    def test_default_cheats_have_free_keys_for_migration(self):
        # 默认 28 条占用了 F1–F11/Shift+F1…，仍应能再分配出空闲键
        self.assertTrue(pick_free_combo(self.cheats, "Ctrl+Alt+P"))


class TestBundle(unittest.TestCase):
    """1.6 P1-G：整包备份 / 恢复"""

    def _store(self):
        store = default_store()
        store["profiles"].append({"name": "速通", "cheats": [
            {"id": "z1", "name": "满血", "code": "ASPIRINE", "hotkey": "Ctrl+F1",
             "group": "生存", "note": "", "interval_ms": 100}]})
        store["active_profile"] = "速通"
        store["stats"] = {"ASPIRINE": {"count": 7, "last": "2026-11-04 20:00"}}
        store["today"] = {"date": "2026-11-04", "count": 3}
        store["settings"]["char_interval_ms"] = 70
        return store

    def test_roundtrip_keeps_profiles_settings_stats_and_speed(self):
        store = self._store()
        payload = bundle_payload(store)
        self.assertEqual(payload["kind"], "bundle")
        self.assertEqual(payload["app"], STORE_APP)
        back, err = parse_bundle(payload)
        self.assertEqual(err, "")
        self.assertIsNotNone(back)
        self.assertEqual([p["name"] for p in back["profiles"]], ["默认", "速通"])
        self.assertEqual(back["active_profile"], "速通")
        self.assertEqual(back["settings"]["char_interval_ms"], 70)
        self.assertEqual(back["stats"]["ASPIRINE"]["count"], 7)
        self.assertEqual(back["today"], {"date": "2026-11-04", "count": 3})
        self.assertEqual(back["profiles"][1]["cheats"][0]["interval_ms"], 100)

    def test_roundtrip_through_disk(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "bundle.json")
            store = self._store()
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(bundle_payload(store), fh, ensure_ascii=False)
            with open(path, encoding="utf-8") as fh:
                back, err = parse_bundle(json.load(fh))
            self.assertEqual(err, "")
            total = sum(len(p["cheats"]) for p in back["profiles"])
            self.assertEqual(total, 28 + 1)

    def test_rejects_foreign_app(self):
        store, err = parse_bundle({"app": "other-tool", "profiles": [{"name": "x", "cheats": []}]})
        self.assertIsNone(store)
        self.assertIn("不是", err)

    def test_rejects_single_profile_file(self):
        store, err = parse_bundle({"app": STORE_APP, "profile": {"name": "a", "cheats": []}})
        self.assertIsNone(store)
        self.assertIn("导入方案", err)

    def test_rejects_empty_or_malformed(self):
        for raw in (None, [], {}, {"profiles": []}, {"profiles": "x"}):
            store, err = parse_bundle(raw)
            self.assertIsNone(store, raw)
            self.assertTrue(err, raw)


class TestSpeedAndToday(unittest.TestCase):
    """1.6 P1-H 单条速度 / P1-J 今日计数"""

    def test_interval_normalized_and_clamped(self):
        self.assertEqual(_norm_cheat({"code": "X1"})["interval_ms"], 0)
        self.assertEqual(_norm_cheat({"code": "X1", "interval_ms": 100})["interval_ms"], 100)
        self.assertEqual(_norm_cheat({"code": "X1", "interval_ms": "120"})["interval_ms"], 120)
        self.assertEqual(_norm_cheat({"code": "X1", "interval_ms": 999})["interval_ms"], 0)   # 越界回落
        self.assertEqual(_norm_cheat({"code": "X1", "interval_ms": "abc"})["interval_ms"], 0)

    def test_touch_today_resets_across_days(self):
        first = touch_today({"date": "2026-11-04", "count": 2}, "2026-11-04")
        self.assertEqual(first["count"], 3)
        nxt = touch_today(first, "2026-11-05")
        self.assertEqual(nxt, {"date": "2026-11-05", "count": 1})
        self.assertEqual(touch_today(None, "2026-11-05", bump=False)["count"], 0)

    def test_today_persisted_and_loaded(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "cheats.json")
            store = default_store()
            store["today"] = {"date": "2026-11-04", "count": 5}
            save_store(store, path)
            self.assertEqual(load_store(path)["today"], {"date": "2026-11-04", "count": 5})

    def test_normalize_store_is_pure(self):
        raw = {"profiles": [{"name": "默认", "cheats": [{"code": "aspirine"}]}]}
        store = normalize_store(raw)
        self.assertEqual(store["profiles"][0]["cheats"][0]["code"], "ASPIRINE")
        self.assertEqual(raw["profiles"][0]["cheats"][0]["code"], "aspirine")  # 源数据不被改写


class TestSorting(unittest.TestCase):
    """1.6 P1-J：按次数 / 最近 / 名称排序"""

    def setUp(self):
        self.cheats = [{"id": "a", "code": "AAA", "name": "乙"},
                       {"id": "b", "code": "BBB", "name": "甲"},
                       {"id": "c", "code": "CCC", "name": "丙"}]
        self.stats = {"AAA": {"count": 1, "last": "2026-11-01 10:00"},
                      "BBB": {"count": 9, "last": "2026-11-04 21:00"}}

    def test_sort_by_count(self):
        self.assertEqual([c["code"] for c in sorted_cheats(self.cheats, "count", True, self.stats)],
                         ["BBB", "AAA", "CCC"])
        self.assertEqual([c["code"] for c in sorted_cheats(self.cheats, "count", False, self.stats)],
                         ["CCC", "AAA", "BBB"])

    def test_sort_by_last(self):
        self.assertEqual([c["code"] for c in sorted_cheats(self.cheats, "last", True, self.stats)],
                         ["BBB", "AAA", "CCC"])

    def test_sort_by_name(self):
        self.assertEqual([c["name"] for c in sorted_cheats(self.cheats, "name", False, self.stats)],
                         ["丙", "乙", "甲"])

    def test_sort_does_not_mutate_source(self):
        before = [c["code"] for c in self.cheats]
        sorted_cheats(self.cheats, "count", True, self.stats)
        self.assertEqual([c["code"] for c in self.cheats], before)


class TestSchema(unittest.TestCase):
    """P0：统一 schema 回归——策略字段不再被归一化丢弃，两条实现保持一致。"""

    def test_cheat_keeps_strategy_fields(self):
        item = {"code": "panzer", "strategy": {"kind": "burst", "interval_ms": 999},
                "strategy_ref": "快速"}
        norm = _norm_cheat(item)
        self.assertEqual(norm["code"], "PANZER")
        self.assertEqual(norm["strategy"]["kind"], "burst")
        self.assertEqual(norm["strategy"]["interval_ms"], 300)   # 策略值走夹取
        self.assertEqual(norm["strategy_ref"], "快速")

    def test_cheat_without_strategy_unchanged(self):
        norm = _norm_cheat({"code": "ASPIRINE"})
        self.assertNotIn("strategy", norm)
        self.assertNotIn("strategy_ref", norm)

    def test_strict_code_validation(self):
        from vcct.schema import is_valid_code, normalize_cheat
        self.assertTrue(is_valid_code("THUGSTOOLS"))
        self.assertFalse(is_valid_code("A"))
        self.assertFalse(is_valid_code("A-B"))
        self.assertIsNone(normalize_cheat({"code": "A"}, strict_code=True))
        # 宽松模式保留旧配置，只做去空白 + 大写
        self.assertEqual(normalize_cheat({"code": "a b"}, strict_code=False)["code"], "AB")

    def test_strategy_matches_core(self):
        from vcct.core.strategy import normalize_strategy as core_norm
        from vcct.schema import normalize_strategy as schema_norm
        # 空输入：schema 用 None 表示"无覆盖"，core 返回 fixed 默认值——这是唯一有意的差异
        self.assertIsNone(schema_norm({}))
        self.assertIsNone(schema_norm(None))
        for raw in ({"kind": "adaptive", "interval_ms": 5, "hold_ms": 900, "retries": 9},
                    {"kind": "nope", "pre_delay_ms": -1},
                    {"kind": "burst"}):
            self.assertEqual(schema_norm(raw), core_norm(raw), raw)

    def test_profile_list_normalized_on_save(self):
        store = default_store()
        store["profiles"] = [{"name": "默认", "cheats": [{"code": "X1", "strategy": {"kind": "burst"}}]},
                             {"name": "", "cheats": []}]
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "cheats.json")
            save_store(store, path)
            loaded = load_store(path)
        names = [p["name"] for p in loaded["profiles"]]
        self.assertEqual(len(names), len(set(names)), names)       # 方案名去重
        self.assertTrue(all(n for n in names), names)              # 空名不落盘


if __name__ == "__main__":
    unittest.main(verbosity=2)
