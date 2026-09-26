"""사용법 (--profile 기본값: childhood, 교육 정책 글은 --profile edu):
  python -m naver_autopost login                             최초 1회 네이버 로그인(세션 저장)
  python -m naver_autopost run --profile childhood           오늘 글 1편 생성·검수·발행(스케줄러가 매일 실행)
  python -m naver_autopost run --profile childhood --dry-run 발행 버튼 직전까지만(설치 확인용)
  python -m naver_autopost preview output/childhood/날짜      post.json으로 이미지·HTML 미리보기만 생성
  python -m naver_autopost import-history 시트.csv --profile childhood  발행 이력 가져오기
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
    run_p = with_profile(sub.add_parser("run"))
    run_p.add_argument("--dry-run", action="store_true", help="발행 버튼은 누르지 않는다")
    run_p.add_argument("--force", action="store_true", help="오늘 이미 발행했어도 한 편 더 발행")
    prev = with_profile(sub.add_parser("preview"))
    prev.add_argument("dir", type=Path)
    imp = with_profile(sub.add_parser("import-history"))
    imp.add_argument("csv", type=Path)
    args = parser.parse_args(argv)
    cfg = Config.load(getattr(args, "profile", profiles.DEFAULT_PROFILE))

    if args.cmd == "login":
        from .publisher import login
        login(cfg)
        return 0
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
    if args.cmd == "import-history":
        from . import history
        added = history.import_csv(cfg.history_file, args.csv)
        print(f"{added}개 글을 발행 이력에 추가했습니다: {cfg.history_file}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
