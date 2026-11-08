# -*- coding: utf-8 -*-
"""1.9-A：v3 配置迁移链 / 备份 / 更高版本保护 / v2 出口。"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from vcct.const import DEFAULT_GAME, STORE_VERSION  # noqa: E402
from vcct.store import (  # noqa: E402
    StoreTooNew, _version_of, default_store, export_v2, last_load_warning,
    load_store, migrate_store, migrate_v1_to_v2, migrate_v2_to_v3,
    normalize_store, parse_bundle, save_store, to_v2,
)

V1 = {"app": "vc-cheat-typer", "version": 1,
      "settings": {"char_interval_ms": 80},
      "cheats": [{"id": "x1", "name": "满血", "code": "ASPIRINE", "hotkey": "F4"}]}

V2 = {"app": "vc-cheat-typer", "version": 2,
      "settings": {"char_interval_ms": 60, "target_keywords": "Vice City"},
      "active_profile": "速通",
      "profiles": [{"name": "速通", "cheats": [
          {"id": "a", "name": "A", "code": "AAA", "hotkey": "F2"},
          {"id": "b", "name": "B", "code": "BBB", "hotkey": "F3"}]}],
      "stats": {"AAA": {"count": 7, "last": "2026-11-01 10:00"}},
      "today": {"date": "2026-11-01", "count": 3},
      "games": [{"name": "VC", "match_type": "exe", "pattern": "gta-vc",
                 "profile": "速通", "enabled": True}]}


class TestVersionDetection(unittest.TestCase):
    def test_version_of(self):
        self.assertEqual(_version_of(V1), 1)
        self.assertEqual(_version_of(V2), 2)
        self.assertEqual(_version_of({"profiles": [{"name": "x"}]}), 2)
        self.assertEqual(_version_of({}), 2)   # 空配置按 v2 处理，走默认值

    def test_current_version_is_3(self):
        self.assertEqual(STORE_VERSION, 3)


class TestMigrationChain(unittest.TestCase):
    def test_v1_to_v2_pure(self):
        before = json.dumps(V1, sort_keys=True)
        out = migrate_v1_to_v2(V1)
        self.assertEqual(out["version"], 2)
        self.assertEqual(out["profiles"][0]["name"], "默认")
        self.assertEqual(json.dumps(V1, sort_keys=True), before, "入参不得被修改")

    def test_v2_to_v3_pure(self):
        before = json.dumps(V2, sort_keys=True)
        out = migrate_v2_to_v3(V2)
        self.assertEqual(out["version"], 3)
        self.assertEqual(out["profiles"][0]["game"], DEFAULT_GAME)
        self.assertEqual(out["packs"], [])
        self.assertEqual(json.dumps(V2, sort_keys=True), before)

    def test_migrate_store_chain(self):
        out = migrate_store(V1)
        self.assertEqual(out["version"], 3)
        self.assertEqual(out["profiles"][0]["cheats"][0]["code"], "ASPIRINE")

    def test_migrate_preserves_all_v2_data(self):
        out = migrate_store(V2)
        self.assertEqual(out["settings"]["char_interval_ms"], 60)
        self.assertEqual(out["active_profile"], "速通")
        self.assertEqual(out["stats"]["AAA"]["count"], 7)
        self.assertEqual(out["today"]["count"], 3)
        self.assertEqual(out["games"][0]["pattern"], "gta-vc")

    def test_migrate_store_is_pure(self):
        before = json.dumps(V2, sort_keys=True)
        migrate_store(V2)
        self.assertEqual(json.dumps(V2, sort_keys=True), before)

    def test_too_new_raises(self):
        with self.assertRaises(StoreTooNew) as ctx:
            migrate_store({"version": 99, "profiles": [{"name": "x"}]})
        self.assertEqual(ctx.exception.found, 99)

    def test_normalize_v1_keeps_custom_settings(self):
        out = normalize_store(V1)
        self.assertEqual(out["version"], STORE_VERSION)
        self.assertEqual(out["settings"]["char_interval_ms"], 80)
        self.assertEqual(out["profiles"][0]["cheats"][0]["code"], "ASPIRINE")
        self.assertEqual(out["packs"], [])
        self.assertEqual(out["ui"], {})

    def test_five_history_samples_no_loss(self):
        """5 份真实形态的历史配置：迁移零丢失。"""
        samples = [
            V1, V2,
            {"app": "vc-cheat-typer", "version": 1, "cheats": []},
            {"app": "vc-cheat-typer", "version": 2, "settings": {"debounce_ms": 500},
             "profiles": [{"name": "A", "cheats": [{"code": "ZZZ"}]},
                          {"name": "A", "cheats": [{"code": "YYY"}]}],
             "active_profile": "A"},
            {"version": 2, "profiles": [{"name": "默认", "cheats": [{"code": "XXX"}]}],
             "games": [{"name": "g", "match_type": "title", "pattern": "Vice",
                        "profile": "默认", "enabled": False}]},
        ]
        for raw in samples:
            with self.subTest(raw=raw.get("version")):
                out = normalize_store(raw)
                self.assertEqual(out["version"], 3)
                self.assertTrue(out["profiles"])
                self.assertEqual(len({p["name"] for p in out["profiles"]}), len(out["profiles"]))


class TestLoadAndBackup(unittest.TestCase):
    def test_migration_backup_created_once(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "cheats.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(V2, fh, ensure_ascii=False)
            loaded = load_store(path)
            self.assertEqual(loaded["version"], 3)
            bak = os.path.join(td, "cheats.v2.bak.json")
            self.assertTrue(os.path.exists(bak), "升版前必须留迁移前原件")
            with open(bak, "r", encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["version"], 2)
            # 第一次备份不能被后续覆盖
            with open(bak, "w", encoding="utf-8") as fh:
                fh.write("SENTINEL")
            load_store(path)
            with open(bak, "r", encoding="utf-8") as fh:
                self.assertEqual(fh.read(), "SENTINEL")

    def test_too_new_config_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "cheats.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"version": 99, "profiles": [{"name": "X", "cheats": []}]}, fh)
            store = load_store(path)
            self.assertEqual(store["version"], 3)
            self.assertIn("更新版本", last_load_warning())
            with open(path, "r", encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["version"], 99, "绝不能回写覆盖新版本配置")

    def test_v3_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "cheats.json")
            store = default_store()
            store["packs"] = [{"name": "P", "author": "me", "game": "VC 经典版",
                               "pack_version": 1, "sha256": "abc", "imported_at": "t"}]
            store["ui"] = {"geometry": "1120x700+10+10", "column_widths": {"name": 148}}
            store["profiles"][0]["game"] = "VC 决定版"
            save_store(store, path)
            back = load_store(path)
            self.assertEqual(back["packs"][0]["name"], "P")
            self.assertEqual(back["ui"]["geometry"], "1120x700+10+10")
            self.assertEqual(back["profiles"][0]["game"], "VC 决定版")

    def test_bundle_rejects_newer_version(self):
        raw = dict(V2, version=99)
        store, err = parse_bundle(raw)
        self.assertIsNone(store)
        self.assertIn("更新版本", err)

    def test_history_roundtrip_capped_at_50(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "cheats.json")
            store = default_store()
            store["history"] = [{"at": f"t{i}", "name": "n", "code": "AAA",
                                 "profile": "默认", "result": "ok", "elapsed": 0.12,
                                 "detail": "d"} for i in range(60)]
            save_store(store, path)
            back = load_store(path)
            self.assertEqual(len(back["history"]), 50)
            self.assertEqual(back["history"][0]["at"], "t0")
            self.assertEqual(back["history"][0]["result"], "ok")

    def test_history_dirty_records_dropped(self):
        out = normalize_store({"history": [None, "x", {"result": "ok",
                                                       "elapsed": "bad"}]})
        self.assertEqual(len(out["history"]), 1)
        self.assertEqual(out["history"][0]["elapsed"], 0.0)

    def test_dirty_records_do_not_consume_history_limit(self):
        raw = [None, {"result": "ok"}] * 40     # 40 脏 + 40 有效
        out = normalize_store({"history": raw})["history"]
        self.assertEqual(len(out), 40, "脏记录不应占用 50 条上限")
        self.assertTrue(all(h["result"] == "ok" for h in out))

    def test_history_is_v3_only(self):
        # v1/v2 老配置没有 history → 空列表，不影响其他字段
        out = normalize_store(V2)
        self.assertEqual(out["history"], [])
        self.assertEqual(out["version"], 3)


class TestV2Exit(unittest.TestCase):
    def test_to_v2_strips_v3_fields(self):
        store = default_store()
        store["packs"] = [{"name": "P"}]
        store["profiles"][0]["cheats"][0]["verified"] = False
        out = to_v2(store)
        self.assertEqual(out["version"], 2)
        self.assertNotIn("packs", out)
        self.assertNotIn("verified", out["profiles"][0]["cheats"][0])
        self.assertNotIn("history", out, "v2 出口不能带 v3 的发送历史")
        self.assertEqual(out["profiles"][0]["cheats"][0]["code"], "THUGSTOOLS")

    def test_export_v2_writes_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "cheats.v2.json")
            export_v2(default_store(), path)
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            self.assertEqual(raw["version"], 2)
            self.assertEqual(len(raw["profiles"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
