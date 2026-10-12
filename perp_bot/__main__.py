"""사용법:
  python -m perp_bot backtest            Hyperliquid 4시간 봉(약 2.5년)으로 백테스트, 위험 설정별 비교
  python -m perp_bot paper [--notify]    모의 운용 한 번(새로 확정된 봉 처리). 예약 작업이 4시간마다 실행
  python -m perp_bot status              모의 운용 상태
  python -m perp_bot research            Yahoo 일봉(2014~)으로 여러 매매 방법론 비교(IS ~2020 / OOS 2021~)
  python -m perp_bot xsmom               여러 코인 중 강한 코인을 고르는 종목 선정형 모멘텀 검증(현물)
  python -m perp_bot bithumb             같은 검증을 빗썸 원화 마켓 코인 전체로
  python -m perp_bot intraday            빗썸 1시간 봉 차트 매매 검증(돌파·과매도·볼린저·급락 반등·시간대)
  python -m perp_bot volume              빗썸 전체 코인 거래량 신호 사건 분석(거래량↑ 가격 그대로 → 이후 수익?)

1단계(지금): 실제 주문 기능 없음. 실제 주문은 모의 운용 결과를 본 뒤 별도 단계에서 만든다.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from dataclasses import replace

import pandas as pd

from naver_autopost.config import ROOT, _load_dotenv
from naver_autopost.notify import send_text

from . import backtest, hl, paper
from .config import BotConfig

STATE = ROOT / "data" / "perp" / "paper_state.json"


def _fmt(m: dict) -> str:
    out = []
    for k, v in m.items():
        if isinstance(v, float) and k in ("총수익", "연환산", "최대낙폭", "승률", "최악의 달"):
            out.append(f"{k} {v * 100:+.1f}%")
        elif isinstance(v, float):
            out.append(f"{k} {v:.2f}")
        else:
            out.append(f"{k} {v}")
    return " · ".join(out)


def cmd_backtest(c: BotConfig) -> int:
    data = {k: hl.candles(k, c.interval, days=900) for k in c.coins}
    fund = {}
    for k in c.coins:
        try:
            fund[k] = hl.funding(k, days=900)
        except Exception as e:
            logging.warning("%s 펀딩비 못 받음(0으로 계산): %s", k, e)
    for k, df in data.items():
        print(f"{k}: {len(df)}개 봉 {df.index[0]:%Y-%m-%d} ~ {df.index[-1]:%Y-%m-%d}, 펀딩 {len(fund.get(k, []))}건")
    variants = [
        ("기본: 손실 2%/거래, 최대 10배, 진입 0.5", c),
        ("보수: 손실 1%/거래", replace(c, risk_per_trade=0.01)),
        ("롱만", replace(c, allow_short=False)),
        ("진입 기준 0(약한 추세도 진입)", replace(c, entry_x=0.0)),
        ("공격: 손실 5%/거래(비교용·사용 금지)", replace(c, risk_per_trade=0.05)),
    ]
    for name, vc in variants:
        sim = backtest.run(data, fund, vc)
        print(f"\n== {name} ==\n  " + _fmt(backtest.metrics(sim, vc)))
    sim = backtest.run(data, fund, c)
    print("\n== 기본 설정 최근 거래 10건 ==")
    for t in sim.trades[-10:]:
        print(f"  {t['coin']} {t['side']} {t['entry_time'][:13]} → {t['exit_time'][:13]} "
              f"{t['entry']:,.2f} → {t['exit']:,.2f} {t['pnl']:+.2f}$ ({t['r']:+.2f}R, {t['lev']:.1f}배) {t['reason']}")
    return 0


def cmd_research(c: BotConfig) -> int:
    from . import research

    data = research.load_daily()
    for k, df in data.items():
        print(f"{k}: 일봉 {len(df)}개 {df.index[0]:%Y-%m-%d} ~ {df.index[-1]:%Y-%m-%d}")
    fund = {}
    for k in c.coins:
        time.sleep(3)  # 연달아 요청하면 429(요청 과다)가 난다
        try:
            fund[k] = hl.funding(k, days=900)
        except Exception as e:
            logging.warning("%s 펀딩비 못 받음: %s", k, e)
    print(research.report(research.run_all(data), research.funding_carry(fund)))
    return 0


def cmd_xsmom() -> int:
    from . import xsmom

    close, dvol, missing = xsmom.load()
    print(f"기간 {close.index[0]:%Y-%m-%d} ~ {close.index[-1]:%Y-%m-%d}")
    rows = xsmom.run_all(close, dvol)
    print(xsmom.report(rows, list(close.columns), missing, xsmom.ended_early(close)))
    return 0


def cmd_bithumb() -> int:
    from . import bithumb, xsmom

    close, dvol, missing = bithumb.load()
    print(f"빗썸 원화 마켓 {close.shape[1]}개 코인, {close.index[0]:%Y-%m-%d} ~ {close.index[-1]:%Y-%m-%d}")
    first = close.apply(lambda s: s.first_valid_index())
    if close["BTC"].first_valid_index() > pd.Timestamp("2019-01-01"):
        print("경고: BTC 기록이 2019년 이후부터라 IS(~2020) 검증이 불가능하다. 아래 결과는 믿지 말 것.")
    print("상장 시점별 코인 수: " + ", ".join(f"{y}년 {n}개" for y, n in first.dt.year.value_counts().sort_index().items()))
    rows = xsmom.run_all(close, dvol)
    print(xsmom.report(rows, list(close.columns), missing, xsmom.ended_early(close),
                       title="[빗썸 원화 마켓 · 종목 선정형 모멘텀] 현물·레버리지 없음. IS = ~2020년, OOS = 2021년~\n"
                             "주의: 지금 상장된 코인만 있음(상장폐지 코인 빠짐) → 실제보다 좋게 나온다"))
    return 0


def cmd_intraday() -> int:
    from . import intraday

    data = intraday.load()
    for k, df in data.items():
        if len(df):
            print(f"{k}: 1시간 봉 {len(df)}개 {df.index[0]:%Y-%m-%d %H시} ~ {df.index[-1]:%Y-%m-%d %H시}")
        else:
            print(f"{k}: 데이터 없음")
    data = {k: v for k, v in data.items() if len(v)}
    rows, cut = intraday.run_all(data)
    print(intraday.report(rows, cut, data))
    return 0


def cmd_volume() -> int:
    from . import volume

    data = volume.load()
    print(volume.report(volume.run_all(data), data))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="perp_bot")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("backtest")
    p = sub.add_parser("paper")
    p.add_argument("--notify", action="store_true")
    sub.add_parser("status")
    sub.add_parser("research")
    sub.add_parser("xsmom")
    sub.add_parser("bithumb")
    sub.add_parser("intraday")
    sub.add_parser("volume")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    _load_dotenv(ROOT / ".env")
    c = BotConfig.load()

    if args.cmd == "backtest":
        return cmd_backtest(c)
    if args.cmd == "research":
        return cmd_research(c)
    if args.cmd == "xsmom":
        return cmd_xsmom()
    if args.cmd == "bithumb":
        return cmd_bithumb()
    if args.cmd == "intraday":
        return cmd_intraday()
    if args.cmd == "volume":
        return cmd_volume()
    if args.cmd == "status":
        sim = paper.load(STATE, c)
        try:
            prices = {k: float(v) for k, v in hl._post({"type": "allMids"}).items() if k in c.coins}
        except Exception:
            prices = None
        print(paper.status_text(sim, prices, c))
        return 0
    sim, msgs = paper.tick(STATE, c)
    text = "\n".join(msgs) if msgs else "새 봉 처리, 변동 없음"
    summary = text + "\n" + paper.status_text(sim, None, c)
    print(summary)
    if args.notify and msgs:
        send_text(os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(), os.environ.get("TELEGRAM_CHAT_ID", "").strip(),
                  "[모의] " + summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
