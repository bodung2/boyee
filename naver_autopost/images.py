"""대표 썸네일(600x600)과 요약 카드(1200x700)를 Pillow로 그린다.

education-insight-extraction 4단계 레이아웃 규칙을 따른다: 가운데 정렬,
실제 렌더링 폭으로 x 계산, 메인 줄 수에 따라 보조 문구 y를 동적으로 계산.
"""
from __future__ import annotations

import platform
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BG = "#1f3a5f"          # 교육 정책 카테고리색(짙은 남색)
ACCENT = "#ffd166"      # 포인트색
WHITE = "#ffffff"
INK = "#1d1d1f"
MUTED = "#6b7280"
CHIP_BG = "#e8eef6"

_FONT_CANDIDATES = {
    "regular": [
        "C:/Windows/Fonts/malgun.ttf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    ],
    "bold": [
        "C:/Windows/Fonts/malgunbd.ttf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    ],
}


def _font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES[weight]:
        if Path(path).exists():
            # AppleSDGothicNeo.ttc는 index 6 근처가 Bold, NotoSansCJK.ttc는 index 1이 한국어(KR) 글꼴이다.
            if path.endswith("AppleSDGothicNeo.ttc"):
                index = 6 if weight == "bold" else 0
            elif "NotoSansCJK" in path:
                index = 1
            else:
                index = 0
            try:
                return ImageFont.truetype(path, size, index=index)
            except OSError:
                return ImageFont.truetype(path, size)
    raise RuntimeError(f"한글 폰트를 찾지 못했습니다({platform.system()}). 맑은 고딕/Noto Sans CJK를 설치하세요.")


def _width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    left, _, right, _ = draw.textbbox((0, 0), text, font=font)
    return right - left


def _wrap(draw, text: str, font, max_width: int) -> list[str]:
    """단어(공백) 단위로 줄바꿈하고, 한 단어가 너무 길면 글자 단위로 자른다."""
    lines: list[str] = []
    current = ""
    for word in text.split(" "):
        candidate = f"{current} {word}".strip()
        if _width(draw, candidate, font) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = ""
        for ch in word:
            if _width(draw, current + ch, font) <= max_width:
                current += ch
            else:
                lines.append(current)
                current = ch
    if current:
        lines.append(current)
    return lines


def _draw_chip(draw, text: str, center_x: int, y: int, font, fill, text_fill) -> int:
    pad_x, pad_y = 28, 14
    w = _width(draw, text, font)
    _, top, _, bottom = draw.textbbox((0, 0), text, font=font)
    h = bottom - top
    x0 = center_x - (w + pad_x * 2) // 2
    draw.rounded_rectangle([x0, y, x0 + w + pad_x * 2, y + h + pad_y * 2], radius=(h + pad_y * 2) // 2, fill=fill)
    draw.text((x0 + pad_x, y + pad_y - top), text, font=font, fill=text_fill)
    return y + h + pad_y * 2


def _draw_centered_line(draw, text: str, y: int, font, canvas_w: int, fill, highlight: str = "") -> None:
    x = (canvas_w - _width(draw, text, font)) // 2
    if highlight and highlight in text:
        before, after = text.split(highlight, 1)
        for part, color in ((before, fill), (highlight, ACCENT), (after, fill)):
            if part:
                draw.text((x, y), part, font=font, fill=color)
                x += _width(draw, part, font)
    else:
        draw.text((x, y), text, font=font, fill=fill)


THUMBNAIL_SIZE = 600       # 블로그 본문 맨 위에 600x600, 가운데 정렬로 넣는다
_DRAW_SIZE = 1200          # 글자가 선명하도록 크게 그린 뒤 줄인다
INFOGRAPHIC_WIDTH = 600    # 인포그래픽은 가로 600px(세로는 비율대로), 가운데 정렬


def fit_width(src: Path, out: Path, width: int) -> Path:
    """비율을 유지한 채 가로를 width로 맞춘다."""
    img = Image.open(src).convert("RGB")
    if img.width != width:
        img = img.resize((width, max(1, round(img.height * width / img.width))), Image.LANCZOS)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)
    return out


def _save_thumbnail(img: Image.Image, out: Path, size: int) -> Path:
    if img.size != (size, size):
        img = img.resize((size, size), Image.LANCZOS)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)
    return out


def make_thumbnail(thumb: dict, out: Path, size: int = THUMBNAIL_SIZE) -> Path:
    final_size, size = size, _DRAW_SIZE
    img = Image.new("RGB", (size, size), BG)
    draw = ImageDraw.Draw(img)
    main_font_size = 120
    main_font = _font("bold", main_font_size)
    sub_font = _font("regular", 58)
    chip_font = _font("bold", 40)
    max_w = size - 160

    main_lines = _wrap(draw, thumb["main"], main_font, max_w)
    while len(main_lines) > 2 and main_font_size > 70:
        main_font_size -= 10
        main_font = _font("bold", main_font_size)
        main_lines = _wrap(draw, thumb["main"], main_font, max_w)
    sub_lines = _wrap(draw, thumb.get("sub", ""), sub_font, max_w) if thumb.get("sub") else []

    line_gap = int(main_font_size * 1.25)
    sub_gap = 76
    gap_after_chip = 80
    min_gap = int(main_font_size * 0.7)          # 메인·보조 사이 최소 여백(0.6~0.8배)
    chip_h = 40 + 28
    block_h = chip_h + gap_after_chip + line_gap * len(main_lines)
    if sub_lines:
        block_h += min_gap + sub_gap * len(sub_lines)
    y = (size - block_h) // 2

    y = _draw_chip(draw, thumb.get("chip", "교육 정책"), size // 2, y, chip_font, ACCENT, BG) + gap_after_chip
    for line in main_lines:
        _draw_centered_line(draw, line, y, main_font, size, WHITE, thumb.get("highlight", ""))
        y += line_gap
    main_bottom_y = y
    y = main_bottom_y + min_gap
    for line in sub_lines:
        _draw_centered_line(draw, line, y, sub_font, size, "#dbe4f0")
        y += sub_gap

    return _save_thumbnail(img, out, final_size)


def make_card(card: dict, out: Path, width: int = 1200, tone: str = BG) -> Path:
    title_font = _font("bold", 52)
    bullet_font = _font("regular", 36)
    chip_font = _font("bold", 28)
    footer_font = _font("regular", 24)
    margin = 72
    max_w = width - margin * 2 - 40

    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    title_lines = _wrap(probe, card["title"], title_font, width - margin * 2)
    bullet_blocks = [_wrap(probe, b, bullet_font, max_w) for b in card["bullets"]]
    footer_lines = _wrap(probe, card.get("footer", ""), footer_font, width - margin * 2) if card.get("footer") else []

    height = 24 + 40 + 60 + 20 + 68 * len(title_lines) + 30
    height += sum(52 * len(block) + 22 for block in bullet_blocks)
    height += 40 + 34 * len(footer_lines) + 50
    height = max(height, 700)

    img = Image.new("RGB", (width, height), WHITE)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, width, 24], fill=tone)
    y = 64
    chip_w = _width(draw, card.get("chip", "교육 정책"), chip_font) + 44
    draw.rounded_rectangle([margin, y, margin + chip_w, y + 50], radius=25, fill=CHIP_BG)
    draw.text((margin + 22, y + 8), card.get("chip", "교육 정책"), font=chip_font, fill=tone)
    y += 50 + 30
    for line in title_lines:
        draw.text((margin, y), line, font=title_font, fill=INK)
        y += 68
    y += 30
    for block in bullet_blocks:
        draw.ellipse([margin + 4, y + 16, margin + 18, y + 30], fill=tone)
        for line in block:
            draw.text((margin + 40, y), line, font=bullet_font, fill=INK)
            y += 52
        y += 22
    y += 10
    draw.line([margin, y, width - margin, y], fill="#e5e7eb", width=2)
    y += 26
    for line in footer_lines:
        draw.text((margin, y), line, font=footer_font, fill=MUTED)
        y += 34

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)
    return out


