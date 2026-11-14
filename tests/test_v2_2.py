# -*- coding: utf-8 -*-
"""2.2 Nova UI 验收测试（契约即测试，见 docs/PLAN-2.2.md §5）。

性能阈值在 CI 上取规格值的 3 倍余量，避免机器波动误报；
本机实测值写入 BENCH 并在类结束时打印，供人工复核。
"""

from __future__ import annotations

import ast
import os
import re
import sys
import time
import tkinter as tk
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import vcct.ui as ui  # noqa: E402
from vcct import const  # noqa: E402
from vcct.const import APP_VER, STORE_VERSION  # noqa: E402
from vcct.store import default_store, normalize_store  # noqa: E402

BENCH: dict[str, float] = {}
UI_DIR = os.path.join(ROOT, "vcct", "ui")
HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
CI_FACTOR = 3.0


class TestVisualConsistency(unittest.TestCase):
    """V1~V5"""

    def test_v1_no_hardcoded_colors_outside_theme(self):
        for name in ("components.py", "shell.py", "commands.py", "__init__.py"):
            with open(os.path.join(UI_DIR, name), "r", encoding="utf-8") as fh:
                src = fh.read()
            # 注释里说明"不得出现颜色字面量"是允许的，只检查代码行
            code_lines = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#") and '"""' not in ln]
            self.assertFalse([ln for ln in code_lines if HEX.search(ln)], f"{name} 不得硬编码颜色，必须走设计令牌")

    def test_v2_wcag_contrast_both_themes(self):
        for theme in ui.THEMES:
            with self.subTest(theme=theme):
                result = ui.check_contrast(ui.PALETTES[theme])
                for name, item in result.items():
                    self.assertGreaterEqual(item["ratio"], 4.5, f"{theme}/{name} 对比度 {item['ratio']} < 4.5")
                    self.assertTrue(item["pass"])

    def test_v3_palette_keys_identical(self):
        self.assertEqual(set(ui.PALETTES["light"]), set(ui.PALETTES["dark"]))
        self.assertEqual(set(ui.PALETTES["light"]), set(ui.tokens("light").colors))
        self.assertEqual(set(ui.PALETTES["dark"]), set(ui.tokens("dark").colors))

    def test_v4_density_scaling_is_linear(self):
        comf, compact = ui.tokens("light", "comfortable"), ui.tokens("light", "compact")
        for key in ("xs", "sm", "md", "lg", "xl"):
            self.assertLess(compact.space(key), comf.space(key))
            self.assertGreater(compact.space(key), 0)
        self.assertEqual(comf.font(), (comf.fonts["family"], comf.fonts["size"]))
        self.assertEqual(ui.tokens("nonsense", "nonsense").theme, "light")

    def test_v5_three_dpi_scales_build(self):
        # 只建一个 Tk 根：反复 Tk()/destroy() 会让 ttk 的 ThemeChanged 事件
        # 投递到已销毁的解释器，产生无害但刺耳的 Tcl 噪音。
        root = tk.Tk()
        try:
            for scale in (1.0, 1.25, 1.5):
                with self.subTest(scale=scale):
                    tk_tokens = ui.tokens("light", "compact" if scale > 1.0 else "comfortable")
                    shell = ui.NovaShell(root, None, tk_tokens, ui.default_commands(None), lambda: None, lambda: None, "Nova")
                    self.assertIsNotNone(shell.content_host)
                    self.assertEqual(len(shell.pills), len(ui.STATUS_KEYS))
                    root.update_idletasks()
                    self.assertGreater(shell.status_bar.winfo_height(), 0, "状态中心不能被内容区挤成 0 高")
                    for child in list(root.winfo_children()):
                        child.destroy()
        finally:
            root.destroy()

    def test_v1_theme_is_single_source(self):
        """apply_theme 原地更新 const.C，既有 C[...] 引用自动跟随。"""
        before = dict(const.C)
        try:
            ui.apply_theme("dark")
            self.assertEqual(const.C["bg"], ui.PALETTES["dark"]["bg"])
            ui.apply_theme("light", classic=True)
            self.assertEqual(const.C["bg"], ui.classic_palette()["bg"])
        finally:
            const.C.clear()
            const.C.update(before)


