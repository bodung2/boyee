@echo off
rem Tistory login keep-alive (3 times a day, before publishing and stats). Run hidden via run_hidden.vbs.
rem Opens the editor once to refresh the Tistory/Kakao login; logs back in with .env KAKAO_LOGIN_* if it expired.
rem The whole script is one block so cmd reads it fully before self_update.py may replace this file.
(
chcp 65001 >nul
set PYTHONUTF8=1
set AUTOPOST_UPDATE_QUIET=1
cd /d "%~dp0.."
".venv\Scripts\python.exe" scripts\self_update.py
".venv\Scripts\python.exe" -m tistory_autopost keepalive %*
exit /b
)
