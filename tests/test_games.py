# -*- coding: utf-8 -*-
"""1.8 数据层测试：games 规则表归一化/匹配/持久化往返 + 托盘模块结构约束。"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from vcct.store import (  # noqa: E402
    _norm_games, default_store, evaluate_game_rules, load_store, match_game_rule,
    normalize_store, save_store,
)
from vcct.const import DEFAULT_SETTINGS  # noqa: E402


class TestGamesRules(unittest.TestCase):
    def test_norm_games_drops_bad_entries(self):
        games = _norm_games([
            {"name": "VC", "match_type": "exe", "pattern": "gta-vc",
             "profile": "默认", "enabled": True},
            {"pattern": ""},                      # 无 pattern → 丢弃
            {"pattern": "x", "match_type": "bad"},  # 非法类型 → 归 exe
            {"pattern": "y", "enabled": 0},       # enabled=0 → False
            "not-a-dict",
            None,
        ])
        self.assertEqual(len(games), 3)
        self.assertEqual(games[0]["match_type"], "exe")
        self.assertEqual(games[1]["match_type"], "exe")
        self.assertEqual(games[1]["enabled"], True)
        self.assertEqual(games[2]["enabled"], False)

    def test_match_rules(self):
        rule_exe = {"name": "r", "match_type": "exe", "pattern": "GTA-VC",
                    "profile": "p", "enabled": True}
        self.assertTrue(match_game_rule(rule_exe, "anything", "gta-vc.exe"))
        self.assertFalse(match_game_rule(rule_exe, "gta-vc", "notepad.exe"))
        rule_title = {"name": "t", "match_type": "title", "pattern": "vice city",
                      "profile": "p", "enabled": True}
        self.assertTrue(match_game_rule(rule_title, "GTA: Vice City", "explorer.exe"))
        self.assertFalse(match_game_rule(rule_title, "记事本", "notepad.exe"))
        # 未启用不匹配
        rule_off = dict(rule_exe, enabled=False)
        self.assertFalse(match_game_rule(rule_off, "x", "gta-vc.exe"))

    def test_evaluate_first_match_wins(self):
        games = [
            {"name": "a", "match_type": "exe", "pattern": "notepad", "profile": "P1", "enabled": True},
            {"name": "b", "match_type": "exe", "pattern": "note", "profile": "P2", "enabled": True},
        ]
        hit = evaluate_game_rules(games, "", "notepad.exe")
        self.assertEqual(hit["profile"], "P1")
        self.assertIsNone(evaluate_game_rules(games, "", "chrome.exe"))
        self.assertIsNone(evaluate_game_rules([], "", "notepad.exe"))
        self.assertIsNone(evaluate_game_rules(None, "", "notepad.exe"))

    def test_normalize_store_keeps_games(self):
        raw = {"games": [{"name": "VC", "match_type": "exe", "pattern": "gta-vc",
                          "profile": "默认", "enabled": True}]}
        store = normalize_store(raw)
        self.assertEqual(len(store["games"]), 1)
        self.assertEqual(store["games"][0]["pattern"], "gta-vc")

    def test_default_store_has_empty_games(self):
        self.assertEqual(default_store()["games"], [])

    def test_new_settings_keys_present(self):
        for key in ("close_to_tray", "auto_switch", "onboarded"):
            self.assertIn(key, DEFAULT_SETTINGS)

    def test_save_load_roundtrip_with_games(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "cheats.json")
            store = default_store()
            store["games"] = [{"name": "VC", "match_type": "exe", "pattern": "gta-vc",
                               "profile": "默认", "enabled": True}]
            store["settings"]["close_to_tray"] = False
            store["settings"]["onboarded"] = True
            save_store(store, path)
            with open(path, "r", encoding="utf-8") as fh:
                on_disk = json.load(fh)
            self.assertEqual(len(on_disk.get("games") or []), 1,
                             "games 必须落盘，否则自动切换规则重启即丢")
            back = load_store(path)
            self.assertEqual(back["games"][0]["pattern"], "gta-vc")
            self.assertFalse(back["settings"]["close_to_tray"])
            self.assertTrue(back["settings"]["onboarded"])

    def test_old_config_without_games_still_loads(self):
        """1.7 的旧配置（无 games 字段）载入后 games 为空 = 不自动切，旧行为不变。"""
        raw = {"app": "vc-cheat-typer", "version": 2,
               "settings": {"char_interval_ms": 60},
               "active_profile": "默认",
               "profiles": [{"name": "默认", "cheats": []}], "stats": {},
               "today": {"date": "", "count": 0}}
        store = normalize_store(raw)
        self.assertEqual(store["games"], [])
        self.assertEqual(store["settings"]["char_interval_ms"], 60)


class TestTrayModuleStructure(unittest.TestCase):
    def test_tray_no_tkinter(self):
        """托盘线程绝不许碰 tkinter——用 AST 验证 import 图。"""
        import ast
        path = os.path.join(ROOT, "vcct", "tray.py")
        with open(path, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertFalse(alias.name.startswith("tkinter"),
                                     "tray.py 禁止 import tkinter")
            elif isinstance(node, ast.ImportFrom):
                self.assertNotEqual((node.module or "").split(".")[0], "tkinter",
                                    "tray.py 禁止 from tkinter import …")

    def test_tray_importable_off_windows(self):
        """非 Windows 上 import 不炸、available=False（供 CI/跨平台检查）。"""
        import importlib
        if os.name == "nt":
            self.skipTest("Windows 上必真初始化，跳过降级路径")
        mod = importlib.import_module("vcct.tray")
        tray = mod.TrayIcon(tooltip="t", emit=lambda a: None)
        self.assertFalse(tray.available)
        tray.close()  # 幂等

    def test_tray_failed_flag_exists_before_thread_runs(self):
        """1.9.1 回归：主线程轮询会立刻读 _failed，必须先在 __init__ 里初始化。"""
        import importlib
        mod = importlib.import_module("vcct.tray")
        tray = mod.TrayIcon(tooltip="t", emit=lambda a: None)
        self.assertIn("_failed", tray.__dict__)
        self.assertFalse(tray._failed)
        tray.close()  # 幂等


if __name__ == "__main__":
    unittest.main(verbosity=2)
