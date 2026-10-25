@echo off
rem Growth lab: daily stats collection for the investment blog and Tistory, weekly review on Sundays (Windows Task Scheduler).
rem The whole script is one block so cmd reads it fully before self_update.py may replace this file.
(
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0.."
".venv\Scripts\python.exe" scripts\self_update.py
".venv\Scripts\python.exe" -m growth_lab daily %*
exit /b
)
