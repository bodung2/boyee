"""코스피·코스닥 지수 일봉을 한국 쪽 출처로 채운다.

야후(yfinance)는 한국 지수의 그날 일봉을 한참 늦게(다음 날 아침까지도) 올리는 날이 있다. 그러면 시황 요약·차트가
전날 종가를 '오늘'처럼 쓰게 된다(2026-11-03: 실제 −3.59%인데 전날 +2.2%가 그대로 나감).
야후 값은 그대로 두고, 야후에 없는 날짜만 아래 출처에서 채운다.

1) 한국거래소(pykrx, 환경변수 KRX_ID·KRX_PW가 있을 때)
2) 네이버 증권 모바일 시세(로그인 불필요)
둘 다 실패하면 None(야후 값만 쓴다).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta

import pandas as pd

log = logging.getLogger(__name__)

KRX_CODE = {"^KS11": "1001", "^KQ11": "2001"}
NAVER_CODE = {"^KS11": "KOSPI", "^KQ11": "KOSDAQ"}
COLS = ["Open", "High", "Low", "Close"]


def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _krx(ticker: str, days: int) -> pd.DataFrame | None:
    if not (os.environ.get("KRX_ID") and os.environ.get("KRX_PW")):
        return None
    from pykrx import stock

    end = datetime.now()
    df = stock.get_index_ohlcv((end - timedelta(days=days)).strftime("%Y%m%d"), end.strftime("%Y%m%d"),
                               KRX_CODE[ticker])
    if df is None or df.empty:
        return None
    df = df.rename(columns={"시가": "Open", "고가": "High", "저가": "Low", "종가": "Close"})[COLS]
    df.index = pd.to_datetime(df.index)
    return df


def parse_naver(items: list[dict]) -> pd.DataFrame | None:
    rows = {}
    for it in items or []:
        d = str(it.get("localTradedAt") or "")[:10]
        c = _num(it.get("closePrice"))
        if len(d) == 10 and c:
            rows[pd.Timestamp(d)] = {"Open": _num(it.get("openPrice")) or c, "High": _num(it.get("highPrice")) or c,
                                     "Low": _num(it.get("lowPrice")) or c, "Close": c}
    return pd.DataFrame.from_dict(rows, orient="index")[COLS].sort_index() if rows else None


def _naver(ticker: str, days: int) -> pd.DataFrame | None:
    import urllib.request

    url = f"https://m.stock.naver.com/api/index/{NAVER_CODE[ticker]}/price?pageSize={min(60, days)}&page=1"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return parse_naver(data if isinstance(data, list) else data.get("result") or data.get("items") or [])


def backup(ticker: str, days: int = 60) -> pd.DataFrame | None:
    """한국 지수 일봉(Open·High·Low·Close, 날짜 인덱스). 받지 못하면 None."""
    if ticker not in KRX_CODE:
        return None
    for name, fn in (("한국거래소", _krx), ("네이버 증권", _naver)):
        try:
            df = fn(ticker, days)
        except Exception as e:  # noqa: BLE001 - 다음 출처로
            log.warning("%s 지수 받기 실패(%s): %s", ticker, name, e)
            continue
        if df is not None and len(df):
            return df
    return None


def fill(df: pd.DataFrame, ticker: str, extra: pd.DataFrame | None = None) -> pd.DataFrame:
    """야후 일봉 df(열 COLS 일부 이상)에 없는 날짜만 한국 출처 값으로 채운다."""
    extra = backup(ticker) if extra is None else extra
    if extra is None or not len(extra):
        return df
    new = extra[~extra.index.isin(df.index)]
    if len(df):
        new = new[new.index > df.index.max() - pd.Timedelta(days=10)]   # 최근 빈 날만(오래된 과거는 야후 기준)
    if not len(new):
        return df
    log.info("%s 일봉을 한국 출처로 채움: %s", ticker, ", ".join(d.strftime("%Y-%m-%d") for d in new.index))
    return pd.concat([df, new[[c for c in df.columns if c in new.columns]]]).sort_index()
