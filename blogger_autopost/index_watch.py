"""구글 블로거 색인 감시: 글마다 구글 색인에 들어갔는지(서치 콘솔 URL 검사)와 검색 노출·클릭을 매일 모은다.

블로거는 아직 색인이 거의 안 돼(2026-10 진단: 사이트맵 15편 중 색인 0편) 조회수로 주제를 고르는 성장 실험실을
돌릴 수 없다. 그래서 먼저 '색인'을 잰다 → 색인 비율이 오르면 성장 실험실로 넘어간다.

- 결과: data/blogger_index.json (집 PC에만). 하루 상태 보고·퀘스트 보드 '자동화 블로그 분석' 칸이 읽는다.
- 서치 콘솔 URL 검사는 하루 2,000건까지라, 하루 MAX_INSPECT편만 본다(색인 안 된 글·오래 안 본 글 먼저).
"""
from __future__ import annotations

import json
import logging
import urllib.parse
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from naver_autopost import history

from . import api
from .config import BloggerConfig

log = logging.getLogger(__name__)
WEBMASTERS = "https://www.googleapis.com/webmasters/v3"
INSPECT = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
MAX_INSPECT = 40
RECHECK_INDEXED_DAYS = 14        # 색인된 글은 2주마다 다시 본다(빠질 수도 있어서)
WINDOW = 28                      # 검색 노출·클릭을 더하는 기간(서치 콘솔은 2~3일 늦게 채워진다)
KEEP_DAYS = 180

# 서치 콘솔 coverageState → 짧은 한국어
STATE_KO = {
    "Submitted and indexed": "색인됨",
    "Indexed, not submitted in sitemap": "색인됨",
    "Discovered - currently not indexed": "발견됨·색인 안 됨",
    "Crawled - currently not indexed": "읽어 갔지만 색인 안 됨",
    "URL is unknown to Google": "구글이 아직 모름",
    "Redirect error": "리디렉션 오류",
    "Page with redirect": "다른 주소로 넘어감",
    "Duplicate without user-selected canonical": "중복으로 봄",
    "Duplicate, Google chose different canonical than user": "중복으로 봄",
    "Excluded by 'noindex' tag": "noindex로 막힘",
    "Soft 404": "빈 페이지로 봄",
    "Not found (404)": "없는 페이지",
}


def state_file(cfg: BloggerConfig) -> Path:
    return cfg.history_file.parent / "blogger_index.json"


def load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {"posts": data.get("posts", {}), "days": data.get("days", []), "site": data.get("site", "")}


def is_indexed(rec: dict) -> bool:
    return rec.get("verdict") == "PASS" or str(rec.get("state", "")).startswith(("Submitted and indexed", "Indexed"))


def label(state: str) -> str:
    return STATE_KO.get(state, state or "확인 전")


def _google(cfg: BloggerConfig, url: str, body: dict | None = None) -> dict:
    from .diagnose import _google as call
    return call(cfg, url, body)


def _site(cfg: BloggerConfig, known: str, call) -> str:
    if known:
        return known
    sites = call(cfg, f"{WEBMASTERS}/sites")
    if "_error" in sites:
        raise RuntimeError(f"서치 콘솔 API 오류: {sites['_error']}")
    host = urllib.parse.urlparse(cfg.blog_url).netloc if cfg.blog_url else ""
    for e in sites.get("siteEntry", []):
        if not host or host in e.get("siteUrl", ""):
            return e["siteUrl"]
    raise RuntimeError("서치 콘솔에 이 블로그가 등록되어 있지 않습니다")


def pick(posts: dict, urls: list[str], today: str, limit: int = MAX_INSPECT) -> list[str]:
    """오늘 검사할 글: 한 번도 안 본 글 → 색인 안 된 글(오래 전에 본 순) → 2주 지난 색인된 글."""
    d0 = date.fromisoformat(today)

    def age(u: str) -> int:
        c = posts.get(u, {}).get("checked")
        return (d0 - date.fromisoformat(c)).days if c else 10 ** 6

    never = [u for u in urls if u not in posts]
    waiting = sorted([u for u in urls if u in posts and not is_indexed(posts[u]) and age(u) >= 1], key=age, reverse=True)
    stale = [u for u in urls if u in posts and is_indexed(posts[u]) and age(u) >= RECHECK_INDEXED_DAYS]
    return (never + waiting + stale)[:limit]


