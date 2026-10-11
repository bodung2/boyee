"""대시보드에 넣을 데이터 묶음(JSON)을 만든다: 사분면·오늘의 답·상관·유동성·국면·백테스트."""
from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pandas as pd

from . import backtest, products, signals
from .signals import Params
from .universe import ASSETS, BENCHMARKS, CASH_KEY, GROUPS, by_key

TRAIL_DAYS = 40   # 꼬리 길이(거래일, 약 8주)
FRAME_DAYS = 252  # 시간 막대로 되돌려 볼 수 있는 기간(거래일, 약 1년)


def _f(v, nd: int = 4):
    """JSON에 넣을 수 있는 숫자(NaN → None)."""
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else round(v, nd)


def _series(s: pd.Series, nd: int = 4) -> list:
    s = s.dropna()
    return [[d.strftime("%Y-%m-%d"), _f(v, nd)] for d, v in s.items()]


def status_of(row: dict) -> str:
    if row["weight"] > 0:
        return "과열·분할 매수" if row["overheat"] else "편입"
    if row["why"]:
        return row["why"]
    q = row["quadrant"]
    if row["x"] is not None and row["x"] > 0 and not row["eligible"]:
        return "확인 부족(200일선·기간 수)"
    return {"주도": "대기", "둔화": "보유 유지·신규 X", "회복": "관심", "회피": "보유 X"}.get(q, q)


def assets_block(prices_sig, prices_val, bt, p: Params):
    sig = bt["signals"]
    weekly = bt["weekly"]
    t = prices_sig.index[-1]
    risky = list(sig["x"].columns)
    held = set()
    if bt["weights"]:
        last = bt["weights"][max(bt["weights"])]
        held = {k for k, w in last.items() if k != CASH_KEY and w > 0}
    picks, why = backtest.select(t, sig, weekly, held, p, risky)
    target = {pk.key: pk.weight for pk in picks}
    meta = by_key()
    # 거래일 단위 프레임(최근 1년 + 꼬리용 8주). 마지막 프레임 = 오늘. 화면은 프레임 사이를 보간해 부드럽게 움직인다
    frame_idx = prices_sig.index[-(FRAME_DAYS + TRAIL_DAYS + 1):]
    out = []
    for k in risky:
        x = sig["x"].loc[t, k]
        a = sig["accel"].loc[t, k]
        pv = prices_val[k].dropna()
        def ret(n):
            return _f(pv.iloc[-1] / pv.iloc[-1 - n] - 1) if len(pv) > n else None
        row = {
            "key": k, "name": meta[k].name, "group": meta[k].group,
            "x": _f(x, 3), "accel": _f(a, 3),
            "quadrant": signals.quadrant(x, a),
            "eligible": bool(sig["eligible"].loc[t, k]),
            "overheat": bool(sig["overheat"].loc[t, k]),
            "stretch": _f(sig["stretch"].loc[t, k], 2),
            "positive": int(sig["positive"].loc[t, k]),
            "above_sma": bool(sig["above_sma"].loc[t, k]),
            "weight": round(target.get(k, 0.0), 4),
            "held": k in held,
            "why": why.get(k, ""),
            "r1m": ret(21), "r3m": ret(63), "r12m": ret(252),
            # [추세, 가속, 과열] 거래일별 기록(시간 막대용)
            "hist": [[_f(sig["x"].loc[d, k], 3), _f(sig["accel"].loc[d, k], 3), int(bool(sig["overheat"].loc[d, k]))]
                     for d in frame_idx],
        }
        row["status"] = status_of(row)
        out.append(row)
    out.sort(key=lambda r: (r["x"] is None, -(r["x"] or 0)))
    return out, t.strftime("%Y-%m-%d"), frame_idx


def frame_weights(bt: dict, frame_idx) -> list[list]:
    """프레임 기간에 걸친 체결 기록 [[프레임 번호, {자산: 비중}], ...]. 첫 항목은 기간 시작 때 들고 있던 비중."""
    out, cur = [], {}
    for d in sorted(bt["weights"]):
        w = {k: round(v, 3) for k, v in bt["weights"][d].items() if k != CASH_KEY and v > 0.001}
        if d <= frame_idx[0]:
            cur = w
        else:
            out.append([int(frame_idx.searchsorted(d)), w])
    return [[0, cur]] + out


