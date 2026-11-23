"""사용법:
  python -m worksheets seed 명세서.docx      워크북 명세서(docx) 예시 페이지에서 고정 캐릭터·사물 원화를 보관함에 넣는다
                                              (data/worksheets 폴더에 docx를 넣어 두면 활동지를 만들 때 알아서 한다)
  python -m worksheets library               보관함 그림 목록
  python -m worksheets render spec.json 폴더  설계서 하나를 그려 본다(드라이브에 올리지 않음)
  python -m worksheets prepare --day 2026-11-24  그날 쓸 활동지를 미리 만든다(설계·원화·그리기·검수). 그날 나눔글이 그대로 씀
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from naver_autopost.config import Config

from . import library, render


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m worksheets", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed")
    s.add_argument("docx")
    sub.add_parser("library")
    pr = sub.add_parser("prepare")
    pr.add_argument("--day", required=True)
    r = sub.add_parser("render")
    r.add_argument("spec")
    r.add_argument("out")
    args = p.parse_args(argv)
    cfg = Config.load("worksheet")
    lib = library.root(cfg.data_dir)
    if args.cmd == "prepare":
        import logging
        from .build import build, prepared_dir
        cfg.log_dir.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                            handlers=[logging.StreamHandler(),
                                      logging.FileHandler(cfg.log_dir / f"worksheet-prepare-{args.day}.log",
                                                          encoding="utf-8")])
        out = prepared_dir(cfg, args.day)
        if (out / "worksheet.json").exists():
            print(f"이미 준비돼 있습니다: {out}")
            return 0
        info = build(cfg, out, args.day)
        print(f"준비 완료: {info['title']} ({info['pdf_pages']}장) → {out}")
        return 0
    if args.cmd == "seed":
        added = library.seed(Path(args.docx), lib)
        print(f"원화 {len(added)}개를 넣었습니다: {', '.join(added) or '(이미 있음)'} → {lib}")
    elif args.cmd == "library":
        for a in library.catalog(lib):
            print(f"{a['key']:24} {a['kind']:5} {'★' if a.get('master') else ' '} {a['name']} (쓴 횟수 {a['used']})")
    else:
        spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
        res = render.render(spec, lib, Path(args.out), f"https://blog.naver.com/{cfg.blog_id}" if cfg.blog_id else "")
        print(json.dumps(res, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
