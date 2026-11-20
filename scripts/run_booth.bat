@echo off
rem Character workshop booth: converts kids drawings with ChatGPT (Codex), prints on SELPHY, posts to Padlet.
rem Keep this window open during the booth. Stop with Ctrl+C. Practice without ChatGPT: run_booth.bat --fake
rem The whole script is one block so cmd reads it fully before self_update.py may replace this file.
(
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0.."
".venv\Scripts\python.exe" scripts\self_update.py
".venv\Scripts\python.exe" -m booth check
".venv\Scripts\python.exe" -m booth run %*
pause
exit /b
)
