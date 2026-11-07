# VC-Cheat-Typer 1.7 开发方案（执行版）

> 基线：v1.6（commit `d1d7eb4`，`vc_cheat_typer.py` 2900 行 / 45 条单测 / CI 全绿）
> 日期：2026-11-07 ｜ 目标发布：2026-11-24
> 上游：`docs/ROADMAP-1.7-2.0.md`（本文档修正了其中的任务顺序与一处错误判断）

---

## 零、先修正一条错误判断（重要）

`ROADMAP-1.7-2.0.md` 里写「连按两个热键会起两条 worker 同时 SendInput，输出交错成乱码」，**这个判断是错的**。

审计结果：`CheatApp.__init__` 第 1544 行已有 `self.sending = threading.Lock()`，`_start_send`（2217–2223）用 `acquire(blocking=False)` 非阻塞抢占，抢不到就丢弃并记日志。**并发交错不存在。**

由此 1.7-B「单飞」从「修 bug」降级为「补短板」，真正缺的是：

| 真实缺口 | 证据 | 后果 |
|---|---|---|
| **无法取消** | 全文无 `Event` 停止标志，`_send_worker` 的 for 循环只受 `check_fg` 约束 | 18 字符发到一半发现错了，只能等它打完 |
| **暂停不中止在飞发送** | `toggle_pause`（2175）只做 `apply_hotkeys()` 注销热键 | 按了「暂停」，当前这条秘籍仍会继续打完——安全语义不成立 |
| **残键无兜底** | `press_key`（351）下压→`sleep`→抬起，中间无 `finally` | 抬起失败/进程被杀 → Ctrl/Shift 卡住，玩家角色一直跑 |
| **锁泄漏** | `_start_send` 里 `Thread(...).start()` 未包 try | 极端情况下线程起不来，锁永不释放，此后所有发送静默丢弃 |
| **丢弃无反馈** | 抢占失败只 `self.log(...)` | 用户按了热键"没反应"，不知道是被丢弃 |

**结论：1.7 的价值不是"修并发"，而是"让发送可中断、可兜底、可观测"。**

---

## 一、改动范围（三类，量化）

| 类别 | 内容 | 规模 | 风险 |
|---|---|---|---|
| **A. 搬运**（无逻辑变更） | 从单文件抽出 5 个叶子模块：`const / winapi / store / loggingx / hotkeys` | ~1450 行移出 | 中（纯机械，但面大） |
| **B. 新增**（新能力） | 取消引擎、残键兜底、发送状态机、质量日志、GUI 冒烟 | ~400–500 行 | 低（新增为主） |
| **C. 修改**（行为变更） | 8 处既有函数 | ~120 行改写 | **高**（直接改发送链路） |

### 1.1 明确**不**做的事（与路线图的重要偏差）

**不做 `CheatApp` 的类拆分。** 原因：

- `CheatApp`（1531–2727，约 1200 行）是一个**单窗口应用对象**，它的"大"是 tk 布局代码密集，不是逻辑纠缠；
- 把它拆成 `app / dialogs / theme` 只是"换个文件放同样多的行"，对 1.8 的设置页改造帮助有限——那时重构 UI 本来就要重写布局；
- 拆 1200 行 tk 代码的回归风险，远高于拆 5 个无 UI 依赖的叶子模块。

**替代方案（strangler）**：只把**不依赖 tk 的部分**抽走。抽完后 `vc_cheat_typer.py` 从 2900 行降到约 1500 行（只剩 UI + 入口），后续 1.8/1.9 的新逻辑（包解析、迁移链、目标规则）直接落在新模块里，不再往单文件堆。

---

## 二、目标模块结构

```
vcct/
├── __init__.py
├── const.py      APP_NAME / APP_VER / DEFAULT_SETTINGS / PRESETS / PAUSE_ID / 配色
├── winapi.py     ctypes 结构体与原型、INPUT、SendInput、press_key、
│                 foreground_info、find_game_window、ImeGuard、raw_char_probe、DPI
├── hotkeys.py    VK 表、parse/format/combo_signature、is_safe_binding、
│                 candidate_combos、pick_free_combo、build_bindings、HotkeyEngine
├── store.py      _norm_* / normalize_store / load_store / save_store /
│                 bundle_payload / parse_bundle / bump_stats / touch_today / filter_cheats
├── loggingx.py   app_dir/data_path/log_dir/log_file/append_log/_rotate_log/
│                 _show_crash_dialog/install_crash_hooks
└── sender.py     【新增】SendParams、SendCancelled、type_text、release_held_modifiers
vc_cheat_typer.py  入口壳：import + CheatApp + HotkeyCapture + CheatDialog + selftest + main
```

