# -*- coding: utf-8 -*-
"""2.1 回归：数据目录模式 / 多语言 / 设置项 / 打包元数据。"""
from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from vcct import paths  # noqa: E402
from vcct.const import APP_VER, DEFAULT_SETTINGS, STORE_VERSION  # noqa: E402
from vcct.i18n import (  # noqa: E402
    EN_TEXT, LOCALES, apply_locale_to_widgets, get_locale, set_locale, t,
)
from vcct.store import default_store, normalize_store, save_store, load_store  # noqa: E402


class _TempMode(unittest.TestCase):
    """把数据目录重定向到临时目录，避免测试碰真实项目文件。"""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.orig_app_dir = paths.app_dir
        self.orig_env = os.environ.get("LOCALAPPDATA")
        self.orig_cache = paths._mode_cache
        paths.app_dir = lambda: self.td.name
        os.environ["LOCALAPPDATA"] = os.path.join(self.td.name, "appdata")
        paths._mode_cache = None

    def tearDown(self):
        paths.app_dir = self.orig_app_dir
        paths._mode_cache = self.orig_cache
        if self.orig_env is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = self.orig_env
        self.td.cleanup()


class TestDataPaths(_TempMode):
    def test_default_is_portable(self):
        self.assertEqual(paths.read_data_mode(), "portable")
        self.assertEqual(paths.data_root(), self.td.name)
        self.assertEqual(paths.data_path(), os.path.join(self.td.name, "cheats.json"))

    def test_set_mode_persists_in_marker(self):
        self.assertTrue(paths.set_data_mode("user"))
        with open(paths.mode_file(), "r", encoding="utf-8") as fh:
            self.assertEqual(fh.read().strip(), "user")
        self.assertEqual(paths.read_data_mode(), "user")
        self.assertTrue(paths.data_root().endswith("VC-Cheat-Typer"))

    def test_invalid_mode_rejected(self):
        with self.assertRaises(ValueError):
            paths.set_data_mode("cloud")

    def test_bad_marker_falls_back_to_portable(self):
        with open(paths.mode_file(), "w", encoding="utf-8") as fh:
            fh.write("garbage")
        paths._mode_cache = None
        self.assertEqual(paths.read_data_mode(), "portable")

    def test_user_mode_falls_back_when_unwritable(self):
        paths.set_data_mode("user")
        # 用一个"文件"冒充目录，makedirs 会失败 → 回落 portable
        blocker = os.path.join(self.td.name, "appdata")
        with open(blocker, "w", encoding="utf-8") as fh:
            fh.write("x")
        self.assertEqual(paths.data_root(), self.td.name)

    def test_other_mode(self):
        self.assertEqual(paths.other_mode("portable"), "user")
        self.assertEqual(paths.other_mode("user"), "portable")

    def test_copy_config_never_deletes_or_overwrites(self):
        src = paths.data_path()
        with open(src, "w", encoding="utf-8") as fh:
            json.dump({"version": 3, "profiles": []}, fh)
        ok, dest = paths.copy_config_to("user")
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(src), "原文件必须保留")
        self.assertTrue(os.path.exists(dest))
        ok2, msg = paths.copy_config_to("user")
        self.assertFalse(ok2)
        self.assertIn("拒绝覆盖", msg)

    def test_copy_missing_source(self):
        ok, msg = paths.copy_config_to("user")
        self.assertFalse(ok)
        self.assertIn("不存在", msg)

    def test_describe_snapshot(self):
        d = paths.describe()
        self.assertEqual(d["mode"], "portable")
        self.assertEqual(d["other_mode"], "user")
        self.assertEqual(d["config"], paths.data_path())
        self.assertTrue(d["mode_persisted"])


