"""주식 섹터 대시보드 데이터: 나라별 섹터 사분면(추세 강도 × 가속도), 섹터 순환 백테스트, 섹터별 종목 후보.

- 섹터 강도: 섹터 ETF 가격(현지 통화)으로 자산군 대시보드와 같은 계산(signals.compute).
- 현금 기준선: 미국 = 3개월 국채금리(^IRX)를 쌓은 지수, 한국 = 단기채권 ETF 가격(없으면 연 3% 가정).
- 섹터 순환 규칙(SECTOR_RULE): 추세 강도 상위 3개 섹터, 역변동성 비중(최대 50%), 매달 리밸런싱, 다음 거래일 체결.
- 종목 후보: 섹터 안 대표 종목을 '추세 50% + 낮은 변동성 25% + 작은 낙폭 25%' 순위로 정렬.
  종목 목록이 지금 기준이라 백테스트하지 않는다(망한 종목이 빠진 생존 편향) → 후보 좁히기 용도.
"""
from __future__ import annotations

import logging
import math
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from . import backtest, signals
from .signals import Params
from .sector_universe import COUNTRIES, SECTOR_RULE, Country

log = logging.getLogger(__name__)

START = "2004-01-01"
TRAIL_DAYS = 40
FRAME_DAYS = 252
CASH, BENCH = "CASH", "BENCH"


def _f(v, nd: int = 4):
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else round(v, nd)


def tickers(c: Country) -> list[str]:
    out = {c.benchmark, c.cash}
    for s in c.sectors:
        out.add(s.etf)
        out.update(s.stocks)
    return sorted(out)


