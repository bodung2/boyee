"""자산군 모멘텀 대시보드: 신호가 미래 데이터를 안 쓰는지, 편입 규칙·비중·백테스트 계산이 맞는지 확인한다."""
import numpy as np
import pandas as pd
import pytest

from market_dashboard import backtest, data, html, report, signals, universe
from market_dashboard.signals import Params

IDX = pd.bdate_range("2010-01-01", "2016-12-30")


def _prices(seed=0, drifts=None):
    rng = np.random.default_rng(seed)
    keys = [a.key for a in universe.ASSETS]
    r = rng.normal(0, 0.008, (len(IDX), len(keys)))
    for k, d in (drifts or {}).items():
        r[:, keys.index(k)] += d
    r[:, keys.index("CASH")] = 0.0001
    return pd.DataFrame(100 * np.exp(np.cumsum(r, axis=0)), index=IDX, columns=keys)


def test_signal_uses_only_past_data():
    px = _prices()
    p = Params()
    base = signals.compute(px.drop(columns="CASH"), px["CASH"], p)["x"]
    t = IDX[1200]
    bumped = px.copy()
    bumped.loc[IDX[1201]:, "SPY"] *= 3  # 미래를 바꿔도 t 시점 신호는 그대로여야 한다
    after = signals.compute(bumped.drop(columns="CASH"), bumped["CASH"], p)["x"]
    assert after.loc[t, "SPY"] == pytest.approx(base.loc[t, "SPY"])


def test_strong_uptrend_is_eligible_and_downtrend_is_not():
    px = _prices(drifts={"GLD": 0.002, "USO": -0.002})
    sig = signals.compute(px.drop(columns="CASH"), px["CASH"], Params())
    t = IDX[-1]
    assert sig["eligible"].loc[t, "GLD"]
    assert sig["x"].loc[t, "GLD"] > 0 > sig["x"].loc[t, "USO"]
    assert not sig["eligible"].loc[t, "USO"]
    assert signals.quadrant(1.0, 0.1) == "주도" and signals.quadrant(-1.0, 0.1) == "회복"


def test_select_skips_highly_correlated_and_caps_weights():
    px = _prices(drifts={"SPY": 0.002, "GLD": 0.0015})
    px["QQQ"] = px["SPY"] * (1 + 0.0001 * np.arange(len(IDX)) / len(IDX))  # SPY와 거의 같음
    p = Params()
    risky = universe.risky_keys()
    sig = signals.compute(px[risky], px["CASH"], p)
    weekly = signals.weekly_returns(px[risky])
    picks, why = backtest.select(IDX[-1], sig, weekly, set(), p, risky)
    keys = [k.key for k in picks]
    assert not ({"SPY", "QQQ"} <= set(keys))
    assert any("상관 겹침" in v for v in why.values())
    assert all(0 < k.weight <= p.max_weight + 1e-9 for k in picks)
    assert sum(k.weight for k in picks) <= 1 + 1e-9


def test_no_trend_means_all_cash():
    px = _prices(drifts={k: -0.004 for k in universe.risky_keys()})
    res = backtest.run(px, px, Params())
    last = res["weights"][max(res["weights"])]
    assert last.get("CASH", 0) == pytest.approx(1.0)


def test_simulate_trades_next_day_and_charges_cost():
    idx = pd.bdate_range("2020-01-01", periods=5)
    rets = pd.DataFrame({"A": [0, 0.10, 0.10, 0, 0], "CASH": 0.0}, index=idx)
    res = backtest.simulate(rets, {idx[1]: {"A": 1.0}}, cost=0.01, start_at=idx[0])
    nav = res["nav"]
    # idx[1] 종가에 체결 → idx[1]의 +10%는 못 먹고 비용 1%, idx[2]의 +10%는 먹는다
    assert nav.iloc[1] == pytest.approx(0.99)
    assert nav.iloc[2] == pytest.approx(0.99 * 1.10)


def test_metrics_drawdown():
    nav = pd.Series([1.0, 1.2, 0.9, 1.3], index=pd.bdate_range("2020-01-01", periods=4))
    m = backtest.metrics(nav, pd.Series(1.0, index=nav.index))
    assert m["최대낙폭"] == pytest.approx(0.9 / 1.2 - 1)


def test_build_and_render_end_to_end():
    px = _prices(drifts={"SPY": 0.0008, "TLT": 0.0004})
    close = pd.DataFrame({a.ticker: px[a.key] for a in universe.ASSETS})
    close["^IRX"] = 2.0  # 현금은 연 수익률(%)로 들어온다
    close[universe.FX_TICKER] = 1200.0
    d = report.build(close, pd.DataFrame(), Params())
    assert d["assets"] and d["backtest"]["table"][0]["name"] == "모멘텀 규칙"
    assert {r["name"] for r in d["backtest"]["table"]} >= {"S&P500 보유", "60/40", "올웨더"}
    page = html.render(d)
    assert page.startswith("<!doctype html>") and "__DATA__" not in page


def test_cash_yield_becomes_index_on_us_trading_days():
    idx = pd.date_range("2020-01-01", periods=10, freq="D")  # 주말 포함(비트코인만 거래한 날)
    close = pd.DataFrame({a.ticker: 100.0 for a in universe.ASSETS}, index=idx)
    close.loc[idx.dayofweek >= 5, "SPY"] = np.nan
    close["^IRX"] = 2.52
    close[universe.FX_TICKER] = 1000.0
    usd = data.to_base(close, "USD")
    assert len(usd) == 8 and (usd.index.dayofweek < 5).all()
    assert usd["CASH"].iloc[1] / usd["CASH"].iloc[0] == pytest.approx(1 + 0.0252 / 252)
    krw = data.to_base(close, "KRW")
    assert krw["SPY"].iloc[0] == pytest.approx(100_000) and krw["KTB10"].iloc[0] == pytest.approx(100)


def test_cli_writes_index_for_pages(tmp_path, monkeypatch):
    from market_dashboard import __main__ as cli

    px = _prices(drifts={"SPY": 0.0008})
    close = pd.DataFrame({a.ticker: px[a.key] for a in universe.ASSETS})
    close["^IRX"] = 2.0
    close[universe.FX_TICKER] = 1200.0
    cache = tmp_path / "cache"
    cache.mkdir()
    close.to_csv(cache / "prices.csv")
    monkeypatch.setattr(cli, "CACHE", cache)
    monkeypatch.setenv("DASHBOARD_URL", "https://example.test/")
    sent = []
    monkeypatch.setattr(cli, "send_text", lambda token, chat, text: sent.append(text))
    assert cli.main(["run", "--offline", "--out", str(tmp_path / "site"), "--notify"]) == 0
    page = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert "갱신" in page and sent and sent[0].endswith("https://example.test/")


def test_every_asset_has_buyable_products():
    from market_dashboard import products

    cat = products.for_dashboard()
    for key in universe.risky_keys():
        e = cat["by_asset"][key]
        assert e["us"] or e["kr"], key
        for it in e["kr"]:
            assert len(it["code"]) == 6 and it["code"].isdigit(), it
            assert it["url"].endswith(it["code"])
        for it in e["us"]:
            assert it["code"].isupper() and it["url"].endswith(it["code"])
    assert cat["cash"]["kr"] and cat["cash"]["us"]
