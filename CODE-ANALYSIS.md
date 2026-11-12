# VC-Cheat-Typer 代码结构说明与功能分析报告

> 分析对象：`vc_cheat_typer.py`（3,946 行 / 201 KB / 11 个类）+ `vcct/` 包（23 个模块 / 约 3,690 行）+ `tests/`（14 个文件 / 228 个用例）+ 构建与文档脚本。
> 分析方法：逐模块通读 + 关键路径交叉验证（GUI 调用点 ↔ core 纯函数 ↔ 持久化白名单 ↔ 测试断言）。
> 结论先行：这是一个"零第三方依赖、Win32 原生注入、双层架构（v1 单体 GUI + v2.x 可复用 core）"的桌面工具；工程化程度明显高于同类小工具，但 v2.0 引入的"发送策略"在 GUI 链路上存在**两处断链**，导致该特性实际不可用（详见 §6.1 / §6.2）。

---

## 一、项目定位与规模

| 维度 | 事实 |
|---|---|
| 产品形态 | Windows 桌面 GUI（Tkinter）+ 命令行（`vcct`）+ PyInstaller 单文件/单目录产物 |
| 核心能力 | 全局热键触发 → 向游戏窗口注入键盘字符序列（秘籍代码），带前台校验、IME 规避、权限拦截识别 |
| 技术栈 | Python ≥ 3.8；运行时零依赖（仅标准库 + `ctypes` 调 user32/kernel32/imm32） |
| 版本 | `2.2.0`（`vcct/const.py`），配置 schema `STORE_VERSION = 3` |
| 入口 | `vc_cheat_typer.py:main()`（GUI / 自检 / 诊断 / `--cli` 转发）；`vcct/cli.py:main()`（控制台脚本 `vcct`） |
| 代码规模 | 单体 3,946 行；包 3,690 行；测试 228 个用例 |
| 质量闸门 | `.github/workflows/ci.yml`：ruff（仅主文件）+ `py_compile` + `unittest discover`，Windows × Python 3.10/3.12 |

---

## 二、整体架构

### 2.1 分层视图

```
┌──────────────────────────────────────────────────────────────────────┐
│ 表现层                                                                 │
│  vc_cheat_typer.py  CheatApp(105 方法) + 10 个 Toplevel 对话框          │
│  vcct/ui/  theme(设计令牌/对比度) · components · shell(NovaShell)       │
│            commands(命令面板/注册表)                                    │
├──────────────────────────────────────────────────────────────────────┤
│ 编排层（业务规则，全部可单测）                                           │
│  vcct/core/  strategy(发送策略) · targets(目标规则) · hooks(扩展点)      │
│  vcct/hotkeys.py(绑定表/冲突/候选键池)                                  │
│  vcct/packs.py(秘籍包) · vcct/importer.py(文本导入) · vcct/templates.py  │
├──────────────────────────────────────────────────────────────────────┤
│ 能力层                                                                 │
│  vcct/sender.py(可中断打字引擎，纯注入)  vcct/winapi.py(SendInput/窗口/  │
│  提权/IME/探针/DPI)  vcct/tray.py(托盘线程)  vcct/i18n.py               │
├──────────────────────────────────────────────────────────────────────┤
│ 数据层                                                                 │
│  vcct/store.py(加载/迁移/归一化/备份/整包)  vcct/paths.py(便携/用户目录) │
│  vcct/loggingx.py(日志轮转/崩溃钩子)  vcct/const.py(默认值/配色/预设)    │
└──────────────────────────────────────────────────────────────────────┘
```

### 2.2 依赖方向（实测）

- **数据层不依赖 Tk**：`tests/test_structure.py` 用 AST 断言 `store/packs/sender` 不 import tkinter，`sender.py` 不 import winapi（键码由 `lookup_vk` 注入）。
- **core 不依赖平台**：`strategy/targets/hooks` 只做纯函数/纯数据结构，Win32 动作通过工厂 `make_switch_window_hook(get_hwnd, activate, ...)` 注入。
- **UI → core 单向**：`vc_cheat_typer.py` 通过 `if IS_WIN:` 兼容块集中导入 `vcct.*`（约 95 行位置），自身不反向被包依赖。
- **唯一的"反向"依赖**：`vcct/ui/theme.py:apply_theme()` 原地改写 `vcct.const.C`，让单体里上百处 `C["..."]` 引用自动跟随主题（见 §6.3 的代价）。

### 2.3 模块速查表

