# -*- coding: utf-8 -*-
"""1.7 结构约束测试：分层边界不能被后续改动悄悄破坏。

这些断言是"搬运没有走样"的守门人：
  * 数据层不得反向依赖 tkinter（否则 CI 无桌面环境跑不了）；
  * 兼容层与实现必须是同一个函数对象（否则改一处漏一处）；
  * app_dir() 必须仍指向项目根（搬运最容易踩的路径坑）。
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import vc_cheat_typer as app  # noqa: E402
import vcct.hotkeys as hotkeys  # noqa: E402
import vcct.loggingx as loggingx  # noqa: E402
import vcct.sender as sender  # noqa: E402
import vcct.store as store  # noqa: E402


class TestLayering(unittest.TestCase):
    def test_data_layer_does_not_import_tkinter(self):
        """store / loggingx 必须在无桌面环境可导入（CI 与纯逻辑测试的前提）。"""
        code = ("import sys; import vcct.store, vcct.loggingx, vcct.sender; "
                "print('tkinter' in sys.modules)")
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(), "False", "数据层不应连带导入 tkinter")

    def test_shim_points_to_same_objects(self):
        """兼容层必须是同一对象，不能是复制品。"""
        self.assertIs(app.parse_combo, hotkeys.parse_combo)
        self.assertIs(app.load_store, store.load_store)
        self.assertIs(app.append_log, loggingx.append_log)

    def test_app_dir_is_project_root(self):
        self.assertEqual(os.path.normcase(loggingx.app_dir()), os.path.normcase(ROOT))
        self.assertEqual(os.path.dirname(loggingx.data_path()), loggingx.app_dir())

    def test_no_win32_in_sender(self):
        """sender 必须与平台无关：不导入 ctypes，也不导入 winapi。"""
        path = os.path.join(ROOT, "vcct", "sender.py")
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods.add(node.module.split(".")[0])
        self.assertFalse(mods & {"ctypes", "win32", "winapi"}, f"sender 不应导入 {mods}")


class TestSenderTypes(unittest.TestCase):
    def test_params_defaults(self):
        p = sender.SendParams(code="ASPIRINE")
        self.assertEqual((p.interval_ms, p.hold_ms, p.pre_delay_ms), (45, 25, 180))
        self.assertFalse(p.uppercase)

    def test_params_immutable(self):
        p = sender.SendParams(code="ASPIRINE")
        with self.assertRaises(Exception):
            p.code = "PANZER"  # type: ignore[misc]

    def test_cancelled_carries_progress(self):
        exc = sender.SendCancelled(5, 18)
        self.assertEqual((exc.sent, exc.total), (5, 18))
        self.assertIn("5/18", str(exc))


if __name__ == "__main__":
    unittest.main(verbosity=2)