**硬约束**：`store.py` / `loggingx.py` 不得 import tkinter；`sender.py` 只接收注入的 `send_key` / `sleep` 回调，不直接调 `user32`（这样单测不需要真实键盘）。

---

## 三、具体改动点（逐处）

### 3.1 搬运清单（move-only，禁止顺手改逻辑）

| # | 当前位置 | 目标 | 说明 |
|---|---|---|---|
| M1 | 1–50 `import` + `APP_NAME/APP_VER` | `const.py` | `APP_VER` 同时改 `1.6` → `1.7` |
| M2 | 70–111 ctypes 结构体（`KEYBDINPUT`/`INPUT`…） | `winapi.py` | 连同 `_reg` 原型设置（113 起）一起 |
| M3 | 113 `MOD_*`、225 `VK_BY_NAME`、1104 `PAUSE_ID`、1523 `C` | `const.py` / `hotkeys.py` | `VK_BY_NAME` 属按键域，进 hotkeys |
| M4 | 278–330 `format_combo`/`parse_combo`/`combo_signature`/`is_safe_binding` | `hotkeys.py` | 纯函数，零依赖 |
| M5 | 332–460 `_key_item`/`_send`/`press_key`/`foreground_info`/`is_key_down`/`find_game_window` | `winapi.py` | — |
| M6 | 454–604 `ImeGuard`/`force_foreground`/`raw_char_probe` | `winapi.py` | — |
| M7 | 604–678 `HotkeyEngine` | `hotkeys.py` | — |
| M8 | 682–750 `DEFAULT_SETTINGS`/`PRESETS`/`_c`/`default_cheats` | `const.py` | — |
| M9 | 751–875 路径/日志/崩溃钩子 | `loggingx.py` | — |
| M10 | 875–1258 归一化/存取/整包/统计/过滤/绑定构造 | `store.py` + `hotkeys.py` | `build_bindings`/`candidate_combos`/`pick_free_combo` 进 hotkeys |
| M11 | 1226–1258 `enable_dpi_awareness`/`ui_scale` | `winapi.py` | — |

**shim 兼容**：`vc_cheat_typer.py` 顶部保留

```python
from vcct.const import *      # noqa: F401,F403
from vcct.store import *      # noqa: F401,F403
from vcct.hotkeys import *    # noqa: F401,F403
from vcct.winapi import *     # noqa: F401,F403
```

目的：`run.bat`、PyInstaller `--name`、README 路径、`tests/test_core.py` 的 45 条旧 import **全部不用改**；同时加一条断言测试 `vc_cheat_typer.parse_combo is vcct.hotkeys.parse_combo`，防止 shim 与实现分叉。

### 3.2 新增：发送引擎 `vcct/sender.py`

```python
@dataclass(frozen=True)
class SendParams:
    code: str
    interval_ms: int = 45
    hold_ms: int = 25
    pre_delay_ms: int = 180
    uppercase: bool = False

class SendCancelled(Exception):
    def __init__(self, sent: int, total: int): ...

def type_text(p: SendParams, stop: threading.Event, *,
              send_key,                     # (vk:int, down:bool) -> None
              sleep=time.sleep,
              on_progress=None) -> int:
    """逐字符注入。stop 置位即中止；中止时保证已按下的键全部抬起，抛 SendCancelled。"""
```

**关键实现约定**（每条都要有对应单测）：

1. **可中断睡眠**：`sleep` 切成 ≤20ms 的片，片间检查 `stop` —— 否则设了 100ms 间隔，用户按停止还要等 100ms 才响应。
2. **字符前检查**：`for i, ch in enumerate(code)` 循环体第一句 `if stop.is_set(): raise SendCancelled(i, len(code))`。
3. **按键必抬起**：`send_key(vk, True)` 后立刻 `try: sleep(hold) finally: send_key(vk, False)` —— 即使中途异常也抬起。
4. **非法字符**：`VK_BY_NAME` 查不到 → 抛 `ValueError(f"非法字符 {ch!r}")`，异常前已按下的键同样走 finally 抬起。
5. **`pre_delay` 也可中断**：用户在 180ms 前置延迟里按停止，应当 0 字符、不留痕迹。
6. **不做任何 tk/Win32 直接调用**：全部经注入的 `send_key`，单测用假函数即可断言调用序列。

### 3.3 修改清单（行为变更，按风险从高到低）

