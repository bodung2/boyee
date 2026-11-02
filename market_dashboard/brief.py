"""매일 시황 요약(brief): 세 화면(자산군·미국 섹터·한국 종목)의 오늘 숫자를 한 장으로 줄이고, 어제와 비교한다.

- 대시보드 위쪽 요약 줄과 '시황 기록' 화면이 이 요약을 쓴다.
- 네이버 투자 블로그의 매일 시황 글(naver_autopost --profile market)이 이 요약을 글감으로 받는다.
  글 속 대시보드 숫자는 모두 이 파일 값 그대로다(팩트체크 기준).
- 날짜별로 data/market/briefs/YYYY-MM-DD.json에 쌓아 두고, 블로그 RSS에서 'M월 D일 시황' 제목의 글을 찾아
  같은 날짜에 링크를 붙인다(posts.json).
"""
from __future__ import annotations

import json
import logging
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
DASHBOARD_URL = "https://bodung2.github.io/boyee/"
# 시황 글의 주요 지수(야후 티커 → 이름). 하루·한 주 변화만 쓴다.
MARKETS = {
    "^GSPC": "S&P500", "^IXIC": "나스닥", "^KS11": "코스피", "^KQ11": "코스닥",
    "KRW=X": "원/달러 환율", "^TNX": "미국 10년물 금리(%)",
}
KR_HOURS = {"^KS11", "^KQ11", "KRW=X"}
POST_TITLE = re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일[^|]{0,6}시황")


def _num(v, nd: int = 3):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else round(v, nd)


def fetch_markets() -> list[dict]:
    """주요 지수 종가와 하루·한 주 변화. 실패하면 빈 목록."""
    try:
        import yfinance as yf

        raw = yf.download(list(MARKETS), period="1mo", auto_adjust=False, progress=False, threads=True)["Close"]
    except Exception as e:  # noqa: BLE001 - 지수가 없어도 요약은 만든다
        log.warning("주요 지수 실패: %s", e)
        return []
    from .kr_stocks import drop_unfinished

    raw.index = pd.to_datetime(raw.index).tz_localize(None)
    out = []
    for t, name in MARKETS.items():
        if t not in raw:
            continue
        s = raw[t].dropna()
        if t in KR_HOURS:   # 한국장·환율은 장중이면 오늘 값이 미완성이다
            s = drop_unfinished(s.to_frame())[t]
        if len(s) < 6:
            continue
        last, prev, week = float(s.iloc[-1]), float(s.iloc[-2]), float(s.iloc[-6])
        is_rate = t == "^TNX"
        out.append({
            "ticker": t, "name": name, "date": s.index[-1].strftime("%Y-%m-%d"), "close": _num(last, 2),
            # 금리는 %p 변화, 나머지는 % 변화
            "d1": _num(last - prev if is_rate else last / prev - 1, 4),
            "w1": _num(last - week if is_rate else last / week - 1, 4),
            "unit": "%p" if is_rate else "%",
        })
    return out


# ---------------- 요약 만들기 ----------------
def _assets(dash: dict | None) -> dict | None:
    """자산군은 '어디 추세가 강한가'만 적는다. 규칙상 편입·비중은 매수 권유로 읽힐 수 있어 요약에 넣지 않는다."""
    if not dash or not dash.get("assets"):
        return None
    a = dash["assets"]
    strong = [{"name": r["name"], "x": r["x"], "quadrant": r["quadrant"]} for r in a if r.get("x") is not None][:3]
    turning = [r["name"] for r in a if r.get("quadrant") == "회복" and (r.get("x") or -9) > -0.3]
    return {"asof": dash.get("asof"), "strongest": strong, "turning": turning,
            "liquidity": _num((dash.get("liquidity") or {}).get("temp"), 2)}


def _us(sec: dict | None) -> dict | None:
    c = next((c for c in (sec or {}).get("countries", []) if c.get("key") == "US"), None)
    if not c:
        return None
    rows = [s for s in c["sectors"] if s.get("x") is not None]
    rank = [{"name": s["name"], "x": s["x"], "accel": s["accel"], "quadrant": s["quadrant"], "r1m": s.get("r1m")}
            for s in rows]
    return {"asof": c.get("asof"), "rank": rank,
            "leaders": [r["name"] for r in rank if r["quadrant"] == "주도"][:3],
            "weakening": [r["name"] for r in rank if r["quadrant"] == "둔화"][:3],
            "laggards": [r["name"] for r in rank[-2:]]}


