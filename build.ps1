# VC-Cheat-Typer - one-click build (Windows PowerShell 5.1+)
#
# Steps: read APP_VER -> optional unittest/ruff -> PyInstaller -> SHA256 manifest
# Usage:
#   .\build.ps1
#   .\build.ps1 -SkipVerify
#   .\build.ps1 -SyncFromTag
#   .\build.ps1 -Python "...\Python310\python.exe" -RuffPython "...\python.exe"
#   .\build.ps1 -OneDir          # also build the onedir distribution (+ zip)
#
# By default this script NEVER modifies source files. -SyncFromTag is opt-in.
# unittest/PyInstaller need a Python WITH tkinter; ruff may be in another
# interpreter, hence -RuffPython. ruff is optional (warning only if missing).
# This file intentionally contains ASCII only: PowerShell 5.1 reads BOM-less
# scripts using the system ANSI codepage.

param(
    [string]$Python = "python",
    [string]$RuffPython = "python",
    [switch]$SkipVerify,
    [switch]$SyncFromTag,
    [switch]$OneDir
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $root

try {
    $constPath = Join-Path $root "vcct\const.py"
    $const = Get-Content $constPath -Raw -Encoding UTF8
    $m = [regex]::Match($const, 'APP_VER\s*=\s*"([^"]+)"')
    if (-not $m.Success) { throw "Cannot find APP_VER in vcct\const.py" }
    $version = $m.Groups[1].Value

    $tag = ""
    try { $tag = (& git describe --tags --abbrev=0 2>$null).Trim() } catch { }
    if ($tag) {
        $tagVer = $tag -replace '^v', ''
        if ($SyncFromTag -and $tagVer -ne $version) {
            $replacement = '${1}' + $tagVer + '${2}'
            $newConst = [regex]::Replace($const, '(APP_VER\s*=\s*")[^"]+(")', $replacement)
            [IO.File]::WriteAllText($constPath, $newConst, (New-Object Text.UTF8Encoding($false)))
            $version = $tagVer
            Write-Host "[version] APP_VER synced from tag '$tag' -> $version" -ForegroundColor Yellow
        } elseif ($tagVer -ne $version) {
            Write-Host "[version] WARNING: APP_VER=$version but latest tag=$tag. Use -SyncFromTag if intended." -ForegroundColor Yellow
        }
    }

    Write-Host "=== VC-Cheat-Typer v$version build ===" -ForegroundColor Cyan

    if (-not $SkipVerify) {
        Write-Host "[1/3] unittest..." -ForegroundColor Gray
        & $Python -m unittest discover -s tests
        if ($LASTEXITCODE -ne 0) { throw "Unit tests failed" }
        Write-Host "[2/3] ruff..." -ForegroundColor Gray
        # Do not redirect native stderr with 2>&1 here: PowerShell 5.1 turns it
        # into NativeCommandError and ErrorActionPreference=Stop aborts the build.
        & $RuffPython -m ruff check vc_cheat_typer.py vcct/
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[2/3] WARNING: ruff unavailable or failed; continuing." -ForegroundColor Yellow
        }
    } else {
        Write-Host "[1/3] verification skipped (-SkipVerify)" -ForegroundColor Gray
    }

    Write-Host "[3/3] PyInstaller + SHA256..." -ForegroundColor Gray
    # PyInstaller calls os.remove on the old dist exe. Some managed environments
    # intercept that with a Recycle-Bin hook and fail, so move the old file aside
    # instead of deleting it.
    $distDir = Join-Path $root "dist"
    $exePath = Join-Path $distDir "VC-Cheat-Typer.exe"
    # Timestamped backup: never delete anything (managed environments may
    # intercept both os.remove and Remove-Item with a Recycle-Bin hook).
    $prevPath = Join-Path $distDir ("VC-Cheat-Typer.exe.previous-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
    if (-not (Test-Path -LiteralPath $distDir)) { New-Item -ItemType Directory -Path $distDir | Out-Null }
    if (Test-Path -LiteralPath $exePath) {
        Move-Item -LiteralPath $exePath -Destination $prevPath -Force
    }

    & $Python -m PyInstaller VC-Cheat-Typer.spec --noconfirm
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

    if (-not (Test-Path -LiteralPath $exePath)) { throw "Build output not found: $exePath" }
    $hash = (Get-FileHash -LiteralPath $exePath -Algorithm SHA256).Hash.ToLowerInvariant()
    $shaPath = Join-Path $distDir "VC-Cheat-Typer-SHA256.txt"
    [IO.File]::WriteAllText($shaPath, "$hash *VC-Cheat-Typer.exe`n", (New-Object Text.UTF8Encoding($false)))

    $size = (Get-Item -LiteralPath $exePath).Length
    Write-Host ""
    Write-Host "OK  dist\VC-Cheat-Typer.exe  ($size bytes)" -ForegroundColor Green
    Write-Host "    SHA256 $hash" -ForegroundColor Green
    Write-Host "    $shaPath" -ForegroundColor Green

    # 2.1-D：控制台 CLI（GUI 子系统 exe 在交互控制台看不到 stdout）
    Write-Host "[4/4] console CLI..." -ForegroundColor Gray
    $cliExe = Join-Path $distDir "VC-Cheat-Typer-cli.exe"
    if (Test-Path -LiteralPath $cliExe) {
        Move-Item -LiteralPath $cliExe -Destination (Join-Path $distDir (
            "VC-Cheat-Typer-cli.exe.previous-" + (Get-Date -Format "yyyyMMdd-HHmmss"))) -Force
    }
    & $Python -m PyInstaller VC-Cheat-Typer-cli.spec --noconfirm
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller (CLI) failed" }
    if (-not (Test-Path -LiteralPath $cliExe)) { throw "CLI output missing" }
    $cliHash = (Get-FileHash -LiteralPath $cliExe -Algorithm SHA256).Hash.ToLowerInvariant()
    $cliShaPath = Join-Path $distDir "VC-Cheat-Typer-cli-SHA256.txt"
    [IO.File]::WriteAllText($cliShaPath, "$cliHash *VC-Cheat-Typer-cli.exe`n",
                            (New-Object Text.UTF8Encoding($false)))
    Write-Host "OK  VC-Cheat-Typer-cli.exe  SHA256 $cliHash" -ForegroundColor Green

    if ($OneDir) {
        Write-Host "[4/4] onedir distribution (2.0-F)..." -ForegroundColor Gray
        & $Python -m PyInstaller VC-Cheat-Typer-onedir.spec --noconfirm
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller (onedir) failed" }
        $oneDirPath = Join-Path $distDir "VC-Cheat-Typer-onedir"
        if (-not (Test-Path -LiteralPath $oneDirPath)) { throw "onedir output missing" }
        $zipPath = Join-Path $distDir ("VC-Cheat-Typer-onedir-" + $version + ".zip")
        Compress-Archive -LiteralPath $oneDirPath -DestinationPath $zipPath -Force
        $zHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
        $zShaPath = $zipPath + ".sha256.txt"
        [IO.File]::WriteAllText($zShaPath, "$zHash *" + (Split-Path -Leaf $zipPath) + "`n",
                                (New-Object Text.UTF8Encoding($false)))
        Write-Host "OK  $zipPath" -ForegroundColor Green
        Write-Host "    SHA256 $zHash" -ForegroundColor Green
    }

    Write-Host ""
    Write-Host "Verify with Git Bash:  sha256sum -c dist/VC-Cheat-Typer-SHA256.txt" -ForegroundColor Gray
} finally {
    Pop-Location
}
