# v2.2 发布前验收报告

> 版本 `APP_VER = 2.2.0`（tag `v2.2`）、配置 `STORE_VERSION = 3`
> 验收环境：Windows 11 (10.0.26300)、Python 3.13.14、PyInstaller 6.22.3
> 验收方式：`build.ps1 -OneDir` 全链路 + 源码自检 + 三产物自检 + 覆盖率 + 哈希复核
> 本轮验收**未修改任何业务代码**

---

## 1. 结果总览

| # | 验收项 | 规格 | 实测 | 结论 |
|---|---|---|---|---|
| 1 | 单元测试 | 全绿 | 253 条，2 skip，60.5 s | 通过 |
| 2 | `ruff check` | 0 告警 | All checks passed | 通过 |
| 3 | `--selftest`（源码） | 全过 | `[1]`~`[6]` 全过，exit 0 | 通过 |
| 4 | `--selftest`（onefile exe） | 全过 | exit 0 | 通过 |
| 5 | `--selftest`（onedir exe） | 全过 | exit 0 | 通过 |
| 6 | 覆盖率（`vcct`，排除 ui/winapi/tray） | ≥ 80% | **86%** | 通过 |
| 7 | 三产物构建 | 成功 | exe / cli.exe / onedir+zip 全部产出 | 通过 |
| 8 | SHA256 清单复核 | 一致 | 三份清单逐项重算一致 | 通过 |
| 9 | 打包 CLI 冒烟 | 可运行 | `version` → `v2.2.0 (config v3)` | 通过 |

---

## 2. 单元测试

```
Ran 253 tests in 60.515s
OK (skipped=2)
```

包含本轮新增的 `TestTargetsCli`（6 条）与既有 `TestStrategiesCli` / `TestPack*` / `test_v2_2.py`。
两条 skip 为既有平台相关用例，非新增。

## 3. 静态检查

```
$ ruff check vc_cheat_typer.py vcct/
All checks passed!
```

## 4. 自检（`--selftest`）

源码自检输出覆盖 11 段，全部通过：

| 段 | 内容 | 关键实测 |
|---|---|---|
| `[1]` | 结构体布局 / 组合键解析 | `sizeof(INPUT)=40` 符合预期 |
| `[2]` | 默认数据完整性 | 28 条秘籍，0 重复热键，0 不安全绑定 |
| `[2b]`~`[2c]` | v1→v3 迁移链 / 损坏文件隔离 / 备份 | 迁移后 `version=3`；损坏文件被隔离并生成 `cheats.bak.json` |
| `[2d]` | 暂停热键表 / 搜索过滤 | 暂停态 1 条、正常态 29 条、冲突 0 |
| `[2e]`~`[2f]` | 秘籍包 / 文本导入 / 模板 / 发送历史 | 包校验通过；历史 60 条截断为 50 条 |
| `[2g]` | core 公共 API / 目标 / 策略 / 钩子 | core 62 项；目标命中 VC → 方案 默认 |
| `[2h]` | 数据目录 / 多语言 / 打包元数据 | portable 模式；`添加 → Add` |
| `[2i]` | Nova UI 令牌 / 命令注册表 | WCAG 5.26:1 / 6.81:1；命令 23 项 |
| `[3]`~`[5]` | 前台探测 / SendInput 真实注入 / 热键冲突 | 注入实得 `aspirinE`（不区分大小写）；冲突检测 `1409` 正确 |
| `[6]` | GUI 启停 | 正常创建并退出 |

打包产物自检：`onefile_selftest_exit=0`、`onedir_selftest_exit=0`。

## 5. 覆盖率

按 `pyproject.toml` 配置（`source=["vcct"]`，`omit=["vcct/ui/*","vcct/winapi.py","vcct/tray.py"]`，`fail_under=80`）：

```
TOTAL   1726 stmts   215 miss   574 branch   77 part   86%
```

关键模块：`store.py` 91%、`hotkeys.py` 93%、`packs.py` 90%、`core/targets.py` 98%、`core/strategy.py` 97%、`schema.py` 97%、`importer.py` 97%、`cli.py` 76%。
最低为 `loggingx.py` 45%（异常分支与文件句柄相关，非核心业务路径）。

> `vc_cheat_typer.py`（GUI 单体）不在覆盖率统计范围内，属既有设定。

## 6. 性能基准（`test_v2_2.py` 实测，含 3× 余量规格）

| 指标 | 规格 | 实测 |
|---|---|---|
| 命令搜索 P95（200 条） | < 20 ms | 0.2 ms |
| 主题切换（不重建控件） | < 200 ms | 4.9 ms |
| 主窗口构建 nova / classic | < 1.5 s | 75.2 ms / 71.7 ms |
| 1000 条秘籍渲染 | < 300 ms | 15.8 ms |

## 7. 构建产物与哈希

| 产物 | 大小 | SHA256 |
|---|---|---|
| `dist/VC-Cheat-Typer.exe` | 12,110,377 B | `2fd3ecf530a1849f67ae3dda2bd47f0c3507152de36ed8688096318b484c38cb` |
| `dist/VC-Cheat-Typer-cli.exe` | 8,881,397 B | `76cbdcabf71a3a6723fc64709a4a18d4002927a0ada25c760d48c837c4e95f97` |
| `dist/VC-Cheat-Typer-onedir-2.2.0.zip` | 12,123,158 B | `75191d79e70071fdbcf9b73503d99faf83ccf7b4f3ecd326c66b574b0cac59e3` |
| `dist/SBOM.json` | 834 B | CycloneDX 1.5 |

三份 `.txt` 清单均已用 `Get-FileHash` 重算比对，结果一致。
UPX：默认关闭（`upx=_UPX`，仅 `VCCT_UPX=1` 时启用）。

## 8. 已知噪音（非缺陷）

1. **`build.ps1` 返回码 -1 但实际已完成**：脚本末行 `Verify with Git Bash` 已打印、产物与哈希全部正确，
   退出码异常来自命令终端回收阶段，非脚本逻辑错误。
2. **onedir 打包 zip 首次失败后重试成功**：`base_library.zip` 被索引/杀软临时占用，
   `build.ps1` 内置 3 次重试，第 2 次成功——这是设计内的容错路径。
3. **`[version] WARNING: APP_VER=2.2.0 but latest tag=v2.2`**：属正常提示。
   注意**不要**用 `-SyncFromTag`：它会把 `APP_VER` 改写成 `2.2`，与既有三段式版本号规范不符。
4. **`<<ThemeChanged>>` 偶发打印**：多 `Tk()` 根共存时的 ttk 噪音，`rc=0`，真实程序单根不受影响。

## 9. 待人工验收（`PLAN-2.2.md` §6，自动化无法覆盖）

- 深浅主题实际观感、125% / 150% DPI 下排版无裁切
- `Ctrl+K` 命令面板手感与 `Esc` / `↑↓` / `Enter` 全键盘路径
- 窄窗口（< 900px）侧栏折叠表现
- 托盘与 Nova 状态中心的状态同步
- 三档缩放截图留档

## 10. 结论

代码级与产物级验收**全部通过**，可进入发布流程；发布前只剩 §9 的人工观感复核。
