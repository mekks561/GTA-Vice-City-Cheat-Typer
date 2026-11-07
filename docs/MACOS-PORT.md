# VC-Cheat-Typer macOS 平台支持方案

> 对应需求：**1.6（macOS 平台支持）**
> 基线：v1.6（Windows，commit `481d6ff`）｜ 文档日期：2026-11-05
> 关联文档：`docs/ROADMAP-1.7-2.0.md`（1.7-D 平台抽象是本文档的前置）

---

## 一、结论先行

**能做，但不是"重新打包一次"，而是一次平台抽象改造。** macOS 没有 `SendInput / RegisterHotKey / ImmAssociateContext`，现有代码 **137 处 Win32 调用点**全部需要一个 macOS 等价实现：

| Windows 能力 | macOS 等价物 | 权限要求 |
|---|---|---|
| `SendInput` + scan code | **CGEventPost**（CoreGraphics），文本走 `CGEventKeyboardSetUnicodeString`、游戏走物理键码 | 辅助功能（Accessibility） |
| `RegisterHotKey` | **RegisterEventHotKey**（Carbon HIToolbox） | **无需权限**（关键优势） |
| 前台窗口判定 | `CGWindowListCopyWindowInfo`（取进程名/PID） | 无需权限（窗口标题才需录屏权限，本文档主动避开） |
| `ImmAssociateContext`（绕 IME） | 不需要——unicode 事件 + 物理键码本身不受输入法影响 | — |
| `LOCALAPPDATA` 回退 | `~/Library/Application Support/VC-Cheat-Typer/` | — |

**推荐路线**：单一 Python 代码库 + 平台后端层（`vcct/core/platform/{win32,macos}.py`），tkinter UI 共用。**不引入 PyObjC 等第三方依赖**，系统框架一律走 ctypes，保持"零运行时依赖"这条资产。

---

## 二、目标与适用范围

### 2.1 目标（按优先级）

| 编号 | 目标 | 验收标准 |
|---|---|---|
| G1 | 在 Apple Silicon 与 Intel Mac 上均可启动并注入 | M 系列与 x86_64 各一台实机各跑通 5 条秘籍 |
| G2 | 全局热键可用，且**不申请多余权限** | 热键注册不触发任何系统授权弹窗；仅注入需要辅助功能 |
| G3 | 安装流程对非技术用户可完成 | 从下载到"按 F1 生效"≤ 5 步，文档可照做 |
| G4 | 缺权限时给出可执行的自救指引 | 未授权时界面明确提示 + 一键跳转系统设置，而非静默无反应 |
| G5 | 可诊断 | `--doctor` 一条命令输出环境/权限/注入自检报告，可粘贴给维护者 |

### 2.2 适用范围（**必须先读，决定这个方案对你是否有用**）

| 场景 | 原生 macOS 版是否适用 | 说明 |
|---|---|---|
| GTA VC **决定版**（App Store / Rockstar，原生 macOS） | ✅ 主要目标 | 决定版有 macOS 原生版本，是本方案的首要服务对象 |
| 其他**原生运行**的 Mac 游戏 / 模拟器 / 软件 | ✅ 适用 | 目标规则可配置，不限于 GTA |
| 游戏跑在 **CrossOver / Whisky / Wine** 里 | ⚠️ 大概率适用 | 这类游戏本质是 macOS 进程，CGEvent 会送到它的窗口；**需实机验证** |
| 游戏跑在 **Parallels / VMware 虚拟机**里 | ⚠️ 部分适用 | HID 层事件通常能透传，但虚拟机常自行接管输入，需实测 |
| **2002 年原版 VC（Mac 移植版）** | ❌ 不适用 | 32 位应用，macOS 10.15 起已彻底无法运行，与本方案无关 |
| 需要 App Store 上架 | ❌ 不可能 | App Sandbox 禁止向其他应用投递事件，这条路直接堵死 |

**一句话**：如果你在 Mac 上跑的是**决定版**或 Wine 包装的游戏 → 本方案有用；如果你跑的是被 CrossOver 包着的 Windows 原版，**Windows 版 exe + CrossOver 可能比原生 Mac 版更省事**——这点会写进文档，避免用户白折腾。

