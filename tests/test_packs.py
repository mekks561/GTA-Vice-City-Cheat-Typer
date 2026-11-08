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
    PACK_FORMAT, diff_pack, make_pack, merge_pack, pack_record, pack_signature,
    validate_pack,
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
