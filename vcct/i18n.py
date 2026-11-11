# -*- coding: utf-8 -*-
"""2.1：表驱动多语言（中 / 英），零第三方依赖。

实现取舍
--------
* 以**中文原文为 key** 做映射：不必给几百处字符串逐一改名，新增文案只要往
  `EN_TEXT` 加一条即可；没映射到的保持中文（不会显示空白或 key 名）。
* 默认 `zh`，与 1.6～2.0 行为完全一致；切换语言写进 `settings.locale`，
  重启后生效（重建所有控件比运行时逐个改更可靠，也让 Tab 顺序保持不变）。
* 覆盖范围：主界面可见控件、更多菜单、右键菜单、设置页与主要弹窗的静态文案、
  Treeview 表头。**日志、诊断报告、异常文本与帮助长句保留中文**——译文会
  掩盖排查线索，这是有意的设计，文档里明确标注。
* `apply_locale_to_widgets` 在控件树建成后遍历替换，纯 UI 后处理，不碰数据。
"""
from __future__ import annotations

import re

from .const import APP_NAME

LOCALES = ("zh", "en")
DEFAULT_LOCALE = "zh"
_current = DEFAULT_LOCALE

EN_TEXT: dict[str, str] = {
    # 主工具条 / 按钮
    "方案": "Profile", "分组": "Group", "搜索": "Search", "清空": "Clear",
    "⌨ 热键总览": "⌨ Hotkeys", "⚙ 设置…": "⚙ Settings…", "⋯ 更多": "⋯ More",
    "⏸ 暂停热键": "⏸ Pause hotkeys", "▶ 恢复热键": "▶ Resume hotkeys",
    "▶ 发送所选 (Enter)": "▶ Send Selected (Enter)", "■ 停止 (Esc)": "■ Stop (Esc)",
    "添加": "Add", "编辑": "Edit", "删除": "Delete", "撤销": "Undo",
    "保存": "Save", "取消": "Cancel", "确定": "OK", "关闭": "Close",
    "捕获": "Capture", "清除": "Clear", "全选": "Select all",
    "清空选择": "Clear selection", "仅选新增": "New only", "套用": "Apply",
    "完成 ✔": "Finish ✔", "下一步 →": "Next →", "← 上一步": "← Back",
    "跳过向导": "Skip wizard", "解析预览": "Parse preview",
    "立即重启": "Restart now", "切换目录": "Switch folder",
    "复制配置到另一目录": "Copy config to other folder",
    "↻ 重新检测": "↻ Re-detect", "↻ 重新检测占用": "↻ Re-detect conflicts",
    "↻ 重新注册快捷键": "↻ Re-register hotkeys", "↻ 重发所选": "↻ Re-send selected",
    "▶ 运行注入自检": "▶ Run injection self-test",
    "⚠ 以管理员身份重启": "⚠ Restart as administrator",
    "以管理员身份重启": "Restart as administrator",
    "从上一版备份恢复": "Restore from previous backup",
    "打开日志目录": "Open log folder", "恢复默认秘籍表": "Restore default cheats",
    "清空使用统计": "Clear usage stats", "清空统计": "Clear stats",
    "清空历史": "Clear history", "发送历史": "Send history",
    "发送历史（最近 50 次）": "Send history (last 50)",
    "快捷键总览": "Hotkey overview", "设置…": "Settings…",
    "首次启动向导（Ctrl+F1）": "First-run wizard (Ctrl+F1)",
    "重新运行首次启动向导": "Re-run first-run wizard",
    "环境诊断": "Environment diagnosis",
    "环境诊断（检查权限 / 前台 / 注入）": "Environment diagnosis (privilege / foreground / injection)",
    "导出整包（设置 + 全部方案 + 统计）": "Export full bundle (settings + profiles + stats)",
    "导入整包…": "Import bundle…", "导出为文本…": "Export as text…",
    "导出 v2 兼容配置…": "Export v2-compatible config…",
    "从文本/CSV 粘贴导入…": "Paste import from text/CSV…",
    "套用游戏模板…": "Apply game template…",
    "秘籍包管理（.vcpack）…": "Cheat pack manager (.vcpack)…",
    "秘籍包管理（.vcpack）": "Cheat pack manager (.vcpack)",
    "从文本 / CSV 粘贴导入": "Paste import from text / CSV",
    "套用游戏模板": "Apply game template",
    "编辑秘籍": "Edit cheat", "添加秘籍": "Add cheat",
    "编辑切换规则": "Edit switch rule", "添加切换规则": "Add switch rule",
    "绑定快捷键": "Bind hotkey", "请按下新的组合键": "Press the new key combination",
    "跟随全局": "Follow global", "发送间隔": "Send interval",
    "名称": "Name", "快捷键": "Hotkey", "启用这条规则": "Enable this rule",
    "代码只填字母/数字（区分大小写无关，游戏内不区分）。":
        "Code: letters/digits only (case-insensitive in game).",
    "Esc 取消 · Backspace 清除绑定\n": "Esc to cancel · Backspace to clear\n",
    "窗口关键字（逗号分隔）": "Window keywords (comma separated)",
    "拾取当前窗口": "Pick current window",
    "每字间隔 (ms)": "Interval per char (ms)", "ms / 字": "ms / char",
    "套用「经典版」预设": "Apply Classic preset",
    "套用「决定版」预设": "Apply Definitive preset",
    "注入自检": "Injection self-test", "重新注册全部快捷键": "Re-register all hotkeys",
    "快捷键与自检": "Hotkeys & self-test", "目标窗口": "Target window",
    "发送速度": "Send speed", "维护": "Maintenance",
    "全局暂停热键": "Global pause hotkey", "包信息": "Pack info",
    "使用统计": "Usage stats", "配置与日志": "Config & logs",
    "数据目录": "Data folder", "方案管理": "Profile management",
    "目标规则（v2.0，配置驱动）": "Target rules (v2.0, config-driven)",
    "从 games 规则生成 targets": "Generate targets from games rules",
    "  常规  ": "  General  ", "  输入  ": "  Input  ",
    "  游戏  ": "  Game  ", "  数据  ": "  Data  ",
    "  导入包  ": "  Import  ", "  导出包  ": "  Export  ",
    "  已安装  ": "  Installed  ",
    "游戏内悬浮提示（发送结果显示在右下角，不抢焦点）":
        "In-game toast (result at bottom-right, does not steal focus)",
    "关闭窗口时最小化到托盘（取消勾选 = 关闭即退出）":
        "Minimize to tray on close (uncheck = close means quit)",
    "按游戏自动切换方案（规则在「游戏」页配置）":
        "Auto-switch profile by game (rules on the Game tab)",
    "启用扩展点（前置/后置钩子，高级功能，默认关闭）":
        "Enable hooks (before/after, advanced, off by default)",
    "在任何窗口按这个键可一键暂停/恢复全部秘籍热键。":
        "Press this key anywhere to pause/resume all cheat hotkeys.",
    "仅当目标窗口在前台时才发送（强烈建议开启）":
        "Only send when target window is in foreground (strongly recommended)",
    "发送时绕开中文输入法（中文 IME 会吞掉注入的字符）":
        "Bypass Chinese IME while sending (IME swallows injected chars)",
    "丢字 → 调大间隔；输入太慢 → 调小。单条秘籍可在编辑对话框里单独覆盖。":
        "Dropped chars: increase interval; too slow: decrease. Per-cheat override available.",
    "游戏窗口在前台且稳定 0.8 秒后，自动切换到规则指定的方案。\n推荐按进程名（exe）匹配；发送过程中绝不切换。":
        "After the game stays in foreground for 0.8s, switch to the configured profile.\n"
        "Prefer exe matching; never switches during a send.",
    "冲突项覆盖本地": "Overwrite conflicts",
    "自动避让热键冲突": "Auto-avoid hotkey conflicts", "导入所选 →": "Import selected →",
    "选择 .vcpack / .json 文件…": "Choose .vcpack / .json file…",
    "未选择文件": "No file selected", "移除选中记录": "Remove selected record",
    "导出为 .vcpack…": "Export as .vcpack…",
    "把当前方案的秘籍导出成一个可分享的 .vcpack 文件。":
        "Export the current profile as a shareable .vcpack file.",
    "导入有效行 →": "Import valid rows →", "跳过与当前方案重复的代码":
        "Skip codes already in this profile",
    "双击一行也可重发；重发按当前方案中的代码查找。":
        "Double-click a row to re-send; lookup by code in the current profile.",
    "选择一套模板：会替换秘籍表并（若有）套用对应发送参数。":
        "Pick a template: replaces the cheat list and (if any) applies its send preset.",
    "第 1 步 / 3：选一套发送参数": "Step 1 / 3: choose send parameters",
    "第 2 步 / 3：验证按键能送达": "Step 2 / 3: verify key injection",
    "第 3 步 / 3：快捷键冲突检查": "Step 3 / 3: hotkey conflict check",
    "✔ 注入链路正常": "✔ Injection chain OK",
    "自动分配可用键": "Assign free keys",
    "换一个可用键（本行）": "Pick a free key (this row)",
    "自动分配全部冲突项": "Auto-fix all conflicts", "复制秘籍代码": "Copy cheat code",
    "批量操作（选中多条时可用）": "Batch actions (multi-select)",
    "批量改分组…": "Batch change group…", "批量分配空闲热键": "Batch assign free hotkeys",
    "批量设置发送间隔…": "Batch set interval…", "批量删除…": "Batch delete…",
    "初始化…": "Initializing…", "注册快捷键…": "Registering hotkeys…",
    "已暂停 · 仅暂停键生效…": "Paused · only pause key works…",
    "⚪ 未检测到游戏": "⚪ Game not detected", "⚪ 检测游戏…": "⚪ Detecting game…",
    "自检中…": "Testing…",
    "✔ 没有冲突，全部快捷键已就绪。\n\n": "✔ No conflicts, all hotkeys ready.\n\n",
    "导入完成，可继续选择下一个包。": "Import done; you can pick another pack.",
    "次数 ↓": "Count ↓", "最近": "Last used",
    "检查更新…": "Check for updates…",
    "界面语言（重启后生效）": "UI language (applies after restart)",
    "显示更新入口（仅打开 Release 页，程序不联网、不自动下载；重启后生效）":
        "Show update menu (opens Release page only; no network calls, no downloads; after restart)",
    f"设置 — {APP_NAME}": f"Settings — {APP_NAME}",
    f"欢迎使用 {APP_NAME}": f"Welcome to {APP_NAME}",
    # Treeview 表头
    "#": "#", "秘籍代码": "Cheat code", "状态": "State", "次数": "Count", "备注": "Note",
    "规则名称": "Rule name", "匹配方式": "Match by", "匹配内容": "Pattern",
    "目标方案": "Target profile", "启用": "Enabled",
    "时间": "Time", "结果": "Result", "耗时(s)": "Duration (s)", "说明": "Detail",
    "条目": "Item", "所属方案": "Profile", "勾选": "Pick",
    "行号": "Line", "代码": "Code", "方式": "Type", "包版本": "Pack ver.",
    "导入时间": "Imported at", "包名": "Pack", "作者": "Author", "游戏": "Game",
    # 2.2 Nova UI
    "切换主题": "Toggle theme", "⌘K  命令面板": "⌘K  Command palette",
    "命令面板": "Command palette",
    "↑↓ 选择 · Enter 执行 · Esc 关闭": "↑↓ select · Enter run · Esc close",
    " 秘籍": " Cheats", " 热键": " Hotkeys", " 内容": " Content",
    " 数据": " Data", " 帮助": " Help",
    "游戏 ●": "Game ●", "热键 ●": "Hotkeys ●", "发送 ●": "Send ●",
    "配置 ●": "Config ●", "中文 ●": "中文 ●",
    "界面（Nova UI）": " UI (Nova UI) ",
    "布局": "Layout", "主题": "Theme", "密度": "Density",
    "Nova（新版）": "Nova (new)", "经典（旧版，可回退）": "Classic (legacy, fallback)",
    "浅色": "Light", "深色": "Dark", "舒适": "Comfortable", "紧凑": "Compact",
}
# 注：上面若出现同义中文，dict 会自动保留最后一条；运行时不影响正确性。

