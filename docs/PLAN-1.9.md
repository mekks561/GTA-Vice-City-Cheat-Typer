# 1.9 执行方案（已完成）

> 基线：v1.8（commit `59deca6`）｜依据：`docs/ROADMAP-1.7-2.0.md` 第四章
> 一句话：**内容可流通** —— 秘籍从写死在代码里的常量，变成可导入导出、可批量操作的数据资产。

## 任务与落点

| 编号 | 任务 | 落点 |
|---|---|---|
| 1.9-A | 配置 v3 + 迁移链 | `vcct/const.py`（STORE_VERSION=3 / DEFAULT_GAME）、`vcct/store.py`：`_version_of` / `migrate_v1_to_v2` / `migrate_v2_to_v3` / `migrate_store`（纯函数）/ `StoreTooNew` / `_norm_packs` / `_norm_ui` / `to_v2` / `export_v2` / `backup_before_migration`；`load_store` 遇更高版本设 `_FORBID_DEFAULT_SAVE` 禁止回写；CLI `--export-v2` |
| 1.9-B | .vcpack | `vcct/packs.py`（`make_pack` / `validate_pack` / `diff_pack` / `merge_pack` / `pack_signature` / `pack_record`）；`PackManagerDialog` 三页（导入 diff 预览 / 导出 / 已安装） |
| 1.9-C | 批量编辑 | Treeview `extended` 多选 + `selected_ids()`；右键「批量操作」子菜单；`batch_set_group` / `batch_assign_hotkeys` / `batch_set_interval` / `batch_delete`；`undo_last` 新增 `batch_cheats` 快照分支 |
| 1.9-D | 多游戏模板 | `vcct/templates.py`（4 套模板 / `template_cheats` / `template_preset`）；`TemplateDialog`；列表 `unverified` 灰标 + 备注前缀；`profiles[].game` 绑定；编辑对话框保留 verified/game/source_pack |
| 1.9-E | 文本导入 | `vcct/importer.py` `parse_pasted` 纯函数；`TextImportDialog`（预览 + 逐行报错） |
| 1.9-F | 文档与发布 | `docs/PACK-FORMAT.md`、`docs/MIGRATION.md`、README v1.9；134 条单测；ruff 0；打包 + Release |

## 关键决策

1. **sha256 不是门禁**：不匹配只警告。否则「导出 → 手工改两条 → 再导入」往返流程会把自己锁死，也与「第三方可手写包」冲突。
2. **更高版本配置拒绝回写**：`load_store` 返回 default_store() 的同时设 `_FORBID_DEFAULT_SAVE`，`save_store()` 对默认路径直接 return，防止界面启动后的第一次 persist 用默认数据覆盖用户的新版文件。
3. **迁移前原件只备份一次**：`cheats.v2.bak.json` 已存在则不覆盖，保证永远留着第一次升版前的样子；`cheats.bak.json` 仍是滚动的上一版保存。
4. **批量删除用完整快照**：`_undo = {"kind":"batch_cheats","snapshot":[...]}`，撤销时整份方案还原，不逐条拼。
5. **模板诚实标注**：GTA III / SA 只录公开秘籍文本，`verified=False`、默认不绑热键、UI 灰显 + 备注前缀，套用前二次确认。
6. **向下兼容**：v3 新字段全部可选；`--export-v2` 剥离新字段，产物可被 1.6/1.7/1.8 读取（旧程序忽略 `games`）。

## 验证

- 单测 **134 条**（1.8 的 89 + 1.9 的 45）：v3 迁移 20 条、包 15 条、模板/导入 9 条、GUI 对话框构建 1 条；5 份历史配置样本零丢失
- ruff（主文件 + vcct/）0 告警；`--selftest` 全过（新增 `[2e]` 段验证迁移链 / 包 / 文本导入 / 模板，含真实注入探针与 GUI 冒烟）
- `--export-v2` CLI 实测导出结构为 version 2

## 待真机验证

包导入 diff 勾选 / 冲突覆盖、导出→改→导入往返、批量多选四项、撤销整份快照、GTA III/SA 模板灰显、文本粘贴预览与报错行号。
