"""한국 주식 대시보드 데이터: 시가총액 상위 200종목의 '시세 추세 × 거래대금 변화' 지도 + 고배당 30.

- 대상: 어제(가장 가까운 거래일) 기준 KOSPI+KOSDAQ 보통주 중, 최근 20일 하루 평균 거래대금 10억 원 이상인
  종목의 시가총액 상위 200개. 종목 목록·시가총액·배당수익률·PBR·PER은 한국거래소(pykrx, KRX_ID·KRX_PW 로그인),
  일별 가격·거래량은 Yahoo. 한국거래소가 막히면 지난번에 받은 목록(kr_universe.pkl)을 쓴다.
- 가로 = 추세 강도: 자산군 대시보드와 같은 계산(3·6·12개월 현금 대비 초과수익 ÷ 변동성, 최근 2주 제외).
- 세로 = 거래대금 변화: log2(최근 20일 평균 거래대금 ÷ 그 앞 100일 평균). +1 = 평소의 2배, −1 = 절반.
- 고배당 30: 이 200종목 중 배당수익률 상위 30. 종목 선정 연구(krcombo)에서 '대형주 200 안에서 배당 30종목,
  매달 교체'가 2018년~ 연 +15.0%, 샤프 0.83(KODEX 200 +16.9%, 0.66)이었다 — 통계적으로 확실한 수준(t 1.3)은 아니다.
- 거래대금 쪽 표시(사분면·'거래만 급증')는 검증하지 않은 관찰용이다. 코인에서 같은 생각(거래량은 늘었는데
  아직 안 오른 종목)을 시험했을 때는 비용을 넘는 수익이 나오지 않았다.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from . import signals
from .signals import Params

log = logging.getLogger(__name__)

TOP_N = 200
DIV_N = 30
MIN_VALUE = 1e9          # 하루 평균 거래대금(원)
CASH = "153130.KS"       # KODEX 단기채권(현금 기준선)
BENCH = "069500.KS"      # KODEX 200
YEARS = 3
FRAMES = 52              # 지도 시간 막대: 지난 52주(주 단위)
TRAIL = 8                # 꼬리 8주
SPIKE = 1.0              # 거래대금 변화가 이 이상(2배)이고 1개월 수익이 ±5% 안이면 '거래만 급증'
QUADS = ("거래 늘며 강세", "강세·거래 식음", "약세에 거래 몰림", "소외")


def _f(v, nd: int = 4):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else round(v, nd)


def yahoo(code: str, market: str) -> str:
    return code + (".KQ" if market == "KOSDAQ" else ".KS")


# ---------------- 데이터 ----------------
def fetch_universe(cache_dir: Path, today: datetime | None = None) -> pd.DataFrame:
    """종목코드 인덱스, 열: 종목명·시장·시가총액·DIV·PBR·PER·기준일. 시가총액 상위 보통주 넉넉히(거래대금 거르기 전)."""
    path = cache_dir / "kr_universe.pkl"
    try:
        from pykrx import stock

        day = (today or datetime.now()) - timedelta(days=1)
        cap = pd.DataFrame()
        for _ in range(10):   # 휴일이면 하루씩 앞으로
            d = day.strftime("%Y%m%d")
            cap = stock.get_market_cap(d, market="ALL")
            if not cap.empty and cap["시가총액"].sum() > 0:
                break
            day -= timedelta(days=1)
        if cap.empty:
            raise RuntimeError("시가총액 표가 비었음")
        fund = stock.get_market_fundamental(d, market="ALL")[["PER", "PBR", "DIV"]]
        kosdaq = set(stock.get_market_ticker_list(d, market="KOSDAQ"))
        df = cap[["시가총액"]].join(fund, how="left")
        df = df[[c.endswith("0") for c in df.index]].sort_values("시가총액", ascending=False).head(TOP_N * 2)
        df["시장"] = ["KOSDAQ" if c in kosdaq else "KOSPI" for c in df.index]
        df["종목명"] = [stock.get_market_ticker_name(c) for c in df.index]
        df["기준일"] = pd.Timestamp(d).strftime("%Y-%m-%d")
        cache_dir.mkdir(parents=True, exist_ok=True)
        df.to_pickle(path)
        return df
    except Exception as e:
        if path.exists():
            log.warning("한국거래소 종목 목록 실패(%s), 저장본 사용", e)
            return pd.read_pickle(path)
        raise


def fetch_prices(uni: pd.DataFrame, cache_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(수정종가, 거래량), 열 = 종목코드(+ CASH·BENCH는 Yahoo 티커 그대로)."""
    path = cache_dir / "kr_prices.pkl"
    tick = {yahoo(c, m): c for c, m in uni["시장"].items()}
    tick.update({CASH: CASH, BENCH: BENCH})
    try:
        import yfinance as yf

        start = (pd.Timestamp.today() - pd.DateOffset(years=YEARS)).strftime("%Y-%m-%d")
        raw = yf.download(sorted(tick), start=start, auto_adjust=True, progress=False, threads=True)
        close, vol = raw["Close"].rename(columns=tick), raw["Volume"].rename(columns=tick)
        if close.dropna(how="all").empty:
            raise RuntimeError("빈 시세")
        for x in (close, vol):
            x.index = pd.to_datetime(x.index).tz_localize(None)
        cache_dir.mkdir(parents=True, exist_ok=True)
        pd.to_pickle((close, vol), path)
        return close, vol
    except Exception as e:
        if path.exists():
            log.warning("한국 종목 시세 실패(%s), 저장본 사용", e)
            return pd.read_pickle(path)
        raise


