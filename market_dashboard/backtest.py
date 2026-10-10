"""규칙 그대로 매달 리밸런싱했을 때의 원화 기준 성과.

- 신호: 월말 종가까지의 데이터(달러 기준 가격)
- 매매: 다음 거래일 종가에 체결(신호와 같은 날 체결하는 낙관 편향 제거)
- 평가: 원화 기준 가격(환율 포함). 남는 비중은 현금(미 3개월 국채 지수)
- 비용: 바뀐 비중(회전율) × 편도 비용. 세금은 넣지 않았다(보고서에 따로 적는다)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import signals
from .signals import Params
from .universe import CASH_KEY


@dataclass
class Pick:
    key: str
    rank: int
    weight: float


def month_ends(index: pd.DatetimeIndex) -> list[pd.Timestamp]:
    s = pd.Series(index, index=index)
    return list(s.groupby([index.year, index.month]).max())


def select(t: pd.Timestamp, sig: dict, weekly: pd.DataFrame, held: set[str], p: Params,
           risky: list[str]) -> tuple[list[Pick], dict[str, str]]:
    """t 시점 목표 비중과, 탈락 사유(대시보드 표시용)."""
    x = sig["x"].loc[t, risky]
    elig = sig["eligible"].loc[t, risky]
    ranked = x[elig].sort_values(ascending=False)
    rank = {k: i + 1 for i, k in enumerate(ranked.index)}
    keep = [k for k in ranked.index if k in held and rank[k] <= p.top_n + p.hold_buffer]
    order = keep + [k for k in ranked.index if k not in keep]

    wk = weekly.loc[:t].tail(p.corr_weeks)
    corr = wk.corr(min_periods=int(p.corr_weeks * 0.6))
    chosen: list[str] = []
    why: dict[str, str] = {}
    for k in order:
        if len(chosen) >= p.top_n:
            why.setdefault(k, "순위 밖(대기)")
            continue
        clash = [c for c in chosen if k in corr and c in corr and corr.loc[k, c] > p.corr_max]
        if clash:
            why[k] = f"상관 겹침({clash[0]}와 {corr.loc[k, clash[0]]:.2f})"
            continue
        chosen.append(k)

    vol = sig["wvol"].loc[t, chosen]
    inv = 1.0 / vol.replace(0, np.nan)
    w = (inv / inv.sum()).clip(upper=p.max_weight).fillna(0.0) if chosen else pd.Series(dtype=float)
    picks = [Pick(k, rank[k], float(w.get(k, 0.0))) for k in chosen]
    return picks, why


def run(prices_sig: pd.DataFrame, prices_val: pd.DataFrame, p: Params, start: str | None = None) -> dict:
    """prices_sig: 달러 기준(신호용), prices_val: 원화 기준(평가용). 열은 자산 키."""
    risky = [c for c in prices_sig.columns if c != CASH_KEY]
    sig = signals.compute(prices_sig[risky], prices_sig[CASH_KEY], p)
    weekly = signals.weekly_returns(prices_sig[risky])
    idx = prices_val.index
    rets = prices_val.pct_change(fill_method=None).fillna(0.0)

    # 신호가 처음 생기는 달부터(가장 이른 12개월+α가 쌓인 뒤)
    first = sig["x"].dropna(how="all").index.min()
    if start:
        first = max(first, pd.Timestamp(start))
    rebal = [d for d in month_ends(idx) if d >= first]
    targets: dict[pd.Timestamp, dict[str, float]] = {}
    held: set[str] = set()
    for t in rebal:
        picks, _ = select(t, sig, weekly, held, p, risky)
        pos = idx.get_loc(t)
        if pos + 1 >= len(idx):
            continue  # 마지막 날 신호는 다음 거래일에 체결(아직 오지 않음)
        w = {pk.key: pk.weight for pk in picks if pk.weight > 0}
        w[CASH_KEY] = 1.0 - sum(w.values())
        targets[idx[pos + 1]] = w
        held = set(k for k in w if k != CASH_KEY)

    return simulate(rets, targets, p.cost, start_at=min(targets) if targets else idx[0]) | {"signals": sig, "weekly": weekly}


def simulate(rets: pd.DataFrame, targets: dict[pd.Timestamp, dict[str, float]], cost: float,
             start_at: pd.Timestamp) -> dict:
    cols = list(rets.columns)
    col = {c: i for i, c in enumerate(cols)}
    r = rets.loc[start_at:].to_numpy()
    dates = rets.loc[start_at:].index
    w = np.zeros(len(cols))
    nav = np.empty(len(dates))
    value = 1.0
    turnover = 0.0
    hist_w = {}
    for i, d in enumerate(dates):
        if i > 0:  # 오늘 수익(어제 비중 기준)
            gross = float(w @ r[i])
            value *= 1.0 + gross
            if 1.0 + gross != 0:
                w = w * (1.0 + r[i]) / (1.0 + gross)
        if d in targets:  # 오늘 종가에 체결
            new = np.zeros(len(cols))
            for k, v in targets[d].items():
                new[col[k]] = v
            tv = float(np.abs(new - w).sum())
            turnover += tv
            value *= 1.0 - tv * cost
            w = new
            hist_w[d] = dict(targets[d])
        nav[i] = value
    years = max((dates[-1] - dates[0]).days / 365.25, 1e-9)
    return {"nav": pd.Series(nav, index=dates), "weights": hist_w, "turnover_per_year": turnover / years}


def fixed_mix(rets: pd.DataFrame, mix: dict[str, float], cost: float, start_at: pd.Timestamp) -> pd.Series:
    idx = rets.loc[start_at:].index
    targets = {}
    ends = set(month_ends(idx))
    for i, d in enumerate(idx):
        if i == 0 or idx[i - 1] in ends:
            targets[d] = mix
    return simulate(rets, targets, cost, start_at)["nav"]


def metrics(nav: pd.Series, cash_nav: pd.Series) -> dict[str, float]:
    nav = nav.dropna()
    r = nav.pct_change().dropna()
    cr = cash_nav.reindex(nav.index).pct_change().reindex(r.index).fillna(0.0)
    years = (nav.index[-1] - nav.index[0]).days / 365.25
    cagr = nav.iloc[-1] ** (1 / years) - 1 if years > 0 else np.nan
    vol = r.std() * np.sqrt(252)
    ex = r - cr
    sharpe = ex.mean() / ex.std() * np.sqrt(252) if ex.std() > 0 else np.nan
    dd = nav / nav.cummax() - 1
    yearly = nav.resample("YE").last().pct_change()
    yearly.iloc[0] = nav.resample("YE").last().iloc[0] / nav.iloc[0] - 1
    monthly = nav.resample("ME").last().pct_change().dropna()
    return {
        "CAGR": cagr,
        "변동성": vol,
        "샤프": sharpe,
        "최대낙폭": dd.min(),
        "최악의 해": yearly.min(),
        "플러스 달 비율": (monthly > 0).mean(),
    }


def drawdown(nav: pd.Series) -> pd.Series:
    return nav / nav.cummax() - 1