class TestI18n(unittest.TestCase):
    def tearDown(self):
        set_locale("zh")

    def test_zh_is_default_and_passes_through(self):
        set_locale("zh")
        self.assertEqual(get_locale(), "zh")
        self.assertEqual(t("发送所选"), "发送所选")
        self.assertTrue(LOCALES == ("zh", "en"))

    def test_en_translates_and_unknown_kept(self):
        set_locale("en")
        self.assertEqual(t("添加"), "Add")
        self.assertEqual(t("某段没收录的文案"), "某段没收录的文案")
        self.assertGreater(len(EN_TEXT), 80)

    def test_invalid_locale_falls_back(self):
        self.assertEqual(set_locale("fr"), "zh")

    def test_dynamic_state_patterns(self):
        set_locale("en")
        self.assertEqual(t("共 28 条 · 今日 3 次"), "Total: 28 · Today 3")
        self.assertEqual(t("✔ 28 个快捷键全部生效"), "✔ 28 hotkeys active")

    def test_apply_to_widgets(self):
        import tkinter as tk
        from tkinter import ttk
        set_locale("en")
        root = tk.Tk()
        try:
            lbl = tk.Label(root, text="添加")
            btn = ttk.Button(root, text="关闭")
            menu = tk.Menu(root, tearoff=0)
            menu.add_command(label="保存")
            n = apply_locale_to_widgets(root, menus=(menu,))
            self.assertGreaterEqual(n, 3)
            self.assertEqual(lbl.cget("text"), "Add")
            self.assertEqual(btn.cget("text"), "Close")
            self.assertEqual(menu.entrycget(0, "label"), "Save")
        finally:
            root.destroy()
            set_locale("zh")


class TestSettingsAndPackaging(unittest.TestCase):
    def test_new_settings_defaults(self):
        s = default_store()
        self.assertEqual(s["settings"]["locale"], "zh")
        self.assertFalse(s["settings"]["check_updates"])
        self.assertEqual(s["version"], STORE_VERSION)
        self.assertFalse(s["settings"]["hooks_enabled"])

    def test_locale_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "cheats.json")
            store = default_store()
            store["settings"]["locale"] = "en"
            store["settings"]["check_updates"] = True
            save_store(store, p)
            back = load_store(p)
            self.assertEqual(back["settings"]["locale"], "en")
            self.assertTrue(back["settings"]["check_updates"])

    def test_old_config_gets_new_defaults(self):
        out = normalize_store({"version": 2, "profiles": [{"name": "默认",
                                                            "cheats": [{"code": "AAA"}]}]})
        self.assertEqual(out["settings"]["locale"], "zh")
        self.assertFalse(out["settings"]["check_updates"])

    def test_pyproject_has_build_system_and_matching_version(self):
        with open(os.path.join(ROOT, "pyproject.toml"), "r", encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("[build-system]", text)
        self.assertIn('build-backend = "setuptools.build_meta"', text)
        self.assertIn(f'version = "{APP_VER}"', text, "pyproject 版本必须与 APP_VER 一致")
        self.assertIn('packages = ["vcct", "vcct.core"]', text)
        self.assertIn("[project.scripts]", text)

    def test_cli_entry_has_main(self):
        import cli_entry
        self.assertTrue(callable(cli_entry.main))

    def test_update_entry_is_offline_only(self):
        """更新入口不得引入任何网络请求（只许 webbrowser.open）。"""
        path = os.path.join(ROOT, "vc_cheat_typer.py")
        with open(path, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        fn = next((n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "check_updates"), None)
        self.assertIsNotNone(fn)
        src = ast.unparse(fn)
        self.assertIn("webbrowser.open", src)
        for banned in ("urllib", "requests", "urlopen", "socket", "http.client"):
            self.assertNotIn(banned, src, f"更新入口不得出现 {banned}")

    def test_contributing_documents_boundaries(self):
        with open(os.path.join(ROOT, "CONTRIBUTING.md"), "r", encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("不得 `import tkinter`", text)
        self.assertIn("core` 新模块不得直接调用 Win32", text)
        self.assertIn("不联网", text)

    def test_main_window_en_locale(self):
        """英文模式下主窗口真的被翻译，且不会抛 Tcl 错误。"""
        import tkinter as tk
        import vc_cheat_typer as app_module
        old_load, old_save = app_module.load_store, app_module.save_store
        store = default_store()
        store["settings"]["locale"] = "en"
        app_module.load_store = lambda path=None: store
        app_module.save_store = lambda *a, **k: None
        root = None
        try:
            root = tk.Tk()
            app = app_module.CheatApp(root)
            root.update()
            self.assertEqual(get_locale(), "en")
            self.assertEqual(app.btn_send.cget("text"), "▶ Send Selected (Enter)")
            self.assertEqual(app.btn_pause.cget("text"), "⏸ Pause hotkeys")
            app.on_close(force=True)
        finally:
            set_locale("zh")
            if root is not None:
                try:
                    root.destroy()
                except Exception:
                    pass
            app_module.load_store, app_module.save_store = old_load, old_save


if __name__ == "__main__":
    unittest.main(verbosity=2)
