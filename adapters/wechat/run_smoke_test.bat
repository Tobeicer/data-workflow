@echo off
cd /d "%~dp0..\.."
powershell -NoProfile -ExecutionPolicy Bypass -File "adapters\wechat\src\run_smoke_test.ps1"
pause
