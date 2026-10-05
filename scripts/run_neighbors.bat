@echo off
rem Daily neighbor suggestions for both blogs (Windows Task Scheduler).
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0.."
".venv\Scripts\python.exe" -m naver_autopost neighbors --profile childhood %*
".venv\Scripts\python.exe" -m naver_autopost neighbors --profile edu %*
