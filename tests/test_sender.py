# -*- coding: utf-8 -*-
"""1.7 发送引擎单测：取消、残键、时序、进度。

这里全部用假 `send_key` / `sleep`，所以不碰键盘、不依赖 Windows，
跑起来是毫秒级。断言的是"调用序列"而不是"屏幕上出现了什么字"——
后者只能人工在游戏里验，前者才是能进 CI 的部分。
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from vcct.sender import (  # noqa: E402
    SLEEP_SLICE_MS,
    SendCancelled,
    SendError,
    SendParams,
    default_hold,
    type_text,
)

VK_A, VK_B, VK_LSHIFT = 65, 66, 0xA0


class FakeInput:
    """记录按键与睡眠，可按"虚拟时间"自动触发取消。"""

    def __init__(self, vk_map=None, cancel_at=None):
        self.keys: list[tuple[int, bool]] = []
        self.sleeps: list[float] = []
        self.elapsed = 0.0
        self.cancel_at = cancel_at
        self.stop = FakeStop(self)
        self.vk_map = vk_map if vk_map is not None else {"a": VK_A, "b": VK_B, "c": 67}

    def send_key(self, vk: int, keyup: bool) -> None:
        self.keys.append((vk, keyup))

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.elapsed += seconds

    def lookup(self, ch: str):
        return self.vk_map.get(ch.lower())

    def assert_balanced(self, case: unittest.TestCase) -> None:
        down = set()
        for vk, keyup in self.keys:
            if keyup:
                down.discard(vk)
            else:
                down.add(vk)
        case.assertEqual(down, set(), f"有按键未抬起：{down}")


class FakeStop:
    def __init__(self, fake: FakeInput):
        self.fake = fake
        self.flag = False

    def is_set(self) -> bool:
        if self.flag:
            return True
        if self.fake.cancel_at is not None and self.fake.elapsed >= self.fake.cancel_at - 1e-9:
            self.flag = True
        return self.flag


def run(code="ab", **kwargs):
    fake = FakeInput(vk_map=kwargs.pop("vk_map", None), cancel_at=kwargs.pop("cancel_at", None))
    params = kwargs.pop("params", None) or SendParams.for_code(
        code, interval_ms=kwargs.pop("interval", 45), pre_delay_ms=kwargs.pop("pre", 0))
    sent = type_text(params, fake.stop,
                     send_key=fake.send_key, sleep=fake.sleep, lookup_vk=fake.lookup,
                     check_target=kwargs.pop("check_target", None),
                     on_progress=kwargs.pop("on_progress", None))
    return sent, fake


class TestSequence(unittest.TestCase):
    def test_full_sequence(self):
        """每个字符必须是 按下 -> 停顿 -> 抬起，顺序不能乱。"""
        sent, fake = run("ab")
        self.assertEqual(sent, 2)
        self.assertEqual(fake.keys, [(VK_A, False), (VK_A, True), (VK_B, False), (VK_B, True)])
        fake.assert_balanced(self)

    def test_hold_and_interval_split(self):
        """hold 与剩余间隔分开推进，总时长等于 interval。"""
        _, fake = run("a", interval=45)
        self.assertEqual(fake.sleeps, [0.02, 0.002, 0.02, 0.003])  # 22 拆两片，23 拆两片

    def test_sleeps_never_exceed_slice(self):
        """所有睡眠必须切片，否则取消最长要等一整个间隔。"""
        _, fake = run("abc", interval=300, pre=180)
        self.assertTrue(fake.sleeps)
        self.assertLessEqual(max(fake.sleeps), SLEEP_SLICE_MS / 1000.0 + 1e-9)

    def test_empty_code_only_pre_delay(self):
        sent, fake = run("", pre=40)
        self.assertEqual(sent, 0)
        self.assertEqual(fake.keys, [])
        self.assertAlmostEqual(sum(fake.sleeps), 0.04)

    def test_progress_reported(self):
        seen = []
        run("ab", on_progress=lambda s, t: seen.append((s, t)))
        self.assertEqual(seen, [(1, 2), (2, 2)])


class TestCancel(unittest.TestCase):
    def test_cancel_during_pre_delay(self):
        """触发后 180ms 里按暂停，必须一个键都不发。"""
        with self.assertRaises(SendCancelled) as ctx:
            run("ab", pre=180, cancel_at=0.05)
        self.assertEqual((ctx.exception.sent, ctx.exception.total), (0, 2))
        _, fake = run("ab", pre=0)
        self.assertTrue(fake.keys)  # 对照：不取消时有按键

    def test_cancel_mid_hold_releases_key(self):
        """在按住某键的 25ms 里取消：该键必须被抬起。"""
        fake = FakeInput()
        fake.cancel_at = 0.010  # 落在第一个 hold 切片内
        with self.assertRaises(SendCancelled):
            type_text(SendParams.for_code("ab", pre_delay_ms=0), fake.stop,
                      send_key=fake.send_key, sleep=fake.sleep, lookup_vk=fake.lookup)
        self.assertEqual(fake.keys, [(VK_A, False), (VK_A, True)])
        fake.assert_balanced(self)

    def test_cancel_between_chars(self):
        """第一个字符已完整发出、间隔中取消：进度必须是 1，不能是 0 或 2。"""
        with self.assertRaises(SendCancelled) as ctx:
            run("ab", interval=45, cancel_at=0.022)
        self.assertEqual(ctx.exception.sent, 1)
        self.assertEqual(ctx.exception.total, 2)

    def test_cancel_never_exceeds_total(self):
        with self.assertRaises(SendCancelled) as ctx:
            run("ab", cancel_at=0.0)
        self.assertEqual(ctx.exception.sent, 0)


class TestErrors(unittest.TestCase):
    def test_illegal_char_raises_and_leaves_no_key_down(self):
        fake = FakeInput(vk_map={"a": VK_A})  # 不认 ? 与 b
        with self.assertRaises(SendError) as ctx:
            type_text(SendParams.for_code("a?", pre_delay_ms=0), fake.stop,
                      send_key=fake.send_key, sleep=fake.sleep, lookup_vk=fake.lookup)
        self.assertEqual((ctx.exception.sent, ctx.exception.total), (1, 2))
        self.assertIn("?", ctx.exception.reason)
        fake.assert_balanced(self)

    def test_send_error_is_value_error(self):
        """调用方既可按 SendError 精确捕获，也可按 ValueError 粗粒度兜底。"""
        self.assertTrue(issubclass(SendError, ValueError))

    def test_check_target_false_aborts(self):
        fake = FakeInput()
        with self.assertRaises(SendError):
            type_text(SendParams.for_code("ab", pre_delay_ms=0), fake.stop,
                      send_key=fake.send_key, sleep=fake.sleep, lookup_vk=fake.lookup,
                      check_target=lambda: False)
        self.assertEqual(fake.keys, [])
        fake.assert_balanced(self)

    def test_check_target_called_per_char(self):
        calls = []
        fake = FakeInput()
        type_text(SendParams.for_code("ab", pre_delay_ms=0), fake.stop,
                  send_key=fake.send_key, sleep=fake.sleep, lookup_vk=fake.lookup,
                  check_target=lambda: calls.append(1) or True)
        self.assertEqual(len(calls), 2)


class TestUppercase(unittest.TestCase):
    def test_shift_down_before_and_up_after(self):
        fake = FakeInput()
        type_text(SendParams.for_code("a", pre_delay_ms=0, uppercase=True), fake.stop,
                  send_key=fake.send_key, sleep=fake.sleep, lookup_vk=fake.lookup)
        self.assertEqual(fake.keys,
                         [(VK_LSHIFT, False), (VK_A, False), (VK_A, True), (VK_LSHIFT, True)])
        fake.assert_balanced(self)

    def test_shift_released_on_cancel(self):
        fake = FakeInput()
        fake.cancel_at = 0.010
        with self.assertRaises(SendCancelled):
            type_text(SendParams.for_code("ab", pre_delay_ms=0, uppercase=True), fake.stop,
                      send_key=fake.send_key, sleep=fake.sleep, lookup_vk=fake.lookup)
        self.assertEqual(fake.keys[-1], (VK_LSHIFT, True))
        fake.assert_balanced(self)

    def test_shift_released_on_error(self):
        fake = FakeInput(vk_map={"a": VK_A})
        with self.assertRaises(SendError):
            type_text(SendParams.for_code("a?", pre_delay_ms=0, uppercase=True), fake.stop,
                      send_key=fake.send_key, sleep=fake.sleep, lookup_vk=fake.lookup)
        self.assertEqual(fake.keys[-1], (VK_LSHIFT, True))
        fake.assert_balanced(self)


class TestHoldRule(unittest.TestCase):
    def test_default_hold_clamped(self):
        """hold 夹在 8~60：太短会被低帧率漏掉，太长会拖慢连打。"""
        self.assertEqual(default_hold(10), 8)
        self.assertEqual(default_hold(45), 22)
        self.assertEqual(default_hold(300), 60)

    def test_for_code_uses_hold_rule(self):
        self.assertEqual(SendParams.for_code("a", interval_ms=45).hold_ms, 22)
        self.assertEqual(SendParams.for_code("a", interval_ms=45, hold_ms=30).hold_ms, 30)

    def test_for_code_sanitizes(self):
        p = SendParams.for_code("a", interval_ms=1, pre_delay_ms=-5, hold_ms=-1)
        self.assertEqual((p.interval_ms, p.pre_delay_ms, p.hold_ms), (10, 0, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