def _kr(kr: dict | None) -> dict | None:
    if not kr or not kr.get("stocks"):
        return None
    stocks = [s for s in kr["stocks"] if not s.get("bench")]
    bench = next((s for s in kr["stocks"] if s.get("bench")), {})
    lead = sorted((s for s in stocks if s["quad"] == "거래 늘며 강세" and s.get("vchg") is not None),
                  key=lambda s: -s["vchg"])[:5]
    moved = [s for s in stocks if s.get("r1w") is not None]
    up = sorted(moved, key=lambda s: -s["r1w"])[:5]
    down = sorted(moved, key=lambda s: s["r1w"])[:5]
    div = sorted((s for s in stocks if "고배당30" in s["tags"]), key=lambda s: s.get("div_rank") or 99)

    def brief_row(s):
        return {"code": s["code"], "name": s["name"], "r1w": s.get("r1w"), "vchg": s.get("vchg")}

    return {"asof": kr.get("asof"), "n": kr["breadth"]["n"], "above_sma": kr["breadth"]["above_sma"],
            "median_x": kr["breadth"]["median_x"], "counts": kr["counts"],
            "kospi200": {"x": bench.get("x"), "r1w": bench.get("r1w"), "r1m": bench.get("r1m")},
            "lead_with_volume": [brief_row(s) for s in lead],
            "week_up": [brief_row(s) for s in up], "week_down": [brief_row(s) for s in down],
            "volume_only": [s["name"] for s in stocks if "거래만 급증" in s["tags"]],
            "div30": [{"code": s["code"], "name": s["name"], "div": s.get("div")} for s in div]}


def _changes(cur: dict, prev: dict | None) -> dict:
    """어제(지난번 요약) 대비 바뀐 것."""
    if not prev:
        return {}
    out: dict = {"since": prev.get("date")}
    k, pk = cur.get("kr"), prev.get("kr")
    if k and pk:
        if k.get("above_sma") is not None and pk.get("above_sma") is not None:
            out["kr_above_sma_pp"] = _num((k["above_sma"] - pk["above_sma"]) * 100, 1)
        out["kr_counts"] = {q: n - (pk.get("counts") or {}).get(q, 0) for q, n in (k.get("counts") or {}).items()}
        now, before = {d["code"]: d["name"] for d in k["div30"]}, {d["code"]: d["name"] for d in pk.get("div30", [])}
        out["div30_in"] = [n for c, n in now.items() if c not in before]
        out["div30_out"] = [n for c, n in before.items() if c not in now]
    u, pu = cur.get("us"), prev.get("us")
    if u and pu:
        was = {r["name"]: r["quadrant"] for r in pu.get("rank", [])}
        out["us_moves"] = [f"{r['name']} {was[r['name']]}→{r['quadrant']}" for r in u["rank"]
                           if r["name"] in was and was[r["name"]] != r["quadrant"]]
    return out


def headline(b: dict) -> list[str]:
    """요약 줄에 쓰는 짧은 문장 3~5개(숫자는 모두 요약 값 그대로)."""
    out = []
    k = b.get("kr")
    if k:
        pp = (b.get("changes") or {}).get("kr_above_sma_pp")
        out.append(f"한국 상위 {k['n']}종목 중 200일선 위 {k['above_sma'] * 100:.0f}%"
                   + (f"({pp:+.0f}%p)" if pp is not None and round(pp) != 0 else ""))
    u = b.get("us")
    if u and u["leaders"]:
        out.append("미국 주도 섹터: " + "·".join(u["leaders"]))
    a = b.get("assets")
    if a and a["strongest"]:
        out.append("추세 강한 자산: " + "·".join(r["name"] for r in a["strongest"]))
    for m in b.get("markets") or []:
        if m["ticker"] in ("^KS11", "^GSPC") and m.get("d1") is not None:
            out.append(f"{m['name']} {m['d1'] * 100:+.1f}%")
    return out


def build(dash: dict | None, sec: dict | None, kr: dict | None, markets: list[dict] | None = None,
          prev: dict | None = None, now: datetime | None = None) -> dict:
    now = now or datetime.now(KST)
    b = {"date": now.strftime("%Y-%m-%d"), "generated": now.strftime("%Y-%m-%d %H:%M KST"),
         "dashboard_url": DASHBOARD_URL, "markets": markets or [],
         "assets": _assets(dash), "us": _us(sec), "kr": _kr(kr)}
    b["changes"] = _changes(b, prev)
    b["headline"] = headline(b)
    return b