def fetch(c: Country, cache_dir: Path, start: str = START) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(수정종가, 거래량). 실패하면 저장본."""
    path = cache_dir / f"sectors_{c.key}.pkl"
    try:
        import yfinance as yf

        raw = yf.download(tickers(c), start=start, auto_adjust=True, progress=False, threads=True)
        close, vol = raw["Close"].dropna(how="all"), raw["Volume"]
        if close.empty:
            raise RuntimeError("빈 시세")
        close.index = pd.to_datetime(close.index).tz_localize(None)
        vol.index = pd.to_datetime(vol.index).tz_localize(None)
        cache_dir.mkdir(parents=True, exist_ok=True)
        pd.to_pickle((close, vol), path)
        return close, vol
    except Exception as e:
        if path.exists():
            log.warning("%s 시세 받기 실패(%s), 저장본 사용", c.name, e)
            return pd.read_pickle(path)
        raise


def cash_index(c: Country, close: pd.DataFrame, idx: pd.DatetimeIndex) -> pd.Series:
    if c.cash in close and close[c.cash].notna().sum() > 100:
        s = close[c.cash].reindex(idx).ffill()
        if c.cash_is_rate:
            return (1 + s.fillna(0) / 100 / 252).cumprod() * 100
        return s.bfill()
    return pd.Series((1 + 0.03 / 252) ** np.arange(len(idx)) * 100, index=idx)  # 대용: 연 3%


def panel(c: Country, close: pd.DataFrame) -> pd.DataFrame:
    """섹터 키 + CASH + BENCH 열, 그 나라 지수 ETF가 거래된 날만."""
    idx = close.index[close[c.benchmark].notna()] if c.benchmark in close else close.index
    cl = close.reindex(idx).ffill()
    out = {s.key: cl[s.etf] for s in c.sectors if s.etf in cl and cl[s.etf].notna().sum() > 0}
    out[CASH] = cash_index(c, close, idx)
    out[BENCH] = cl[c.benchmark]
    return pd.DataFrame(out)


def stock_table(c: Country, close: pd.DataFrame, volume: pd.DataFrame, cash: pd.Series, p: Params) -> dict:
    """섹터 키 → 종목 후보 목록(정렬됨)."""
    idx = cash.index
    names = {t: n for s in c.sectors for t, n in s.stocks.items()}
    have = [t for t in names if t in close and close[t].notna().sum() > 0]
    cl = close.reindex(idx)[have].ffill()
    vo = volume.reindex(idx)[have]
    sig = signals.compute(cl, cash, p)
    t = idx[-1]
    vol_a = signals.daily_vol(cl, 126).iloc[-1] * math.sqrt(252)
    last = cl.tail(252)
    mdd = (last / last.cummax() - 1).min()
    value20 = (cl * vo).tail(20).mean()

    def ret(k, n):
        s = cl[k].dropna()
        return _f(s.iloc[-1] / s.iloc[-1 - n] - 1) if len(s) > n else None

    out = {}
    for s in c.sectors:
        rows = []
        for tk, nm in s.stocks.items():
            if tk not in have:
                rows.append({"ticker": tk, "name": nm, "status": "데이터 없음"})
                continue
            x = sig["x"].loc[t, tk]
            above = bool(sig["above_sma"].loc[t, tk])
            liq = value20.get(tk)
            if math.isnan(x):
                st = "기록 부족(상장 1년 미만)"
            elif liq is not None and not math.isnan(liq) and liq < c.min_value:
                st = "거래대금 부족"
            elif x > p.min_x and above:
                st = "후보"
            elif x > 0 and above:
                st = "관찰(추세 약함)"
            else:
                st = "약세"
            rows.append({"ticker": tk, "name": nm, "x": _f(x, 3), "accel": _f(sig["accel"].loc[t, tk], 3),
                         "quadrant": signals.quadrant(x, sig["accel"].loc[t, tk]), "above_sma": above,
                         "vol": _f(vol_a.get(tk)), "mdd": _f(mdd.get(tk)), "value20": _f(liq, 0),
                         "overheat": bool(sig["overheat"].loc[t, tk]),
                         "r1m": ret(tk, 21), "r3m": ret(tk, 63), "r12m": ret(tk, 252), "status": st})
        scored = [r for r in rows if r.get("x") is not None]
        if scored:
            df = pd.DataFrame(scored).set_index("ticker")
            score = (0.5 * df["x"].rank(pct=True) + 0.25 * (-df["vol"]).rank(pct=True)
                     + 0.25 * df["mdd"].rank(pct=True))
            for r in scored:
                r["score"] = _f(score.get(r["ticker"]), 3)
        order = {"후보": 0, "관찰(추세 약함)": 1, "약세": 2, "거래대금 부족": 3, "기록 부족(상장 1년 미만)": 4, "데이터 없음": 5}
        rows.sort(key=lambda r: (order.get(r["status"], 9), -(r.get("score") or -1)))
        out[s.key] = rows
    return out


def sector_params() -> Params:
    return replace(Params(), **SECTOR_RULE)


def country_block(c: Country, close: pd.DataFrame, volume: pd.DataFrame, p: Params | None = None) -> dict:
    p = p or sector_params()
    px = panel(c, close)
    risky = [s.key for s in c.sectors if s.key in px]
    sig_px = px[risky + [CASH]]
    sig = signals.compute(px[risky], px[CASH], p)
    # 백테스트는 섹터 8개 이상(적으면 전부)이 신호를 낼 수 있게 된 뒤부터
    need = min(8, len(risky))
    ok = sig["x"].notna().sum(axis=1) >= need
    start = ok.idxmax() if ok.any() else px.index[0]
    bt = backtest.run(sig_px, px, p, start=str(start.date()))
    rets = px.pct_change(fill_method=None).fillna(0.0)
    bstart = bt["nav"].index[0]
    bench = backtest.fixed_mix(rets, {BENCH: 1.0}, p.cost, bstart)
    table = []
    for name, nav in (("섹터 순환 규칙", bt["nav"]), (c.benchmark_name + " 보유", bench)):
        m = backtest.metrics(nav, px[CASH])
        table.append({"name": name, **{k: _f(v) for k, v in m.items()}})
    table[0]["회전율"] = _f(bt["turnover_per_year"], 2)
    robust = []
    for name, vp in (("상위 2", replace(p, top_n=2)), ("상위 4", replace(p, top_n=4)),
                     ("편입 기준 0", replace(p, min_x=0.0)), ("비용 2배", replace(p, cost=p.cost * 2))):
        r = backtest.run(sig_px, px, vp, start=str(bstart.date()))
        robust.append({"name": name, **{k: _f(v) for k, v in backtest.metrics(r["nav"], px[CASH]).items()}})

    t = px.index[-1]
    held = set()
    if bt["weights"]:
        held = {k for k, w in bt["weights"][max(bt["weights"])].items() if k != CASH and w > 0}
    picks, why = backtest.select(t, bt["signals"], bt["weekly"], held, p, risky)
    target = {pk.key: pk.weight for pk in picks}
    frame_idx = px.index[-(FRAME_DAYS + TRAIL_DAYS + 1):]
    vol_a = signals.daily_vol(px[risky], 126).iloc[-1] * math.sqrt(252)
    stocks = stock_table(c, close, volume, px[CASH], Params())
    sectors = []
    for s in c.sectors:
        if s.key not in risky:
            continue
        k = s.key
        x, a = sig["x"].loc[t, k], sig["accel"].loc[t, k]
        pv = px[k].dropna()

        def ret(n):
            return _f(pv.iloc[-1] / pv.iloc[-1 - n] - 1) if len(pv) > n else None

        w = round(target.get(k, 0.0), 4)
        q = signals.quadrant(x, a)
        if w > 0:
            status = "규칙상 편입" + (" · 과열(분할)" if bool(sig["overheat"].loc[t, k]) else "")
        elif why.get(k):
            status = why[k]
        elif not math.isnan(x) and 0 < x <= p.min_x:
            status = f"추세 약함({p.min_x} 미만)"
        else:
            status = {"주도": "대기", "둔화": "보유 유지·신규 X", "회복": "관심", "회피": "보유 X"}.get(q, q)
        sectors.append({
            "key": k, "name": s.name, "etf": s.etf, "etf_name": s.etf_name,
            "x": _f(x, 3), "accel": _f(a, 3), "quadrant": q, "vol": _f(vol_a.get(k)),
            "above_sma": bool(sig["above_sma"].loc[t, k]), "overheat": bool(sig["overheat"].loc[t, k]),
            "weight": w, "status": status, "r1m": ret(21), "r3m": ret(63), "r12m": ret(252),
            "hist": [[_f(sig["x"].loc[d, k], 3), _f(sig["accel"].loc[d, k], 3), int(bool(sig["overheat"].loc[d, k]))]
                     for d in frame_idx],
            "stocks": stocks.get(k, []),
        })
    sectors.sort(key=lambda r: (r["x"] is None, -(r["x"] or 0)))
    missing = [tk for tk in tickers(c) if tk not in close or close[tk].notna().sum() == 0]
    return {"key": c.key, "name": c.name, "currency": c.currency, "benchmark": c.benchmark_name,
            "asof": t.strftime("%Y-%m-%d"), "frames": [d.strftime("%Y-%m-%d") for d in frame_idx],
            "trail_days": TRAIL_DAYS, "sectors": sectors, "missing": missing,
            "backtest": {"start": bstart.strftime("%Y-%m-%d"), "table": table, "robust": robust},
            "min_value": c.min_value}


def build(data: dict[str, tuple[pd.DataFrame, pd.DataFrame]]) -> dict:
    p = sector_params()
    return {"params": {"min_x": p.min_x, "top_n": p.top_n, "max_weight": p.max_weight, "cost": p.cost},
            "countries": [country_block(c, *data[c.key], p) for c in COUNTRIES if c.key in data]}


def summary(d: dict) -> str:
    lines = []
    for c in d["countries"]:
        lines.append(f"[{c['name']} 섹터] {c['asof']} 기준")
        for s in c["sectors"]:
            top = [r["name"] for r in s["stocks"] if r["status"] == "후보"][:3]
            lines.append(f"  {s['name']:<8} 추세 {s['x'] if s['x'] is not None else '–':>6} 가속 {s['accel'] if s['accel'] is not None else '–':>6} "
                         f"{s['quadrant']:<4} {s['status']}" + (f" · 후보 종목: {', '.join(top)}" if top else ""))
        for r in c["backtest"]["table"] + c["backtest"]["robust"]:
            lines.append(f"  [{c['backtest']['start']}~] {r['name']:<20} CAGR {(r['CAGR'] or 0) * 100:+.1f}% "
                         f"샤프 {r['샤프'] or 0:.2f} 최대낙폭 {(r['최대낙폭'] or 0) * 100:.1f}%")
        if c["missing"]:
            lines.append("  받지 못한 티커: " + ", ".join(c["missing"]))
    return "\n".join(lines)
