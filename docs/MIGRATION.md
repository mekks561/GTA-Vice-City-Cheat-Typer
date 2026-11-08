# 配置迁移说明（v1 → v2 → v3）

> 适用：VC-Cheat-Typer v1.9｜实现：`vcct/store.py` 的 `migrate_store()` 及其逐级函数

## 1. 版本矩阵

| 程序版本 | 配置版本 | 读旧配置 | 回退路径 |
|---|---|---|---|
| v1.5 及更早 | v1（顶层 `cheats` 单列表） | — | — |
| v1.6 / 1.7 / 1.8 | v2（`profiles` 多方案） | ✅ 自动迁移 v1 | 覆盖旧 exe |
| **v1.9** | **v3** | ✅ 自动迁移 v1 / v2 + 备份 | `--export-v2` 或界面「导出 v2 兼容配置」 |
| 更高版本 | > v3 | ❌ 明确拒绝 | 见 §5 |

**三条铁律**

1. 配置只升不降，但**必须留显式出口**：任何升版自动备份迁移前原件，并提供 `--export-v2`；
2. 新字段一律可选：缺省 = 旧行为。允许「程序新、配置旧」，**不允许「程序旧、配置新」静默降级**；
3. 迁移函数纯化：`migrate_store(raw) -> dict` 不碰文件系统、不改入参、不写全局，便于回归测试。

## 2. 结构差异

```
v1  { version:1, settings, cheats[] }
 ↓  migrate_v1_to_v2：顶层 cheats 包成 profiles[0] = {name:"默认", cheats}
v2  { version:2, settings, active_profile, profiles[], stats, today, games? }
 ↓  migrate_v2_to_v3：补 packs / ui / profiles[].game
v3  { version:3, settings, active_profile, profiles[].{name,cheats,game},
      stats, today, games?, packs[], ui{} }
```

新增字段（全部可选）：

| 字段 | 用途 | 缺省 |
|---|---|---|
| `profiles[].game` | 方案绑定的游戏模板 | `VC 经典版` |
| `cheats[].verified` | 是否实机验证（false 在 UI 灰显） | `true` |
| `cheats[].game` / `source_pack` | 来源标记，仅记录、不参与逻辑 | `""` |
| `packs[]` | 已安装 .vcpack 记录（名称/作者/游戏/版本/校验/时间） | `[]` |
| `ui` | 窗口位置 `geometry` + 列宽 `column_widths` | `{}` |
| `history` | v1.9.1 发送历史：最近 50 次（时间/名称/代码/方案/结果/耗时/说明） | `[]` |
| `targets` | v2.0 通用目标规则（name/match/require_foreground/ime_policy/strategy_ref/profile_ref） | `[]` |
| `strategies` | v2.0 具名发送策略表 | `{}` |

`games` 是 1.8 引入的 v2 可选字段，v3 原样保留；`targets` 非空时优先于 `games`。
`settings.hooks_enabled` 默认 `False`（扩展点关闭）。

> v1.9.1 **不升配置版本**：`history` 是 v3 可选字段，缺省空列表；`to_v2()` 会剥离它，因此 `--export-v2` 产物仍可被 1.6/1.7/1.8 读取。旧程序读到 v1.9.1 配置时同样安全忽略 `history`。

## 3. 升级时发生了什么

`load_store()` 读取 `cheats.json`：

1. 解析失败 / 顶层不是对象 → 原文件隔离为 `cheats.corrupt-<时间戳>.json`，载入默认表并弹窗；
2. `_version_of(raw)` 推断版本（缺 `version` 时按结构猜：有 `profiles` = v2，有顶层 `cheats` = v1）；
3. **若版本低于 3**：先 `backup_before_migration()` 把**迁移前原件**复制为 `cheats.v2.bak.json`（v1 则是 `cheats.v1.bak.json`），同名备份已存在时不覆盖——永远保留第一次的原件；
4. 走 `migrate_store()` 串行链，再 `normalize_store()` 做字段白名单 / 默认值 / 方案名去重；
5. 下一次 `persist()` 才把 v3 结构写回 `cheats.json`；每次保存照旧留上一版 `cheats.bak.json`。

> 备份层次别混淆：`cheats.v2.bak.json` = **升版前原件**（永久保留）；`cheats.bak.json` = **上一次保存**（滚动覆盖）。

## 4. 失败与回滚

| 情况 | 行为 | 恢复方式 |
|---|---|---|
| 迁移函数抛异常 | 不写盘、不覆盖原文件；载入默认表 | 手工把 `cheats.v2.bak.json` 改回 `cheats.json` |
| 保存失败（只读目录/权限） | 打印 + 写日志，不中断程序 | 检查目录权限；程序会自动回退到 `%LOCALAPPDATA%` |
| 想退回 1.8 | 用 `--export-v2` 导出或直接改文件名 | `VC-Cheat-Typer.exe --export-v2 [路径]` / 界面「⋯ 更多 → 导出 v2 兼容配置」 |

CLI 出口：

```bat
VC-Cheat-Typer.exe --export-v2                :: 默认写到 cheats.v2.json
VC-Cheat-Typer.exe --export-v2 D:\backup.json :: 指定路径
```

`to_v2()` 会剥掉 `packs` / `ui` / `verified` / `game` / `source_pack`，把 `version` 写回 2，保留 `games`（旧程序安全忽略），**不会覆盖当前 v3 配置**。

## 5. 读到更高版本（防静默降级）

若 `version > 3`：

- `load_store()` 给出可读提示「配置来自更新版本（vX），本程序最高支持 v3，请升级程序」，界面弹窗；
- 本次载入默认秘籍表，且设置 `_FORBID_DEFAULT_SAVE` —— **`save_store()` 拒绝回写默认路径**，避免用默认数据覆盖用户的新版配置；
- `migrate_store()` 直接抛 `StoreTooNew(found, current)`；
- 导入整包时同样拒绝（`parse_bundle` 返回明确错误）。

处理：升级程序；或把 `cheats.json` 改名保存，再用 `--export-v2` 从新版程序导出兼容副本。

## 6. 回归样本

`tests/test_v3_store.py` 固定 5 份历史形态配置做迁移零丢失回归：

1. 标准 v1（自定义间隔 + 1 条秘籍）；
2. 标准 v2（多字段：方案 / 统计 / 当日 / games 规则）；
3. 空 v1（无 cheats）；
4. v2 重名方案（验证方案名去重）；
5. v2 无 `app` 字段 + 关闭的 games 规则。

另测：备份只生成一次、更高版本不回写、v3 往返、bundle 拒绝更新版本、`to_v2` 字段剥离。

## 7. 第三方 / 手写配置建议

- 不写 `version` 也能读（按结构推断），但建议显式写 `3`；
- 未知字段会被忽略，不会报错；
- 只想分享秘籍请用 `.vcpack`（见 `docs/PACK-FORMAT.md`），不要手改 `cheats.json`。
