"""사용법:
  python -m blogger_autopost auth           최초 1회 구글 계정 승인(블로그 글쓰기 권한 토큰 저장)
  python -m blogger_autopost blogs          내 블로그 목록과 ID 보기
  python -m blogger_autopost check          Codex·스킬·구글 로그인·블로그 연결 한 번에 확인
  python -m blogger_autopost run            오늘 글 1편 생성·검수·발행(작업 스케줄러가 매일 실행)
  python -m blogger_autopost run --draft    발행하지 않고 블로거 '초안'으로만 저장(설치 확인용)
  python -m blogger_autopost sync-history   블로그에 있는 글을 발행 이력에 가져오기
"""
from __future__ import annotations

import argparse
import shutil
import sys

from .config import BloggerConfig


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="blogger_autopost")
    sub = parser.add_subparsers(dest="cmd", required=True)
    auth = sub.add_parser("auth")
    auth.add_argument("--no-browser", action="store_true", help="브라우저를 자동으로 열지 않는다")
    sub.add_parser("blogs")
    chk = sub.add_parser("check")
    chk.add_argument("--no-search", action="store_true", help="Codex 웹 검색 확인(1~3분)은 건너뛴다")
    run_p = sub.add_parser("run")
    run_p.add_argument("--draft", action="store_true", help="발행하지 않고 초안으로만 저장")
    run_p.add_argument("--force", action="store_true", help="오늘 이미 발행했어도 한 편 더")
    sub.add_parser("sync-history")
    args = parser.parse_args(argv)
    cfg = BloggerConfig.load()

    if args.cmd == "auth":
        from . import api
        api.authorize(cfg, open_browser=not args.no_browser)
        print(f"✅ 구글 블로거 로그인 완료. 토큰: {cfg.token_file}")
        for b in api.my_blogs(cfg):
            print(f"   - {b.get('name')}  {b.get('url')}  (ID {b.get('id')})")
        return 0
    if args.cmd == "blogs":
        from . import api
        for b in api.my_blogs(cfg):
            print(f"{b.get('id')}  {b.get('url')}  {b.get('name')}  글 {b.get('posts', {}).get('totalItems', '?')}편")
        return 0
    if args.cmd == "check":
        return _check(cfg, search=not args.no_search)
    if args.cmd == "run":
        from .pipeline import run
        return run(cfg, draft=args.draft, force=args.force)
    if args.cmd == "sync-history":
        from .pipeline import sync_history
        print(f"이력에 없던 {sync_history(cfg)}편을 추가했습니다: {cfg.history_file}")
        return 0
    return 1


def _check(cfg: BloggerConfig, search: bool) -> int:
    from . import api, writer
    ok = True

    print("1) Codex CLI: ", end="")
    if shutil.which(cfg.codex_bin):
        print(f"✅ {shutil.which(cfg.codex_bin)}")
    else:
        ok = False
        print(f"❌ '{cfg.codex_bin}' 명령이 없습니다 → npm install -g @openai/codex 후 codex 로그인")

    skill = writer.find_skill(cfg)
    print(f"2) {cfg.skill} 스킬: " + (f"✅ {skill}" if skill else
          "❌ 찾지 못했습니다 → ~/.codex/skills/ 아래에 있는지 확인하거나 .env의 BLOGGER_SKILL_PATH에 SKILL.md 경로를 적으세요"))
    ok &= bool(skill)

    print("3) 구글 블로거 로그인·블로그: ", end="")
    try:
        blog_id = api.resolve_blog_id(cfg)
        info = api.request(cfg, "GET", f"/blogs/{blog_id}")
        print(f"✅ {info.get('name')} {info.get('url')} (글 {info.get('posts', {}).get('totalItems', '?')}편)")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"❌ {e}")

    print(f"4) 예약 발행 시각: {cfg.publish_time + ' (한국 시각)' if cfg.publish_time else '없음(글이 완성되는 즉시 발행)'}")

    if search:
        from naver_autopost.openai_client import codex_selftest
        print("5) Codex(ChatGPT 구독) 웹 검색 ... (1~3분)")
        try:
            r = codex_selftest(cfg)
            print(f"   ✅ {r.get('title', '')} {r.get('url', '')}" if r.get("ok") else f"   ❌ 웹 검색 꺼짐: {r.get('reason')}")
            ok &= bool(r.get("ok"))
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"   ❌ {e}")
    print("모두 정상입니다." if ok else "실패한 항목의 메시지를 Claude에게 알려주세요.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