# ---------------------------------------------------------------- 유아 블로그(시리즈 고정 템플릿)
# early-childhood-insight-extraction 4-1: 질문형·다크, 좌상단 고정 좌표, 영역별 배경 톤.

CHILDHOOD_TONES = {
    "N": "#1a4d7a",   # 초기수학 딥블루
    "M": "#2f6b3d",   # 감각·운동 딥그린
    "C": "#155e52",   # 인지·공간 딥틸
    "L": "#2c2960",   # 언어·문해 인디고
    "S": "#7a2e46",   # 사회정서 버건디
    "E": "#4a2a6b",   # 실행기능 딥퍼플
    "A": "#146b6b",   # 창의·탐구 딥청록
}
CHILDHOOD_DEFAULT_TONE = "#1a4d7a"
WARM_TONES = {"#7a2e46", "#7a3a12"}


def childhood_tone(domain: str | None) -> str:
    return CHILDHOOD_TONES.get((domain or "").strip().upper()[:1], CHILDHOOD_DEFAULT_TONE)


def make_thumbnail_childhood(thumb: dict, domain: str | None, out: Path, size: int = THUMBNAIL_SIZE) -> Path:
    final_size, size = size, _DRAW_SIZE
    tone = childhood_tone(domain)
    accent = "#ffcf5a" if tone in WARM_TONES else "#ffd23f"
    img = Image.new("RGB", (size, size), tone)
    draw = ImageDraw.Draw(img)

    chip_font = _font("bold", 38)
    chip = thumb.get("chip", "유아교육")
    draw.rounded_rectangle([90, 110, 90 + _width(draw, chip, chip_font) + 56, 190], radius=26, fill=accent)
    draw.text((118, 129), chip, font=chip_font, fill=tone)

    lines = [line for line in (thumb.get("main_lines") or []) if line][:3]
    font_size = 130
    main_font = _font("bold", font_size)
    # 한 줄이라도 캔버스를 넘으면 글자 크기를 줄인다(우측 여백 90 유지).
    while font_size > 90 and any(_width(draw, line, main_font) > size - 180 for line in lines):
        font_size -= 6
        main_font = _font("bold", font_size)
    line_h = int(font_size * 1.22)
    y = 300
    y_end = y
    for line in lines:
        draw.text((90, y), line, font=main_font, fill=WHITE)
        y_end = draw.textbbox((90, y), line, font=main_font)[3]   # 실제로 그려진 글자 아래끝
        y += line_h
    draw.rectangle([96, y_end + 16, 96 + 320, y_end + 34], fill=accent)
    if thumb.get("sub"):
        draw.text((96, y_end + 84), thumb["sub"], font=_font("regular", 48), fill=accent)

    return _save_thumbnail(img, out, final_size)
