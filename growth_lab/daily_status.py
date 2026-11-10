"""하루 상태 보고: 블로그별 오늘 발행 수, 티스토리 로그인 상태, 오늘의 실패·경고 알림 → diagnostics/status/daily.md.

텔레그램이 없어도 문제가 Claude 대화창까지 오게 한다. 매일 22:30 GrowthLab이 쓰고 GitHub에 올리면,
Claude가 매일 밤 읽어 문제가 있을 때 대화창에 알린다. 저장소가 공개라서 글 제목·주소·블로그 아이디는 싣지 않는다
(발행은 편수만, 알림은 실패·경고만 골라 주소·아이디를 지운다)."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from naver_autopost import history

# (이름, 발행 이력 파일). 네이버 프로필은 이력 파일이 있는 것만 싣는다.
BLOGS = [("네이버 교육", "published_edu.json"), ("네이버 유아", "published_childhood.json"),
         ("네이버 유아 장소", "published_place.json"), ("네이버 투자", "published_invest.json"),
         ("네이버 시황", "published_market.json"), ("티스토리", "published_tistory.json"),
         ("구글 블로거", "published_blogger.json")]
# 실패·경고로 볼 알림(성공 알림에는 글 제목이 들어 있어 싣지 않는다)
PROBLEM = re.compile(r"실패|풀려|풀렸|만료|한도|못했|못 했|못 읽|막혔|멈춥|멈췄|오류|⚠️|❌|끝날 수|다시 로그인|확인 요청")
_URL = re.compile(r"https?://\S+")


def _published(path: Path, day: str) -> tuple[int, str]:
    """(그날 자동 발행 편수, 마지막 발행일)."""
    entries = [e for e in history.load(path) if e.get("url")]
    today = sum(1 for e in entries if e.get("source") == "autopost" and str(e.get("date", ""))[:10] == day)
    last = max((str(e.get("date", ""))[:10] for e in entries if e.get("source") == "autopost"), default="-")
    return today, last


def _alerts(path: Path, day: str, idents: list[str]) -> list[str]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            a = json.loads(line)
        except ValueError:
            continue
        text = str(a.get("text", ""))
        if not str(a.get("at", "")).startswith(day) or not PROBLEM.search(text):
            continue
        text = _URL.sub("(주소)", text)
        for i in idents:
            if i:
                text = text.replace(i, "<BLOG>")
        first = " ".join(text.split())[:300]
        out.append(f"{a['at'][11:]} {first}")
    return out[-30:]


def _tistory_login(data_dir: Path) -> str:
    try:
        from types import SimpleNamespace

        from tistory_autopost import login_log
        cfg = SimpleNamespace(data_dir=data_dir)
        events = login_log.load(cfg).get("events", [])
        last = events[-1] if events else None
        state = ("확인 기록 없음" if not last else
                 f"마지막 점검 {last['at']} → {'정상' if last['event'] in ('ok', 'manual_login') else '실패(' + last.get('state', '?') + ')'}")
        return f"{state} · {login_log.summary(cfg)}"
    except Exception as e:  # noqa: BLE001
        return f"(로그인 기록을 읽지 못함: {e})"[:200]


def write(data_dir: Path, out: Path, idents: list[str], now: datetime | None = None) -> Path:
    now = now or datetime.now()
    day = now.strftime("%Y-%m-%d")
    lines = [f"# 하루 상태 · {day} ({now:%H:%M} 기준)", "", "## 발행", "",
             "| 블로그 | 오늘 | 마지막 발행 |", "|---|---|---|"]
    for name, fname in BLOGS:
        path = data_dir / fname
        if not path.exists():
            continue
        n, last = _published(path, day)
        # 블로그마다 발행 요일·빈도가 달라(장소 글은 사진이 들어온 날만, 시황은 평일) 빠졌다고 단정하지 않는다
        lines.append(f"| {name} | {'✅ ' if n else ''}{n}편 | {last} |")
    lines += ["", "## 티스토리 로그인", "", f"- {_tistory_login(data_dir)}"]
    alerts = _alerts(data_dir / "alerts.jsonl", day, idents)
    lines += ["", "## 오늘의 실패·경고 알림", ""] + ([f"- {a}" for a in alerts] or ["- 없음"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