def run(cfg: BloggerConfig, today: str, call=None, limit: int = MAX_INSPECT) -> dict:
    """오늘 한 번 모으고 그날 요약을 돌려준다. call: 테스트에서 구글 API를 바꿔 끼운다."""
    call = call or _google
    if call is _google and not api.has_scope(cfg, api.SEARCH_CONSOLE_SCOPE):
        raise RuntimeError("서치 콘솔 권한이 없습니다 → python -m blogger_autopost auth 다시 실행")
    path = state_file(cfg)
    data = load(path)
    data["site"] = site = _site(cfg, data["site"], call)
    entries = [e for e in history.load(cfg.history_file) if e.get("url")]
    pub = {e["url"]: str(e.get("date", ""))[:10] for e in entries}
    urls = sorted(pub, key=lambda u: pub[u], reverse=True)
    errors = []
    for url in pick(data["posts"], urls, today, limit):
        r = call(cfg, INSPECT, {"inspectionUrl": url, "siteUrl": site})
        if "_error" in r:
            errors.append(r["_error"][:200])
            if "429" in r["_error"] or "quota" in r["_error"].lower():
                break
            continue
        idx = (r.get("inspectionResult") or {}).get("indexStatusResult") or {}
        rec = data["posts"].setdefault(url, {})
        was = is_indexed(rec)
        rec.update(state=idx.get("coverageState") or "", verdict=idx.get("verdict") or "", checked=today,
                   crawled=str(idx.get("lastCrawlTime") or "")[:10], published=pub.get(url, ""))
        if is_indexed(rec) and not was:
            rec["indexed_seen"] = today
        elif not is_indexed(rec):
            rec.pop("indexed_seen", None)
    # 검색 노출·클릭(사이트 전체, 날짜별)
    end = date.fromisoformat(today)
    q = urllib.parse.quote(site, safe="")
    perf = call(cfg, f"{WEBMASTERS}/sites/{q}/searchAnalytics/query", {
        "startDate": (end - timedelta(days=WINDOW)).isoformat(), "endDate": end.isoformat(),
        "dimensions": ["date"], "rowLimit": 100})
    by_day = {}
    if "_error" in perf:
        errors.append(perf["_error"][:200])
    else:
        by_day = {r["keys"][0]: {"impressions": int(r.get("impressions", 0)), "clicks": int(r.get("clicks", 0))}
                  for r in perf.get("rows", [])}
    summary = summarize(data["posts"], urls, today, by_day, errors)
    data["days"] = [d for d in data["days"] if d.get("date") != today and d.get("date", "") >= (
        end - timedelta(days=KEEP_DAYS)).isoformat()] + [summary]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
    log.info("블로거 색인: %d/%d편 색인 · 최근 %d일 노출 %d·클릭 %d", summary["indexed"], summary["posts"], WINDOW,
             summary["impressions"], summary["clicks"])
    return summary


def summarize(posts: dict, urls: list[str], today: str, by_day: dict, errors: list[str] | None = None) -> dict:
    recs = [posts[u] for u in urls if u in posts]
    lags = []
    for r in recs:
        if r.get("indexed_seen") and r.get("published"):
            try:
                lags.append((date.fromisoformat(r["indexed_seen"]) - date.fromisoformat(r["published"])).days)
            except ValueError:
                pass
    states = Counter(label(r.get("state", "")) for r in recs if not is_indexed(r))
    return {
        "date": today, "posts": len(urls), "checked": len(recs), "indexed": sum(is_indexed(r) for r in recs),
        "states": dict(states.most_common()),
        "impressions": sum(v["impressions"] for v in by_day.values()),
        "clicks": sum(v["clicks"] for v in by_day.values()),
        "by_day": by_day,
        "days_to_index": sorted(lags)[len(lags) // 2] if lags else None,   # 중간값(확인한 날 기준이라 실제보다 조금 길다)
        "errors": (errors or [])[:5],
    }


def latest(path: Path) -> dict | None:
    days = load(path)["days"]
    return days[-1] if days else None


def status_line(path: Path) -> str:
    """하루 상태 보고용 한 줄(숫자만 — 공개 저장소에 올라간다)."""
    s = latest(path)
    if not s:
        return ""
    rate = f"{s['indexed'] * 100 // s['posts']}%" if s["posts"] else "-"
    top = ", ".join(f"{k} {v}" for k, v in list(s.get("states", {}).items())[:3])
    return (f"{s['date']} 색인 {s['indexed']}/{s['posts']}편({rate}, 확인한 글 {s['checked']}편) · "
            f"최근 {WINDOW}일 검색 노출 {s['impressions']}·클릭 {s['clicks']}" + (f" · 안 된 이유: {top}" if top else ""))
