"""인쇄용 사진(엽서 100×148mm, 300dpi)을 만들고 윈도우 프린터(캐논 셀피 CP1500 등)로 보낸다."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from naver_autopost import images as _images
from naver_autopost.images import font_safe

W, H = 1181, 1748          # 100×148mm @300dpi(셀피 엽서 용지)
M = 70                     # 테두리 없이 인쇄할 때 잘려 나가는 가장자리를 피하는 여백
BG, INK, MUTED, ACCENT = "#fffaf3", "#1f2937", "#6b7280", "#ff7a59"


def _font(weight: str, size: int):
    """한글 글꼴(윈도우는 맑은 고딕). 없으면 기본 글꼴로라도 인쇄한다(글자가 네모로 보일 수 있음)."""
    try:
        return _images._font(weight, size)
    except RuntimeError:
        return ImageFont.load_default(size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int, lines: int) -> list[str]:
    out, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=font) > width:
            out.append(cur)
            cur = ch.lstrip()
            if len(out) == lines:
                out[-1] = out[-1][:-1] + "…"
                return out
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out[:lines]


def _paste_rounded(page: Image.Image, img: Image.Image, xy: tuple[int, int], radius: int) -> None:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, img.width - 1, img.height - 1), radius, fill=255)
    page.paste(img, xy, mask)


def compose(result: Path, original: Path | None, nickname: str, style_label: str, intro: str = "",
            title: str = "", day: date | None = None) -> Image.Image:
    nickname, style_label, intro, title = font_safe([nickname, style_label, intro, title])
    page = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(page)
    side = W - 2 * M
    art = ImageOps.fit(Image.open(result).convert("RGB"), (side, side), Image.LANCZOS)
    _paste_rounded(page, art, (M, M), 36)

    y = M + side + 44
    d.text((M, y), f"{nickname}의 캐릭터", font=_font("bold", 76), fill=INK)
    y += 100
    d.text((M, y), f"{style_label} 버전", font=_font("bold", 46), fill=ACCENT)
    y += 70
    thumb = 250
    for line in _wrap(d, intro, _font("regular", 38), W - 2 * M - thumb - 40, 3) if intro else []:
        d.text((M, y), line, font=_font("regular", 38), fill=INK)
        y += 52

    if original and Path(original).exists():
        small = ImageOps.fit(ImageOps.exif_transpose(Image.open(original)).convert("RGB"), (thumb, thumb), Image.LANCZOS)
        tx, ty = W - M - thumb, H - M - thumb
        _paste_rounded(page, small, (tx, ty), 20)
        cap = _font("regular", 26)
        d.text((tx + thumb / 2, ty - 10), "내가 그린 그림", font=cap, fill=MUTED, anchor="mb")
    foot = " · ".join(x for x in [title, (day or date.today()).strftime("%Y.%m.%d")] if x)
    d.text((M, H - M), foot, font=_font("regular", 32), fill=MUTED, anchor="ls")
    return page


def list_printers() -> list[str]:
    if sys.platform != "win32":
        return []
    import win32print
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    return [p[2] for p in win32print.EnumPrinters(flags)]


def pick_printer(wanted: str, available: list[str], default: str = "") -> str:
    """BOOTH_PRINTER에 'SELPHY'처럼 이름 일부만 적어도 찾는다. 비어 있으면 기본 프린터."""
    if not wanted:
        return default
    for name in available:
        if name.lower() == wanted.lower():
            return name
    for name in available:
        if wanted.lower() in name.lower():
            return name
    raise RuntimeError(f"프린터 '{wanted}'를 찾지 못했습니다. 연결된 프린터: {', '.join(available) or '없음'}")


def print_image(img: Image.Image, wanted: str = "", job_name: str = "캐릭터 공방") -> str:
    """윈도우 프린터로 바로 인쇄한다(대화상자 없음). 용지·테두리 없음 설정은 프린터 기본 설정을 따른다."""
    if sys.platform != "win32":
        raise RuntimeError("인쇄는 윈도우 노트북에서만 됩니다")
    import win32print
    import win32ui
    from PIL import ImageWin

    name = pick_printer(wanted, list_printers(), win32print.GetDefaultPrinter())
    dc = win32ui.CreateDC()
    dc.CreatePrinterDC(name)
    try:
        pw, ph = dc.GetDeviceCaps(8), dc.GetDeviceCaps(10)        # HORZRES, VERTRES: 인쇄 가능 영역(픽셀)
        if (pw > ph) != (img.width > img.height):
            img = img.rotate(90, expand=True)
        k = min(pw / img.width, ph / img.height)
        w, h = int(img.width * k), int(img.height * k)
        x, y = (pw - w) // 2, (ph - h) // 2
        dc.StartDoc(job_name)
        dc.StartPage()
        ImageWin.Dib(img.convert("RGB")).draw(dc.GetHandleOutput(), (x, y, x + w, y + h))
        dc.EndPage()
        dc.EndDoc()
    finally:
        dc.DeleteDC()
    return name
