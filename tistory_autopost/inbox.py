"""텔레그램 '화제 제보' 받기.

SNS에서 뜰 것 같은 화제를 보면 알림 봇에게 "화제 금수저 논쟁 다시 터짐"처럼 보낸다.
설정된 채팅(TELEGRAM_CHAT_ID)에서 온, 머리말(TISTORY_TIP_PREFIX)로 시작하는 메시지만 받는다.
제보는 주제 힌트일 뿐이며 글쓰기 단계에서 지시로 다루지 않는다.

같은 봇으로 성장 실험실 제안에 답할 수도 있다("승인 투3", "거절 티2"). 텔레그램은 받은 메시지를 한 번만 넘겨 주므로
(offset) 제보와 답장을 이 파일 하나에서 같이 받아 두고, 실험실이 자기 몫(commands)을 꺼내 간다."""
from __future__ import annotations

import json
import logging
import re
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from naver_autopost.pipeline import KST

from .config import TistoryConfig

log = logging.getLogger(__name__)
MAX_TIP_CHARS = 300
COMMAND = re.compile(r"^(승인|거절)\s*([가-힣A-Za-z]?)\s*(\d+)")
TIP_TTL_DAYS = 14        # SNS 화제는 금방 식으므로 2주 지난 제보는 쓰지 않는다


def _load(path: Path) -> dict:
    if not path.exists():
        return {"offset": 0, "tips": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def add(cfg: TistoryConfig, text: str, source: str = "manual") -> dict:
    data = _load(cfg.inbox_file)
    now = datetime.now(KST)
    tip = {"id": now.strftime("%Y%m%d%H%M%S"), "text": text.strip()[:MAX_TIP_CHARS],
           "date": now.isoformat(timespec="seconds"), "source": source, "used": ""}
    data["tips"].append(tip)
    _save(cfg.inbox_file, data)
    return tip


def parse_commands(updates: list[dict], chat_id: str) -> list[dict]:
    """getUpdates 결과에서 실험실 제안 답장("승인 투3")만 뽑는다."""
    out = []
    for u in updates:
        msg = u.get("message") or u.get("channel_post") or {}
        if str((msg.get("chat") or {}).get("id", "")) != str(chat_id):
            continue
        m = COMMAND.match((msg.get("text") or "").strip())
        if m:
            out.append({"verb": m.group(1), "prefix": m.group(2), "id": int(m.group(3)), "update_id": u.get("update_id")})
    return out


def parse_updates(updates: list[dict], chat_id: str, prefix: str) -> tuple[list[str], int]:
    """getUpdates 결과에서 제보 문구만 뽑는다. (문구 목록, 다음 offset)"""
    texts, next_offset = [], 0
    for u in updates:
        next_offset = max(next_offset, int(u.get("update_id", 0)) + 1)
        msg = u.get("message") or u.get("channel_post") or {}
        if str((msg.get("chat") or {}).get("id", "")) != str(chat_id):
            continue                      # 다른 사람이 봇에 보낸 메시지는 무시
        text = (msg.get("text") or "").strip()
        if COMMAND.match(text) or (prefix and not text.startswith(prefix)):
            continue
        text = text[len(prefix):].strip(" :：-") if prefix else text
        if text:
            texts.append(text)
    return texts, next_offset


def pull(cfg: TistoryConfig) -> int:
    """텔레그램에 쌓인 제보를 가져와 data/tistory_inbox.json에 넣는다. 가져온 개수."""
    if not (cfg.telegram_bot_token and cfg.telegram_chat_id):
        return 0
    data = _load(cfg.inbox_file)
    url = (f"https://api.telegram.org/bot{cfg.telegram_bot_token}/getUpdates"
           f"?offset={int(data.get('offset', 0))}&timeout=0&allowed_updates=%5B%22message%22%5D")
    with urllib.request.urlopen(url, timeout=20) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    texts, offset = parse_updates(body.get("result", []), cfg.telegram_chat_id, cfg.tip_prefix)
    cmds = parse_commands(body.get("result", []), cfg.telegram_chat_id)
    if offset or cmds:
        now = datetime.now(KST).isoformat(timespec="seconds")
        data.setdefault("commands", []).extend({**c, "date": now, "done": ""} for c in cmds)
        data["offset"] = offset or data.get("offset", 0)
        _save(cfg.inbox_file, data)
    for text in texts:
        add(cfg, text, source="telegram")
    return len(texts)


def pending(cfg: TistoryConfig, now: datetime | None = None) -> list[dict]:
    cutoff = (now or datetime.now(KST)) - timedelta(days=TIP_TTL_DAYS)
    return [t for t in _load(cfg.inbox_file).get("tips", [])
            if not t.get("used") and datetime.fromisoformat(t["date"]) >= cutoff]


def mark_used(cfg: TistoryConfig, tip_id: str, url: str) -> None:
    data = _load(cfg.inbox_file)
    for t in data.get("tips", []):
        if t.get("id") == tip_id:
            t["used"] = url
    _save(cfg.inbox_file, data)


def pending_commands(path: Path) -> list[dict]:
    return [c for c in _load(path).get("commands", []) if not c.get("done")]


def mark_command(path: Path, update_id, result: str) -> None:
    data = _load(path)
    for c in data.get("commands", []):
        if c.get("update_id") == update_id:
            c["done"] = result
    _save(path, data)
