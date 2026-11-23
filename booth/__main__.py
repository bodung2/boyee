"""캐릭터 공방 부스 노트북 명령.

  python -m booth check          설정·웹앱·Codex·프린터·패들렛을 한 번에 확인
  python -m booth run            부스 시작(창을 켜 두면 계속 그림을 처리). --fake: ChatGPT 없이 연습
  python -m booth qr             QR 안내판 그림(output/booth/qr_안내판.png)과 큰 화면 주소
  python -m booth print-test     예시 사진 한 장 인쇄
  python -m booth padlet-test    패들렛에 시험 글 하나 올리기
  python -m booth reprint ID     그 작업의 사진을 다시 인쇄
"""
from __future__ import annotations

import argparse
import logging
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from . import padlet, printer, worker
from .client import Server
from .config import BoothConfig
from .convert import convert, fake_convert

log = logging.getLogger("booth")
NEED_API = 3                      # Code.gs의 BOOTH_API가 이보다 작으면 다시 붙여 넣으라고 알린다


def _setup_logging(cfg: BoothConfig) -> None:
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S")
    for h in (logging.StreamHandler(sys.stdout), logging.FileHandler(cfg.out_dir / "booth.log", encoding="utf-8")):
        h.setFormatter(fmt)
        log.addHandler(h)
    log.setLevel(logging.INFO)


def cmd_check(cfg: BoothConfig) -> int:
    bad = 0

    def line(ok: bool | None, what: str, detail: str = "") -> None:
        nonlocal bad
        mark = {True: "✅", False: "❌", None: "➖"}[ok]
        bad += ok is False
        print(f"{mark} {what}{(' — ' + detail) if detail else ''}")

    try:
        info = Server(cfg).announce()
        line(True, "웹앱 연결", f"기다리는 그림 {info.get('waiting', 0)}장")
        if int(info.get("api") or 0) < NEED_API:
            line(False, "웹앱 코드", "옛 버전 — booth/apps_script/Code.gs를 다시 붙여 넣고 배포 관리 → 새 버전으로 배포")
    except Exception as e:                           # noqa: BLE001
        line(False, "웹앱 연결", str(e))
    line(bool(shutil.which(cfg.codex_bin)), "Codex CLI(ChatGPT 구독)",
         "설치됨 — 로그인은 'codex'를 실행해 확인" if shutil.which(cfg.codex_bin)
         else "없음: npm install -g @openai/codex 후 codex 실행 → Sign in with ChatGPT")
    if not cfg.print_on:
        line(None, "인쇄", "BOOTH_PRINTER가 비어 있어 자동 인쇄 안 함 — 부스에서 패들렛·갤러리 그림을 셀피 앱으로 인쇄")
    elif sys.platform != "win32":
        line(None, "인쇄", "윈도우가 아니라 확인하지 않음")
    else:
        try:
            import win32print
            name = printer.pick_printer(cfg.printer, printer.list_printers(), win32print.GetDefaultPrinter())
            line(True, "프린터", name)
        except Exception as e:                       # noqa: BLE001
            line(False, "프린터", str(e))
    if not cfg.padlet_on and cfg.padlet_url:
        line(True, "패들렛", "아이가 완성 화면의 '패들렛에 올리기' 버튼으로 직접 올림")
    elif not cfg.padlet_on:
        line(None, "패들렛", "PADLET_BOARD가 비어 있어 패들렛 버튼 없음(큰 화면 모아 보기 사용)")
    else:
        try:
            attrs = padlet.board_info(cfg.padlet_key, cfg.padlet_board).get("data", {}).get("attributes", {})
            line(True, "패들렛", f"보드 '{attrs.get('title', cfg.padlet_board)}'")
        except Exception as e:                       # noqa: BLE001
            line(False, "패들렛", str(e))
    return 1 if bad else 0


def cmd_qr(cfg: BoothConfig) -> int:
    if not cfg.webapp_url:
        print(".env에 BOOTH_WEBAPP_URL을 먼저 적어 주세요")
        return 1
    try:
        import qrcode
    except ImportError:
        print("qrcode 패키지가 없습니다: .venv\\Scripts\\python.exe -m pip install -r requirements.txt")
        return 1
    from .printer import _font
    q = qrcode.QRCode(border=2, box_size=24, error_correction=qrcode.constants.ERROR_CORRECT_M)
    q.add_data(cfg.webapp_url)
    q.make(fit=True)
    code = q.make_image(fill_color="black", back_color="white").convert("RGB").resize((1100, 1100), Image.NEAREST)
    page = Image.new("RGB", (1240, 1754), "#fff8ef")          # A4 세로 150dpi
    d = ImageDraw.Draw(page)
    d.text((620, 110), "캐릭터 공방", font=_font("bold", 96), fill="#ff7a59", anchor="mm")
    d.text((620, 215), "내가 그린 캐릭터를 AI가 새로운 모습으로!", font=_font("bold", 46), fill="#1f2937", anchor="mm")
    page.paste(code, (70, 290))
    steps = ["① 카메라로 QR을 찍어요", "② 별명 쓰고, 학습지 그림 찍고, 모습 고르기",
             "③ 보내기 → 완성 그림을 패들렛에 올리고 인쇄 받기" if not cfg.print_on
             else "③ 보내기 → 완성 사진이 프린터에서 나와요"]
    for i, s in enumerate(steps):
        d.text((110, 1440 + i * 80), s, font=_font("regular", 48), fill="#1f2937")
    out = cfg.out_dir / "qr_안내판.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    page.save(out)
    print(f"QR 안내판: {out}")
    print(f"아이들 주소: {cfg.webapp_url}")
    print(f"큰 화면 모아 보기: {cfg.webapp_url}?view=wall")
    return 0


