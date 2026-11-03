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

from vc_cheat_tool import (  # noqa: E402
    DEFAULT_SETTINGS,
    STORE_VERSION,
    VK_BY_NAME,
    _norm_cheat,
    bump_stats,
    default_store,
    format_combo,
    is_safe_binding,
    load_store,
    parse_combo,
    save_store,
)


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
