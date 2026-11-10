# v2.1 执行方案（P1 收尾，已完成）

> 基线：v2.0（tag `v2.0`，commit `c07c539`）
> 路线图 `docs/ROADMAP-1.7-2.0.md` 只规划到 v2.0，本版 = 剩余的 P1 可选项（2.0-I~L）
> + 兑现 v2.0 未落地的工程承诺。

## 关键假设

1. **版本定位**：v2.0 已把全部必做做完，v2.1 不开新架构层、不升配置版本（仍 v3）、
   不改包格式、不改任何默认行为；只做「补齐 + 修复」。
2. **2.0-K 的"不联网"口径**：跨版本不变量写的是「不读写游戏内存、不联网」。
   因此更新入口**只调用 `webbrowser.open` 把 Release 页交给系统浏览器**，
   程序自身不发起任何网络请求、不下载、不解析版本，且默认关闭。
   AST 测试禁止 urllib / requests / socket / http.client 出现在这个函数里。
3. **2.0-J 的覆盖边界**：i18n 覆盖可见控件与菜单；**日志、诊断、异常文本保留中文**——
   译文会掩盖排查线索。语言切换写 `settings.locale`，重启生效（重建控件比运行时
   逐个改更可靠，也不动 Tab 顺序），提供一键重启。
4. **2.0-I 不自动搬运配置**：模式存 exe 旁独立 `path-mode.txt`，避免"读配置前先知道
   配置在哪"的循环依赖；切换只影响下次启动，复制是显式操作且拒绝覆盖、不删原文件。
5. **2.0-L 不做 PyPI 发布**：只让 `pip install -e .` / `vcct` 命令真正成立、写清架构约束。
   上传 PyPI 需要长期维护承诺与对外发布动作，属 Out of Scope，留给真有人复用时再说。
6. **2.1-D 的必要性**：GUI 子系统（`console=False`）exe 在交互控制台看不到 stdout，
   故新增 `console=True` 的独立 CLI exe，而不是改主 exe 的形态。

## 落点

| 编号 | 文件 |
|---|---|
| 2.0-I | `vcct/paths.py`（新增）、`vcct/loggingx.py`（复用 data_root）、`vc_cheat_typer.py`（`--portable`/`--userdata`、设置页数据目录面板、`relaunch()`） |
| 2.0-J | `vcct/i18n.py`（新增）、`vcct/const.py`（`locale`）、`vc_cheat_typer.py`（`_build_ui` 末尾套用、`bind_dialog_keys` 后处理、设置页语言组合框） |
| 2.0-K | `vcct/const.py`（`check_updates`）、`vc_cheat_typer.py`（`check_updates()` + 菜单项，默认关闭） |
| 2.0-L | `pyproject.toml`（重写：build-system / scripts / packages / version 对齐）、`CONTRIBUTING.md`（新增） |
| 2.1-D | `cli_entry.py`、`VC-Cheat-Typer-cli.spec`、`build.ps1`（第三个产物 + SHA256） |
| 测试 | `tests/test_v2_1.py`（21 条）、`tests/test_v2_core.py`（版本断言改动态） |

## 兼容性

- 配置 v3 不变；新设置项 `locale` / `check_updates` 缺省 = 中文 / 关闭；旧配置读到自动补默认值
- `data_path()` 默认仍指向 exe 旁，1.6～2.0 用户升级零感知
- `.vcpack` 格式、`pack_version`、发送策略与目标规则行为全部不变
- `pyproject.toml` 版本号从陈旧的 `1.5.0` 校正为 `2.1.0`，与 `APP_VER` 一致（测试守着）

## 本版额外修掉的真 bug（开发过程中由 `-X faulthandler` 抓到）

| 问题 | 根因 | 修复 |
|---|---|---|
| 完整测试套件中途 **Windows access violation / rc=127** | 托盘固定窗口类名 `VCCT_TrayWnd`：第二个实例 `RegisterClassW` 报 1410 后继续用旧类，旧类 `lpfnWndProc` 指向已回收回调；同时自建 WinDLL 的大多数函数没声明 64 位签名，句柄被截断 | 每实例唯一类名、退出时 `DestroyWindow` + `UnregisterClassW`；补齐全部 argtypes/restype；`close()` 短等 `_tid`。修后 208 条测试 0 次 AV |
| `pip install -e .` 实际失败 | `pyproject.toml` 停留在 `version=1.5.0`、缺 `[build-system]`；`--no-build-isolation` 下还缺 `wheel` | 重写元数据；在无 tkinter 的 3.13（自带 setuptools+wheel）实测通过 |

## 验证

- `python -m unittest discover -s tests` → **208 条通过**（2 条环境跳过，新增 24）
- `python -X faulthandler -m unittest discover -s tests` → **0 次 access violation**
- `ruff check vc_cheat_typer.py vcct/ tools/ cli_entry.py` → 0 告警
- `--selftest` 全部通过（新增 `[2h]` 段：数据模式 / i18n / 设置项）
- `pip install -e . --no-build-isolation` 在**无 tkinter 的 Python 3.13** 实测成功；
  从项目外 `import vcct.core` 成功且 `tkinter not in sys.modules`；`vcct version` 可用
- `build.ps1 -OneDir` 实测三产物（onefile / onedir zip / console CLI）+ 各自 SHA256
- 三产物 exe 自检 / `sha256sum -c` 校验通过；CI 3.10 / 3.12 双绿

## 待真机验证

切换 `userdata` 后重启是否确实读写新目录（含日志）、复制配置后数据一致、
英文模式下各弹窗与菜单文案、一键重启、`VC-Cheat-Typer-cli.exe` 在 `cmd` 里直接可见输出、
更新入口点击只开浏览器不联网。

## 仍不做（Out of Scope）

macOS 后端（`docs/MACOS-PORT.md` 暂缓）、自动更新下载、遥测 / 云同步 / 账号、
代码签名、界面框架重写、宏录制 / 定时循环、PyPI 正式发布。