| 文件 | 行数 | 关键符号 | 职责 |
|---|---:|---|---|
| `vcct/const.py` | 58 | `DEFAULT_SETTINGS` / `PRESETS` / `C` / `PAUSE_ID` | 全局默认值、配色、虚拟热键 id |
| `vcct/paths.py` | 109 | `data_path` / `set_data_mode` / `copy_config_to` / `describe` | 便携 vs `%APPDATA%` 双数据目录、可写性探测 |
| `vcct/store.py` | 521 | `load_store` / `save_store` / `normalize_store` / `migrate_*` / `parse_bundle` | v1→v3 迁移、白名单归一化、备份/隔离、v2 导出 |
| `vcct/loggingx.py` | 106 | `append_log` / `install_crash_hooks` / `log_file` | 1 MB × 3 轮转、`sys.excepthook`/`threading.excepthook` |
| `vcct/winapi.py` | 559 | `send_key` / `vk_for_char` / `ImeGuard` / `find_game_window` / `raw_char_probe` / `process_elevated` | 全部 Win32 封装与探测 |
| `vcct/sender.py` | 145 | `SendParams` / `type_text` / `SendCancelled` / `SendError` | 可中断、可注入、无残留按键的打字循环 |
| `vcct/hotkeys.py` | 208 | `HotkeyEngine` / `build_bindings` / `candidate_combos` / `pick_free_combo` | 专用消息泵线程注册全局热键、冲突检测与改键 |
| `vcct/tray.py` | 301 | `TrayIcon` / `_NOTIFYICONDATAW` | 独立线程 + 隐藏窗口 + 弹出菜单 + Explorer 重启自愈 |
| `vcct/i18n.py` | 237 | `t` / `set_locale` / `apply_locale_to_widgets` / `_DYNAMIC` | 以中文原文为 key 的词典 + 动态正则翻译 |
| `vcct/packs.py` | 254 | `make_pack` / `validate_pack` / `diff_pack` / `merge_pack` / `auto_avoid_hotkeys` | 秘籍包签名、校验、差异合并、热键避让 |
| `vcct/importer.py` | 80 | `parse_pasted` | 粘贴文本 → 秘籍条目 |
| `vcct/templates.py` | 117 | `TEMPLATE_NAMES` / `template_cheats` / `template_preset` | 4 套游戏模板（VC 经典/决定版/GTA3/SA） |
| `vcct/cli.py` | 159 | `cmd_*` / `build_parser` | 7 个子命令；`send` 默认 dry-run |
| `vcct/core/strategy.py` | 103 | `SendStrategy` / `plan_send` / `should_retry` / `resolve_strategy` | fixed/burst/adaptive 三策略，纯函数 |
| `vcct/core/targets.py` | 113 | `Target` / `evaluate_targets` / `resolve_target` / `targets_from_games` | exe/title/class 规则 → 方案/策略/IME/前台 |
| `vcct/core/hooks.py` | 84 | `HookBus` / `make_switch_window_hook` | 前置可否决、后置必执行、异常隔离 |
| `vcct/ui/theme.py` | 97 | `Tokens` / `apply_theme` / `contrast_ratio` / `check_contrast` | 设计令牌、密度换算、WCAG 对比度自检 |
| `vcct/ui/shell.py` | 107 | `NovaShell` / `NAV_ITEMS` / `refresh_theme` | 顶栏/侧栏/状态中心/内容宿主 |
| `vcct/ui/commands.py` | 155 | `Command` / `CommandRegistry` / `CommandPalette` | 子序列模糊搜索的命令面板 |
| `vc_cheat_typer.py` | 3946 | `CheatApp` + 10 对话框 + `selftest` / `diagnose_report` / `main` | 全部 GUI 编排与旧版兼容层 |

---

## 三、核心功能模块划分

### 3.1 数据与配置（store / paths / loggingx）

- **双数据模式**：`paths.data_path()` 依据 `path-mode.txt` 在"exe 同目录（portable）"与 `%APPDATA%\VC-Cheat-Typer` 间切换；`copy_config_to` 负责迁移配置。`--portable` / `--userdata` 在 `main()` **任何配置/日志访问之前**处理（`vc_cheat_typer.py:3885-3889`）。
- **三层数据安全**：
  1. 迁移前备份：`backup_before_migration` 保留 v1/v2 原件；
  2. 损坏隔离：`quarantine_corrupt` 把无法解析的文件改名保留，载入默认并弹窗告知；
  3. 防降级：读到 `version > STORE_VERSION` 时置 `_FORBID_DEFAULT_SAVE=True`，此后 `save_store` 拒绝写默认路径，避免旧程序覆盖新配置。
- **白名单归一化**：`normalize_store` 用 `dict(DEFAULT_SETTINGS)` 合并设置，未知键丢弃；`_norm_*` 对 stats/today/games/packs/ui/history/targets/strategies 逐条清洗；方案名自动去重、`active_profile` 不存在时回落首项。
- **保存策略**：`tmp → 复制旧文件为 .bak → os.replace`，原子替换；失败仅记日志不抛异常（`store.py:519-531`）。没有 `fsync`，断电极端场景可能丢最后一次写。

### 3.2 输入注入（sender + winapi）

- `SendParams`（frozen dataclass）：`code / interval_ms / hold_ms / pre_delay_ms / uppercase`；`for_code()` 把 hold 规则收敛为"间隔一半，夹在 8~60ms"。
- `type_text()` 的契约（`sender.py:118-183`）：
  - `pre_delay` 也可中断；
  - 每字符：停止检查 → 目标焦点检查 → `lookup_vk` → 按下 → 保持（可中断）→ **`finally` 抬起** → 计数/回调 → `interval - hold` 睡眠；
  - 任何异常路径都保证不留按下键，含 `uppercase` 模式的左 Shift；
  - 输出了 `SendCancelled(sent,total)` / `SendError` 两类可诊断异常。