| # | 位置 | 现状 | 改为 | 为什么 |
|---|---|---|---|---|
| C1 | `_send_worker` 2238–2298 | 循环内手工 `press_key` + `time.sleep` + 三处 `return` | 改为调用 `sender.type_text(...)`，只保留「前台校验 / IME 守卫 / 成功日志 / 统计」这些外围职责 | 让可测逻辑与 UI 解耦；三处 `return` 收敛为一处 `except SendCancelled` |
| C2 | `_start_send` 2217–2223 | `acquire()` 后直接起线程 | 加 `self._stop.clear()`、`self._inflight = cheat`、`Thread.start()` 包 `try/except`（失败则 `release()`）；抢占失败改为 **toast + 日志** 双通道 | 修锁泄漏；让"丢弃"可见 |
| C3 | `__init__` 1544 附近 | 只有 `self.sending` | 增 `self._stop = threading.Event()`、`self._inflight: dict \| None = None` | 状态机基础 |
| C4 | `toggle_pause` 2175 | 只 `apply_hotkeys()` | 先 `if self.paused: self._stop.set()` 再注销热键；恢复时不重置 | **安全语义**：暂停 = 立即停止一切注入 |
| C5 | `press_key` 351（搬入 winapi 时） | 上下压无 finally | keyup 放 `finally`；新增 `release_held_modifiers(is_down, send_key)` | 残键兜底 |
| C6 | `on_close` 2706 | 直接销毁 | `self._stop.set()` → `join` 最多 300ms → `release_held_modifiers()` → 销毁 | 关程序不留卡键 |
| C7 | 工具栏「发送所选」按钮 | 固定文案 | 发送中变「■ 停止」并置为可用，结束恢复 | **不加新控件**（1.6 已因工具栏溢出踩过 R3），复用现有按钮位 |
| C8 | 根窗口 `<Escape>` | 无绑定 | 绑定 `stop_send()`；弹窗内 Esc 优先关闭弹窗 | 键盘用户的快速出口 |

### 3.4 设置项改动（易漏）

`save_store`（1033 起）会把 settings **过滤成只保留 `DEFAULT_SETTINGS` 里存在的键**。因此新增任何设置项（如 `debounce_ms`、`stop_on_pause`）必须**同时**加入 `DEFAULT_SETTINGS`，否则保存一次就被丢弃。

1.7 新增设置项（均为 v2 可选字段，不升 `STORE_VERSION`）：

```python
"debounce_ms": 250,        # 同一秘籍连按去抖窗口
"stop_on_pause": True,     # 暂停时中止在飞发送（安全默认）
```

### 3.5 日志增强（`loggingx` + `_send_worker` 尾部）

发送完成/取消/失败各记一行结构化日志：

```
SEND ok   name=满血 code=ASPIRINE chars=8 interval=45ms hold=25ms
          planned=540ms actual=562ms dev=+4.1%
SEND cancel name=坦克 code=PANZER sent=3/6 at_char=4 elapsed=310ms
SEND fail reason=fg_lost name=坦克 code=PANZER sent=3/6
```

偏差 >15% 时打 `WARN`（对应 1.7-F 验收）。这条日志是**真机丢字问题唯一可远程诊断的手段**——用户贴一行就能判断是间隔太短还是权限问题。

---

## 四、优先级任务（可直接开工）

| ID | 任务 | 优先级 | 估时 | 依赖 | 完成定义（DoD） |
|---|---|---|---|---|---|
| **T-01** | 抽 `const.py` + `winapi.py`（M1–M3、M5–M6、M11） | **P0** | 1.0d | — | 2900 → ~2200 行；45 单测 + selftest 全过；搬运提交无逻辑改动 |
| **T-02** | 抽 `store.py` + `loggingx.py`（M9–M10） | **P0** | 1.0d | T-01 | 同上；`store/loggingx` 不 import tkinter（加断言测试） |
| **T-03** | 抽 `hotkeys.py`（M4、M7、M10 部分）+ 建 `sender.py` 空壳 | **P0** | 1.0d | T-02 | `HotkeyEngine` 平移后热键注册数仍为 28、0 冲突 |
| **T-04** | 实现 `type_text` + `SendCancelled`（B 核心） | **P0** | 1.0d | T-03 | 新增 ≥10 条单测覆盖 §3.2 六条约定；假 `send_key` 断言调用序列 |
| **T-05** | 接线：C1 改造 + C2/C3/C7/C8（停止按钮、Esc、状态机） | **P0** | 0.8d | T-04 | 界面「停止」可在任意时刻中断；按钮文案随状态切换 |
| **T-06** | 暂停中止在飞发送（C4）+ 残键兜底（C5/C6） | **P0** | 0.6d | T-05 | 发送中按 `Ctrl+Alt+P` → 立即停且无残键；关闭窗口同理 |
| **T-07** | 单飞完善 + 发送质量日志（C2 剩余 + §3.5） | P1 | 0.6d | T-05 | 抢占失败有 toast；日志含 planned/actual/dev |
| **T-08** | GUI 冒烟进 CI（`tests/test_gui_smoke.py`） | P1 | 0.8d | T-03 | Actions 出现 `gui-smoke` job，非阻塞 |
| **T-09** | 单测补齐 ≥55 + selftest 增 `[7] 取消与时序` | P1 | 0.6d | T-04~T-06 | `--selftest` 连跑 3 次全过 |
| **T-10** | README/CHANGELOG、打包、SHA256、Release v1.7 | **P0** | 1.0d | 全部 | 资产齐全，tag `v1.7` |

