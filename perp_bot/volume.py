"""거래량 신호 사건 분석: '거래량은 터졌는데 가격은 아직 안 오른 코인'이 그 뒤 시장보다 더 오르는가?

결과를 보기 전에 사건 정의·숫자를 모두 아래에 고정해 두고, 전부 보고한다.

- 데이터: 빗썸 원화 마켓 전체 코인의 일봉(시가·고가·저가·종가·원화 거래대금).
  지금 상장된 코인만 있다(상장폐지 코인 빠짐 → 결과가 실제보다 좋게 나온다).
- 대상: 상장 후 60일이 지났고, 최근 30일 거래대금 중앙값이 1억 원 이상인 코인-날짜만.
- 사건은 그날 종가까지의 정보로만 판단 → 다음 날 시가에 사서 h일 뒤 종가까지(h = 1, 3, 7, 14).
- '초과수익' = 그 코인의 수익 − 같은 기간 대상 코인 전체 평균 수익(시장 전체가 오른 효과를 뺀다).
- 같은 날 사건이 여러 코인에서 나면 서로 비슷하게 움직이므로, 날짜별 평균을 먼저 낸 뒤 날짜들로 평균·t값을 계산한다.
  보유 기간이 겹치는 만큼 t값을 √h로 나눠 보수적으로 줄였다. 사건 36개×기간이라 |t| ≥ 3 정도는 돼야 의미 있다.
- 실제 매매 기준 '순수익' = 그 코인의 수익 − 왕복 비용 0.5%(알트 수수료+미끄러짐).
- 검증: 2023년까지 = 고르는 기간(IS), 2024년부터 = 평가 기간(OOS).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

SPLIT = pd.Timestamp("2024-01-01")
HORIZONS = (1, 3, 7, 14)
ROUND_TRIP = 0.005
MIN_VALUE = 1e8
MIN_AGE = 60


def load(workers: int = 4) -> dict[str, pd.DataFrame]:
    from concurrent.futures import ThreadPoolExecutor

    from . import bithumb

    names = bithumb.markets()

    def one(k):
        try:
            return k, bithumb.daily(k)
        except Exception:
            return k, None

    with ThreadPoolExecutor(workers) as ex:
        return {k: df for k, df in ex.map(one, names) if df is not None and len(df) > MIN_AGE + 30}


def panel(data: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    idx = pd.date_range(min(d.index[0] for d in data.values()), max(d.index[-1] for d in data.values()), freq="D")
    return {f: pd.DataFrame({k: d[f] for k, d in data.items()}).reindex(idx)
            for f in ("open", "high", "low", "close", "value")}


def events(p: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """반환: (사건 이름 → 참/거짓 표, 대상 여부 표). 모두 그날 종가까지의 정보만 쓴다."""
    o, h, l, c, v = p["open"], p["high"], p["low"], p["close"], p["value"]
    age = c.notna().cumsum()
    med30 = v.shift(1).rolling(30, min_periods=20).median()
    ok = (age > MIN_AGE) & (med30 >= MIN_VALUE) & c.notna() & o.notna()
    rvol = v / med30
    ret1 = c / c.shift(1) - 1
    ret3 = c / c.shift(3) - 1
    rvol3 = (v.rolling(3).mean()) / med30
    s50 = c.rolling(50, min_periods=50).mean()
    lo30, hi30 = l.rolling(30).min(), h.rolling(30).max()
    pos30 = (c - lo30) / (hi30 - lo30)
    close_pos = (c - l) / (h - l)
    obv = (np.sign(c.diff()).fillna(0) * v).cumsum()
    obv_up = obv - obv.shift(20) > 0
    flat = ret1.abs() <= 0.02
    e1 = (rvol >= 3) & flat
    ev = {
        "E1 거래대금 3배 + 가격 ±2% 이내(아이디어 그대로)": e1,
        "E2 거래대금 5배 + 가격 ±3% 이내": (rvol >= 5) & (ret1.abs() <= 0.03),
        "E3 3일 연속 평균 2배 + 3일 가격 ±3% 이내(조용한 매집)": (rvol3 >= 2) & (ret3.abs() <= 0.03),
        "E4 E1 + 50일선 위(상승 추세 속 매집)": e1 & (c > s50),
        "E5 E1 + 30일 범위 하단 30%(바닥권 매집)": e1 & (pos30 <= 0.3),
        "E6 E1 + 종가가 하루 범위 상단 30%(매수 우위)": e1 & (close_pos >= 0.7),
        "E7 OBV 20일 상승 + 가격 20일 하락(거래량 다이버전스)": obv_up & (c / c.shift(20) - 1 <= 0),
        "비교: 거래대금 3배 + 이미 +10% 급등(추격 매수)": (rvol >= 3) & (ret1 >= 0.10),
        "비교: 거래대금 3배 + −10% 급락(투매 받기)": (rvol >= 3) & (ret1 <= -0.10),
    }
    return {k: (e & ok).fillna(False) for k, e in ev.items()}, ok.fillna(False)


def forward(p: dict[str, pd.DataFrame], ok: pd.DataFrame, h: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """다음 날 시가에 사서 h일째 종가까지의 수익과, 시장(대상 코인 평균) 대비 초과수익."""
    fwd = p["close"].shift(-h) / p["open"].shift(-1) - 1
    fwd = fwd.where(ok)
    mkt = fwd.mean(axis=1)
    return fwd, fwd.sub(mkt, axis=0)


def summarize(mask: pd.DataFrame, fwd: pd.DataFrame, abn: pd.DataFrame, h: int) -> dict:
    m = mask & fwd.notna()
    n = int(m.values.sum())
    if n < 10:
        return {"n": n}
    per_date = abn.where(m).mean(axis=1).dropna()
    raw = fwd.where(m).stack().dropna()
    a = abn.where(m).stack().dropna()
    t = per_date.mean() / per_date.std(ddof=1) * math.sqrt(len(per_date)) / math.sqrt(h) if len(per_date) > 2 else float("nan")
    return {"n": n, "날짜": len(per_date), "초과": float(per_date.mean()), "t": float(t),
            "적중": float((a > 0).mean()), "순수익": float(raw.mean() - ROUND_TRIP),
            "순수익 중앙": float(raw.median() - ROUND_TRIP)}


def run_all(data: dict[str, pd.DataFrame]) -> list[dict]:
    p = panel(data)
    ev, ok = events(p)
    rows = []
    for h in HORIZONS:
        fwd, abn = forward(p, ok, h)
        is_, oos = fwd.index < SPLIT, fwd.index >= SPLIT
        for name, mask in {"전체(기준선: 대상 코인 아무 날)": ok, **ev}.items():
            rows.append({"event": name, "h": h,
                         "IS": summarize(mask[is_], fwd[is_], abn[is_], h),
                         "OOS": summarize(mask[oos], fwd[oos], abn[oos], h)})
    return rows


def report(rows: list[dict], data: dict[str, pd.DataFrame]) -> str:
    def pct(v):
        return "    –  " if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v * 100:+6.2f}%"

    def num(v, fmt="{:5.1f}"):
        return "   – " if v is None or (isinstance(v, float) and math.isnan(v)) else fmt.format(v)

    first = pd.Series({k: d.index[0] for k, d in data.items()})
    lines = ["[빗썸 거래량 신호 사건 분석] 다음 날 시가 매수 → h일 뒤 종가. 초과 = 시장 평균 대비",
             f"코인 {len(data)}개, {first.min():%Y-%m-%d} ~ {max(d.index[-1] for d in data.values()):%Y-%m-%d}. "
             "지금 상장된 코인만(상장폐지 빠짐 → 좋게 나옴). IS = ~2023년, OOS = 2024년~",
             "", "  {:<46} {:>3} | {:>6} {:>8} {:>5} {:>6} | {:>6} {:>8} {:>5} {:>6} {:>8} {:>8}".format(
                 "사건", "h일", "IS건수", "IS초과", "IS t", "IS적중", "OOS건수", "OOS초과", "t", "적중", "순수익", "순중앙")]
    for r in rows:
        i, o = r["IS"], r["OOS"]
        lines.append("  {:<46} {:>3} | {:>6} {} {} {} | {:>6} {} {} {} {} {}".format(
            r["event"][:46], r["h"], i.get("n", 0), pct(i.get("초과")), num(i.get("t")), pct(i.get("적중")),
            o.get("n", 0), pct(o.get("초과")), num(o.get("t")), pct(o.get("적중")), pct(o.get("순수익")),
            pct(o.get("순수익 중앙"))))
    good = [f"{r['event']}({r['h']}일)" for r in rows if not r["event"].startswith(("전체", "비교"))
            and r["IS"].get("t", 0) >= 2 and r["OOS"].get("t", 0) >= 2 and r["OOS"].get("순수익", -1) > 0]
    lines += ["", "초과 = 날짜별 평균 초과수익의 평균, t = 보유 기간 겹침을 보정한 t값, 적중 = 시장보다 더 오른 비율,",
              "순수익 = 그 코인 수익 평균 − 왕복 0.5%, 순중앙 = 같은 값의 중앙값(소수 대박에 끌려가지 않은 '보통' 결과).",
              "IS·OOS 모두 t ≥ 2이고 OOS 순수익이 플러스인 사건: " + (", ".join(good) or "없음")]
    return "\n".join(lines)