# ---------------- 계산 ----------------
def quad(x: float | None, v: float | None) -> str:
    if x is None or v is None:
        return "데이터 부족"
    if x >= 0:
        return QUADS[0] if v >= 0 else QUADS[1]
    return QUADS[2] if v >= 0 else QUADS[3]


def volume_change(value: pd.DataFrame) -> pd.DataFrame:
    recent = value.rolling(20, min_periods=15).mean()
    base = value.shift(20).rolling(100, min_periods=60).mean()
    return np.log2((recent / base).where(base > 0))


def build(uni: pd.DataFrame, close: pd.DataFrame, volume: pd.DataFrame, p: Params | None = None) -> dict:
    p = p or Params()
    idx = close.index[close[BENCH].notna()] if BENCH in close else close.index
    cl = close.reindex(idx).ffill(limit=5)
    vo = volume.reindex(idx)
    value = cl * vo
    if CASH in cl and cl[CASH].notna().sum() > 100:
        cash = cl[CASH].ffill().bfill()
    else:
        cash = pd.Series((1 + 0.03 / 252) ** np.arange(len(idx)) * 100, index=idx)
    have = [c for c in uni.index if c in cl and cl[c].notna().sum() > 60]
    v20 = value[have].tail(20).mean()
    pool = [c for c in have if v20.get(c, 0) >= MIN_VALUE]
    pool = sorted(pool, key=lambda c: -uni.loc[c, "시가총액"])[:TOP_N]
    cols = pool + [BENCH]
    sig = signals.compute(cl[cols], cash, p)
    vchg = volume_change(value[cols])
    t = idx[-1]
    frame_pos = list(range(len(idx) - 1, -1, -5))[:FRAMES + TRAIL + 1][::-1]
    frames = [idx[i] for i in frame_pos]

    def ret(c, n):
        s = cl[c].dropna()
        return _f(s.iloc[-1] / s.iloc[-1 - n] - 1) if len(s) > n else None

    div = uni["DIV"].reindex(pool).where(lambda s: s > 0)
    div_top = set(div.dropna().sort_values(ascending=False).head(DIV_N).index)
    div_rank = div.rank(ascending=False, method="first")
    rows = []
    for c in cols:
        x, a, v = _f(sig["x"].loc[t, c], 3), _f(sig["accel"].loc[t, c], 3), _f(vchg.loc[t, c], 3)
        r1m = ret(c, 21)
        is_b = c == BENCH
        info = uni.loc[c] if not is_b else None
        tags = []
        if c in div_top:
            tags.append("고배당30")
        if v is not None and v >= SPIKE and r1m is not None and abs(r1m) < 0.05:
            tags.append("거래만 급증")
        if bool(sig["overheat"].loc[t, c]):
            tags.append("과열")
        rows.append({
            "code": c, "name": "KOSPI200(KODEX 200)" if is_b else str(info["종목명"]),
            "market": "지수" if is_b else str(info["시장"]), "bench": is_b,
            "cap": None if is_b else _f(info["시가총액"], 0),
            "div": None if is_b else _f(info["DIV"], 2), "pbr": None if is_b else _f(info["PBR"], 2),
            "per": None if is_b else _f(info["PER"], 1),
            "div_rank": None if is_b or math.isnan(div_rank.get(c, float("nan"))) else int(div_rank[c]),
            "x": x, "accel": a, "vchg": v, "quad": quad(x, v), "above_sma": bool(sig["above_sma"].loc[t, c]),
            "value20": _f(value[c].tail(20).mean(), 0),
            "r1w": ret(c, 5), "r1m": r1m, "r3m": ret(c, 63), "r12m": ret(c, 252),
            "vol": _f(signals.daily_vol(cl[[c]], 126).iloc[-1, 0] * math.sqrt(252)),
            "tags": tags,
            "hist": [[_f(sig["x"].loc[d, c], 3), _f(vchg.loc[d, c], 3)] for d in frames],
        })
    stocks = [r for r in rows if not r["bench"]]
    counts = {q: sum(r["quad"] == q for r in stocks) for q in QUADS}
    xs = [r["x"] for r in stocks if r["x"] is not None]
    return {
        "asof": t.strftime("%Y-%m-%d"), "universe_date": str(uni["기준일"].iloc[0]) if len(uni) else None,
        "frames": [d.strftime("%Y-%m-%d") for d in frames], "trail": TRAIL,
        "stocks": rows, "counts": counts,
        "breadth": {"above_sma": _f(np.mean([r["above_sma"] for r in stocks])) if stocks else None,
                    "median_x": _f(float(np.median(xs)), 3) if xs else None, "n": len(stocks)},
        "rule": {"top_n": TOP_N, "div_n": DIV_N, "min_value": MIN_VALUE, "spike": SPIKE},
        "missing": [str(uni.loc[c, "종목명"]) for c in uni.index[:TOP_N] if c not in have],
    }


def summary(d: dict) -> str:
    s = [r for r in d["stocks"] if not r["bench"]]
    lines = [f"[한국 종목 지도] {d['asof']} 기준 · 시가총액 상위 {len(s)}종목"]
    lines.append("  " + " · ".join(f"{q} {n}" for q, n in d["counts"].items()))
    b = d["breadth"]
    if b["above_sma"] is not None:
        lines.append(f"  200일선 위 {b['above_sma'] * 100:.0f}% · 추세 강도 중앙값 {b['median_x']}")
    div = sorted((r for r in s if "고배당30" in r["tags"]), key=lambda r: r["div_rank"] or 99)
    lines.append("  고배당 30: " + ", ".join(f"{r['name']}({r['div']}%)" for r in div[:10]) + (" …" if len(div) > 10 else ""))
    spike = [r["name"] for r in s if "거래만 급증" in r["tags"]]
    if spike:
        lines.append("  거래만 급증(관찰용): " + ", ".join(spike[:10]))
    if d["missing"]:
        lines.append("  시세를 받지 못한 종목: " + ", ".join(d["missing"][:20]))
    return "\n".join(lines)
