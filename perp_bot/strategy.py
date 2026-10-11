"""신호와 포지션 크기. 모든 값은 그 봉의 종가까지로만 계산한다(미래 데이터 없음)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import BotConfig


def indicators(df: pd.DataFrame, c: BotConfig) -> pd.DataFrame:
    close = df["close"]
    lr = np.log(close).diff()
    vol = lr.rolling(c.vol_window, min_periods=int(c.vol_window * 0.8)).std()
    parts = [(np.log(close) - np.log(close.shift(h))) / (vol * np.sqrt(h)) for h in c.horizons]
    x = sum(parts) / len(parts)
    prev_close = close.shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev_close).abs(), (df["low"] - prev_close).abs()], axis=1).max(axis=1)
    out = pd.DataFrame({
        "close": close,
        "x": x,
        "ema": close.ewm(span=c.ema_window, adjust=False, min_periods=c.ema_window).mean(),
        "atr": tr.rolling(c.atr_window, min_periods=c.atr_window).mean(),
    })
    return out


def entry_side(row: pd.Series, c: BotConfig) -> int:
    """+1 롱, −1 숏, 0 진입 없음."""
    if any(pd.isna(row[k]) for k in ("x", "ema", "atr")):
        return 0
    if row["x"] > c.entry_x and row["close"] > row["ema"]:
        return 1
    if c.allow_short and row["x"] < -c.entry_x and row["close"] < row["ema"]:
        return -1
    return 0


def should_exit(side: int, row: pd.Series, c: BotConfig) -> bool:
    """추세가 0을 지나 반대로 돌면 정리(손절과 별개)."""
    if pd.isna(row["x"]):
        return False
    return (side > 0 and row["x"] < c.exit_x) or (side < 0 and row["x"] > -c.exit_x)


@dataclass
class Sizing:
    notional: float     # 포지션 크기(달러)
    stop: float         # 처음 손절 가격
    leverage: float     # 이 포지션 / 잔고
    reason: str = ""


def size(side: int, price: float, atr: float, equity: float, open_notional: float, c: BotConfig) -> Sizing:
    """손절에 걸리면 잔고의 risk_per_trade만 잃도록 크기를 정하고, 레버리지 상한으로 자른다."""
    stop_dist = c.stop_atr * atr
    stop = price - side * stop_dist
    pct = stop_dist / price
    if pct <= 0 or equity <= 0:
        return Sizing(0, stop, 0, "손절 거리 계산 불가")
    notional = equity * c.risk_per_trade / pct
    reason = ""
    cap_coin = equity * c.max_coin_leverage
    cap_total = max(equity * c.max_leverage - open_notional, 0)
    if notional > cap_coin:
        notional, reason = cap_coin, f"코인당 레버리지 {c.max_coin_leverage:g}배로 제한"
    if notional > cap_total:
        notional, reason = cap_total, f"전체 레버리지 {c.max_leverage:g}배로 제한"
    lev = notional / equity
    # 손절이 청산보다 먼저 와야 한다(격리 마진 청산 거리 ≈ 1/레버리지의 절반 이상 여유)
    if lev > 0 and pct >= 0.5 / lev:
        notional = equity * 0.5 / pct * 0.9
        lev, reason = notional / equity, "손절이 청산가보다 먼저 오도록 축소"
    if notional < 10:  # Hyperliquid 최소 주문 10달러
        return Sizing(0, stop, 0, "최소 주문 금액(10달러) 미만")
    return Sizing(notional, stop, lev, reason)
