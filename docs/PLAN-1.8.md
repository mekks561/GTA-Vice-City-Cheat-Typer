# 1.8 执行方案（已完成）

> 基线：v1.7.1（commit `d55285b`）｜依据：`docs/ROADMAP-1.7-2.0.md` 第三章
> 状态：**全部 P0 已实现并发布**

## 任务与实现落点

| 编号 | 任务 | 落点 |
|---|---|---|
| 1.8-A | 托盘常驻 | `vcct/tray.py`（Shell_NotifyIconW + 独立消息线程 + TaskbarCreated 重注册）；`CheatApp.on_close(force=False)` 默认缩托盘，`_on_unmap` 拦最小化；设置 `close_to_tray` 可改回旧行为 |
| 1.8-B | 按游戏自动切方案 | `vcct/store.py`：`_norm_games` / `match_game_rule` / `evaluate_game_rules` 纯函数，`games` 规则表进配置（v2 兼容可选字段）；`CheatApp._auto_switch_tick` 挂在 3s 轮询里，800ms 防抖、发送中不切、规则指向不存在方案只警告一次 |
| 1.8-C | 首次启动向导 | `OnboardWizard`：选预设（可勾选添加 gta-vc 自动切换规则）→ 注入自检（raw_char_probe）→ 冲突检测/一键分配；完成或跳过写 `settings.onboarded`；`Ctrl+F1` 重开 |
| 1.8-D | 设置对话框 | `SettingsDialog` 四页（常规/输入/游戏/数据）+ `GameRuleDialog`；Tk 变量抽到 `CheatApp._make_vars()` 与控件解耦；主界面只留方案切换/搜索/分组/发送/列表/日志 |
| 1.8-E | 热键总览 | `HotkeyOverview`：全部热键 + 占用状态 + 所属方案，冲突红标、未注册灰显；重新检测占用；导出文本 |
| 1.8-F | 测试与文档 | `tests/test_games.py`（10 条）+ 冒烟断言更新；README 重写快速上手 + v1.8 章节 |

## 关键实现决策

1. **托盘独立线程 + Win32 消息窗**：tkinter 的窗口/消息泵不能被第二线程碰，托盘用裸 ctypes 建隐藏窗口自跑 `GetMessage` 循环；回调经 `app.events` 队列投回主线程，托盘线程零 tkinter 依赖（AST 测试守住）。
2. **64 位 ctypes 签名**：`DefWindowProcW/PostMessageW` 必须显式声明 argtypes，否则 lparam 大值 OverflowError（实测踩到）。
3. **on_close 语义变更**：默认最小化到托盘；托盘不可用或 `force=True`（托盘退出、提权重启、selftest）才真正退出——selftest 与冒烟测试同步更新。
4. **games 规则匹配窗口选择**：对**前台窗口**（标题+进程）匹配而非仅 find_game_window 的游戏窗口——规则表是通用场景开关（将来可加别的游戏），且"切回桌面不误切"由"离开前台即停止匹配"保证。
5. **配置只升不降**：新字段全部可选、缺省=旧行为；`save_store` 白名单同步收录 `games`，旧版程序读到 v1.8 配置会忽略 games 字段，不报错。

## 验证

- 单测：89 条（1.7 的 79 + 1.8 的 10）全过；ruff（主文件）0 告警
- `--selftest` 全部通过（含 GUI 冒烟 + 真实注入探针 + 热键冲突返回码 1409）
- 真机待验证清单：托盘右键三项、Explorer 重启图标恢复、gta-vc 前台自动切方案、向导三步、设置四页逐项、热键总览导出
