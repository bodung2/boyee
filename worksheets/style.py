"""활동지 디자인 요소: 블로그 주인이 직접 만든 무료 나눔 활동지(소풍 시리즈) 양식을 코드로 옮겼다.

크림색 종이, 점선 테두리가 있는 알약 모양 제목 + 양옆 잎·꽃 장식(또는 캐릭터 4명), 잎 아이콘이 붙은 한 줄 안내,
점선 카드, 흰 낱말 상자, 아래쪽 풀·꽃 장식, 초록 브랜드 띠. 글꼴은 둥근 제목체(주아)와 본문체(나눔고딕 굵게).
"""
from __future__ import annotations

import logging
import math
import os
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

log = logging.getLogger(__name__)

# A4 300dpi (2480×3508). 1mm = 11.81px
W, H = 2480, 3508
MM = W / 210
PAPER = (255, 247, 236)
INK = (74, 44, 20)              # 제목·낱말(짙은 갈색)
INK_SOFT = (96, 72, 52)         # 안내 문장
PILL_FILL = (253, 232, 176)
PILL_EDGE = (238, 196, 120)
PILL_DASH = (214, 160, 84)
CARD_FILL = (255, 253, 249)
CARD_EDGE = (246, 222, 184)
CARD_DASH = (236, 196, 136)
LABEL_EDGE = (240, 200, 140)
LEAF = (104, 158, 72)
LEAF_DARK = (70, 120, 50)
FLOWER = (246, 146, 58)
FLOWER_C = (255, 210, 63)
DOT = (58, 38, 22)
TRACE = (150, 140, 130)
GREEN, YELLOW = (47, 107, 61), (255, 210, 63)
BAND_H = 210

FONT_URLS = {
    "title": ("Jua-Regular.ttf", "https://raw.githubusercontent.com/google/fonts/main/ofl/jua/Jua-Regular.ttf"),
    "body": ("NanumGothic-Bold.ttf",
             "https://raw.githubusercontent.com/google/fonts/main/ofl/nanumgothic/NanumGothic-Bold.ttf"),
}
SYSTEM_FONTS = ("C:/Windows/Fonts/malgunbd.ttf", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf", "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc")


def font_dir() -> Path:
    root = Path(__file__).resolve().parent.parent
    return Path(os.environ.get("WORKSHEET_FONTS") or root / "data" / "worksheets" / "fonts")


def ensure_fonts(folder: Path | None = None, fetch=None) -> None:
    """둥근 제목체·본문체(무료 OFL 글꼴)를 처음 한 번 받아 둔다. 못 받으면 맑은 고딕으로 그린다."""
    folder = folder or font_dir()
    for name, url in FONT_URLS.values():
        path = folder / name
        if path.exists() and path.stat().st_size > 10000:
            continue
        try:
            data = fetch(url) if fetch else urllib.request.urlopen(url, timeout=60).read()
            folder.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        except Exception as e:  # noqa: BLE001
            log.warning("활동지 글꼴을 받지 못했습니다(맑은 고딕으로 그림): %s", e)


_CACHE: dict[tuple, ImageFont.FreeTypeFont] = {}


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    key = (kind, size)
    if key not in _CACHE:
        own = font_dir() / FONT_URLS.get(kind, FONT_URLS["body"])[0]
        cands = [own, *SYSTEM_FONTS]
        for p in cands:
            p = Path(p)
            if p.exists():
                _CACHE[key] = ImageFont.truetype(str(p), size, index=1 if "NotoSansCJK" in p.name else 0)
                break
        else:
            from naver_autopost.images import _font
            _CACHE[key] = _font("bold", size)
    return _CACHE[key]


def tw(d: ImageDraw.ImageDraw, text: str, f) -> int:
    l, _, r, _ = d.textbbox((0, 0), text, font=f)
    return r - l


def fit(d, text: str, kind: str, size: int, max_w: float, min_size: int = 30):
    f = font(kind, size)
    while size > min_size and tw(d, text, f) > max_w:
        size -= 4
        f = font(kind, size)
    return f


def center_text(d, box, text, f, fill=INK):
    x0, y0, x1, y1 = box
    l, t, r, b = d.textbbox((0, 0), text, font=f)
    d.text(((x0 + x1 - (r - l)) / 2 - l, (y0 + y1 - (b - t)) / 2 - t), text, font=f, fill=fill)


# ---------------------------------------------------------------- 선

def dashed_line(d, pts, fill=CARD_DASH, width=6, dash=26, gap=18):
    on, left = True, dash
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        seg = math.hypot(x1 - x0, y1 - y0)
        pos = 0.0
        while seg and pos < seg:
            step = min(left, seg - pos)
            if on:
                a, b = pos / seg, (pos + step) / seg
                d.line([(x0 + (x1 - x0) * a, y0 + (y1 - y0) * a), (x0 + (x1 - x0) * b, y0 + (y1 - y0) * b)],
                       fill=fill, width=width)
            pos += step
            left -= step
            if left <= 0:
                on = not on
                left = dash if on else gap


def rounded_path(box, r, n=10):
    """둥근 사각형 테두리 점들(점선 테두리용)."""
    x0, y0, x1, y1 = box
    r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)
    pts = []
    for cx, cy, a0 in ((x1 - r, y0 + r, -90), (x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180)):
        for i in range(n + 1):
            a = math.radians(a0 + 90 * i / n)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts + pts[:1]


