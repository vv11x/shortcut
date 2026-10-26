@echo off
"%~dp0shortcut.exe" --restore-desktop
if errorlevel 1 (
    echo Desktop icon restore failed. See %LOCALAPPDATA%\shortcut\logs\shortcut.log.
    pause
)
