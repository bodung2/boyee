"""카카오 로그인 유지 기간 기록·미리 알림.

카카오는 '로그인 상태 유지'·'간편로그인' 유지 기간을 밝히지 않는다. 그래서 직접 재 본다.
- 블로그 주인이 `login`으로 직접 로그인한 시각(manual_login)
- 로그인 확인 결과(ok는 하루 한 번만, 실패는 매번 + 막힌 화면 종류)
를 data/tistory_login_log.json에 남기고, '직접 로그인 → 비밀번호를 다시 물음'까지 걸린 날수를 유지 기간으로 본다.
관찰한 유지 기간 중 가장 짧은 값에서 REMIND_DAYS일 전부터 하루 한 번 "편할 때 login 한 번" 알림을 보낸다.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))
FILE = "tistory_login_log.json"
REMIND_DAYS = 3
MAX_EVENTS = 500
# 이 화면에서 멈췄으면 카카오 쪽 로그인 유지가 끝난 것(비밀번호·계정 선택부터 다시)
EXPIRED_STATES = ("kakao_password", "kakao_wrong_password", "captcha", "kakao_select")


def _path(cfg) -> Path:
    return Path(cfg.data_dir) / FILE


def load(cfg) -> dict:
    try:
        data = json.loads(_path(cfg).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(cfg, data: dict) -> None:
    path = _path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def record(cfg, event: str, state: str = "", now: datetime | None = None) -> None:
    """event: manual_login | ok | fail. 실패해도 발행에는 영향이 없다."""
    try:
        now = (now or datetime.now(KST)).astimezone(KST)
        data = load(cfg)
        events = data.setdefault("events", [])
        stamp = now.strftime("%Y-%m-%d %H:%M")
        if event == "ok" and any(e["event"] == "ok" and e["at"][:10] == stamp[:10] for e in events):
            return                                     # 정상 확인은 하루 한 번만 남긴다
        events.append({"at": stamp, "event": event, **({"state": state} if state else {})})
        del events[:-MAX_EVENTS]
        _save(cfg, data)
    except Exception as e:  # noqa: BLE001
        log.warning("로그인 기록 실패: %s", e)


def _at(e: dict) -> datetime:
    return datetime.strptime(e["at"], "%Y-%m-%d %H:%M").replace(tzinfo=KST)


def lifetimes(events: list[dict]) -> list[float]:
    """직접 로그인 → (처음) 카카오가 비밀번호를 다시 물을 때까지 걸린 날수들."""
    out, start = [], None
    for e in events:
        if e["event"] == "manual_login":
            start = _at(e)
        elif e["event"] == "fail" and e.get("state") in EXPIRED_STATES and start:
            out.append(round((_at(e) - start).total_seconds() / 86400, 1))
            start = None
    return out


def status(cfg, now: datetime | None = None) -> dict:
    now = (now or datetime.now(KST)).astimezone(KST)
    events = load(cfg).get("events", [])
    logins = [e for e in events if e["event"] == "manual_login"]
    life = lifetimes(events)
    since = (now - _at(logins[-1])).total_seconds() / 86400 if logins else None
    expected = min(life) if life else None
    return {"since_login_days": since, "lifetimes": life, "expected_days": expected,
            "days_left": (expected - since) if (expected is not None and since is not None) else None}


def summary(cfg, now: datetime | None = None) -> str:
    st = status(cfg, now)
    if st["since_login_days"] is None:
        return "직접 로그인 기록이 아직 없습니다(다음 `login`부터 잽니다)"
    text = f"직접 로그인 후 {st['since_login_days']:.0f}일째"
    if st["expected_days"] is None:
        return text + " · 카카오 로그인 유지 기간은 아직 관찰 중(한 번 끝나 봐야 압니다)"
    seen = ", ".join(f"{d:g}일" for d in st["lifetimes"][-5:])
    return text + f" · 지금까지 유지 기간 {seen} → 약 {int(max(st['days_left'], 0))}일 남음"


def due_reminder(cfg, now: datetime | None = None) -> str:
    """미리 알릴 때면 알림 문구(하루 한 번), 아니면 빈 문자열."""
    now = (now or datetime.now(KST)).astimezone(KST)
    st = status(cfg, now)
    if st["days_left"] is None or st["days_left"] > REMIND_DAYS:
        return ""
    data = load(cfg)
    today = now.strftime("%Y-%m-%d")
    if data.get("reminded") == today:
        return ""
    data["reminded"] = today
    _save(cfg, data)
    left = max(st["days_left"], 0)
    return (f"[티스토리] 카카오 로그인 유지가 약 {int(left)}일 뒤 끝날 수 있어요"
            f"(지금까지 {', '.join(f'{d:g}일' for d in st['lifetimes'][-5:])} 만에 끝남). "
            "편할 때 PC에서 `.venv\\Scripts\\python.exe -m tistory_autopost login`을 한 번 해 주세요"
            "('로그인 상태 유지'·'간편로그인 정보 저장' 체크). 그러면 발행이 막히지 않습니다.")
