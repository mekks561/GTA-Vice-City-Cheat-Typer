# -*- coding: utf-8 -*-
"""GUI 冒烟测试：只验证"窗口能建起来、结构没缺、能干净退出"。

刻意保持极轻：不发送、不注册真实热键行为、不依赖时序。
真实发送链路由 tests/test_sender.py（纯逻辑）+ build/gui_test_1_7.py（手工功能测试）覆盖。
"""
from __future__ import annotations

import os
import sys
import tkinter as tk
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import vc_cheat_typer as app_module  # noqa: E402
from vcct.store import default_store  # noqa: E402


class TestGuiSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            probe = tk.Tk()
            probe.destroy()
        except Exception as exc:  # 无桌面环境（部分 CI）直接跳过，不算失败
            raise unittest.SkipTest(f"无图形环境：{exc}")

    def test_build_and_close(self):
        old_load, old_save = app_module.load_store, app_module.save_store
        app_module.load_store = lambda path=None: default_store()
        app_module.save_store = lambda *a, **k: None
        root = None
        try:
            root = tk.Tk()
            app = app_module.CheatApp(root)
            root.update()

            self.assertEqual(len(app.tree["columns"]), 8, "表格列数变了，确认是否有意")
            self.assertIn("发送所选", app.btn_send.cget("text"))
            self.assertEqual(app._inflight, "", "初始应为空闲")
            self.assertFalse(app._stop.is_set(), "初始不应处于停止态")
            self.assertGreater(len(app.cheats), 0, "默认秘籍不能为空")

            app.on_close()
        finally:
            try:
                if root is not None:
                    root.destroy()
            except Exception:
                pass
            app_module.load_store, app_module.save_store = old_load, old_save


if __name__ == "__main__":
    unittest.main(verbosity=2)
