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
    STORE_VERSION,
    VK_BY_NAME,
    _norm_cheat,
    build_bindings,
    bump_stats,
    default_store,
    filter_cheats,
    format_combo,
    is_safe_binding,
    load_store,
    parse_combo,
    save_store,
)
import vc_cheat_typer as _module  # noqa: E402  （需要读模块级 LAST_LOAD_WARNING）


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
            self.assertTrue(_module.LAST_LOAD_WARNING, "应记录可展示的告警")
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
            self.assertEqual(_module.LAST_LOAD_WARNING, "")
            restored = load_store(bak)
            self.assertEqual(restored["version"], STORE_VERSION)


if __name__ == "__main__":
    unittest.main(verbosity=2)