- `winapi`：
  - `_key_item` 统一走 **扫描码**（`MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)` + `KEYEVENTF_SCANCODE`），对 DirectInput 类游戏更稳；
  - `_send` 用 `SendInput` 且校验返回值，不足即 `OSError(last_error)`；
  - `release_modifiers` 兜底松开 Ctrl/Shift/Win（发送前防止"变速跑"，退出前防止角色一直跑）；
  - `ImeGuard`：发送期间 `ImmAssociateContext(hwnd, NULL)` 摘掉输入法，结束后恢复，失败降级不阻断；
  - `find_game_window`：`EnumWindows` + 进程名白名单（`gta-vc.exe` 等）+ 标题含 "Vice City"，跳过自身进程；
  - `raw_char_probe`：注册临时窗口类 + 自建消息泵，注入 "VCCT" 并校验回读，用于 `--diagnose`；
  - `process_elevated` / `self_elevated`：`OpenProcessToken + GetTokenInformation(TokenElevation)`，识别 **UIPI 静默拦截**（本工具非管理员、游戏是管理员）。

### 3.3 热键子系统（hotkeys）

- `HotkeyEngine` 启动专用 `hotkey-pump` 线程：`GetCurrentThreadId` → `PeekMessageW` 强制建队列 → `GetMessageW` 循环；主线程通过 `PostThreadMessageW(WM_APP_RELOAD)` 唤醒重注册（`WM_HOTKEY` 只投递到注册线程）。
- `build_bindings()` 产出 `[(hotkey_id, mods, vk, owner)]`：暂停键固定 `PAUSE_HID=9000`，秘籍键 1..N 顺延；同键重复、与暂停键冲突、无法解析的组合都会进 `conflicts`。
- `is_safe_binding` 只允许"带修饰键"或 F1–F24（避开 F12 的调试占用），避免裸字母被游戏当成打字吞掉。
- 冲突自愈：`_on_hotkeys_applied` 把系统占用（1409）/权限不足（5）分类记录，`_assign_free_combos` 用 `candidate_combos + pick_free_combo` 换键，最多 2 轮，且把"真的被占用"的键累积进 `_avoid` 避免原地打转。

### 3.4 发送策略与目标规则（core）

- `SendStrategy` 只暴露 5 个参数，`normalize_strategy` 全部夹取范围；`fixed` 默认与 1.9.1 逐项一致。
- `plan_send(strategy, code, base_interval, base_pre, uppercase, attempt)`：`burst` 把间隔压到 ≤20ms、hold ≤12ms；`adaptive` 在 `attempt>0` 时间隔 `+15ms/次`、hold `+5ms/次`，且重试不再重复 pre_delay。
- `should_retry`：仅 `adaptive` 且 `sent < total` 且 `attempt < retries`。
- `Target`：`match_type ∈ {exe,title,class}`、`ime_policy ∈ {disable,keep}`、`strategy_ref`、`profile_ref`、`enabled`；`resolve_target` 把不存在的方案/策略名回落空串，保证"缺省即旧行为"。

### 3.5 内容生态（packs / importer / templates）

- 包格式 `vcct-pack` v1：`pack_signature` 对"去掉 sha256 字段的规范化 JSON"取 SHA-256，改包可检测但不做密码学签名（文档明确是"防手滑"而非"防篡改"）。
- `validate_pack` 校验格式/版本/`app`/秘籍字段/重复代码/`min_app`；`diff_pack` 分类 `new / changed / same / local_only`；`merge_pack` 只合并选中项，覆盖时保留本地 `id`；`compare_pack_record` 判定 `new / upgrade / changed / same`。
- `auto_avoid_hotkeys` 在导入前把与本地冲突的键换成空闲键（含包内自重复），并预留暂停键。
- `importer.parse_pasted` 支持"名称, 代码, 热键"等分隔行，`CODE_RE = ^[A-Z0-9]+$`。

### 3.6 表现层（ui/ + 单体 GUI）

- **双 UI 形态**：`ui_mode=nova` 时 `NovaShell` 先占底栏状态中心与顶栏，再放可伸缩 body + 侧栏 5 个导航（秘籍/热键/内容/数据/帮助）；`classic` 时完全不创建 shell，原控件树直接挂 `root`，实现"一键回退到 1.7~2.1"。
- **主题令牌**：`Tokens(theme,density,colors,spacing,fonts)` 支持 `space()/font()` 与紧凑密度系数 0.72；`check_contrast` 用相对亮度做 WCAG 4.5:1 自检。
- **命令面板**：`CommandRegistry` 支持标题/别名子序列匹配（`_subsequence`），`CommandPalette` 为独立 Toplevel；默认注册 23 个命令（秘籍增删改/发送/停止、暂停热键、重注册、快捷键总览、包管理、粘贴导入、模板、整包导入导出、历史、设置、清统计、日志目录、诊断、向导、注入自检、管理员重启、检查更新）。
- **单体 GUI 的 11 个类**：`HotkeyCapture`(键位捕获)、`CheatDialog`(增改秘籍，`^[A-Z0-9]{2,40}$` 校验)、`GameRuleDialog`、`SettingsDialog`(4 页：常规/输入/游戏/数据)、`OnboardWizard`、`HotkeyOverview`、`PackManagerDialog`、`TextImportDialog`、`TemplateDialog`、`HistoryDialog`，以及编排中心 `CheatApp`。
- **线程纪律**：工作线程**只写 `queue.Queue`**，绝不碰 Tk/store；主线程 `after(40ms)` 的 `_pump` 统一消费 `log/status/toast/stats/hotkey/hotkeys/tray/history/send_done/probe_done/diag_done`（`vc_cheat_typer.py:2008-2040`）。

