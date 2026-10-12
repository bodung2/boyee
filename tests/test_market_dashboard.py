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
            assert len(it["code"]) == 6 and it["code"].isalnum(), it
            assert it["url"].endswith(it["code"])
        for it in e["us"]:
            assert it["code"].isupper() and it["url"].endswith(it["code"])
        # 신호 기준 상품은 자산마다 최대 하나
        assert sum(it["signal"] for it in e["us"] + e["kr"]) <= 1
    assert cat["cash"]["kr"] and cat["cash"]["us"]
    # 거래대금을 모르면 아무것도 추천하지 않는다
    assert not any(it["best"] for e in cat["by_asset"].values() for it in e["us"] + e["kr"])


def test_rank_prefers_cheapest_among_liquid():
    from market_dashboard.products import K, U, rank

    items = [U("AAA", "a", fee=0.20, signal=True), U("BBB", "b", fee=0.03), U("CCC", "c", fee=0.01)]
    live = {"AAA": {"turnover": 5e9}, "BBB": {"turnover": 2e8, "fee": 0.04}, "CCC": {"turnover": 1e6}}
    rows = rank(items, live)
    assert [r["code"] for r in rows] == ["BBB", "AAA", "CCC"]  # CCC는 싸지만 거래가 적어 맨 뒤
    assert rows[0]["best"] and rows[0]["fee"] == 0.04 and rows[0]["fee_src"] == "자동"
    assert not rows[2]["liquid"]

    kr = rank([K("111111", "x"), K("222222", "y", fee=0.5)], {"111111.KS": {"turnover": 5e10}, "222222.KS": {"turnover": 5e10}})
    assert kr[0]["code"] == "222222"  # 보수를 아는 상품이 먼저

    # 보수가 사실상 같으면(0.01%p 이내) 거래대금이 많은 쪽
    tie = rank([K("333333", "a", fee=0.004), K("444444", "b", fee=0.0068)],
               {"333333.KS": {"turnover": 2e9}, "444444.KS": {"turnover": 1e10}})
    assert tie[0]["code"] == "444444" and tie[0]["best"]


def test_analysis_tables_and_text():
    from market_dashboard import analysis

    px = _prices(drifts={"GLD": 0.001, "USO": -0.001})
    a = analysis.run(px, px, Params())
    quads = {r["bucket"] for r in a["by_quadrant"]}
    assert quads <= {"주도", "둔화", "회복", "회피"} and quads
    gld = next(r for r in a["profiles"] if r["key"] == "GLD")
    assert gld["share_pos"] > 0.5 and gld["mean_pos"] > 0
    # 미래 수익은 관찰 시점 이후 값만 쓴다: 마지막 63거래일은 3개월 수익이 없다
    pan = analysis.panel(px, Params())
    last = pan[pan["date"] > px.index[-63]]
    assert last["f_3개월"].isna().all()
    text = analysis.as_text(a, {"GLD": "금"})
    assert "사분면별" in text and "금" in text


def test_entry_needs_strong_trend_but_holdings_stay_until_zero():
    idx = pd.bdate_range("2020-01-01", periods=3)
    keys = ["A", "B"]
    t = idx[-1]
    frame = lambda a, b: pd.DataFrame({"A": [a] * 3, "B": [b] * 3}, index=idx)
    p = Params()
    x = frame(0.3, 0.3)  # 둘 다 0 < x < 0.5
    sig = {"x": x, "eligible": x > p.min_x, "holdable": x > p.hold_x, "wvol": frame(0.01, 0.01)}
    weekly = pd.DataFrame(np.random.default_rng(0).normal(0, 0.01, (60, 2)), columns=keys,
                          index=pd.date_range(end=t, periods=60, freq="W-FRI"))
    picks, _ = backtest.select(t, sig, weekly, {"A"}, p, keys)
    assert [pk.key for pk in picks] == ["A"]  # 보유 중인 A만 유지, B는 새로 편입하지 않음


def _fake_country(c, days=900, seed=0, drop=()):
    from market_dashboard import sectors
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2021-01-01", periods=days)
    cols = [t for t in sectors.tickers(c) if t not in drop]
    close = {}
    for i, t in enumerate(cols):
        if t == c.cash and c.cash_is_rate:
            close[t] = np.full(days, 4.0)
            continue
        close[t] = 100 * np.exp(np.cumsum(rng.normal(0.0004 * ((i % 5) - 2), 0.015, days)))
    close = pd.DataFrame(close, index=idx)
    vol = pd.DataFrame(1e7, index=idx, columns=cols)
    return close, vol


def test_sector_dashboard_builds_and_renders():
    from market_dashboard import sector_html, sectors
    from market_dashboard.sector_universe import KR, US
    data = {"US": _fake_country(US), "KR": _fake_country(KR, seed=1, drop=("266410.KS",))}
    d = sectors.build(data)
    us, kr = d["countries"]
    assert len(us["sectors"]) == len(US.sectors) and len(kr["sectors"]) == len(KR.sectors) - 1
    assert "266410.KS" in kr["missing"]
    s = us["sectors"][0]
    assert len(s["hist"]) == len(us["frames"]) and s["stocks"]
    assert sum(x["weight"] for x in us["sectors"]) <= 1.0 + 1e-9
    assert all(x["weight"] <= sectors.SECTOR_RULE["max_weight"] + 1e-9 for x in us["sectors"])
    assert us["backtest"]["table"][0]["name"] == "섹터 순환 규칙"
    scores = [r["score"] for r in s["stocks"] if r.get("score") is not None]
    assert scores and all(0 < v <= 1 for v in scores)
    page = sector_html.render(d)
    assert "주식 섹터 지도" in page and "</script>" in page
    assert "섹터" in sectors.summary(d)


def test_sector_stock_status_uses_liquidity_floor():
    from market_dashboard import sectors
    from market_dashboard.sector_universe import US
    close, vol = _fake_country(US, seed=2)
    vol.loc[:, "AAPL"] = 1.0   # 거래대금 거의 0
    px = sectors.panel(US, close)
    rows = sectors.stock_table(US, close, vol, px["CASH"], sectors.Params())["XLK"]
    aapl = next(r for r in rows if r["ticker"] == "AAPL")
    assert aapl["status"] == "거래대금 부족"
