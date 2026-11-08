# v2.0 执行方案（通用输入平台，已完成）

> 基线：v1.9.1（tag `v1.9.1`，commit `25d4428`）｜依据：`docs/ROADMAP-1.7-2.0.md` 第五章
> 日历说明：路线图把 v2.0 排在 2027-03-11 冻结期之后，但 1.7～1.9.1 已提前约 4 个月全部交付，
> 排期约束失效，故按"当前进度"连续开发。

## 关键实现决策（假设）

1. **兼容式抽库，不搬文件**：直接把 `vcct/*.py` 移进 `vcct/core/` 会让 1.7～1.9 的全部 import、
   PyInstaller spec、CLI 同时失效，正是路线图 R2.0.1「抽库演变成重写」的高风险。
   因此新增 `vcct/core/` 作为**门面 + 新能力模块**，既有 `vcct/*.py` 原地保留为实现层。
   UI 继续从 `vcct.*` 导入，行为逐项不变；通用能力一律走 `vcct.core`。
2. **配置版本不升级**：`STORE_VERSION` 仍为 3。`targets` / `strategies` / `hooks_enabled`
   都是可选字段，缺省 = 旧行为；`to_v2()` 自然剥离。避免"升版必迁移"的连锁成本。
3. **默认行为是硬约束（Gate G2.0）**：策略默认 `fixed`（plan_send 与旧 `SendParams.for_code`
   参数完全一致）、钩子默认关闭、targets 缺省空时完全沿用 1.8 的 games 逻辑。
4. **CLI 默认不碰键盘**：`send` 只预演，必须 `--execute` 才注入，防止脚本误触发把代码打进编辑器。
5. **core 惰性导出**：平台相关模块（winapi/hotkeys/tray/importer）用 PEP 562 `__getattr__`，
   `import vcct.core` 在无桌面/非 Windows 环境不会去加载 Win32 DLL。
6. **P1 未做**：2.0-I 便携模式路径选择、2.0-J 多语言 UI、2.0-K 更新提示、2.0-L PyPI 发布——
   按路线图属于可选，且 K/L 涉及联网/长期维护承诺，与"不联网"跨版本不变量冲突。

## 任务与落点

| 编号 | 落点 |
|---|---|
| 2.0-A | `vcct/core/__init__.py`（门面）、`vcct/loggingx.py`（弹窗改注入）、`vc_cheat_typer.py`（`show_crash_dialog` 注入）、`tests/test_v2_core.py`（AST 架构守卫） |
| 2.0-B | `vcct/core/strategy.py`；`CheatApp._send_worker` 用 `plan_send` + adaptive 重试循环；`_read_params` 带 `strategy_ref` |
| 2.0-C | `vcct/core/targets.py`；`store.py` 新增可选 `targets`/`strategies`；`CheatApp._auto_switch_tick` 优先 targets、回落 games；设置 → 游戏 增加迁移按钮 |
| 2.0-D | `vcct/core/hooks.py`；`CheatApp.hooks`（默认关闭）+ 设置 → 常规 开关；发送前 `fire_before`、结束 `fire_after` |
| 2.0-E | `vcct/cli.py`；主程序 `--cli` 转发；`python -m vcct.cli` |
| 2.0-F | `VC-Cheat-Typer-onedir.spec`、`build.ps1 -OneDir`（zip + SHA256）；`--export-v2` 沿用 |
| 2.0-G | `tools/build_docs.py` → `docs/site/*.html`（10 页，零依赖、离线） |
| 2.0-H | `tests/test_v2_upgrade.py`（v1.6 / v1.8 / v1.9 三条升级路径） |

## 兼容性

- 配置：v3 不变；新字段全部可选；1.6/1.7/1.8 配置照旧自动迁移；旧程序读 v2.0 配置安全忽略新字段
- 包：`.vcpack` 格式与 `pack_version` 不变
- 交互：托盘 / 向导 / 设置四页 / 自动切换 / 发送可取消 / 暂停语义全部保持；新增开关默认取"旧行为"
- 产物：onefile 仍是主交付；onedir 为附加形态，均带 SHA256

## 验证

- `python -m unittest discover -s tests` → 184 条通过（2 条环境跳过），新增 32 条
- `ruff check vc_cheat_typer.py vcct/ tools/` → 0 告警（CI 只检查主文件，同样通过）
- `--selftest` 全部通过（新增 `[2g]` 段验证 core / targets / strategy / hooks）
- `import vcct.core` 不加载 tkinter；`python -m vcct.cli version/list/send/pack info` 实测
- 三条升级路径零丢失 + v2 出口 + 整包往返 + 更高版本禁止回写
- `build.ps1 -OneDir` 实测：onefile + onedir zip 双产物 + SHA256

## 待真机验证

CLI `--execute` 真实注入（需目标前台）、adaptive 策略在丢字场景的补发、targets 规则带策略/IME 的切换、
onedir 目录启动速度对比、扩展点开启后的两个示例钩子。