**合计 8.4 人日**（比路线图的 9.5 少，因为砍掉了 `CheatApp` 大拆）。按 11/07 起每天 2–3h，到 11/24 有 17 天 ≈ 34–50h，**工期成立但缓冲很薄**——所以 T-07/T-08 是唯一可牺牲项，P0 六项不可动。

### 4.1 为什么先搬运再加功能（与路线图顺序相反）

原路线图是「先做 A/B/C 功能，再拆包」。审计后改为**先搬后加**，理由：

1. **搬运营造"零差异基线"**：搬运阶段行为必须完全一致，任何测试失败都只有"搬错了"一个原因，定位成本最低；
2. **避免二次搬运**：先写取消功能再拆包，等于把新代码再搬一遍，且搬运提交里混入新逻辑，"move-only 可验证"这个安全前提就废了；
3. **单测能直接对着新模块写**：`type_text` 一旦落在 `vcct/sender.py`，测试 import 路径稳定，不会因后续搬迁再改。

代价是前 3 天没有可见进展 —— 这是有意接受的投资。

---

## 五、验证矩阵与回滚

### 5.1 自动验证（每次提交）

| 项 | 命令 | 门槛 |
|---|---|---|
| 静态检查 | `uvx ruff check .` | 0 告警 |
| 单元测试 | `python -m unittest discover -s tests` | 45 → **≥55** 条全过 |
| 内置自检 | `python vc_cheat_typer.py --selftest` | 6 → **7** 项全过，连跑 3 次 |
| 编译 | `python -m py_compile` | 通过 |
| 导入隔离 | 新增断言 | `store`/`loggingx` 的 `sys.modules` 无 `tkinter` |

### 5.2 人工验证（发布门槛，必须逐条走）

1. 发送 18 字符秘籍，中途点「停止」→ 立刻停，剩余字符零输出，**无残留修饰键**（在记事本按 Ctrl 观察）
2. 发送中途按 `Ctrl+Alt+P` → 立即停止 + 热键全注销；再按一次 → 恢复且能正常发送
3. 发送中途点窗口关闭 → 进程退出，键盘无卡键
4. 同一热键 200ms 内连按两次 → 只发一条（去抖生效）
5. 不同热键连续按 → 第二条被丢弃时**有 toast 提示**（不是静默）
6. 发送时切走窗口 → 按现有逻辑中止并提示
7. 游戏内实测 F1/F8 各 3 次，全中
8. 100%/125%/150% 三档截图复查（确认「停止」按钮文案切换未挤坏布局）

### 5.3 回滚策略

- 每个搬运任务 **单独一个 commit**，commit message 前缀 `refactor(1.7):`，且该 commit 内 **diff 只允许移动/import 变化**；
- 每个 T-0x 完成后打轻量 tag（`v1.7-step1` … `v1.7-step6`）；
- 任一环节回归失败 → `git revert <该 commit>` 回到上一个可发布点，不影响后续功能开发；
- 发布前保留 `v1.6` 的 `dist/VC-Cheat-Typer.exe`，必要时可原地回退给用户。

---

## 六、1.7 不做（防止范围膨胀）

- `CheatApp` 类拆分、UI 框架更换 → 推迟到 1.8 做设置页时顺带
- 托盘、自动切方案、向导（属 1.8）
- 秘籍包格式、配置 v3（属 1.9）
- macOS 后端（需求 1.6 已暂缓，见 `docs/MACOS-PORT.md`）
- 发送策略引擎（属 2.0，1.7 只做"能取消"，不做"自适应间隔"）

---

## 七、一句话

**1.7 = 把 1450 行无 UI 依赖的代码搬出单文件（先立地基），再在新地基上加「随时能停、停了不留残键、暂停立即生效」三件事。**
不追求新功能，只追求"按下去可控、停下来干净、出问题能查"。