# 动态状态文案（带数字）：正则替换，未命中则保留原文
_DYNAMIC = (
    (re.compile(r"^共 (\d+) 条 · 今日 (\d+) 次$"), r"Total: \1 · Today \2"),
    (re.compile(r"^匹配 (\d+) / 共 (\d+) 条 · 今日 (\d+) 次$"), r"Matched \1 / \2 · Today \3"),
    (re.compile(r"^✔ (\d+) 个快捷键全部生效$"), r"✔ \1 hotkeys active"),
    (re.compile(r"^⚠ (\d+) 个快捷键不可用（(\d+) 个生效）$"), r"⚠ \1 hotkeys unavailable (\2 active)"),
    (re.compile(r"^已暂停（(.+) 恢复）$"), r"Paused (press \1 to resume)"),
)


def set_locale(locale: str) -> str:
    global _current
    _current = locale if locale in LOCALES else DEFAULT_LOCALE
    return _current


def get_locale() -> str:
    return _current


def t(text: str) -> str:
    """翻译一段界面文本；未收录或中文模式下原样返回。"""
    if _current != "en" or not isinstance(text, str):
        return text
    if text in EN_TEXT:
        return EN_TEXT[text]
    for pattern, repl in _DYNAMIC:
        if pattern.match(text):
            return pattern.sub(repl, text)
    return text


def apply_locale_to_widgets(root, menus=()) -> int:
    """遍历控件树 + 菜单 + 表头替换可见文本；返回替换条数（纯 UI 后处理）。"""
    if _current != "en":
        return 0
    changed = 0

    def walk(widget):
        nonlocal changed
        try:
            txt = widget.cget("text")
        except Exception:
            txt = None
        if isinstance(txt, str) and txt:
            new = t(txt)
            if new != txt:
                try:
                    widget.configure(text=new)
                    changed += 1
                except Exception:
                    pass
        try:
            for col in widget.cget("columns"):
                head = widget.heading(col, "text")
                new = t(head)
                if new != head:
                    widget.heading(col, text=new)
                    changed += 1
        except Exception:
            pass
        try:
            children = widget.winfo_children()
        except Exception:
            return
        for child in children:
            walk(child)

    walk(root)
    for menu in menus:
        if menu is None:
            continue
        try:
            last = menu.index("end")
            if last is None:
                continue
            for i in range(last + 1):
                try:
                    label = menu.entrycget(i, "label")
                    new = t(label)
                    if new != label:
                        menu.entryconfigure(i, label=new)
                        changed += 1
                except Exception:
                    continue
        except Exception:
            continue
    return changed
