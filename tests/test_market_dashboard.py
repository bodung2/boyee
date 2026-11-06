"""자산군 모멘텀 대시보드: 신호가 미래 데이터를 안 쓰는지, 편입 규칙·비중·백테스트 계산이 맞는지 확인한다."""
import json
import pathlib
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


def _kr_snaps(months=60, n=120, seed=0):
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2014-01-31", periods=months, freq="ME")
    codes = [f"{i:05d}0" for i in range(n)]
    price = pd.Series(10000.0, index=codes)
    pbr = pd.Series(rng.uniform(0.3, 3, n), index=codes)
    snaps = {}
    for d in dates:
        # 저PBR 종목이 조금 더 오르게(기준이 실제로 잡아내는지 확인)
        price = price * (1 + rng.normal(0.01, 0.06, n) + 0.01 * (pbr < 1))
        snaps[d] = pd.DataFrame({"종가": price, "시가총액": price * 1e6, "거래대금": 5e9, "상장주식수": 1e6,
                                 "PER": rng.uniform(5, 30, n), "PBR": pbr, "DIV": 2.0, "외국인순매수": rng.normal(0, 1e8, n)})
    return snaps


def test_kr_factor_study_runs_and_finds_planted_value_effect():
    from market_dashboard import kr_factors
    snaps = _kr_snaps()
    res = kr_factors.run(snaps)
    rows = {r["name"]: r for r in res["rows"]}
    assert set(rows) == set(kr_factors.FACTORS)
    v = rows["저PBR(가치)"]
    assert v["IS"]["Q1"]["CAGR"] > v["IS"]["Q5"]["CAGR"]
    assert "종목 선정" in kr_factors.report(res)


def test_kr_factor_split_adjusted_returns():
    from market_dashboard import kr_factors
    snaps = _kr_snaps(months=3, n=60)
    d1, d2 = sorted(snaps)[:2]
    snaps[d2].loc["000000", ["종가", "상장주식수"]] = [snaps[d1].loc["000000", "종가"] / 50, 50e6]  # 50:1 액면분할
    r = kr_factors.monthly_returns(kr_factors.panel(snaps))
    assert abs(r.loc[d1, "000000"] - 2.0 / 100 / 12) < 1e-9   # 가격 변화 없음 + 배당만


def test_kr_factor_combo_and_dividend_anatomy():
    from market_dashboard import kr_combo, kr_factors
    snaps = _kr_snaps(months=60, n=150)
    p = kr_factors.panel(snaps)
    ret, uni, sc = kr_factors.monthly_returns(p), kr_factors.universe(p), kr_factors.scores(p)
    market = ret.where(uni).mean(axis=1).iloc[:-1]
    res = kr_combo.run_combos(p, ret, uni, sc, market, None)
    assert len(res["rows"]) == 2 * (len(kr_combo.BASE) + len(kr_combo.COMBOS) + 3)
    anat = kr_combo.dividend_anatomy(p, ret, uni, sc, market)
    assert set(anat) == {"split", "profile", "capture", "calendar", "regression"}
    text = kr_combo.report(res, anat)
    assert "고배당은 왜" in text and "2017년까지 성적으로 골랐다면" in text
    # 배당 제외 수익은 배당 포함보다 작다(배당수익률 2%/12)
    pr = kr_factors.monthly_returns(p, include_div=False)
    assert (ret - pr).stack().dropna().round(6).eq(round(0.02 / 12, 6)).mean() > 0.9


def _kr_stock_data(n=40, days=800, seed=3):
    from market_dashboard import kr_stocks
    rng = np.random.default_rng(seed)
    codes = [f"{i:05d}0" for i in range(1, n + 1)]
    uni = pd.DataFrame({
        "시가총액": np.linspace(5e13, 5e11, n), "DIV": rng.uniform(0, 7, n), "PBR": rng.uniform(0.3, 3, n),
        "PER": rng.uniform(4, 30, n), "시장": ["KOSDAQ" if i % 4 == 0 else "KOSPI" for i in range(n)],
        "종목명": [f"종목{i}" for i in range(n)], "기준일": "2024-01-02"}, index=codes)
    idx = pd.bdate_range("2021-01-01", periods=days)
    cols = codes + [kr_stocks.CASH, kr_stocks.BENCH]
    close = pd.DataFrame({c: 100 * np.exp(np.cumsum(rng.normal(0.0003 * ((i % 5) - 2), 0.02, days)))
                          for i, c in enumerate(cols)}, index=idx)
    close[kr_stocks.CASH] = 100 * (1 + 0.03 / 252) ** np.arange(days)
    vol = pd.DataFrame(rng.uniform(1e8, 2e8, (days, len(cols))), index=idx, columns=cols)
    vol.iloc[-20:, 1] *= 6          # 두 번째 종목: 최근 거래 급증
    vol.loc[:, codes[2]] = 10.0     # 세 번째 종목: 거래대금 부족 → 제외
    return uni, close, vol


