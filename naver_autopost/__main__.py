"""사용법 (--profile 기본값: childhood, 교육 정책 글은 --profile edu):
  python -m naver_autopost login                             최초 1회 네이버 로그인(세션 저장)
  python -m naver_autopost run --profile childhood           오늘 글 1편 생성·검수·발행(스케줄러가 매일 실행)
  python -m naver_autopost run --profile childhood --dry-run 발행 버튼 직전까지만(설치 확인용)
  python -m naver_autopost preview output/childhood/날짜      post.json으로 이미지·HTML 미리보기만 생성
  python -m naver_autopost import-history 시트.csv --profile childhood  발행 이력 가져오기
  python -m naver_autopost check-ai                          그림 생성·Codex(ChatGPT) 웹 검색 연결 확인
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import profiles
from .config import Config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="naver_autopost")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def with_profile(p):
        p.add_argument("--profile", default=profiles.DEFAULT_PROFILE, choices=sorted(profiles.PROFILES))
        return p

    sub.add_parser("login")
    sub.add_parser("check-login")
    cap = sub.add_parser("capture-style")
    cap.add_argument("url", help="디자인 기준이 되는 기존 네이버 글 주소")
    cap.add_argument("--no-push", action="store_true", help="GitHub에 올리지 않고 파일만 만든다")
    lab = sub.add_parser("style-lab")
    lab.add_argument("--link", default="https://blog.naver.com/kkus_i/224403929458", help="링크 카드 시험용 글 주소")
    lab.add_argument("--no-push", action="store_true")
    prevw = with_profile(sub.add_parser("preview-editor"))
    prevw.add_argument("dir", nargs="?", type=Path, help="post.json이 있는 폴더(기본: 가장 최근 글)")
    prevw.add_argument("--no-push", action="store_true")
    prevw.add_argument("--style", choices=["native", "plain"], default="native", help="시험할 서식 방식")
    lab3 = sub.add_parser("style-lab3")
    lab3.add_argument("url", nargs="?", default="https://blog.naver.com/kkus_i/224403935438")
    lab3.add_argument("--no-push", action="store_true")
    lab2 = sub.add_parser("style-lab2")
    lab2.add_argument("url", nargs="?", default="https://blog.naver.com/kkus_i/224403935438")
    lab2.add_argument("--no-push", action="store_true")
    run_p = with_profile(sub.add_parser("run"))
    run_p.add_argument("--dry-run", action="store_true", help="발행 버튼은 누르지 않는다")
    run_p.add_argument("--force", action="store_true", help="오늘 이미 발행했어도 한 편 더 발행")
    prev = with_profile(sub.add_parser("preview"))
    prev.add_argument("dir", type=Path)
    rec = with_profile(sub.add_parser("record"))
    rec.add_argument("url", help="발행된 글 주소(프로그램이 주소를 확인하지 못했을 때 직접 기록)")
    rec.add_argument("--date", help="글 날짜 YYYY-MM-DD(기본: 오늘)")
    forget = with_profile(sub.add_parser("forget"))
    forget.add_argument("target", help="지운 글 주소 또는 날짜(YYYY-MM-DD)")
    imp = with_profile(sub.add_parser("import-history"))
    imp.add_argument("csv", type=Path)
    with_profile(sub.add_parser("check-ai"))
    args = parser.parse_args(argv)
    cfg = Config.load(getattr(args, "profile", profiles.DEFAULT_PROFILE))

    if args.cmd == "login":
        from .publisher import login
        login(cfg)
        return 0
    if args.cmd == "check-login":
        from .publisher import check_session
        ok = check_session(cfg)
        print("네이버 로그인 유지됨 ✅" if ok else "네이버 로그인이 풀려 있습니다 ❌ → python -m naver_autopost login")
        return 0 if ok else 1
    if args.cmd == "style-lab":
        from .config import ROOT
        from .publisher import style_lab
        res = style_lab(cfg, ROOT / "diagnostics" / "style", ROOT / "diagnostics" / "lab", args.link)
        for name, r in res["experiments"].items():
            print(f"  {'✅' if r.get('ok') else '❌'} {name}: {r.get('classes') or r.get('error')}")
        return 0 if args.no_push else _push_diagnostics("Style lab results")
    if args.cmd == "preview-editor":
        cfg.style_mode = args.style
        return _preview_editor(cfg, args.dir, push=not args.no_push)
    if args.cmd == "style-lab3":
        from .config import ROOT
        from .publisher import style_lab3
        res = style_lab3(cfg, args.url, ROOT / "diagnostics" / "lab3")
        for k, v in res.items():
            if isinstance(v, dict) and "diff" in v:
                print(f"  {k}: 저장소 변화 {len(v['diff'])}건 {[d['key'] for d in v['diff']][:5]}")
            else:
                print(f"  {k}: {str(v)[:120]}")
        return 0 if args.no_push else _push_diagnostics("Style lab 3 results")
    if args.cmd == "style-lab2":
        from .config import ROOT
        from .publisher import style_lab2
        res = style_lab2(cfg, args.url, ROOT / "diagnostics" / "lab2")
        for k, v in res.items():
            size = len(json.dumps(v, ensure_ascii=False))
            print(f"  {k}: {size:,}자" + (" ⚠️" if "ERR" in str(v)[:20] or "__error" in str(v)[:40] else ""))
        return 0 if args.no_push else _push_diagnostics("Style lab 2 results")
    if args.cmd == "capture-style":
        return _capture_style(cfg, args.url, push=not args.no_push)
    if args.cmd == "run":
        from .pipeline import run
        return run(cfg, dry_run=args.dry_run, force=args.force)
    if args.cmd == "preview":
        from . import content
        from .pipeline import render_images
        post = content.normalize(json.loads((args.dir / "post.json").read_text(encoding="utf-8")))
        for err in content.validate(post, cfg.profile):
            print("검증 문제:", err)
        imgs = render_images(cfg, post, args.dir)
        body = post["body_html"]
        for name, path in imgs.items():
            if name != "thumbnail":
                body = content.IMAGE_MARKER.sub(
                    lambda m, n=name, p=path: f'<p><img src="{p.name}" width="640"></p>' if m.group(1) == n else m.group(0),
                    body)
        html = (f'<!doctype html><meta charset="utf-8"><title>{post["title"]}</title>'
                f'<body style="max-width:760px;margin:40px auto;padding:0 16px;font-family:sans-serif;line-height:1.8">'
                f'<h1>{post["title"]}</h1><img src="{imgs["thumbnail"].name}" width="400">{body}'
                f'<p>{" ".join("#" + t for t in post["tags"])}</p></body>')
        (args.dir / "preview.html").write_text(html, encoding="utf-8")
        print("미리보기:", args.dir / "preview.html")
        return 0
    if args.cmd == "check-ai":
        return _check_ai(cfg)
    if args.cmd == "record":
        from . import history
        from .pipeline import today_kst
        date = args.date or today_kst()
        post_path = cfg.output_dir / date / "post.json"
        post = json.loads(post_path.read_text(encoding="utf-8")) if post_path.exists() else {}
        url = args.url.split("?")[0].rstrip("/")
        history.append(cfg.history_file, {
            "date": date, "title": post.get("title", ""), "url": url, "topic": post.get("topic", ""),
            "lane": post.get("lane", ""), "cluster": post.get("cluster", ""), "domain": post.get("domain"),
            "tags": post.get("tags", []), "source": "autopost",
        })
        print(f"  기록했습니다: {date} {post.get('title', '(제목 없음)')} {url}")
        return 0
    if args.cmd == "forget":
        from . import history
        removed = history.remove(cfg.history_file, args.target)
        for e in removed:
            print(f"  이력에서 뺐습니다: {e.get('date')} {e.get('title')} {e.get('url')}")
        if not removed:
            print("  일치하는 발행 이력이 없습니다(이미 없거나 주소가 다릅니다).")
        return 0
    if args.cmd == "import-history":
        from . import history
        added = history.import_csv(cfg.history_file, args.csv)
        print(f"{added}개 글을 발행 이력에 추가했습니다: {cfg.history_file}")
        return 0
    return 1


def _capture_style(cfg: Config, url: str, push: bool) -> int:
    """기존 글의 디자인 구조를 diagnostics/style 에 저장하고, GitHub에 올려 Claude가 볼 수 있게 한다."""
    from .config import ROOT
    from .publisher import capture_style
    out = ROOT / "diagnostics" / "style"
    files = capture_style(cfg, url, out)
    for f in files:
        print(f"  저장: {f.relative_to(ROOT)} ({f.stat().st_size:,} bytes)")
    if not push:
        return 0
    return _push_diagnostics(f"Capture blog design sample from {url}")


def _preview_editor(cfg: Config, post_dir: Path | None, push: bool) -> int:
    """저장된 글(post.json)을 새 디자인으로 에디터에 넣어 보고(발행 안 함) 결과를 올린다."""
    from . import content
    from .config import ROOT
    from .pipeline import render_images
    from .publisher import publish
    if post_dir is None:
        candidates = sorted((p for p in cfg.output_dir.glob("*/post.json") if "rejected" not in p.parent.name),
                            key=lambda p: p.stat().st_mtime)
        if not candidates:
            print("post.json이 있는 글이 없습니다. 먼저 run --dry-run 으로 글을 만드세요.")
            return 1
        post_dir = candidates[-1].parent
    post = content.normalize(json.loads((post_dir / "post.json").read_text(encoding="utf-8")))
    imgs = render_images(cfg, post, post_dir)
    diag = ROOT / "diagnostics" / "preview"
    print(f"미리보기: {post['title']} ({post_dir})")
    publish(cfg, post, imgs, dry_run=True, diag_dir=diag)
    print(f"  에디터 화면: {diag / 'editor_full.png'}")
    return 0 if not push else _push_diagnostics("Editor preview with native style")


def _push_diagnostics(message: str) -> int:
    """diagnostics 폴더를 GitHub에 올려 Claude가 볼 수 있게 한다."""
    import subprocess

    from .config import ROOT
    git = ["git", "-c", "user.name=naver-autopost", "-c", "user.email=naver-autopost@localhost"]
    steps = [git + ["pull", "--no-rebase", "--no-edit"], git + ["add", "diagnostics"],
             git + ["commit", "-m", message], git + ["push"]]
    for cmd in steps:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0 and "nothing to commit" not in (r.stdout + r.stderr):
            print(f"  ❌ git {cmd[5]} 실패:\n{(r.stdout + r.stderr).strip()[-600:]}")
            return 1
    print("✅ 결과를 GitHub에 올렸습니다. Claude에게 '올렸어'라고 알려주세요.")
    return 0


def _check_ai(cfg: Config) -> int:
    import logging

    from . import openai_client
    from .pipeline import image_generator
    logging.basicConfig(level=logging.INFO, format="  %(message)s")
    ok = True

    print(f"1) 그림 생성 확인 ({cfg.image_backend}) ... (1~3분)")
    out = cfg.output_dir.parent / "check" / f"{cfg.image_backend}_test.png"
    try:
        image_generator(cfg).generate_image(
            cfg, "a cute flat vector illustration of a child stacking colorful wooden blocks in a Korean living room, "
                 "warm pastel light, wide 16:9", out)
        print(f"   ✅ 성공: {out}  (그림을 열어 확인해 보세요)")
    except Exception as e:
        ok = False
        print(f"   ❌ 실패: {e}")

    print("2) Codex(ChatGPT 구독) 웹 검색 확인 ... (1~3분)")
    try:
        r = openai_client.codex_selftest(cfg)
        if r.get("ok"):
            print(f"   ✅ 성공: {r.get('date', '')} {r.get('title', '')}\n      {r.get('url', '')}")
        else:
            ok = False
            print(f"   ❌ Codex는 실행되지만 웹 검색이 꺼져 있습니다: {r.get('reason', '')}")
    except Exception as e:
        ok = False
        print(f"   ❌ 실패: {e}")
    print("모두 정상입니다." if ok else "실패한 항목의 메시지를 Claude에게 알려주세요.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
