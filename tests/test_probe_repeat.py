# -*- coding: utf-8 -*-
"""1.9.1 回归：同一进程内连续调用注入探针。

真实硬件/桌面测试，默认跳过（CI 的 Windows runner 没有可交互前台）。
本地验证：  VCCT_REAL_PROBE=1 python -m unittest tests.test_probe_repeat -v
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from vcct.winapi import raw_char_probe  # noqa: E402

REAL = os.environ.get("VCCT_REAL_PROBE") == "1" and os.name == "nt"


@unittest.skipUnless(REAL, "需要可交互桌面；设 VCCT_REAL_PROBE=1 手动运行")
class TestProbeRepeat(unittest.TestCase):
    def test_two_probes_in_one_process(self):
        """旧实现第二次调用会复用已被 GC 的窗口过程 → WM_CHAR 全丢。"""
        for attempt in (1, 2):
            with self.subTest(attempt=attempt):
                got_fg, got = raw_char_probe("VCCT")
                self.assertTrue(got_fg, "未取得前台（桌面被占用时可重跑）")
                self.assertEqual(got.strip().upper(), "VCCT")


if __name__ == "__main__":
    unittest.main(verbosity=2)
