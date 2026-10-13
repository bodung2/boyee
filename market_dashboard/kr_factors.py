"""한국 주식 종목 선정 방식 비교(팩터 연구): 섹터 대신 '어떤 성질의 종목'을 사면 좋았나.

결과를 보기 전에 시험할 기준·숫자를 모두 아래에 고정해 두고, 전부 보고한다.

- 데이터: 한국거래소(pykrx, KRX 정보데이터시스템 로그인 필요: 환경변수 KRX_ID·KRX_PW) 월말 스냅숏 — 그 시점에 상장돼 있던 전 종목의 종가·시가총액·상장주식수·거래대금·
  PER·PBR·배당수익률, 외국인 20일 순매수. 나중에 상장폐지된 종목도 그때는 들어 있다(생존 편향 적음).
- 대상(매달): KOSPI+KOSDAQ 보통주 중 시가총액 상위 500개, 그중 그달 거래대금이 하루 평균 10억 원 이상.
- 매달 말 기준으로 기준값 순서대로 5개 묶음(1 = 가장 좋다고 보는 쪽)으로 나눠 같은 비중으로 담고, 다음 달 말까지 보유.
- 수익: 종가 수익(액면분할·병합은 상장주식수로 보정) + 배당수익률/12. 다음 달에 사라진 종목은 −50%로 친다(불리하게).
- 비용: 바뀐 비중 × 편도 0.25%(수수료·미끄러짐 + 매도 거래세 평균).
- 비교: 대상 전체 같은 비중(시장 평균), KODEX 200(배당 포함 가격).
- 검증: 2017년까지 = 고르는 기간(IS), 2018년부터 = 평가 기간(OOS).
"""
from __future__ import annotations

import logging
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

START = "2010-01"
SPLIT = pd.Timestamp("2018-01-01")
TOP_CAP = 500
MIN_VALUE = 1e9
COST = 0.0025
DELIST_RET = -0.5
N_Q = 5

# 기준 이름: (설명, 계산 함수 키, 큰 값이 좋은가)
FACTORS = {
    "저PBR(가치)": ("PBR 낮은 순", "pbr", False),
    "저PER(이익 대비 싼)": ("이익수익률 E/P 높은 순", "ep", True),
    "고배당": ("배당수익률 높은 순", "div", True),
    "고ROE(수익성)": ("ROE = PBR/PER 높은 순", "roe", True),
    "가치+수익성": ("저PBR 순위 + 고ROE 순위 평균", "value_quality", True),
    "저변동성": ("최근 12개월 월수익 변동성 낮은 순", "vol", False),
    "모멘텀 12-1": ("최근 12개월(마지막 1개월 제외) 수익 높은 순", "mom", True),
    "단기 반전": ("지난 1개월 수익 낮은 순", "rev", False),
    "52주 고점 근접": ("최근 12개월 월말 최고가 대비 가까운 순", "high52", True),
    "외국인 순매수": ("지난 20거래일 외국인 순매수 ÷ 시가총액 높은 순", "foreign", True),
    "대형주": ("시가총액 큰 순", "cap", True),
}


# ---------------- 데이터 ----------------
def month_ends(start: str = START) -> list[str]:
    from pykrx import stock

    out = []
    for m in pd.period_range(start, pd.Timestamp.today().to_period("M") - 1, freq="M"):
        d = stock.get_nearest_business_day_in_a_week(m.end_time.strftime("%Y%m%d"), prev=True)
        out.append(d)
    return out


