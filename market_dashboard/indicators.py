"""시황에서 매일 추적할 지표 고르기: 어떤 지표가 '그다음 시장'에 대해 실제로 정보를 줬나(백테스트).

결과를 보기 전에 지표·구간·판정 기준을 아래에 고정하고 전부 보고한다.

- 매달 말 지표 값으로 상태를 나눈다.
  · 예/아니오 지표(추세·역전 등): 그 조건이 맞는 달 vs 아닌 달
  · 연속 지표(VIX·스프레드 등): 그때까지의 과거 값만으로 매긴 백분위(미래 정보 없음, 최소 36개월 쌓인 뒤부터)로
    상위 1/3 vs 하위 1/3
- 그 뒤 시장(미국 = S&P500, 한국 = 코스피)의 성적을 잰다.
  · 수익: 다음 1·3·6·12개월 수익 평균의 차이와 t값(기간이 겹치는 만큼 √기간으로 나눠 보수적으로)
  · 위험: 다음 6개월 안에 −10% 이상 빠진 적이 있는 비율, 다음 1개월 변동성(연율)
- 기간을 반으로 나눠(미국 ~2007 / 2008~, 한국 지수 ~2009 / 2010~, 한국 스냅숏 ~2017 / 2018~) 두 기간 모두에서
  같은 방향이면 '오래 통한 지표'로 본다. 지표 15개 × 기간 4개를 봤으니 t 하나만 크다고 믿지 않는다.
- 거시 지표(실업률)는 발표가 늦으므로 한 달 늦춰 쓴다. 스프레드·금리차·VIX는 그달 마지막 값.
"""
from __future__ import annotations

import io
import logging
import math
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

START = "1990-01-01"
HORIZONS = (1, 3, 6, 12)
DD_MONTHS, DD_LEVEL = 6, -0.10
MIN_HISTORY = 36
SECTORS9 = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]   # 1998년 말부터 있는 섹터 ETF
YAHOO = ["^GSPC", "^VIX", "^KS11", "KRW=X"] + SECTORS9
FRED = ["T10Y3M", "BAA10Y", "UNRATE"]   # 하이일드 스프레드(ICE)는 FRED가 최근 3년만 줘서 Baa−10년물로 대신


@dataclass(frozen=True)
class Spec:
    key: str
    name: str
    market: str          # "US" | "KR"
    kind: str            # "flag" | "level"
    good: str            # 사람이 읽는 '좋은 쪽' 설명(예측 방향은 결과로 판단)
    split: str           # IS/OOS 나누는 날짜


SPECS = [
    Spec("us_trend", "S&P500이 10개월 평균 위", "US", "flag", "위", "2008-01-01"),
    Spec("us_mom12", "S&P500 12개월 수익 플러스", "US", "flag", "플러스", "2008-01-01"),
    Spec("us_dd52", "S&P500 52주 고점 대비 낙폭", "US", "level", "낙폭 큼(상위 1/3)", "2008-01-01"),
    Spec("vix", "VIX(변동성 지수)", "US", "level", "높음(상위 1/3)", "2008-01-01"),
    Spec("curve", "장단기 금리차(10년−3개월) 역전", "US", "flag", "역전", "2008-01-01"),
    Spec("hy", "신용 스프레드(Baa 회사채−10년물)", "US", "level", "높음(상위 1/3)", "2008-01-01"),
    Spec("hy_chg", "신용 스프레드 3개월 변화", "US", "level", "확대(상위 1/3)", "2008-01-01"),
    Spec("unrate", "실업률이 12개월 평균 위(한 달 늦춤)", "US", "flag", "위", "2008-01-01"),
    Spec("us_breadth", "미국 섹터 9개 중 10개월 평균 위 비율", "US", "level", "높음(상위 1/3)", "2008-01-01"),
    Spec("kr_trend", "코스피가 10개월 평균 위", "KR", "flag", "위", "2010-01-01"),
    Spec("kr_mom12", "코스피 12개월 수익 플러스", "KR", "flag", "플러스", "2010-01-01"),
    Spec("krw3", "원/달러 환율 3개월 변화", "KR", "level", "원화 약세(상위 1/3)", "2010-01-01"),
    Spec("us_to_kr", "S&P500이 10개월 평균 위 → 코스피", "KR", "flag", "위", "2010-01-01"),
    Spec("kr_breadth", "상위 500종목 중 10개월 평균 위 비율", "KR", "level", "높음(상위 1/3)", "2018-01-01"),
    Spec("kr_pbr", "시장 PBR(상위 500, 시총 가중)", "KR", "level", "높음(상위 1/3)", "2018-01-01"),
    Spec("kr_div", "시장 배당수익률(상위 500, 시총 가중)", "KR", "level", "높음(상위 1/3)", "2018-01-01"),
    Spec("kr_foreign", "외국인 20일 순매수 ÷ 시총(상위 500)", "KR", "level", "많이 삼(상위 1/3)", "2018-01-01"),
]