def correlation_block(weekly: pd.DataFrame) -> dict:
    short = weekly.tail(52).corr(min_periods=30)
    long = weekly.tail(156).corr(min_periods=100)
    keys = list(weekly.columns)
    edges = []
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            s, l = short.loc[a, b], long.loc[a, b]
            if pd.isna(s):
                continue
            edges.append({"a": a, "b": b, "r": _f(s, 2), "r_long": _f(l, 2),
                          "shift": bool(not pd.isna(l) and abs(s - l) >= 0.4)})
    # 평균 상관(대각 제외) 추이: 52주 창을 매주 굴린다(최근 3년)
    hist = []
    weeks = weekly.index[-156:]
    for d in weeks:
        c = weekly.loc[:d].tail(52).corr(min_periods=30).to_numpy()
        m = c[~np.eye(len(c), dtype=bool)]
        m = m[~np.isnan(m)]
        if len(m):
            hist.append([d.strftime("%Y-%m-%d"), _f(m.mean(), 3)])
    return {"edges": edges, "avg_hist": hist, "avg_now": hist[-1][1] if hist else None}


def _to_billions(s: pd.Series) -> pd.Series:
    s = s.dropna()
    return s / 1000 if len(s) and s.median() > 100_000 else s


def _z13(s: pd.Series) -> float | None:
    """13주 변화가 지난 3년 13주 변화들 중 어디쯤인지(z)."""
    w = s.resample("W-FRI").last().dropna()
    ch = w.diff(13).dropna()
    if len(ch) < 60:
        return None
    hist = ch.tail(156)
    sd = hist.std()
    return _f((ch.iloc[-1] - hist.mean()) / sd, 2) if sd > 0 else None


def liquidity_block(fred: pd.DataFrame, prices_sig: pd.DataFrame) -> dict:
    parts = {}
    net = None
    if not fred.empty and {"WALCL", "RRPONTSYD", "WTREGEN"} <= set(fred.columns):
        wal = _to_billions(fred["WALCL"]).resample("W-WED").last()
        rrp = _to_billions(fred["RRPONTSYD"]).resample("W-WED").last()
        tga = _to_billions(fred["WTREGEN"]).resample("W-WED").last()
        net = (wal - rrp.reindex(wal.index).ffill() - tga.reindex(wal.index).ffill()).dropna()
        parts["연준 순유동성"] = _z13(net)
    if "BAMLH0A0HYM2" in fred:
        z = _z13(fred["BAMLH0A0HYM2"])
        parts["하이일드 스프레드(역)"] = None if z is None else -z
    if "DFII10" in fred:
        z = _z13(fred["DFII10"])
        parts["실질금리(역)"] = None if z is None else -z
    if "UUP" in prices_sig:
        z = _z13(np.log(prices_sig["UUP"]))
        parts["달러(역)"] = None if z is None else -z
    vals = [v for v in parts.values() if v is not None]
    temp = _f(sum(vals) / len(vals), 2) if vals else None
    return {
        "temp": temp,
        "parts": [{"name": k, "z": v} for k, v in parts.items()],
        "net_hist": _series(net.tail(156), 0) if net is not None else [],
    }


def regime_block(fred: pd.DataFrame, prices_sig: pd.DataFrame) -> dict:
    """성장 = 구리/금 비율, 물가 = 10년 기대인플레이션(T10YIE). 둘 다 13주 변화의 z."""
    growth = None
    if {"CPER", "GLD"} <= set(prices_sig.columns):
        growth = _z13(np.log(prices_sig["CPER"] / prices_sig["GLD"]))
    infl = _z13(fred["T10YIE"]) if "T10YIE" in fred else None
    name = None
    if growth is not None and infl is not None:
        name = {(True, False): "골디락스(성장↑ 물가↓)", (True, True): "리플레이션(성장↑ 물가↑)",
                (False, True): "스태그플레이션(성장↓ 물가↑)", (False, False): "디플레이션·침체(성장↓ 물가↓)"}[
            (growth >= 0, infl >= 0)]
    return {"growth": growth, "inflation": infl, "name": name}


