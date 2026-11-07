"""퀘스트별 '그날 결과' 확인: 각 파이프라인이 남기는 기록·로그·잠금 파일을 읽는다(아무것도 고치지 않는다).

새 종류의 예약 작업이 글·게시물을 발행한다면 아래 KINDS에 bat 이름으로 확인 함수를 하나 추가한다.
추가하지 않아도 보드에는 나타나고, 작업 스케줄러의 실행 결과(성공·실패)와 로그로 상태를 보여 준다.
"""
from __future__ import annotations

import json
import os
import re
import shlex
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .schedule import ROOT, Quest

STALE_LOCK_SEC = 4 * 3600      # naver_autopost.pipeline._Lock과 같은 기준
ACTIVE_LOG_SEC = 15 * 60       # 로그가 이 안에 바뀌었으면 진행 중으로 본다
KST = timezone(timedelta(hours=9))


@dataclass
class Result:
    state: str = "none"          # done 완료 / skip 건너뜀(할 일 없음) / none 기록 없음
    title: str = ""
    url: str = ""
    note: str = ""
    links: list[tuple[str, str]] = field(default_factory=list)   # (이름, 주소) — SNS 채널 등


@dataclass
class Paths:
    data: Path
    output: Path
    logs: Path

    @classmethod
    def load(cls) -> "Paths":
        try:
            from naver_autopost.config import _load_dotenv
            _load_dotenv(ROOT / ".env")
        except Exception:  # noqa: BLE001
            pass
        env = os.environ.get
        return cls(data=Path(env("DATA_DIR", str(ROOT / "data"))), output=Path(env("OUTPUT_DIR", str(ROOT / "output"))),
                   logs=Path(env("LOG_DIR", str(ROOT / "logs"))))


def _json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _opt(arg: str, name: str, default: str = "") -> str:
    try:
        parts = shlex.split(arg or "")
    except ValueError:
        parts = (arg or "").split()
    for i, p in enumerate(parts):
        if p == name and i + 1 < len(parts):
            return parts[i + 1]
        if p.startswith(name + "="):
            return p.split("=", 1)[1]
    return default


def _mday(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, KST).strftime("%Y-%m-%d")
    except OSError:
        return ""


def _mtime_hm(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, KST).strftime("%H:%M")
    except OSError:
        return ""


# ---------------------------------------------------------------- 종류별 확인

NO_PLACE_LOG = "새 장소 폴더가 없어 오늘은 쉽니다"   # naver_autopost.pipeline.NO_PLACE_LOG와 같은 문구


def _naver(p: Paths, q: Quest, day: str) -> Result:
    prof = _opt(q.arg, "--profile", "childhood")
    for e in _json(p.data / f"published_{prof}.json", []):
        if e.get("source") == "autopost" and e.get("date") == day and e.get("url"):
            return Result("done", e.get("title", ""), e["url"], e.get("category", ""))
    # 장소 글(사진 폴더가 있는 날만 발행): 폴더가 없어 쉰 날은 '건너뜀'
    if prof == "place" and NO_PLACE_LOG in _tail(p.logs / f"{prof}-{day}.log") \
            and not _error(p.logs / f"{prof}-{day}.log"):
        return Result("skip", note="places_inbox에 새 장소 폴더가 없어 쉬었습니다")
    return Result()


def _tistory(p: Paths, q: Quest, day: str) -> Result:
    slot = int(_opt(q.arg, "--slot", "1") or 1)
    for e in _json(p.data / "published_tistory.json", []):
        if (e.get("source") == "autopost" and e.get("date") == day and e.get("url")
                and int(e.get("slot") or 1) == slot):
            return Result("done", e.get("title", ""), e["url"])
    return Result()


def _blogger(p: Paths, q: Quest, day: str) -> Result:
    for e in _json(p.data / "published_blogger.json", []):
        if e.get("source") == "autopost" and e.get("date") == day and e.get("url"):
            return Result("done", e.get("title", ""), e["url"])
    return Result()


def _social(p: Paths, q: Quest, day: str) -> Result:
    prof = _opt(q.arg, "--profile", "childhood")
    state = _json(p.output / prof / day / "social_state.json", {})
    links = [(ch, v["url"]) for ch, v in state.items() if isinstance(v, dict) and v.get("url")]
    if links:
        return Result("done", " · ".join(ch for ch, _ in links), links=links)
    blog = _naver(p, Quest(q.name, q.bat, f"--profile {prof}"), day)
    if blog.state != "done":
        return Result("skip", note="그날 블로그 글이 없어 올릴 것이 없었습니다")
    return Result()


_NEIGHBOR_PROFILES = {"childhood": "유아", "edu": "교육", "invest": "투자"}


def _neighbors(p: Paths, q: Quest, day: str) -> Result:
    counts = {}
    for prof, label in _NEIGHBOR_PROFILES.items():
        n = sum(1 for r in _json(p.data / f"neighbors_{prof}.json", []) if r.get("date") == day)
        if n:
            counts[label] = n
    if counts:
        return Result("done", " · ".join(f"{k} {v}곳" for k, v in counts.items()), note="시트 '이웃 후보' 탭")
    return Result()


def _by_mtime(rel: str, what: str):
    def check(p: Paths, q: Quest, day: str) -> Result:
        path = (p.output if rel.startswith("output/") else p.data) / rel.split("/", 1)[1]
        if _mday(path) == day:
            return Result("done", f"{what} 갱신 {_mtime_hm(path)}")
        return Result()
    return check


