# 1.9.1 执行说明（增量补丁）

> 基线：v1.9（tag `v1.9`，commit `d718100`）
> 范围：**只做路线图里剩余的可选项 + 修复影响现有功能的明显问题**，不重做已完成部分。

## 范围选择（关键假设）

1. **"尚未完成的功能" 取路线图 P1 可选项**：1.9-G/H、1.8-G/I、1.7-G/H。v2.0 按 `ROADMAP-1.7-2.0.md` 排在 2027-01-21~03-10 冻结期之后，本轮不启动；1.8-H（深色主题跟随系统）会改动全局配色、与"保持交互行为一致"冲突，暂不做；1.7-I（onedir 评估）只出结论，收益低，暂不做。
2. **1.9-I 视为已等价实现**：路线图原写"导出为 v2 兼容包"，1.9-A 已交付 `--export-v2` 与界面「导出 v2 兼容配置」，导出的是完整可回退配置，比只导秘籍更完整，不重复造一个更弱的功能。
3. **不改配置版本**：新增 `history` 与包能力都是 v3 **可选字段**（缺省 = 旧行为），`STORE_VERSION` 保持 3；`to_v2()` 自然剥离 history。
4. **不改包格式**：自动避让与版本比对都在导入端做内存变换 / 本地记录比对，`pack_version` 仍为 1，旧包完全兼容。
5. **不改默认交互**：托盘仍默认开、自动切换仍默认开、向导仍按 `onboarded` 触发；所有新增开关默认取对用户最安全的取值（自动避让开），批量操作从"全量重排"收敛为"只改有问题的"。

## 交付落点

| 类别 | 文件 | 内容 |
|---|---|---|
| 修复 | `vcct/tray.py` | 启动线程前初始化 `_failed`，消除托盘随机失效 |
| 修复 | `vcct/winapi.py` | 注入探针：去掉 `WM_DESTROY` 里的 `PostQuitMessage`（残留 WM_QUIT 会让下一次探针立刻退出，这是主因）、每次用唯一窗口类名并在结束时注销（避免复用已被 GC 的窗口过程）；发送途中前台被抢则逐字重新抢回 |
| 修复 | `vcct/store.py` | `_norm_history` 先过滤脏记录再截断 50 条上限 |
| 修复 | `vc_cheat_typer.py` | `HotkeyOverview` 去掉 ttk 非法 `bg=`；selftest 探针重试 3 次且「未取得前台」判为未验证而非失败 |
| 修复 | `vc_cheat_typer.py` | `HotkeyOverview` 去掉 ttk 非法 `bg=`；设置输入页 FocusOut 绑到真实控件；批量热键只处理未绑定/冲突项；总览刷新保留选中与滚动；`_auto_switch_tick` 移出 try |
| 1.9-G/H | `vcct/packs.py` | `_candidate_combos` / `auto_avoid_hotkeys` / `compare_pack_record`（纯函数、零 ctypes 依赖）；导入页新增开关与提示 |
| 1.8-I | `vcct/store.py`, `vc_cheat_typer.py` | `_norm_history` + v3 `history` 字段；`_send_worker` 只投递 `("history", dict)` 事件；`_record_history` 主线程写盘（上限 50）；`HistoryDialog` 面板 + 重发 + 清空；两处入口 |
| 1.8-G | `vc_cheat_typer.py` | `bind_dialog_keys()` 统一 Esc 关弹窗；列表 Home/End；↑↓/Enter 沿用既有行为并写入文档 |
| 1.7-G/H | `README.en.md`, `build.ps1` | 英文文档；一键构建（单测 + ruff + PyInstaller + SHA256，版本核对，默认不改源码） |
| 文档 | `README.md`, `docs/PACK-FORMAT.md`, `docs/MIGRATION.md` | v1.9.1 章节 / 关键假设 / 验证清单；两份规范补字段说明 |
| 测试 | `tests/test_packs.py`, `test_v3_store.py`, `test_games.py`, `test_gui_smoke.py`, `test_probe_repeat.py` | 17 条新增（151 条通过 + 1 条桌面手动回归）；GUI 冒烟补 2 个此前没覆盖的对话框，直接暴露了 `ttk.Frame(bg=)` 缺陷 |

## 兼容性

- 配置：v3 不变；`history` 缺省 `[]`；1.6/1.7/1.8 配置读进来照旧迁移；旧程序读 v1.9.1 配置会忽略 `history`（不会报错）
- 包：格式与 `pack_version` 不变，旧包仍可导入；自动避让只改内存副本，不回写包文件；包记录沿用 `pack_record`
- 行为：所有默认值保持不变；唯一"行为收敛"是批量分配热键不再动已正常绑定的键（修复误操作）
- 发版：仍为 onefile exe + SHA256 清单；`build.ps1` 生成的清单与 `sha256sum -c` 兼容

## 验证

- `python -m unittest discover -s tests` → **151 条通过 + 1 条桌面手动回归跳过**（新增 17）
- `ruff check vc_cheat_typer.py vcct/` → 0 告警
- `--selftest` → **连续 4 次全部通过**（新增 `[2f]` 段；含真实注入探针 / 热键冲突码 1409 / GUI 冒烟）
- `build.ps1` 实测跑通（单测 + ruff + PyInstaller + SHA256；产物用 `sha256sum -c` 校验通过）
- 打包后 exe 复跑 `--selftest` / `--diagnose`

## 需要真机验证的行为

1. 反复启动/关闭 10 次，托盘每次都在（回归 `_failed` 竞态）；
2. 「⌨ 热键总览」能正常打开、选中行在自动刷新后不丢失；
3. 设置 → 输入：改关键字/间隔后直接关窗，重开仍在；
4. 全选 28 条点「批量分配空闲热键」→ 已绑定键位不变；
5. 导入一个与本地热键冲突的 .vcpack → 预览显示自动避让结果；
6. 重复导入同名包 → 提示"完全一致"；改过内容 → 提示"内容变化"；
7. 发几条秘籍后打开发送历史，重发/清空可用；
8. 各弹窗按 Esc 可关，列表 Home/End/↑↓/Enter 行为符合预期。