def test_kr_stock_map_builds_and_renders():
    from market_dashboard import kr_html, kr_stocks
    uni, close, vol = _kr_stock_data()
    d = kr_stocks.build(uni, close, vol)
    stocks = [s for s in d["stocks"] if not s["bench"]]
    codes = {s["code"] for s in stocks}
    assert uni.index[2] not in codes and len(stocks) == len(uni) - 1
    assert any(s["bench"] for s in d["stocks"])
    assert sum("고배당30" in s["tags"] for s in stocks) == kr_stocks.DIV_N
    top_div = uni.drop(uni.index[2])["DIV"].idxmax()
    assert next(s for s in stocks if s["code"] == top_div)["div_rank"] == 1
    spike = next(s for s in stocks if s["code"] == uni.index[1])
    assert spike["vchg"] > 1.5
    assert all(len(s["hist"]) == len(d["frames"]) for s in d["stocks"])
    assert sum(d["counts"].values()) <= len(stocks)
    page = kr_html.render(d)
    assert "한국 종목 지도" in page and 'href="kr.html" class="on"' in page
    assert "고배당 30" in kr_stocks.summary(d)
    assert "한국 종목" in kr_html.render_error("x")


def _three_screens():
    from market_dashboard import kr_stocks, sectors
    from market_dashboard.sector_universe import US
    px = _prices(drifts={"SPY": 0.0008, "TLT": 0.0004})
    close = pd.DataFrame({a.ticker: px[a.key] for a in universe.ASSETS})
    close["^IRX"] = 2.0
    close[universe.FX_TICKER] = 1200.0
    dash = json.loads(json.dumps(report.build(close, pd.DataFrame(), Params())))
    sec = json.loads(json.dumps(sectors.build({"US": _fake_country(US)})))
    kr = json.loads(json.dumps(kr_stocks.build(*_kr_stock_data(n=60))))
    return dash, sec, kr


def test_brief_summarises_three_screens_and_compares_with_yesterday():
    from datetime import datetime
    from market_dashboard import brief
    dash, sec, kr = _three_screens()
    mk = [{"ticker": "^KS11", "name": "코스피", "date": "2026-11-02", "close": 2500.0, "d1": 0.012, "w1": -0.02, "unit": "%"}]
    y = brief.build(dash, sec, kr, mk, now=datetime(2026, 11, 2, 9, tzinfo=brief.KST))
    assert y["kr"]["n"] == 59 and len(y["kr"]["div30"]) == 30 and y["us"]["rank"] and y["assets"] is not None
    assert y["changes"] == {}
    # 배분(편입·비중)은 요약에 넣지 않는다
    assert "weight" not in json.dumps(y) and "picks" not in json.dumps(y)
    prev = json.loads(json.dumps(y))
    prev["kr"]["above_sma"] = y["kr"]["above_sma"] - 0.05
    prev["kr"]["div30"] = prev["kr"]["div30"][1:] + [{"code": "999990", "name": "빠진종목", "div": 9.0}]
    prev["us"]["rank"][0]["quadrant"] = "회피" if y["us"]["rank"][0]["quadrant"] != "회피" else "주도"
    t = brief.build(dash, sec, kr, mk, prev=prev, now=datetime(2026, 11, 3, 9, tzinfo=brief.KST))
    c = t["changes"]
    assert c["since"] == "2026-11-02" and c["kr_above_sma_pp"] == 5.0
    assert c["div30_in"] == [y["kr"]["div30"][0]["name"]] and c["div30_out"] == ["빠진종목"]
    assert c["us_moves"]
    assert any("200일선 위" in h and "(+5%p)" in h for h in t["headline"])
    assert any(h.startswith("코스피 +1.2%") for h in t["headline"])
    assert brief.build(None, None, None)["headline"] == []      # 아무것도 못 받은 날에도 멈추지 않음


def test_brief_matches_sihwang_posts_by_title_date():
    from market_dashboard import brief
    items = [
        {"title": "11월 3일 시황 | 200일선 위 21%", "url": "https://blog.naver.com/b/1", "pub_date": "Tue, 03 Nov 2026 14:02:00 +0900"},
        {"title": "12월 31일 시황 | 한 해 정리", "url": "https://blog.naver.com/b/2", "pub_date": "Fri, 01 Jan 2027 09:00:00 +0900"},
        {"title": "연봉 4천, 상위 몇 %일까?", "url": "https://blog.naver.com/b/3", "pub_date": "Tue, 03 Nov 2026 07:00:00 +0900"},
    ]
    got = brief.match_posts(items, {"2026-11-02": {"title": "old", "url": "u"}})
    assert set(got) == {"2026-11-02", "2026-11-03", "2026-12-31"}
    assert got["2026-11-03"]["url"].endswith("/1")