def _growth_lab(p: Paths, q: Quest, day: str) -> Result:
    log = p.logs / f"lab-{day}.log"
    if log.exists() and not _error(log) and not (p.logs / ".run-lab.lock").exists():
        return Result("done", "통계 수집·리뷰")
    return Result()


def _tistory_keepalive(p: Paths, q: Quest, day: str) -> Result:
    log = p.logs / f"tistory-keepalive-{day}.log"
    if log.exists() and not _error(log):
        return Result("done", f"로그인 유지 확인 {_mtime_hm(log)}")
    return Result()


@dataclass
class Kind:
    group: str                       # 발행 / SNS / 보조
    check: object                    # (Paths, Quest, day) -> Result
    logs: object                     # (Quest, day) -> [로그 파일 이름]
    locks: object                    # (Quest) -> [잠금 파일 이름]
    history: bool = True             # 지난 날짜도 기록으로 확인할 수 있는지


def _prof(q: Quest) -> str:
    return _opt(q.arg, "--profile", "childhood")


KINDS: dict[str, Kind] = {
    "run_daily.bat": Kind("발행", _naver, lambda q, d: [f"{_prof(q)}-{d}.log"], lambda q: [f".run-{_prof(q)}.lock"]),
    "run_tistory_daily.bat": Kind("발행", _tistory, lambda q, d: [f"tistory-{d}.log"], lambda q: [".run-tistory.lock"]),
    "run_blogger_daily.bat": Kind("발행", _blogger, lambda q, d: [f"blogger-{d}.log"], lambda q: [".run-blogger.lock"]),
    "run_social.bat": Kind("SNS", _social, lambda q, d: [f"{_prof(q)}-social-{d}.log"], lambda q: []),
    "run_neighbors.bat": Kind("보조", _neighbors, lambda q, d: [f"neighbors-{p}-{d}.log" for p in _NEIGHBOR_PROFILES],
                              lambda q: [f".neighbors-{p}.lock" for p in _NEIGHBOR_PROFILES]),
    "run_market_dashboard.bat": Kind("보조", _by_mtime("output/market/dashboard.html", "대시보드"),
                                     lambda q, d: [], lambda q: [], history=False),
    "run_perp_paper.bat": Kind("보조", _by_mtime("data/perp/paper_state.json", "모의 운용"),
                               lambda q, d: [], lambda q: [], history=False),
    "run_tistory_keepalive.bat": Kind("보조", _tistory_keepalive, lambda q, d: [f"tistory-keepalive-{d}.log"],
                                      lambda q: []),
    "run_growth_lab.bat": Kind("보조", _growth_lab, lambda q, d: [f"lab-{d}.log"], lambda q: [".run-lab.lock"]),
}
GENERIC = Kind("보조", lambda p, q, d: Result(), lambda q, d: [], lambda q: [], history=False)


def kind_of(q: Quest) -> Kind:
    return KINDS.get(q.bat.lower(), GENERIC)


def known(q: Quest) -> bool:
    return q.bat.lower() in KINDS


# ---------------------------------------------------------------- 로그·잠금

_STAMP = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")


def _tail(path: Path, size: int = 200_000) -> str:
    try:
        with path.open("rb") as f:
            f.seek(max(0, path.stat().st_size - size))
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _error(path: Path) -> str:
    """로그의 마지막 ERROR 기록에서 원인 한 줄(예외 메시지)을 뽑는다. 그 뒤에 정상 완료 기록이 있으면 빈 문자열."""
    lines = _tail(path).splitlines()
    idx = max((i for i, l in enumerate(lines) if _STAMP.match(l) and " ERROR " in l), default=-1)
    if idx < 0:
        return ""
    block = [lines[idx]]
    for l in lines[idx + 1:]:
        if _STAMP.match(l):
            if any(w in l for w in ("완료", "이미 발행", "발행했습니다")):
                return ""       # 실패 뒤 재시도로 끝까지 간 경우
            break
        block.append(l)
    msg = next((l.strip() for l in reversed(block[1:]) if l.strip() and not l.startswith(" ")), "")
    if msg:
        msg = re.sub(r"^[A-Za-z_][A-Za-z0-9_.]*: ", "", msg)      # "RuntimeError: ..." → "..."
    else:
        msg = block[0].split(": ", 1)[-1]
    return msg.strip()[:200]


def log_files(p: Paths, q: Quest, day: str) -> list[Path]:
    return [p.logs / n for n in kind_of(q).logs(q, day) if (p.logs / n).exists()]


def failure(p: Paths, q: Quest, day: str) -> str:
    for log in log_files(p, q, day):
        msg = _error(log)
        if msg:
            return msg
    return ""


def running(p: Paths, q: Quest, now: datetime) -> bool:
    """잠금 파일이 살아 있거나(4시간 안) 오늘 로그가 방금 바뀌었으면 진행 중."""
    for name in kind_of(q).locks(q):
        lock = p.logs / name
        try:
            if now.timestamp() - lock.stat().st_mtime < STALE_LOCK_SEC:
                return True
        except OSError:
            pass
    for log in log_files(p, q, now.strftime("%Y-%m-%d")):
        try:
            if now.timestamp() - log.stat().st_mtime < ACTIVE_LOG_SEC:
                return True
        except OSError:
            pass
    return False


def check(p: Paths, q: Quest, day: str) -> Result:
    try:
        return kind_of(q).check(p, q, day)
    except Exception as e:  # noqa: BLE001 - 기록 파일 하나가 깨져도 보드는 만든다
        return Result(note=f"기록을 읽지 못함: {e}")