### 3.7 CLI

`vcct/cli.py`：`version / list / targets / strategies / pack info / send / export-v2`。`send` 默认只预演（打印计划参数），必须 `--execute` 才注入；复用 `resolve_target/resolve_strategy/plan_send/type_text`，因此 CLI 与 GUI 共享同一发送引擎（但注意 §6.1 的 GUI 侧断链）。

---

## 四、主要执行流程

### 4.1 启动引导

```
argv 解析
 ├ --userdata / --portable  → set_data_mode（必须先于任何配置/日志访问）
 ├ --classic-ui / --nova-ui → 本次进程强制 UI 形态（不写回配置）
 ├ --diagnose / --selftest / --cli / --export-v2 → 各自分支后退出
 └ 否则进入 GUI：
    install_crash_hooks → 写启动日志
    → CreateMutexW("Local\\VC_Cheat_Typer_SingleInstance")，ERROR_ALREADY_EXISTS=183 则提示并退出
    → enable_dpi_awareness()（必须在 tk.Tk() 之前）
    → tk.Tk() → 可选 VCCT_UI_SCALE 缩放 → CheatApp(root) → mainloop
```

`CheatApp.__init__` 顺序（`vc_cheat_typer.py:1628-1711`）：

1. `load_store()` → `settings/stats/active_profile/cheats`（`cheats` 是 store 内列表的**引用**，增删改即时一致）；
2. 运行态：`sending=Lock`、`_stop=Event`、`_inflight`、去抖表、托盘提示位、`_active_target`、`HookBus(enabled=False)`；
3. `set_locale` → UI 形态/主题/密度 → `apply_theme()` 原地改 `const.C` → `_make_vars()`（Tk 变量与控件解耦）；
4. `_setup_style()`（clam + 全量 ttk 样式；`reset_geometry=False` 时不动窗口几何）→ `_build_ui()`（Nova 套壳或经典直挂）→ `refresh_tree()`；
5. `HotkeyEngine(events)` → `apply_hotkeys()`；
6. `after(40, _pump)` / `after(500, _poll_foreign_foreground)` / `after(1500, _update_game_status)`（此后 3s 自循环）；
7. `TrayIcon(...)`（失败则 `available=False`，自动回落"关闭即退出"）；
8. 未完成首次向导则 `after(800, open_wizard)`。

### 4.2 热键注册时序

```
主线程                        hotkey-pump 线程
apply_hotkeys()
  build_bindings(cheats, pause, include_cheats=not paused)
  engine.apply(bindings) ──存 _pending + PostThreadMessage(WM_APP_RELOAD)──▶ _do_apply()
                                                              全部 UnregisterHotKey
                                                              逐条 RegisterHotKey(MOD_NOREPEAT)
                                                              events.put(("hotkeys", results, id_map))
_pump 消费 ◀──────────────────────────────────────────────────┘
  conflicts 分类（占用 1409 / 权限 5 / 其他）
  refresh_tree() 标红 + 日志
  若本轮是自动分配且仍被占用 → after(10) 再换一批（≤2 轮）
```

暂停时 `include_cheats=False`，只注册暂停键；`toggle_pause()` 先 `self._stop.set()` 中止在飞发送，再重注册，语义是"立刻停手"。

### 4.3 单次发送（核心路径）

```
用户 Enter / 双击 / 全局热键 / 托盘 / 命令面板
        │
_start_send(cheat, force, from_hotkey)          [主线程]
  ├ 去抖：同 id 在 debounce_ms(250) 内重复 → 忽略并记日志
  ├ sending.acquire(blocking=False) 失败 → "上一次未结束"双通道提示（日志 + 悬浮）
  ├ _last_send[cid]=now；_stop.clear()
  ├ params = _read_params(force)      ← 唯一允许读 Tk 变量的地方（主线程快照）
  └ Thread(_send_worker).start()；线程启动失败必须 release 锁
        │
_send_worker(cheat, params)                    [工作线程]
  ├ 权限实时复核 _permission_mismatch_live() → UIPI 风险直接失败并解释
  ├ check_fg 且 _fg_ok(keywords) 为假 → 记录当前前台标题，拒发
  ├ hooks.fire_before({hwnd}, cheat) 返回 False → 否决
  ├ release_modifiers()（防止触发时按着 Ctrl → 游戏"变速跑"）
  ├ with ImeGuard(target_hwnd, disable_ime):
  │    attempt = 0
  │    while True:
  │      sp = plan_send(strategy, code[sent_total:], interval, pre, uppercase, attempt)
  │      try: sent_total += type_text(sp, _stop, send_key, sleep, vk_for_char,
  │                                  check_target=前台仍是发起时窗口)
  │      except SendError as e:
  │          sent_total += e.sent
  │          if not should_retry(...): raise
  │          attempt += 1（adaptive 自动加长间隔，重试剩余字符）
  └ 成功：质量日志(planned vs actual/dev) → 日志 → toast → "stats" → "history"
    取消：SendCancelled → 记录停在第几字
    失败：SendError / OSError / Exception 分类落盘
    finally：events.put(("send_done", cid)) → sending.release() → hooks.fire_after(...)
        │
_pump 收到 stats/history → 更新统计、最近使用、写历史（各触发一次 persist）
```

