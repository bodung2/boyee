"""한국 주식: 기준을 섞은 종목 선정 비교 + '고배당이 왜 잘됐나' 분해.

결과를 보기 전에 조합 목록·숫자를 아래에 고정해 두고 전부 보고한다(kr_factors와 같은 데이터·비용·대상).
조합 = 각 기준의 그달 순위(0~1, 좋은 쪽이 1)를 같은 비중으로 평균한 점수. 상위 20%(약 80종목)와 상위 30종목 두 가지로 담는다.
과최적화 방지: 2017년까지(IS) 성적이 가장 좋은 조합을 '미리 골랐다고 치고' 2018년~(OOS) 성적을 따로 보고한다.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import kr_factors as kf

# 기준 키 → (scores()의 키, 큰 값이 좋은가)
BASE = {
    "배당": ("div", True), "저PBR": ("pbr", False), "저PER": ("ep", True), "ROE": ("roe", True),
    "저변동": ("vol", False), "모멘텀": ("mom", True), "대형": ("cap", True),
}
COMBOS = [
    ("배당", "저PBR"), ("배당", "저변동"), ("배당", "대형"), ("배당", "저PBR", "대형"),
    ("배당", "저PBR", "저변동"), ("배당", "저PBR", "ROE"), ("저PBR", "ROE", "저변동"),
    ("저PBR", "모멘텀"), ("배당", "모멘텀"), ("배당", "저PBR", "모멘텀"), ("저PBR", "대형"),
    ("배당", "저PBR", "ROE", "저변동", "대형"), ("배당", "저PBR", "저PER", "ROE", "저변동", "모멘텀", "대형"),
]
LARGE_N = 200   # '대형주 안에서' 변형: 시가총액 상위 200개만
TOP_K = 30


def base_ranks(sc: dict[str, pd.DataFrame], uni: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {name: sc[key].where(uni).rank(axis=1, pct=True, ascending=hb) for name, (key, hb) in BASE.items()}


def combo_score(ranks: dict[str, pd.DataFrame], names: tuple[str, ...]) -> pd.DataFrame:
    frames = [ranks[n] for n in names]
    s = sum(frames) / len(frames)
    ok = frames[0].notna()
    for f in frames[1:]:
        ok &= f.notna()
    return s.where(ok)


def top_portfolio(score: pd.DataFrame, ret: pd.DataFrame, uni: pd.DataFrame, k: int | None) -> pd.Series:
    """매달 점수 상위(k개 또는 상위 20%) 같은 비중, 비용 반영 월수익."""
    out, prev, idx = [], pd.Series(dtype=float), []
    for t in ret.index[:-1]:
        s = score.loc[t].where(uni.loc[t]).dropna()
        if len(s) < 50:
            continue
        n = k or max(int(len(s) * 0.2), 10)
        names = s.sort_values(ascending=False).index[:n]
        w = pd.Series(1 / len(names), index=names)
        r = ret.loc[t, names].fillna(kf.DELIST_RET)
        turn = w.subtract(prev, fill_value=0).abs().sum()
        out.append(float((w * r).sum()) - turn * kf.COST)
        idx.append(t)
        grown = w * (1 + r)
        prev = grown / grown.sum() if grown.sum() > 0 else w
    return pd.Series(out, index=pd.DatetimeIndex(idx))


def _split(r: pd.Series) -> tuple[pd.Series, pd.Series]:
    return r[r.index < kf.SPLIT], r[r.index >= kf.SPLIT]


def run_combos(p, ret, uni, sc, market: pd.Series, k200: pd.Series | None) -> dict:
    ranks = base_ranks(sc, uni)
    large = uni & (p["시가총액"].rank(axis=1, ascending=False) <= LARGE_N)
    tests = [(" + ".join(c), combo_score(ranks, c), uni) for c in [(b,) for b in BASE] + COMBOS]
    tests += [("대형주 200 안에서 배당", combo_score(ranks, ("배당",)), large),
              ("대형주 200 안에서 배당 + 저PBR", combo_score(ranks, ("배당", "저PBR")), large),
              ("대형주 200 안에서 배당 + 저PBR + 저변동", combo_score(ranks, ("배당", "저PBR", "저변동")), large)]
    rows = []
    for name, score, u in tests:
        for size, k in (("상위20%", None), ("30종목", TOP_K)):
            r = top_portfolio(score, ret, u, k)
            a, b = _split(r)
            ex = r - market.reindex(r.index)
            ea, eb = _split(ex)
            rows.append({"name": name, "size": size, "IS": kf.stats(a), "OOS": kf.stats(b),
                         "t_is": kf.tstat(ea), "t_oos": kf.tstat(eb), "series": r})
    best = max(rows, key=lambda x: x["IS"].get("샤프", -9))
    bench = {"시장 평균": {t: kf.stats(s) for t, s in zip(("IS", "OOS"), _split(market))}}
    if k200 is not None:
        bench["KODEX 200"] = {t: kf.stats(s) for t, s in zip(("IS", "OOS"), _split(k200.reindex(market.index)))}
    return {"rows": rows, "best_is": best, "bench": bench, "n_tests": len(rows)}


# ---------------- 고배당 분해 ----------------
def _beta(q: pd.Series, mk: pd.Series) -> float:
    d = pd.concat([q, mk], axis=1).dropna()
    return float(d.iloc[:, 0].cov(d.iloc[:, 1]) / d.iloc[:, 1].var()) if len(d) > 2 and d.iloc[:, 1].var() > 0 else float("nan")


def dividend_anatomy(p, ret, uni, sc, market: pd.Series) -> dict:
    div_rank = sc["div"].where(uni).rank(axis=1, pct=True)
    q1 = (div_rank > 0.8) & uni
    price_ret = kf.monthly_returns(p, include_div=False)
    out = {}
    # 1) 수익 = 배당 + 주가
    q1_tot = ret.where(q1).mean(axis=1).iloc[:-1]
    q1_price = price_ret.where(q1).mean(axis=1).iloc[:-1]
    mk_price = price_ret.where(uni).mean(axis=1).iloc[:-1]
    yld_q1 = p["DIV"].where(q1).mean(axis=1).iloc[:-1] / 100
    yld_mk = p["DIV"].where(uni).mean(axis=1).iloc[:-1] / 100
    out["split"] = {t: {"고배당 총수익(연)": (1 + a).prod() ** (12 / len(a)) - 1,
                        "고배당 주가만(연)": (1 + b).prod() ** (12 / len(b)) - 1,
                        "시장 주가만(연)": (1 + c).prod() ** (12 / len(c)) - 1,
                        "고배당 평균 배당수익률": d.mean(), "시장 평균 배당수익률": e.mean()}
                    for t, (a, b, c, d, e) in {
                        "IS": tuple(x[x.index < kf.SPLIT] for x in (q1_tot, q1_price, mk_price, yld_q1, yld_mk)),
                        "OOS": tuple(x[x.index >= kf.SPLIT] for x in (q1_tot, q1_price, mk_price, yld_q1, yld_mk))}.items()}
    # 2) 어떤 종목인가(그달 중앙값의 평균): 고배당 상위 20% vs 대상 전체
    cap_rank = p["시가총액"].rank(axis=1, ascending=False)
    feats = {"PBR": p["PBR"].where(p["PBR"] > 0), "PER": p["PER"].where(p["PER"] > 0),
             "ROE(%)": (p["PBR"] / p["PER"]).where((p["PER"] > 0) & (p["PBR"] > 0)) * 100,
             "월 변동성(%)": sc["vol"] * 100, "시총 순위": cap_rank}
    out["profile"] = {k: (float(v.where(q1).median(axis=1).mean()), float(v.where(uni).median(axis=1).mean()))
                      for k, v in feats.items()}
    # 3) 오를 때·내릴 때
    mk = market
    q = q1_tot.reindex(mk.index)
    up, dn = mk > 0, mk <= 0
    out["capture"] = {"오른 달 평균(고배당/시장)": (float(q[up].mean()), float(mk[up].mean())),
                      "내린 달 평균(고배당/시장)": (float(q[dn].mean()), float(mk[dn].mean())),
                      "시장 대비 민감도(베타)": _beta(q, mk)}
    # 4) 달력: 주가만 기준 고배당 − 시장(월별 평균), 한국 결산 배당은 대부분 12월 결산
    gap = (q1_price - mk_price)
    out["calendar"] = {int(m): float(v) for m, v in gap.groupby(gap.index.month).mean().items()}
    # 5) 다른 기준으로 설명되는 부분: 고배당 초과수익을 가치·저변동·대형·모멘텀 롱숏 수익에 회귀
    ls = {}
    for name, (key, hb) in {"가치(저PBR)": ("pbr", False), "저변동": ("vol", False),
                            "대형": ("cap", True), "모멘텀": ("mom", True)}.items():
        qr = kf.quintile_returns(sc[key], ret, uni, hb)
        ls[name] = qr[1] - qr[kf.N_Q]
    y = (q1_tot - market).reindex(ls["가치(저PBR)"].index)
    X = pd.DataFrame(ls).reindex(y.index)
    df = pd.concat([y.rename("y"), X], axis=1).dropna()
    A = np.column_stack([np.ones(len(df)), df[list(ls)].to_numpy()])
    coef, *_ = np.linalg.lstsq(A, df["y"].to_numpy(), rcond=None)
    resid = df["y"].to_numpy() - A @ coef
    s2 = resid @ resid / (len(df) - A.shape[1])
    se = np.sqrt(np.abs(np.diag(s2 * np.linalg.pinv(A.T @ A)))) + 1e-12
    out["regression"] = {"남는 초과수익(연)": (coef[0] * 12, coef[0] / se[0]),
                         **{k: (coef[i + 1], coef[i + 1] / se[i + 1]) for i, k in enumerate(ls)},
                         "설명력 R²": 1 - resid.var() / df["y"].var(), "초과수익 원래(연)": df["y"].mean() * 12}
    return out


def report(res: dict, anat: dict) -> str:
    def f(v, pct=True, d=1):
        if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
            return "  –  "
        return f"{v * 100:+.{d}f}%" if pct else f"{v:.2f}"

    L = ["[한국 주식 · 기준 섞기] 조합 점수 상위 종목을 같은 비중으로 매달 교체(비용·배당·상장폐지 반영)",
         "IS = ~2017년, OOS = 2018년~. t = 시장 평균(같은 비중) 대비 초과수익의 t값"]
    for b, v in res["bench"].items():
        L.append(f"  비교 {b}: IS 연 {f(v['IS'].get('CAGR'))} 샤프 {f(v['IS'].get('샤프'), False)} · "
                 f"OOS 연 {f(v['OOS'].get('CAGR'))} 샤프 {f(v['OOS'].get('샤프'), False)} 낙폭 {f(v['OOS'].get('MDD'))}")
    L += ["", "  {:<34} {:<6} | {:>7} {:>5} {:>5} | {:>7} {:>5} {:>7} {:>5}".format(
        "조합", "담는수", "IS연", "샤프", "t", "OOS연", "샤프", "낙폭", "t")]
    for r in sorted(res["rows"], key=lambda x: -(x["OOS"].get("샤프") or -9)):
        i, o = r["IS"], r["OOS"]
        L.append("  {:<34} {:<6} | {:>7} {:>5} {:>5.1f} | {:>7} {:>5} {:>7} {:>5.1f}".format(
            r["name"][:34], r["size"], f(i.get("CAGR")), f(i.get("샤프"), False), r["t_is"],
            f(o.get("CAGR")), f(o.get("샤프"), False), f(o.get("MDD")), r["t_oos"]))
    b = res["best_is"]
    L += ["", f"(OOS 샤프 순으로 정렬. 시험한 조합 {res['n_tests']}개 → 우연을 거르려면 |t| 3 안팎 필요)",
          f"2017년까지 성적으로 골랐다면: '{b['name']}'({b['size']}) → IS 샤프 {f(b['IS'].get('샤프'), False)} → "
          f"OOS 연 {f(b['OOS'].get('CAGR'))}, 샤프 {f(b['OOS'].get('샤프'), False)}, 낙폭 {f(b['OOS'].get('MDD'))}"]

    L += ["", "[고배당은 왜 잘됐나]", "1) 수익을 배당과 주가로 나누면"]
    for t, v in anat["split"].items():
        L.append(f"  {t}: 고배당 총 {f(v['고배당 총수익(연)'])} = 주가 {f(v['고배당 주가만(연)'])} + 배당 약 "
                 f"{f(v['고배당 평균 배당수익률'])} | 시장 주가 {f(v['시장 주가만(연)'])} + 배당 약 {f(v['시장 평균 배당수익률'])}")
    L.append("2) 어떤 종목인가(그달 중앙값의 평균): 고배당 상위 20% vs 대상 전체")
    for k, (a, b2) in anat["profile"].items():
        L.append(f"  {k:<10} {a:8.2f} vs {b2:8.2f}")
    L.append("3) 오를 때·내릴 때")
    for k, v in anat["capture"].items():
        L.append(f"  {k}: " + (f"{f(v[0], d=2)} / {f(v[1], d=2)}" if isinstance(v, tuple) else f"{v:.2f}"))
    L.append("4) 달력(주가만, 고배당 − 시장, 월평균): " + " ".join(f"{m}월 {f(v, d=2)}" for m, v in anat["calendar"].items()))
    rg = anat["regression"]
    L.append(f"5) 다른 기준으로 설명되는 부분(고배당 초과수익 연 {f(rg['초과수익 원래(연)'])}, 설명력 R² {rg['설명력 R²']:.2f})")
    for k, v in rg.items():
        if isinstance(v, tuple):
            L.append(f"  {k}: {v[0] * (100 if k.startswith('남는') else 1):+.2f}{'%' if k.startswith('남는') else ''} (t {v[1]:.1f})")
    return "\n".join(L)