class TestCommandRegistry(unittest.TestCase):
    def test_covers_all_existing_actions(self):
        import vc_cheat_typer as app_module

        reg = ui.default_commands(None)
        self.assertGreaterEqual(len(reg), 20)
        missing = [c.action_name for c in reg.all() if not callable(getattr(app_module.CheatApp, c.action_name, None))]
        self.assertEqual(missing, [], "命令必须绑定到已存在的业务方法")

    def test_fuzzy_search(self):
        reg = ui.default_commands(None)
        self.assertTrue(reg.search("设置"))
        self.assertTrue(reg.search("hist"))
        self.assertTrue(reg.search("htov"))  # 子序列模糊匹配
        self.assertEqual(reg.search("设置")[0].id, "data.settings")

    def test_execute_calls_existing_method(self):
        class Dummy:
            def __init__(self):
                self.calls = []

            def send_selected(self):
                self.calls.append("send")

        d = Dummy()
        reg = ui.default_commands(d)
        cmd = next(c for c in reg.all() if c.id == "cheat.send")
        self.assertTrue(reg.execute(cmd))
        self.assertEqual(d.calls, ["send"])

    def test_i2_keyboard_flow(self):
        root = tk.Tk()
        try:
            reg = ui.default_commands(None)
            palette = ui.CommandPalette(root, reg, ui.tokens("light"))
            palette.var_query.set("设置")
            palette._refresh()
            self.assertTrue(palette.results)
            palette._move(1)
            palette.entry.event_generate("<Return>")
            root.update_idletasks()
            palette.entry.event_generate("<Escape>")
        finally:
            root.destroy()