### 4.4 自动切方案

`_update_game_status` 每 3s：检测游戏窗口/权限 → 更新头部状态 → `_auto_switch_tick()` → `_refresh_nova_status()`。

`_auto_switch_tick`（`vc_cheat_typer.py:2108-2165`）：

1. `auto_switch` 关闭 / 无 `targets` 且无 `games` / 正在发送 → 直接返回（发送中绝不切，硬约束）；
2. 有 `targets`：`evaluate_targets(title, exe)` → `resolve_target`（方案/策略/IME/前台）；
3. 否则走 1.8 `evaluate_game_rules`；
4. 同一 `(规则名, 方案名)` 稳定 ≥800ms 才切（Alt+Tab 掠过不触发）；
5. 方案不存在 → 每条规则只警告一次并跳过。

### 4.5 配置生命周期

```
load_store(path)
  ├ 文件不存在 → default_store() + save_store()
  ├ JSON 解析失败 → quarantine_corrupt() → 默认数据 + LAST_LOAD_WARNING
  ├ 顶层非对象 → 同上
  ├ version > 3 → 默认数据 + 禁止回写默认路径（_FORBID_DEFAULT_SAVE）
  ├ version < 3 → backup_before_migration() → normalize_store()
  └ 其它       → normalize_store()

persist()（GUI 每次修改/发送统计/历史都调用）
  store["settings"]=settings；store["stats"]=stats；store["active_profile"]=...
  → save_store：settings 白名单 + targets/strategies/games/packs/ui/history 归一化
  → tmp 写入 → 旧文件复制为 .bak → os.replace
```

### 4.6 秘籍包导入

`PackManagerDialog`：选文件 → `validate_pack`（格式/版本/签名/重复代码/min_app）→ `compare_pack_record`（新包/升级/内容变更/相同）→ 展示 `diff_pack` 差异勾选 → `merge_pack`（只并选中、覆盖保留本地 id）→ `pack_record` 写入 `store["packs"]`。导入前可选 `auto_avoid_hotkeys` 自动改冲突键。

### 4.7 CLI

`main(argv)` → `argparse` 子命令 → `_store()` 每次重新 `load_store`（无缓存）→ 输出文本。`send` 未带 `--execute` 只打印 `describe_plan` 结果，属于安全默认。

---

## 五、关键逻辑实现细节

| 主题 | 实现要点 | 位置 |
|---|---|---|
| 按键注入 | 扫描码而非 VK，单键单次 `SendInput`，失败带 `last_error` | `winapi.py:241-261` |
| 帧率适配 | `hold` 必须大于游戏帧间隔；默认取 `interval/2` 夹 8~60ms | `sender.py:62-64` |
| 可中断性 | 所有睡眠按 ≤20ms 切片，每片前检查 `stop`；`pre_delay` 同样可中断 | `sender.py:104-115` |
| 无残留键 | 抬起放 `finally`；`release_modifiers` 三处兜底 | `sender.py:167-183`、`winapi.py:268-278` |
| UIPI 识别 | 令牌提权对比；发送前实时复核，避免 UI 3s 缓存过期 | `winapi.py:604-641`、`vc_cheat_typer.py:2177-2187` |
| 前台校验 | 游戏窗口自动命中优先于关键字；测试窗口 `test_hwnd` 豁免 | `vc_cheat_typer.py:2608-2616` |
| IME 吞字 | `ImmGetContext/ImmAssociateContext` 临时摘除并恢复 | `winapi.py:392-418` |
| 热键安全池 | F1–F24 裸键安全，避开 F12；其余必须带修饰键 | `hotkeys.py:67-75`、`200-216` |
| 单实例 | 命名互斥体 + `ERROR_ALREADY_EXISTS`，避免抢同一批全局热键 | `vc_cheat_typer.py:3921-3929` |
| 主题 | 令牌 + `apply_theme` 原地改 `const.C` + WCAG 对比度自检 | `ui/theme.py:57-115` |
| i18n | 中文原文作 key；`_DYNAMIC` 处理带变量的句子；切换后重启生效 | `i18n.py:21-237` |
| 迁移链 | 纯函数 `v1→v2→v3`，逐级可测，`StoreTooNew` 显式异常 | `store.py:178-232` |
| 包签名 | 规范化 JSON（去 sha）取 SHA-256，防手滑不防篡改 | `packs.py:76-103` |
| 日志 | 1 MB × 保留 3 份；崩溃钩子注入对话框实现，core 不依赖 tkinter | `loggingx.py:24-106` |

---

## 六、潜在问题与风险

> 严重度：**高** = 功能不可用/数据风险；**中** = 行为与文档不符或可观测错误；**低** = 可维护性/边界健壮性。

### 6.1【高】GUI 读取策略表的位置错误，具名策略与 `strategy_ref` 实际永不生效

- 证据：`vc_cheat_typer.py:2723` 读取 `named = self.settings.get("strategies")`；
  而配置中策略表存放在**顶层**：`store.py:394`、`store.py:517`（`"strategies": _norm_strategies(...)`）。