# ---------------- 날짜별 기록·글 링크 ----------------
def load_archive(arch: Path) -> list[dict]:
    out = []
    for p in sorted(arch.glob("????-??-??.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception as e:  # noqa: BLE001 - 깨진 파일 하나 때문에 기록 화면이 멈추지 않게
            log.warning("기록 파일 무시(%s): %s", p.name, e)
    return out


def save_archive(arch: Path, b: dict) -> None:
    arch.mkdir(parents=True, exist_ok=True)
    (arch / f"{b['date']}.json").write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")


def previous(archive: list[dict], date: str) -> dict | None:
    older = [b for b in archive if b.get("date", "") < date]
    return older[-1] if older else None


def match_posts(items: list[dict], known: dict[str, dict] | None = None) -> dict[str, dict]:
    """RSS 글 목록에서 'M월 D일 시황' 제목을 찾아 {날짜: {title, url}}. 연도는 발행일에서 가져온다."""
    known = dict(known or {})
    for it in items:
        m = POST_TITLE.search(it.get("title", ""))
        if not m:
            continue
        try:
            pub = datetime.strptime((it.get("pub_date") or "")[:16].strip(), "%a, %d %b %Y")
        except ValueError:
            pub = datetime.now(KST)
        month, day = int(m.group(1)), int(m.group(2))
        year = pub.year - (1 if month == 12 and pub.month == 1 else 0)   # 12월 31일 시황을 1월 1일에 올린 경우
        try:
            key = datetime(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            continue
        known[key] = {"title": it["title"], "url": it["url"]}
    return known


def sync_posts(arch: Path, blog_id: str) -> dict[str, dict]:
    """블로그 RSS에서 시황 글 링크를 찾아 posts.json에 쌓는다(RSS는 최근 글만 주므로 누적 보관)."""
    path = arch / "posts.json"
    known = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not blog_id:
        return known
    try:
        import urllib.request

        from naver_autopost.history import parse_rss

        req = urllib.request.Request(f"https://rss.blog.naver.com/{blog_id}.xml",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            xml = resp.read().decode("utf-8", "replace")
        known = match_posts(parse_rss(xml, blog_id), known)
        arch.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(known, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:  # noqa: BLE001 - 링크가 없어도 기록 화면은 만든다
        log.warning("블로그 RSS 실패: %s", e)
    return known


def history_rows(archive: list[dict], posts: dict[str, dict]) -> list[dict]:
    rows = []
    for b in sorted(archive, key=lambda b: b.get("date", ""), reverse=True):
        rows.append({"date": b["date"], "headline": b.get("headline", []), "post": posts.get(b["date"]),
                     "changes": b.get("changes", {})})
    return rows


# ---------------- 시황 글(집 PC)이 쓰는 입구 ----------------
def _get_json(url: str, timeout: int = 20) -> dict | None:
    import urllib.request

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        log.warning("%s 받기 실패: %s", url, e)
        return None


def for_post(today: str, out_path: Path, site_url: str = DASHBOARD_URL, build_dir: Path | None = None) -> Path:
    """오늘 시황 글의 글감(brief)을 out_path에 저장한다.

    1) 게시된 대시보드의 brief.json이 오늘 것이면 그대로 쓴다(블로그 글과 대시보드 숫자가 같아진다).
    2) 아니면(대시보드 갱신이 늦은 날) 이 PC에서 세 화면을 직접 계산해 만들고, 게시된 요약을 어제 값으로 비교한다.
    """
    import subprocess
    import sys

    site = _get_json(site_url.rstrip("/") + "/brief.json")
    if site and site.get("date") == today:
        b = site
    else:
        log.info("게시된 요약이 오늘 것이 아니라(%s) 이 PC에서 계산합니다", (site or {}).get("date"))
        build_dir = build_dir or out_path.parent / "dashboard"
        build_dir.mkdir(parents=True, exist_ok=True)
        for cmd in ("run", "sectors", "krstocks"):
            subprocess.run([sys.executable, "-m", "market_dashboard", cmd, "--out", str(build_dir)],
                           cwd=Path(__file__).resolve().parent.parent, timeout=1800, check=False)

        def read(name):
            f = build_dir / name
            return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None

        b = build(read("dashboard.json"), read("sectors.json"), read("kr.json"), fetch_markets(),
                  prev=site if site and site.get("date", "") < today else None)
        if not (b.get("kr") or b.get("us") or b.get("assets")):
            raise RuntimeError("대시보드 숫자를 하나도 만들지 못했습니다(시세 받기 실패)")
        b["source"] = "local"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
    return out_path