def test_brief_cli_archives_and_renders_history(tmp_path, monkeypatch):
    import market_dashboard.__main__ as cli
    from market_dashboard import brief, kr_html, sector_html
    dash, sec, kr = _three_screens()
    monkeypatch.setattr(brief, "MANUAL_POSTS", tmp_path / "none.json")
    site = tmp_path / "site"
    site.mkdir()
    for name, d in (("dashboard.json", dash), ("sectors.json", sec), ("kr.json", kr)):
        (site / name).write_text(json.dumps(d), encoding="utf-8")
    monkeypatch.setattr(cli, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(brief, "fetch_markets", lambda: [])
    monkeypatch.setattr(brief, "fetch_risk", lambda: None)
    monkeypatch.delenv("NAVER_BLOG_ID_INVEST", raising=False)
    monkeypatch.delenv("NAVER_BLOG_ID_MARKET", raising=False)
    (tmp_path / "cache" / "briefs").mkdir(parents=True)
    (tmp_path / "cache" / "briefs" / "posts.json").write_text(json.dumps(
        {"2000-01-03": {"title": "1월 3일 시황 | 옛날", "url": "https://blog.naver.com/x/9"}}), encoding="utf-8")
    old = brief.build(dash, sec, kr)
    old["date"] = "2000-01-03"
    brief.save_archive(tmp_path / "cache" / "briefs", old)
    assert cli.main(["brief", "--out", str(site)]) == 0
    b = json.loads((site / "brief.json").read_text(encoding="utf-8"))
    assert b["changes"]["since"] == "2000-01-03" and b["latest_post"]["url"].endswith("/9")
    page = (site / "history.html").read_text(encoding="utf-8")
    assert "시황 기록" in page and "1월 3일 시황 | 옛날" in page and b["date"] in page
    assert len(list((tmp_path / "cache" / "briefs").glob("????-??-??.json"))) == 2
    # 모든 화면 위쪽 탭에 '시황 기록'과 요약 줄 자리가 있다
    for html_page in (kr_html.render(kr), sector_html.render(sec)):
        assert 'href="history.html"' in html_page and 'id="briefStrip"' in html_page


def test_kr_unfinished_daily_bar_is_dropped_during_market_hours():
    from datetime import datetime
    from market_dashboard import kr_stocks
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0]}, index=pd.to_datetime(["2026-10-30", "2026-10-31", "2026-11-02"]))
    at = lambda h, m: datetime(2026, 11, 2, h, m, tzinfo=kr_stocks.KST)  # noqa: E731
    assert len(kr_stocks.drop_unfinished(df, at(10, 0))) == 2       # 장중: 오늘 값 뺌
    assert len(kr_stocks.drop_unfinished(df, at(16, 0))) == 3       # 마감 뒤: 그대로
    assert len(kr_stocks.drop_unfinished(df.iloc[:2], at(10, 0))) == 2   # 오늘 값이 없으면 그대로


def test_indicator_study_finds_planted_risk_signal():
    """합성 시장: 금리차가 역전된 달 다음 달에는 크게 빠진다 → '하락 위험 신호'로 골라야 한다. 아무 정보 없는 지표는 빼야 한다."""
    from market_dashboard import indicators
    rng = np.random.default_rng(5)
    idx = pd.bdate_range("1995-01-02", "2024-12-31")
    months = idx.to_period("M")
    crash_m = pd.Index(months.unique())[rng.random(len(months.unique())) < 0.08]   # 드물게(8%) 오는 급락 달
    crash = months.isin(crash_m)
    ret = rng.normal(np.where(crash, -0.008, 0.0006), np.where(crash, 0.03, 0.008))
    spx = pd.Series(100 * np.exp(np.cumsum(ret)), index=idx)
    px = pd.DataFrame({"^GSPC": spx, "^VIX": 15 + rng.normal(0, 3, len(idx)), "^KS11": spx * 0.5, "KRW=X": 1200.0}, index=idx)
    for t in indicators.SECTORS9:
        px[t] = spx
    fidx = pd.date_range("1995-01-01", "2024-12-01", freq="MS")
    # 급락 달 바로 전 달에 금리차 역전(미래를 아는 합성 신호)
    inverted = pd.Index(fidx.to_period("M")).map(lambda p: (p + 1) in set(crash_m))
    fred = pd.DataFrame({"T10Y3M": np.where(inverted, -0.5, 1.0), "BAA10Y": rng.uniform(1, 4, len(fidx)),
                         "UNRATE": 5.0}, index=fidx)
    res = indicators.run(px, fred)
    curve = next(r for r in res if r["spec"].key == "curve")
    v = indicators.verdict(curve)[0]
    assert v.startswith("추적 추천") and "하락" in v
    vix = next(r for r in res if r["spec"].key == "vix")       # 아무 정보 없는 VIX(잡음)
    assert not indicators.verdict(vix)[0].startswith("추적 추천")
    text = indicators.report(res)
    assert "장단기 금리차" in text and "== 추적 추천 ==" in text
    # 미래 정보 없음: 백분위는 그때까지 값만으로
    r = indicators.expanding_rank(pd.Series(np.arange(40, dtype=float)))
    assert np.isnan(r.iloc[34]) and r.iloc[39] == 1.0


