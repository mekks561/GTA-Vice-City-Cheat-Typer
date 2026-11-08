# -*- coding: utf-8 -*-
"""1.9-B：.vcpack 格式 / 校验 / diff / 合并往返。"""
from __future__ import annotations

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from vcct.packs import (  # noqa: E402
    PACK_FORMAT, auto_avoid_hotkeys, compare_pack_record, diff_pack, make_pack,
    merge_pack, pack_record, pack_signature, validate_pack, _candidate_combos,
)

CHEATS = [
    {"id": "1", "name": "满血", "code": "ASPIRINE", "hotkey": "F4",
     "group": "生存", "note": "a", "interval_ms": 0, "verified": True},
    {"id": "2", "name": "坦克", "code": "PANZER", "hotkey": "F8",
     "group": "载具", "note": "b", "interval_ms": 0, "verified": True},
]


class TestPackFormat(unittest.TestCase):
    def test_make_pack_has_signature(self):
        pack = make_pack("测试包", CHEATS, author="me", game="VC 经典版")
        self.assertEqual(pack["format"], PACK_FORMAT)
        self.assertEqual(pack["sha256"], pack_signature(pack))
        self.assertEqual(len(pack["cheats"]), 2)

    def test_signature_ignores_sha_field(self):
        pack = make_pack("p", CHEATS)
        sig = pack["sha256"]
        self.assertEqual(pack_signature(dict(pack, sha256="x")), sig)

    def test_json_roundtrip(self):
        pack = make_pack("p", CHEATS)
        raw = json.loads(json.dumps(pack, ensure_ascii=False))
        got, warns, err = validate_pack(raw, "1.9.0")
        self.assertEqual(err, "")
        self.assertEqual(warns, [])
        self.assertEqual(got["cheats"][0]["code"], "ASPIRINE")

    def test_validate_rejects_wrong_format(self):
        _, _, err = validate_pack({"format": "something-else", "pack_version": 1,
                                   "cheats": [{"code": "X"}]})
        self.assertIn("不是 .vcpack", err)

    def test_validate_rejects_empty_or_bad_cheats(self):
        _, _, err = validate_pack({"format": PACK_FORMAT, "pack_version": 1, "cheats": []})
        self.assertIn("没有任何秘籍", err)
        _, _, err = validate_pack({"format": PACK_FORMAT, "pack_version": 1,
                                   "cheats": [{"code": "!!!"}]})
        self.assertIn("都不合法", err)

    def test_validate_rejects_duplicate_codes(self):
        _, _, err = validate_pack({"format": PACK_FORMAT, "pack_version": 1,
                                   "cheats": [{"code": "AAA"}, {"code": "AAA"}]})
        self.assertIn("重复秘籍代码", err)

    def test_validate_rejects_newer_pack_version(self):
        _, _, err = validate_pack({"format": PACK_FORMAT, "pack_version": 99,
                                   "cheats": [{"code": "AAA"}]})
        self.assertIn("不受支持", err)

    def test_unknown_fields_ignored(self):
        pack = make_pack("p", CHEATS)
        pack["future_field"] = "whatever"
        got, _, err = validate_pack(pack, "1.9.0")
        self.assertEqual(err, "")
        self.assertNotIn("future_field", got)

    def test_modified_pack_warns_but_importable(self):
        """导出→改→导入往返一致：sha 不符只是警告，不能阻断。"""
        pack = make_pack("p", CHEATS)
        pack["cheats"][0]["name"] = "改过的名称"
        got, warns, err = validate_pack(pack, "1.9.0")
        self.assertEqual(err, "")
        self.assertTrue(any("校验和不匹配" in w for w in warns))
        self.assertEqual(got["cheats"][0]["name"], "改过的名称")

    def test_min_app_warning(self):
        pack = make_pack("p", CHEATS, min_app="9.9.9")
        _, warns, err = validate_pack(pack, "1.9.0")
        self.assertEqual(err, "")
        self.assertTrue(any("要求程序版本" in w for w in warns))


class TestDiffMerge(unittest.TestCase):
    def test_diff_classifies(self):
        pack = make_pack("p", [
            {"name": "满血", "code": "ASPIRINE", "hotkey": "F4", "group": "生存", "note": "a"},
            {"name": "改过的坦克", "code": "PANZER", "hotkey": "F9", "group": "载具", "note": "b"},
            {"name": "新条目", "code": "NEWCODE", "hotkey": "", "group": "自定义", "note": ""},
        ])
        diff = diff_pack(pack, CHEATS)
        self.assertEqual([d["status"] for d in diff], ["same", "conflict", "new"])

    def test_merge_only_selected(self):
        pack = make_pack("p", [{"name": "新 A", "code": "NEWA"}, {"name": "新 B", "code": "NEWB"}],
                         game="GTA SA")
        merged, counts = merge_pack(CHEATS, pack, ["NEWA"])
        self.assertEqual(len(merged), 3)
        self.assertEqual(counts["added"], 1)
        self.assertEqual(merged[-1]["source_pack"], "p")
        self.assertEqual(merged[-1]["game"], "GTA SA")
        self.assertNotEqual(merged[-1]["id"], "")
        self.assertEqual(len(CHEATS), 2, "入参不得被修改")

    def test_merge_overwrite_keeps_id(self):
        pack = make_pack("p", [{"name": "改过的坦克", "code": "PANZER",
                                "hotkey": "F9", "group": "载具"}])
        merged, counts = merge_pack(CHEATS, pack, ["PANZER"], overwrite=True)
        self.assertEqual(counts["updated"], 1)
        self.assertEqual(merged[1]["id"], "2")
        self.assertEqual(merged[1]["hotkey"], "F9")

    def test_merge_no_overwrite_skips(self):
        pack = make_pack("p", [{"name": "改过的坦克", "code": "PANZER"}])
        merged, counts = merge_pack(CHEATS, pack, ["PANZER"], overwrite=False)
        self.assertEqual(counts["skipped"], 1)
        self.assertEqual(merged[1]["name"], "坦克")

    def test_pack_record(self):
        pack = make_pack("p", CHEATS, author="me")
        rec = pack_record(pack)
        self.assertEqual(rec["name"], "p")
        self.assertEqual(rec["pack_version"], 1)
        self.assertTrue(rec["imported_at"])


