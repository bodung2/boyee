"""신호 계산: 추세 강도(X) · 가속도(Y) · 확인 조건 · 과열.

모든 값은 그날 종가까지의 데이터만 쓴다(미래 데이터 금지). 신호는 달러 기준 가격으로 계산하고
(연구 관례와 같게, 환율 움직임이 신호를 흔들지 않게), 수익은 백테스트에서 원화로 평가한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Params:
    horizons: tuple[int, ...] = (63, 126, 252)  # 3·6·12개월(거래일)
    skip: int = 10                               # 최근 2주는 뺀다(단기 반전 회피)
    vol_window: int = 126
    accel_lag: int = 20                          # 가속도 = 지금 X − 4주 전 X
    sma_long: int = 200
    sma_short: int = 50
    min_positive: int = 2                        # 3개 기간 중 몇 개가 현금보다 나아야 하나
    overheat_z: float = 2.5                      # 50일선 이탈이 변동성 대비 이 이상이면 과열
    top_n: int = 5
    hold_buffer: int = 2                         # 보유 자산은 top_n+buffer 위까지 밀려도 유지
    corr_weeks: int = 52
    corr_max: float = 0.7                        # 이미 담은 자산과 상관이 이보다 높으면 건너뜀
    max_weight: float = 0.35
    weight_vol_window: int = 63
    cost: float = 0.0015                         # 편도 거래비용+환전 스프레드(가정)
    extra: dict = field(default_factory=dict, compare=False)


def daily_vol(prices: pd.DataFrame, window: int) -> pd.DataFrame:
    lr = np.log(prices).diff()
    return lr.rolling(window, min_periods=int(window * 0.8)).std()


def trend_components(prices: pd.DataFrame, cash: pd.Series, p: Params) -> dict[int, pd.DataFrame]:
    """기간별 '현금 대비 초과 로그수익 ÷ (일간 변동성 × √기간)'."""
    lp = np.log(prices)
    lc = np.log(cash)
    vol = daily_vol(prices, p.vol_window)
    out = {}
    for h in p.horizons:
        ex = (lp.shift(p.skip) - lp.shift(p.skip + h)).sub(lc.shift(p.skip) - lc.shift(p.skip + h), axis=0)
        out[h] = ex / (vol * np.sqrt(h))
    return out


def compute(prices: pd.DataFrame, cash: pd.Series, p: Params) -> dict[str, pd.DataFrame]:
    comps = trend_components(prices, cash, p)
    stacked = np.stack([c.to_numpy() for c in comps.values()])
    # 기간 하나라도 계산이 안 되면 NaN(상장 초기 자산은 12개월이 쌓일 때까지 제외)
    x = pd.DataFrame(stacked.mean(axis=0), index=prices.index, columns=prices.columns)
    positive = pd.DataFrame((stacked > 0).sum(axis=0), index=prices.index, columns=prices.columns)
    accel = x - x.shift(p.accel_lag)
    above = prices > prices.rolling(p.sma_long, min_periods=p.sma_long).mean()
    vol = daily_vol(prices, p.vol_window)
    sma_s = prices.rolling(p.sma_short, min_periods=p.sma_short).mean()
    # 랜덤워크에서 '가격 − n일 평균'의 표준편차 ≈ σ·√(n/3)
    stretch = (np.log(prices) - np.log(sma_s)) / (vol * np.sqrt(p.sma_short / 3))
    eligible = (x > 0) & (positive >= p.min_positive) & above
    return {
        "x": x,
        "accel": accel,
        "positive": positive,
        "above_sma": above,
        "stretch": stretch,
        "overheat": stretch > p.overheat_z,
        "eligible": eligible.fillna(False).astype(bool),
        "wvol": daily_vol(prices, p.weight_vol_window),
    }


def weekly_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """주간(금요일) 수익률. 한국·미국 장 마감 시각 차이로 일간 상관이 낮게 나오는 문제를 피한다."""
    return prices.resample("W-FRI").last().pct_change(fill_method=None)


def quadrant(x: float, a: float) -> str:
    if np.isnan(x) or np.isnan(a):
        return "데이터 부족"
    if x >= 0:
        return "주도" if a >= 0 else "둔화"
    return "회복" if a >= 0 else "회피"