def test_one_missing_ticker_is_refetched_or_filled_from_cache(tmp_path):
    idx = pd.bdate_range("2024-01-01", periods=5)
    close = pd.DataFrame({"SPY": [1.0, 2, 3, 4, 5], "GLD": np.nan}, index=idx)
    old = pd.DataFrame({"SPY": 1.0, "GLD": [9.0, 9, 9, 9, 9], "TLT": 7.0}, index=idx)
    cache = tmp_path / "prices.csv"
    old.to_csv(cache)
    # 다시 받기가 되면 그 값
    got = data.fill_missing(close, ["SPY", "GLD"], cache, lambda t: pd.Series(2.0, index=idx))
    assert (got["GLD"] == 2.0).all()
    # 다시 받기도 실패하면 저장본 값, 저장본에도 없으면 그대로 비워 둔다
    def fail(t):
        raise RuntimeError("database is locked")
    got = data.fill_missing(close, ["SPY", "GLD", "TLT", "QQQ"], cache, fail)
    assert (got["GLD"] == 9.0).all() and (got["TLT"] == 7.0).all() and "QQQ" not in got


def test_kr_snapshot_load_retries_failed_months(tmp_path, monkeypatch):
    from market_dashboard import kr_factors
    months = list(pd.period_range("2024-01", "2024-03", freq="M"))
    monkeypatch.setattr(kr_factors.pd.Timestamp, "today", classmethod(lambda cls: pd.Timestamp("2024-04-15")))
    monkeypatch.setattr(kr_factors, "trading_month_ends", lambda start: {m: m.end_time.normalize() - pd.Timedelta(days=1) for m in months})
    calls = {}

    def fake_snapshot(day, cache_dir):
        calls[day] = calls.get(day, 0) + 1
        if day.startswith("202402") and calls[day] == 1:      # 2월은 처음 한 번 빈 응답
            raise KeyError("종가")
        df = pd.DataFrame({"종가": [1.0], "시가총액": [10.0]}, index=["000010"])
        df.to_pickle(cache_dir / f"krx_{day}.pkl")
        return df

    monkeypatch.setattr(kr_factors, "snapshot", fake_snapshot)
    snaps = kr_factors.load(tmp_path, start="2024-01", pause=0)
    assert len(snaps) == 3 and calls["20240228"] == 2
    # 다음 실행은 저장본만 읽고 한국거래소에 묻지 않는다
    calls.clear()
    assert len(kr_factors.load(tmp_path, start="2024-01", pause=0)) == 3 and not calls


def test_public_pages_drop_allocation_and_buy_wording():
    from market_dashboard import kr_html, public, sector_html
    dash, sec, kr = _three_screens()
    assert any(a["weight"] > 0 for a in dash["assets"])            # 집 PC 화면에는 있다
    pd_, ps, pk = public.assets(dash), public.sectors(sec), public.kr(kr)
    assert all(a["weight"] == 0 for a in pd_["assets"]) and pd_["backtest"] is None and not pd_["products"]
    assert all(s["weight"] == 0 for c in ps["countries"] for s in c["sectors"])
    assert all(r["status"] != "후보" for c in ps["countries"] for s in c["sectors"] for r in s["stocks"])
    pages = {"asset": html.render(pd_), "sector": sector_html.render(ps), "kr": kr_html.render(pk)}
    for name, page in pages.items():
        # 화면 구간(HTML)이 빠졌는지만 본다 — 화면에 실제로 보이는 글은 브라우저 점검으로 확인
        for word in ("<h2>이 자산군 사려면</h2>", "<h2>백테스트(원화 기준)</h2>", "<h2>규칙</h2>", "이번 연구에서 가장 나았던 방식",
                     "매수 후보\"", "<!--private-->"):
            assert word not in page, (name, word)
        assert "참고 자료" in page or "매매 신호" in page
    # 집 PC 화면은 그대로
    assert "이 자산군 사려면" in html.render(dash) and "고배당 30" in kr_html.render(kr)


