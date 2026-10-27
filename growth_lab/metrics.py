"""매일 수집: 통계 화면(글별 조회수) + 검색 순위 → data/lab/metrics_<블로그>.jsonl에 하루 한 줄."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

from naver_autopost import history

from . import rank, stats, store
from .config import BLOGS, LabConfig

log = logging.getLogger(__name__)


def _platform_cfg(blog: str):
    if BLOGS[blog].platform == "naver":
        from naver_autopost.config import Config
        return Config.load(blog)
    from tistory_autopost.config import TistoryConfig
    return TistoryConfig.load()


def blog_ident(pcfg) -> str:
    """통계 화면 원본에서 지울 블로그 아이디(다른 블로그와 연결되지 않게)."""
    return str(getattr(pcfg, "blog_id", "") or getattr(pcfg, "blog_name", "") or "")


DAILY_BACKFILL_DAYS = 60     # 처음엔 60일치, 그 뒤로는 빠진 날 + 어제·오늘만 받는다


def days_to_fetch(cfg: LabConfig, blog: str, today: str) -> list[str]:
    fetched = set(store.load_daily(cfg, blog)["fetched"])
    d0 = date.fromisoformat(today)
    window = [(d0 - timedelta(days=i)).isoformat() for i in range(DAILY_BACKFILL_DAYS)]
    # 오늘은 아직 덜 찼고 어제도 늦게 집계될 수 있어 늘 다시 받는다
    return sorted({d for d in window if d not in fetched} | set(window[:2]))


def capture(blog: str, cfg: LabConfig, pcfg=None, shots: Path | None = None, today: str = "") -> stats.Capture:
    pcfg = pcfg or _platform_cfg(blog)
    if BLOGS[blog].platform == "naver":
        if not pcfg.blog_id:
            raise RuntimeError(f".env에 NAVER_BLOG_ID_{blog.upper()}가 없습니다")
        days = days_to_fetch(cfg, blog, today) if today else None
        return stats.capture_naver(pcfg, cfg.naver_stat_urls, shots, days)
    if not pcfg.blog_name:
        raise RuntimeError(".env에 TISTORY_BLOG가 없습니다")
    return stats.capture_tistory(pcfg, cfg.tistory_stat_urls, shots,
                                 days_to_fetch(cfg, blog, today) if today else None)


def collect(blog: str, cfg: LabConfig, today: str, capture_fn=None, rank_fetch=None) -> dict:
    spec = BLOGS[blog]
    entries = [e for e in history.load(cfg.history_file(blog)) if e.get("url")]
    pcfg = None if capture_fn else _platform_cfg(blog)
    snapshot: dict = {"date": today, "posts": {}, "errors": []}
    try:
        cap = capture_fn() if capture_fn else capture(blog, cfg, pcfg, today=today)
    except Exception as e:  # noqa: BLE001 - 통계 화면을 못 읽어도 검색 순위는 모은다
        log.warning("[%s] 통계 화면 읽기 실패: %s", spec.label, e)
        cap = stats.Capture(errors=[str(e)[:300]])
    # 조회수는 날짜별 글 조회수를 발행일부터 더한 값만 쓴다. 통계 화면에 보이는 숫자는 그날·그 기간 값이거나
    # 댓글 수일 수 있어(2026-10 진단) 누적 조회수로 쓰면 점수가 틀어진다 → 날짜별 값을 못 받은 날은 비워 둔다.
    matched: dict = {}
    if cap.daily:
        daily = store.merge_daily(cfg, blog, stats.daily_views(cap, entries), sorted(cap.daily))
        matched = {k: {"views": sum(v.values()), "candidates": [{"field": "daily", "value": sum(v.values())}]}
                   for k, v in daily["posts"].items()}
    elif cap.logged_in:
        cap.errors.append("날짜별 글 조회수를 받지 못해 오늘은 조회수를 기록하지 않습니다")
    out_dir = cfg.output_dir / blog / today
    ident = blog_ident(pcfg) if pcfg else ""
    snapshot["capture_file"] = str(stats.save_capture(cap, out_dir, {ident: "<BLOG>"} if ident else None))
    snapshot["logged_in"] = cap.logged_in
    snapshot["errors"] += cap.errors
    snapshot["responses"] = len(cap.responses)
    snapshot["daily_days"] = len(cap.daily)
    try:
        ranks = rank.check(entries, spec.platform, cfg.naver_search_id, cfg.naver_search_secret, today,
                           cfg.rank_max_queries, rank_fetch, debug_dir=out_dir)
    except Exception as e:  # noqa: BLE001
        snapshot["errors"].append(f"검색 순위: {e}"[:300])
        ranks = {}
    for e in entries:
        key = stats.post_key(e["url"])
        row = {}
        if key in matched:
            row["views"] = matched[key]["views"]
            row["src"] = matched[key]["candidates"][0]["field"]
        if key in ranks:
            row["rank"] = {k: v for k, v in ranks[key].items() if k != "query"}
            row["query"] = ranks[key].get("query", "")
        if row:
            snapshot["posts"][key] = row
    snapshot["matched"] = len(matched)
    snapshot["total_posts"] = len(entries)
    store.append_metrics(cfg, blog, snapshot)
    log.info("[%s] 수집: 글 %d편 중 조회수 %d편, 검색 순위 %d편, 데이터 응답 %d개",
             spec.label, len(entries), len(matched), len(ranks), len(cap.responses))
    return snapshot
