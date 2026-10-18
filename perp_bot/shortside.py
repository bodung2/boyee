"""빗썸 거래량 신호로 Hyperliquid 무기한 선물 '숏'을 치면 어떨까? (검증만, 주문 없음)

결과를 보기 전에 규칙·숫자를 모두 아래에 고정해 두고, 전부 보고한다.

- 신호: 빗썸 일봉(한국 시간 하루)에서 앞선 거래량 분석(volume.py)과 같은 사건. 빗썸 하루는 UTC 15시에 끝난다.
- 매매: Hyperliquid에 같은 코인이 있으면(이름이 같거나 k 접두어: kPEPE 등), 신호 다음 UTC 날짜의
  Hyperliquid 일봉 시가(= 신호 9시간 뒤)에 숏 → h일째 일봉 종가에 청산(h = 1, 3, 7).
- 방식 3가지:
  · 맨숏: 그 코인만 숏
  · 맨숏 + 손절 15%: 보유 중 일봉 고가가 진입가 +15%에 닿으면 그 값에서 손절(갭이면 시가)
  · BTC 헤지: 그 코인 숏 + 같은 금액 BTC 롱(시장 전체 등락을 지운다)
- 비용: 왕복 0.3%(수수료 0.045%×2 + 알트 미끄러짐), 헤지는 BTC 왕복 0.12% 추가.
- 펀딩비는 본 계산에 넣지 않았다. 사건별로 일부(최대 60건)만 실제 펀딩을 받아 '숏이 받은 펀딩'을 따로 보고한다.
- 같은 날 여러 코인 신호는 서로 닮았으니 날짜별 평균 → 날짜들로 t값(보유 기간 겹침만큼 √h로 나눔).
- 빗썸 쪽은 지금 상장된 코인만, Hyperliquid 쪽은 상장폐지 코인도 포함(meta 목록 기준).
- 기간: Hyperliquid 데이터가 있는 기간 전체(2023~). 이 기간 대부분이 거래량 분석의 '평가 기간'과 겹친다.
  안정성을 보려고 앞 절반 / 뒤 절반으로도 나눠 보고한다.
"""
from __future__ import annotations

import logging
import math
import random
import time

import numpy as np
import pandas as pd

from . import hl

log = logging.getLogger(__name__)
HORIZONS = (1, 3, 7)
COST, HEDGE_COST, STOP = 0.003, 0.0012, 0.15
SIGNALS = {
    "S1 거래량 3배 + 이미 +10% 급등": "비교: 거래대금 3배 + 이미 +10% 급등(추격 매수)",
    "S2 거래량 3배 + −10% 급락": "비교: 거래대금 3배 + −10% 급락(투매 받기)",
    "S3 거래량 5배 + 가격 ±3%": "E2 거래대금 5배 + 가격 ±3% 이내",
    "S4 거래량 3배 + 가격 ±2%": "E1 거래대금 3배 + 가격 ±2% 이내(아이디어 그대로)",
}


def _retry(fn, tries: int = 5):
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            if i == tries - 1:
                raise
            log.warning("Hyperliquid 재시도(%s)", e)
            time.sleep(5 * (i + 1))


def hl_names() -> list[str]:
    meta = _retry(lambda: hl._post({"type": "meta"}))
    return [u["name"] for u in meta["universe"]]


def match(bithumb_coins, names) -> dict[str, str]:
    s = set(names)
    out = {}
    for k in bithumb_coins:
        if k in s:
            out[k] = k
        elif "k" + k in s:
            out[k] = "k" + k
    return out


def load_hl(mapping: dict[str, str], pause: float = 0.6) -> dict[str, pd.DataFrame]:
    out = {}
    for b, h in mapping.items():
        try:
            df = _retry(lambda: hl.candles(h, "1d", days=1400))
        except Exception as e:
            log.warning("%s 일봉 못 받음: %s", h, e)
            continue
        time.sleep(pause)
        if len(df):
            df.index = df.index.tz_localize(None).normalize()
            out[b] = df
    return out


def trades(ev: pd.DataFrame, hld: dict[str, pd.DataFrame], btc: pd.DataFrame, h: int) -> pd.DataFrame:
    """사건 표(빗썸 날짜 × 코인) → 거래 목록. 빗썸 날짜 d의 신호 → HL UTC 날짜 d+1 시가 진입."""
    rows = []
    for coin in ev.columns:
        if coin not in hld:
            continue
        df = hld[coin]
        for d in ev.index[ev[coin].to_numpy()]:
            start, end = d + pd.Timedelta(days=1), d + pd.Timedelta(days=h)
            win = df.loc[start:end]
            if len(win) < h or win.index[0] != start:
                continue
            e, x = win["open"].iloc[0], win["close"].iloc[-1]
            naked = -(x / e - 1)
            stopped = naked
            lvl = e * (1 + STOP)
            for t, bar in win.iterrows():
                if t > start and bar["open"] >= lvl:
                    stopped = -(bar["open"] / e - 1)
                    break
                if bar["high"] >= lvl:
                    stopped = -STOP
                    break
            bw = btc.loc[start:end]
            hedge = naked + (bw["close"].iloc[-1] / bw["open"].iloc[0] - 1) if len(bw) == len(win) else np.nan
            rows.append({"date": d, "coin": coin, "맨숏": naked - COST, "맨숏+손절15%": stopped - COST,
                         "BTC 헤지": hedge - COST - HEDGE_COST})
    return pd.DataFrame(rows)


