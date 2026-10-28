"""대표 썸네일(600x600)과 요약 카드(1200x700)를 Pillow로 그린다.

education-insight-extraction 4단계 레이아웃 규칙을 따른다: 가운데 정렬,
실제 렌더링 폭으로 x 계산, 메인 줄 수에 따라 보조 문구 y를 동적으로 계산.
"""
from __future__ import annotations

import platform
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

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


# 교육 블로그: 주제 레인(edu-auto-post의 A~E)마다 배경색을 정해, 썸네일만 봐도 어떤 주제인지 구분되게 한다.
# 흰 글자·노란 강조가 모두 잘 읽히는 짙은 색만 쓴다(대비 4.5 이상).
EDU_TONES = {
    "A": "#146356",   # 경기교육 정책·이슈 — 딥그린
    "B": "#87400f",   # 교직 실무 꿀팁 — 번트오렌지
    "C": "#1f3a5f",   # 전국 교육부 정책 — 남색(기존 색)
    "D": "#8c2f4b",   # 학부모 관심 교육정보 — 베리
    "E": "#4b2c82",   # 교육 핵심 동향·인사이트 — 딥퍼플
}


def edu_tone(lane: str | None) -> str:
    """레인 글자(A~E, '(C)'·'C 레인'도 됨)의 배경색. 모르면 기존 남색."""
    letter = next((ch for ch in str(lane or "").upper() if ch.isalpha()), "")
    return EDU_TONES.get(letter, BG)


