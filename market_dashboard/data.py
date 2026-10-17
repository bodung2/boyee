"""시세·거시 데이터 받기. 시세는 yfinance(배당·이자 재투자 반영 수정주가), 거시는 FRED CSV(키 불필요).

받은 데이터는 data/market/에 저장해 두고, 다음 실행에서 네트워크가 안 되면 저장본을 쓴다.
"""
from __future__ import annotations

import io
import logging
import urllib.request
from pathlib import Path

import pandas as pd

from .universe import ASSETS, FX_TICKER

log = logging.getLogger(__name__)

START = "2004-01-01"

# 유동성 온도용 FRED 시리즈
FRED_SERIES = {
    "WALCL": "연준 총자산(주간)",
    "RRPONTSYD": "역레포 잔액(십억 달러)",
    "WTREGEN": "재무부 일반계정 TGA(주간)",
    "DFII10": "10년 실질금리(%)",
    "BAMLH0A0HYM2": "하이일드 스프레드(%p)",
    "T10YIE": "10년 기대인플레이션(%)",
}


def fetch_prices(cache_dir: Path, start: str = START) -> pd.DataFrame:
    """종목별 수정종가(현지 통화) + 원/달러 환율 열(FX_TICKER). 실패하면 저장본."""
    cache = cache_dir / "prices.csv"
    try:
        import yfinance as yf

        tickers = [a.ticker for a in ASSETS] + [FX_TICKER]
        raw = yf.download(tickers, start=start, auto_adjust=True, progress=False, threads=True)
        close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw
        close = close.dropna(how="all")
        if close.empty:
            raise RuntimeError("빈 시세")
        cache_dir.mkdir(parents=True, exist_ok=True)
        close.to_csv(cache)
        return close
    except Exception as e:  # 네트워크·라이브러리 문제
        if cache.exists():
            log.warning("시세 받기 실패(%s), 저장본 사용", e)
            return pd.read_csv(cache, index_col=0, parse_dates=True)
        raise


def fetch_fred(cache_dir: Path, start: str = START) -> pd.DataFrame:
    cache = cache_dir / "fred.csv"
    frames = []
    for sid in FRED_SERIES:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={start}"
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                df = pd.read_csv(io.BytesIO(r.read()), index_col=0, parse_dates=True, na_values=".")
            frames.append(df.iloc[:, 0].rename(sid))
        except Exception as e:
            log.warning("FRED %s 실패: %s", sid, e)
    if frames:
        out = pd.concat(frames, axis=1).sort_index()
        cache_dir.mkdir(parents=True, exist_ok=True)
        out.to_csv(cache)
        return out
    if cache.exists():
        return pd.read_csv(cache, index_col=0, parse_dates=True)
    return pd.DataFrame()


def to_base(close: pd.DataFrame, base: str = "KRW") -> pd.DataFrame:
    """종목 키를 열로 하는 '기준 통화' 가격표(미국 거래일만). 휴장일 차이는 직전 값으로 메운다."""
    close = close.sort_index()
    if "SPY" in close:  # 주말(비트코인만 거래)·미국 휴장일 제거
        close = close[close["SPY"].notna()]
    close = close.ffill()
    fx = close[FX_TICKER]
    out = {}
    for a in ASSETS:
        if a.ticker not in close:
            continue
        p = close[a.ticker]
        if a.cash:  # 연 수익률(%) → 거래일마다 쌓은 지수
            p = (1 + p.fillna(0) / 100 / 252).cumprod() * 100
        if a.currency == "USD" and base == "KRW":
            p = p * fx
        elif a.currency == "KRW" and base == "USD":
            p = p / fx
        out[a.key] = p
    return pd.DataFrame(out)
