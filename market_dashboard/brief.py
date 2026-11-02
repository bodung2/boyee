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
import os
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


# ---------------- 하락 위험 신호(백테스트로 고른 미국 지표 3개) ----------------
# market_dashboard indicators(1990~2026 월말)에서 두 기간(~2007 / 2008~) 모두 같은 방향이던 지표만.
# 값: (위험 쪽 이름, 안전 쪽 이름, 위험일 때 6개월 안 −10% 하락 비율, 안전일 때 비율)
RISK_SPECS = {
    "us_trend": ("S&P500이 10개월 평균 아래", "S&P500이 10개월 평균 위", 0.44, 0.14),
    "us_mom12": ("S&P500 12개월 수익 마이너스", "S&P500 12개월 수익 플러스", 0.42, 0.16),
    "credit": ("신용 스프레드가 3개월 새 크게 벌어짐", "신용 스프레드가 3개월 새 좁아지는 쪽", 0.35, 0.14),
}
RISK_BASIS = "1990~2026년 월말 기준, 그 뒤 6개월 안에 S&P500이 −10% 넘게 빠진 적이 있었던 비율"


def _fred(sid: str) -> pd.Series:
    import io
    import urllib.request

    with urllib.request.urlopen(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd=1986-01-01", timeout=60) as r:
        df = pd.read_csv(io.BytesIO(r.read()), index_col=0, parse_dates=True, na_values=".")
    return df.iloc[:, 0].dropna()


def risk_states(spx: pd.Series, credit: pd.Series | None) -> dict:
    """오늘 기준 상태. spx = S&P500 일별 종가, credit = Baa−10년물 스프레드(일별). 판단 방식은 백테스트와 같게."""
    spx = spx.dropna()
    out = {}
    m = spx.resample("ME").last()
    m.iloc[-1] = spx.iloc[-1]                    # 이번 달은 오늘 값으로
    sma10 = m.rolling(10).mean().iloc[-1]
    out["us_trend"] = {"risk": bool(spx.iloc[-1] < sma10), "value": _num(spx.iloc[-1] / sma10 - 1, 4)}
    if len(m) > 12:
        r12 = m.iloc[-1] / m.iloc[-13] - 1
        out["us_mom12"] = {"risk": bool(r12 < 0), "value": _num(r12, 4)}
    if credit is not None and len(credit) > 400:
        cm = credit.resample("ME").last()
        cm.iloc[-1] = credit.iloc[-1]
        chg = (cm - cm.shift(3)).dropna()
        past, now = chg.iloc[:-1], chg.iloc[-1]
        rank = float((past <= now).mean())            # 과거 값만으로 매긴 백분위(백테스트와 같은 방식)
        state = True if rank >= 2 / 3 else False if rank <= 1 / 3 else None
        out["credit"] = {"risk": state, "value": None}   # 무디스 자료라 값은 싣지 않고 상태만
    return out


def fetch_risk() -> dict | None:
    try:
        import yfinance as yf

        spx = yf.download("^GSPC", period="2y", auto_adjust=True, progress=False)["Close"].squeeze()
        spx.index = pd.to_datetime(spx.index).tz_localize(None)
    except Exception as e:  # noqa: BLE001
        log.warning("S&P500 받기 실패: %s", e)
        return None
    try:
        credit = _fred("BAA10Y")
    except Exception as e:  # noqa: BLE001
        log.warning("신용 스프레드 받기 실패: %s", e)
        credit = None
    return risk_block(risk_states(spx, credit))


def risk_block(states: dict) -> dict:
    sigs = []
    for k, (risk_name, safe_name, p_risk, p_safe) in RISK_SPECS.items():
        st = states.get(k)
        if not st:
            continue
        r = st["risk"]
        sigs.append({"key": k, "state": "위험" if r else "안전" if r is False else "중간",
                     "label": risk_name if r else safe_name if r is False else risk_name.replace("크게 벌어짐", "중간쯤 변함"),
                     "value": st.get("value"), "p_if_risk": p_risk, "p_if_safe": p_safe})
    return {"signals": sigs, "on": sum(s["state"] == "위험" for s in sigs), "of": len(sigs), "basis": RISK_BASIS}


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
    r, pr = cur.get("risk"), prev.get("risk")
    if r and pr:
        was = {s["key"]: s["state"] for s in pr.get("signals", [])}
        out["risk_moves"] = [f"{s['label']}({was[s['key']]}→{s['state']})" for s in r["signals"]
                             if s["key"] in was and was[s["key"]] != s["state"]]
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
    r = b.get("risk")
    if r and r["of"]:
        out.append(f"미국 하락 위험 신호 {r['on']}/{r['of']}개 켜짐")
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
          prev: dict | None = None, now: datetime | None = None, risk: dict | None = None) -> dict:
    now = now or datetime.now(KST)
    b = {"date": now.strftime("%Y-%m-%d"), "generated": now.strftime("%Y-%m-%d %H:%M KST"),
         "dashboard_url": os.environ.get("DASHBOARD_URL") or DASHBOARD_URL, "markets": markets or [],
         "assets": _assets(dash), "us": _us(sec), "kr": _kr(kr), "risk": risk}
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