### 2.3 明确不做（本期）

- 不做 Mac App Store 分发（沙箱冲突，技术上不可行）
- 不做**公证（notarization）**：需 Apple Developer Program（$99/年），与"不买证书"的既有决策一致；改为"ad-hoc 签名 + 完整放行指引"（见 §七 风险 R-M4）
- 不做 Mac 专属 UI（托盘/向导/自动切方案沿用现有 tk 实现，能跑即可；完整对齐留给 v2.1）
- 不做 macOS 12 以下、PowerPC、32 位
- 不做内存读写/注入 dylib（法律与反作弊风险，与 Windows 侧一致）

---

## 三、兼容性要求

### 3.1 芯片架构

| 架构 | 支持级别 | 说明 |
|---|---|---|
| **arm64（Apple Silicon，M1–M4）** | 一等公民 | 主要验证目标；Python 3.11/3.12 universal2 |
| **x86_64（Intel）** | 支持 | 通过 universal2 单包或独立产物 |
| Rosetta 2 转译 | 可用但不推荐 | 转译下 CGEvent 时序略有抖动，丢字率上升，建议用原生 arm64 包 |

**产物策略**：优先 **universal2 单包**（需 universal2 Python + Tcl/Tk 8.6.12+，python.org 官方安装包已满足）。若 PyInstaller 打 universal2 出现 Tcl/Tk 架构混装问题（常见），退化为**两个独立产物**：
`VC-Cheat-Typer-macOS-arm64.zip` / `VC-Cheat-Typer-macOS-x86_64.zip`，Release 说明里明确该下哪个。

### 3.2 系统版本

- **最低支持：macOS 12 Monterey**
- 主要验证：**macOS 13 Ventura / 14 Sonoma / 15 Sequoia / 26 Tahoe**
- 理由：Monterey 是仍能装 python.org universal2 + Tk 8.6.12 的合理下限；更低版本用户占比极低且 Apple 已停止安全更新。
- **Tk 版本要求 ≥ 8.6.12**：更早的 Tk 8.6 在 Retina 上是位图拉伸（模糊），与 Windows 侧 1.6 做的高 DPI 适配是同一类问题。

### 3.3 依赖

| 类别 | 内容 | 说明 |
|---|---|---|
| 运行依赖 | **零第三方包** | 仅 stdlib + tkinter + ctypes 调系统框架 |
| 系统框架 | CoreGraphics、CoreFoundation、ApplicationServices、Carbon(HIToolbox) | 均为系统自带，通过 ctypes 加载，不打包、不下载 |
| Python（源码运行） | 3.10+，**必须含 tkinter** | Homebrew 的 python 默认**不含** tkinter，需 `brew install python-tk`；推荐 python.org 官方包 |
| 构建依赖 | PyInstaller ≥ 6.x、`codesign`（Xcode CLT） | 仅打包机需要 |

### 3.4 权限矩阵（核心）

| 权限 | 是否必需 | 触发时机 | 用户路径 |
|---|---|---|---|
| **辅助功能 Accessibility** | ✅ **必需**（唯一硬权限） | 首次注入前检测 `AXIsProcessTrusted()` | 系统设置 → 隐私与安全性 → 辅助功能 → 勾选 VC-Cheat-Typer |
| 输入监控 Input Monitoring | ❌ 不需要 | — | 采用 RegisterEventHotKey 而非 CGEventTap 监听，正是为了避开它 |
| 屏幕录制 | ❌ 不需要 | — | 只取进程名/PID，不读窗口标题 |
| 通知 | ⚠️ 可选 | 开启"发送成功提示"时 | 首次弹系统询问 |
| 完全磁盘访问 / 自动化 | ❌ 不需要 | — | — |

**设计要点**：只有一项硬权限，且**热键本身不需要权限**——这决定了首次启动可以"先让用户看到界面、先试用热键"，只在真正注入时才引导授权，心理门槛低得多。

---

## 四、技术方案

### 4.1 平台抽象层（前置改造）

1.7-D 已规划把单文件拆成 `vcct/`。本方案要求把它进一步分为：

