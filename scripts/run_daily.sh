#!/bin/bash
# launchd/cron이 매일 실행하는 파일
cd "$(dirname "$0")/.." || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$HOME/.npm-global/bin:$PATH"
exec .venv/bin/python -m naver_autopost run "$@"