- 放大因素：`save_store` 对 settings 做白名单过滤（`store.py:503`，键集仅来自 `DEFAULT_SETTINGS`），因此 `settings["strategies"]` 即使被临时写入也不会持久化。
- 后果：`ref in named` 恒为 False，`target.strategy_ref` 解析出的策略在 GUI 发送时被丢弃；GUI 永远走 `fixed` 默认（除非 cheats 里带策略，见 6.2，而它也会被丢）。
- 影响面：2.0 宣传的 `adaptive`（丢字自动加长间隔并续发）在 GUI 中完全不可达；CLI 路径正常（`cli.py:116` 用的是 `store.get("strategies")`）。
- 修复：改为 `named = self.store.get("strategies") or {}`；或在 `_send_worker` 前把 `store["strategies"]` 显式传入参数（工作线程不碰 store 的原则下更推荐后者）。

### 6.2【高】秘籍级策略字段在加载时被白名单丢弃（保存/加载不对称）

- 证据：`store._norm_cheat` 返回的字典只含 `id/name/code/hotkey/group/note/interval_ms/verified/game/source_pack`（`store.py:74-93`），**不含** `strategy` / `strategy_ref`；
  而 `core/strategy.resolve_strategy` 明确读取这两个字段（`strategy.py:79-88`）。
- 另一侧不对称：`save_store` 写 `profiles: store.get("profiles", [])` 原样落盘（`store.py:509`），不做归一化。也就是说运行期塞进去的 `strategy` 会写进文件，但下次启动被读丢——形成"看起来保存了、重启就消失"的错觉。
- 修复：schemas 统一（见 §7.2），`_norm_cheat` 增加 `"strategy": normalize_strategy(item.get("strategy")) if ... else None`，并让 `save_store` 也走 `_norm_cheat`。

### 6.3【中】主题"即时切换"只覆盖 ttk 样式，经典 tk 控件仍是旧配色

- 证据：`toggle_theme` 仅执行 `apply_theme` + `_setup_style(reset_geometry=False)` + `shell.refresh_theme`（`vc_cheat_typer.py:3376-3387`）；
  但工具条 `tk.Frame(bg=C["panel"])`、搜索框 `tk.Entry(bg="#ffffff")`、日志 `tk.Text` 等颜色在 `_build_ui` 时已固化（`vc_cheat_typer.py:1824-1852`）。
- 硬编码放大：主文件共 **68 处、30 种**十六进制颜色；`_setup_style` 里 `Treeview.Heading` 固定 `#eef1f6/#374151`、选中行固定 `#dbe7ff`、`Accent.TButton` map 固定 `#1d4ed8/#1e40af`（`vc_cheat_typer.py:1774-1786`），不随 dark 主题变化。
- 后果：深色主题下会出现"深色背景 + 白色工具条 / 浅色表头"的割裂；Nova 外壳自身因 `_remember(widget, option, token)` 机制能正确换肤，内容区不能。
- 修复方向：为内容区建立同样的 `(widget, option, token_key)` 注册表并在 `toggle_theme` 遍历重设；或把残留 `tk.*` 控件逐步换成 ttk。

### 6.4【中】有 `targets` 时不再回落到 `games`，与文档描述不一致

- 证据：`vc_cheat_typer.py:2127-2136`，`if targets:` 命中失败即 `self._active_target=None; return`，不会继续 `evaluate_game_rules`。
- 文档口径：`docs/PLAN-2.0.md` 2.0-C 写的是"优先 targets、回落 games"。
- 后果：同时配置了两套规则的用户，旧 `games` 规则会静默失效（只在日志外无提示）。
- 修复：任选其一——命中失败后继续尝试 games，或在设置页明确提示"targets 存在时 games 仅作迁移来源"。

### 6.5【中】诊断报告展示的 UI 形态/主题是默认值而非实际值

- 证据：`vc_cheat_typer.py:3817` 使用 `DEFAULT_SETTINGS.get('ui_mode')` / `('theme')`，而同函数下方 3836 行才 `load_store()` 取真实设置。
- 后果：用户报障时诊断输出恒为 `nova / theme=light`，误导排查。
- 修复：改为 `settings.get('ui_mode')` / `settings.get('theme')`（把 `load_store` 提前）。

### 6.6【中】"配置来自更高版本"后所有编辑静默丢弃

- 证据：`load_store` 置 `_FORBID_DEFAULT_SAVE=True`（`store.py:487-489`），`save_store` 直接 `return`（`store.py:499-501`），此时 GUI 的 `persist()` 无任何反馈。
- 后果：用户在只读模式下的新增/改键/设置全部"看起来成功、重启消失"，仅启动时弹过一次窗。
- 修复：`save_store` 返回 bool，`persist()` 在失败时置状态位并在底部状态中心/首次编辑时提示"当前为只读模式"。

### 6.7【低】发送质量日志的 planned 与实际口径不一致

- 证据：重试循环里 `sp` 是"剩余字符"的计划（`vc_cheat_typer.py:2781`），而 `_log_send_quality` 用 `sp.pre_delay_ms + total * sp.interval_ms` 与**整段**实际耗时比较（`vc_cheat_typer.py:2840-2846`）。
- 后果：发生过 adaptive 重试时 `dev` 偏差被系统性放大，可能误报"节奏偏差"。
- 修复：把累计的 `planned` 在重试时累加，或用 `sent_total` 而非 `total` 计算。

