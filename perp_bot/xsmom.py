"""여러 코인 중 최근 강한 코인을 골라 사는 '종목 선정형 모멘텀' 검증. 현물·레버리지 없음.

결과를 보기 전에 시험할 규칙·숫자를 모두 아래에 고정해 두고, 전부 보고한다.

데이터: Yahoo 일봉(대부분 2017-11~). 몰락한 코인(LUNA·FTT·EOS·WAVES 등)도 일부러 넣었다(생존 편향 줄이기).
종목 후보(시점별): 그 주까지 90일 이상 거래 기록이 있고, 최근 30일 평균 거래대금 상위 15개.
  → 지금 기준 시가총액 상위를 미리 골라 넣는 '미래 정보'를 피한다. 다만 아래 목록 자체는 지금 아는
    코인들이라 생존 편향이 완전히 없지는 않다(그사이 사라져 Yahoo에 기록조차 없는 코인은 빠짐).
매매: 매주 일요일 종가에 판단 → 그 다음 날부터 1주 보유(주중 가격 변화로 비중이 흘러감).
비용: 편도 BTC·ETH 0.1%, 그 밖의 코인 0.3%(호가가 넓음). 리밸런싱 때 바뀐 비중만큼 낸다.
가격 기록이 중간에 끊긴 코인은 마지막 가격에 판 것으로 본다(유리한 가정 — 끊긴 코인 목록을 함께 보고).
검증: 2020년까지 = 고르는 기간(IS), 2021년부터 = 평가 기간(OOS).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .research import SPLIT, luck_sharpe, sma, stats

TICKERS = {
    "BTC": ("BTC-USD",), "ETH": ("ETH-USD",), "XRP": ("XRP-USD",), "BNB": ("BNB-USD",), "SOL": ("SOL-USD",),
    "ADA": ("ADA-USD",), "DOGE": ("DOGE-USD",), "TRX": ("TRX-USD",), "AVAX": ("AVAX-USD",), "DOT": ("DOT-USD",),
    "LINK": ("LINK-USD",), "LTC": ("LTC-USD",), "BCH": ("BCH-USD",), "XLM": ("XLM-USD",), "ATOM": ("ATOM-USD",),
    "ETC": ("ETC-USD",), "XMR": ("XMR-USD",), "EOS": ("EOS-USD",), "NEO": ("NEO-USD",), "XTZ": ("XTZ-USD",),
    "MATIC": ("MATIC-USD",), "UNI": ("UNI7083-USD", "UNI-USD"), "FIL": ("FIL-USD",), "ALGO": ("ALGO-USD",),
    "VET": ("VET-USD",), "ICP": ("ICP-USD",), "NEAR": ("NEAR-USD",), "HBAR": ("HBAR-USD",), "SHIB": ("SHIB-USD",),
    "LUNA(구)": ("LUNC-USD", "LUNA1-USD"), "FTT": ("FTT-USD",), "IOTA": ("IOTA-USD", "MIOTA-USD"),
    "DASH": ("DASH-USD",), "ZEC": ("ZEC-USD",), "WAVES": ("WAVES-USD",), "BSV": ("BSV-USD",),
    "THETA": ("THETA-USD",), "AAVE": ("AAVE-USD",), "SUI": ("SUI20947-USD", "SUI-USD"),
    "TON": ("TON11419-USD", "TON-USD"), "APT": ("APT21794-USD", "APT-USD"), "PEPE": ("PEPE24478-USD", "PEPE-USD"),
}
MAJORS = {"BTC", "ETH"}
UNIVERSE_N = 15
MIN_HISTORY = 90
COST_MAJOR, COST_ALT = 0.001, 0.003
LOOKBACKS = (7, 14, 30, 60)
TOPS = (1, 3, 5)
FILTERS = {"none": "필터 없음", "btc100": "BTC 100일선 위일 때만", "abs": "자기 수익률 플러스만"}


def load(start: str = "2017-01-01"):
    """반환: (종가 DataFrame, 거래대금 DataFrame, 못 받은 코인 목록). 날짜는 매일."""
    import yfinance as yf

    closes, dvols, missing = {}, {}, []
    for k, alts in TICKERS.items():
        best = None
        for t in alts:
            try:
                df = yf.download(t, start=start, auto_adjust=False, progress=False)
            except Exception:
                continue
            if df is None or df.empty:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df[["Close", "Volume"]].dropna(subset=["Close"])
            if best is None or df.index[0] < best.index[0]:
                best = df
        if best is None or len(best) < MIN_HISTORY:
            missing.append(k)
            continue
        best.index = pd.to_datetime(best.index).tz_localize(None)
        closes[k] = best["Close"].astype(float)
        dvols[k] = (best["Close"] * best["Volume"]).astype(float)
    close = pd.DataFrame(closes).sort_index()
    close = close.reindex(pd.date_range(close.index[0], close.index[-1], freq="D"))
    dvol = pd.DataFrame(dvols).reindex(close.index)
    return close, dvol, missing


def ended_early(close: pd.DataFrame, days: int = 30) -> list[str]:
    last = close.apply(lambda s: s.last_valid_index())
    return [f"{k}({d:%Y-%m})" for k, d in last.items() if d is not None and (close.index[-1] - d).days > days]


def backtest(close: pd.DataFrame, dvol: pd.DataFrame, top: int, look: int, filt: str = "none",
             weighting: str = "equal", fixed: dict[str, float] | None = None,
             majors: set[str] = MAJORS) -> tuple[pd.Series, dict]:
    """일간 수익률과 부가 정보(연 회전율, 현금 비율, 평균 보유 종목 수)."""
    px = close.ffill()
    real = close.notna()
    hist = real.cumsum()
    dv30 = dvol.rolling(30, min_periods=20).mean()
    ok = real & (hist >= MIN_HISTORY) & dv30.notna()
    cols = close.columns
    mom = px / px.shift(look) - 1
    vol30 = px.pct_change(fill_method=None).rolling(30, min_periods=20).std()
    btc_ok = close["BTC"].ffill() > sma(close["BTC"].ffill(), 100)
    cost = pd.Series({k: COST_MAJOR if k in majors else COST_ALT for k in close.columns})

    sundays = [t for t in close.index if t.weekday() == 6]
    ends = sundays[1:] + [close.index[-1]]
    out = pd.Series(np.nan, index=close.index)
    drift: dict[str, float] = {}
    turnover, cash_weeks, n_hold, weeks = 0.0, 0, 0, 0
    started = False
    for a, b in zip(sundays, ends):
        if b <= a:
            continue
        elig = list(cols[ok.loc[a].to_numpy()])
        if not started and len(elig) < 8:
            continue
        started = True
        if fixed is not None:
            w = {k: v for k, v in fixed.items() if k in elig}
        else:
            uni = dv30.loc[a, elig].nlargest(UNIVERSE_N).index
            m = mom.loc[a, uni].dropna()
            picks = list(m.nlargest(top).index)
            if filt == "btc100" and not bool(btc_ok.at[a]):
                picks = []
            elif filt == "abs":
                picks = [k for k in picks if mom.at[a, k] > 0]
            if weighting == "invvol" and picks:
                iv = {k: 1 / vol30.at[a, k] for k in picks if vol30.at[a, k] > 0}
                tot = sum(iv.values())
                w = {k: v / tot * len(picks) / top for k, v in iv.items()}
            else:
                w = {k: 1 / top for k in picks}
        tv = sum(abs(w.get(k, 0) - drift.get(k, 0)) * cost[k] for k in set(w) | set(drift))
        turnover += sum(abs(w.get(k, 0) - drift.get(k, 0)) for k in set(w) | set(drift))
        weeks += 1
        cash_weeks += not w
        n_hold += len(w)
        seg = px.loc[a:b]
        growth = {k: seg[k] / seg[k].iloc[0] for k in w}
        value = pd.Series(1 - sum(w.values()), index=seg.index)
        for k, g in growth.items():
            value = value + w[k] * g
        value = value * (1 - tv)
        value.iloc[0] = 1.0
        out.loc[seg.index[1:]] = (value / value.shift(1) - 1).iloc[1:].to_numpy()
        end_v = value.iloc[-1] / (1 - tv)
        drift = {k: w[k] * growth[k].iloc[-1] / end_v for k in w}
    r = out.dropna()
    yrs = max(len(r) / 365, 1e-9)
    info = {"회전율/년": turnover / yrs, "현금 주 비율": cash_weeks / max(weeks, 1),
            "평균 보유 수": n_hold / max(weeks, 1)}
    return r, info


def no_best_weeks(r: pd.Series, n: int = 5) -> float:
    """가장 좋았던 n주를 뺀 연 수익률(몇 번의 대박에 기대는지 확인)."""
    wk = (1 + r).resample("W-SUN").prod() - 1
    if len(wk) <= n:
        return float("nan")
    keep = wk.drop(wk.nlargest(n).index)
    eq = (1 + keep).prod()
    yrs = len(r) / 365
    return eq ** (1 / yrs) - 1 if eq > 0 else -1.0


def grid() -> list[tuple[str, dict]]:
    """시험할 전략 전부(결과를 보기 전에 고정)."""
    g = [("BTC 보유(기준선)", {"top": 1, "look": 1, "fixed": {"BTC": 1.0}}),
         ("상위15 동일비중 보유", {"top": UNIVERSE_N, "look": 1}),
         ("상위15 동일비중 + BTC 100일선", {"top": UNIVERSE_N, "look": 1, "filt": "btc100"})]
    for look in LOOKBACKS:
        for top in TOPS:
            for f, fname in FILTERS.items():
                g.append((f"상위{top} · {look}일 · {fname}", {"top": top, "look": look, "filt": f}))
    for look in (14, 30):
        for top in (3, 5):
            g.append((f"상위{top} · {look}일 · BTC 100일선 · 변동성가중",
                      {"top": top, "look": look, "filt": "btc100", "weighting": "invvol"}))
    return g


def run_all(close: pd.DataFrame, dvol: pd.DataFrame, majors: set[str] = MAJORS) -> list[dict]:
    rows = []
    for name, kw in grid():
        r, info = backtest(close, dvol, majors=majors, **kw)
        isr, oos = r[r.index < SPLIT], r[r.index >= SPLIT]
        rows.append({"strategy": name, "IS": stats(isr), "OOS": stats(oos), "info": info,
                     "OOS 대박5주 제외": no_best_weeks(oos), "bench": "fixed" in kw or kw["look"] == 1})
    return rows


def report(rows: list[dict], loaded: list[str], missing: list[str], ended: list[str],
           title: str = "[종목 선정형 모멘텀] 현물·레버리지 없음. IS = ~2020년, OOS = 2021년~") -> str:
    def f(v, pct=True):
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return "   –  "
        return f"{v * 100:+6.1f}%" if pct else f"{v:5.2f}"

    shown = ", ".join(loaded) if len(loaded) <= 60 else ", ".join(loaded[:60]) + " …"
    lines = [title, f"받은 코인 {len(loaded)}개: {shown}",
             f"못 받은 코인: {', '.join(missing) or '없음'} / 기록이 중간에 끊긴 코인: {', '.join(ended) or '없음'}",
             "", "  {:<34} | {:>7} {:>5} {:>7} | {:>7} {:>5} {:>7} {:>8} | {:>5} {:>5} {:>4} {:>5}".format(
                 "전략", "IS연", "IS샤프", "IS낙폭", "OOS연", "샤프", "낙폭", "대박5주X", "회전", "현금", "보유", "레버")]
    for r in rows:
        i, o, inf = r["IS"], r["OOS"], r["info"]
        lines.append("  {:<34} | {} {} {} | {} {} {} {:>8} | {:5.1f} {:>5} {:4.1f} {}".format(
            r["strategy"][:34], f(i.get("CAGR")), f(i.get("샤프"), False), f(i.get("MDD")),
            f(o.get("CAGR")), f(o.get("샤프"), False), f(o.get("MDD")), f(r["OOS 대박5주 제외"]),
            inf["회전율/년"], f"{inf['현금 주 비율'] * 100:.0f}%", inf["평균 보유 수"],
            f(o.get("허용 레버리지(−33%)"), False)))
    strat = [r for r in rows if not r["bench"]]
    btc = next(r for r in rows if r["strategy"].startswith("BTC 보유"))
    ew = next(r for r in rows if r["strategy"] == "상위15 동일비중 보유")
    beat_btc = sum(r["OOS"].get("샤프", -9) > btc["OOS"].get("샤프", 9) for r in strat)
    beat_ew = sum(r["OOS"].get("샤프", -9) > ew["OOS"].get("샤프", 9) for r in strat)
    med = float(np.median([r["OOS"].get("샤프", 0) for r in strat]))
    lines += ["", "회전 = 1년에 포트폴리오를 몇 바퀴 갈아끼웠는지, 현금 = 현금으로 쉰 주의 비율, 보유 = 평균 보유 종목 수.",
              "대박5주X = 2021년~ 가장 좋았던 5주를 뺐을 때의 연 수익률(몇 번의 급등에 기대는지).",
              f"전략 {len(strat)}개 중 OOS 샤프가 BTC 보유보다 높은 것 {beat_btc}개, 상위15 동일비중보다 높은 것 {beat_ew}개. "
              f"전략들의 OOS 샤프 중앙값 {med:.2f} (BTC {btc['OOS'].get('샤프', 0):.2f}, 동일비중 {ew['OOS'].get('샤프', 0):.2f}).",
              f"실력 없이도 우연히 나올 만한 최고 OOS 샤프 ≈ {luck_sharpe(len(rows), 5.8):.2f}."]
    pick = sorted(strat, key=lambda r: r["IS"].get("샤프", -9), reverse=True)[:3]
    lines.append("2020년까지 성적(IS 샤프)으로 골랐다면 → 2021년~ 실제 성적:")
    for r in pick:
        lines.append(f"  {r['strategy']}: IS 샤프 {r['IS'].get('샤프', 0):.2f} → OOS 연 {f(r['OOS'].get('CAGR')).strip()}, "
                     f"샤프 {r['OOS'].get('샤프', 0):.2f}, 낙폭 {f(r['OOS'].get('MDD')).strip()}")
    return "\n".join(lines)