def snapshot(day: str, cache_dir: Path) -> pd.DataFrame:
    """그날 전 종목 표(인덱스 = 종목코드). 한 번 받으면 저장해 둔다."""
    path = cache_dir / f"krx_{day}.pkl"
    if path.exists():
        return pd.read_pickle(path)
    from pykrx import stock

    cap = stock.get_market_cap(day, market="ALL")[["종가", "시가총액", "거래대금", "상장주식수"]]
    fund = stock.get_market_fundamental(day, market="ALL")[["PER", "PBR", "DIV"]]
    start = (pd.Timestamp(day) - pd.Timedelta(days=30)).strftime("%Y%m%d")
    try:
        flow = stock.get_market_net_purchases_of_equities(start, day, "ALL", "외국인")
        col = [c for c in flow.columns if "순매수" in c and "대금" in c]
        flow = flow[col[0]].rename("외국인순매수") if col else pd.Series(dtype=float, name="외국인순매수")
    except Exception as e:
        log.warning("%s 외국인 순매수 실패: %s", day, e)
        flow = pd.Series(dtype=float, name="외국인순매수")
    df = cap.join(fund, how="left").join(flow, how="left")
    cache_dir.mkdir(parents=True, exist_ok=True)
    df.to_pickle(path)
    time.sleep(0.3)
    return df


def load(cache_dir: Path, start: str = START) -> dict[pd.Timestamp, pd.DataFrame]:
    snaps = {}
    for d in month_ends(start):
        try:
            snaps[pd.Timestamp(d)] = snapshot(d, cache_dir)
        except Exception as e:
            log.warning("%s 스냅숏 실패: %s", d, e)
    return snaps


