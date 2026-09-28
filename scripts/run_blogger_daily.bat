@echo off
rem Google Blogger daily entry point for Windows Task Scheduler (double-click also works).
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0.."
".venv\Scripts\python.exe" -m blogger_autopost run %*
