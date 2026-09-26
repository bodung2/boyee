#!/bin/bash
# macOS 집 PC 설치 스크립트:  bash scripts/setup_mac.sh 06:00
set -euo pipefail
TIME="${1:-06:00}"
HOUR=$((10#${TIME%%:*})); MINUTE=$((10#${TIME##*:}))
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
[ -f .env ] || { cp .env.example .env; echo ".env를 만들었습니다. NAVER_BLOG_ID를 채우세요."; }
chmod +x scripts/run_daily.sh

PLIST="$HOME/Library/LaunchAgents/com.boyee.naver-edu-autopost.plist"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.boyee.naver-edu-autopost</string>
  <key>ProgramArguments</key><array><string>$ROOT/scripts/run_daily.sh</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>$HOUR</integer><key>Minute</key><integer>$MINUTE</integer></dict>
  <key>StandardOutPath</key><string>$ROOT/logs/launchd.out.log</string>
  <key>StandardErrorPath</key><string>$ROOT/logs/launchd.err.log</string>
</dict></plist>
PL
mkdir -p logs
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "매일 $TIME 자동 실행 등록 완료. 이제 '.venv/bin/python -m naver_autopost login'으로 네이버에 로그인하세요."
