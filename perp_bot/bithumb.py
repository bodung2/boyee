"""빗썸 공개 API(로그인·키 없음)로 원화 마켓 코인 일봉 전체 기록을 받는다.

- 코인 목록: /public/ticker/ALL_KRW (지금 상장된 코인만 → 상장폐지 코인은 빠진다 = 생존 편향, 결과가 좋게 나옴)
- 일봉: /public/candlestick/{코인}_KRW/24h → [시각(ms), 시가, 종가, 고가, 저가, 거래량]
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request

import pandas as pd

BASE = "https://api.bithumb.com/public"
log = logging.getLogger(__name__)


def _get(url: str, tries: int = 4) -> dict:
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "boyee-research/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.loads(r.read().decode("utf-8"))
            if str(d.get("status")) != "0000":
                raise RuntimeError(f"빗썸 응답 오류 {d.get('status')}: {d.get('message')}")
            return d
        except Exception as e:
            if i == tries - 1:
                raise
            log.warning("빗썸 요청 실패(%s), 다시 시도", e)
            time.sleep(2 * (i + 1))
    raise RuntimeError("unreachable")


def coins() -> list[str]:
    d = _get(f"{BASE}/ticker/ALL_KRW")["data"]
    return sorted(k for k, v in d.items() if isinstance(v, dict))


def parse_candles(rows: list) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["t", "open", "close", "high", "low", "volume"])
    df.index = pd.to_datetime(df.pop("t").astype("int64"), unit="ms").dt.normalize()
    df = df.astype(float)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


def daily(coin: str) -> pd.DataFrame:
    return parse_candles(_get(f"{BASE}/candlestick/{coin}_KRW/24h")["data"])


def load(min_days: int = 90, pause: float = 0.12):
    """반환: (종가, 원화 거래대금, 못 받은 코인). xsmom.backtest에 그대로 넣을 수 있는 모양."""
    closes, dvols, missing = {}, {}, []
    for k in coins():
        try:
            df = daily(k)
        except Exception as e:
            log.warning("%s 일봉 못 받음: %s", k, e)
            missing.append(k)
            continue
        finally:
            time.sleep(pause)
        if len(df) < min_days:
            continue
        closes[k] = df["close"]
        dvols[k] = df["close"] * df["volume"]
    close = pd.DataFrame(closes).sort_index()
    close = close.reindex(pd.date_range(close.index[0], close.index[-1], freq="D"))
    dvol = pd.DataFrame(dvols).reindex(close.index)
    return close, dvol, missing
