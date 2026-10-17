"""자산군별 경향성과 '어느 구간에서 사면 좋았나' 분석.

각 자산을 5거래일마다 관찰해, 그 시점의 신호(사분면·추세 강도·과열 등)와 그 뒤 1개월(21거래일)·3개월(63거래일)
'현금 대비 초과수익'을 짝지어 모은다. 신호는 그날까지의 데이터로만 계산했으므로 미래 정보가 섞이지 않는다.

주의
- 3개월 수익은 관찰 간격(5일)보다 길어 표본끼리 겹친다. 그래서 t값은 겹침을 감안한 '실효 표본 수'(n×5/63)로 계산한다.
- 여러 구간을 동시에 비교하므로 t값 2 안팎은 우연일 수 있다. |t|≥3 정도부터 의미 있게 본다.
- 수익은 신호와 같은 달러 기준(환율 영향 없음)이다. 원화 투자자의 실제 결과는 환율만큼 달라진다.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import signals
from .signals import Params
from .universe import CASH_KEY, by_key

STEP = 5
HORIZONS = {"1개월": 21, "3개월": 63}
X_BINS = [-np.inf, -1.0, -0.5, 0.0, 0.5, 1.0, np.inf]
X_LABELS = ["≤ -1", "-1 ~ -0.5", "-0.5 ~ 0", "0 ~ 0.5", "0.5 ~ 1", "> 1"]


def _fwd_excess(prices: pd.DataFrame, cash: pd.Series, h: int) -> pd.DataFrame:
    lp, lc = np.log(prices), np.log(cash)
    return (lp.shift(-h) - lp).sub(lc.shift(-h) - lc, axis=0)


def panel(prices_sig: pd.DataFrame, p: Params) -> pd.DataFrame:
    """(날짜, 자산) 한 줄씩: 신호 값들 + 앞으로의 초과수익."""
    risky = [c for c in prices_sig.columns if c != CASH_KEY]
    px, cash = prices_sig[risky], prices_sig[CASH_KEY]
    sig = signals.compute(px, cash, p)
    fwd = {name: _fwd_excess(px, cash, h) for name, h in HORIZONS.items()}
    idx = px.index[::STEP]
    cross_up = (sig["x"] > 0) & (sig["x"].shift(STEP) <= 0)
    frames = []
    for k in risky:
        df = pd.DataFrame({
            "date": idx, "asset": k,
            "x": sig["x"][k].reindex(idx).to_numpy(),
            "accel": sig["accel"][k].reindex(idx).to_numpy(),
            "eligible": sig["eligible"][k].reindex(idx).to_numpy(),
            "overheat": sig["overheat"][k].reindex(idx).to_numpy(),
            "stretch": sig["stretch"][k].reindex(idx).to_numpy(),
            "cross_up": cross_up[k].reindex(idx).to_numpy(),
            **{f"f_{n}": f[k].reindex(idx).to_numpy() for n, f in fwd.items()},
        })
        frames.append(df)
    out = pd.concat(frames, ignore_index=True).dropna(subset=["x", "accel"])
    out["quadrant"] = [signals.quadrant(x, a) for x, a in zip(out["x"], out["accel"])]
    out["x_bin"] = pd.cut(out["x"], X_BINS, labels=X_LABELS)
    return out


def _stats(s: pd.Series, h: int) -> dict:
    s = s.dropna()
    n = len(s)
    if n < 10:
        return {"n": n, "mean": None, "hit": None, "t": None}
    n_eff = max(n * STEP / h, 2)
    sd = s.std()
    t = s.mean() / (sd / math.sqrt(n_eff)) if sd > 0 else None
    return {"n": n, "mean": float(np.expm1(s.mean())), "hit": float((s > 0).mean()),
            "t": None if t is None else float(t)}


def _table(df: pd.DataFrame, by: str, order: list | None = None) -> list[dict]:
    rows = []
    groups = df.groupby(by, observed=True)
    keys = order or list(groups.groups)
    for key in keys:
        if key not in groups.groups:
            continue
        g = groups.get_group(key)
        row = {"bucket": str(key)}
        for name, h in HORIZONS.items():
            row[name] = _stats(g[f"f_{name}"], h)
        rows.append(row)
    return rows


def asset_profile(prices_sig: pd.DataFrame, prices_val: pd.DataFrame, pan: pd.DataFrame) -> list[dict]:
    """자산별 성격: 변동성·최대낙폭·위기 연도 성과·S&P500과의 상관·추세 지속성."""
    meta = by_key()
    risky = [c for c in prices_sig.columns if c != CASH_KEY]
    wk = prices_sig[risky].resample("W-FRI").last().pct_change(fill_method=None)
    out = []
    for k in risky:
        p = prices_sig[k].dropna()
        if len(p) < 300:
            continue
        r = p.pct_change().dropna()
        dd = (p / p.cummax() - 1).min()
        yr = p.resample("YE").last().pct_change()
        g = pan[pan["asset"] == k]
        pos, neg = g[g["x"] > 0]["f_3개월"].dropna(), g[g["x"] <= 0]["f_3개월"].dropna()
        # 추세 지속성: 지금 추세 강도와 앞으로 3개월 초과수익의 순위 상관
        persist = g[["x", "f_3개월"]].dropna().corr(method="spearman").iloc[0, 1] if len(g) > 50 else np.nan
        val = prices_val[k].dropna()
        out.append({
            "key": k, "name": meta[k].name, "group": meta[k].group,
            "since": p.index[0].strftime("%Y"),
            "vol": float(r.std() * math.sqrt(252)),
            "mdd": float(dd),
            "y2008": _f(yr.get(pd.Timestamp("2008-12-31"))),
            "y2020": _f(yr.get(pd.Timestamp("2020-12-31"))),
            "y2022": _f(yr.get(pd.Timestamp("2022-12-31"))),
            "corr_spy": _f(wk[k].corr(wk["SPY"])) if "SPY" in wk and k != "SPY" else None,
            "persist": _f(persist),
            "hit_pos": _f((pos > 0).mean()) if len(pos) >= 10 else None,
            "hit_neg": _f((neg > 0).mean()) if len(neg) >= 10 else None,
            "mean_pos": _f(np.expm1(pos.mean())) if len(pos) >= 10 else None,
            "mean_neg": _f(np.expm1(neg.mean())) if len(neg) >= 10 else None,
            "share_pos": _f(len(pos) / max(len(pos) + len(neg), 1)),
            "krw_cagr": _f((val.iloc[-1] / val.iloc[0]) ** (365.25 / max((val.index[-1] - val.index[0]).days, 1)) - 1),
        })
    return out


def _f(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else round(v, 4)


def run(prices_sig: pd.DataFrame, prices_val: pd.DataFrame, p: Params) -> dict:
    pan = panel(prices_sig, p)
    quad_order = ["주도", "둔화", "회복", "회피"]
    per_asset_quad = {}
    for k, g in pan.groupby("asset"):
        per_asset_quad[k] = {r["bucket"]: r["3개월"] for r in _table(g, "quadrant", quad_order)}
    pos = pan[pan["x"] > 0]
    return {
        "note": "5거래일마다 관찰, 달러 기준 현금 대비 초과수익. t는 겹침을 감안한 실효 표본으로 계산(|t|≥3이면 우연일 가능성이 낮음).",
        "start": pan["date"].min().strftime("%Y-%m-%d"),
        "end": pan["date"].max().strftime("%Y-%m-%d"),
        "by_quadrant": _table(pan, "quadrant", quad_order),
        "by_x": _table(pan, "x_bin", X_LABELS),
        "eligible": _table(pan.assign(e=pan["eligible"].map({True: "편입 조건 충족", False: "미충족"})), "e",
                           ["편입 조건 충족", "미충족"]),
        "overheat_in_uptrend": _table(pos.assign(o=pos["overheat"].map({True: "과열(🔥)", False: "과열 아님"})), "o",
                                      ["과열 아님", "과열(🔥)"]),
        "accel_in_uptrend": _table(pos.assign(a=np.where(pos["accel"] >= 0, "가속(주도)", "감속(둔화)")), "a",
                                   ["가속(주도)", "감속(둔화)"]),
        "fresh_cross": _table(pos.assign(c=pos["cross_up"].map({True: "막 0을 넘음(최근 1주)", False: "이미 추세 중"})), "c",
                              ["막 0을 넘음(최근 1주)", "이미 추세 중"]),
        "per_asset_quadrant": per_asset_quad,
        "profiles": asset_profile(prices_sig, prices_val, pan),
    }


def as_text(a: dict, names: dict[str, str]) -> str:
    """실행 기록(로그)에 남길 표."""
    def fmt(s):
        if not s or s["mean"] is None:
            return f"n={s['n'] if s else 0:>5} (표본 부족)"
        t = "  –  " if s["t"] is None else f"{s['t']:+5.1f}"
        return f"n={s['n']:>5} 평균 {s['mean']*100:+6.2f}% 적중 {s['hit']*100:5.1f}% t {t}"

    lines = [f"[경향 분석] {a['start']} ~ {a['end']}", a["note"], ""]
    for title, key in [("사분면별", "by_quadrant"), ("추세 강도 구간별", "by_x"), ("편입 조건", "eligible"),
                       ("상승 추세 안에서 과열 여부", "overheat_in_uptrend"), ("상승 추세 안에서 가속/감속", "accel_in_uptrend"),
                       ("상승 추세 진입 시점", "fresh_cross")]:
        lines.append(f"== {title} ==")
        for r in a[key]:
            lines.append(f"  {r['bucket']:<22} 1개월 {fmt(r['1개월'])} | 3개월 {fmt(r['3개월'])}")
        lines.append("")
    lines.append("== 자산별 3개월 후 초과수익(평균/적중) by 사분면 ==")
    for k, q in a["per_asset_quadrant"].items():
        cells = []
        for name in ["주도", "둔화", "회복", "회피"]:
            s = q.get(name)
            cells.append(f"{name} " + ("  –   " if not s or s["mean"] is None else f"{s['mean']*100:+5.1f}%/{s['hit']*100:3.0f}%"))
        lines.append(f"  {names.get(k, k):<14} " + "  ".join(cells))
    lines.append("")
    lines.append("== 자산별 성격 ==")
    lines.append("  자산            시작  변동성  최대낙폭  2008   2020   2022  SPY상관 지속성  x>0적중 x≤0적중 x>0비중")
    def pc(v):
        return "   –  " if v is None else f"{v * 100:+5.0f}%"

    def num(v):
        return "  –  " if v is None else f"{v:+.2f}"

    for r in a["profiles"]:
        lines.append(f"  {r['name']:<14} {r['since']} {r['vol'] * 100:5.0f}% {r['mdd'] * 100:7.0f}% "
                     f"{pc(r['y2008'])} {pc(r['y2020'])} {pc(r['y2022'])} {num(r['corr_spy'])}  {num(r['persist'])}  "
                     f"{pc(r['hit_pos'])}  {pc(r['hit_neg'])}  {pc(r['share_pos'])}")
    return "\n".join(lines)