def card(d, box, radius=56, fill=CARD_FILL, edge=CARD_EDGE, dash=CARD_DASH):
    """원본 활동지의 칸: 연한 실선 테두리 + 안쪽 점선."""
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=edge, width=5)
    x0, y0, x1, y1 = box
    dashed_line(d, rounded_path((x0 + 20, y0 + 20, x1 - 20, y1 - 20), radius - 16), fill=dash, width=5)


def cut_box(d, box, radius=40):
    """오리는 칸: 진한 점선만."""
    dashed_line(d, rounded_path(box, radius), fill=DOT, width=6, dash=28, gap=20)


def label(d, box, text, kind="title", size=None, fill=(255, 255, 255)):
    x0, y0, x1, y1 = box
    d.rounded_rectangle(box, radius=min(40, (y1 - y0) / 2), fill=fill, outline=LABEL_EDGE, width=6)
    f = fit(d, text, kind, size or int((y1 - y0) * 0.6), (x1 - x0) * 0.86)
    center_text(d, box, text, f, INK)


# ---------------------------------------------------------------- 장식

def leaf(img, cx, cy, length, angle, color=LEAF):
    lw = int(length)
    layer = Image.new("RGBA", (lw * 2, lw * 2), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.ellipse([lw - lw * 0.5, lw - lw * 0.2, lw + lw * 0.5, lw + lw * 0.2], fill=color + (255,))
    ld.line([(lw - lw * 0.45, lw), (lw + lw * 0.4, lw)], fill=LEAF_DARK + (255,), width=max(2, lw // 22))
    layer = layer.rotate(angle, resample=Image.BICUBIC)
    img.paste(layer, (int(cx - lw), int(cy - lw)), layer)


def flower(d, cx, cy, r, color=FLOWER):
    for i in range(5):
        a = math.radians(i * 72 - 90)
        px, py = cx + r * 0.62 * math.cos(a), cy + r * 0.62 * math.sin(a)
        d.ellipse([px - r * 0.5, py - r * 0.5, px + r * 0.5, py + r * 0.5], fill=color)
    d.ellipse([cx - r * 0.36, cy - r * 0.36, cx + r * 0.36, cy + r * 0.36], fill=FLOWER_C)


def sprig(img, x, y, h, mirror=False, with_flower=True):
    """제목 옆 잎 줄기(+꽃 한 송이)."""
    d = ImageDraw.Draw(img)
    s = -1 if mirror else 1
    pts = [(x + s * h * 0.25 * math.sin(t / 10 * math.pi * 0.6), y - h * t / 10) for t in range(11)]
    d.line(pts, fill=LEAF_DARK, width=max(4, int(h / 40)))
    for k, (px, py) in enumerate(pts[2::2]):
        side = 1 if k % 2 else -1
        leaf(img, px + side * h * 0.12, py, h * 0.22, (25 if side > 0 else 155) * (1 if not mirror else 1) + 0)
    if with_flower:
        flower(d, pts[2][0] - s * h * 0.12, pts[2][1] + h * 0.1, h * 0.13)


def leaf_icon(img, x, cy, size):
    leaf(img, x + size * 0.35, cy, size * 0.62, 125, LEAF)
    leaf(img, x + size * 0.8, cy, size * 0.62, 55, (130, 180, 80))


def grass(img, y, n=9, seed=3):
    """맨 아래 풀·꽃 장식(활동 영역에 닿지 않게 띠 바로 위)."""
    import random
    rnd = random.Random(seed)
    d = ImageDraw.Draw(img)
    for i in range(n):
        x = 140 + (W - 280) * i / (n - 1) + rnd.uniform(-60, 60)
        for k in range(3):
            a = math.radians(-90 + (k - 1) * 28)
            d.line([(x, y), (x + 46 * math.cos(a), y + 70 * math.sin(a))], fill=LEAF, width=9)
        if i % 3 == 1:
            flower(d, x + 30, y - 70, 26, (255, 196, 70) if i % 2 else FLOWER)


def band(img, blog_url: str):
    d = ImageDraw.Draw(img)
    y0 = H - BAND_H
    d.rectangle([0, y0, W, H], fill=GREEN)
    d.rectangle([0, y0, W, y0 + 12], fill=YELLOW)
    center_text(d, (0, y0 + 22, W, y0 + 118), "© 꾸쓰쌤  ·  더 많은 교육자료는 블로그에", font("body", 58), (255, 255, 255))
    if blog_url:
        center_text(d, (0, y0 + 118, W, y0 + 196), blog_url, font("body", 46), (255, 238, 180))


def pill(img, d, box, lines: list[str], size: int):
    x0, y0, x1, y1 = box
    r = min(110, (y1 - y0) / 2)
    d.rounded_rectangle(box, radius=r, fill=PILL_FILL, outline=PILL_EDGE, width=8)
    dashed_line(d, rounded_path((x0 + 22, y0 + 22, x1 - 22, y1 - 22), r - 18), fill=PILL_DASH, width=6, dash=22, gap=16)
    f = font("title", size)
    lh = size * 1.18
    top = (y0 + y1) / 2 - lh * len(lines) / 2
    for i, line in enumerate(lines):
        center_text(d, (x0, top + i * lh, x1, top + (i + 1) * lh), line, f, INK)


def soft_shadow(img, box, radius=40, offset=10, blur=18, alpha=40):
    x0, y0, x1, y1 = (int(v) for v in box)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle([x0, y0 + offset, x1, y1 + offset], radius=radius, fill=(120, 80, 40, alpha))
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    img.paste(layer, (0, 0), layer)
