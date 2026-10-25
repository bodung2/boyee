"""실험실 파일 읽기·쓰기: 주제 장부(ledger), 지표 기록(metrics), 플레이북(learned.md).

모두 data/lab/ 아래에 있고 git에 올라가지 않는다(집 PC가 매일 고쳐 쓰므로 자동 업데이트와 부딪히지 않게).
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import date
from pathlib import Path

from .config import LabConfig

LEARNED_MAX_CHARS = 6000          # 플레이북이 글쓰기 프롬프트를 잡아먹지 않게
APPROVED_HEADER = "## 확정 규칙 (블로그 주인 승인)"


def empty_ledger() -> dict:
    return {
        "topics": {},            # 이름 → {status, posts, keywords, first, last_verdict, notes}
        "graveyard": [],         # [{name, keywords, reason, date, ratio}]
        "explore_queue": [],     # 리뷰가 찾은 새 주제 후보 [{name, keywords, why, demand, added}]
        "experiment": None,      # 진행 중 실험 {var, arms, start, post_until, status}
        "experiments_done": [],
        "adopted": {},           # 실험으로 정한 값 {image_style: "base"}
        "proposals": [],         # 큰 변경 제안 [{id, text, evidence, status, date}]
        "next_proposal_id": 1,
        "changelog": [],         # [{date, what, why}]
        "lab_posts": 0,          # 실험실 안내를 받아 쓴 글 수(탐색 차례 계산용)
    }


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except json.JSONDecodeError:
        broken = path.with_suffix(f".broken-{date.today():%Y%m%d}.json")
        shutil.copy(path, broken)          # 깨진 파일은 남겨 두고 새로 시작한다
        return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def ledger_path(cfg: LabConfig, blog: str) -> Path:
    return cfg.data_dir / f"ledger_{blog}.json"


def load_ledger(cfg: LabConfig, blog: str) -> dict:
    data = _read_json(ledger_path(cfg, blog), {})
    return {**empty_ledger(), **data}


def save_ledger(cfg: LabConfig, blog: str, ledger: dict) -> None:
    _write_json(ledger_path(cfg, blog), ledger)


def log_change(ledger: dict, today: str, what: str, why: str) -> None:
    ledger["changelog"].append({"date": today, "what": what, "why": why})
    ledger["changelog"] = ledger["changelog"][-300:]


# ---- 지표: 하루 한 줄씩 쌓는다 ----

def metrics_path(cfg: LabConfig, blog: str) -> Path:
    return cfg.data_dir / f"metrics_{blog}.jsonl"


def append_metrics(cfg: LabConfig, blog: str, snapshot: dict) -> None:
    path = metrics_path(cfg, blog)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 같은 날 다시 수집하면 그날 줄을 바꾼다(하루 한 줄).
    rows = [r for r in load_metrics(cfg, blog) if r.get("date") != snapshot.get("date")]
    rows.append(snapshot)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)


def load_metrics(cfg: LabConfig, blog: str) -> list[dict]:
    path = metrics_path(cfg, blog)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return sorted(rows, key=lambda r: r.get("date", ""))


# ---- 일별 글 조회수(네이버 조회수 순위) ----

def daily_path(cfg: LabConfig, blog: str) -> Path:
    return cfg.data_dir / f"daily_{blog}.json"


def load_daily(cfg: LabConfig, blog: str) -> dict:
    """{"fetched": [받아 온 날짜], "posts": {글 주소: {날짜: 그날 조회수}}}"""
    data = _read_json(daily_path(cfg, blog), {})
    return {"fetched": data.get("fetched", []), "posts": data.get("posts", {})}


def merge_daily(cfg: LabConfig, blog: str, views: dict[str, dict[str, int]], fetched: list[str]) -> dict:
    """새로 받은 날짜는 그날 값으로 바꾼다(그날 순위에 없던 글은 0으로 본다)."""
    data = load_daily(cfg, blog)
    days = set(fetched)
    for key, by_day in data["posts"].items():
        for d in days:
            by_day.pop(d, None)
    for key, by_day in views.items():
        data["posts"].setdefault(key, {}).update(by_day)
    data["fetched"] = sorted(set(data["fetched"]) | days)
    _write_json(daily_path(cfg, blog), data)
    return data


# ---- 플레이북 ----

def learned_path(cfg: LabConfig, blog: str) -> Path:
    return cfg.data_dir / f"learned_{blog}.md"


def load_learned(cfg: LabConfig, blog: str) -> str:
    path = learned_path(cfg, blog)
    return path.read_text(encoding="utf-8") if path.exists() else ""


def approved_rules(text: str) -> str:
    """플레이북에서 블로그 주인이 승인한 규칙 부분(리뷰가 지우지 못하게 따로 지킨다)."""
    i = text.find(APPROVED_HEADER)
    if i < 0:
        return ""
    rest = text[i + len(APPROVED_HEADER):]
    nxt = re.search(r"^## ", rest, re.M)
    return (APPROVED_HEADER + (rest[:nxt.start()] if nxt else rest)).strip()


def save_learned(cfg: LabConfig, blog: str, text: str, today: str) -> Path:
    """새 플레이북을 저장한다. 예전 판은 data/lab/backup/에 남기고, 승인된 규칙은 항상 이어 붙인다."""
    path = learned_path(cfg, blog)
    old = load_learned(cfg, blog)
    if old:
        backup = cfg.data_dir / "backup" / f"learned_{blog}_{today}.md"
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_text(old, encoding="utf-8")
    keep = approved_rules(old)
    body = text.replace(approved_rules(text), "").strip() if approved_rules(text) else text.strip()
    budget = LEARNED_MAX_CHARS - len(keep) - 2
    if len(body) > budget:
        body = body[:max(budget, 0)].rsplit("\n", 1)[0]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text((body + ("\n\n" + keep if keep else "")).strip() + "\n", encoding="utf-8")
    return path


def add_approved_rule(cfg: LabConfig, blog: str, rule: str, today: str) -> None:
    text = load_learned(cfg, blog)
    keep = approved_rules(text) or APPROVED_HEADER
    rest = text.replace(approved_rules(text), "").strip() if approved_rules(text) else text.strip()
    keep += f"\n- ({today}) {rule.strip()}"
    path = learned_path(cfg, blog)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(((rest + "\n\n") if rest else "") + keep + "\n", encoding="utf-8")
