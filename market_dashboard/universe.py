"""투자 대상(유니버스). 돈을 넣기 전에 고정해 두고, 뉴스에 뜬 자산을 그때그때 넣지 않는다.

currency: 시세 통화. USD 자산은 원/달러 환율을 곱해 원화 기준으로 바꾼다.
cash=True인 자산은 순위 대상이 아니라 '현금' 기준선(초과수익 계산·남는 비중 보관)이다.
남는 비중은 달러 단기국채로 들고 있는 것으로 계산한다(원화로 보면 환율 영향을 받는다).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Asset:
    key: str
    name: str
    group: str
    ticker: str
    currency: str = "USD"
    cash: bool = False


GROUPS = {
    "equity": "주식",
    "bond": "채권",
    "real": "실물",
    "fx": "통화",
    "alt": "대체",
}

ASSETS: list[Asset] = [
    Asset("SPY", "미국 S&P500", "equity", "SPY"),
    Asset("QQQ", "미국 나스닥100", "equity", "QQQ"),
    Asset("EFA", "선진국(미국 외)", "equity", "EFA"),
    Asset("EEM", "신흥국", "equity", "EEM"),
    Asset("EWY", "한국(MSCI Korea)", "equity", "EWY"),
    Asset("TLT", "미 장기국채", "bond", "TLT"),
    Asset("IEF", "미 중기국채", "bond", "IEF"),
    Asset("TIP", "미 물가연동채", "bond", "TIP"),
    Asset("LQD", "미 투자등급 회사채", "bond", "LQD"),
    Asset("HYG", "미 하이일드", "bond", "HYG"),
    Asset("KTB10", "한국 국고채 10년", "bond", "148070.KS", currency="KRW"),
    Asset("GLD", "금", "real", "GLD"),
    Asset("DBC", "원자재 종합", "real", "DBC"),
    Asset("USO", "원유", "real", "USO"),
    Asset("CPER", "구리", "real", "CPER"),
    Asset("VNQ", "미국 리츠", "real", "VNQ"),
    Asset("UUP", "달러 인덱스", "fx", "UUP"),
    Asset("FXY", "엔화", "fx", "FXY"),
    Asset("BTC", "비트코인", "alt", "BTC-USD"),
    # 현금: 미 3개월 국채금리(^IRX, %)를 매일 쌓은 지수. BIL ETF(2007년 5월 상장)보다 길게 거슬러 간다.
    Asset("CASH", "현금(미 3개월 국채)", "alt", "^IRX", cash=True),
]

FX_TICKER = "KRW=X"  # 1달러당 원화
CASH_KEY = "CASH"

# 비교 대상(벤치마크): 고정 비중, 매월 리밸런싱
BENCHMARKS: dict[str, dict[str, float]] = {
    "S&P500 보유": {"SPY": 1.0},
    "60/40": {"SPY": 0.6, "IEF": 0.4},
    "올웨더": {"SPY": 0.30, "TLT": 0.40, "IEF": 0.15, "GLD": 0.075, "DBC": 0.075},
}


def by_key() -> dict[str, Asset]:
    return {a.key: a for a in ASSETS}


def risky_keys() -> list[str]:
    return [a.key for a in ASSETS if not a.cash]