```
vcct/
├── core/
│   ├── platform/
│   │   ├── base.py      Backend 抽象：send_text / send_key / register_hotkeys / frontmost / app_paths / doctor
│   │   ├── win32.py     现有 137 处 Win32 调用整体搬家（行为零变更）
│   │   ├── macos.py     本文档新增实现
│   │   └── null.py      无后端（CI/无桌面环境跑纯逻辑测试用）
│   ├── sender.py        与平台无关：策略、队列、取消、日志
│   ├── hotkeys.py       与平台无关：组合键解析、冲突检测、候选键
│   └── store.py         与平台无关：v3 schema、迁移、路径通过 backend.app_paths()
└── ui/                  tkinter 共用；仅字体/菜单/快捷键文案做平台分支
```

**硬约束**：`sender.py` / `hotkeys.py` / `store.py` 不得直接 import `ctypes` 或任何 Win32/macOS 符号。这条约束同时也是 2.0"core 抽库"的验收条件——**macOS 支持本身就是平台抽象是否成功的唯一硬证据**。

预计需要新增/改造：`base.py` 约 120 行、`macos.py` 约 700–900 行、`win32.py` 为纯搬运。

### 4.2 按键注入

macOS 无 `SendInput`，用 **CGEventPost**，分两条路径：

| 用途 | 做法 | 理由 |
|---|---|---|
| **文本注入**（记事本/聊天/模拟器） | `CGEventCreateKeyboardEvent(source, 0, True)` + `CGEventKeyboardSetUnicodeString` 写入整串，再 post | 不依赖键码表与输入法，任意 Unicode 一条事件搞定；等价于 Windows 侧绕开 IME 的效果 |
| **游戏注入**（决定版等） | 逐字符生成 **物理键码**（`kVK_ANSI_A=0x00` … `kVK_ANSI_0=0x1D`），keyDown/keyUp 各一条，中间按 `key_hold_ms` 延时 | 游戏按帧轮询键盘状态，必须有独立的按下/抬起事件与足够 hold；物理键码不受输入法/键盘布局影响 |

统一走 `kCGHIDEventTap(0)`（进程能触达的最低层事件），事件源用 `CGEventSourceCreate(kCGEventSourceStateHIDSystemState)`。

**能力边界（必须写进 README）**：CGEvent 无法骗过使用 **raw HID / IOHIDManager 独占读取**的游戏。这类游戏只能靠外接硬件或系统级驱动，与本方案同类限制也存在于 Windows（DirectInput 部分场景）。决定版是否属于此类 **需实机验证**，验证不通过则在兼容性矩阵中标注。

**丢字处理**：macOS 事件队列在高负载/低帧率下同样会丢。沿用 Windows 侧的"逐字符间隔 + hold"模型，默认值建议 **60ms 间隔 / 30ms hold**（比 Windows 的 45/25 略保守），并保留"决定版"预设。

### 4.3 全局热键

**方案 A（推荐）**：`RegisterEventHotKey`（Carbon HIToolbox）

- 无需任何权限，且天然支持"其他应用前台时触发"
- 需要事件循环：起一个专用线程 + `CFRunLoopRun()`，通过 `InstallEventHandler` 挂到 `GetEventDispatcherTarget()` 接收 `kEventHotKeyPressed`
- **注意常量陷阱**：`RegisterEventHotKey` 的修饰键掩码与 CGEventFlags **完全不同**
  （`cmdKey=1<<8`、`shiftKey=1<<9`、`optionKey=1<<11`、`controlKey=1<<12`），不可复用 CGEvent 的 `kCGEventFlagMask*`
- 冲突检测：注册失败返回 `eventHotKeyExistsErr(-9878)`，语义等价于 Windows 的 `1409`，复用现有冲突提示与候选键分配逻辑

**方案 B（退路）**：`CGEventTap` 监听全局按键。需 Input Monitoring 或辅助功能权限，且要自己维护按键状态机、还要处理"不吞掉游戏按键"——复杂度与权限成本都更高，仅当 A 在目标系统版本上出现兼容问题时启用。

**macOS 特有的按键冲突**（必须在 UI 里提示）：