class TestPackComparison(unittest.TestCase):
    """1.9-H：包版本比对（纯本地）。"""

    def test_first_import_is_new(self):
        pack = make_pack("P", CHEATS)
        status, old = compare_pack_record(pack, [])
        self.assertEqual(status, "new")
        self.assertIsNone(old)

    def test_upgrade_when_version_higher(self):
        pack = make_pack("P", CHEATS)
        rec = pack_record(pack)
        rec["pack_version"] = 0
        status, old = compare_pack_record(pack, [rec])
        self.assertEqual(status, "upgrade")
        self.assertEqual(old["name"], "P")

    def test_changed_when_sha_differs(self):
        pack = make_pack("P", CHEATS)
        rec = dict(pack_record(pack), sha256="different")
        self.assertEqual(compare_pack_record(pack, [rec])[0], "changed")

    def test_same_when_identical(self):
        pack = make_pack("P", CHEATS)
        self.assertEqual(compare_pack_record(pack, [pack_record(pack)])[0], "same")

    def test_other_pack_name_ignored(self):
        pack = make_pack("P", CHEATS)
        self.assertEqual(compare_pack_record(pack, [pack_record(make_pack("Q", CHEATS))])[0],
                         "new")


class TestAutoAvoidHotkeys(unittest.TestCase):
    """1.9-G：包内热键自动避让。"""

    def test_candidates_order_and_no_f12(self):
        cands = _candidate_combos()
        self.assertEqual(cands[0], "F1")
        self.assertEqual(cands[-1], "Alt+F11")
        self.assertFalse(any("F12" in x for x in cands))
        self.assertEqual(len(cands), len(set(cands)))

    def test_conflicting_hotkey_moved(self):
        pack = make_pack("P", [{"code": "NEWONE", "name": "新", "hotkey": "F4"}])
        new_pack, changed = auto_avoid_hotkeys(pack, CHEATS, "Ctrl+Alt+P")
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0]["old"], "F4")
        self.assertNotEqual(changed[0]["new"], "F4")
        self.assertEqual(new_pack["cheats"][0]["hotkey"], changed[0]["new"])
        self.assertEqual(pack["cheats"][0]["hotkey"], "F4", "不得修改入参")

    def test_non_conflicting_hotkey_kept(self):
        pack = make_pack("P", [{"code": "NEWONE", "name": "新", "hotkey": "Ctrl+Alt+F9"}])
        _new, changed = auto_avoid_hotkeys(pack, CHEATS, "Ctrl+Alt+P")
        self.assertEqual(changed, [], "合法且未冲突的自定义键应保持原样")

    def test_same_code_local_is_not_conflict(self):
        pack = make_pack("P", [{"code": "ASPIRINE", "name": "满血", "hotkey": "F4"}])
        _new, changed = auto_avoid_hotkeys(pack, CHEATS, "Ctrl+Alt+P")
        self.assertEqual(changed, [])

    def test_internal_duplicates_avoided(self):
        pack = make_pack("P", [
            {"code": "AAA", "hotkey": "F6"},
            {"code": "BBB", "hotkey": "F6"},
            {"code": "CCC", "hotkey": "f6"},   # 大小写不敏感
        ])
        new_pack, changed = auto_avoid_hotkeys(pack, [], "Ctrl+Alt+P")
        keys = [c["hotkey"] for c in new_pack["cheats"]]
        self.assertEqual(len({k.lower() for k in keys}), 3)
        self.assertEqual(len(changed), 2)

    def test_pause_hotkey_is_reserved(self):
        pack = make_pack("P", [{"code": "NEWONE", "hotkey": "Ctrl+Alt+P"}])
        _new, changed = auto_avoid_hotkeys(pack, [], "Ctrl+Alt+P")
        self.assertEqual(len(changed), 1)

    def test_empty_hotkey_left_alone(self):
        pack = make_pack("P", [{"code": "NEWONE", "hotkey": ""}])
        _new, changed = auto_avoid_hotkeys(pack, CHEATS)
        self.assertEqual(changed, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
