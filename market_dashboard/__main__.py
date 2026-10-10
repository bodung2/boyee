"""사용법:
  python -m market_dashboard run              시세·거시 데이터 받기 → 백테스트 → output/market/dashboard.html
  python -m market_dashboard run --notify     위 작업 + 오늘의 답을 텔레그램으로(TELEGRAM_BOT_TOKEN·CHAT_ID)
  python -m market_dashboard run --offline    받아 둔 데이터(data/market/)로만 다시 계산
  python -m market_dashboard run --base USD   달러 기준 수익으로 평가(기본 원화)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

import pandas as pd

from naver_autopost.config import ROOT, _load_dotenv
from naver_autopost.notify import send_text

from . import data, html, report
from .signals import Params

CACHE = ROOT / "data" / "market"
OUT = ROOT / "output" / "market"

log = logging.getLogger("market_dashboard")


def summary(d: dict) -> str:
    picks = [a for a in d["assets"] if a["weight"] > 0]
    cash = 1 - sum(a["weight"] for a in picks)
    lines = [f"[자산군 모멘텀] {d['asof']} 기준"]
    if picks:
        lines.append("규칙상 목표: " + ", ".join(
            f"{a['name']} {a['weight'] * 100:.0f}%{' 🔥분할' if a['overheat'] else ''}" for a in picks)
            + f", 현금 {cash * 100:.0f}%")
    else:
        lines.append("규칙상 목표: 전부 현금(현금보다 강한 추세 없음)")
    turning = [a["name"] for a in d["assets"] if a["quadrant"] == "회복" and (a["x"] or -9) > -0.3]
    if turning:
        lines.append("곧 넘어올 수 있음(회복→주도 경계): " + ", ".join(turning))
    liq = d["liquidity"]["temp"]
    if liq is not None:
        lines.append(f"유동성 온도 {liq:+.2f}")
    lines.append(f"다음 리밸런싱 {d['next_rebalance']} · 참고 자료, 매매 신호 아님")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="market_dashboard")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--offline", action="store_true")
    r.add_argument("--notify", action="store_true")
    r.add_argument("--base", choices=["KRW", "USD"], default="KRW")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    _load_dotenv(ROOT / ".env")

    if args.offline:
        close = pd.read_csv(CACHE / "prices.csv", index_col=0, parse_dates=True)
        fred_path = CACHE / "fred.csv"
        fred = pd.read_csv(fred_path, index_col=0, parse_dates=True) if fred_path.exists() else pd.DataFrame()
    else:
        close = data.fetch_prices(CACHE)
        fred = data.fetch_fred(CACHE)

    d = report.build(close, fred, Params(), base=args.base)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "dashboard.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    page = OUT / "dashboard.html"
    page.write_text(html.render(d), encoding="utf-8")
    text = summary(d)
    print(text)
    print(f"대시보드: {page}")
    if args.notify:
        send_text(os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(), os.environ.get("TELEGRAM_CHAT_ID", "").strip(), text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
