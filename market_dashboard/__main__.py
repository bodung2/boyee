"""사용법:
  python -m market_dashboard run              시세·거시 데이터 받기 → 백테스트 → output/market/dashboard.html
  python -m market_dashboard run --notify     위 작업 + 오늘의 답을 텔레그램으로(TELEGRAM_BOT_TOKEN·CHAT_ID)
  python -m market_dashboard run --offline    받아 둔 데이터(data/market/)로만 다시 계산
  python -m market_dashboard run --base USD   달러 기준 수익으로 평가(기본 원화)
  python -m market_dashboard run --out site   결과를 site/index.html로(GitHub Pages 배포용)
  python -m market_dashboard analyze          자산군별 경향·'어느 구간에서 사면 좋았나' 표를 출력
  python -m market_dashboard sectors --out site   미국·한국 주식 섹터 지도 → site/sectors.html
  python -m market_dashboard krfactors        한국 주식 종목 선정 방식(가치·수익성·저변동·모멘텀·수급 등) 비교
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from naver_autopost.config import ROOT, _load_dotenv
from naver_autopost.notify import send_text

from . import backtest, data, html, products, report
from .signals import Params

CACHE = ROOT / "data" / "market"
OUT = ROOT / "output" / "market"

KST = timezone(timedelta(hours=9))

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
    r.add_argument("--out", help="이 폴더에 index.html로 저장(기본: output/market/dashboard.html)")
    an = sub.add_parser("analyze")
    an.add_argument("--offline", action="store_true")
    sub.add_parser("krfactors")
    se = sub.add_parser("sectors")
    se.add_argument("--offline", action="store_true")
    se.add_argument("--out", help="이 폴더에 sectors.html로 저장(기본: output/market/)")
    se.add_argument("--check-names", action="store_true", help="티커가 맞는 종목인지 Yahoo 이름과 나란히 출력")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    _load_dotenv(ROOT / ".env")

    if args.cmd == "krfactors":
        from . import kr_factors

        snaps = kr_factors.load(CACHE / "krx")
        print(f"월말 스냅숏 {len(snaps)}개")
        if len(snaps) < 24:
            print("데이터가 부족해 중단(한국거래소 접속 실패 가능)")
            return 1
        try:
            import yfinance as yf

            k200 = yf.download("069500.KS", start="2009-12-01", auto_adjust=True, progress=False)["Close"].squeeze()
        except Exception:
            k200 = None
        res = kr_factors.run(snaps, k200)
        names = {}
        try:
            from pykrx import stock

            for c in {c for v in res["current"].values() for c in v[:10]}:
                names[c] = stock.get_market_ticker_name(c)
        except Exception as e:
            log.warning("종목명 실패: %s", e)
        print(kr_factors.report(res, names))
        return 0

    if args.cmd == "sectors":
        from . import sector_html, sectors
        from .sector_universe import COUNTRIES

        if args.check_names:
            import yfinance as yf

            for c in COUNTRIES:
                pairs = [(s.etf, s.etf_name) for s in c.sectors] + [(c.benchmark, c.benchmark_name), (c.cash, "현금 기준")]
                if c.key == "KR":
                    pairs += [(t, n) for s in c.sectors for t, n in s.stocks.items()]
                for t, n in dict(pairs).items():
                    try:
                        info = yf.Ticker(t).info or {}
                        yname = info.get("longName") or info.get("shortName") or "?"
                    except Exception as e:
                        yname = f"실패: {e}"
                    print(f"  {t:<12} 우리 이름 {n:<28} Yahoo 이름 {yname}")
            return 0

        got = {}
        for c in COUNTRIES:
            try:
                got[c.key] = (pd.read_pickle(CACHE / f"sectors_{c.key}.pkl") if args.offline
                              else sectors.fetch(c, CACHE))
            except Exception as e:
                log.warning("%s 섹터 시세 없음: %s", c.name, e)
        d = sectors.build(got)
        d["generated"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
        out = Path(args.out) if args.out else OUT
        out.mkdir(parents=True, exist_ok=True)
        (out / "sectors.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        (out / "sectors.html").write_text(sector_html.render(d), encoding="utf-8")
        print(sectors.summary(d))
        print(f"섹터 지도: {out / 'sectors.html'}")
        return 0

    if args.cmd == "analyze":
        from . import analysis
        from .universe import by_key

        close = (pd.read_csv(CACHE / "prices.csv", index_col=0, parse_dates=True) if args.offline
                 else data.fetch_prices(CACHE))
        usd, krw = data.to_base(close, "USD"), data.to_base(close, "KRW")
        a = analysis.run(usd, krw, Params())
        print(analysis.as_text(a, {k: v.name for k, v in by_key().items()}))
        print()
        print("== 백테스트(원화) 규칙 비교 ==")
        bench_start = max(krw[k].first_valid_index() for mix in report.BENCHMARKS.values() for k in mix)
        for name, vp in report.variants(Params())[:2]:
            r = backtest.run(usd, krw, vp, start=str(bench_start.date()))
            m = backtest.metrics(r["nav"], krw[report.CASH_KEY])
            print(f"  {name:<22} " + " ".join(f"{k} {v * 100:+.1f}%" if k != "샤프" else f"샤프 {v:.2f}" for k, v in m.items())
                  + f" 회전율 {r['turnover_per_year']:.1f}배/년")
        return 0

    if args.offline:
        close = pd.read_csv(CACHE / "prices.csv", index_col=0, parse_dates=True)
        fred_path = CACHE / "fred.csv"
        fred = pd.read_csv(fred_path, index_col=0, parse_dates=True) if fred_path.exists() else pd.DataFrame()
        prod_path = CACHE / "products.json"
        live = json.loads(prod_path.read_text(encoding="utf-8")) if prod_path.exists() else {}
    else:
        close = data.fetch_prices(CACHE)
        fred = data.fetch_fred(CACHE)
        live = products.fetch_live(CACHE)

    d = report.build(close, fred, Params(), base=args.base, products_live=live)
    d["generated"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    out = Path(args.out) if args.out else OUT
    out.mkdir(parents=True, exist_ok=True)
    (out / "dashboard.json").write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    page = out / ("index.html" if args.out else "dashboard.html")
    page.write_text(html.render(d), encoding="utf-8")
    text = summary(d)
    if os.environ.get("DASHBOARD_URL"):
        text += "\n" + os.environ["DASHBOARD_URL"]
    print(text)
    print(f"대시보드: {page}")
    if args.notify:
        send_text(os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(), os.environ.get("TELEGRAM_CHAT_ID", "").strip(), text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