class TestInteractionAndPerformance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import vc_cheat_typer as app_module

        cls.mod = app_module
        cls.old_load, cls.old_save = app_module.load_store, app_module.save_store
        app_module.save_store = lambda *a, **k: None

    @classmethod
    def tearDownClass(cls):
        cls.mod.load_store, cls.mod.save_store = cls.old_load, cls.old_save
        # CI 控制台可能是 cp1252，输出必须保持 ASCII，否则 UnicodeEncodeError。
        print("\n[2.2 bench] " + "  ".join(f"{k}={v:.1f}ms" for k, v in BENCH.items()))

    def _make_app(self, mode="nova"):
        store = default_store()
        store["settings"]["ui_mode"] = mode
        old_load, old_cli = self.mod.load_store, self.mod._cli_ui_mode
        self.mod.load_store = lambda path=None: store
        self.mod._cli_ui_mode = None
        root = tk.Tk()
        t0 = time.perf_counter()
        app = self.mod.CheatApp(root)
        elapsed = (time.perf_counter() - t0) * 1000
        self.mod.load_store, self.mod._cli_ui_mode = old_load, old_cli
        return root, app, elapsed

    def _close(self, root, app):
        try:
            app.on_close(force=True)
        except Exception:
            pass
        try:
            root.update()  # 冲刷 ttk 挂起事件，避免销毁后收到 ThemeChanged
            root.destroy()
        except Exception:
            pass

    def test_i5_r1_both_modes_build_and_core_intact(self):
        for mode in ("nova", "classic"):
            with self.subTest(mode=mode):
                root, app, elapsed = self._make_app(mode)
                try:
                    self.assertIsNotNone(app.tree)
                    self.assertTrue(callable(app.send_selected))
                    self.assertIs(app.shell is not None, mode == "nova")
                    root.update_idletasks()
                    BENCH[f"build_{mode}"] = elapsed
                    # R1：主窗口构建 < 1.5s（CI 放宽 3 倍）
                    self.assertLess(elapsed, 1500 * CI_FACTOR)
                    # 业务方法在两种模式下都可调用
                    app.toggle_pause()
                    app.toggle_pause()
                    app.refresh_tree()
                finally:
                    self._close(root, app)

    def test_nova_hotkey_pill_reflects_conflicts(self):
        """Nova 外壳 hotkeys pill 必须随注册结果变色。

        内容区（行级 conflict tag / lbl_state / 热键总览页）两种模式共用，
        唯独外壳 pill 是 Nova 独有，_on_hotkeys_applied 必须显式同步。
        """
        root, app, _ = self._make_app("nova")
        try:
            pill = app.shell._pill_by_key["hotkeys"]
            cid = app.cheats[0]["id"]
            occupied = self.mod.ERROR_HOTKEY_ALREADY_REGISTERED

            app.conflicts.clear()
            app._on_hotkeys_applied({cid: (False, occupied)}, {})
            self.assertIn("⚠", pill.cget("text"))
            self.assertEqual(pill.cget("bg"), app.ui_tokens["status_warn"])

            app.conflicts.clear()
            app._on_hotkeys_applied({cid: (True, 0)}, {})
            self.assertIn("✔", pill.cget("text"))
            self.assertEqual(pill.cget("bg"), app.ui_tokens["status_ok"])

            app.toggle_pause()
            app.conflicts.clear()
            app._on_hotkeys_applied({}, {})
            self.assertIn("⏸", pill.cget("text"))
            self.assertEqual(pill.cget("bg"), app.ui_tokens["status_idle"])
        finally:
            self._close(root, app)

    def test_nova_hotkey_pill_opens_overview(self):
        root, app, _ = self._make_app("nova")
        try:
            opened = []
            app.open_hotkey_overview = lambda: opened.append(True)
            pill = app.shell._pill_by_key["hotkeys"]
            self.assertEqual(pill.cget("cursor"), "hand2")
            root.update()
            pill.event_generate("<Button-1>", x=2, y=2)
            root.update()
            self.assertEqual(opened, [True])
        finally:
            self._close(root, app)

    def test_i3_theme_switch_does_not_rebuild_widgets(self):
        root, app, _ = self._make_app("nova")
        try:
            tree_before = app.tree
            shell_before = app.shell
            t0 = time.perf_counter()
            app.toggle_theme()
            elapsed = (time.perf_counter() - t0) * 1000
            BENCH["theme_switch"] = elapsed
            self.assertIs(app.tree, tree_before)
            self.assertIs(app.shell, shell_before)
            self.assertLess(elapsed, 200 * CI_FACTOR)
        finally:
            self._close(root, app)

    def test_i4_no_blocking_calls_in_ui_layer(self):
        for name in os.listdir(UI_DIR):
            if not name.endswith(".py"):
                continue
            with open(os.path.join(UI_DIR, name), "r", encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            src = ast.unparse(tree)
            self.assertNotIn("time.sleep(", src, f"{name} 不得阻塞主线程")
            self.assertNotIn("sleep(", src, f"{name} 不得阻塞主线程")

    def test_i1_r3_command_search_latency(self):
        reg = ui.CommandRegistry(None)
        for i in range(200):
            reg.add(f"cmd.{i}", f"命令 {i}", "测试", "noop", f"key{i}")
        samples = []
        for q in ("命令", "cmd", "12", "测", ""):
            t0 = time.perf_counter()
            for _ in range(100):
                reg.search(q)
            samples.append((time.perf_counter() - t0) * 1000 / 100)
        BENCH["search_200_p95"] = sorted(samples)[-1]
        self.assertLess(BENCH["search_200_p95"], 20 * CI_FACTOR)

    def test_r2_thousand_rows_render(self):
        root, app, _ = self._make_app("nova")
        try:
            app.cheats[:] = [
                {
                    "id": f"x{i}",
                    "name": f"秘籍{i}",
                    "code": f"CODE{i:04d}",
                    "hotkey": "",
                    "group": "测试",
                    "note": "",
                    "interval_ms": 0,
                    "verified": True,
                    "enabled": True,
                }
                for i in range(1000)
            ]
            t0 = time.perf_counter()
            app.refresh_tree()
            elapsed = (time.perf_counter() - t0) * 1000
            BENCH["render_1000"] = elapsed
            self.assertLess(elapsed, 300 * CI_FACTOR)
        finally:
            self._close(root, app)


class TestCompatibility(unittest.TestCase):
    """数据兼容要求（§4）"""

    def test_config_still_v3_and_new_settings_optional(self):
        s = default_store()
        self.assertEqual(s["version"], STORE_VERSION)
        self.assertEqual(s["settings"]["ui_mode"], "nova")
        self.assertEqual(s["settings"]["theme"], "light")
        self.assertEqual(s["settings"]["density"], "comfortable")

    def test_old_config_gets_nova_defaults(self):
        for version in (1, 2, 3):
            with self.subTest(version=version):
                raw = {"version": version, "profiles": [{"name": "默认", "cheats": [{"code": "AAA"}]}]}
                out = normalize_store(raw)
                self.assertEqual(out["settings"]["ui_mode"], "nova")
                self.assertEqual(out["version"], 3)

    def test_classic_restores_legacy_palette(self):
        before = dict(const.C)
        try:
            ui.apply_theme("dark")
            ui.apply_theme("light", classic=True)
            self.assertEqual(const.C, ui.classic_palette())
        finally:
            const.C.clear()
            const.C.update(before)

    def test_no_new_store_fields(self):
        """本版不得改动持久化字段集合（除可选 settings 键）。"""
        keys = set(default_store().keys())
        expected = {
            "app",
            "version",
            "settings",
            "active_profile",
            "profiles",
            "stats",
            "today",
            "games",
            "packs",
            "ui",
            "history",
            "targets",
            "strategies",
        }
        self.assertEqual(keys, expected)

    def test_version_aligned(self):
        self.assertEqual(APP_VER, "2.2.1")
        with open(os.path.join(ROOT, "pyproject.toml"), "r", encoding="utf-8") as fh:
            self.assertIn(f'version = "{APP_VER}"', fh.read())


if __name__ == "__main__":
    unittest.main(verbosity=2)
