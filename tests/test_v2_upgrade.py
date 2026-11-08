# -*- coding: utf-8 -*-
"""2.0-H：从 v1.6 / v1.8 / v1.9 三条升级路径零丢失回归。

每条路径都走真实的 `load_store()`（含备份 / 迁移链 / 归一化），
再检查关键字段、v2 出口、整包往返。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from vcct.const import STORE_VERSION  # noqa: E402
from vcct.store import (  # noqa: E402
    bundle_payload, load_store, normalize_store, parse_bundle, save_store, to_v2,
)

V16 = {
    "app": "vc-cheat-typer", "version": 2,
    "settings": {"char_interval_ms": 45, "target_keywords": "Vice City",
                 "pause_hotkey": "Ctrl+Alt+P"},
    "active_profile": "默认",
    "profiles": [{"name": "默认", "cheats": [
        {"id": "a1", "name": "满血", "code": "ASPIRINE", "hotkey": "F4",
         "group": "生存", "note": "x", "interval_ms": 0},
        {"id": "a2", "name": "坦克", "code": "PANZER", "hotkey": "F8",
         "group": "载具", "note": "", "interval_ms": 0}]}],
    "stats": {"ASPIRINE": {"count": 12, "last": "2026-11-01 10:00"}},
    "today": {"date": "2026-11-01", "count": 4},
}

V18 = dict(V16, games=[{"name": "VC", "match_type": "exe", "pattern": "gta-vc",
                        "profile": "默认", "enabled": True}],
           settings=dict(V16["settings"], close_to_tray=True, auto_switch=True,
                         onboarded=True))

V19 = dict(V18,
           profiles=[{"name": "默认", "game": "VC 经典版", "cheats": V16["profiles"][0]["cheats"]}],
           settings=dict(V18["settings"], debounce_ms=250),
           packs=[{"name": "社区包", "author": "me", "game": "VC 经典版",
                   "pack_version": 1, "sha256": "abc", "imported_at": "2026-11-08"}],
           ui={"geometry": "1120x700+10+10", "column_widths": {"name": 148}},
           history=[{"at": "t", "name": "满血", "code": "ASPIRINE", "profile": "默认",
                     "result": "ok", "elapsed": 0.5, "detail": "ok"}],
           version=3)


class TestUpgradePaths(unittest.TestCase):
    def _upgrade(self, raw):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "cheats.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(raw, fh, ensure_ascii=False)
            store = load_store(path)
            self.assertEqual(store["version"], STORE_VERSION)
            self.assertEqual(len(store["profiles"]), 1)
            self.assertEqual(len(store["profiles"][0]["cheats"]), 2)
            self.assertEqual(store["profiles"][0]["cheats"][0]["code"], "ASPIRINE")
            self.assertEqual(store["settings"]["char_interval_ms"], 45)
            self.assertEqual(store["stats"]["ASPIRINE"]["count"], 12)
            self.assertEqual(store["today"]["count"], 4)
            # v2 出口始终可写、可被旧程序读取
            out = to_v2(store)
            self.assertEqual(out["version"], 2)
            self.assertNotIn("targets", out)
            self.assertNotIn("history", out)
            # 整包往返不丢方案
            bundle, err = parse_bundle(bundle_payload(store))
            self.assertEqual(err, "")
            self.assertEqual(len(bundle["profiles"][0]["cheats"]), 2)
            # 升版前的原件备份存在
            self.assertTrue(os.path.exists(os.path.join(td, f"cheats.v{raw['version']}.bak.json"))
                            if raw["version"] < STORE_VERSION else True)
            save_store(store, path)
            with open(path, "r", encoding="utf-8") as fh:
                self.assertEqual(json.load(fh)["version"], STORE_VERSION)
            return store

    def test_from_1_6(self):
        store = self._upgrade(V16)
        self.assertEqual(store["games"], [])
        self.assertEqual(store["packs"], [])
        self.assertEqual(store["targets"], [])
        self.assertEqual(store["profiles"][0]["game"], "VC 经典版")

    def test_from_1_8(self):
        store = self._upgrade(V18)
        self.assertEqual(store["games"][0]["pattern"], "gta-vc")
        self.assertTrue(store["settings"]["close_to_tray"])
        self.assertTrue(store["settings"]["onboarded"])

    def test_from_1_9(self):
        store = self._upgrade(V19)
        self.assertEqual(store["packs"][0]["name"], "社区包")
        self.assertEqual(store["ui"]["geometry"], "1120x700+10+10")
        self.assertEqual(len(store["history"]), 1)
        self.assertEqual(store["profiles"][0]["game"], "VC 经典版")

    def test_v1_legacy_single_list(self):
        raw = {"app": "vc-cheat-typer", "version": 1,
               "settings": {"char_interval_ms": 80},
               "cheats": [{"id": "x", "name": "满血", "code": "ASPIRINE", "hotkey": "F4"}]}
        out = normalize_store(raw)
        self.assertEqual(out["version"], 3)
        self.assertEqual(out["profiles"][0]["cheats"][0]["code"], "ASPIRINE")
        self.assertEqual(out["settings"]["char_interval_ms"], 80)

    def test_newer_config_not_downgraded(self):
        import vcct.store as store_mod
        from vcct.store import StoreTooNew, migrate_store, last_load_warning
        with self.assertRaises(StoreTooNew):
            migrate_store({"version": 99, "profiles": []})
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "cheats.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"version": 99, "profiles": [{"name": "X", "cheats": []}]}, fh)
            original = store_mod.data_path
            store_mod.data_path = lambda: path
            try:
                load_store()
                self.assertIn("更新版本", last_load_warning())
                save_store({"version": 3, "profiles": [], "settings": {}}, None)
                with open(path, "r", encoding="utf-8") as fh:
                    self.assertEqual(json.load(fh)["version"], 99,
                                     "更高版本配置必须禁止回写")
            finally:
                store_mod.data_path = original
                store_mod._FORBID_DEFAULT_SAVE = False


if __name__ == "__main__":
    unittest.main(verbosity=2)
