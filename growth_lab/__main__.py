"""사용법:
  python -m growth_lab daily                 매일: 통계·검색 순위 수집(예약 작업). 리뷰 요일(기본 일요일)이면 주간 리뷰까지
  python -m growth_lab collect [--blog invest]   수집만
  python -m growth_lab review [--blog invest] [--no-claude]   주간 리뷰를 지금 실행(--no-claude: 판정·장부만)
  python -m growth_lab status [--blog invest]    장부 요약(주제 상태·무덤·탐색 후보·실험·제안)
  python -m growth_lab brief --blog invest       오늘 글쓰기에 넘길 안내문 미리 보기
  python -m growth_lab diagnose --blog invest [--no-push]   통계 화면 구조 진단(조회수를 못 찾을 때)
  python -m growth_lab approve 투3 [--text "고친 문장"]   제안 승인(투=투자, 티=티스토리, 생=생활 절차) / reject 투3: 거절

주간 보고는 diagnostics/growth/<블로그>/weekly.md로 GitHub에 올라간다(글 제목·주소 없이, LAB_PUSH_REPORT=false로 끔).
Claude 대화에서 정한 승인·거절은 data/lab_decisions.json으로 들어와 다음 실행 때 반영된다.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime
from types import SimpleNamespace

from naver_autopost.pipeline import KST, _Lock, today_kst

from .config import BLOGS, LabConfig

log = logging.getLogger("growth_lab")
WEEKDAYS = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}
# 통계 화면은 발행과 같은 크롬 프로필을 쓴다 → 그 블로그가 발행 중이면 건너뛴다(프로필은 동시에 못 연다).
BLOG_LOCK = {"invest": ".run-invest.lock", "tistory": ".run-tistory.lock", "guide": ".run-guide.lock"}


def _setup_logging(cfg: LabConfig, today: str) -> None:
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.FileHandler(cfg.log_dir / f"lab-{today}.log", encoding="utf-8"),
                                  logging.StreamHandler()])


def _pull_telegram(cfg: LabConfig) -> None:
    """제안 답장("승인 투3")을 받아 둔다. 티스토리 화제 제보와 같은 받은편지함·offset을 쓴다."""
    from tistory_autopost import inbox
    box = SimpleNamespace(telegram_bot_token=cfg.telegram_bot_token, telegram_chat_id=cfg.telegram_chat_id,
                          inbox_file=cfg.history_dir / "tistory_inbox.json",
                          tip_prefix=os.environ.get("TISTORY_TIP_PREFIX", "화제").strip())
    try:
        inbox.pull(box)
    except Exception as e:  # noqa: BLE001
        log.warning("텔레그램 답장 받기 실패: %s", e)


def collect_all(cfg: LabConfig, blogs: list[str], today: str) -> list[str]:
    from . import metrics
    notes = []
    for blog in blogs:
        try:
            with _Lock(cfg.log_dir / BLOG_LOCK[blog]):
                snap = metrics.collect(blog, cfg, today)
            if not snap.get("logged_in", True):
                notes.append(f"[{BLOGS[blog].label}] 로그인이 풀려 통계를 못 읽었습니다(발행 쪽 login 명령으로 다시 로그인)")
            elif snap["matched"] == 0 and snap["total_posts"]:
                notes.append(f"[{BLOGS[blog].label}] 통계 화면에서 글 조회수를 찾지 못했습니다 → "
                             f"`python -m growth_lab diagnose --blog {blog}` 실행 후 Claude에게 알려 주세요")
        except RuntimeError as e:
            log.warning("[%s] 수집 건너뜀: %s", BLOGS[blog].label, e)
        except Exception as e:  # noqa: BLE001 - 한 블로그 실패가 다른 블로그 수집을 막지 않게
            log.exception("[%s] 수집 실패", BLOGS[blog].label)
            notes.append(f"[{BLOGS[blog].label}] 수집 실패: {str(e)[:200]}")
    return notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="growth_lab")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("approve", "reject"):
        p = sub.add_parser(name)
        p.add_argument("proposal", help="제안 번호(예: 투3, 티2)")
        p.add_argument("--text", default="", help="승인하면서 규칙 문장을 고칠 때")
    for name in ("daily", "collect", "review", "status", "brief", "diagnose"):
        p = sub.add_parser(name)
        p.add_argument("--blog", choices=list(BLOGS), help="한 블로그만(기본: LAB_BLOGS 전체)")
        if name == "review":
            p.add_argument("--no-claude", action="store_true", help="판정·장부만, 진단·리서치(Claude)는 건너뛴다")
        if name == "diagnose":
            p.add_argument("--no-push", action="store_true", help="GitHub에 올리지 않는다")
    args = parser.parse_args(argv)
    cfg = LabConfig.load()
    today = today_kst()
    blogs = [args.blog] if args.blog else cfg.blogs

    if args.cmd == "brief":
        from . import brief
        print(brief.for_blog(args.blog or blogs[0], today, cfg=cfg) or "(실험실이 꺼져 있습니다: .env의 LAB_BLOGS 확인)")
        return 0
    if args.cmd == "status":
        return _status(cfg, blogs)
    if args.cmd in ("approve", "reject"):
        return _decide(cfg, args.proposal, "승인" if args.cmd == "approve" else "거절", args.text, today)
    _setup_logging(cfg, today)
    if args.cmd == "diagnose":
        from . import diagnose
        for blog in blogs:
            path = diagnose.run(blog, cfg, today)
            print(f"[{BLOGS[blog].label}] 구조 진단: {path}\n  스크린샷·원본(집 PC에만): {cfg.output_dir / blog / f'diagnose-{today}'}")
        if args.no_push:
            return 0
        from naver_autopost.__main__ import _push_diagnostics
        return _push_diagnostics("Growth lab: stat page structure")

    from naver_autopost.notify import send_text
    from . import review
    try:
        with _Lock(cfg.log_dir / ".run-lab.lock"):
            notes: list[str] = []
            notes += _apply_decisions(cfg, blogs, today)
            if args.cmd in ("daily", "collect"):
                notes += collect_all(cfg, blogs, today)
            weekday = WEEKDAYS.get(os.environ.get("LAB_REVIEW_WEEKDAY", "일").strip()[:1], 6)
            if args.cmd == "review" or (args.cmd == "daily" and datetime.now(KST).weekday() == weekday):
                _pull_telegram(cfg)
                for blog in blogs:
                    review.run(blog, cfg, today, use_claude=not getattr(args, "no_claude", False), idents=_idents())
                if cfg.push_report:
                    from naver_autopost.__main__ import _push_diagnostics
                    if _push_diagnostics("Growth lab: weekly report"):
                        notes.append("⚠️ 주간 보고를 GitHub에 올리지 못했습니다(로그 확인)")
            if notes:
                send_text(cfg.telegram_bot_token, cfg.telegram_chat_id, "[성장 실험실]\n" + "\n".join(notes))
        return 0
    except Exception as e:  # noqa: BLE001
        log.exception("성장 실험실 실패")
        send_text(cfg.telegram_bot_token, cfg.telegram_chat_id, f"[성장 실험실 실패] {today}\n{e}")
        return 1


def _idents() -> list[str]:
    """공개 보고에서 지울 블로그 아이디(네이버 세 블로그·티스토리)."""
    keys = ("NAVER_BLOG_ID", "NAVER_BLOG_ID_EDU", "NAVER_BLOG_ID_INVEST", "NAVER_BLOG_ID_CHILDHOOD", "TISTORY_BLOG")
    out = [os.environ.get(k, "").strip() for k in keys]
    return [i.removeprefix("https://").split(".tistory.com")[0].strip("/") for i in out if i]


def _apply_decisions(cfg: LabConfig, blogs: list[str], today: str) -> list[str]:
    from . import review, store
    notes = []
    for blog in blogs:
        led = store.load_ledger(cfg, blog)
        got = review.apply_repo_decisions(blog, cfg, led, today)
        if got:
            store.save_ledger(cfg, blog, led)
            notes += [f"[{BLOGS[blog].label}] {n}" for n in got]
    return notes


def _decide(cfg: LabConfig, proposal: str, verb: str, text: str, today: str) -> int:
    import re
    from . import review, store
    m = re.fullmatch(r"\s*([가-힣])?\s*(\d+)\s*", proposal)
    blog = next((b for b, pre in review.PREFIX.items() if m and pre == m.group(1)), None)
    if not m or not blog:
        print("제안 번호는 '투3'(투자)·'티2'(티스토리)·'생1'(생활 절차)처럼 적습니다")
        return 1
    led = store.load_ledger(cfg, blog)
    note = review.decide(blog, cfg, led, int(m.group(2)), verb, today, text)
    if not note:
        print(f"결정할 수 있는 제안 {proposal}이 없습니다(이미 정했거나 번호가 다름). `python -m growth_lab status`로 확인하세요.")
        return 1
    store.save_ledger(cfg, blog, led)
    print(note)
    return 0


def _status(cfg: LabConfig, blogs: list[str]) -> int:
    from . import store
    from .review import PREFIX, STATUS_KO
    for blog in blogs:
        led = store.load_ledger(cfg, blog)
        rows = store.load_metrics(cfg, blog)
        print(f"== {BLOGS[blog].label} == 수집 {len(rows)}일" + (f"(마지막 {rows[-1]['date']}, 조회수 찾은 글 "
                                                            f"{rows[-1].get('matched', 0)}/{rows[-1].get('total_posts', 0)})" if rows else ""))
        for name, t in sorted(led["topics"].items(), key=lambda x: -(x[1].get("ratio") or 0)):
            print(f"  {STATUS_KO.get(t.get('status'), t.get('status')):<8} {name}  점수 {t.get('ratio', '-')}  글 {t.get('posts', 0)}편")
        for g in led["graveyard"]:
            print(f"  ⚰️ {g['name']} — {g.get('reason', '')}")
        for c in led["explore_queue"][:5]:
            print(f"  🔍 후보 {c['name']} (수요 {c.get('demand', '-')})")
        if led.get("experiment"):
            e = led["experiment"]
            print(f"  🧪 {e['var']}: {e['arms'][0]} vs {e['arms'][1]} ({e['status']}, ~{e['post_until']})")
        print(f"  채택된 화풍: {(led.get('adopted') or {}).get('image_style', 'base')}")
        for p in led["proposals"]:
            if p["status"] == "pending":
                print(f"  💬 제안 {PREFIX[blog]}{p['id']}: {p['text'][:100]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
