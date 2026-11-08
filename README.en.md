# VC-Cheat-Typer

[![CI](https://github.com/mekks561/GTA-Vice-City-Cheat-Typer/actions/workflows/ci.yml/badge.svg)](https://github.com/mekks561/GTA-Vice-City-Cheat-Typer/actions/workflows/ci.yml)

> A single-file, dependency-free Windows desktop tool that types GTA: Vice City cheat codes for you when you press a global hotkey.

[中文 README（完整文档）](README.md) · [Releases](https://github.com/mekks561/GTA-Vice-City-Cheat-Typer/releases)

## What it does

VC-Cheat-Typer injects **real keyboard events** (`SendInput` with hardware scan codes) into the game window. GTA: Vice City (classic) polls the keyboard through DirectInput, so message-level tricks like `PostMessage` / `SendKeys` simply do nothing. Every character is sent as a separate key-down and key-up with a hold time, because a press+release inside one frame is dropped by the game.

It does **not** read or write game memory, patch files, or inject DLLs. Single-player / offline use only — do not use in online or anti-cheat environments.

## Requirements

| | |
|---|---|
| OS | Windows 10 / 11 (64-bit) |
| Python (source mode only) | 3.8+, **with tkinter** (the official python.org installer includes it) |
| Third-party packages | **None** at runtime (stdlib + ctypes Win32 only) |
| Privileges | Normal user is fine. **If the game runs as administrator, this tool must run as administrator too** — otherwise Windows UIPI silently drops injected keys while `SendInput` still reports success. The UI shows a red warning and offers a one-click restart as admin. |
| Game | Classic PC GTA: Vice City (1.0 recommended). Definitive Edition mostly works with slower intervals. |

## Quick start (3 minutes)

1. Download `VC-Cheat-Typer.exe` from [Releases](https://github.com/mekks561/GTA-Vice-City-Cheat-Typer/releases) and verify it against `VC-Cheat-Typer-SHA256.txt`.
2. Double-click it. On first launch a 3-step wizard opens: choose a speed preset → run the injection self-test → check hotkey conflicts. (`Ctrl+F1` reopens it.)
3. Switch to the game, press `F4` (health) or any bound key. "Cheat Activated" in the top-left corner means it worked.

> Since v1.8, closing/minimizing the window sends it to the **system tray** (click the icon to restore, right-click to quit). Disable it in **Settings → General** if you prefer close = exit.

If nothing happens: check the red privilege warning → make sure the game window is focused and not minimized → run **⋯ More → Environment Diagnosis** (or `VC-Cheat-Typer.exe --diagnose`) → inspect `logs/app.log` for `SEND` lines.

## Features

- **28 built-in cheats**, all pre-bound to `F1`–`F11` / `Shift+…` / `Ctrl+Shift+…`; add, edit, delete, search, group and sort entries
- **Global hotkeys** via `RegisterHotKey` with real conflict detection (error 1409 = already taken); one-click reassignment to a free key
- **Foreground check**: only sends when the target window is focused (auto-detected by process name, or by configurable title keywords)
- **Chinese IME bypass**: temporarily detaches the target window's input context (IME otherwise swallows injected characters)
- **Non-focus-stealing toast**: result feedback drawn with `WS_EX_NOACTIVATE`, safe while playing
- **Profiles**: independent cheat sets and hotkeys, one-click switching; **auto-switch by game** (v1.8) via exe/title rules with 800 ms debounce
- **System tray** (v1.8), **first-run wizard** (v1.8), **Settings dialog** with 4 tabs (v1.8), **hotkey overview** with text export (v1.8)
- **Shareable `.vcpack` packs** (v1.9): diff preview before import (new / conflict / identical), import only selected rows, optional overwrite, sha256 integrity hint, automatic hotkey collision avoidance, version comparison. Spec: [`docs/PACK-FORMAT.md`](docs/PACK-FORMAT.md)
- **Batch editing** (v1.9): multi-select and change group / assign free hotkeys / set interval / delete (one-step undo of the whole snapshot)
- **Game templates** (v1.9): VC classic, VC Definitive Edition, GTA III, GTA SA. The latter two contain publicly listed codes that are **NOT verified on this tool** — they are greyed out, labelled, unbound by default, and require confirmation before applying
- **Paste import** (v1.9): `CODE` or `Name,CODE[,Hotkey[,Note]]`, comma/Tab separated, per-line errors with line numbers, preview before commit
- **Send history** (v1.9.1): last 50 sends (time / cheat / profile / result / duration), replayable; **keyboard navigation** with ↑/↓, Home/End, Enter to send, Esc to close dialogs
- **Generic input platform** (v2.0): `vcct.core` public API with zero tkinter dependency, configurable `Target` rules (exe/title/class → profile/strategy/IME/foreground), send strategies (`fixed` default / `burst` / `adaptive` with retry), optional before/after hooks (off by default), and a CLI. Script: `python -m vcct.cli send ASPIRINE --target VC` (dry-run; add `--execute` to inject)
- **Two distributions** (v2.0): onefile portable exe + onedir zip (`build.ps1 -OneDir`); offline docs site at `docs/site/index.html`
- **v3 config with migration chain** (v1.9): v1/v2 configs auto-migrate with a permanent pre-upgrade backup; `--export-v2` writes a config readable by v1.6–v1.8. See [`docs/MIGRATION.md`](docs/MIGRATION.md)
- **Safety**: cancellable sends (Esc / Stop button), modifier keys always released, debounce, send-quality logging, config backups, crash logs

## Command line

```bat
VC-Cheat-Typer.exe --selftest        :: structure / real injection / hotkey registration / GUI smoke
VC-Cheat-Typer.exe --diagnose        :: privilege / foreground / window / injection report
VC-Cheat-Typer.exe --export-v2 [path]:: export a v2-compatible config for older versions
```

## Build from source

```bat
:: Option A: PowerShell one-click (unittest + ruff + PyInstaller + SHA256)
powershell -ExecutionPolicy Bypass -File build.ps1

:: Option B: run from source
run.bat
python vc_cheat_typer.py --selftest

:: Option C: manual packaging
python -m PyInstaller VC-Cheat-Typer.spec --noconfirm
```

Verification: `python -m unittest discover -s tests` and `ruff check vc_cheat_typer.py`.

## Documentation

| File | Content |
|---|---|
| [`README.md`](README.md) | Full Chinese documentation, changelog, default hotkey table, FAQ |
| [`docs/PACK-FORMAT.md`](docs/PACK-FORMAT.md) | `.vcpack` format spec (write a valid pack by hand) |
| [`docs/MIGRATION.md`](docs/MIGRATION.md) | Config v1→v2→v3 migration, backups, rollback |
| [`docs/ROADMAP-1.7-2.0.md`](docs/ROADMAP-1.7-2.0.md) | Version roadmap (Chinese) |
| [`docs/PLAN-1.7.md`](docs/PLAN-1.7.md) / `PLAN-1.8.md` / `PLAN-1.9.md` | Implementation notes per release (Chinese) |

## Disclaimer

Single-player only. This tool sends standard keyboard events; it never touches game memory, game files, or online services. The GTA III / San Andreas templates contain unverified public cheat text — verify effects yourself before binding hotkeys.