### 6.8【低】重试失败时进度回报偏小

- 证据：`except SendError` 内 `sent_total += exc.sent`，若判定不重试则 `raise`（重新抛出的是本次 `exc`，其 `sent` 只含本轮字符数）（`vc_cheat_typer.py:2792-2797`）；外层 `except SendError` 打印/落盘的是 `exc.sent`（2817-2822）。
- 后果：多重试轮次的失败日志显示"已发 3/12"而实际已发 10/12。
- 修复：抛出前包装为 `SendError(reason, sent_total, total)`。

### 6.9【低】代码字符集校验只存在于部分入口

- 证据：`CheatDialog` 校验 `^[A-Z0-9]{2,40}$`（`vc_cheat_typer.py:345`）、`packs._norm_pack_cheat` 校验字母数字、`importer.CODE_RE` 校验；但 `store._norm_cheat` 只 `strip().upper()`（`store.py:77`），而"导入方案"走的正是 `_norm_cheat`（`vc_cheat_typer.py:3166`）。
- 后果：含空格/符号的方案可被导入并持久化，直到发送时才 `SendError`。
- 修复：`_norm_cheat` 拒绝不匹配 `^[A-Z0-9]{2,40}$` 的条目（返回 None），保持所有入口同一规则。

### 6.10【低】每次成功发送触发两次全量写盘 + 两次备份复制

- 证据：`_bump_stats` → `persist()`（`vc_cheat_typer.py:2292-2300`）；`_record_history` → `persist()`（`vc_cheat_typer.py:2042-2047`）；`save_store` 每次都会把旧文件 `shutil.copyfile` 成 `.bak` 再 `os.replace`。
- 后果：连发秘籍时是 2×(序列化 + 复制 + 原子替换)，配置越大抖动越明显（历史 50 条、多方案时可达数十 KB）。
- 修复：合并为一次 persist（stats 与 history 同批），或加 200–500ms 节流/空闲合并。

### 6.11【低】单实例互斥体依赖局部变量生命周期

- 证据：`mutex = kernel32.CreateMutexW(...)` 注释说明"句柄必须保持存活"（`vc_cheat_typer.py:3923`）。
- 风险：当前靠 `main()` 栈帧长期存活成立；一旦 `main` 被重构/内联，句柄可能被回收导致互斥失效。
- 修复：挂到模块级变量或 `atexit` 注册关闭，显式表达生命周期。

### 6.12【低】热键引擎就绪等待失败被忽略

- 证据：`HotkeyEngine.__init__` 中 `self._ready.wait(3.0)` 未检查返回值（`hotkeys.py:91`）；若线程异常退出，`thread_id=0`，后续 `apply/_wake` 全部静默 no-op（`hotkeys.py:104-111`）。
- 后果：极端环境下"热键完全没反应且无任何错误提示"。
- 修复：`ready` 超时后向 events 投递 `("hotkeys", {}, {})` 并记录 ERROR。

### 6.13【低】裸 `except: pass` 削弱可观测性

- 证据：`_auto_switch_tick`（`vc_cheat_typer.py:2164-2165`）、`_update_game_status`（2086-2087）、`_bump_stats`（2301-2302）、`show_toast` 等大量 `except Exception: pass`。
- 后果：自动切换、统计、托盘等子系统坏掉时日志无痕，只能靠现象猜。
- 修复：统一 `append_log(..., "ERROR")` 或至少 `loggingx.append_log(traceback...)`，保留一次限流（同一异常只记首次）。

### 6.14【低】架构性：单体仍承载全部 UI 编排

- 事实：`vc_cheat_typer.py` 3,946 行 / 201 KB；`CheatApp` 单类 **105 个方法**，混合了"控件构建 / 事件泵 / 发送编排 / 设置同步 / 持久化 / 批量操作 / 包管理入口"。
- 后果：`tests/test_gui_smoke.py` 只能做"能建能关"的冒烟；发送与设置同步逻辑难以单测；`_on_setting_change` 与 `on_close` 手写同一组 settings↔vars 映射（`3183-3197` vs `3541-3549`），加字段时容易漏。
- 另：`relaunch()` 过滤所有 `--` 参数（`vc_cheat_typer.py:2220`），会丢掉 `--classic-ui` 等会话级开关（数据模式因落盘可保留）。

### 6.15【低】`apply_theme` 改写全局 `const.C` 的隐式耦合

- 证据：`ui/theme.apply_theme` 直接 `const.C.clear(); const.C.update(palette)`（`ui/theme.py:86-95`）。
- 风险：进程内多窗口/测试并发时是共享可变状态；`docstring` 已声明这是刻意取舍（"既有上百处 C[...] 引用自动跟随"），但代价是主题切换无法做到"局部预览"。
- 建议：保留快捷路径，同时给内容区控件建立与 Nova 相同的注册表机制（见 6.3）。

---

## 七、优化建议（按投入产出排序）

### 7.1 先修功能断链（1–2 处改动即可闭环）
1. `_send_worker` 的策略来源改为 store 顶层（或作为 `params` 传入）。
2. `_norm_cheat` 保留 `strategy` / `strategy_ref`，并与 `packs/importer/CheatDialog` 共用同一套字段校验。
3. `diagnose_report` 使用真实 settings。

