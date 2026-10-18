"""자산군별로 실제로 살 수 있는 상품과 고르는 규칙.

고르는 규칙(같은 자산이면): 최근 20거래일 평균 거래대금이 기준 이상인 상품 중에서 총보수가 가장 낮은 것을 '추천'으로 둔다.
  보수 차이가 0.01%p 이내면 사실상 같다고 보고 거래대금이 많은 쪽을 고른다(호가가 촘촘해 실제 비용이 더 작다).
  - 거래대금 기준: 국내 상장 하루 10억 원, 미국 상장 하루 1천만 달러(이보다 적으면 호가가 듬성듬성할 수 있다)
  - 총보수: 미국 상장은 매일 yfinance에서 받고, 못 받으면 아래 적어 둔 값. 국내 상장은 운용사·거래소 자료를
    확인해 적어 둔 값(FEE_CHECKED 시점). 확인하지 못한 보수는 None으로 두고, 순위에서 보수를 아는 상품 뒤로 보낸다.
  - 거래대금: 매일 yfinance에서 받는다(국내는 코드.KS). 못 받으면 '거래대금 확인 안 됨'으로 표시하고 추천에서 뺀다.
'신호 기준'(signal=True)은 대시보드 신호를 계산하는 바로 그 상품이라는 표시일 뿐, 추천과는 별개다.
특정 상품의 매수 권유가 아니라, 그 자산군에 투자하는 대표적인 방법을 모아 둔 목록이다.
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

NAVER = "https://finance.naver.com/item/main.naver?code={}"
YAHOO = "https://finance.yahoo.com/quote/{}"
FEE_CHECKED = "2026-10"
MIN_TURNOVER = {"kr": 1e9, "us": 1e7}  # 원, 달러
FEE_TIE = 0.01  # %p. 이보다 작은 보수 차이는 같다고 보고 거래대금으로 고른다


@dataclass(frozen=True)
class Product:
    market: str            # "kr" | "us"
    code: str              # 국내 6자리 코드 / 미국 티커
    name: str
    desc: str = ""
    fee: float | None = None   # 총보수 %(연). 미국 상장은 자동 값이 우선
    signal: bool = False

    @property
    def yahoo(self) -> str:
        return f"{self.code}.KS" if self.market == "kr" else self.code

    @property
    def url(self) -> str:
        return NAVER.format(self.code) if self.market == "kr" else YAHOO.format(self.code)


def K(code, name, desc="", fee=None, signal=False):
    return Product("kr", code, name, desc, fee, signal)


def U(code, name, desc="", fee=None, signal=False):
    return Product("us", code, name, desc, fee, signal)


# 미국 상장 보수는 자동 값이 없을 때만 쓰는 대략값(%)
CATALOG: dict[str, dict] = {
    "SPY": {"items": [
        U("SPY", "SPDR S&P 500", "", 0.0945, True), U("VOO", "Vanguard S&P 500", "", 0.03), U("IVV", "iShares Core S&P 500", "", 0.03),
        K("360750", "TIGER 미국S&P500", "환노출", 0.0068), K("360200", "ACE 미국S&P500", "환노출", 0.004),
        K("379780", "RISE 미국S&P500", "환노출", 0.0047), K("379800", "KODEX 미국S&P500", "환노출"),
    ]},
    "QQQ": {"items": [
        U("QQQ", "Invesco QQQ", "", 0.20, True), U("QQQM", "Invesco NASDAQ 100", "", 0.15),
        K("133690", "TIGER 미국나스닥100", "환노출", 0.0068), K("379810", "KODEX 미국나스닥100", "환노출", 0.0062),
        K("367380", "ACE 미국나스닥100", "환노출", 0.006),
    ]},
    "EFA": {"items": [
        U("EFA", "iShares MSCI EAFE", "미국 제외 선진국", 0.33, True), U("IEFA", "iShares Core MSCI EAFE", "", 0.07),
        U("VEA", "Vanguard FTSE Developed", "", 0.03),
        K("251350", "KODEX MSCI선진국", "환노출 · MSCI World라 미국이 60% 이상 포함(신호와 다름)", 0.30),
    ]},
    "EEM": {"items": [
        U("EEM", "iShares MSCI Emerging", "", 0.70, True), U("IEMG", "iShares Core MSCI EM", "", 0.09),
        U("VWO", "Vanguard FTSE EM", "", 0.07),
        K("195980", "PLUS 신흥국MSCI(합성 H)", "환헤지 · 합성", 0.50),
    ]},
    "EWY": {"items": [
        U("EWY", "iShares MSCI South Korea", "달러로 산 한국 주식", 0.50, True),
        K("069500", "KODEX 200", "코스피200", 0.15), K("148020", "RISE 200", "코스피200", 0.02),
        K("105190", "ACE 200", "코스피200", 0.02), K("152100", "PLUS 200", "코스피200(옛 ARIRANG 200)", 0.02),
        K("102110", "TIGER 200", "코스피200"),
    ], "note": "원화로 살 때는 국내 코스피200 ETF가 자연스럽다. EWY는 원/달러 환율 영향이 함께 들어 있다."},
    "TLT": {"items": [
        U("TLT", "iShares 20+ Year Treasury", "", 0.15, True), U("VGLT", "Vanguard Long-Term Treasury", "", 0.04),
        K("484790", "KODEX 미국30년국채액티브(H)", "환헤지", 0.015), K("453850", "ACE 미국30년국채액티브(H)", "환헤지", 0.05),
    ]},
    "IEF": {"items": [
        U("IEF", "iShares 7-10 Year Treasury", "", 0.15, True), U("VGIT", "Vanguard Intermediate Treasury", "3~10년", 0.04),
        K("305080", "TIGER 미국채10년선물", "환노출 · 선물", 0.29),
    ]},
    "TIP": {"items": [
        U("TIP", "iShares TIPS Bond", "", 0.18, True), U("SCHP", "Schwab U.S. TIPS", "", 0.03),
    ], "note": "국내 상장 미국 물가연동채 ETF는 확인된 대표 상품이 없어 미국 상장 상품만 적었다."},
    "LQD": {"items": [
        U("LQD", "iShares iBoxx IG Corporate", "", 0.14, True), U("VCIT", "Vanguard Intermediate Corp", "중기 회사채", 0.03),
    ], "note": "국내 상장 미국 투자등급 회사채 ETF는 확인된 대표 상품이 없어 미국 상장 상품만 적었다."},
    "HYG": {"items": [
        U("HYG", "iShares iBoxx High Yield", "", 0.49, True), U("USHY", "iShares Broad USD High Yield", "", 0.08),
    ], "note": "국내에는 ACE 미국하이일드액티브(H) 등 액티브 상품이 있다. 종목코드는 운용사 사이트에서 확인한다."},
    "KTB10": {"items": [
        K("148070", "KIWOOM 국고채10년", "옛 KOSEF 국고채10년", 0.07, True),
    ]},
    "GLD": {"items": [
        U("GLD", "SPDR Gold Shares", "", 0.40, True), U("IAU", "iShares Gold Trust", "", 0.25),
        U("GLDM", "SPDR Gold MiniShares", "", 0.10),
        K("0072R0", "TIGER KRX금현물", "환노출 · 국내 금 현물", 0.15), K("411060", "ACE KRX금현물", "환노출 · 국내 금 현물", 0.19),
        K("132030", "KODEX 골드선물(H)", "환헤지 · 선물", 0.68),
    ], "note": "증권사 KRX 금시장 계좌로 금 현물을 직접 사는 방법도 있다(매매차익 비과세, 실물 인출 시 부가세)."},
    "DBC": {"items": [
        U("DBC", "Invesco DB Commodity", "", 0.85, True), U("PDBC", "Invesco Optimum Yield Commodity", "K-1 세금서류 없음", 0.59),
    ], "note": "원자재 종합 지수를 그대로 담은 국내 상장 상품은 마땅치 않다. 금·원유·구리를 따로 담는 방법도 있다."},
    "USO": {"items": [
        U("USO", "United States Oil Fund", "WTI 선물", 0.60, True),
        K("130680", "TIGER 원유선물Enhanced(H)", "환헤지 · 선물(롤오버 비용)", 0.69),
    ]},
    "CPER": {"items": [
        U("CPER", "United States Copper Index", "구리 선물", 0.97, True),
        K("138910", "KODEX 구리선물(H)", "환헤지 · 선물"),
    ]},
    "VNQ": {"items": [
        U("VNQ", "Vanguard Real Estate", "", 0.13, True), U("SCHH", "Schwab U.S. REIT", "", 0.07),
        K("182480", "TIGER 미국MSCI리츠(합성 H)", "환헤지 · 합성 · 월분배", 0.24),
    ]},
    "UUP": {"items": [
        U("UUP", "Invesco DB US Dollar Bullish", "달러 인덱스", 0.78, True),
        K("261240", "KODEX 미국달러선물", "원/달러 환율 그 자체", 0.25),
    ], "note": "원화 투자자에게 '달러 강세'는 원/달러 환율 상승이다. 달러 예금·달러 RP도 같은 효과를 낸다."},
    "FXY": {"items": [
        U("FXY", "Invesco CurrencyShares Yen", "달러 대비 엔", 0.40, True),
        K("292560", "TIGER 일본엔선물", "원/엔 환율"),
    ]},
    "BTC": {"items": [
        U("IBIT", "iShares Bitcoin Trust", "미국 현물 ETF", 0.25), U("FBTC", "Fidelity Wise Origin Bitcoin", "미국 현물 ETF", 0.25),
    ], "note": "2024년 금융위원회 판단 이후 국내 증권사는 해외 비트코인 현물 ETF 매매를 중개하지 않는다(현재 허용 여부는 증권사에 확인). "
               "국내에서는 가상자산 거래소에서 직접 사는 방법뿐이며, 변동성이 매우 크다."},
    "CASH": {"items": [
        U("SGOV", "iShares 0-3 Month Treasury", "", 0.09), U("BIL", "SPDR 1-3 Month T-Bill", "", 0.14),
        K("459580", "KODEX CD금리액티브(합성)", "원화 단기금리", 0.02), K("357870", "TIGER CD금리투자KIS(합성)", "원화 단기금리"),
    ], "note": "규칙상 남는 비중(현금). 백테스트는 달러 단기국채로 계산했다. 원화로 두려면 CD금리·파킹형 ETF나 예금도 된다."},
}

GUIDE = [
    "추천 = 같은 자산 중 최근 20거래일 평균 거래대금이 기준(국내 10억 원, 미국 1천만 달러) 이상인 상품에서 총보수가 가장 낮은 것. "
    "보수 차이가 0.01%p 이내면 거래대금이 더 많은 쪽.",
    "연금저축·IRP·ISA에서는 국내 상장 ETF만 살 수 있고, 매매차익 과세가 늦춰지거나 줄어든다. 선물·합성형은 IRP 편입이 제한될 수 있다.",
    "미국 상장 ETF는 해외주식 계좌에서 사며 양도차익에 22%(연 250만 원 공제) 세금이 붙는다. 국내 상장 해외 ETF는 매매차익에 15.4%(금융소득종합과세 합산).",
    "(H) 환헤지 상품은 원/달러 환율 영향을 없앤다. 대시보드 신호와 백테스트는 환노출 원화 기준이라, 환헤지 상품은 숫자가 다르게 나온다.",
]


def all_products() -> list[Product]:
    return [p for e in CATALOG.values() for p in e["items"]]


def fetch_live(cache_dir: Path) -> dict[str, dict]:
    """상품별 {turnover: 20일 평균 거래대금(현지 통화), fee: 자동 총보수 %}. 실패하면 저장본."""
    cache = cache_dir / "products.json"
    live: dict[str, dict] = {}
    try:
        import yfinance as yf

        prods = all_products()
        raw = yf.download([p.yahoo for p in prods], period="3mo", auto_adjust=False, progress=False, threads=True)
        close, vol = raw["Close"], raw["Volume"]
        for p in prods:
            if p.yahoo in close and p.yahoo in vol:
                tv = (close[p.yahoo] * vol[p.yahoo]).dropna().tail(20)
                if len(tv) >= 5 and tv.mean() > 0:
                    live.setdefault(p.yahoo, {})["turnover"] = float(tv.mean())
        for p in prods:
            if p.market != "us":
                continue
            try:
                info = yf.Ticker(p.yahoo).info or {}
            except Exception:
                continue
            fee = info.get("netExpenseRatio")  # % 단위
            if fee is None and info.get("annualReportExpenseRatio") is not None:
                fee = info["annualReportExpenseRatio"] * 100
            if fee is not None and 0 < float(fee) < 3:
                live.setdefault(p.yahoo, {})["fee"] = round(float(fee), 4)
        if live:
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(live, ensure_ascii=False), encoding="utf-8")
            return live
    except Exception as e:
        log.warning("상품 거래대금·보수 받기 실패: %s", e)
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    return {}


def rank(items: list[Product], live: dict[str, dict]) -> list[dict]:
    """한 시장(국내/미국) 안에서 거래대금 기준을 넘는 상품을 총보수 낮은 순으로, 그다음 나머지."""
    rows = []
    for p in items:
        lv = live.get(p.yahoo, {})
        fee = lv.get("fee", p.fee) if p.market == "us" else p.fee
        if p.market == "us":
            fee_src = "자동" if "fee" in lv else ("대략값" if fee is not None else "")
        else:
            fee_src = f"{FEE_CHECKED} 확인" if fee is not None else ""
        tv = lv.get("turnover")
        liquid = tv is not None and tv >= MIN_TURNOVER[p.market]
        rows.append({"code": p.code, "name": p.name, "desc": p.desc, "url": p.url, "signal": p.signal,
                     "fee": fee, "fee_src": fee_src, "turnover": None if tv is None or math.isnan(tv) else round(tv),
                     "liquid": liquid, "best": False})
    rows.sort(key=lambda r: (not r["liquid"], r["fee"] is None, r["fee"] if r["fee"] is not None else 0,
                             -(r["turnover"] or 0)))
    # 보수 차이가 0.01%p 이내면 사실상 같다고 보고, 그중 거래대금이 가장 많은 상품을 추천한다
    priced = [r for r in rows if r["liquid"] and r["fee"] is not None]
    if priced:
        floor = min(r["fee"] for r in priced) + FEE_TIE
        best = max((r for r in priced if r["fee"] <= floor), key=lambda r: r["turnover"] or 0)
    else:
        best = rows[0] if rows and rows[0]["liquid"] else None
    if best is not None:
        best["best"] = True
        rows.remove(best)
        rows.insert(0, best)
    return rows


def for_dashboard(live: dict[str, dict] | None = None) -> dict:
    live = live or {}

    def pack(entry: dict) -> dict:
        items = entry["items"]
        return {"kr": rank([p for p in items if p.market == "kr"], live),
                "us": rank([p for p in items if p.market == "us"], live),
                "note": entry.get("note", "")}

    by = {k: pack(v) for k, v in CATALOG.items() if k != "CASH"}
    return {"by_asset": by, "cash": pack(CATALOG["CASH"]), "guide": GUIDE, "checked": FEE_CHECKED,
            "min_turnover": MIN_TURNOVER, "live": bool(live)}
