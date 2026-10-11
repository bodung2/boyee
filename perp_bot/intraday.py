"""빗썸 1시간 봉 차트 매매 검증(현물·롱만·레버리지 없음).

결과를 보기 전에 시험할 규칙·숫자를 모두 아래에 고정해 두고, 전부 보고한다.

- 코인: 빗썸 원화 마켓 대형 6개(BTC·ETH·XRP·SOL·DOGE·ADA). 급등 테마 코인은 일부러 뺐다(일봉 검증에서 지는 쪽).
- 기간: 2021년~. 앞 60%가 고르는 기간(IS), 뒤 40%가 평가 기간(OOS).
- 체결: 신호가 난 봉의 다음 봉 시가. 같은 봉에서 손절·익절 둘 다 닿으면 손절 먼저(불리하게).
- 비용: 편도 0.15%(수수료 + 미끄러짐, 보수적)와 0.05%(수수료 쿠폰 등 유리할 때) 두 가지로 모두 계산.
- 손익비형: 한 거래에 잔고 1%를 걸고(손절 = −1R), 보유 중에도 매시간 평가.
- 6개 코인을 동시에 운용한 결과(코인마다 1% 위험 / 포지션형은 6분의 1씩)를 한 줄로 보고하고,
  OOS에서 플러스였던 코인 수를 함께 적는다.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .research import Trade, atr, luck_sharpe, rsi, run_bracket, sma, stats, trades_to_returns

COINS = ("BTC", "ETH", "XRP", "SOL", "DOGE", "ADA")
SINCE = "2021-01-01"
COSTS = (0.0015, 0.0005)
IS_FRACTION = 0.6


def load(since: str = SINCE) -> dict[str, pd.DataFrame]:
    from . import bithumb

    return {k: bithumb.hourly(k, since=since) for k in COINS}


def split_time(data: dict[str, pd.DataFrame]) -> pd.Timestamp:
    start = min(df.index[0] for df in data.values())
    end = max(df.index[-1] for df in data.values())
    return (start + (end - start) * IS_FRACTION).normalize()


# ---------- 신호(모두 그 봉의 종가까지만 사용) ----------
def signals(df: pd.DataFrame) -> dict[str, pd.Series]:
    c, v = df["close"], df["volume"]
    s200 = sma(c, 200)
    up = c > s200
    hi24 = df["high"].rolling(24).max().shift(1)
    r14 = rsi(c, 14)
    mid, sd = sma(c, 20), c.rolling(20).std()
    lower = mid - 2 * sd
    ret1 = c.pct_change()
    vol_spike = v > 3 * v.rolling(24).mean().shift(1)
    return {
        "24시간 고점 돌파": (c > hi24) & up,
        "거래량 3배 + 24시간 고점 돌파": (c > hi24) & vol_spike & (c > df["open"]),
        "과매도 RSI<25 (상승장)": (r14 < 25) & up,
        "볼린저 하단 이탈 후 복귀 (상승장)": (c > lower) & (c.shift(1) <= lower.shift(1)) & up,
        "1시간 −3% 급락 뒤 반등 노리기": ret1 < -0.03,
    }


BRACKETS = {  # 이름: (손절 ATR 배수, 익절 R 목록, 최대 보유 시간)
    "24시간 고점 돌파": (1.5, (2, 3), 48),
    "거래량 3배 + 24시간 고점 돌파": (1.5, (2, 3), 48),
    "과매도 RSI<25 (상승장)": (2.0, (1, 2), 24),
    "볼린저 하단 이탈 후 복귀 (상승장)": (1.5, (1.5, 3), 24),
    "1시간 −3% 급락 뒤 반등 노리기": (2.0, (1, 2), 24),
}


def run_positions(df: pd.DataFrame, pos: pd.Series, cost: float) -> pd.Series:
    """pos[t] = t봉 종가에 정한 보유 비중 → t+1봉 수익에 적용."""
    ret = df["close"].pct_change().fillna(0)
    p = pos.reindex(df.index).fillna(0)
    held = p.shift(1).fillna(0)
    trade = p.diff().abs().fillna(p.abs()).shift(1).fillna(0)
    return held * ret - trade * cost


def best_hours(df: pd.DataFrame, until: pd.Timestamp, n: int = 4) -> list[int]:
    """IS 기간에서 평균 수익이 가장 높았던 시간대(한국 시각) n개. OOS 정보는 쓰지 않는다."""
    r = df["close"].pct_change().shift(-1)  # t봉 종가에 사서 t+1봉 종가까지
    r = r[r.index < until - pd.Timedelta(hours=1)]
    return list(r.groupby(r.index.hour).mean().nlargest(n).index)


def positions(df: pd.DataFrame, until: pd.Timestamp) -> dict[str, pd.Series]:
    c = df["close"]
    hours = best_hours(df, until)
    return {
        "보유(기준선)": pd.Series(1.0, index=df.index),
        "1시간 20/50 이평 교차": (sma(c, 20) > sma(c, 50)).astype(float),
        f"시간대 효과(IS 최고 4개 시간대만 보유: {sorted(hours)}시)":
            pd.Series(np.isin(df.index.hour, hours).astype(float), index=df.index),
    }


def to_daily(r: pd.Series) -> pd.Series:
    return (1 + r).resample("D").prod() - 1


def run_all(data: dict[str, pd.DataFrame]) -> tuple[list[dict], pd.Timestamp]:
    cut = split_time(data)
    per: dict[tuple[str, float], dict[str, tuple[pd.Series, list[Trade]]]] = {}
    for coin, df in data.items():
        df = df.dropna()
        if len(df) < 1000:
            continue
        sig = signals(df)
        for cost in COSTS:
            for name, pos in positions(df, cut).items():
                key = (name if not name.startswith("시간대") else "시간대 효과(IS 최고 4개 시간대만 보유)", cost)
                per.setdefault(key, {})[coin] = (run_positions(df, pos, cost), [])
            for name, (sl, rrs, ts) in BRACKETS.items():
                for rr in rrs:
                    tr = run_bracket(df, sig[name], sl, rr, time_stop=ts, cost=cost, fund_per_bar=0.0)
                    key = (f"{name} · 손절 {sl:g}ATR · 익절 {rr:g}R", cost)
                    per.setdefault(key, {})[coin] = (trades_to_returns(tr, df), tr)
    rows = []
    for (name, cost), coins in per.items():
        is_bracket = any(tr for _, tr in coins.values()) or "익절" in name
        daily = {k: to_daily(r) for k, (r, _) in coins.items()}
        frame = pd.DataFrame(daily).fillna(0.0)
        port = frame.sum(axis=1) if is_bracket else frame.mean(axis=1)
        trades = [t for _, tr in coins.values() for t in tr]
        oos_pos = sum(1 for k, d in daily.items() if (1 + d[d.index >= cut]).prod() > 1)
        rows.append({
            "strategy": name, "cost": cost,
            "IS": stats(port[port.index < cut], [t for t in trades if t.exit_date < cut] if is_bracket else None),
            "OOS": stats(port[port.index >= cut], [t for t in trades if t.exit_date >= cut] if is_bracket else None),
            "OOS 플러스 코인": f"{oos_pos}/{len(daily)}",
        })
    return rows, cut


def report(rows: list[dict], cut: pd.Timestamp, data: dict[str, pd.DataFrame]) -> str:
    def f(v, pct=True):
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return "   –  "
        return f"{v * 100:+6.1f}%" if pct else f"{v:5.2f}"

    span = ", ".join(f"{k} {df.index[0]:%Y-%m-%d}~{df.index[-1]:%m-%d}({len(df)}봉)" for k, df in data.items() if len(df))
    lines = ["[빗썸 1시간 봉 차트 매매] 현물·롱만. 6개 코인 동시 운용 결과",
             f"데이터: {span}",
             f"IS = ~{cut:%Y-%m-%d}, OOS = {cut:%Y-%m-%d}~. 같은 봉 손절·익절이면 손절 먼저.", ""]
    for cost in COSTS:
        lines.append(f"== 비용 편도 {cost * 100:.2f}% ==")
        lines.append("  {:<44} | {:>7} {:>5} | {:>7} {:>5} {:>7} {:>5} {:>6} {:>6} {:>6} {:>5}".format(
            "전략", "IS연", "IS샤프", "OOS연", "샤프", "낙폭", "거래", "승률", "기대R", "플러스", "레버"))
        for r in rows:
            if r["cost"] != cost:
                continue
            i, o = r["IS"], r["OOS"]
            lines.append("  {:<44} | {} {} | {} {} {} {:>5} {} {} {:>6} {}".format(
                r["strategy"][:44], f(i.get("CAGR")), f(i.get("샤프"), False), f(o.get("CAGR")),
                f(o.get("샤프"), False), f(o.get("MDD")), o.get("거래", "–"), f(o.get("승률")),
                f(o.get("기대값R"), False), r["OOS 플러스 코인"], f(o.get("허용 레버리지(−33%)"), False)))
        lines.append("")
    n = len(rows)
    yrs = max((max(df.index[-1] for df in data.values()) - cut).days / 365, 0.5)
    base = {r["cost"]: r["OOS"].get("샤프", 0) for r in rows if r["strategy"] == "보유(기준선)"}
    for cost in COSTS:
        cand = [r for r in rows if r["cost"] == cost and r["strategy"] != "보유(기준선)"
                and r["IS"].get("샤프", -9) > 0 and r["OOS"].get("샤프", -9) > max(base.get(cost, 0), 0)]
        lines.append(f"비용 {cost * 100:.2f}%: IS 플러스이고 OOS 샤프가 보유보다 높은 전략 = "
                     + (", ".join(r["strategy"] for r in cand) or "없음"))
    lines.append(f"시험한 전략×비용 {n}개, OOS {yrs:.1f}년 → 실력 없이 우연히 나올 만한 최고 OOS 샤프 ≈ {luck_sharpe(n, yrs):.2f}")
    lines.append("플러스 = OOS에서 수익이 난 코인 수, 레버 = −33% 낙폭까지 견딜 수 있는 대략의 배율(현물이라 1배 이상은 의미 없음).")
    return "\n".join(lines)
