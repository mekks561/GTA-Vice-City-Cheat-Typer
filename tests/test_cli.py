# -*- coding: utf-8 -*-
"""CLI 子命令（pack validate / diff / import）回归测试。

CLI 是一层薄组合，底层 packs.py 与 store.py 已各自被 test_packs.py / test_v2_1.py 覆盖；
这里只测：参数解析 → 函数返回正确 exit code → 关键输出字符串包含预期关键词。
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

# 确保项目根在 sys.path 里，这样 `python -m unittest discover -s tests` 也能跑
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from vcct.cli import cmd_pack_validate, cmd_pack_diff, cmd_pack_import, main
from vcct.packs import make_pack


def _make_simple_pack(name="测试包", cheat_codes=("AAA", "BBB")):
    cheats = [
        {
            "id": f"x{i}",
            "name": f"秘籍{i}",
            "code": c,
            "hotkey": f"F{i + 1}",
            "group": "武器",
            "note": "",
            "interval_ms": 0,
            "verified": True,
        }
        for i, c in enumerate(cheat_codes)
    ]
    return make_pack(name, cheats, author="dev", game="VC 经典版")


class _FakeArgs:
    """argparse 命名空间替身，避免在测试里绕 parser。"""

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


class TestPackValidate(unittest.TestCase):
    def test_valid_pack_exit_0(self):
        pack = _make_simple_pack()
        with tempfile.NamedTemporaryFile("w", suffix=".vcpack", delete=False, encoding="utf-8") as f:
            json.dump(pack, f)
            path = f.name
        try:
            exit_code = main(["pack", "validate", path])
            self.assertEqual(exit_code, 0)
        finally:
            os.unlink(path)

    def test_broken_json_exit_1(self):
        with tempfile.NamedTemporaryFile("w", suffix=".vcpack", delete=False, encoding="utf-8") as f:
            f.write("{not json")
            path = f.name
        try:
            exit_code = main(["pack", "validate", path])
            self.assertEqual(exit_code, 1)
        finally:
            os.unlink(path)

    def test_json_flag_prints_object(self):
        pack = _make_simple_pack()
        with tempfile.NamedTemporaryFile("w", suffix=".vcpack", delete=False, encoding="utf-8") as f:
            json.dump(pack, f)
            path = f.name
        try:
            buf = io.StringIO()
            with mock.patch("sys.stdout", buf):
                code = cmd_pack_validate(_FakeArgs(file=path, json=True))
            self.assertEqual(code, 0)
            data = json.loads(buf.getvalue())
            self.assertTrue(data["ok"])
            self.assertEqual(data["pack"]["cheat_count"], 2)
        finally:
            os.unlink(path)


class TestPackDiff(unittest.TestCase):
    def test_diff_counts_new(self):
        pack = _make_simple_pack()
        with tempfile.NamedTemporaryFile("w", suffix=".vcpack", delete=False, encoding="utf-8") as f:
            json.dump(pack, f)
            path = f.name
        try:
            fake_store = {"active_profile": "默认", "profiles": [{"name": "默认", "cheats": []}], "settings": {}}
            buf = io.StringIO()
            with mock.patch("vcct.cli.load_store", return_value=fake_store):
                with mock.patch("sys.stdout", buf):
                    code = cmd_pack_diff(_FakeArgs(file=path, profile=None))
            self.assertEqual(code, 0)
            self.assertIn("新增 2", buf.getvalue())
        finally:
            os.unlink(path)


class TestPackImport(unittest.TestCase):
    def test_dry_run_does_not_save(self):
        pack = _make_simple_pack()
        with tempfile.NamedTemporaryFile("w", suffix=".vcpack", delete=False, encoding="utf-8") as f:
            json.dump(pack, f)
            path = f.name
        try:
            fake_store = {"active_profile": "默认", "profiles": [{"name": "默认", "cheats": []}], "settings": {}}
            save_mock = mock.Mock()
            with mock.patch("vcct.cli.load_store", return_value=fake_store):
                with mock.patch("vcct.store.save_store", save_mock):
                    code = cmd_pack_import(_FakeArgs(file=path, profile=None, no_overwrite=False, avoid_hotkeys=False, dry_run=True))
            self.assertEqual(code, 0)
            save_mock.assert_not_called()
        finally:
            os.unlink(path)

    def test_overwrite_writes_store_and_records_pack(self):
        pack = _make_simple_pack()
        with tempfile.NamedTemporaryFile("w", suffix=".vcpack", delete=False, encoding="utf-8") as f:
            json.dump(pack, f)
            path = f.name
        try:
            fake_store = {"active_profile": "默认", "profiles": [{"name": "默认", "cheats": []}], "settings": {}}
            saved = []

            def _capture(s):
                saved.append(s)

            with mock.patch("vcct.cli.load_store", return_value=fake_store):
                with mock.patch("vcct.store.save_store", _capture):
                    code = cmd_pack_import(_FakeArgs(file=path, profile=None, no_overwrite=False, avoid_hotkeys=False, dry_run=False))
            self.assertEqual(code, 0)
            self.assertEqual(len(saved), 1)
            self.assertEqual(len(saved[0]["profiles"][0]["cheats"]), 2)
            self.assertEqual(len(saved[0]["packs"]), 1)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
