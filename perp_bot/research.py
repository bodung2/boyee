"""코인 매매 방법론 비교 연구. 결과를 보기 전에 시험할 전략·숫자를 모두 아래에 고정해 두고, 전부 보고한다.

데이터: Yahoo 일봉(BTC 2014~, ETH 2017~, SOL 2020~). 펀딩비 메커니즘만 Hyperliquid(약 2.5년).
검증: 2020년까지 = '고르는 기간(IS)', 2021년부터 = '평가 기간(OOS)'. OOS 숫자가 진짜 성적이다.
가정(보수적):
- 신호는 그날 종가로 판단하고 다음 날 시가에 체결(일봉 브래킷은 시가부터 고가·저가로 손절·익절 확인).
- 비용: 한 번 사고팔 때마다 편도 0.10%(수수료+미끄러짐).
- 펀딩비: 롱 보유 시 연 10%(무기한 선물에서 롱이 보통 내는 수준), 숏은 0으로 계산(받는 펀딩을 무시 = 불리하게).
- 같은 날 손절과 익절에 모두 닿으면 손절 먼저(불리하게).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

COINS = {"BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD"}
SPLIT = pd.Timestamp("2021-01-01")
COST = 0.001
FUND_LONG = 0.10
RISK = 0.01   # 손익비형 전략: 한 거래에 잔고의 1%를 건다(손절 = −1R)


def load_daily() -> dict[str, pd.DataFrame]:
    import yfinance as yf

    out = {}
    for k, t in COINS.items():
        df = yf.download(t, start="2014-01-01", auto_adjust=False, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[["Open", "High", "Low", "Close"]].dropna()
        df.columns = ["open", "high", "low", "close"]
        df.index = pd.to_datetime(df.index).tz_localize(None)
        out[k] = df
    return out


# ---------- 지표 ----------
def sma(s, n):
    return s.rolling(n, min_periods=n).mean()


def atr(df, n=14):
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=n).mean()


def rsi(s, n):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


# ---------- A. 포지션형 전략(매일 보유 비중 −1~+1) ----------
def run_positions(df: pd.DataFrame, pos: pd.Series) -> pd.Series:
    """pos[t] = t일 종가에 정한 보유 비중 → t+1일 수익에 적용. 일간 전략 수익률."""
    ret = df["close"].pct_change().fillna(0)
    p = pos.reindex(df.index).fillna(0).shift(1).fillna(0)
    cost = pos.reindex(df.index).fillna(0).diff().abs().fillna(0).shift(1).fillna(0) * COST
    fund = p.clip(lower=0) * FUND_LONG / 365
    return p * ret - cost - fund


def pos_hold(df):
    return pd.Series(1.0, index=df.index)


def pos_sma(df, n):
    return (df["close"] > sma(df["close"], n)).astype(float)


def pos_tsmom(df, n, short=False):
    m = np.sign(df["close"].pct_change(n))
    return m if short else m.clip(lower=0)


def pos_dual_ma(df, f, s):
    return (sma(df["close"], f) > sma(df["close"], s)).astype(float)


def pos_rsi2(df):
    """평균회귀: 200일선 위에서 RSI(2)<10이면 사고, 5일선 위로 오르거나 5일 지나면 판다."""
    c = df["close"]
    r2, s200, s5 = rsi(c, 2), sma(c, 200), sma(c, 5)
    pos = np.zeros(len(c))
    held = 0
    for i in range(len(c)):
        if held:
            held += 1
            if c.iloc[i] > s5.iloc[i] or held > 5:
                held = 0
        elif r2.iloc[i] < 10 and c.iloc[i] > s200.iloc[i]:
            held = 1
        pos[i] = 1.0 if held else 0.0
    return pd.Series(pos, index=c.index)


def vol_target(df, base, target=0.6, cap=1.0):
    """기본 신호에 변동성 맞춤(연 60% 목표, 최대 1배)."""
    vol = df["close"].pct_change().rolling(30).std() * math.sqrt(365)
    return base * (target / vol).clip(upper=cap).fillna(0)


# ---------- B. 손익비형(브래킷) 전략 ----------
@dataclass
class Trade:
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    r: float
    days: int
    reason: str
    entry_px: float = 0.0
    risk: float = 0.0
    exit_px: float = 0.0


def run_bracket(df: pd.DataFrame, entry: pd.Series, sl_atr: float, rr: float | None,
                exit_low: int | None = None, time_stop: int | None = None) -> list[Trade]:
    """롱만. entry[t]가 참이면 t+1 시가에 진입. 손절 = 진입가 − sl_atr×ATR(t).
    rr가 있으면 익절 = 진입가 + rr×손절폭. exit_low가 있으면 최근 N일 최저가 이탈 시 종가 청산(추세 추종형)."""
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    a = atr(df).to_numpy()
    lowN = df["low"].rolling(exit_low).min().shift(1).to_numpy() if exit_low else None
    ent = entry.reindex(df.index).fillna(False).to_numpy()
    idx = df.index
    trades: list[Trade] = []
    i = 0
    n = len(df)
    while i < n - 1:
        if not ent[i] or np.isnan(a[i]):
            i += 1
            continue
        j = i + 1
        e = o[j]
        risk = sl_atr * a[i]
        if risk <= 0:
            i += 1
            continue
        sl, tp = e - risk, (e + rr * risk if rr else None)
        exit_px, reason, k = None, "", j
        for k in range(j, n):
            if k > j and o[k] <= sl:
                exit_px, reason = o[k], "손절(갭)"
            elif l[k] <= sl:
                exit_px, reason = sl, "손절"
            elif tp is not None and k > j and o[k] >= tp:
                exit_px, reason = o[k], "익절(갭)"
            elif tp is not None and h[k] >= tp:
                exit_px, reason = tp, "익절"
            elif lowN is not None and not np.isnan(lowN[k]) and c[k] < lowN[k]:
                exit_px, reason = c[k], "추세 이탈"
            elif time_stop and k - j + 1 >= time_stop:
                exit_px, reason = c[k], "시간 청산"
            if exit_px is not None:
                break
        if exit_px is None:
            exit_px, reason, k = c[n - 1], "기간 끝", n - 1
        days = k - j + 1
        cost_r = (COST * (e + exit_px)) / risk
        fund_r = e * FUND_LONG / 365 * days / risk
        trades.append(Trade(idx[j], idx[k], (exit_px - e) / risk - cost_r - fund_r, days, reason, e, risk, exit_px))
        i = k + 1
    return trades


def trades_to_returns(trades: list[Trade], df: pd.DataFrame) -> pd.Series:
    """거래마다 잔고의 RISK를 걸었다고 보고, 보유 중에도 매일 종가로 평가한 일간 수익률
    (청산일에만 반영하면 보유 중 되돌림이 낙폭에서 빠져 지나치게 좋아 보인다)."""
    r = pd.Series(0.0, index=df.index)
    close = df["close"]
    for t in trades:
        path = close.loc[t.entry_date:t.exit_date].to_numpy().copy()
        path[-1] = t.exit_px
        prev = np.concatenate([[t.entry_px], path[:-1]])
        daily = RISK * (path - prev) / t.risk
        dates = close.loc[t.entry_date:t.exit_date].index
        r.loc[dates] += daily
        r.loc[t.exit_date] += RISK * (t.r - (t.exit_px - t.entry_px) / t.risk)  # 비용·펀딩
    return r


# ---------- C. 코인 간 순환 ----------
def rotation(data: dict[str, pd.DataFrame], look=30) -> pd.Series:
    """매주 최근 look일 수익률이 가장 높은 코인 하나를 보유(그 수익률이 0 이하이면 현금)."""
    closes = pd.DataFrame({k: v["close"] for k, v in data.items()}).ffill()
    mom = closes.pct_change(look)
    weekly = mom.resample("W-SUN").last().dropna(how="all")
    pick = weekly.idxmax(axis=1).where(weekly.max(axis=1) > 0)
    pick = pick.reindex(closes.index, method="ffill")
    ret = closes.pct_change().fillna(0)
    out = pd.Series(0.0, index=closes.index)
    prev = None
    for t in closes.index:
        cur = pick.get(t)
        cur = cur if isinstance(cur, str) else None
        out.loc[t] = 0.0
        if prev is not None:
            out.loc[t] = ret.loc[t, prev] - FUND_LONG / 365
        if cur != prev:
            out.loc[t] -= COST * ((prev is not None) + (cur is not None))
        prev = cur
    return out


# ---------- 평가 ----------
def stats(r: pd.Series, trades: list[Trade] | None = None) -> dict:
    r = r.dropna()
    if len(r) < 60:
        return {}
    eq = (1 + r).cumprod()
    yrs = len(r) / 365
    out = {
        "CAGR": eq.iloc[-1] ** (1 / yrs) - 1 if eq.iloc[-1] > 0 else -1.0,
        "샤프": r.mean() / r.std() * math.sqrt(365) if r.std() > 0 else 0.0,
        "MDD": float((eq / eq.cummax() - 1).min()),
        "노출": float((r != 0).mean()),
    }
    if trades is not None:
        rs = np.array([t.r for t in trades])
        out["거래"] = len(rs)
        if len(rs):
            w, ls = rs[rs > 0], rs[rs <= 0]
            out["승률"] = len(w) / len(rs)
            payoff = (w.mean() / -ls.mean()) if len(w) and len(ls) and ls.mean() < 0 else float("nan")
            out["손익비"] = payoff
            out["손익분기 승률"] = 1 / (1 + payoff) if payoff == payoff else float("nan")
            out["기대값R"] = float(rs.mean())
            out["중앙R"] = float(np.median(rs))
            tot = rs.sum()
            out["상위3비중"] = float(np.sort(rs)[-3:].sum() / tot) if tot > 0 else float("nan")
    # 600$→400$(−33%)에 닿지 않으려면 견딜 수 있는 대략의 최대 레버리지
    out["허용 레버리지(−33%)"] = min(0.33 / -out["MDD"], 10.0) if out["MDD"] < 0 else 10.0
    return out


def split(r: pd.Series, trades=None):
    isr, oos = r[r.index < SPLIT], r[r.index >= SPLIT]
    if trades is None:
        return stats(isr), stats(oos)
    return (stats(isr, [t for t in trades if t.exit_date < SPLIT]),
            stats(oos, [t for t in trades if t.exit_date >= SPLIT]))


def strategies(df: pd.DataFrame) -> dict:
    """시험할 전략 전부(결과를 보기 전에 고정). 값: ('pos', 비중) 또는 ('trades', 거래 목록)."""
    c = df["close"]
    s200, s50 = sma(c, 200), sma(c, 50)
    hi20 = df["high"].rolling(20).max().shift(1)
    breakout = (c > hi20) & (c > s200)
    r14 = rsi(c, 14)
    pullback = (c > s200) & (s50 > s200) & (r14 > 35) & (r14.shift(1) <= 35)
    S = {
        "보유(기준선)": ("pos", pos_hold(df)),
        "200일선 위 보유": ("pos", pos_sma(df, 200)),
        "100일선 위 보유": ("pos", pos_sma(df, 100)),
        "50일선 위 보유": ("pos", pos_sma(df, 50)),
        "20/100 이평 교차": ("pos", pos_dual_ma(df, 20, 100)),
        "모멘텀 30일(롱)": ("pos", pos_tsmom(df, 30)),
        "모멘텀 90일(롱)": ("pos", pos_tsmom(df, 90)),
        "모멘텀 90일(롱숏)": ("pos", pos_tsmom(df, 90, short=True)),
        "200일선 + 변동성맞춤": ("pos", vol_target(df, pos_sma(df, 200))),
        "평균회귀 RSI(2)": ("pos", pos_rsi2(df)),
        "터틀 20일 돌파·10일 저점 이탈(손절 2ATR)": ("trades", run_bracket(df, breakout, 2.0, None, exit_low=10)),
        "터틀 짧은 손절(1ATR)·10일 저점 이탈": ("trades", run_bracket(df, breakout, 1.0, None, exit_low=10)),
    }
    for name, ent in (("돌파", breakout), ("눌림목", pullback)):
        for sl in (1.0, 1.5):
            for rr in (2, 3, 5):
                S[f"손익비 {name} 손절{sl:g}ATR 익절{rr}R"] = ("trades", run_bracket(df, ent, sl, rr, time_stop=60))
    return S


def run_all(data: dict[str, pd.DataFrame]) -> list[dict]:
    rows = []
    for coin, df in data.items():
        for name, (kind, val) in strategies(df).items():
            if kind == "pos":
                r = run_positions(df, val)
                isr, oos = split(r)
            else:
                r = trades_to_returns(val, df)
                isr, oos = split(r, val)
            rows.append({"coin": coin, "strategy": name, "IS": isr, "OOS": oos})
    # 손익비형 대표(짧은 손절 + 추세 이탈까지 보유)를 세 코인에 동시에(각 1% 위험) 운용
    combo = None
    for coin, df in data.items():
        c = df["close"]
        brk = (c > df["high"].rolling(20).max().shift(1)) & (c > sma(c, 200))
        rr = trades_to_returns(run_bracket(df, brk, 1.0, None, exit_low=10), df)
        combo = rr if combo is None else combo.add(rr, fill_value=0.0)
    isr, oos = split(combo)
    rows.append({"coin": "3종 합", "strategy": "터틀 짧은 손절(1ATR) 세 코인 동시", "IS": isr, "OOS": oos})
    rot = rotation(data)
    isr, oos = split(rot)
    rows.append({"coin": "3종 순환", "strategy": "30일 최강 코인 순환(주 1회)", "IS": isr, "OOS": oos})
    return rows


def luck_sharpe(n_tests: int, years: float) -> float:
    """아무 실력 없는 전략 n개 중 최고 샤프가 우연히 나올 만한 수준(대략 √(2 ln n / 년수))."""
    return math.sqrt(2 * math.log(max(n_tests, 2)) / max(years, 0.5))


def funding_carry(fund: dict[str, pd.Series]) -> list[str]:
    """펀딩비 수취: 현물 롱 + 무기한 숏(가격 방향 중립)으로 받는 펀딩. 진입·청산 비용 4회 반영."""
    lines = []
    for k, f in fund.items():
        if f is None or not len(f):
            continue
        yrs = (f.index[-1] - f.index[0]).days / 365
        always = f.sum() / yrs - 4 * COST / yrs
        d = f.resample("D").sum()
        on = (d.rolling(7).mean().shift(1) > 0)  # 지난 7일 평균 펀딩이 플러스일 때만
        cond = d[on].sum() / yrs - (on.astype(int).diff().abs().sum() * 2 * COST) / yrs
        lines.append(f"  {k}: 기간 {yrs:.1f}년, 펀딩 플러스 시간 비율 {(f > 0).mean() * 100:.0f}%, "
                     f"연 펀딩 평균 {f.mean() * 24 * 365 * 100:+.1f}% → 항상 보유 시 연 {always * 100:+.1f}%, "
                     f"7일 평균이 플러스일 때만 {cond * 100:+.1f}%(비용 반영)")
    return lines


def report(rows: list[dict], fund_lines: list[str] | None = None) -> str:
    def f(s, k, pct=True):
        v = s.get(k)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return "  –  "
        return f"{v * 100:+6.1f}%" if pct else f"{v:5.2f}"

    lines = ["[코인 매매 방법론 비교] IS = ~2020년(고르는 기간), OOS = 2021년~(평가 기간)",
             "비용 편도 0.1%, 롱 펀딩 연 10%, 숏이 받는 펀딩은 무시, 같은 날 손절·익절이면 손절로 처리", ""]
    head = "  {:<40} {:>4} | {:>7} {:>5} {:>7} | {:>7} {:>5} {:>7} {:>5} {:>6} {:>6} {:>6} {:>5}".format(
        "전략", "코인", "IS연", "IS샤프", "IS낙폭", "OOS연", "샤프", "낙폭", "거래", "승률", "손익비", "기대R", "레버")
    lines.append(head)
    for r in rows:
        i, o = r["IS"], r["OOS"]
        lines.append("  {:<40} {:>4} | {} {} {} | {} {} {} {:>5} {} {} {} {} {} {}".format(
            r["strategy"][:40], r["coin"][:4], f(i, "CAGR"), f(i, "샤프", False), f(i, "MDD"),
            f(o, "CAGR"), f(o, "샤프", False), f(o, "MDD"), o.get("거래", "–"), f(o, "승률"),
            f(o, "손익비", False), f(o, "기대값R", False), f(o, "중앙R", False), f(o, "상위3비중"),
            f(o, "허용 레버리지(−33%)", False)))
    n = len(rows)
    lines += ["", "손익비형은 한 거래에 잔고 1%를 걸고 보유 중에도 매일 평가. 상위3 = 전체 R 중 가장 좋은 3건이 차지한 비율.",
              f"시험한 전략×코인 {n}개. 실력 없이도 우연히 나올 만한 최고 OOS 샤프 ≈ {luck_sharpe(n, 5.8):.2f} "
                  "(이보다 낮으면 '운일 수 있음')."]
    # 코인 3개 모두에서 IS·OOS 둘 다 보유보다 나은 전략
    by = {}
    for r in rows:
        by.setdefault(r["strategy"], {})[r["coin"]] = r
    good = []
    for name, cs in by.items():
        if name == "보유(기준선)" or len(cs) < 3:
            continue
        ok = all(cs[c]["OOS"].get("샤프", -9) > by["보유(기준선)"][c]["OOS"].get("샤프", 9)
                 and cs[c]["IS"].get("샤프", -9) > 0 for c in cs if c in by["보유(기준선)"])
        if ok:
            good.append(name)
    lines.append("세 코인 모두에서 IS 플러스 + OOS 샤프가 단순 보유보다 높은 전략: " + (", ".join(good) if good else "없음"))
    if fund_lines:
        lines += ["", "== 펀딩비 수취(가격 방향 중립, Hyperliquid) =="] + fund_lines
    return "\n".join(lines)
