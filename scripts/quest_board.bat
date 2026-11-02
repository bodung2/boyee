@echo off
rem Double-click: open the quest board with buttons (change time / pause / run now) at http://127.0.0.1:8765/.
rem Keep this window open while using the buttons; closing it stops them.
rem The whole script is one block so cmd reads it fully before self_update.py may replace this file.
(
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0.."
".venv\Scripts\python.exe" scripts\self_update.py
".venv\Scripts\python.exe" -m quest_board serve %*
exit /b
)