def test_risk_signals_follow_backtest_rules():
    from market_dashboard import brief
    idx = pd.bdate_range("2023-01-02", "2026-10-30")
    up = pd.Series(np.linspace(100, 200, len(idx)), index=idx)
    down = up.copy()
    down.iloc[-120:] = np.linspace(200, 120, 120)                 # 최근 반년 급락
    cidx = pd.bdate_range("1990-01-01", "2026-10-30")
    calm = pd.Series(2.0 + 0.3 * np.sin(np.arange(len(cidx)) / 200), index=cidx)
    wide = calm.copy()
    wide.iloc[-60:] += np.linspace(0, 3, 60)                      # 최근 3개월 스프레드 급확대
    safe = brief.risk_block(brief.risk_states(up, calm))
    risky = brief.risk_block(brief.risk_states(down, wide))
    st = {s["key"]: s["state"] for s in risky["signals"]}
    assert st == {"us_trend": "위험", "us_mom12": "위험", "credit": "위험"} and risky["on"] == 3
    assert {s["key"]: s["state"] for s in safe["signals"]}["us_trend"] == "안전"
    # 무디스 자료(신용 스프레드)는 값 없이 상태만
    assert next(s for s in risky["signals"] if s["key"] == "credit")["value"] is None
    b = brief.build(None, None, None, risk=risky)
    assert b["headline"][0] == "미국 하락 위험 신호 3/3개 켜짐"
    prev = brief.build(None, None, None, risk=safe)
    assert brief.build(None, None, None, prev=prev, risk=risky)["changes"]["risk_moves"]


def test_kr_public_data_source_builds_map(tmp_path):
    """공공데이터포털 응답 모양(가짜)으로 한국 종목 지도를 만든다: 분할 보정·시가총액 가중 비교 지수·배당 열 없음."""
    from datetime import datetime
    from market_dashboard import kr_html, kr_public, kr_stocks
    rng = np.random.default_rng(7)
    days = pd.bdate_range("2023-09-01", "2026-10-30")
    codes = [f"{i:05d}0" for i in range(1, 61)] + ["000015"]          # 마지막은 우선주(빠져야 함)
    rows = []
    for j, c in enumerate(codes):
        px = 10000 * np.exp(np.cumsum(rng.normal(0.0003, 0.02, len(days))))
        shares = np.full(len(days), 1e7)
        if j == 0:                                                     # 첫 종목: 중간에 1:5 액면분할
            px[400:] /= 5
            shares[400:] *= 5
        for d, p_, sh in zip(days, px, shares):
            rows.append({"basDt": d.strftime("%Y%m%d"), "srtnCd": c, "itmsNm": "스팩1호" if j == 59 else f"종목{j}",
                         "mrktCtg": "KOSDAQ" if j % 3 == 0 else "KOSPI", "clpr": str(round(p_)), "trqu": "1000",
                         "trPrc": str(5e9 + j * 1e8), "lstgStCnt": str(int(sh)), "mrktTotAmt": str(p_ * sh * (1 + j))})
    allrows = pd.DataFrame(rows)

    def fake_fetch(key, params):
        df = allrows
        if "basDt" in params:
            df = df[df["basDt"] == params["basDt"]]
        if "likeSrtnCd" in params:
            df = df[(df["srtnCd"] == params["likeSrtnCd"]) & (df["basDt"] >= params["beginBasDt"])
                    & (df["basDt"] <= params["endBasDt"])]
        n, pg = params["numOfRows"], params["pageNo"]
        return df.iloc[(pg - 1) * n: pg * n].to_dict("records"), len(df)

    snap = kr_public.latest("k", today=datetime(2026, 11, 1, tzinfo=kr_public.KST), fetch=fake_fetch)
    assert snap["date"].iloc[0] == pd.Timestamp("2026-10-30")
    uni = kr_public.universe(snap)
    assert "000015" not in uni.index and not uni["종목명"].str.contains("스팩").any()
    panel = kr_public.update_panel("k", list(uni.index), tmp_path, snap, fetch=fake_fetch)
    close, vol = kr_public.prices(panel, list(uni.index), kr_stocks.BENCH)
    s = close["000010"].dropna()
    assert abs(s.iloc[401] / s.iloc[399] - 1) < 0.2                   # 분할 날 가격이 1/5로 뚝 떨어지지 않음
    d = kr_stocks.build(uni, close, vol, bench_name=kr_public.BENCH_NAME, bench_short=kr_public.BENCH_SHORT,
                        source=kr_public.SOURCE)
    assert d["source"] == kr_public.SOURCE and len([x for x in d["stocks"] if not x["bench"]]) == 59
    bench = next(x for x in d["stocks"] if x["bench"])
    assert bench["short"] == "상위 200" and bench["x"] is not None
    assert all(x["div"] is None for x in d["stocks"])
    # 다음 날: 저장본에 하루치만 이어 붙인다
    calls = []
    kr_public.update_panel("k", list(uni.index), tmp_path, snap, fetch=lambda k, p: (calls.append(p), fake_fetch(k, p))[1])
    assert all("likeSrtnCd" not in c for c in calls)
    page = kr_html.render(d)
    assert "금융위원회" in page


