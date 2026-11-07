# -*- coding: utf-8 -*-
"""平台能力测试：权限探测与目标关键字自愈。

这两块是"按了没反应"的主要来源，必须有断言守住：
  * 权限探测查不到时要返回 None（不能返回 False，否则会把可用场景误拦）；
  * 目标关键字指向工具自身时必须自动重置（否则前台校验永远不通过）。
"""
from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import vc_cheat_typer as app_module  # noqa: E402
from vcct.winapi import process_elevated, self_elevated, window_pid  # noqa: E402


class TestElevation(unittest.TestCase):
    def test_self_elevated_is_bool(self):
        self.assertIsInstance(self_elevated(), bool)

    def test_process_elevated_unknown_returns_none(self):
        """查不到必须返回 None：调用方据此"不拦截"，而不是误判为低权限。"""
        self.assertIsNone(process_elevated(0))
        self.assertIsNone(process_elevated(999999))

    def test_window_pid_of_invalid_hwnd(self):
        self.assertEqual(window_pid(0), 0)

    def test_current_process_is_queryable(self):
        val = process_elevated(os.getpid())
        self.assertIn(val, (True, False), "本进程自己必须能被判定")


class TestTargetKeywordHeal(unittest.TestCase):
    def _heal(self, kw):
        dummy = SimpleNamespace(settings={"target_keywords": kw})
        fixed = app_module.CheatApp._heal_target_keywords(dummy)
        return fixed, dummy.settings["target_keywords"]

    def test_keyword_pointing_to_self_is_reset(self):
        """点「拾取当前窗口」时前台就是本工具 —— 必须自愈，否则永远不发送。"""
        for kw in ("VC-Cheat-Typer v1.7", "vc-cheat-typer", "VC-Cheat-Typer.exe"):
            fixed, new = self._heal(kw)
            self.assertTrue(fixed, kw)
            self.assertEqual(new, "Vice City")

    def test_normal_keyword_untouched(self):
        fixed, new = self._heal("Vice City")
        self.assertFalse(fixed)
        self.assertEqual(new, "Vice City")

    def test_empty_keyword_untouched(self):
        fixed, new = self._heal("")
        self.assertFalse(fixed)
        self.assertEqual(new, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
