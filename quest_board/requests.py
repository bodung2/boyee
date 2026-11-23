"""Claude 대화에서 보낸 '지금 해 줘' 요청을 집 PC가 매시간 퀘스트 보드 갱신 때 실행한다.

블로그 주인이 PC 앞에 없을 때(휴대폰) 밤 예약 작업까지 기다리지 않고 자료를 받으려고 만들었다(2026-11-22).
- 요청 파일: data/remote_requests.json (git에 올라감) — {"requests": [{"id": "...", "action": "export", "blog": "invest"}]}
- 실행한 요청 id는 data/remote_requests_done.json(이 PC에만)에 남겨 한 번씩만 한다.
- 실행할 수 있는 일은 아래 ACTIONS에 정한 것뿐이다(저장소가 공개라 임의 명령은 받지 않는다).
- 오래 걸리는 일(통계 화면 수집)은 따로 띄워 두고 퀘스트 보드 갱신은 바로 끝낸다.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .schedule import ROOT

REQUESTS = "remote_requests.json"
DONE = "remote_requests_done.json"
BLOGS = {"invest", "tistory", "edu", "childhood"}
PROFILES = {"edu", "edu_series", "childhood", "invest", "market", "place", "worksheet"}   # 네이버 자동 발행 프로필


def command(req: dict) -> list[str] | None:
    """허용된 요청이면 실행할 명령, 아니면 None."""
    if req.get("action") == "export" and req.get("blog") in BLOGS:
        return [sys.executable, "-m", "growth_lab", "export", "--blog", req["blog"]]
    if req.get("action") == "blogger_index":
        return [sys.executable, "-m", "blogger_autopost", "index"]
    # 실패 원인 보기: 그날 로그·Claude 마지막 답을 드라이브 diag_<프로필>.md로
    if req.get("action") == "diag" and req.get("profile") in PROFILES and _is_day(req.get("day")):
        return [sys.executable, "-m", "quest_board.diag", "--profile", req["profile"], "--day", req["day"]]
    # 원인을 고친 뒤 오늘 글을 바로 다시 쓰기(이미 발행했으면 아무것도 안 함)
    # 발행했던 글을 새 형식으로만 고쳐 다시 발행(블로그 주인이 옛 글을 지운 뒤)
    if req.get("action") == "restyle" and req.get("profile") in PROFILES and _is_day(req.get("day")):
        return [sys.executable, "-m", "naver_autopost", "restyle", "--profile", req["profile"], "--day", req["day"],
                "--publish"]
    # 발행한 글 썸네일을 지금 규칙으로 다시 그려 드라이브에(블로그 주인이 직접 바꿈)
    if req.get("action") == "rethumb" and req.get("profile") in PROFILES and _is_day(req.get("day")):
        return [sys.executable, "-m", "naver_autopost", "rethumb", "--profile", req["profile"], "--day", req["day"]]
    if req.get("action") == "rerun" and req.get("profile") in PROFILES:
        return [sys.executable, "-m", "naver_autopost", "run", "--profile", req["profile"]]
    return None


def _is_day(value) -> bool:
    import re
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value or "")))


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def run_pending(repo_data: Path, local_data: Path, logs: Path, spawn=None) -> list[str]:
    """아직 안 한 요청을 띄우고 그 id들을 돌려준다."""
    reqs = _load(repo_data / REQUESTS, {}).get("requests") or []
    done_path = local_data / DONE
    done = _load(done_path, {})
    started = []
    for req in reqs:
        rid = str(req.get("id") or "")
        if not rid or rid in done:
            continue
        cmd = command(req)
        done[rid] = {"at": datetime.now().isoformat(timespec="seconds"), "ok": bool(cmd)}
        if not cmd:
            continue
        logs.mkdir(parents=True, exist_ok=True)
        log = logs / f"remote-{rid}.log"
        if spawn:
            spawn(cmd, log)
        else:
            with open(log, "w", encoding="utf-8") as f:     # 퀘스트 보드 갱신을 붙잡지 않게 따로 띄운다
                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
                subprocess.Popen(cmd, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, creationflags=flags)
        started.append(rid)
    if started or reqs:
        done_path.parent.mkdir(parents=True, exist_ok=True)
        done_path.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8")
    return started
