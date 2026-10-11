"""코인 선물 봉(1단계): 신호가 미래를 안 쓰는지, 위험 한도(레버리지·손실·잔고 하한)가 지켜지는지 확인한다."""
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from perp_bot import backtest, paper, strategy
from perp_bot.config import HARD_MAX_LEVERAGE, HARD_STOP_EQUITY, BotConfig

IDX = pd.date_range("2024-01-01", periods=1500, freq="4h", tz="UTC")


def _candles(drift=0.0, vol=0.01, seed=0, shock_at=None, shock=0.0):
    rng = np.random.default_rng(seed)
    r = rng.normal(drift, vol, len(IDX))
    if shock_at is not None:
        r[shock_at] += shock
    close = 100 * np.exp(np.cumsum(r))
    open_ = np.r_[close[0], close[:-1]]
    hi = np.maximum(open_, close) * (1 + abs(rng.normal(0, vol / 3, len(IDX))))
    lo = np.minimum(open_, close) * (1 - abs(rng.normal(0, vol / 3, len(IDX))))
    return pd.DataFrame({"open": open_, "high": hi, "low": lo, "close": close, "volume": 1.0}, index=IDX)


def test_config_cannot_be_loosened(monkeypatch):
    monkeypatch.setenv("PERP_MAX_LEVERAGE", "50")
    monkeypatch.setenv("PERP_RISK_PER_TRADE", "0.2")
    monkeypatch.setenv("PERP_STOP_EQUITY", "100")
    c = BotConfig.load()
    assert c.max_leverage == HARD_MAX_LEVERAGE and c.risk_per_trade == 0.02 and c.stop_equity == HARD_STOP_EQUITY


def test_indicators_use_only_past():
    c = BotConfig()
    df = _candles(0.001)
    base = strategy.indicators(df, c)["x"]
    bumped = df.copy()
    bumped.iloc[1001:] *= 2
    after = strategy.indicators(bumped, c)["x"]
    assert after.iloc[1000] == pytest.approx(base.iloc[1000])


def test_sizing_respects_risk_and_leverage():
    c = BotConfig()
    s = strategy.size(1, price=100, atr=2, equity=600, open_notional=0, c=c)
    # 손절 거리 5% → 잔고 2%(12$) 손실이 되도록 240$
    assert s.notional == pytest.approx(240) and s.stop == pytest.approx(95)
    tight = strategy.size(1, price=100, atr=0.01, equity=600, open_notional=0, c=c)
    assert tight.notional <= 600 * c.max_coin_leverage + 1e-6
    full = strategy.size(1, price=100, atr=0.01, equity=600, open_notional=600 * 10, c=c)
    assert full.notional == 0  # 전체 10배를 이미 쓰고 있으면 더 못 늘린다


def test_stop_comes_before_liquidation():
    c = replace(BotConfig(), risk_per_trade=0.02, max_coin_leverage=10)
    s = strategy.size(1, price=100, atr=4, equity=600, open_notional=0, c=c)  # 손절 10%
    assert s.leverage == 0 or 0.10 < 0.5 / s.leverage


def test_trend_is_traded_and_kill_switch_stops_everything():
    c = BotConfig()
    up = {"BTC": _candles(0.002, seed=1), "ETH": _candles(0.0, seed=2), "SOL": _candles(-0.001, seed=3)}
    sim = backtest.run(up, {}, c)
    assert sim.trades and any(t["coin"] == "BTC" and t["side"] == "롱" for t in sim.trades)
    assert all(t["lev"] <= c.max_coin_leverage + 1e-6 for t in sim.trades)

    # 큰 손실이 나면 잔고 하한에서 멈추고 그 뒤로는 거래하지 않는다
    c2 = replace(c, stop_equity=599.0)
    sim2 = backtest.run(up, {}, c2)
    assert sim2.killed_at is not None and not sim2.pos
    killed = pd.Timestamp(sim2.killed_at)
    assert all(pd.Timestamp(t["entry_time"]) <= killed for t in sim2.trades)


def test_paper_tick_resumes_from_saved_state(tmp_path):
    c = BotConfig()
    data = {k: _candles(0.002, seed=i) for i, k in enumerate(c.coins)}
    path = tmp_path / "state.json"
    part = {k: v.iloc[:1200] for k, v in data.items()}
    sim, _ = paper.tick(path, c, part, {})
    assert sim.last_bar == str(IDX[1199])  # 처음엔 마지막 봉 하나만 처리
    sim, msgs = paper.tick(path, c, data, {})
    assert sim.last_bar == str(IDX[-1]) and path.exists()
    again, msgs2 = paper.tick(path, c, data, {})
    assert msgs2 == []  # 같은 봉을 두 번 처리하지 않는다


def _daily(rows):
    idx = pd.date_range("2022-01-01", periods=len(rows), freq="D")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)


def test_bracket_stop_first_when_both_hit_same_day():
    from perp_bot import research
    flat = [(100, 101, 99, 100)] * 20                 # ATR(14) = 2
    df = _daily(flat + [(100, 120, 80, 100)] + [(100, 101, 99, 100)] * 5)
    ent = pd.Series(False, index=df.index)
    ent.iloc[19] = True                               # 다음 날(20번째) 시가 100에 진입
    tr = research.run_bracket(df, ent, sl_atr=1.0, rr=3)
    assert len(tr) == 1 and tr[0].reason == "손절" and tr[0].r < -1


def test_bracket_target_pays_rr_minus_costs_and_no_lookahead():
    from perp_bot import research
    flat = [(100, 101, 99, 100)] * 20
    df = _daily(flat + [(100, 101, 99.5, 100)] + [(100, 107, 99.5, 106)] + [(106, 107, 105, 106)] * 3)
    ent = pd.Series(False, index=df.index)
    ent.iloc[19] = True
    tr = research.run_bracket(df, ent, sl_atr=1.0, rr=3)
    t = tr[0]
    assert t.reason == "익절" and t.entry_date == df.index[20]   # 신호 다음 날 진입
    assert 2.7 < t.r < 3.0                             # +3R에서 비용·펀딩만 빠짐
    # 신호 날 이후의 가격을 바꿔도 진입·손절폭은 그대로(미래 정보 안 씀)
    df2 = df.copy()
    df2.iloc[21:, :] = 50
    t2 = research.run_bracket(df2, ent, sl_atr=1.0, rr=3)[0]
    assert t2.entry_date == t.entry_date and t2.reason.startswith("손절")


def test_research_positions_and_split():
    from perp_bot import research
    rng = np.random.default_rng(0)
    idx = pd.date_range("2018-01-01", "2023-12-31", freq="D")
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.001, 0.03, len(idx)))), index=idx)
    df = pd.DataFrame({"open": close.shift(1).fillna(100), "high": close * 1.01, "low": close * 0.99, "close": close})
    r = research.run_positions(df, research.pos_hold(df))
    assert abs(r.iloc[5] - (close.iloc[5] / close.iloc[4] - 1 - research.FUND_LONG / 365)) < 1e-12
    isr, oos = research.split(r)
    assert isr["CAGR"] != oos["CAGR"] and "허용 레버리지(−33%)" in oos
    rows = research.run_all({"BTC": df, "ETH": df, "SOL": df})
    assert len(rows) == 3 * len(research.strategies(df)) + 1
    assert "IS" in research.report(rows)
