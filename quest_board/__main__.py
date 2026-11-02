"""python -m quest_board [build|serve] [--open] [--notify] [--text] [--days 14] [--out 경로] [--port 8765]"""
from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from pathlib import Path

from . import board, html, schedule
from .checks import Paths


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="quest_board", description="매일 예약 작업(퀘스트)의 오늘 상태와 최근 발행 기록")
    ap.add_argument("--open", action="store_true", help="만든 뒤 브라우저로 연다")
    ap.add_argument("--notify", action="store_true", help="오늘 요약을 텔레그램으로 보낸다(.env의 TELEGRAM_BOT_TOKEN·CHAT_ID)")
    ap.add_argument("--text", action="store_true", help="요약을 화면에 출력한다")
    ap.add_argument("--days", type=int, default=14, help="기록 표에 보일 날짜 수(기본 14)")
    ap.add_argument("--out", type=Path, help="저장할 파일(기본: output/quest_board.html)")
    ap.add_argument("cmd", nargs="?", choices=["build", "serve"], default="build",
                    help="build: 보기 전용 파일 만들기(기본) / serve: 버튼이 있는 보드를 이 PC 안에서 열기")
    ap.add_argument("--port", type=int, default=8765, help="serve 포트(기본 8765)")
    args = ap.parse_args(argv)
    if args.cmd == "serve":
        from .server import serve
        return serve(args.port)

    paths = Paths.load()
    quests, has_live, missing = schedule.load(live=schedule.read_scheduler())
    b = board.build(quests, has_live, missing, days=max(2, args.days), paths=paths)
    out = args.out or paths.output / "quest_board.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html.render(b), encoding="utf-8")
    text = board.summary_text(b)
    if args.text or not (args.open or args.notify):
        print(text)
    print(f"퀘스트 보드: {out}")
    if args.notify:
        from naver_autopost.notify import send_text
        send_text(os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", ""), text)
    if args.open:
        webbrowser.open(out.resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
