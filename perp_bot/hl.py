"""Hyperliquid 공개 정보 API(키 불필요): 캔들, 펀딩비. 주문 기능은 1단계에 없다."""
from __future__ import annotations

import json
import logging
import time
import urllib.request

import pandas as pd

log = logging.getLogger(__name__)
INFO_URL = "https://api.hyperliquid.xyz/info"
INTERVAL_MS = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


def _post(body: dict, retries: int = 3):
    data = json.dumps(body).encode()
    for i in range(retries):
        try:
            req = urllib.request.Request(INFO_URL, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except Exception as e:  # 일시적 오류는 잠깐 쉬고 다시
            if i == retries - 1:
                raise
            log.warning("Hyperliquid 요청 실패(%s), 다시 시도", e)
            time.sleep(2 * (i + 1))


def candles(coin: str, interval: str = "4h", days: int = 900) -> pd.DataFrame:
    """종가가 확정된 봉만(open, high, low, close, volume). 인덱스 = 봉 시작 시각(UTC)."""
    step = INTERVAL_MS[interval]
    end = int(time.time() * 1000)
    start = end - days * 86_400_000
    rows: dict[int, dict] = {}
    cur = start
    while cur < end:
        got = _post({"type": "candleSnapshot",
                     "req": {"coin": coin, "interval": interval, "startTime": cur, "endTime": end}}) or []
        if not got:
            break
        for c in got:
            rows[int(c["t"])] = c
        last = max(int(c["t"]) for c in got)
        if last + step <= cur:
            break
        cur = last + step
        if len(got) < 10:
            break
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame([{"t": k, "open": float(v["o"]), "high": float(v["h"]), "low": float(v["l"]),
                        "close": float(v["c"]), "volume": float(v["v"]), "T": int(v["T"])}
                       for k, v in sorted(rows.items())])
    df = df[df["T"] < end]  # 아직 안 끝난 봉 제외
    df.index = pd.to_datetime(df["t"], unit="ms", utc=True)
    return df[["open", "high", "low", "close", "volume"]]


def funding(coin: str, days: int = 900) -> pd.Series:
    """시간당 펀딩비(롱이 숏에게 내는 비율, 음수면 반대)."""
    end = int(time.time() * 1000)
    cur = end - days * 86_400_000
    out: dict[int, float] = {}
    while cur < end:
        got = _post({"type": "fundingHistory", "coin": coin, "startTime": cur, "endTime": end}) or []
        if not got:
            break
        for f in got:
            out[int(f["time"])] = float(f["fundingRate"])
        last = max(int(f["time"]) for f in got)
        if last <= cur:
            break
        cur = last + 1
    s = pd.Series(out, dtype=float).sort_index()
    s.index = pd.to_datetime(s.index, unit="ms", utc=True)
    return s
