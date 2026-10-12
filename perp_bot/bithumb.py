"""빗썸 공개 API(로그인·키 없음)로 원화 마켓 코인 일봉 전체 기록을 받는다.

- 코인 목록: /v1/market/all (지금 상장된 코인만 → 상장폐지 코인은 빠진다 = 생존 편향, 결과가 좋게 나옴)
- 일봉: /v1/candles/days?market=KRW-BTC&count=200&to=… 를 과거로 거슬러 올라가며 반복해서 받는다.
  (옛 /public/candlestick 은 최근 약 200일만 줘서 쓰지 않는다)
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

BASE = "https://api.bithumb.com/v1"
log = logging.getLogger(__name__)


def _get(path: str, params: dict | None = None, tries: int = 5):
    url = f"{BASE}{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "boyee-research/1.0", "accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            if i == tries - 1:
                raise
            log.warning("빗썸 요청 실패(%s), 다시 시도", e)
            time.sleep(1.5 * (i + 1))
    raise RuntimeError("unreachable")


def markets() -> list[str]:
    return sorted(m["market"].split("-", 1)[1] for m in _get("/market/all", {"isDetails": "false"})
                  if m.get("market", "").startswith("KRW-"))


def parse_candles(rows: list[dict], normalize: bool = True) -> pd.DataFrame:
    idx = pd.to_datetime([r["candle_date_time_kst"] for r in rows])
    df = pd.DataFrame({
        "open": [r["opening_price"] for r in rows], "high": [r["high_price"] for r in rows],
        "low": [r["low_price"] for r in rows], "close": [r["trade_price"] for r in rows],
        "value": [r.get("candle_acc_trade_price", 0) for r in rows],
        "volume": [r.get("candle_acc_trade_volume", 0) for r in rows],
    }, index=idx.normalize() if normalize else idx)
    df = df.astype(float)
    return df[~df.index.duplicated(keep="first")].sort_index()


def _pages(path: str, coin: str, pause: float, max_pages: int, since: str | None = None) -> list[dict]:
    """가장 최근부터 200개씩 과거로. 더 이상 과거가 없거나 since보다 오래되면 멈춘다."""
    pages, to = [], None
    for _ in range(max_pages):
        params = {"market": f"KRW-{coin}", "count": 200}
        if to:
            params["to"] = to
        rows = _get(path, params)
        time.sleep(pause)
        if not rows:
            break
        pages.extend(rows)
        oldest = min(r["candle_date_time_kst"] for r in rows)
        nxt = oldest.replace("T", " ")
        if nxt == to or len(rows) < 200 or (since and oldest < since):
            break
        to = nxt
    return pages


def daily(coin: str, pause: float = 0.05, max_pages: int = 40) -> pd.DataFrame:
    """환경변수 BITHUMB_CACHE에 폴더를 주면 한 번 받은 일봉을 저장해 두고 다시 쓴다(같은 실행 안 여러 분석용)."""
    cache = os.environ.get("BITHUMB_CACHE")
    path = Path(cache) / f"{coin}_daily.pkl" if cache else None
    if path and path.exists():
        return pd.read_pickle(path)
    pages = _pages("/candles/days", coin, pause, max_pages)
    df = parse_candles(pages) if pages else pd.DataFrame()
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_pickle(path)
    return df


def hourly(coin: str, since: str = "2021-01-01", pause: float = 0.05, max_pages: int = 400) -> pd.DataFrame:
    """1시간 봉(한국 시간 기준 시각). since 이후만."""
    pages = _pages("/candles/minutes/60", coin, pause, max_pages, since=since)
    if not pages:
        return pd.DataFrame()
    df = parse_candles(pages, normalize=False)
    return df[df.index >= pd.Timestamp(since)]


def load(min_days: int = 90, workers: int = 4):
    """반환: (종가, 원화 거래대금, 못 받은 코인). xsmom.backtest에 그대로 넣을 수 있는 모양."""
    names = markets()

    def one(k):
        try:
            return k, daily(k)
        except Exception as e:
            log.warning("%s 일봉 못 받음: %s", k, e)
            return k, None

    closes, dvols, missing = {}, {}, []
    with ThreadPoolExecutor(workers) as ex:
        for k, df in ex.map(one, names):
            if df is None:
                missing.append(k)
            elif len(df) >= min_days:
                closes[k] = df["close"]
                dvols[k] = df["value"]
    close = pd.DataFrame(closes).sort_index()
    close = close.reindex(pd.date_range(close.index[0], close.index[-1], freq="D"))
    dvol = pd.DataFrame(dvols).reindex(close.index)
    return close, dvol, missing
