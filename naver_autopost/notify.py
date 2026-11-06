"""결과 알림(텔레그램, 선택). 설정이 없으면 로그에만 남긴다."""
from __future__ import annotations

import json
import logging
import urllib.request

from .config import Config

log = logging.getLogger(__name__)


def send(cfg: Config, text: str) -> None:
    send_text(cfg.telegram_bot_token, cfg.telegram_chat_id, text)


def send_text(bot_token: str, chat_id: str, text: str) -> None:
    log.info("알림: %s", text)
    if not (bot_token and chat_id):
        return
    body = json.dumps({"chat_id": chat_id, "text": text, "disable_web_page_preview": False}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data=body, headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:
        log.warning("텔레그램 알림 실패: %s", e)


def send_photo(bot_token: str, chat_id: str, path, caption: str = "") -> bool:
    """사진 한 장을 보낸다(실패 화면 등). 설정이 없거나 파일이 없으면 False."""
    from pathlib import Path
    import uuid

    path = Path(path)
    if not (bot_token and chat_id and path.exists()):
        return False
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in (("chat_id", chat_id), ("caption", caption[:1000])):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="{path.name}"\r\n'
                 f"Content-Type: image/png\r\n\r\n".encode() + path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendPhoto", data=b"".join(parts),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        urllib.request.urlopen(req, timeout=30).read()
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("텔레그램 사진 알림 실패: %s", e)
        return False