- 默认绑定 F1–F11，但 Mac 键盘的 F1/F2 默认是**亮度**、F3 是调度中心 → 用户需在 系统设置 → 键盘 里开启「**将 F1、F2 等键用作标准功能键**」，否则按 F1 只会调亮度
- 程序可读 `defaults read -g com.apple.keyboard.fnState`（1 = 已开启），未开启时在启动提示里给一键跳转
- `Cmd+Space`、`Cmd+Tab`、`Ctrl+↑` 等被系统占用，`is_safe_binding` 需增加一份 macOS 保留键黑名单

**组合键语义映射**（避免用户困惑）：

| Windows 习惯 | macOS 对应 | 说明 |
|---|---|---|
| Ctrl | **Control** | 一对一保留 |
| Alt | **Option** | 一对一保留 |
| Win 键 | **Command** | 语义最接近（系统级修饰键） |

界面在 macOS 上直接显示 `⌃⌥P` 这类符号，同时设置页提供"显示为文字"选项。

### 4.4 前台与目标识别

`CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements)` 取第一层（`kCGWindowLayer == 0`）窗口的 `kCGWindowOwnerName`（应用名）与 `kCGWindowOwnerPID`。

- **不读 `kCGWindowName`**（窗口标题）——macOS 10.15 起该字段需屏幕录制权限，读了等于强制用户多授一项权限，不划算
- 目标匹配规则改为按 **应用名 / bundle id / 进程名** 匹配（Windows 侧原有的"标题关键字"在 mac 上降级为可选，需用户显式开启）
- 复用现有 3s 轮询节流；macOS 上改为 1.5s（CGWindowList 开销远低于 EnumWindows），但发送期间暂停轮询

### 4.5 数据与路径

| 项 | Windows | macOS |
|---|---|---|
| 配置目录 | exe 同目录（可写时）否则 `%LOCALAPPDATA%` | **`~/Library/Application Support/VC-Cheat-Typer/`**（首选，不写 `.app` 内部） |
| 日志 | `logs/app.log` | `~/Library/Logs/VC-Cheat-Typer/app.log`（符合 mac 惯例，Console.app 可见） |
| 备份/隔离文件 | 同目录 | 配置目录内，命名规则不变 |

**为什么不写 `.app` 旁边**：`.app` 是只读签名的包；且未公证应用从"下载"目录首次启动会触发 **App Translocation（路径随机化）**，程序实际运行在一个随机只读路径下，写配置必失败。这是 macOS 移植最经典的坑，必须在代码层规避（统一走 `Application Support`），而不是靠文档提醒用户。

### 4.6 UI 差异（最小改动）

| 项 | 处理 |
|---|---|
| 字体 | 用 `SF Pro Text` / `Helvetica Neue` 替代 `Microsoft YaHei UI`；中文自动回落 PingFang SC |
| 菜单栏 | 补一个最小 App 菜单（关于/退出 `Cmd+Q`/设置 `Cmd+,`），否则 tk 应用在 Mac 上菜单栏是空的，很怪 |
| 窗口关闭 | 默认"关闭 = 隐藏到 Dock"（mac 习惯），退出走 `Cmd+Q` |
| DPI | macOS 是逻辑点 + Retina 自动缩放，不需要 Windows 那套 DPI 感知；但需 `NSHighResolutionCapable=true` 才能拿清晰渲染 |
| 右键菜单 | 保持；补充 `Ctrl+Click` 等价（tk 在 mac 上已映射） |
| 快捷键文案 | `Ctrl+F` → `Cmd+F` 等按平台替换 |

### 4.7 打包与签名

```bash
# 构建 .app（--windowed 在 mac 上等价于 --osx-bundle-identifier + BUNDLE）
pyinstaller --windowed --name VC-Cheat-Typer \
  --osx-bundle-identifier com.mekks561.vcct \
  --icon assets/icon.icns vc_cheat_typer.py

# ad-hoc 签名（无证书，仅让 Gatekeeper 认为"结构完整"）
codesign --force --deep --sign - "dist/VC-Cheat-Typer.app"
```

`Info.plist` 需显式包含：`NSHighResolutionCapable=true`、`LSMinimumSystemVersion=12.0`、`CFBundleIdentifier`（**必须固定**，TCC 授权按 bundle id + 签名记录，改了就要重新授权）。

---

## 五、安装与首次启动流程

