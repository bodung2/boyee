@echo off
rem Perp bot paper-trading tick for Windows Task Scheduler (every 4 hours, a few minutes after each 4h candle closes).
rem The whole script is one block so cmd reads it fully before self_update.py may replace this file.
(
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0.."
".venv\Scripts\python.exe" scripts\self_update.py
".venv\Scripts\python.exe" -m perp_bot paper --notify %*
exit /b
)