def backtest_block(prices_sig, prices_val, p: Params, bt: dict, variants: list[tuple[str, Params]]) -> dict:
    rets = prices_val.pct_change(fill_method=None).fillna(0.0)
    start = bt["nav"].index[0]
    cash = prices_val[CASH_KEY]
    navs = {"모멘텀 규칙": bt["nav"]}
    for name, mix in BENCHMARKS.items():
        if all(prices_val[k].loc[start:].notna().all() for k in mix):
            navs[name] = backtest.fixed_mix(rets, mix, p.cost, start)
    table = []
    for name, nav in navs.items():
        m = backtest.metrics(nav, cash)
        table.append({"name": name, **{k: _f(v) for k, v in m.items()}})
    table[0]["회전율"] = _f(bt["turnover_per_year"], 2)

    robust = []
    for name, vp in variants:
        r = backtest.run(prices_sig, prices_val, vp, start=str(start.date()))
        m = backtest.metrics(r["nav"], cash)
        robust.append({"name": name, **{k: _f(v) for k, v in m.items()}})

    weekly = {k: _series(v.resample("W-FRI").last(), 4) for k, v in navs.items()}
    dd = {k: _series(backtest.drawdown(v).resample("W-FRI").min(), 4) for k, v in navs.items()}
    years = {}
    for k, v in navs.items():
        y = v.resample("YE").last()
        yr = y.pct_change()
        yr.iloc[0] = y.iloc[0] / v.iloc[0] - 1
        years[k] = {str(d.year): _f(x) for d, x in yr.items()}
    # 월별 보유 이력(최근 24회)
    hist = []
    for d in sorted(bt["weights"])[-24:]:
        w = bt["weights"][d]
        hist.append({"date": d.strftime("%Y-%m-%d"),
                     "w": {k: round(v, 3) for k, v in sorted(w.items(), key=lambda kv: -kv[1]) if v > 0.001}})
    return {"start": start.strftime("%Y-%m-%d"), "table": table, "robust": robust,
            "nav": weekly, "dd": dd, "years": years, "holdings": hist}


def variants(p: Params) -> list[tuple[str, Params]]:
    return [
        ("기본(3·6·12개월, 상위 5)", p),
        ("기간 2·5·10개월", replace(p, horizons=(42, 105, 210))),
        ("기간 4·8·12개월", replace(p, horizons=(84, 168, 252))),
        ("상위 3", replace(p, top_n=3)),
        ("상위 7", replace(p, top_n=7)),
        ("상관 필터 끔", replace(p, corr_max=1.01)),
        ("최근 2주 제외 안 함", replace(p, skip=0)),
        ("비용 2배", replace(p, cost=p.cost * 2)),
    ]


def build(close: pd.DataFrame, fred: pd.DataFrame, p: Params, base: str = "KRW") -> dict:
    from .data import to_base

    prices_sig = to_base(close, "USD")
    prices_val = to_base(close, base)
    # 비교 대상(올웨더 등)의 자산이 모두 상장된 뒤부터 같은 기간으로 비교한다
    bench_assets = {k for mix in BENCHMARKS.values() for k in mix}
    bench_start = max(prices_val[k].first_valid_index() for k in bench_assets)
    bt = backtest.run(prices_sig, prices_val, p, start=str(bench_start.date()))
    assets, asof, frame_idx = assets_block(prices_sig, prices_val, bt, p)
    return {
        "asof": asof,
        "base": base,
        "groups": GROUPS,
        "params": {"horizons": list(p.horizons), "skip": p.skip, "top_n": p.top_n, "corr_max": p.corr_max,
                   "max_weight": p.max_weight, "overheat_z": p.overheat_z, "cost": p.cost},
        "assets": assets,
        "products": products.for_dashboard(),
        "frames": [d.strftime("%Y-%m-%d") for d in frame_idx],
        "trail_days": TRAIL_DAYS,
        "frame_weights": frame_weights(bt, frame_idx),
        "next_rebalance": _next_month_end(prices_sig.index[-1]),
        "corr": correlation_block(bt["weekly"]),
        "liquidity": liquidity_block(fred, prices_sig),
        "regime": regime_block(fred, prices_sig),
        "backtest": backtest_block(prices_sig, prices_val, p, bt, variants(p)[1:]),
    }


def _next_month_end(t: pd.Timestamp) -> str:
    end = (t + pd.offsets.BMonthEnd(0))
    return end.strftime("%Y-%m-%d")
