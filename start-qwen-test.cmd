@echo off
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0scripts\start-qwen-test.ps1"
if errorlevel 1 pause