目标：**5 步内从下载到"按 F1 生效"**，且每一步失败都有明确下一步。

| 步骤 | 用户动作 | 程序行为 | 失败时的引导 |
|---|---|---|---|
| 1 | 下载 `VC-Cheat-Typer-macOS-universal2.zip`，解压 | — | 若提示"无法打开，因为 Apple 无法检查…"→ 见 §七 Q1 |
| 2 | **拖到「应用程序」文件夹**（关键） | 首次启动检测自身路径是否含 `/AppTranslocation/` 或位于下载目录 → 提示"请先移到「应用程序」" | 检测到 Translocation 时直接弹提示并给"打开应用程序文件夹"按钮 |
| 3 | 右键 → **打开** → 确认打开 | 正常启动，创建 `~/Library/Application Support/VC-Cheat-Typer/` | — |
| 4 | 看到首屏提示"需要辅助功能权限才能注入" → 点「去授权」 | `AXIsProcessTrusted()` 为假时显示；按钮执行 `open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"` | 授权后回来点「我已授权」→ 程序复查并立即生效（无需重启） |
| 5 | 点「注入自检」→ 在弹出窗口按 F1 | 用原生 tk 输入框做探针（mac 上事件投递到自身窗口同样受 AX 约束，能真实反映权限状态） | 自检失败 → 输出 `--doctor` 报告 |

**首次启动还会做三件事**（沿用 Windows 侧向导思路）：① 检测 `com.apple.keyboard.fnState`，未开标准功能键则提示；② 检测 F1–F11 是否被系统/其他软件占用并列出；③ 询问是否复制一份预置方案（VC 决定版 / 通用）。

**卸载**：删除 `.app` + 删除 `~/Library/Application Support/VC-Cheat-Typer`，并在系统设置里移除辅助功能条目（程序内提供「打开授权设置」入口，卸载说明附在 README）。

---

## 六、运行验证

### 6.1 `--doctor` 自检（新增，跨平台统一入口）

一条命令输出可粘贴的诊断报告：

```
VC-Cheat-Typer 2.0.0 (darwin)
OS          : macOS 14.6.1 (23G93) / arm64
Python      : 3.12.4 / Tk 8.6.13 (aqua)
Bundle      : com.mekks561.vcct
Path        : /Applications/VC-Cheat-Typer.app  (translocation: no)
Data dir    : ~/Library/Application Support/VC-Cheat-Typer  (writable: yes)
Accessibility: GRANTED
Standard Fn keys: ON
Frontmost   : Finder (com.apple.finder)
Hotkeys     : 28 registered, 0 conflict
Injection   : unicode probe OK (0.42s), keycode probe OK (0.38s)
Log         : ~/Library/Logs/VC-Cheat-Typer/app.log
```

### 6.2 自动化验证（可进 CI 的部分）

| 检查 | 能否在 GitHub Actions macOS runner 上跑 | 说明 |
|---|---|---|
| 纯逻辑（store/迁移/组合键解析/候选键） | ✅ | `macos-14`(arm64) + `macos-13`(x86_64) 双架构矩阵 |
| `import vcct.core` 不依赖 tkinter | ✅ | 用 `sys.modules` 断言 |
| `--doctor --no-gui` 环境探测 | ✅ | 权限必然是 NOT GRANTED，只断言"能正确报告未授权" |
| GUI 建窗 | ⚠️ 不稳定 | runner 无交互会话，Tk 可能失败 → `continue-on-error` |
| **真实注入 / 热键** | ❌ | 需要 TCC 授权与交互会话，**只能人工实机** |

### 6.3 人工实机验证清单（发布门槛）

必须在 **M 系列 + Intel 各一台**上全部通过：

1. 未授权状态下点「注入自检」→ 明确提示缺权限，且给出可点击的设置入口（不得静默失败）
2. 授权后（不重启程序）→ 自检立即通过
3. 在 TextEdit 里按热键 → 完整输出秘籍文本，无丢字、无大小写错乱
4. 在游戏（VC 决定版）内按 F1 → 满血；F8 → 坦克；连续 5 条秘籍全中
5. 按暂停键 `⌃⌥P` → 在 TextEdit 按 F1 **零注入**；再按一次恢复生效
6. 连按两个不同秘籍热键 → 只出现完整一条，无交错（验证 1.7-B 单飞在 mac 侧成立）
7. 中文/日文输入法激活状态下注入 → 仍然正确（unicode 事件路径）
8. 从「下载」直接双击（不移动）→ 程序提示"请移到应用程序文件夹"而非静默写配置失败
9. 重启系统后 → 授权仍在、热键仍生效
10. 换一个 macOS 大版本（如 13 → 15）→ 无布局错乱

