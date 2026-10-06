"""사용법:
  python -m tistory_autopost login              최초 1회 티스토리(카카오) 로그인을 자동화용 크롬에 저장
  python -m tistory_autopost check              로그인·글쓰기 화면·주제 큐 확인
  python -m tistory_autopost queue              오늘 쓸 주제 후보, 갱신할 글, 대기 중인 화제 제보 보기
  python -m tistory_autopost tip "금수저 논쟁"   화제 제보를 직접 넣기(텔레그램으로 "화제 ..."를 보내도 된다)
  python -m tistory_autopost run                오늘 글 1편 생성·검수·발행(작업 스케줄러가 매일 실행)
  python -m tistory_autopost run --dry-run      공개 발행 직전까지만(설치 확인용)
  python -m tistory_autopost republish          오늘 검수 통과한 글을 다시 올리기(잘못 올라간 글을 지운 뒤)
  python -m tistory_autopost republish --date 2026-10-07 --dry-run
  python -m tistory_autopost diagnose           글쓰기 화면 구조 저장(발행이 화면을 못 찾을 때)
"""
from __future__ import annotations

import argparse
import sys
from datetime import date

from .config import TistoryConfig


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tistory_autopost")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login")
    sub.add_parser("check")
    sub.add_parser("queue")
    tip = sub.add_parser("tip")
    tip.add_argument("text")
    run_p = sub.add_parser("run")
    run_p.add_argument("--dry-run", action="store_true", help="공개 발행 직전에 멈춘다")
    run_p.add_argument("--force", action="store_true", help="오늘 이미 발행했어도 한 편 더")
    rep = sub.add_parser("republish")
    rep.add_argument("--date", help="YYYY-MM-DD(기본: 오늘)")
    rep.add_argument("--dry-run", action="store_true", help="공개 발행 직전에 멈춘다")
    sub.add_parser("diagnose")
    args = parser.parse_args(argv)
    cfg = TistoryConfig.load()

    if args.cmd == "login":
        from . import publisher
        publisher.login(cfg)
        return 0
    if args.cmd == "check":
        return _check(cfg)
    if args.cmd == "queue":
        return _queue(cfg)
    if args.cmd == "tip":
        from . import inbox
        t = inbox.add(cfg, args.text)
        print(f"화제 제보 저장: {t['text']} (다음 실행 때 우선 검토)")
        return 0
    if args.cmd == "run":
        from .pipeline import run
        return run(cfg, dry_run=args.dry_run, force=args.force)
    if args.cmd == "republish":
        from .pipeline import republish
        return republish(cfg, args.date, dry_run=args.dry_run)
    if args.cmd == "diagnose":
        from . import publisher
        path = publisher.diagnose(cfg, cfg.output_dir / "diagnostics")
        print(f"저장했습니다: {path.parent} (이 폴더의 파일을 Claude에게 보여 주세요)")
        return 0
    return 1


def _queue(cfg: TistoryConfig) -> int:
    from naver_autopost import history
    from . import inbox, topics

    today = date.today()
    entries = history.load(cfg.history_file)
    all_topics = topics.load(cfg.topics_file)
    ranked = topics.rank(all_topics, entries, today)
    print(f"남은 주제 {len(ranked)}개 / 전체 {len(all_topics)}개")
    for c in ranked[:10]:
        print(f"  {c.score:>3}점  {c.topic['id']:<28} {c.topic['title_hint']}  ({c.why})")
    tips = inbox.pending(cfg)
    if tips:
        print("대기 중인 화제 제보:")
        for t in tips:
            print(f"  - {t['date'][:10]} {t['text']}")
    due = topics.refresh_due(all_topics, entries, today)
    if due:
        print("새 통계가 나와 갱신하면 좋은 글:")
        for d in due:
            print(f"  - {d['title']} {d['url']} (발표 {d['released'][:7]})")
    return 0


def _check(cfg: TistoryConfig) -> int:
    import shutil
    from . import publisher, topics
    ok = True
    print(f"1) 블로그: {cfg.blog_url if cfg.blog_name else '❌ .env에 TISTORY_BLOG가 없습니다'}")
    ok &= bool(cfg.blog_name)
    print("2) Claude Code: " + (f"✅ {shutil.which(cfg.claude_bin)}" if shutil.which(cfg.claude_bin)
                               else f"❌ '{cfg.claude_bin}' 명령이 없습니다"))
    ok &= bool(shutil.which(cfg.claude_bin))
    if cfg.gpt_factcheck:
        has = bool(shutil.which(cfg.codex_bin))
        print("3) Codex CLI(ChatGPT 교차 팩트체크): " + ("✅" if has else "❌ 없음(TISTORY_GPT_FACTCHECK=false로 끌 수 있음)"))
        ok &= has
    try:
        n = len(topics.load(cfg.topics_file))
        print(f"4) 주제 큐: ✅ {n}개 ({cfg.topics_file})")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"4) 주제 큐: ❌ {e}")
    if cfg.blog_name:
        print("5) 티스토리 로그인·글쓰기 화면: ", end="", flush=True)
        try:
            good = publisher.check_session(cfg)
            print("✅" if good else "❌ 로그인이 필요합니다 → python -m tistory_autopost login")
            ok &= good
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"❌ {e}")
    print("모두 정상입니다." if ok else "실패한 항목의 메시지를 Claude에게 알려주세요.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
