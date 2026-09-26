"""결과 알림(텔레그램, 선택). 설정이 없으면 로그에만 남긴다."""
from __future__ import annotations

import json
import logging
import urllib.request

from .config import Config

log = logging.getLogger(__name__)


def send(cfg: Config, text: str) -> None:
    log.info("알림: %s", text)
    if not (cfg.telegram_bot_token and cfg.telegram_chat_id):
        return
    body = json.dumps({"chat_id": cfg.telegram_chat_id, "text": text, "disable_web_page_preview": False}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{cfg.telegram_bot_token}/sendMessage",
        data=body, headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:
        log.warning("텔레그램 알림 실패: %s", e)