---

## 七、常见问题与应对

| # | 现象 | 原因 | 处置 |
|---|---|---|---|
| Q1 | 提示"**已损坏，无法打开**"或"Apple 无法检查是否包含恶意软件" | 未公证 + 浏览器加了 quarantine 隔离属性 | ① 右键 →「打开」→「打开」；Sonoma 起若被拦：系统设置 → 隐私与安全性 → 点「仍要打开」；② 或终端执行 `xattr -dr com.apple.quarantine "/Applications/VC-Cheat-Typer.app"` |
| Q2 | 双击后**没有任何反应**，Dock 也没图标 | App Translocation 或签名损坏 | 先移到「应用程序」；仍无反应看 `~/Library/Logs/VC-Cheat-Typer/app.log` 与 Console.app；`codesign -dv --verbose=2` 查签名 |
| Q3 | 按热键**完全没反应**（程序在运行） | 辅助功能未授权；或授权后程序被替换导致签名变化 | 系统设置 → 隐私与安全性 → 辅助功能：**先删除旧条目**，再重新添加当前 `.app`（同 bundle id 换签名会保留旧记录，这是最常见的"已勾选却不生效"） |
| Q4 | 按 F1 屏幕只是**变暗/变亮** | Mac 键盘 F1/F2 默认是亮度键 | 系统设置 → 键盘 → 勾选「将 F1、F2 等键用作标准功能键」；程序启动时会检测并提示 |
| Q5 | 热键在别的应用里生效，**进游戏就失效** | 游戏为独占全屏且接管输入；或使用 raw HID 读取 | 改窗口化/无边框窗口；若是 raw HID 类游戏，CGEvent 无法穿透，属方案边界（见 §4.2） |
| Q6 | 发送**丢字 / 顺序错乱** | 间隔过短；游戏帧率低；Rosetta 下时序抖动 | 把间隔提到 80–100ms、hold 到 40ms；确认使用 arm64 原生包而非 Rosetta |
| Q7 | 中文输入法激活时注入成乱码/被吞 | 走了键码路径 | 文本场景走 unicode 事件路径（默认已如此）；确认 `disable_ime` 等价项在 mac 上走 unicode 分支 |
| Q8 | 配置**不保存**，每次启动都回到默认 | 从下载目录直接运行（Translocation）→ 只读路径；或 `.app` 内相对路径不可写 | 移到「应用程序」；确认数据目录为 `~/Library/Application Support/VC-Cheat-Typer`；`--doctor` 会显示 `writable` |
| Q9 | 每次重新构建后都要**重新授权** | ad-hoc 签名的签名值随构建变化，TCC 视为不同应用 | 开发期可接受；发布版固定产物不重建即可；长期解法是正式证书签名（见 R-M4） |
| Q10 | 程序在 Dock 里但**窗口找不到** | 窗口被移出屏幕（多显示器变更） | 菜单「窗口 → 居中」；程序启动时校验窗口位置是否在任一屏幕内，否则自动居中 |
| Q11 | Intel Mac 上启动报"**无法打开，因为不受支持**" | 下成了 arm64 单架构包 | 按 Release 说明下载 x86_64 包或 universal2 包；`uname -m` 自查 |
| Q12 | 全屏游戏里**看不到提示浮层** | 独占全屏无法叠加窗口 | 改为无边框窗口化；或关闭浮层（本就非必需） |

---

## 八、落地路径与版本归属

**前置**：必须等 **1.7-D（拆包）** 完成。在 2900 行单文件上直接加 macOS 分支，等于给两个平台同时埋雷。

**建议归属**：作为 **v2.0 的第二个交付目标**（与 core 抽库并行）——

