@echo off
rem Evening social publish (Threads + Instagram) for Windows Task Scheduler.
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0.."
".venv\Scripts\python.exe" -m naver_autopost social-publish %*
