# -*- coding: utf-8 -*-
"""2.1：控制台版 CLI 入口（供 PyInstaller 打 console=True 的独立 exe）。

GUI 子系统（console=False）的 exe 在交互控制台里看不到 stdout，
所以命令行用法需要单独一个控制台产物。源码模式仍用 `python -m vcct.cli`。
"""
import sys

from vcct.cli import main

if __name__ == "__main__":
    sys.exit(main())
