# CONTRIBUTING — 架构约束与开发流程

> 路线图 5.4 要求把架构约束写进 CONTRIBUTING。本文是**硬约束**，PR 违反即打回。

## 1. 分层

```
vcct/
├── core/          # 零 GUI 依赖、可独立安装（import vcct.core）
│   ├── __init__.py   公共 API 门面（惰性导出平台相关模块）
│   ├── targets.py    目标应用规则（纯逻辑）
│   ├── strategy.py   发送策略（纯逻辑）
│   └── hooks.py      扩展点（纯逻辑）
├── const.py / winapi.py / hotkeys.py / sender.py / store.py / packs.py
├── loggingx.py / templates.py / importer.py / paths.py / i18n.py
├── tray.py / cli.py
└── vc_cheat_typer.py（仓库根，UI 壳）
```

**兼容式抽库**：2.0 起 `vcct/core/` 是门面与新能力模块，既有平铺模块仍是实现层。
不要为了"目录看着整齐"把 `vcct/*.py` 搬进 `core/` —— 那会同时打断 1.7～1.9 的
import、PyInstaller spec 与 CLI（路线图风险 R2.0.1）。

## 2. 三条不可违反的边界

1. **`core` 不得 `import tkinter`**（包括函数内延迟导入）。`import vcct.core`
   在无桌面 / 非 Windows 环境也必须成功；平台相关模块用 PEP 562 惰性导出。
2. **`core` 新模块不得直接调用 Win32**（不得 `import ctypes` / `windll` / `winapi`）。
   平台能力一律通过注入函数传入（见 `hooks.make_switch_window_hook`）。
3. **UI 不得直接调 `SendInput`**：一律走 `vcct.sender.type_text` + 注入的
   `send_key` / `lookup_vk`；所有 Win32 调用集中在 `winapi.py`。

`tests/test_v2_core.py::TestCoreBoundary` 用 AST 守住前两条，CI 每次跑。

## 3. 跨版本不变量（任何情况下不牺牲）

- 零第三方**运行时**依赖；
- 配置不丢（迁移前备份、失败可回滚、更高版本配置禁止回写）；
- 发布必带 SHA256；
- 暂停键在任何状态下都能停掉注入（发送睡眠切片 ≤20ms）；
- 不读写游戏内存、**不联网**、不支持联机 / 反作弊环境。

新增字段一律可选：缺省 = 旧行为。允许"程序新 + 配置旧"，不允许"程序旧 + 配置新"
静默降级。配置版本目前 v3，迁移链在 `vcct/store.py::migrate_store`（纯函数、不碰磁盘）。

## 4. 本地开发

```bat
:: 运行时零依赖，直接跑
run.bat
python vc_cheat_typer.py --selftest
python vc_cheat_typer.py --diagnose
python vc_cheat_typer.py --cli list

:: 把 core 作为可编辑包安装（离线环境用 --no-build-isolation 避免下载；
:: 该模式要求本机已有 setuptools>=61 与 wheel）
python -m pip install -e . --no-build-isolation
python -m vcct.cli version
:: 已在无 tkinter 的 Python 3.13 上实测：import vcct.core 不会加载 tkinter

:: 开发期工具
python -m unittest discover -s tests
python -m ruff check vc_cheat_typer.py vcct/ tools/
```

数据目录：`--portable`（默认，exe 旁）/ `--userdata`（`%LOCALAPPDATA%\VC-Cheat-Typer`）。
模式写在 exe 旁 `path-mode.txt`，切换只影响下次启动；配置搬运必须显式复制且不覆盖。

## 5. 构建与发布

```bat
powershell -ExecutionPolicy Bypass -File build.ps1 -OneDir
python tools/build_docs.py
```

`build.ps1` 依次跑单测 + ruff + PyInstaller（onefile / onedir / console CLI），
生成各自的 SHA256 清单。发布纪律见 `docs/ROADMAP-1.7-2.0.md` §6.3：
tag `vX.Y` → Release 名称 `VC-Cheat-Typer vX.Y` → 资产 exe + SHA256.txt，
说明里固定写清"覆盖升级 / 回退需保留旧 exe + 备份"。

## 6. PR 规则

- 一个 PR 只做一件事；结构性改动必须同时补单测与 GUI 冒烟覆盖。
- 新增设置项进 `DEFAULT_SETTINGS` 白名单，并给 `to_v2()` 的剥离语义写测试。
- 新增对话框调用 `bind_dialog_keys(...)`（统一 Esc 关闭 + 语言后处理）。
- 新增界面文案往 `vcct/i18n.py::EN_TEXT` 加映射；日志 / 诊断 / 异常文本保持中文。
- 不引入任何运行时第三方依赖；不新增网络请求（更新入口只允许 `webbrowser.open`）。

## 7. 明确不做（Out of Scope）

界面框架重写（Qt / Web UI）、内存修改器 / DLL 注入、自动更新下载、遥测 / 云同步 /
账号体系、代码签名、联机支持、宏录制 / 连招序列 / 定时循环。理由见路线图 §9。