def _pub(it: dict):
    try:
        return datetime.strptime((it.get("pub_date") or "")[:16].strip(), "%a, %d %b %Y")
    except ValueError:
        return None


def drop_deleted(items: list[dict], known: dict[str, dict]) -> dict[str, dict]:
    """블로그에서 지운 시황 글은 빼낸다. RSS는 최근 글만 주므로, RSS가 덮는 기간(가장 오래된 글 날짜 이후)에
    있어야 할 글이 목록에 없을 때만 지워진 것으로 본다(그보다 오래된 글은 그대로 둔다)."""
    dates = [d for d in (_pub(it) for it in items) if d]
    if not dates:
        return known
    since = min(dates).strftime("%Y-%m-%d")
    urls = {it.get("url") for it in items}
    gone = [d for d, p in known.items() if d >= since and p.get("url") not in urls]
    for d in gone:
        log.info("블로그에서 지운 시황 글을 기록에서 뺍니다: %s %s", d, known[d].get("title"))
    return {d: p for d, p in known.items() if d not in gone}


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
        items = parse_rss(xml, blog_id)
        known = match_posts(items, drop_deleted(items, known))
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


REQUIRED = ("us", "kr")       # 이 둘이 없으면 시황 글을 쓰지 않는다(16:00 재시도)
SITE_FILES = {"dashboard.json": "assets", "sectors.json": "us", "kr.json": "kr"}


def for_post(today: str, out_path: Path, site_url: str = DASHBOARD_URL, build_dir: Path | None = None,
             wait_min: int = 15, sleep=None) -> Path:
    """오늘 시황 글의 글감(brief)을 out_path에 저장한다.

    1) 게시된 대시보드의 brief.json이 오늘 것이면 그대로 쓴다(블로그 글과 대시보드 숫자가 같아진다).
       아직 아니면 wait_min분 기다렸다가 한 번 더 본다(GitHub 갱신이 늦게 도는 날).
    2) 그래도 아니면 이 PC에서 세 화면을 직접 계산한다. 화면마다 기록을 남기고(dashboard/<화면>.log), 실패하면 한 번 더,
       그래도 안 되면 게시된 그 화면 파일(어제 것일 수 있음)을 쓴다.
    3) 미국 섹터·한국 종목 중 하나라도 끝내 없으면 멈춘다(빠진 채로 글을 쓰지 않는다).
    """
    import subprocess
    import sys
    import time as _time

    sleep = sleep or _time.sleep
    base = site_url.rstrip("/") + "/"
    site = _get_json(base + "brief.json")
    if not (site and site.get("date") == today) and wait_min > 0:
        log.info("게시된 요약이 아직 오늘 것이 아니라(%s) %d분 기다립니다", (site or {}).get("date"), wait_min)
        sleep(wait_min * 60)
        site = _get_json(base + "brief.json") or site
    if site and site.get("date") == today and all(site.get(k) for k in REQUIRED):
        b = site
    else:
        log.info("게시된 요약을 쓸 수 없어(%s) 이 PC에서 계산합니다", (site or {}).get("date"))
        build_dir = build_dir or out_path.parent / "dashboard"
        build_dir.mkdir(parents=True, exist_ok=True)
        root = Path(__file__).resolve().parent.parent
        commands = {"dashboard.json": "run", "sectors.json": "sectors", "kr.json": "krstocks"}
        for attempt in (1, 2):
            for name, cmd in commands.items():
                if (build_dir / name).exists():
                    continue
                with open(build_dir / f"{cmd}.log", "a", encoding="utf-8") as fh:
                    fh.write(f"\n=== {attempt}회째 ===\n")
                    fh.flush()
                    r = subprocess.run([sys.executable, "-m", "market_dashboard", cmd, "--out", str(build_dir)],
                                       cwd=root, timeout=1800, check=False, stdout=fh, stderr=subprocess.STDOUT)
                if not (build_dir / name).exists():
                    log.warning("%s 계산 실패(%d회째, 종료 코드 %s) — 기록: %s", cmd, attempt, r.returncode,
                                build_dir / f"{cmd}.log")

        used_site = []

        def read(name):
            f = build_dir / name
            if f.exists():
                return json.loads(f.read_text(encoding="utf-8"))
            d = _get_json(base + name)          # 게시된 화면 파일(마지막 갱신분)
            if d:
                used_site.append(name)
            return d

        b = build(read("dashboard.json"), read("sectors.json"), read("kr.json"), fetch_markets(),
                  prev=site if site and site.get("date", "") < today else None, risk=fetch_risk())
        b["source"] = "local"
        if used_site:
            b["from_site"] = used_site
            log.warning("이 PC에서 못 만든 화면은 게시된 파일을 썼습니다: %s", ", ".join(used_site))
    missing = [k for k in REQUIRED if not b.get(k)]
    if missing:
        names = {"us": "미국 섹터", "kr": "한국 종목"}
        raise RuntimeError(f"{'·'.join(names[k] for k in missing)} 숫자를 받지 못해 시황 글을 쓰지 않습니다"
                           f"(기록: {out_path.parent / 'dashboard'})")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(b, ensure_ascii=False, indent=1), encoding="utf-8")
    return out_path
