@echo off
rem Quest board: summarize today's scheduled jobs (output\quest_board.html) and send a Telegram summary.
rem The whole script is one block so cmd reads it fully before self_update.py may replace this file.
(
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0.."
".venv\Scripts\python.exe" scripts\self_update.py
".venv\Scripts\python.exe" -m quest_board %*
exit /b
)