def summarize(tr: pd.DataFrame, col: str, h: int) -> dict:
    t = tr[["date", col]].dropna()
    if len(t) < 10:
        return {"n": len(t)}
    per = t.groupby("date")[col].mean()
    tstat = per.mean() / per.std(ddof=1) * math.sqrt(len(per)) / math.sqrt(h) if len(per) > 2 else float("nan")
    v = t[col]
    return {"n": len(t), "평균": float(v.mean()), "중앙": float(v.median()), "승률": float((v > 0).mean()),
            "하위5%": float(v.quantile(0.05)), "최악": float(v.min()), "t": float(tstat)}


def funding_sample(ev_trades: pd.DataFrame, mapping: dict[str, str], h: int, k: int = 60, seed: int = 0) -> float | None:
    """사건 일부의 보유 기간 동안 숏이 받은 펀딩 합계의 평균(+면 숏이 받음)."""
    if ev_trades.empty:
        return None
    rng = random.Random(seed)
    idx = list(ev_trades.index)
    rng.shuffle(idx)
    got = []
    for i in idx[:k]:
        r = ev_trades.loc[i]
        start = pd.Timestamp(r["date"]) + pd.Timedelta(days=1)
        s_ms = int(start.tz_localize("UTC").timestamp() * 1000)
        e_ms = s_ms + h * 86_400_000
        try:
            rows = _retry(lambda: hl._post({"type": "fundingHistory", "coin": mapping[r["coin"]],
                                            "startTime": s_ms, "endTime": e_ms}))
        except Exception:
            continue
        time.sleep(0.6)
        got.append(sum(float(x["fundingRate"]) for x in rows or []))
    return float(np.mean(got)) if got else None


def run(close_events: dict[str, pd.DataFrame], hld: dict[str, pd.DataFrame], btc: pd.DataFrame,
        mapping: dict[str, str], with_funding: bool = True) -> tuple[list[dict], pd.Timestamp]:
    first = min(df.index[0] for df in hld.values())
    last = max(df.index[-1] for df in hld.values())
    mid = (first + (last - first) / 2).normalize()
    rows = []
    for name, key in SIGNALS.items():
        ev = close_events[key]
        ev = ev[ev.index >= first]
        for h in HORIZONS:
            tr = trades(ev, hld, btc, h)
            fund = funding_sample(tr, mapping, h) if with_funding and h == 3 else None
            for col in ("맨숏", "맨숏+손절15%", "BTC 헤지"):
                if tr.empty:
                    rows.append({"signal": name, "h": h, "way": col, "all": {"n": 0}, "a": {}, "b": {}, "fund": None})
                    continue
                rows.append({"signal": name, "h": h, "way": col,
                             "all": summarize(tr, col, h),
                             "a": summarize(tr[tr["date"] < mid], col, h),
                             "b": summarize(tr[tr["date"] >= mid], col, h),
                             "fund": fund if col == "맨숏" else None})
    return rows, mid


def report(rows: list[dict], mid: pd.Timestamp, mapping: dict[str, str], hld: dict[str, pd.DataFrame]) -> str:
    def pct(v):
        return "    –  " if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v * 100:+6.2f}%"

    def num(v):
        return "  – " if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:4.1f}"

    first = min(df.index[0] for df in hld.values())
    lines = ["[빗썸 신호 → Hyperliquid 숏] 신호 9시간 뒤 HL 시가 진입, h일 뒤 종가 청산. 비용 왕복 0.3%(펀딩 제외)",
             f"빗썸·HL 공통 코인 {len(mapping)}개 중 일봉 받은 코인 {len(hld)}개, {first:%Y-%m-%d}~. "
             f"앞 절반 = ~{mid:%Y-%m-%d}, 뒤 절반 = {mid:%Y-%m-%d}~", "",
             "  {:<26} {:>2} {:<11} | {:>5} {:>8} {:>8} {:>6} {:>8} {:>8} {:>5} | {:>8} {:>4} | {:>8} {:>4}".format(
                 "신호", "h", "방식", "건수", "평균", "중앙", "승률", "하위5%", "최악", "t", "앞평균", "t", "뒤평균", "t")]
    for r in rows:
        a, x, y = r["all"], r["a"], r["b"]
        lines.append("  {:<26} {:>2} {:<11} | {:>5} {} {} {} {} {} {} | {} {} | {} {}".format(
            r["signal"][:26], r["h"], r["way"], a.get("n", 0), pct(a.get("평균")), pct(a.get("중앙")),
            pct(a.get("승률")), pct(a.get("하위5%")), pct(a.get("최악")), num(a.get("t")),
            pct(x.get("평균")), num(x.get("t")), pct(y.get("평균")), num(y.get("t"))))
    lines.append("")
    for r in rows:
        if r["fund"] is not None:
            lines.append(f"  {r['signal']} 3일 보유 중 숏이 받은 펀딩(표본 평균): {r['fund'] * 100:+.3f}%")
    good = [f"{r['signal']}·{r['h']}일·{r['way']}" for r in rows
            if r["all"].get("t", 0) >= 2.5 and r["a"].get("평균", -1) > 0 and r["b"].get("평균", -1) > 0
            and r["all"].get("중앙", -1) > 0]
    lines += ["", "하위5% = 가장 나쁜 5% 거래의 경계(이보다 더 잃은 거래가 5%), 최악 = 가장 크게 잃은 한 건.",
              "t ≥ 2.5 + 앞·뒤 절반 모두 평균 플러스 + 중앙값 플러스인 조합: " + (", ".join(good) or "없음")]
    return "\n".join(lines)