理由：2.0 的核心命题是"输入引擎可被复用"，而**第二个平台的真实实现是检验这个抽象是否成立的唯一硬证据**。如果 macOS 后端能只写 `platform/macos.py` 就接上，说明抽象成功；如果被迫改 `sender.py`，说明抽象失败，应当立即返工而不是硬推。

| 任务 | 内容 | 估时 |
|---|---|---|
| M-01 | `platform/base.py` 接口 + `win32.py` 纯搬运 + `null.py` | 2.0d |
| M-02 | `macos.py`：CGEvent 注入（unicode + 键码双路径）、hold/间隔 | 2.0d |
| M-03 | 全局热键（RegisterEventHotKey + CFRunLoop 线程 + 冲突检测） | 2.0d |
| M-04 | 前台/目标识别（CGWindowList，仅进程维度）+ 保留键黑名单 | 1.0d |
| M-05 | 路径与日志迁移、Translocation 检测、权限引导 UI | 1.0d |
| M-06 | `--doctor` + 权限状态呈现 + fnState 检测 | 1.0d |
| M-07 | 打包 universal2/双产物、ad-hoc 签名、Info.plist | 1.5d |
| M-08 | 文档（安装/FAQ/兼容性矩阵）+ 双架构实机验证 | 1.5d |

合计 **12 人日**（≈ 24 自然日 @ 2h/天）。若 2.0 已因排期紧张，可整体降级为 **v2.1**，把 2.0 的 17 人日守住；**不建议把 macOS 塞进 1.8/1.9** —— 那两个版本的改动集中在 UI 与数据层，混入平台层会让回归面失控。

---

## 九、风险登记

| # | 风险 | 概率/影响 | 缓解 |
|---|---|---|---|
| R-M1 | **CGEvent 对目标游戏无效**（raw HID / 反作弊 / 独占全屏） | 中 / **高** | 第 1 周就先做注入可行性验证（只写 100 行探针，跑通决定版再投入其余 11 人日）；不通过则本方案只对"原生窗口应用/模拟器"承诺 |
| R-M2 | PyInstaller universal2 打包时 Tcl/Tk 架构冲突 | 高 / 中 | 退化为双架构独立产物；CI 里对两个 runner 各自打包，不在单机拼 universal2 |
| R-M3 | TCC 授权"已勾选但不生效"（签名变化/条目残留） | 高 / 中 | 文档给"删除旧条目再添加"的标准动作；程序内检测到"授权为真但注入自检失败"时直接提示这一条 |
| R-M4 | 未公证带来的安装摩擦劝退用户 | **高** / 中 | 短期：完整放行指引 + 首启检测 + 一键去隔离命令；中期：若下载量证明有真实需求，再评估 $99 公证（这也是与 Windows 侧决策的差异点：Windows 只是 SmartScreen 警告，macOS 是硬拦截） |
| R-M5 | 平台抽象被 macOS 需求反推着改坏 Windows 行为 | 中 / **高** | 每次改 `base.py` 必须同时跑 Windows 全量回归（单测 + selftest + GUI 21 项）；CI 增加 macOS 逻辑层矩阵，但不允许 mac 侧改动绕过 win 侧测试 |
| R-M6 | macOS 上 tkinter 观感与 Windows 差距大，被认为"半成品" | 中 / 低 | 明确 MVP 定义：功能可用优先，UI 对齐留给 v2.1；README 如实说明 |
| R-M7 | 用户在 Mac 上其实该用 CrossOver 跑 Windows 版，白折腾 | 中 / 中 | §2.2 的判断表放在 README 最前面，先劝退错误路径 |

---

## 十、一句话总结

**macOS 支持不是"再打一个包"，而是把 137 处 Win32 调用换成一个可插拔后端**：注入换 CGEvent（文本走 unicode、游戏走物理键码）、热键换 RegisterEventHotKey（唯一不需要权限的方案）、前台判定换 CGWindowList（只取进程维度以避开录屏权限）、配置必须搬进 `Application Support`（躲开 Translocation）。

真正的风险只有一个：**CGEvent 能不能打进目标游戏**。所以第一步不是写 700 行 `macos.py`，而是写 100 行探针先在决定版里打出三个字符——打不进去，后面 11 人日都是白做。
