"""블로그 분석 자료 내보내기: 글별 조회수·검색 순위·유입 경로 원본을 한 파일로 모아 블로그 주인 구글 드라이브에 올린다.

`python -m growth_lab export --blog edu` — 조회수를 지금 한 번 모은 뒤(--no-collect면 건너뜀) 내보낸다.
Claude 대화에서 이 파일(드라이브의 lab_export_<블로그>.md)을 읽어 분석한다.
글 제목이 들어가므로 공개 GitHub에는 올리지 않고, 주인만 보는 드라이브 파일 하나를 덮어쓴다.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from statistics import median

from naver_autopost import history

from . import scoring, store
from .stats import post_key
from .config import BLOGS, LabConfig

RAW_KEYS = ("referer", "inflow", "search", "keyword", "visit", "path")   # 유입 경로·검색어로 보이는 응답
RAW_MAX_CHARS = 60000


def drive_name(blog: str) -> str:
    return f"lab_export_{blog}.md"


def _fmt(v) -> str:
    return "-" if v is None else str(v)


def build(blog: str, cfg: LabConfig, today: str) -> str:
    spec = BLOGS[blog]
    entries = [e for e in history.load(cfg.history_file(blog)) if e.get("url")]
    daily = store.load_daily(cfg, blog)
    rows = store.load_metrics(cfg, blog)
    table = scoring.post_table(blog, entries, rows, today, scoring.topic_maps(cfg.history_dir), daily)
    by_key = {p["key"]: p for p in table}
    fetched = sorted(daily.get("fetched") or [])
    lines = [f"# 분석 자료 · {spec.label} · {today}", "",
             f"- 발행 이력 {len(entries)}편 · 일별 조회수 받은 날 {len(fetched)}일"
             + (f" ({fetched[0]} ~ {fetched[-1]})" if fetched else ""),
             f"- 판정 나이: {spec.eval_days[0]}일(v1), {spec.eval_days[1]}일(v2) · views_now = 받은 날들의 조회수 합", ""]

    # 갈래(레인·카테고리)별 요약
    def group(e: dict) -> str:
        return str(e.get("lane") or e.get("category") or "-")
    groups: dict[str, list[dict]] = {}
    for e in entries:
        p = by_key.get(post_key(e["url"]))
        if p:
            groups.setdefault(group(e), []).append(p)
    lines += ["## 갈래별 요약", "", "| 갈래 | 글 | v1 중간값 | v1 0~2회 글 | views_now 합 |", "|---|---|---|---|---|"]
    for g, ps in sorted(groups.items(), key=lambda x: -len(x[1])):
        v1 = [p["v1"] for p in ps if isinstance(p.get("v1"), int)]
        low = sum(1 for v in v1 if v <= 2)
        lines.append(f"| {g} | {len(ps)} | {median(v1) if v1 else '-'} | {low}/{len(v1)} | "
                     f"{sum(p['views_now'] or 0 for p in ps)} |")

    lines += ["", "## 글별", "",
              "| 발행일 | 갈래 | 카테고리 | 주제 | 제목 | v1 | v2 | views_now | 최고 검색 순위 |",
              "|---|---|---|---|---|---|---|---|---|"]
    for e in sorted(entries, key=lambda e: str(e.get("date", "")), reverse=True):
        p = by_key.get(post_key(e["url"]), {})
        title = str(e.get("title", "")).replace("|", "/")
        lines.append(f"| {str(e.get('date', ''))[:10]} | {group(e)} | {e.get('category', '') or '-'} | "
                     f"{str(e.get('topic', '') or '-').replace('|', '/')[:40]} | {title} | {_fmt(p.get('v1'))} | "
                     f"{_fmt(p.get('v2'))} | {_fmt(p.get('views_now'))} | {_fmt(p.get('best_rank'))} |")

    # 유입 경로·검색어 원본(최근 수집)
    caps = sorted((cfg.output_dir / blog).glob("*/capture.json"))
    if caps:
        try:
            cap = json.loads(caps[-1].read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cap = {}
        raw = [r for r in cap.get("responses", []) if any(k in str(r.get("url", "")).lower() for k in RAW_KEYS)]
        text = json.dumps(raw, ensure_ascii=False)[:RAW_MAX_CHARS]
        lines += ["", f"## 유입 경로·검색어 원본 ({caps[-1].parent.name} 수집, 통계 화면 응답 {len(raw)}개)", "",
                  "```json", text, "```"]
        pages = [p for p in cap.get("pages", []) if "유입" in str(p.get("nav", "")) or "referer" in str(p.get("url", ""))]
        for pg in pages[:2]:
            lines += ["", f"### 화면 글자: {pg.get('nav') or pg.get('url')}", "", str(pg.get("text", ""))[:4000]]
    return "\n".join(lines) + "\n"


def run(blog: str, cfg: LabConfig, today: str | None = None, upload=None) -> Path:
    today = today or date.today().isoformat()
    text = build(blog, cfg, today)
    out = cfg.output_dir / blog / drive_name(blog)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    if upload is None:
        from quest_board.drive import put as upload
    upload(text.encode("utf-8"), drive_name(blog), "text/markdown", cfg.data_dir / f"drive_export_{blog}.json")
    return out