def make_thumbnail(thumb: dict, out: Path, size: int = THUMBNAIL_SIZE, tone: str = BG) -> Path:
    final_size, size = size, _DRAW_SIZE
    img = Image.new("RGB", (size, size), tone)
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

    y = _draw_chip(draw, thumb.get("chip", "교육 정책"), size // 2, y, chip_font, ACCENT, tone) + gap_after_chip
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


# 투자 블로그(bold): 레인별 진한 배경. 홈피드 썸네일에서 노란 큰 글씨가 잘 보이는 어두운 톤.
INVEST_TONES = {
    "A": "#14325c",   # 내 위치(자산·소득) 딥네이비
    "B": "#5c1f24",   # 부동산 딥레드
    "C": "#6b3a12",   # 일상 지출 딥브라운
    "D": "#1f4a5c",   # 일·직장 딥틸
    "E": "#3b1f5e",   # 개미 vs 통계 딥퍼플
    "F": "#0f4d3a",   # 제도·세금·연금 딥그린
    "G": "#2b2b33",   # 시장·금리 차콜
}


def invest_tone(lane: str | None) -> str:
    letter = next((ch for ch in str(lane or "").upper() if ch.isalpha()), "")
    return INVEST_TONES.get(letter, INVEST_TONES["A"])


def make_thumbnail_childhood(thumb: dict, domain: str | None, out: Path, size: int = THUMBNAIL_SIZE,
                             tone: str | None = None) -> Path:
    final_size, size = size, _DRAW_SIZE
    tone = tone or childhood_tone(domain)
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


def _darker(hex_color: str, factor: float = 0.55) -> str:
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % (int(r * factor), int(g * factor), int(b * factor))


def make_thumbnail_scene(thumb: dict, background: Path, out: Path, tone: str, size: int = THUMBNAIL_SIZE) -> Path:
    """홈피드용 장면 썸네일. 본문 일러스트(Codex가 그린 그림)를 정사각형 배경으로 깔고, 글씨가 놓이는 영역만
    흐리게(블러) + 레인 색으로 물들인 패널을 부드러운 가장자리로 얹은 뒤, 굵은 테두리 글씨를 올린다.
    질문의 마지막 줄은 노란색으로 강조한다. 그림을 열 수 없으면 단색 썸네일로 대신한다."""
    try:
        pic = Image.open(background).convert("RGB")
    except (OSError, ValueError):
        return make_thumbnail_childhood(thumb, None, out, size=size, tone=tone)
    final_size, size = size, _DRAW_SIZE
    w, h = pic.size
    side = min(w, h)
    pic = pic.crop(((w - side) // 2, (h - side) // 2, (w - side) // 2 + side, (h - side) // 2 + side))
    pic = pic.resize((size, size), Image.LANCZOS)
    pic = Image.blend(pic, Image.new("RGB", (size, size), "#000000"), 0.15)      # 전체를 살짝 눌러 대비 확보
    accent = "#ffd23f"
    edge = _darker(tone, 0.45)
    draw = ImageDraw.Draw(pic)

    # 1) 글씨 배치 계산
    chip_font = _font("bold", 40)
    chip = thumb.get("chip", "")
    lines = [line for line in (thumb.get("main_lines") or []) if line][:3]
    font_size = 146
    main_font = _font("bold", font_size)
    while font_size > 96 and any(_width(draw, line, main_font) > size - 200 for line in lines):
        font_size -= 6
        main_font = _font("bold", font_size)
    line_h = int(font_size * 1.2)
    sub_font = _font("bold", 50)
    top_y = 300
    bottom = top_y + line_h * len(lines) + (110 if thumb.get("sub") else 10)
    right = max([_width(draw, line, main_font) for line in lines] +
                [_width(draw, thumb.get("sub", ""), sub_font), _width(draw, chip, chip_font) + 56]) + 90

    # 2) 글씨 뒤 컬러 블러 패널(가장자리는 부드럽게 사라진다)
    panel = Image.blend(pic.filter(ImageFilter.GaussianBlur(26)), Image.new("RGB", (size, size), tone), 0.62)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([40, 70, min(size - 30, right + 70), min(size - 30, bottom + 60)],
                                           radius=60, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(38))
    img = Image.composite(panel, pic, mask)
    draw = ImageDraw.Draw(img)

    # 3) 글씨: 칩 → 질문(굵은 테두리, 마지막 줄 노랑) → 보조
    if chip:
        draw.rounded_rectangle([90, 110, 90 + _width(draw, chip, chip_font) + 56, 192], radius=26, fill=accent)
        draw.text((118, 128), chip, font=chip_font, fill=edge)
    y = top_y
    for i, line in enumerate(lines):
        fill = accent if i == len(lines) - 1 and len(lines) > 1 else WHITE
        draw.text((90, y), line, font=main_font, fill=fill, stroke_width=7, stroke_fill=edge)
        y += line_h
    if thumb.get("sub"):
        draw.text((96, y + 34), thumb["sub"], font=sub_font, fill=WHITE, stroke_width=4, stroke_fill=edge)
    return _save_thumbnail(img, out, final_size)


# 생활 절차 블로그(photo): 레인별 차분한 톤(칩·글씨 그림자). 실제 사진·캡처가 배경이라 색은 작게만 쓴다.
GUIDE_TONES = {
    "A": "#1d4e89",   # 시험·자격증 블루
    "B": "#2f6b3f",   # 생활 민원 그린
    "C": "#5a3a1e",   # 생활 법률 브라운
}


def guide_tone(lane: str | None) -> str:
    letter = next((ch for ch in str(lane or "").upper() if ch.isalpha()), "")
    return GUIDE_TONES.get(letter, GUIDE_TONES["A"])


def make_thumbnail_photo(thumb: dict, background: Path, out: Path, tone: str, size: int = THUMBNAIL_SIZE) -> Path:
    """실제 사진·공식 화면 캡처를 정사각형으로 깔고, 아래쪽만 어둡게 눌러 흰 글씨를 얹는다(사람이 만든 썸네일처럼
    담백하게: 작은 칩 + 굵은 흰 글씨 + 얇은 보조 문구). 캡처는 위쪽(메뉴·제목)이 중요해 위에서부터 자른다.
    그림을 열 수 없으면 단색 썸네일로 대신한다."""
    try:
        pic = Image.open(background).convert("RGB")
    except (OSError, ValueError):
        return make_thumbnail_childhood(thumb, None, out, size=size, tone=tone)
    final_size, size = size, _DRAW_SIZE
    w, h = pic.size
    side = min(w, h)
    is_capture = "cap" in background.stem
    top = 0 if is_capture else (h - side) // 2
    pic = pic.crop(((w - side) // 2, top, (w - side) // 2 + side, top + side)).resize((size, size), Image.LANCZOS)
    if is_capture:
        # 화면 캡처는 글자가 많아 제목과 겹쳐 보인다 → 살짝 흐리게(어떤 화면인지는 알아볼 정도로)
        pic = pic.filter(ImageFilter.GaussianBlur(5))

    # 아래쪽을 점점 어둡게(글씨 자리). 캡처는 더 위에서부터, 더 진하게
    shade = Image.new("L", (size, size), 0)
    sd = ImageDraw.Draw(shade)
    start, peak = (int(size * 0.25), 238) if is_capture else (int(size * 0.42), 215)
    for y in range(start, size):
        sd.line([(0, y), (size, y)], fill=int(peak * ((y - start) / (size - start)) ** 0.7))
    img = Image.composite(Image.new("RGB", (size, size), "#0b0f14"), pic, shade)
    draw = ImageDraw.Draw(img)

    lines = [line for line in (thumb.get("main_lines") or []) if line][:3]
    font_size = 118
    main_font = _font("bold", font_size)
    while font_size > 80 and any(_width(draw, line, main_font) > size - 160 for line in lines):
        font_size -= 6
        main_font = _font("bold", font_size)
    line_h = int(font_size * 1.22)
    sub = thumb.get("sub", "")
    sub_font = _font("regular", 46)
    y = size - 90 - line_h * len(lines) - (80 if sub else 0)
    chip = thumb.get("chip", "")
    if chip:
        chip_font = _font("bold", 38)
        cy = y - 100
        draw.rounded_rectangle([80, cy, 80 + _width(draw, chip, chip_font) + 48, cy + 70], radius=12, fill=tone)
        draw.text((104, cy + 12), chip, font=chip_font, fill=WHITE)
    for line in lines:
        draw.text((80, y), line, font=main_font, fill=WHITE, stroke_width=3, stroke_fill="#0b0f14")
        y += line_h
    if sub:
        draw.text((84, y + 14), sub, font=sub_font, fill="#e8e8e8")
    return _save_thumbnail(img, out, final_size)