### 7.2 统一"秘籍条目" schema
当前同一实体有 4 套归一化：`store._norm_cheat`、`packs._norm_pack_cheat`、`importer.parse_pasted`、`CheatDialog` 表单校验。建议抽出 `vcct/schema.py`（TypedDict 或 dataclass + `normalize_cheat()`），所有入口只调它，消除"某入口多/少字段"的长期隐患。

### 7.3 拆分 `CheatApp`
按职责拆成 3 个可测对象：
- `SendController`：去抖、互斥、参数快照、worker、结果回投；
- `SettingsBinder`：settings↔Tk 变量双向映射（含 `_on_setting_change` / `on_close` 去重）；
- `ViewBuilder`：`_build_ui` + 主题重刷注册表。
UI 只留薄壳，`test_gui_smoke` 可升级为 controller 单测。

### 7.4 主题系统补全
建立 `ThemeAware` 注册表（与 `NovaShell._remember` 同构），把内容区 68 处硬编码颜色收拢为令牌；`ttk.Style` 中用 `C[...]` 派生 `heading/selected/accent-active`，避免深色主题下白块。

### 7.5 持久化节流
`persist()` 增加脏标记 + `after(300)` 合并；`_bump_stats` 与 `_record_history` 同批写入；`.bak` 只在配置实质变化时复制（可用内容 hash 判断）。

### 7.6 可观测性
- 发送链路加 `trace` 短 id，`SEND start/ok/fail` 日志带同一 id，便于对照"计划/实际/偏差"。
- 把 `except: pass` 改为限流 ERROR 日志；诊断报告增加"上次发送 trace"摘要。
- `save_store` 返回状态，GUI 只读模式下给出显式提示。

### 7.7 测试补强
- 目前 228 例覆盖纯函数与发送引擎很扎实（`test_sender.py` 用 FakeInput 注入），但 GUI→worker 的参数装配没有测试——恰是 §6.1 漏网之处。建议对 `_read_params` + 策略选择抽成纯函数后补测。
- 增加"保存→加载→保存"的往返测试断言 `strategy` 字段不丢（能直接锁死 6.2）。

---

## 八、技术实现特点与亮点

1. **零依赖、全 ctypes**：不引入 `pywin32/pynput`，`SendInput` 走扫描码，便携性与兼容性好。
2. **关注"静默失败"**：UIPI 拦截、前台不匹配、热键被占用、连击被忽略——四类"看起来没反应"的场景都有专门识别与双通道提示，这是同类工具最常见的用户困惑点。
3. **发送引擎与平台解耦**：`type_text` 只接收 `send_key/sleep/lookup_vk/check_target` 四个回调，单测可完全脱离 Windows。
4. **中断语义完整**：20ms 切片 + `finally` 抬键 + `release_modifiers` 三处兜底，暂停/停止/退出都不会留下按下的键。
5. **数据安全三件套**：迁移前备份、损坏隔离、防降级只读，且 `normalize_store` 是纯函数（整包导入也复用）。
6. **热键冲突自愈**：候选池 + 两轮换键 + "真被占用"键记忆，减少手工改键。
7. **"缺省即旧行为"的渐进演进**：`targets/strategies/hooks/Nova UI` 全部为可选字段，`classic` 布局可一键回退，迁移链逐级可测。
8. **诊断自证**：`raw_char_probe` 真注入并回读，`--diagnose` 一次性给出权限/前台/热键/注入四段结论。
9. **文档与代码同步**：`docs/PLAN-*` 记录每版验收门（G2.0/G2.2），`tools/build_docs.py` 零依赖生成离线站。

---

## 九、结论

- **架构层面**：v1 单体（UI 编排）+ v2.x 可复用包（数据/输入/策略/UI 组件）的分层是有效的，`tests/test_structure.py` 用 AST 把"数据层不得依赖 Tk""sender 不得依赖 win32"变成了可执行约束，这一点在个人工具中相当难得。
- **功能层面**：核心链路（热键 → 校验 → 注入 → 反馈 → 持久化）完整且异常路径考虑细致；但 **2.0 的发送策略在 GUI 侧因"策略表读取位置 + 字段被归一化丢弃"两处断链而实际不可用**，属于必须优先修复的功能缺陷。
- **演进层面**：主要债务集中在单体 `CheatApp`（105 方法）与主题系统的"部分换肤"；建议按 §7.2–7.4 抽 schema、拆 controller、补主题注册表，这三步能同时降低回归风险与后续加功能成本。

### 建议的验证命令（复现 §6.1 / §6.2）

```bash
# 1) 策略字段往返丢失（预期：当前失败）
python -c "from vcct.store import normalize_store; s=normalize_store({'profiles':[{'name':'p','cheats':[{'code':'ASPIRINE','strategy':{'kind':'adaptive','retries':2}}]}]}); print(s['profiles'][0]['cheats'][0])"

# 2) GUI 策略来源（静态检查）
# grep -n 'settings.get("strategies")' vc_cheat_typer.py   → 2723

# 3) 全量回归
python -m unittest discover -s tests -v
```

---

*本报告基于当前工作区代码静态阅读与交叉验证，未修改任何源文件。*