def _sample_images(folder: Path) -> tuple[Path, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    art, orig = folder / "sample_result.png", folder / "sample_original.jpg"
    img = Image.new("RGB", (1024, 1024), "#ffe9d6")
    d = ImageDraw.Draw(img)
    d.ellipse((262, 200, 762, 700), fill="#ff9f6e", outline="#5b3a29", width=12)
    d.ellipse((392, 380, 452, 440), fill="#1f2937")
    d.ellipse((572, 380, 632, 440), fill="#1f2937")
    d.arc((432, 470, 592, 590), 20, 160, fill="#1f2937", width=10)
    d.rectangle((402, 690, 622, 900), fill="#6ec1ff", outline="#5b3a29", width=12)
    img.save(art)
    img.convert("L").convert("RGB").save(orig)
    return art, orig


def cmd_print_test(cfg: BoothConfig) -> int:
    art, orig = _sample_images(cfg.out_dir / "test")
    card = printer.compose(art, orig, "시험별명", "양모펠트 인형", "축구를 좋아하고 노래를 잘해요", cfg.title)
    out = cfg.out_dir / "test" / "print_test.jpg"
    card.save(out, "JPEG", quality=95)
    print(f"인쇄용 사진: {out}")
    try:
        print(f"인쇄 보냄 → {printer.print_image(card, cfg.printer, '캐릭터 공방 시험 인쇄')}")
    except Exception as e:                           # noqa: BLE001
        print(f"인쇄 실패: {e}")
        return 1
    return 0


def cmd_padlet_test(cfg: BoothConfig) -> int:
    if not cfg.padlet_on:
        print(".env에 PADLET_API_KEY와 PADLET_BOARD(보드 주소)를 적어 주세요")
        return 1
    try:
        padlet.create_post(cfg.padlet_key, cfg.padlet_board, "캐릭터 공방 연결 시험", "이 글은 지워도 됩니다.")
    except Exception as e:                           # noqa: BLE001
        print(f"실패: {e}")
        return 1
    print("패들렛에 시험 글을 올렸습니다. 보드에서 확인한 뒤 지워 주세요.")
    return 0


def cmd_reprint(cfg: BoothConfig, job_id: str) -> int:
    hits = sorted(cfg.out_dir.glob(f"*/{job_id}_인쇄.jpg"))
    if not hits:
        print(f"{job_id}의 인쇄용 사진을 찾지 못했습니다({cfg.out_dir})")
        return 1
    print(f"인쇄 보냄 → {printer.print_image(Image.open(hits[-1]), cfg.printer, f'캐릭터 공방 {job_id}')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m booth", description="캐릭터 공방 부스 노트북")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    r = sub.add_parser("run")
    r.add_argument("--fake", action="store_true", help="ChatGPT 없이 연습(색만 바꾼 그림)")
    r.add_argument("--once", action="store_true", help="그림 하나만 처리하고 끝")
    sub.add_parser("qr")
    sub.add_parser("print-test")
    sub.add_parser("padlet-test")
    rp = sub.add_parser("reprint")
    rp.add_argument("job_id")
    args = ap.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):          # 윈도우 콘솔에서 한글·이모지가 깨지지 않게
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    cfg = BoothConfig.load()
    if args.cmd == "check":
        return cmd_check(cfg)
    if args.cmd == "qr":
        return cmd_qr(cfg)
    if args.cmd == "print-test":
        return cmd_print_test(cfg)
    if args.cmd == "padlet-test":
        return cmd_padlet_test(cfg)
    if args.cmd == "reprint":
        return cmd_reprint(cfg, args.job_id)
    _setup_logging(cfg)
    server = Server(cfg)
    info = server.announce()
    if int(info.get("api") or 0) < NEED_API:
        log.warning("⚠ 웹앱 코드(Code.gs)가 옛 버전입니다. 저장소의 booth/apps_script/Code.gs를 다시 붙여 넣고 "
                    "배포 관리 → 새 버전으로 배포하세요(그러지 않으면 '잠금 시간초과'가 날 수 있습니다)")
    padlet_mode = "자동 게시" if cfg.padlet_on else ("아이가 직접 올림" if cfg.padlet_url else "끔")
    log.info("캐릭터 공방 시작 — 동시에 %d장, 인쇄 %s, 패들렛 %s%s", cfg.parallel,
             "켬" if cfg.print_on else "끔", padlet_mode,
             " [연습 모드: ChatGPT 안 씀]" if args.fake else "")
    log.info("이 창을 켜 두세요. 멈추려면 Ctrl+C")
    worker.run(cfg, server, fake_convert if args.fake else convert, once=args.once)
    return 0


if __name__ == "__main__":
    sys.exit(main())
