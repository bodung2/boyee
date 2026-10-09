"""사용법:
  python -m blogger_autopost auth           최초 1회 구글 계정 승인(블로그 글쓰기 권한 토큰 저장)
  python -m blogger_autopost blogs          내 블로그 목록과 ID 보기
  python -m blogger_autopost check          Codex·스킬·구글 로그인·블로그 연결 한 번에 확인
  python -m blogger_autopost run            오늘 글 1편 생성·검수·발행(작업 스케줄러가 매일 실행)
  python -m blogger_autopost run --draft    발행하지 않고 블로거 '초안'으로만 저장(설치 확인용)
  python -m blogger_autopost sync-history   블로그에 있는 글을 발행 이력에 가져오기
  python -m blogger_autopost diagnose       검색 유입 진단 자료(글·공개 페이지·서치 콘솔)를 모아 GitHub에 올리기
  python -m blogger_autopost check-meta     글 페이지에 검색 설명(meta description)이 실제로 나오는지 확인
  python -m blogger_autopost fix-posts      이미 발행한 글 다듬기 미리보기(그림을 첫 문단 뒤로, 관련 글 링크)
  python -m blogger_autopost fix-posts --apply   실제로 고치기(바꾸기 전 본문은 output/blogger/backup/에 저장)
  python -m blogger_autopost refresh-post today   오늘 글을 새 양식(그림 3장·인포그래픽·경험 문단)으로 바꾼 미리보기
  python -m blogger_autopost refresh-post today --apply   실제로 고치기(날짜 YYYY-MM-DD나 글 주소도 됨)
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

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
    sub.add_parser("check-meta")
    fix = sub.add_parser("fix-posts")
    fix.add_argument("--apply", action="store_true", help="미리보기가 아니라 실제로 블로그 글을 고친다")
    fix.add_argument("--restore", type=Path, help="이 백업 폴더의 본문으로 글을 되돌린다")
    ref = sub.add_parser("refresh-post")
    ref.add_argument("target", nargs="?", default="today", help="today / 2026-10-06 / 글 주소 / 글 ID")
    ref.add_argument("--apply", action="store_true", help="미리보기가 아니라 실제로 블로그 글을 고친다")
    ref.add_argument("--again", action="store_true", help="만들어 둔 미리보기를 버리고 처음부터 다시 만든다")
    ref.add_argument("--no-persona", action="store_true", help="경험·'내 생각' 문단은 넣지 않는다")
    ref.add_argument("--images", action="store_true", help="글에 그림이 이미 있어도 사진·생성 그림을 넣는다")
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
    if args.cmd == "check-meta":
        return _check_meta(cfg)
    if args.cmd == "fix-posts":
        return _fix_posts(cfg, args.apply, args.restore)
    if args.cmd == "refresh-post":
        return _refresh_post(cfg, args)
    if args.cmd == "diagnose":
        return _diagnose(cfg, push=not args.no_push)
    if args.cmd == "sync-history":
        from .pipeline import sync_history
        added, removed, _ = sync_history(cfg)
        print(f"이력에 없던 {added}편 추가, 블로그에서 지운 {removed}편 제외: {cfg.history_file}")
        return 0
    return 1


def _check_meta(cfg: BloggerConfig) -> int:
    from . import diagnose
    rows = diagnose.check_meta(cfg)
    if rows and not any(r["rendered"] for r in rows):
        print("(참고: 브라우저를 띄우지 못해 스크립트 실행 전 HTML로 확인합니다. 테마 스크립트로 채우는 설명은 안 보일 수 있습니다\n"
              " → .venv\\Scripts\\python.exe -m playwright install chromium 후 다시 실행)")
    ok = True
    for r in rows:
        if r["tags"] == 1 and r["meta_description"]:
            print(f"✅ {r['title']}\n     {r['meta_description']}")
        elif r["tags"] > 1:
            ok = False
            print(f"⚠️ {r['title']}: 검색 설명 태그가 {r['tags']}개입니다(테마에 두 번 들어감)")
        else:
            ok = False
            why = ("태그는 있는데 내용이 비어 있음 → 테마 코드가 예전 3줄이거나, 새 스크립트가 본문을 못 찾음" if r["tags"]
                   else "검색 설명 태그 자체가 없음 → 테마에 코드가 아직 없거나, 저장이 안 됐거나, head 밖에 들어감")
            print(f"❌ {r['title']}: {why} (HTTP {r['status']})")
            if r.get("og_description"):
                print(f"     (참고: 공유용 설명 og:description은 있음: {r['og_description'][:90]})")
    print("모든 글에 검색 설명이 나옵니다." if ok and rows else
          "검색 설명이 빠진 글이 있습니다 → docs/blogger-meta-description.xml 안내대로 테마에 넣었는지 확인하세요.")
    return 0 if ok else 1


def _fix_posts(cfg: BloggerConfig, apply: bool, restore: Path | None) -> int:
    from . import fixposts
    if restore:
        print(f"{fixposts.restore(cfg, restore)}편을 백업 본문으로 되돌렸습니다.")
        return 0
    report = fixposts.run(cfg, apply=apply)
    if not report:
        print("고칠 글이 없습니다(이미 다듬어져 있음).")
        return 0
    for r in report:
        print(f"\n■ {r['title']}")
        if r["moved_images"]:
            print(f"  A. 맨 앞 그림 {r['moved_images']}개 → 첫 문단 뒤로")
            print(f"     전: {r['opening_before']}")
            print(f"     후: {r['opening_after']}")
        print(f"  B. 관련 글: {', '.join(r['related']) or '(없음)'}")
    if apply:
        print(f"\n✅ {len(report)}편을 고쳤습니다. 되돌리려면: python -m blogger_autopost fix-posts --restore "
              f"{cfg.output_dir / 'backup'}\\<날짜폴더>")
    else:
        print("\n(미리보기입니다. 실제로 고치려면: python -m blogger_autopost fix-posts --apply)")
    return 0


def _refresh_post(cfg: BloggerConfig, args) -> int:
    from . import refresh
    from .pipeline import setup_logging
    setup_logging(cfg, "blogger-refresh")
    try:
        r = refresh.run(cfg, args.target, apply=args.apply, again=args.again, use_persona=not args.no_persona,
                        images=args.images)
    except RuntimeError as e:
        print(f"❌ {e}")
        return 1
    print(f"\n■ {r['title']}\n  {r['url'] or '(예약 글)'}")
    print(f"  그림: 모두 {r['images']}장 ({r['images_note'] or '추가 없음'})")
    print(f"  경험·내 생각 문단: {r['persona_paragraphs']}개 {', '.join(r['persona_used'])}")
    print(f"  관련 글: {', '.join(r['related']) or '(없음)'}")
    print(f"  미리보기: {r['preview']}  (더블클릭하면 브라우저로 열립니다)")
    if r["saved"]:
        print(f"\n✅ 블로그 글을 고쳤습니다. 되돌리려면: python -m blogger_autopost fix-posts --restore {r['backup']}")
    else:
        print(f"\n(미리보기입니다. 괜찮으면: python -m blogger_autopost refresh-post {args.target} --apply\n"
              f" 다시 만들려면: python -m blogger_autopost refresh-post {args.target} --again)")
    return 0


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
    for row in r.get("redirects", [])[:3]:
        g = row["googlebot_mobile"]
        chain = " → ".join(str(h["status"]) for h in g["hops"])
        print(f"  구글 휴대폰 로봇으로 열기: {g['verdict']} ({chain}) {row['url']}")
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

    from naver_autopost import persona
    ptext = persona.load()
    print("4-1) 작가 페르소나: " + (f"✅ {persona.path()} (에피소드 {len(persona.episode_ids(ptext))}개)" if ptext
                                   else f"없음 → 경험·생각 없이 씁니다({persona.path()}에 두면 적용)"))
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