# ---------------- 데이터 ----------------
def fetch(cache_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(일별 종가, 월별 FRED). 실패하면 저장본."""
    path = cache_dir / "indicators_raw.pkl"
    try:
        import yfinance as yf

        px = yf.download(YAHOO, start=START, auto_adjust=True, progress=False, threads=True)["Close"]
        px.index = pd.to_datetime(px.index).tz_localize(None)
        frames = []
        for sid in FRED:
            url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={START}"
            with urllib.request.urlopen(url, timeout=60) as r:
                frames.append(pd.read_csv(io.BytesIO(r.read()), index_col=0, parse_dates=True, na_values="."))
        fred = pd.concat(frames, axis=1).sort_index()
        cache_dir.mkdir(parents=True, exist_ok=True)
        pd.to_pickle((px, fred), path)
        return px, fred
    except Exception as e:
        if path.exists():
            log.warning("지표 데이터 받기 실패(%s), 저장본 사용", e)
            return pd.read_pickle(path)
        raise


def month_end(s: pd.Series | pd.DataFrame):
    return s.resample("ME").last()


def snapshot_signals(snaps: dict) -> pd.DataFrame:
    """한국거래소 월말 스냅숏(kr_factors)으로 만든 시장 지표(생존 편향 없음)."""
    from . import kr_factors

    p = kr_factors.panel(snaps)
    uni = kr_factors.universe(p)
    px, sh = p["종가"], p["상장주식수"]
    ratio = sh / sh.shift(1)
    adj = ratio.where((ratio > 1.5) | (ratio < 0.67), 1.0).fillna(1.0).cumprod()
    tr = px * adj
    above = (tr > tr.rolling(10, min_periods=10).mean()).where(tr.rolling(10, min_periods=10).mean().notna())
    cap = p["시가총액"].where(uni)
    pbr = p["PBR"].where(p["PBR"] > 0)
    out = pd.DataFrame({
        "kr_breadth": above.where(uni).mean(axis=1),
        "kr_pbr": cap.sum(axis=1) / (cap / pbr).sum(axis=1),
        "kr_div": (cap * p["DIV"].fillna(0)).sum(axis=1) / cap.sum(axis=1),
        "kr_foreign": p["외국인순매수"].where(uni).sum(axis=1) / cap.sum(axis=1),
    })
    out.index = out.index.to_period("M").to_timestamp("M")
    return out


def signals(px: pd.DataFrame, fred: pd.DataFrame, snap: pd.DataFrame | None = None) -> pd.DataFrame:
    """월말(행) × 지표(열)."""
    m = month_end(px)
    spx, ks = m["^GSPC"], m["^KS11"]
    d_spx = px["^GSPC"].dropna()
    hi52 = month_end(d_spx.rolling(252, min_periods=200).max())
    f = month_end(fred.ffill())
    unrate = f["UNRATE"]
    sec = m[[c for c in SECTORS9 if c in m]]
    sec_ok = sec.notna().sum(axis=1) >= 9
    out = pd.DataFrame({
        "us_trend": (spx > spx.rolling(10).mean()).where(spx.rolling(10).mean().notna()),
        "us_mom12": (spx / spx.shift(12) > 1).where(spx.shift(12).notna()),
        "us_dd52": -(month_end(d_spx) / hi52 - 1),
        "vix": m["^VIX"],
        "curve": (f["T10Y3M"] < 0).where(f["T10Y3M"].notna()),
        "hy": f["BAA10Y"],
        "hy_chg": f["BAA10Y"] - f["BAA10Y"].shift(3),
        "unrate": (unrate > unrate.rolling(12).mean()).where(unrate.rolling(12).mean().notna()).shift(1),
        "us_breadth": (sec > sec.rolling(10, min_periods=10).mean()).where(sec.rolling(10, min_periods=10).mean().notna())
        .mean(axis=1).where(sec_ok & sec.rolling(10, min_periods=10).mean().notna().all(axis=1)),
        "kr_trend": (ks > ks.rolling(10).mean()).where(ks.rolling(10).mean().notna()),
        "kr_mom12": (ks / ks.shift(12) > 1).where(ks.shift(12).notna()),
        "krw3": m["KRW=X"] / m["KRW=X"].shift(3) - 1,
    })
    out["us_to_kr"] = out["us_trend"]
    if snap is not None and len(snap):
        out = out.join(snap, how="left")
    return out


# ---------------- 그다음 시장 ----------------
def outcomes(daily: pd.Series) -> pd.DataFrame:
    """월말마다: 다음 h개월 수익, 다음 6개월 안 최저점(−10% 이상 빠졌나), 다음 1개월 변동성."""
    daily = daily.dropna()
    m = month_end(daily).dropna()
    out = pd.DataFrame({f"r{h}": m.shift(-h) / m - 1 for h in HORIZONS})
    idx, vals = daily.index.values, daily.to_numpy(float)
    lr = np.diff(np.log(vals), prepend=np.nan)
    dd, vol = [], []
    for t, v in m.items():
        i0 = np.searchsorted(idx, np.datetime64(t), side="right")
        i6 = np.searchsorted(idx, np.datetime64(t + pd.DateOffset(months=DD_MONTHS)), side="right")
        i1 = np.searchsorted(idx, np.datetime64(t + pd.DateOffset(months=1)), side="right")
        complete = i6 < len(idx)          # 6개월이 다 지나야 판정
        dd.append(float(vals[i0:i6].min() / v - 1 <= DD_LEVEL) if complete and i6 > i0 else np.nan)
        vol.append(float(np.nanstd(lr[i0:i1], ddof=1) * math.sqrt(252)) if i1 - i0 > 15 and i1 < len(idx) else np.nan)
    out["dd"] = dd
    out["vol"] = vol
    return out


def expanding_rank(s: pd.Series) -> pd.Series:
    """그때까지의 값만으로 매긴 백분위(0~1)."""
    vals, out = [], []
    for v in s:
        if np.isnan(v):
            out.append(np.nan)
            continue
        vals.append(v)
        out.append(np.mean(np.array(vals) <= v) if len(vals) >= MIN_HISTORY else np.nan)
    return pd.Series(out, index=s.index)


def states(spec: Spec, sig: pd.Series) -> pd.Series:
    """1 = '좋은 쪽' 설명에 해당(조건 참·상위 1/3), 0 = 반대(조건 거짓·하위 1/3), NaN = 가운데·데이터 없음."""
    if spec.kind == "flag":
        return sig.astype(float)
    r = expanding_rank(sig.astype(float))
    return pd.Series(np.where(r >= 2 / 3, 1.0, np.where(r <= 1 / 3, 0.0, np.nan)), index=sig.index).where(r.notna())


def _t(a: pd.Series, b: pd.Series, h: int) -> float:
    a, b = a.dropna(), b.dropna()
    if len(a) < 6 or len(b) < 6:
        return float("nan")
    se = math.sqrt(a.var() / len(a) + b.var() / len(b))
    return float((a.mean() - b.mean()) / se / math.sqrt(h)) if se > 0 else float("nan")


def compare(st: pd.Series, oc: pd.DataFrame) -> dict:
    d = oc.join(st.rename("s"), how="inner").dropna(subset=["s"])
    on, off = d[d["s"] == 1], d[d["s"] == 0]
    row = {"n_on": int(len(on)), "n_off": int(len(off))}
    for h in HORIZONS:
        k = f"r{h}"
        row[k] = (on[k].mean(), off[k].mean(), _t(on[k], off[k], h))
    row["dd"] = (on["dd"].mean(), off["dd"].mean())
    row["vol"] = (on["vol"].mean(), off["vol"].mean(), _t(on["vol"], off["vol"], 1))
    return row


def run(px: pd.DataFrame, fred: pd.DataFrame, snap: pd.DataFrame | None = None) -> list[dict]:
    sig = signals(px, fred, snap)
    target = {"US": outcomes(px["^GSPC"]), "KR": outcomes(px["^KS11"])}
    res = []
    for spec in SPECS:
        if spec.key not in sig or sig[spec.key].notna().sum() < 48:
            res.append({"spec": spec, "missing": True})
            continue
        st = states(spec, sig[spec.key])
        oc = target[spec.market]
        split = pd.Timestamp(spec.split)
        res.append({"spec": spec, "all": compare(st, oc), "IS": compare(st[st.index < split], oc),
                    "OOS": compare(st[st.index >= split], oc), "start": sig[spec.key].first_valid_index(),
                    "now": _now(spec, sig[spec.key], st)})
    return res


def _now(spec: Spec, s: pd.Series, st: pd.Series) -> str:
    s = s.dropna()
    if not len(s):
        return "–"
    v = s.iloc[-1]
    if spec.kind == "flag":
        return "예" if v else "아니오"
    state = st.dropna()
    tag = {1.0: "상위 1/3", 0.0: "하위 1/3"}.get(state.iloc[-1] if len(state) and state.index[-1] == s.index[-1] else -1, "가운데")
    return f"{v:.3g} ({tag})"


# ---------------- 판정·보고 ----------------
def verdict(r: dict) -> tuple[str, str]:
    """(판정, 이유). 두 기간 모두 같은 방향이고 효과가 어느 정도 클 때만 '추적 추천'."""
    if r.get("missing"):
        return "데이터 없음", ""
    reasons = []
    ret_ok = False
    for h in (6, 12):
        a, b = r["IS"][f"r{h}"], r["OOS"][f"r{h}"]
        da, db = a[0] - a[1], b[0] - b[1]
        if np.sign(da) == np.sign(db) and abs(r["all"][f"r{h}"][2]) >= 2 and min(abs(da), abs(db)) >= 0.02:
            ret_ok = True
            reasons.append(f"{h}개월 뒤 수익 차이가 두 기간 모두 {'+' if da > 0 else '−'}쪽")
    dd_ok = vol_ok = False
    a, b = r["IS"]["dd"], r["OOS"]["dd"]
    if all(not np.isnan(x) for x in (*a, *b)):
        da, db = a[0] - a[1], b[0] - b[1]
        if np.sign(da) == np.sign(db) and min(abs(da), abs(db)) >= 0.10:
            dd_ok = True
            reasons.append(f"6개월 안 −10% 하락 확률이 두 기간 모두 {'높음' if da > 0 else '낮음'}")
    a, b = r["IS"]["vol"], r["OOS"]["vol"]
    if np.sign(a[0] - a[1]) == np.sign(b[0] - b[1]) and abs(r["all"]["vol"][2]) >= 2 \
            and min(abs(a[0] - a[1]), abs(b[0] - b[1])) >= 0.03:
        vol_ok = True
        reasons.append(f"다음 달 변동성이 두 기간 모두 {'높음' if a[0] > a[1] else '낮음'}")
    # 변동성은 원래 다음 달로 이어지므로(변동성 지속) 변동성 차이만으로는 추천하지 않는다
    if ret_ok and dd_ok:
        return "추적 추천(수익·하락 위험 모두)", "; ".join(reasons)
    if dd_ok:
        return "추적 추천(하락 위험 신호)", "; ".join(reasons)
    if ret_ok:
        return "추적 추천(수익 차이)", "; ".join(reasons)
    if vol_ok:
        return "참고(변동성만 — 원래 이어지는 성질)", "; ".join(reasons)
    return "뺌(일관된 효과 없음)", ""


def report(res: list[dict]) -> str:
    def pct(v, nd=1):
        return "  –  " if v is None or (isinstance(v, float) and np.isnan(v)) else f"{v * 100:+.{nd}f}%"

    lines = ["[시황 지표 고르기] 지표 상태별로 그다음 시장(미국 S&P500 / 한국 코스피)이 어땠나",
             "'좋은 쪽' = 표의 설명에 해당하는 달(조건 참 또는 그때까지 과거 값 기준 상위 1/3), '반대' = 조건 거짓 또는 하위 1/3.",
             "t = 두 상태의 평균 차이 t값(기간 겹침만큼 √기간으로 나눔). 지표 17개 × 기간 4개를 봤으니 |t| 2.5~3 이상이어야 우연을 넘는다.",
             ""]
    for r in res:
        s = r["spec"]
        if r.get("missing"):
            lines.append(f"■ {s.name} [{s.market}] — 데이터 없음")
            continue
        v, why = verdict(r)
        lines.append(f"■ {s.name} [{s.market}] '좋은 쪽' = {s.good} · {r['start']:%Y-%m}~ · 지금: {r['now']}")
        lines.append(f"   판정: {v}" + (f" — {why}" if why else ""))
        for tag in ("IS", "OOS", "all"):
            c = r[tag]
            label = {"IS": f"~{s.split[:4]}", "OOS": f"{s.split[:4]}~", "all": "전체"}[tag]
            rets = "  ".join(f"{h}개월 {pct(c[f'r{h}'][0])}/{pct(c[f'r{h}'][1])} t{c[f'r{h}'][2]:+.1f}" for h in HORIZONS)
            lines.append(f"   {label:<7} (n {c['n_on']}/{c['n_off']})  {rets}  | 6개월 내 −10%: {pct(c['dd'][0], 0)}/{pct(c['dd'][1], 0)}"
                         f"  | 다음달 변동성: {pct(c['vol'][0], 0)}/{pct(c['vol'][1], 0)}")
        lines.append("")
    keep = [r for r in res if not r.get("missing") and verdict(r)[0].startswith("추적")]
    lines.append("== 추적 추천 ==")
    lines += [f"  - {r['spec'].name} [{r['spec'].market}]: {verdict(r)[0]} — {verdict(r)[1]}" for r in keep] or ["  (없음)"]
    return "\n".join(lines)