# ---------------- 계산 ----------------
def panel(snaps: dict[pd.Timestamp, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """월(행) × 종목(열) 표들."""
    dates = sorted(snaps)
    fields = ["종가", "시가총액", "거래대금", "상장주식수", "PER", "PBR", "DIV", "외국인순매수"]
    out = {f: pd.DataFrame({d: snaps[d][f] for d in dates if f in snaps[d]}).T.sort_index() for f in fields}
    out["종가"] = out["종가"].where(out["종가"] > 0)   # 거래정지 등으로 0인 값은 없는 것으로
    return out


def monthly_returns(p: dict[str, pd.DataFrame], include_div: bool = True) -> pd.DataFrame:
    """t월 말 → t+1월 말 수익(다음 행이 아니라 같은 행에 둔다: ret.loc[t] = t에 사서 t+1에 판 수익)."""
    px, sh, div = p["종가"], p["상장주식수"], p["DIV"].fillna(0)
    ratio = sh.shift(-1) / sh
    split = (ratio > 1.5) | (ratio < 0.67)          # 액면분할·병합: 가격 비율에 주식수 비율을 곱해 보정
    r = px.shift(-1) / px * ratio.where(split, 1.0) - 1
    if include_div:
        r = r + div / 100 / 12
    gone = px.notna() & px.shift(-1).isna()
    r = r.where(~gone, DELIST_RET)
    r.iloc[-1] = np.nan
    return r


def universe(p: dict[str, pd.DataFrame]) -> pd.DataFrame:
    common = pd.DataFrame({c: c.endswith("0") for c in p["종가"].columns}, index=p["종가"].index)
    cap_rank = p["시가총액"].rank(axis=1, ascending=False)
    # 거래대금(그날 하루)은 들쭉날쭉해서, 시가총액 상위이면서 그날 거래대금이 기준 이상인 종목
    return common & (cap_rank <= TOP_CAP) & (p["거래대금"] >= MIN_VALUE) & p["종가"].notna()


def scores(p: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    px = p["종가"]
    sh = p["상장주식수"]
    ratio = sh / sh.shift(1)
    adj = (ratio.where((ratio > 1.5) | (ratio < 0.67), 1.0)).fillna(1.0).cumprod()
    tr = px * adj   # 분할 보정 가격 지수
    mret = tr / tr.shift(1) - 1
    per, pbr = p["PER"].where(p["PER"] > 0), p["PBR"].where(p["PBR"] > 0)
    roe = pbr / per
    s = {
        "pbr": pbr, "ep": 1 / per, "div": p["DIV"].where(p["DIV"] > 0), "roe": roe,
        "value_quality": (-pbr).rank(axis=1, pct=True) / 2 + roe.rank(axis=1, pct=True) / 2,
        "vol": mret.rolling(12, min_periods=10).std(),
        "mom": tr.shift(1) / tr.shift(12) - 1,
        "rev": mret,
        "high52": tr / tr.rolling(12, min_periods=10).max(),
        "foreign": p["외국인순매수"] / p["시가총액"],
        "cap": p["시가총액"],
    }
    return s


def quintile_returns(score: pd.DataFrame, ret: pd.DataFrame, uni: pd.DataFrame, higher_better: bool) -> pd.DataFrame:
    """월별 5개 묶음 수익(비용 반영). 열 1 = 좋다고 보는 쪽."""
    out = {q: [] for q in range(1, N_Q + 1)}
    prev = {q: pd.Series(dtype=float) for q in out}
    idx = []
    for t in ret.index[:-1]:
        s = score.loc[t].where(uni.loc[t]).dropna()
        if len(s) < N_Q * 10:
            continue
        rk = s.rank(ascending=not higher_better, method="first")
        bucket = np.ceil(rk / len(s) * N_Q).astype(int)
        idx.append(t)
        for q in out:
            names = bucket.index[bucket == q]
            w = pd.Series(1 / len(names), index=names)
            r = ret.loc[t, names].fillna(DELIST_RET)
            turn = w.subtract(prev[q], fill_value=0).abs().sum()
            out[q].append(float((w * r).sum()) - turn * COST)
            grown = w * (1 + r)
            prev[q] = grown / grown.sum() if grown.sum() > 0 else w
    return pd.DataFrame(out, index=pd.DatetimeIndex(idx))


def stats(r: pd.Series) -> dict:
    r = r.dropna()
    if len(r) < 12:
        return {}
    eq = (1 + r).cumprod()
    yrs = len(r) / 12
    return {"CAGR": eq.iloc[-1] ** (1 / yrs) - 1, "샤프": r.mean() / r.std() * math.sqrt(12) if r.std() > 0 else 0.0,
            "MDD": float((eq / eq.cummax() - 1).min())}


def tstat(x: pd.Series) -> float:
    x = x.dropna()
    return float(x.mean() / x.std() * math.sqrt(len(x))) if len(x) > 2 and x.std() > 0 else float("nan")


def run(snaps: dict[pd.Timestamp, pd.DataFrame], kodex200: pd.Series | None = None) -> dict:
    p = panel(snaps)
    ret = monthly_returns(p)
    uni = universe(p)
    sc = scores(p)
    market = ret.where(uni).mean(axis=1).iloc[:-1]
    rows = []
    for name, (desc, key, hb) in FACTORS.items():
        q = quintile_returns(sc[key], ret, uni, hb)
        ex = q[1] - market.reindex(q.index)
        spread = q[1] - q[N_Q]
        row = {"name": name, "desc": desc}
        for tag, mask in (("IS", q.index < SPLIT), ("OOS", q.index >= SPLIT)):
            row[tag] = {"Q1": stats(q[1][mask]), "Q5": stats(q[N_Q][mask]),
                        "excess_t": tstat(ex[mask]), "spread_t": tstat(spread[mask]),
                        "ladder": [stats(q[k][mask]).get("CAGR") for k in range(1, N_Q + 1)]}
        rows.append(row)
    bench = {}
    for tag, mask in (("IS", market.index < SPLIT), ("OOS", market.index >= SPLIT)):
        bench[tag] = {"시장 평균(같은 비중)": stats(market[mask])}
        kk = monthly_benchmark(kodex200, market.index)
        if kk is not None:
            bench[tag]["KODEX 200"] = stats(kk[mask])
    n_uni = uni.sum(axis=1)
    return {"rows": rows, "bench": bench, "months": len(market), "start": market.index[0].strftime("%Y-%m"),
            "end": market.index[-1].strftime("%Y-%m"), "uni_size": int(n_uni.median()),
            "current": current_picks(p, sc, uni)}


def monthly_benchmark(px: pd.Series | None, index: pd.DatetimeIndex) -> pd.Series | None:
    """일별 가격 → 우리 월말 날짜 기준 '그달 말 → 다음 달 말' 수익."""
    if px is None or not len(px):
        return None
    k = px.resample("ME").last().pct_change().shift(-1)
    k.index = k.index.to_period("M")
    return pd.Series(index.to_period("M").map(k), index=index, dtype=float)


def current_picks(p, sc, uni, k: int = 15) -> dict:
    """가장 최근 달 기준 각 기준의 상위 종목 코드(참고용)."""
    t = p["종가"].index[-1]
    out = {}
    for name, (_, key, hb) in FACTORS.items():
        s = sc[key].loc[t].where(uni.loc[t]).dropna()
        out[name] = list((s.sort_values(ascending=not hb)).index[:k])
    return out


def report(res: dict, names: dict[str, str] | None = None) -> str:
    def f(v, pct=True):
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return "   –  "
        return f"{v * 100:+6.1f}%" if pct else f"{v:5.2f}"

    lines = [f"[한국 주식 종목 선정 방식 비교] {res['start']} ~ {res['end']} 월별 {res['months']}개월, 대상 평균 {res['uni_size']}종목",
             "5개 묶음 중 1 = 그 기준으로 가장 좋다고 보는 20%, 5 = 반대쪽 20%. 비용 편도 0.25%, 배당 포함, 상장폐지 −50%.",
             "IS = ~2017년, OOS = 2018년~ (OOS가 진짜 성적)", ""]
    for tag in ("IS", "OOS"):
        b = res["bench"][tag]
        lines.append(f"[{tag}] 비교 기준: " + " · ".join(f"{k} 연 {f(v.get('CAGR')).strip()} 샤프 {f(v.get('샤프'), False).strip()} 낙폭 {f(v.get('MDD')).strip()}" for k, v in b.items()))
    lines += ["", "  {:<18} | {:>7} {:>5} {:>7} {:>6} | {:>7} {:>5} {:>7} {:>6} {:>6} | {}".format(
        "기준", "IS 1연", "샤프", "IS 5연", "t초과", "OOS 1연", "샤프", "낙폭", "t초과", "t1-5", "OOS 1→5 연수익(계단)")]
    for r in res["rows"]:
        i, o = r["IS"], r["OOS"]
        ladder = " ".join(f(v).strip() for v in o["ladder"])
        lines.append("  {:<18} | {} {} {} {:>6} | {} {} {} {:>6} {:>6} | {}".format(
            r["name"][:18], f(i["Q1"].get("CAGR")), f(i["Q1"].get("샤프"), False), f(i["Q5"].get("CAGR")),
            f"{i['excess_t']:.1f}" if not math.isnan(i["excess_t"]) else "–",
            f(o["Q1"].get("CAGR")), f(o["Q1"].get("샤프"), False), f(o["Q1"].get("MDD")),
            f"{o['excess_t']:.1f}" if not math.isnan(o["excess_t"]) else "–",
            f"{o['spread_t']:.1f}" if not math.isnan(o["spread_t"]) else "–", ladder))
    good = [r["name"] for r in res["rows"] if r["IS"]["excess_t"] >= 2 and r["OOS"]["excess_t"] >= 2]
    lines += ["", "t초과 = 1번 묶음이 시장 평균(같은 비중)보다 나은 정도의 t값, t1-5 = 1번과 5번 묶음 차이의 t값.",
              f"기준 {len(res['rows'])}개를 시험했으니 우연을 걸러내려면 |t| 2.5~3 이상이 필요하다.",
              "IS·OOS 둘 다 t초과 ≥ 2인 기준: " + (", ".join(good) or "없음"), "", "[가장 최근 달 기준 상위 종목(참고)]"]
    for name, codes in res["current"].items():
        shown = [f"{(names or {}).get(c, c)}" for c in codes[:10]]
        lines.append(f"  {name}: {', '.join(shown)}")
    return "\n".join(lines)
