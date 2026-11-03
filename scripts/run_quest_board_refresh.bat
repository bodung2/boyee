@echo off
rem Hourly quest board refresh (output\quest_board.html + Google Drive copy for the phone web app), run hidden via run_hidden.vbs. No Telegram message.
rem The whole script is one block so cmd reads it fully before self_update.py may replace this file.
(
chcp 65001 >nul
set PYTHONUTF8=1
set AUTOPOST_UPDATE_QUIET=1
cd /d "%~dp0.."
".venv\Scripts\python.exe" scripts\self_update.py
".venv\Scripts\python.exe" -m quest_board --upload %*
exit /b
)