def test_indicator_now_ignores_month_without_us_price():
    """미국장이 아직 안 열린 새 달(한국 시세만 있는 줄)을 '12개월 수익 마이너스'로 읽으면 안 된다."""
    from market_dashboard import brief, indicators
    idx = pd.bdate_range("2023-01-02", "2026-10-30")
    spx = pd.Series(np.linspace(90, 100, len(idx)), index=idx)
    px = pd.DataFrame({"^GSPC": spx})
    for t in ["^VIX", "^KS11", "KRW=X"] + indicators.SECTORS9:
        px[t] = spx
    px.loc[pd.Timestamp("2026-11-02")] = np.nan
    px.loc[pd.Timestamp("2026-11-02"), "^KS11"] = 50.0
    fred = pd.DataFrame({"T10Y3M": [1.0], "BAA10Y": [2.0], "UNRATE": [5.0]}, index=[pd.Timestamp("2020-01-01")])
    sig = indicators.signals(px, fred)
    assert sig["us_mom12"].dropna().iloc[-1] == True          # noqa: E712 - 10월 말 기준 플러스
    assert brief.risk_states(spx, None)["us_mom12"]["risk"] is False


def test_for_post_waits_retries_and_falls_back_to_site_files(tmp_path, monkeypatch):
    """게시된 요약이 오늘 것이 아니면 기다렸다가 PC에서 계산하고, 미국 섹터 계산이 두 번 다 실패하면 게시된 섹터 파일을 쓴다."""
    import subprocess
    from market_dashboard import brief
    dash, sec, kr = _three_screens()
    site = {"brief.json": {"date": "2026-11-01", "us": {"x": 1}, "kr": {"x": 1}}, "sectors.json": sec}
    monkeypatch.setattr(brief, "_get_json", lambda url: site.get(url.rsplit("/", 1)[-1]))
    monkeypatch.setattr(brief, "fetch_markets", lambda: [])
    monkeypatch.setattr(brief, "fetch_risk", lambda: None)
    runs = []

    def fake_run(cmd, cwd, timeout, check, stdout, stderr):
        name = {"run": "dashboard.json", "sectors": "sectors.json", "krstocks": "kr.json"}[cmd[3]]
        runs.append(cmd[3])
        if cmd[3] != "sectors":                       # 미국 섹터만 계속 실패
            (pathlib.Path(cmd[5]) / name).write_text(json.dumps({"run": dash, "krstocks": kr}[cmd[3]]), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 1 if cmd[3] == "sectors" else 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    slept = []
    out = tmp_path / "out" / "market_brief.json"
    brief.for_post("2026-11-02", out, sleep=slept.append)
    b = json.loads(out.read_text(encoding="utf-8"))
    assert slept == [15 * 60] and runs.count("sectors") == 2 and runs.count("run") == 1
    assert b["us"]["leaders"] is not None and b["from_site"] == ["sectors.json"] and b["kr"]["n"] > 0
    assert (tmp_path / "out" / "dashboard" / "sectors.log").exists()
    # 게시된 섹터 파일도 없으면 빠진 채로 쓰지 않고 멈춘다
    site.pop("sectors.json")
    out2 = tmp_path / "out2" / "market_brief.json"
    with pytest.raises(RuntimeError, match="미국 섹터"):
        brief.for_post("2026-11-02", out2, sleep=lambda s: None)



def test_for_post_needs_todays_kospi_close(tmp_path, monkeypatch):
    """요약 날짜가 오늘이어도 코스피 종가가 전날 것이면(장중에 갱신된 요약) 쓰지 않고 기다렸다가 PC에서 계산한다."""
    import subprocess
    from market_dashboard import brief
    dash, sec, kr = _three_screens()
    ks = lambda d: [{"ticker": "^KS11", "date": d, "close": 1.0}, {"ticker": "^GSPC", "date": "2026-11-02", "close": 1.0}]
    fresh = {"date": "2026-11-03", "markets": ks("2026-11-03"), "us": {"x": 1}, "kr": {"x": 1}}
    stale = {"date": "2026-11-03", "markets": ks("2026-11-02"), "us": {"x": 1}, "kr": {"x": 1}}
    assert brief.kr_fresh(fresh, "2026-11-03") and not brief.kr_fresh(stale, "2026-11-03")
    assert not brief.kr_fresh({}, "2026-11-03")
    site = {"brief.json": stale}
    monkeypatch.setattr(brief, "_get_json", lambda url: site.get(url.rsplit("/", 1)[-1]))
    monkeypatch.setattr(brief, "fetch_risk", lambda: None)
    runs = []

    def fake_run(cmd, cwd, timeout, check, stdout, stderr):
        name = {"run": "dashboard.json", "sectors": "sectors.json", "krstocks": "kr.json"}[cmd[3]]
        runs.append(cmd[3])
        (pathlib.Path(cmd[5]) / name).write_text(json.dumps({"run": dash, "sectors": sec, "krstocks": kr}[cmd[3]]),
                                                 encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    # 1) 오늘 종가가 든 요약은 기다리지 않고 그대로 쓴다
    site["brief.json"] = fresh
    slept = []
    out = tmp_path / "a" / "market_brief.json"
    brief.for_post("2026-11-03", out, sleep=slept.append)
    assert slept == [] and runs == [] and json.loads(out.read_text(encoding="utf-8"))["markets"][0]["date"] == "2026-11-03"
    # 2) 장중 요약(코스피 전날 종가)은 기다렸다가 PC에서 계산하고, 그래도 오늘 종가가 없으면 kr_stale로 표시한다
    site["brief.json"] = stale
    monkeypatch.setattr(brief, "fetch_markets", lambda: ks("2026-11-02"))
    out = tmp_path / "b" / "market_brief.json"
    brief.for_post("2026-11-03", out, sleep=slept.append)
    b = json.loads(out.read_text(encoding="utf-8"))
    assert slept == [15 * 60] and sorted(runs) == ["krstocks", "run", "sectors"]
    assert b["source"] == "local" and b["kr_stale"] == "2026-11-02"
    # 3) PC 계산에 오늘 종가가 있으면 표시하지 않는다
    monkeypatch.setattr(brief, "fetch_markets", lambda: ks("2026-11-03"))
    out = tmp_path / "c" / "market_brief.json"
    brief.for_post("2026-11-03", out, sleep=lambda s: None)
    assert "kr_stale" not in json.loads(out.read_text(encoding="utf-8"))

def _fake_ohlc(days=520, seed=11):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-10-01", periods=days)
    out = {}
    for k, base in (("KS11", 2500), ("GSPC", 5000), ("IXIC", 16000)):
        c = base * np.exp(np.cumsum(rng.normal(0.0003, 0.01, days)))
        o = c * (1 + rng.normal(0, 0.003, days))
        out[k] = pd.DataFrame({"Open": o, "High": np.maximum(o, c) * 1.004, "Low": np.minimum(o, c) * 0.996, "Close": c},
                              index=idx)
    return out


def test_market_chart_builds_with_risk_band_marks_and_posts():
    from market_dashboard import chart
    ohlc = _fake_ohlc()
    last = ohlc["GSPC"].index[-1].strftime("%Y-%m-%d")
    prev = ohlc["GSPC"].index[-2].strftime("%Y-%m-%d")
    archive = [{"date": prev, "kr": {"above_sma": 0.22, "counts": {"소외": 96}}, "us": {"leaders": ["에너지"]},
                "risk": {"on": 1, "of": 3}, "changes": {"kr_above_sma_pp": -2.0}, "headline": ["h"]},
               {"date": last, "kr": {"above_sma": 0.25}, "headline": []}]
    posts = {prev: {"title": "시황", "url": "https://blog.naver.com/x/1"}}
    risk = chart.risk_history(ohlc["GSPC"]["Close"], None, days=30)
    d = chart.build(ohlc, archive, posts, risk)
    assert set(d["series"]) == {"KS11", "GSPC", "IXIC"} and len(d["series"]["KS11"]["d"]) == 520
    o, h, lo, c = d["series"]["GSPC"]["d"][-1][1:]
    assert lo <= min(o, c) and h >= max(o, c)
    assert len(d["risk"]) == 30 and all(0 <= r["on"] <= r["of"] for r in d["risk"].values())
    assert d["marks"][prev]["post"].endswith("/1") and d["marks"][prev]["kr_above_pp"] == -2.0
    assert "post" not in d["marks"][last]
    # 그날까지의 값만: 마지막 날의 띠는 오늘 시황 요약의 위험 신호 계산과 같다
    from market_dashboard import brief
    assert risk[last]["on"] == brief.risk_block(brief.risk_states(ohlc["GSPC"]["Close"], None))["on"]
    page = html.render(_three_screens()[0])
    assert 'id="mktCard"' in page and "chart.json" in page


def test_deleted_sihwang_post_is_dropped_but_old_ones_kept():
    from market_dashboard import brief
    known = {"2026-10-01": {"title": "10월 1일 시황", "url": "https://blog.naver.com/b/1"},   # RSS 기간 밖 → 유지
             "2026-11-03": {"title": "11월 3일 시황 | 시험", "url": "https://blog.naver.com/b/9"}}  # 지운 글
    items = [{"title": "11월 4일 시황 | 오늘", "url": "https://blog.naver.com/b/10", "pub_date": "Wed, 04 Nov 2026 13:40:00 +0900"},
             {"title": "연봉 4천, 상위 몇 %일까?", "url": "https://blog.naver.com/b/8", "pub_date": "Mon, 02 Nov 2026 07:00:00 +0900"}]
    got = brief.match_posts(items, brief.drop_deleted(items, known))
    assert set(got) == {"2026-10-01", "2026-11-04"}
    assert brief.drop_deleted([], known) == known          # RSS를 못 받으면 아무것도 지우지 않는다


def test_kr_index_fills_days_yahoo_is_missing(monkeypatch):
    """야후에 11/3 코스피가 없으면 한국 출처 값으로 채우고, 야후에 있는 날은 건드리지 않는다."""
    from market_dashboard import kr_index
    idx = pd.bdate_range("2026-10-26", "2026-11-02")
    yahoo = pd.DataFrame({"Close": np.linspace(5600, 5859.08, len(idx))}, index=idx)
    naver = kr_index.parse_naver([
        {"localTradedAt": "2026-11-03T15:30:00+09:00", "closePrice": "5,648.79", "openPrice": "5,800.00",
         "highPrice": "5,810.00", "lowPrice": "5,615.80"},
        {"localTradedAt": "2026-11-02", "closePrice": "1.00"},       # 야후에 있는 날은 무시
    ])
    from market_dashboard import brief
    out = kr_index.fill(yahoo, "^KS11", extra=naver)
    assert out.index[-1] == pd.Timestamp("2026-11-03") and out["Close"].iloc[-1] == 5648.79
    assert out.loc["2026-11-02", "Close"] == 5859.08 and list(out.columns) == ["Close"]
    e = brief.market_entry("^KS11", "코스피", out["Close"])
    assert e["date"] == "2026-11-03" and round(e["d1"], 4) == round(5648.79 / 5859.08 - 1, 4)
    assert kr_index.backup("^GSPC") is None                                  # 한국 지수가 아니면 받지 않는다


def test_repair_kr_fixes_archived_brief_with_stale_kospi():
    from market_dashboard import brief
    idx = pd.bdate_range("2026-10-26", "2026-11-03")
    s = pd.Series(np.r_[np.linspace(5500, 5859.08, len(idx) - 1), 5648.79], index=idx)
    old = {"date": "2026-11-03", "generated": "2026-11-03 22:39 KST", "kr_stale": "2026-11-02",
           "markets": [{"ticker": "^KS11", "name": "코스피", "date": "2026-11-02", "d1": 0.0224}]}
    morning = {"date": "2026-11-04", "generated": "2026-11-04 07:20 KST",       # 아침 요약은 11/3까지가 맞다
               "markets": [{"ticker": "^KS11", "name": "코스피", "date": "2026-11-02", "d1": 0.0224}]}
    fine = {"date": "2026-11-03", "generated": "2026-11-03 12:34 KST",          # 장중 요약은 11/2가 맞다
            "markets": [{"ticker": "^KS11", "name": "코스피", "date": "2026-11-02", "d1": 0.0224}]}
    fixed = brief.repair_kr([old, morning, fine], {"^KS11": s})
    assert fixed == [old, morning] and "kr_stale" not in old
    assert old["markets"][0]["date"] == "2026-11-03" and old["markets"][0]["d1"] < -0.03
    assert "코스피 -3.6%" in old["headline"] and fine["markets"][0]["date"] == "2026-11-02"


def test_manual_posts_override_rss(tmp_path, monkeypatch):
    from market_dashboard import brief
    f = tmp_path / "m.json"
    f.write_text(json.dumps({"2026-11-03": {"title": "11월 3일 시황", "url": "https://blog.naver.com/x/1"},
                             "bad": {"url": "u"}}), encoding="utf-8")
    assert brief.manual_posts(f) == {"2026-11-03": {"title": "11월 3일 시황", "url": "https://blog.naver.com/x/1"}}
    # RSS를 못 받아도 직접 지정한 링크는 posts.json에 들어간다
    monkeypatch.setattr(brief, "MANUAL_POSTS", f)
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(OSError("막힘")))
    assert brief.sync_posts(tmp_path / "arch", "someblog")["2026-11-03"]["url"].endswith("/1")
    real = brief.manual_posts(pathlib.Path(brief.__file__).with_name("posts_manual.json"))
    assert real["2026-11-03"]["url"].endswith("224464022707")


def test_fetch_risk_returns_none_when_yahoo_is_empty(monkeypatch):
    """야후가 빈 시세를 주면(집 PC SSL 오류 등) 글쓰기를 멈추지 않고 위험 신호만 뺀다."""
    import yfinance as yf
    from market_dashboard import brief
    monkeypatch.setattr(yf, "download", lambda *a, **k: pd.DataFrame({"Close": pd.Series(dtype=float)}))
    assert brief.fetch_risk() is None


def test_ascii_ca_bundle_on_korean_user_folder(tmp_path, monkeypatch):
    import certifi
    import market_dashboard as md
    src = tmp_path / "박보영" / "cacert.pem"
    src.parent.mkdir()
    src.write_text("CERT", encoding="utf-8")
    monkeypatch.setattr(md._sys, "platform", "win32")
    monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
    monkeypatch.setattr(certifi, "where", lambda: str(src))
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "pd"))
    md._ascii_ca_bundle()
    dst = md._os.environ["CURL_CA_BUNDLE"]
    assert dst.startswith(str(tmp_path / "pd")) and pathlib.Path(dst).read_text(encoding="utf-8") == "CERT"
    monkeypatch.delenv("CURL_CA_BUNDLE")
