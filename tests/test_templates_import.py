# -*- coding: utf-8 -*-
"""1.9-D/E：多游戏模板 + 文本/CSV 粘贴导入。"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from vcct.importer import parse_pasted  # noqa: E402
from vcct.templates import (  # noqa: E402
    TEMPLATE_NAMES, template_cheats, template_preset,
)


class TestTemplates(unittest.TestCase):
    def test_four_templates(self):
        self.assertEqual(len(TEMPLATE_NAMES), 4)
        for name in TEMPLATE_NAMES:
            with self.subTest(name=name):
                self.assertTrue(template_cheats(name))

    def test_classic_has_28_bound_cheats(self):
        cheats = template_cheats("VC 经典版")
        self.assertEqual(len(cheats), 28)
        self.assertTrue(all(c["hotkey"] for c in cheats))
        self.assertTrue(all(c["verified"] for c in cheats))

    def test_unverified_templates_marked_and_unbound(self):
        for name in ("GTA III（未验证）", "GTA SA（未验证）"):
            cheats = template_cheats(name)
            self.assertFalse(any(c["verified"] for c in cheats))
            self.assertFalse(any(c["hotkey"] for c in cheats))
            self.assertTrue(all("未实机验证" in c["note"] for c in cheats))
            self.assertTrue(all(c["code"].isalnum() and c["code"].isupper() for c in cheats))

    def test_fresh_ids_each_call(self):
        a, b = template_cheats("VC 经典版"), template_cheats("VC 经典版")
        self.assertNotEqual([c["id"] for c in a], [c["id"] for c in b])

    def test_preset_mapping(self):
        self.assertEqual(template_preset("VC 经典版")["char_interval_ms"], 45)
        self.assertEqual(template_preset("VC 决定版")["char_interval_ms"], 70)
        self.assertEqual(template_preset("GTA III（未验证）"), {})


class TestTextImport(unittest.TestCase):
    def test_plain_code_line(self):
        items, errors = parse_pasted("ASPIRINE\nPANZER")
        self.assertEqual([i["code"] for i in items], ["ASPIRINE", "PANZER"])
        self.assertEqual(errors, [])
        self.assertEqual(items[0]["name"], "ASPIRINE")

    def test_csv_variants(self):
        text = ("满血,ASPIRINE\n"
                "坦克,PANZER,F8\n"
                "晴天,ALOVELYDAY,Shift+F11,天气类\n"
                "# 这是注释\n\n")
        items, errors = parse_pasted(text)
        self.assertEqual(len(items), 3)
        self.assertEqual(errors, [])
        self.assertEqual(items[1]["hotkey"], "F8")
        self.assertEqual(items[2]["hotkey"], "Shift+F11")
        self.assertEqual(items[2]["note"], "天气类")

    def test_tab_separator_and_code_name_swap(self):
        items, errors = parse_pasted("满血\tASPIRINE\tF4\nPANZER,坦克2")
        self.assertEqual(errors, [])
        self.assertEqual(items[0]["code"], "ASPIRINE")
        # 第二行 "代码,名称" 兼容写法：首列纯代码 → 交换
        self.assertEqual(items[1]["name"], "坦克2")
        self.assertEqual(items[1]["code"], "PANZER")

    def test_line_numbers_in_errors(self):
        text = "OKCODE\n坏代码!\n\n满血,A\nALSOOK"
        items, errors = parse_pasted(text)
        self.assertEqual([i["code"] for i in items], ["OKCODE", "ALSOOK"])
        self.assertEqual([e["line"] for e in errors], [2, 4])
        self.assertTrue(all(e["raw"] and e["reason"] for e in errors))

    def test_bad_hotkey_reports_line(self):
        items, errors = parse_pasted("坦克,PANZER,Q")
        self.assertEqual(items, [])
        self.assertIn("热键", errors[0]["reason"])

    def test_duplicate_in_batch(self):
        items, errors = parse_pasted("AAA\nAAA")
        self.assertEqual(len(items), 1)
        self.assertIn("重复", errors[0]["reason"])

    def test_normalizes_case_and_strips_bom(self):
        items, errors = parse_pasted("\ufeff aspirine \n")
        self.assertEqual(items[0]["code"], "ASPIRINE")
        self.assertEqual(errors, [])

    def test_imported_items_marked_unverified(self):
        items, _ = parse_pasted("ASPIRINE")
        self.assertFalse(items[0]["verified"])
        self.assertEqual(items[0]["group"], "导入")


if __name__ == "__main__":
    unittest.main(verbosity=2)
