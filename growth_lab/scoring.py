"""점수와 판정(규칙은 코드로 고정 — Claude가 숫자를 보고 기분대로 바꾸지 못하게).

- 글 점수 = 그 글의 'N일째 조회수' ÷ 같은 블로그 글들의 'N일째 조회수' 중간값.
  블로그가 커지면 절대 조회수는 다 같이 오르므로, 같은 나이끼리 블로그 안에서 비교한다.
- 주제 점수 = 그 주제 글 점수들의 중간값. 글 1편은 운이 크게 작용하므로 시험 글 LAB_PROBE_POSTS편(기본 3)을 본 뒤 판정한다.
- 채널 점검: 블로그 전체 조회 증가가 거의 없으면(색인·노출 문제) 어떤 주제도 무덤에 넣지 않는다.
- 입질: 조회수는 적어도 대표 검색어로 네이버 상위 10위 안에 든 글이 있으면 무덤에 넣지 않는다.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from statistics import median

from .config import BLOGS, LabConfig
from .stats import post_key

OWN = "(직접 쓴 글)"
STATS_BUCKET = "논쟁×통계(예전 '숫자로 보는 한국')"


def topic_maps(data_dir: Path) -> dict[str, str]:
    """티스토리 주제 큐 id → 실험실 주제 이름(도구 계열). 예전 통계 글은 한 묶음으로 본다."""
    out: dict[str, str] = {}
    for name, bucket in (("tistory_fix_topics.json", None), ("tistory_topics.json", STATS_BUCKET)):
        path = data_dir / name
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for t in data["topics"] if isinstance(data, dict) else data:
            out[t["id"]] = bucket or f"{t.get('tool') or '기타'} 오류"
    return out


def topic_of(blog: str, entry: dict, maps: dict[str, str]) -> str:
    if entry.get("source") != "autopost":
        return OWN
    if entry.get("lab_topic"):
        return str(entry["lab_topic"]).strip()
    if BLOGS[blog].platform == "tistory":
        if entry.get("lane") == "tip":
            return "화제 제보"
        return maps.get(entry.get("topic_id", ""), entry.get("topic_id") or "기타")
    return str(entry.get("topic") or entry.get("cluster") or f"레인 {entry.get('lane') or '?'}").strip()


def _series(rows: list[dict]) -> dict[str, list[tuple[date, int]]]:
    out: dict[str, list[tuple[date, int]]] = {}
    for r in rows:
        d = date.fromisoformat(r["date"])
        for key, p in (r.get("posts") or {}).items():
            if isinstance(p.get("views"), int):
                out.setdefault(key, []).append((d, p["views"]))
    return out


def views_at_age(series: list[tuple[date, int]], published: date, age: int, tol: int = 2) -> int | None:
    """발행 뒤 age일째(앞뒤로 조금 여유) 기록된 누적 조회수."""
    best = None
    for d, v in series:
        a = (d - published).days
        if age - 1 <= a <= age + tol and (best is None or abs(a - age) < abs(best[0] - age)):
            best = (a, v)
    return best[1] if best else None


def views_at_age_daily(by_day: dict[str, int], fetched: set[str], published: date, age: int,
                       today: date) -> int | None:
    """일별 조회수를 발행일부터 age일째까지 더한 값. 그 사이 날짜를 모두 받아 왔고 age일째가 지났을 때만."""
    end = published + timedelta(days=age)
    if end >= today:
        return None
    days = [(published + timedelta(days=i)).isoformat() for i in range(age + 1)]
    if any(d not in fetched for d in days):
        return None
    return sum(int(by_day.get(d, 0)) for d in days)


def health_daily(daily: dict, today: str, days: int = 14) -> int | None:
    """최근 days일(오늘 제외) 블로그 전체(우리 글 합계) 조회수. 그 기간을 절반 넘게 못 받았으면 None."""
    d0 = date.fromisoformat(today)
    window = {(d0 - timedelta(days=i)).isoformat() for i in range(1, days + 1)}
    got = window & set(daily.get("fetched", []))
    if len(got) < days // 2:
        return None
    return sum(int(v) for by_day in daily.get("posts", {}).values() for d, v in by_day.items() if d in got)


def _best_rank(rows: list[dict], key: str) -> int | None:
    ranks = []
    for r in rows:
        rk = ((r.get("posts") or {}).get(key) or {}).get("rank") or {}
        ranks += [v for v in rk.values() if isinstance(v, int)]
    return min(ranks) if ranks else None


def post_table(blog: str, entries: list[dict], rows: list[dict], today: str, maps: dict[str, str],
               daily: dict | None = None) -> list[dict]:
    """daily(일별 글 조회수)가 있으면 그것으로, 없으면 매일 기록한 누적 조회수로 N일째 조회수를 낸다."""
    spec = BLOGS[blog]
    series = _series(rows)
    d0 = date.fromisoformat(today)
    fetched = set((daily or {}).get("fetched", []))
    per_post = (daily or {}).get("posts", {})
    out = []
    for e in entries:
        if not e.get("url"):
            continue
        try:
            pub = date.fromisoformat(str(e.get("date", ""))[:10])
        except ValueError:
            continue
        key = post_key(e["url"])
        s = series.get(key, [])
        if fetched:
            by_day = per_post.get(key, {})
            v1 = views_at_age_daily(by_day, fetched, pub, spec.eval_days[0], d0)
            v2 = views_at_age_daily(by_day, fetched, pub, spec.eval_days[1], d0)
            now = sum(int(v) for v in by_day.values())
        else:
            v1, v2 = views_at_age(s, pub, spec.eval_days[0]), views_at_age(s, pub, spec.eval_days[1])
            now = s[-1][1] if s else None
        out.append({
            "key": key, "title": e.get("title", ""), "date": pub.isoformat(), "age": (d0 - pub).days,
            "topic": topic_of(blog, e, maps), "autopost": e.get("source") == "autopost",
            "mode": e.get("lab_mode", ""), "features": e.get("lab") or {},
            "views_now": now, "v1": v1, "v2": v2,
            "best_rank": _best_rank(rows, key),
        })
    return out


def baseline(table: list[dict], field: str, min_posts: int) -> float | None:
    vals = [p[field] for p in table if isinstance(p.get(field), int)]
    return float(median(vals)) if len(vals) >= min_posts else None


def health(rows: list[dict], today: str, days: int = 14) -> int | None:
    """최근 days일 동안 블로그 전체(조회수를 읽은 글 합계) 조회 증가. 기록이 모자라면 None."""
    if not rows:
        return None
    d0 = date.fromisoformat(today)
    past = [r for r in rows if (d0 - date.fromisoformat(r["date"])).days >= days]
    if not past:
        return None
    then, now = past[-1].get("posts") or {}, rows[-1].get("posts") or {}
    gain = 0
    for key, p in now.items():
        if isinstance(p.get("views"), int):
            before = (then.get(key) or {}).get("views")
            gain += p["views"] - (before if isinstance(before, int) else 0)
    return gain


def ratios(table: list[dict], base: float | None) -> None:
    for p in table:
        p["ratio"] = round(p["v1"] / base, 2) if (base and isinstance(p.get("v1"), int)) else None


def judge(table: list[dict], cfg: LabConfig, gain: int | None) -> tuple[list[dict], str]:
    """주제별 판정. (판정 목록, 채널 상태 문구)"""
    base = baseline(table, "v1", cfg.min_baseline_posts)
    ratios(table, base)
    if base is None:
        return [], "데이터 부족(N일째 조회수가 기록된 글이 모자람 — 수집을 계속하면 풀린다)"
    channel_ok = gain is None or gain >= cfg.health_min_views
    channel = "정상" if channel_ok else f"채널 점검 필요(최근 14일 조회 증가 {gain} < {cfg.health_min_views}) — 주제 탓으로 보지 않음"
    by_topic: dict[str, list[dict]] = {}
    for p in table:
        if p["autopost"] and p["topic"] != "":
            by_topic.setdefault(p["topic"], []).append(p)
    verdicts = []
    for topic, posts in by_topic.items():
        posts.sort(key=lambda p: p["date"])
        rs = [p["ratio"] for p in posts if p["ratio"] is not None]
        bite = any(isinstance(p["best_rank"], int) and p["best_rank"] <= 10 for p in posts)
        r = round(median(rs), 2) if rs else None
        n = len(rs)
        if r is None or n < cfg.probe_posts:
            status = "promising" if (n >= 2 and r is not None and r >= cfg.promising_ratio * 1.5) else "testing"
        elif r >= cfg.promising_ratio:
            status = "core" if n >= 6 else "promising"
        elif r <= cfg.dead_ratio and not bite:
            status = "dead" if channel_ok else "hold"
        else:
            status = "neutral"
        if status in ("core", "promising") and len(rs) >= 3 and all(x < 0.8 for x in rs[-3:]):
            status = "saturated"
        ranks = [p["best_rank"] for p in posts if isinstance(p["best_rank"], int)]
        verdicts.append({"topic": topic, "status": status, "ratio": r, "evaluated": n, "posts": len(posts),
                         "bite": bite, "best_rank": min(ranks) if ranks else None})
    return sorted(verdicts, key=lambda v: (v["ratio"] is None, -(v["ratio"] or 0))), channel


def arm_scores(table: list[dict], var: str, arms: list[str], start: str, until: str) -> dict[str, dict]:
    """실험 기간에 쓴 글을 갈래(예: 화풍)별로 나눠 점수 중간값을 낸다."""
    out = {}
    for arm in arms:
        rs = [p["ratio"] for p in table if p["autopost"] and start <= p["date"] <= until
              and str((p.get("features") or {}).get(var, "base")) == arm and p.get("ratio") is not None]
        out[arm] = {"n": len(rs), "ratio": round(median(rs), 2) if rs else None}
    return out
