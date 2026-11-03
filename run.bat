@echo off
rem Launcher for Vice City Cheat Typer (no console window)
cd /d "%~dp0"
set "PYW="
if exist "%LOCALAPPDATA%\Programs\Python\Python310\pythonw.exe" set "PYW=%LOCALAPPDATA%\Programs\Python\Python310\pythonw.exe"
if defined PYW (
    start "" "%PYW%" vc_cheat_tool.py
) else (
    echo [!] pythonw.exe not found. Install Python 3.8+ from python.org
    echo     ^(default install includes tkinter^), then run again.
    py -0p 2>nul
    pause
)
