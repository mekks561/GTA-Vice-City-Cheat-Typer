# -*- coding: utf-8 -*-
"""2.0：`vcct.core` 架构守卫 + 目标/策略/钩子/CLI 回归。"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import vcct.core as core  # noqa: E402
from vcct.core.hooks import HookBus, make_log_hook  # noqa: E402
from vcct.core.strategy import (  # noqa: E402
    describe_plan, normalize_strategies, normalize_strategy, plan_send,
    resolve_strategy, should_retry,
)
from vcct.core.targets import (  # noqa: E402
    Target, evaluate_targets, match_target, normalize_targets, parse_target_spec,
    resolve_target, targets_from_games,
)
from vcct.store import default_store, normalize_store, save_store, load_store  # noqa: E402


class TestCoreBoundary(unittest.TestCase):
    """架构约束：core 零 tkinter、零 Win32 直接调用。"""

    def _core_files(self):
        files = []
        d = os.path.join(ROOT, "vcct", "core")
        for name in sorted(os.listdir(d)):
            if name.endswith(".py"):
                files.append(os.path.join(d, name))
        for mod in ("const", "sender", "store", "packs", "loggingx", "templates"):
            files.append(os.path.join(ROOT, "vcct", mod + ".py"))
        return files

    def test_no_tkinter_in_core_or_implementation(self):
        for path in self._core_files():
            with open(path, "r", encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertFalse(alias.name.split(".")[0] == "tkinter",
                                         f"{os.path.basename(path)} 不得 import tkinter")
                elif isinstance(node, ast.ImportFrom):
                    self.assertNotEqual((node.module or "").split(".")[0], "tkinter",
                                        f"{os.path.basename(path)} 不得 from tkinter import")

    def test_no_win32_calls_in_core(self):
        """core 新模块不得 import ctypes（AST 判定，避免误伤文档字符串）。"""
        core_dir = os.path.join(ROOT, "vcct", "core")
        for name in sorted(os.listdir(core_dir)):
            if not name.endswith(".py"):
                continue
            path = os.path.join(core_dir, name)
            with open(path, "r", encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    self.assertNotIn("ctypes", [a.name.split(".")[0] for a in node.names],
                                     f"{name} 不得直接加载 Win32")
                elif isinstance(node, ast.ImportFrom):
                    self.assertNotIn((node.module or "").split(".")[0], ("ctypes", "winapi"),
                                     f"{name} 不得依赖 winapi/ctypes")

    def test_importing_core_does_not_load_tkinter(self):
        code = "import sys; import vcct.core; assert 'tkinter' not in sys.modules; print('ok')"
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("ok", out.stdout)

    def test_core_facade_exports(self):
        for name in ("type_text", "SendParams", "normalize_store", "Target",
                     "plan_send", "HookBus", "default_store"):
            self.assertTrue(hasattr(core, name), f"core 缺少公共 API {name}")
        self.assertIn("vcct.core.targets", core.core_modules())
        # 惰性导出：用到时才加载平台相关模块
        self.assertTrue(callable(core.parse_combo))


class TestTargets(unittest.TestCase):
    def test_match_types(self):
        exe = {"name": "e", "match_type": "exe", "pattern": "GTA-VC", "enabled": True}
        self.assertTrue(match_target(exe, "", "gta-vc.exe"))
        self.assertFalse(match_target(exe, "gta-vc", "notepad.exe"))
        title = {"name": "t", "match_type": "title", "pattern": "vice city", "enabled": True}
        self.assertTrue(match_target(title, "GTA: Vice City", "x.exe"))
        cls = {"name": "c", "match_type": "class", "pattern": "GTA", "enabled": True}
        self.assertTrue(match_target(cls, "", "", "GTA_WindowClass"))
        self.assertFalse(match_target(dict(exe, enabled=False), "", "gta-vc.exe"))

    def test_evaluate_first_match(self):
        ts = normalize_targets([
            {"name": "a", "match_type": "exe", "pattern": "notepad"},
            {"name": "b", "match_type": "exe", "pattern": "note"},
        ])
        self.assertEqual(evaluate_targets(ts, "", "notepad.exe")["name"], "a")
        self.assertIsNone(evaluate_targets(ts, "", "chrome.exe"))
        self.assertIsNone(evaluate_targets([], "", "x.exe"))

    def test_normalize_drops_bad(self):
        ts = normalize_targets([
            {"name": "x", "pattern": "abc", "match_type": "bad", "ime_policy": "weird"},
            {"pattern": ""}, "junk", None,
        ])
        self.assertEqual(len(ts), 1)
        self.assertEqual(ts[0]["match_type"], "exe")
        self.assertEqual(ts[0]["ime_policy"], "disable")
        self.assertTrue(ts[0]["require_foreground"])

    def test_from_games(self):
        games = [{"name": "VC", "match_type": "exe", "pattern": "gta-vc",
                  "profile": "经典版", "enabled": True}]
        ts = targets_from_games(games)
        self.assertEqual(ts[0]["profile_ref"], "经典版")
        self.assertEqual(ts[0]["ime_policy"], "disable")
        self.assertEqual(targets_from_games(None), [])

    def test_resolve_falls_back(self):
        store = {"profiles": [{"name": "默认"}], "strategies": {"fast": {"kind": "burst"}}}
        r = resolve_target({"profile_ref": "不存在的方案", "strategy_ref": "missing"}, store)
        self.assertEqual(r["profile"], "")
        self.assertEqual(r["strategy"], "")
        r2 = resolve_target({"profile_ref": "默认", "strategy_ref": "fast",
                             "ime_policy": "keep", "require_foreground": False}, store)
        self.assertEqual(r2["profile"], "默认")
        self.assertEqual(r2["strategy"], "fast")
        self.assertFalse(r2["disable_ime"])
        self.assertFalse(r2["require_foreground"])

    def test_target_spec_and_dataclass(self):
        self.assertEqual(parse_target_spec("exe:gta-vc")["pattern"], "gta-vc")
        self.assertIsNone(parse_target_spec("???"))
        self.assertEqual(Target("a").to_dict()["match_type"], "exe")


class TestStrategy(unittest.TestCase):
    def test_default_is_fixed_and_preserves_legacy_params(self):
        s = normalize_strategy(None)
        p = plan_send(s, "ASPIRINE", 45, 180)
        self.assertEqual(s["kind"], "fixed")
        self.assertEqual(s["retries"], 0)
        self.assertEqual((p.interval_ms, p.hold_ms, p.pre_delay_ms), (45, 22, 180))
        self.assertFalse(should_retry(s, 0, 3, 8), "fixed 永不重试")

    def test_burst_clamps(self):
        s = normalize_strategy({"kind": "burst"})
        p = plan_send(s, "ASPIRINE", 45, 180)
        self.assertLessEqual(p.interval_ms, 20)
        self.assertLessEqual(p.hold_ms, 12)

    def test_adaptive_lengthens_on_retry(self):
        s = normalize_strategy({"kind": "adaptive", "retries": 2})
        p0 = plan_send(s, "ASPIRINE", 45, 180, attempt=0)
        p1 = plan_send(s, "RINE", 45, 180, attempt=1)
        p2 = plan_send(s, "RINE", 45, 180, attempt=2)
        self.assertEqual(p0.pre_delay_ms, 180)
        self.assertEqual(p1.pre_delay_ms, 0, "重试不该重复前置延迟")
        self.assertGreater(p1.interval_ms, p0.interval_ms)
        self.assertGreater(p2.interval_ms, p1.interval_ms)
        self.assertTrue(should_retry(s, 0, 3, 8))
        self.assertTrue(should_retry(s, 1, 3, 8))
        self.assertFalse(should_retry(s, 2, 3, 8))
        self.assertFalse(should_retry(s, 0, 8, 8), "已发完不重试")

    def test_invalid_kind_falls_back(self):
        self.assertEqual(normalize_strategy({"kind": "magic"})["kind"], "fixed")
        self.assertEqual(normalize_strategy("junk")["kind"], "fixed")
        self.assertEqual(normalize_strategy({"interval_ms": 99999})["interval_ms"], 300)

    def test_cheat_overrides_named(self):
        named = {"slow": {"kind": "burst", "interval_ms": 10}}
        self.assertEqual(resolve_strategy(named, {"strategy_ref": "slow"})["kind"], "burst")
        own = resolve_strategy(named, {"strategy": {"kind": "adaptive"},
                                       "strategy_ref": "slow"})
        self.assertEqual(own["kind"], "adaptive")
        self.assertEqual(normalize_strategies({"a": {"kind": "burst"}})["a"]["kind"], "burst")

    def test_describe_plan(self):
        d = describe_plan({"kind": "fixed"}, "ABCD", 45, 180)
        self.assertEqual(d["chars"], 4)
        self.assertEqual(d["planned_seconds"], 0.36)


class TestHooks(unittest.TestCase):
    def test_disabled_by_default(self):
        bus = HookBus()
        calls = []
        bus.register_before("veto", lambda t, c: False)
        self.assertTrue(bus.fire_before({}, {}))
        bus.fire_after({"result": "ok"})
        self.assertEqual(calls, [])
        self.assertEqual(bus.events, [])

    def test_before_can_veto(self):
        bus = HookBus(enabled=True)
        bus.register_before("veto", lambda t, c: False)
        self.assertFalse(bus.fire_before({}, {}))
        self.assertFalse(bus.events[0].ok)

    def test_after_and_exception_isolation(self):
        bus = HookBus(enabled=True)
        seen = []
        bus.register_after("ok", lambda r: seen.append(r["result"]))
        bus.register_after("bad", lambda r: 1 / 0)
        bus.fire_after({"result": "ok"})
        self.assertEqual(seen, ["ok"])
        self.assertEqual(len(bus.events), 2)
        self.assertFalse(bus.events[1].ok)

    def test_builtin_log_hook(self):
        lines = []
        before, after = make_log_hook(lines.append)
        bus = HookBus(enabled=True)
        bus.register_before("log", before)
        bus.register_after("log", after)
        self.assertTrue(bus.fire_before({}, {"code": "ASPIRINE"}))
        bus.fire_after({"result": "ok", "sent": 8})
        self.assertEqual(len(lines), 2)
        self.assertIn("ASPIRINE", lines[0])


class TestConfigFields(unittest.TestCase):
    def test_new_fields_default_empty(self):
        s = default_store()
        self.assertEqual(s["targets"], [])
        self.assertEqual(s["strategies"], {})
        self.assertFalse(s["settings"]["hooks_enabled"])

    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "cheats.json")
            store = default_store()
            store["targets"] = normalize_targets([{"name": "VC", "match_type": "exe",
                                                    "pattern": "gta-vc", "profile_ref": "默认"}])
            store["strategies"] = {"fast": {"kind": "burst"}}
            store["settings"]["hooks_enabled"] = True
            save_store(store, path)
            back = load_store(path)
            self.assertEqual(back["targets"][0]["profile_ref"], "默认")
            self.assertEqual(back["strategies"]["fast"]["kind"], "burst")
            self.assertTrue(back["settings"]["hooks_enabled"])

    def test_old_config_still_loads(self):
        raw = {"version": 2, "profiles": [{"name": "默认", "cheats": [{"code": "AAA"}]}]}
        out = normalize_store(raw)
        self.assertEqual(out["version"], 3)
        self.assertEqual(out["targets"], [])
        self.assertEqual(out["strategies"], {})


class TestCli(unittest.TestCase):
    def _run(self, argv):
        import contextlib
        import io
        from vcct.cli import main
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(argv)
        return rc, buf.getvalue()

    def test_version_and_dry_run(self):
        rc, out = self._run(["version"])
        self.assertEqual(rc, 0)
        self.assertIn("v2.0.0", out)
        rc, out = self._run(["send", "ASPIRINE"])   # 预演，不碰键盘
        self.assertEqual(rc, 0)
        self.assertIn("预演模式", out)

    def test_pack_info(self):
        from vcct.packs import make_pack
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "p.vcpack")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(make_pack("P", [{"code": "AAA"}]), fh, ensure_ascii=False)
            rc, out = self._run(["pack", "info", path])
            self.assertEqual(rc, 0)
            self.assertIn("条目 1 条", out)

    def test_list_and_targets(self):
        self.assertEqual(self._run(["list"])[0], 0)
        self.assertEqual(self._run(["targets"])[0], 0)
        self.assertEqual(self._run(["strategies"])[0], 0)

    def test_invalid_code_rejected(self):
        self.assertEqual(self._run(["send", "!!"])[0], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
