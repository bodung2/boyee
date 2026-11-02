"""한국 종목 시세를 공공데이터포털 '금융위원회_주식시세정보'(이용허락범위 제한 없음)에서 받는다.

- 키: 공공데이터포털(data.go.kr)에서 활용 신청 후 받은 일반 인증키 → 환경변수 DATA_GO_KR_KEY
  (Encoding 키·Decoding 키 어느 쪽이든 된다)
- 주는 것: 날짜별 전 종목 종가·거래량·거래대금·상장주식수·시가총액. 배당·PBR·PER은 없다(그 열은 비워 둔다).
- 갱신: 기준일 다음 영업일 오후 1시 이후 → 아침에 돌리면 이틀 전 장까지가 최신이다.
- 받아 둔 것(data/market/kr_public_panel.pkl)에 날짜를 이어 붙여, 처음 한 번만 종목별로 3년치를 받는다.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

API = "https://apis.data.go.kr/1160100/service/GetStockSecuritiesInfoService/getStockPriceInfo"
KST = timezone(timedelta(hours=9))
YEARS = 3
SOURCE = "금융위원회 주식시세정보(공공데이터포털)"
BENCH_NAME, BENCH_SHORT = "상위 200 시가총액 가중", "상위 200"
FIELDS = {"basDt": "date", "srtnCd": "code", "itmsNm": "name", "mrktCtg": "market", "clpr": "close",
          "trqu": "volume", "trPrc": "value", "lstgStCnt": "shares", "mrktTotAmt": "cap"}


class ApiError(RuntimeError):
    pass


def _url(key: str, params: dict) -> str:
    # Encoding 키(이미 %가 들어 있음)는 그대로, Decoding 키는 인코딩해서 붙인다
    k = key if "%" in key else urllib.parse.quote(key, safe="")
    return f"{API}?serviceKey={k}&" + urllib.parse.urlencode(params)


def fetch_page(key: str, params: dict, timeout: int = 60) -> tuple[list[dict], int]:
    with urllib.request.urlopen(_url(key, {**params, "resultType": "json"}), timeout=timeout) as r:
        raw = r.read().decode("utf-8", "replace")
    try:
        body = json.loads(raw)["response"]
    except (ValueError, KeyError) as e:   # 키 오류 등은 XML로 온다
        raise ApiError(f"공공데이터포털 응답을 읽지 못함: {raw[:200]}") from e
    head = body.get("header", {})
    if head.get("resultCode") not in ("00", "0", None):
        raise ApiError(f"공공데이터포털 오류 {head.get('resultCode')}: {head.get('resultMsg')}")
    b = body.get("body", {})
    items = (b.get("items") or {}).get("item") or []
    if isinstance(items, dict):
        items = [items]
    return items, int(b.get("totalCount") or 0)


def fetch_all(key: str, params: dict, rows: int = 5000, fetch=fetch_page) -> list[dict]:
    out, page = [], 1
    while True:
        items, total = fetch(key, {**params, "numOfRows": rows, "pageNo": page})
        out += items
        if len(out) >= total or not items:
            return out
        page += 1
        time.sleep(0.2)


def to_frame(items: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(items)
    if df.empty:
        return pd.DataFrame(columns=list(FIELDS.values()))
    df = df.rename(columns=FIELDS)[[c for c in FIELDS.values() if c in df.rename(columns=FIELDS)]]
    df["code"] = df["code"].astype(str).str.replace("^A", "", regex=True).str.zfill(6)
    df["date"] = pd.to_datetime(df["date"].astype(str), format="%Y%m%d")
    for c in ("close", "volume", "value", "shares", "cap"):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def latest(key: str, today: datetime | None = None, fetch=fetch_page, tries: int = 10) -> pd.DataFrame:
    """가장 최근 거래일의 전 종목 표."""
    day = (today or datetime.now(KST)).date()
    for _ in range(tries):
        if day.weekday() < 5:
            df = to_frame(fetch_all(key, {"basDt": day.strftime("%Y%m%d")}, fetch=fetch))
            if len(df):
                return df
        day -= timedelta(days=1)
    raise ApiError("최근 열흘 안에 시세가 없음")


def universe(snap: pd.DataFrame, n: int = 400) -> pd.DataFrame:
    """kr_stocks.fetch_universe와 같은 모양: 종목코드 인덱스, 종목명·시장·시가총액·DIV·PBR·PER·기준일."""
    d = snap[snap["market"].isin(["KOSPI", "KOSDAQ"]) & snap["code"].str.endswith("0")
             & ~snap["name"].str.contains("스팩", na=False)]
    d = d.sort_values("cap", ascending=False).head(n)
    out = pd.DataFrame({"시가총액": d["cap"].values, "종목명": d["name"].values, "시장": d["market"].values,
                        "DIV": np.nan, "PBR": np.nan, "PER": np.nan,
                        "기준일": d["date"].iloc[0].strftime("%Y-%m-%d") if len(d) else None}, index=d["code"].values)
    return out


def update_panel(key: str, codes: list[str], cache_dir: Path, snap: pd.DataFrame, fetch=fetch_page) -> pd.DataFrame:
    """긴 표(date·code·close·value·shares·cap). 처음 보는 종목은 3년치를 종목별로, 그 뒤로는 빠진 날짜만 날짜별로."""
    path = cache_dir / "kr_public_panel.pkl"
    panel = pd.read_pickle(path) if path.exists() else pd.DataFrame(columns=["date", "code", "close", "value", "shares", "cap"])
    last = snap["date"].iloc[0]
    start = last - pd.DateOffset(years=YEARS)
    have = set(panel.loc[panel["date"] <= start + pd.Timedelta(days=30), "code"]) if len(panel) else set()
    parts = [panel]
    new = [c for c in codes if c not in have]
    for i, c in enumerate(new):                 # 처음 한 번: 종목별 3년치
        items = fetch_all(key, {"likeSrtnCd": c, "beginBasDt": start.strftime("%Y%m%d"),
                                "endBasDt": last.strftime("%Y%m%d")}, rows=1000, fetch=fetch)
        df = to_frame(items)
        parts.append(df[df["code"] == c])
        if i % 50 == 49:
            log.info("종목별 과거 시세 %d/%d", i + 1, len(new))
    if len(panel):                              # 그 뒤: 빠진 날짜만
        d = panel["date"].max() + pd.Timedelta(days=1)
        while d < last:
            if d.weekday() < 5:
                parts.append(to_frame(fetch_all(key, {"basDt": d.strftime("%Y%m%d")}, fetch=fetch)))
            d += pd.Timedelta(days=1)
    parts.append(snap)
    keep = ["date", "code", "close", "value", "shares", "cap"]
    out = pd.concat([p[keep] for p in parts if len(p)], ignore_index=True)
    out = out.drop_duplicates(["date", "code"], keep="last")
    out = out[out["date"] >= start - pd.Timedelta(days=10)]
    cache_dir.mkdir(parents=True, exist_ok=True)
    out.to_pickle(path)
    return out


def adjusted_close(close: pd.DataFrame, shares: pd.DataFrame) -> pd.DataFrame:
    """액면분할·병합 보정: 상장주식수가 하루에 1.5배 넘게(또는 2/3 밑으로) 바뀐 날 앞의 가격을 그 비율로 나눈다."""
    ratio = (shares / shares.shift(1)).where(lambda r: (r > 1.5) | (r < 0.67), 1.0).fillna(1.0)
    after = ratio.iloc[::-1].cumprod().iloc[::-1].shift(-1).fillna(1.0)   # t 뒤에 있었던 분할의 누적 비율
    return close / after


def prices(panel: pd.DataFrame, pool: list[str], bench: str, n_bench: int = 200) -> tuple[pd.DataFrame, pd.DataFrame]:
    """kr_stocks.build가 받는 (종가, 거래량) — 거래량 자리에는 '거래대금 ÷ 보정 종가'를 넣어 종가×거래량 = 거래대금이 되게.
    비교 지수(bench 열)는 시가총액 상위 n_bench 종목의 시가총액 가중 지수."""
    p = panel[panel["code"].isin(pool)]
    wide = {f: p.pivot_table(index="date", columns="code", values=f) for f in ("close", "value", "shares", "cap")}
    adj = adjusted_close(wide["close"], wide["shares"])
    vol = wide["value"] / adj
    top = wide["cap"].iloc[-1].sort_values(ascending=False).head(n_bench).index
    r = adj[top].pct_change(fill_method=None)
    w = wide["cap"][top].shift(1)
    idx_ret = (r * w).sum(axis=1) / w.where(r.notna()).sum(axis=1)
    adj[bench] = 100 * (1 + idx_ret.fillna(0)).cumprod()
    vol[bench] = np.nan
    return adj, vol
