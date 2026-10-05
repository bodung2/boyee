"""사용법:
  python -m blogger_autopost auth           최초 1회 구글 계정 승인(블로그 글쓰기 권한 토큰 저장)
  python -m blogger_autopost blogs          내 블로그 목록과 ID 보기
  python -m blogger_autopost check          Codex·스킬·구글 로그인·블로그 연결 한 번에 확인
  python -m blogger_autopost run            오늘 글 1편 생성·검수·발행(작업 스케줄러가 매일 실행)
  python -m blogger_autopost run --draft    발행하지 않고 블로거 '초안'으로만 저장(설치 확인용)
  python -m blogger_autopost sync-history   블로그에 있는 글을 발행 이력에 가져오기
  python -m blogger_autopost diagnose       검색 유입 진단 자료(글·공개 페이지·서치 콘솔)를 모아 GitHub에 올리기
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
    diag = sub.add_parser("diagnose")
    diag.add_argument("--no-push", action="store_true", help="GitHub에 올리지 않고 파일만 만든다")
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
    if args.cmd == "diagnose":
        return _diagnose(cfg, push=not args.no_push)
    if args.cmd == "sync-history":
        from .pipeline import sync_history
        added, removed, _ = sync_history(cfg)
        print(f"이력에 없던 {added}편 추가, 블로그에서 지운 {removed}편 제외: {cfg.history_file}")
        return 0
    return 1


def _diagnose(cfg: BloggerConfig, push: bool) -> int:
    import json

    from naver_autopost.__main__ import _push_diagnostics
    from naver_autopost.config import ROOT

    from . import diagnose
    print("블로그 글·공개 페이지·서치 콘솔 자료를 모으는 중입니다(1~3분)...")
    path = diagnose.run(cfg, ROOT / "diagnostics" / "blogger")
    r = json.loads(path.read_text(encoding="utf-8"))
    posts = r["posts"]
    print(f"  글 {len(posts)}편(예약 {len(r['scheduled'])}편), 평균 {sum(p['words'] for p in posts) // max(len(posts), 1)}단어")
    home = r["public_pages"]["home"]
    print(f"  홈 HTTP {home['status']}, 메타 설명: {'있음' if home.get('meta_description') else '없음'}, "
          f"사이트맵 URL {r['public_pages']['sitemap'].get('url_count')}개")
    sc = r["search_console"]
    if sc.get("_error"):
        print(f"  서치 콘솔: ❌ {sc['_error']}")
    else:
        rows = (sc.get("by_date") or {}).get("rows", [])
        print(f"  서치 콘솔(90일): 노출 {sum(x['impressions'] for x in rows):.0f}회, 클릭 {sum(x['clicks'] for x in rows):.0f}회")
        states = [i.get("coverageState") or i.get("error") for i in sc.get("inspections", [])]
        print(f"  색인 상태(최근 글): {states[:5]}")
    print(f"  저장: {path}")
    return 0 if not push else _push_diagnostics("Blogger search traffic diagnostics")


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

    print("4) 생성 그림용 구글 드라이브: ", end="")
    if cfg.illustrations <= 0:
        print("끔(BLOGGER_ILLUSTRATIONS=0)")
    elif not api.has_scope(cfg, api.DRIVE_SCOPE):
        ok = False
        print("❌ 드라이브 권한이 없습니다 → python -m blogger_autopost auth 다시 실행")
    else:
        from . import hosting
        try:
            hosting._folder_id(cfg)
            print(f"✅ 드라이브 '{hosting.FOLDER_NAME}' 폴더에 그림을 올립니다")
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"❌ {e}")

    print(f"5) 예약 발행 시각: {cfg.publish_time + ' (한국 시각)' if cfg.publish_time else '없음(글이 완성되는 즉시 발행)'}")
    print(f"6) 글쓰기 모델: {cfg.codex_model or '(Codex 기본값)'}, 추론 {cfg.codex_effort or '(기본값)'}"
          f" / 안 되면 {cfg.codex_fallback_model or '없음'}. 그림: 글마다 생성 그림 {cfg.illustrations}장"
          f" + 실제 사진 {cfg.photos}장(위키미디어 커먼즈)")

    if search:
        from naver_autopost.openai_client import CODEX_SELFTEST, _extract_json
        print("7) Codex(ChatGPT 구독) 모델·웹 검색 ... (1~3분)")
        try:
            r = _extract_json(writer._codex(cfg, CODEX_SELFTEST, None, "read-only", cfg.codex_timeout))
            if cfg.model_note:
                print(f"   {cfg.model_note}")
            print(f"   ✅ {r.get('title', '')} {r.get('url', '')}" if r.get("ok") else f"   ❌ 웹 검색 꺼짐: {r.get('reason')}")
            ok &= bool(r.get("ok"))
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"   ❌ {e}")
    print("모두 정상입니다." if ok else "실패한 항목의 메시지를 Claude에게 알려주세요.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
