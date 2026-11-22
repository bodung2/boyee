"""활동지 그리기: AI 원화는 그림만 맡고, 글씨·점선·칸·브랜드 띠는 코드로 정확하게 그린다.

A4(200dpi, 1654×2339) PNG를 장마다 만들고, 묶어서 PDF 한 파일로 저장한다.
블로그에는 폭 1000px로 줄인 장 이미지와 16:9 미리보기(cover)를 올린다.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import library
from .spec import PAGE_TYPES

W, H = 1654, 2339
DPI = 200
M = 96                                   # 바깥 여백
GREEN, YELLOW = (47, 107, 61), (255, 210, 63)
INK, SOFT, TRACE = (51, 51, 51), (150, 150, 150), (196, 196, 196)
PAPER_TINT = (255, 248, 228)
BAND_H = 118
CONTENT_TOP = 590
CONTENT_BOTTOM = H - BAND_H - 70
BLOG_WIDTH = 1000
FONT_FALLBACK = ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
                 "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
                 "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc")


def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        from naver_autopost.images import _font
        return _font(weight, size)
    except RuntimeError:
        for p in FONT_FALLBACK:
            if Path(p).exists():
                return ImageFont.truetype(p, size, index=1 if "NotoSansCJK" in p else 0)
        raise


def _tw(d: ImageDraw.ImageDraw, text: str, f) -> int:
    l, _, r, _ = d.textbbox((0, 0), text, font=f)
    return r - l


def _fit(d, text: str, weight: str, size: int, max_w: int, min_size: int = 28):
    f = font(weight, size)
    while size > min_size and _tw(d, text, f) > max_w:
        size -= 2
        f = font(weight, size)
    return f


def _center_text(d, box, text, f, fill):
    x0, y0, x1, y1 = box
    l, t, r, b = d.textbbox((0, 0), text, font=f)
    d.text(((x0 + x1 - (r - l)) / 2 - l, (y0 + y1 - (b - t)) / 2 - t), text, font=f, fill=fill)


class Assets:
    """원화 불러오기(같은 그림은 한 번만 읽는다)."""

    def __init__(self, lib: Path):
        self.lib = lib
        self._cache: dict[tuple, Image.Image] = {}

    def get(self, key: str, size: int, cut: bool = False, shadow: bool = False) -> Image.Image:
        ck = (key, size, cut, shadow)
        if ck not in self._cache:
            img = Image.open(library.path(self.lib, key)).convert("RGB")
            img = img.resize((size, size), Image.LANCZOS)
            if shadow:
                img = library.silhouette(img)
            elif cut:
                img = library.cutout(img)
            self._cache[ck] = img
        return self._cache[ck]

    def paste(self, page: Image.Image, key: str, box, cut=True, shadow=False) -> None:
        x0, y0, x1, y1 = (int(v) for v in box)
        side = min(x1 - x0, y1 - y0)
        img = self.get(key, side, cut=cut or shadow, shadow=shadow)
        pos = (x0 + (x1 - x0 - side) // 2, y0 + (y1 - y0 - side) // 2)
        if img.mode == "RGBA":
            page.paste(img, pos, img)
        else:
            page.paste(img, pos)


# ---------------------------------------------------------------- 점선

def _dashed(d, pts, fill=SOFT, width=10, dash=24, gap=18):
    on, left = True, dash
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        seg = math.hypot(x1 - x0, y1 - y0)
        pos = 0.0
        while pos < seg:
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


def path_points(kind: str, x0: float, x1: float, y: float, amp: float, n: int = 240) -> list[tuple[float, float]]:
    pts = []
    for i in range(n + 1):
        t = i / n
        x = x0 + (x1 - x0) * t
        if kind == "wave":
            dy = -amp * math.sin(t * math.pi * 5)
        elif kind == "zigzag":
            ph = (t * 5) % 1
            dy = amp * (1 - 4 * abs(ph - 0.5)) * -1
        elif kind == "steps":
            dy = -amp * 0.8 if int(t * 6) % 2 else amp * 0.8
        elif kind == "arc":
            dy = -amp * 1.3 * math.sin(t * math.pi)
        elif kind == "loop":                      # 고리 4개(트로코이드)
            r = (x1 - x0) / 4 / (2 * math.pi) * 1.9
            th = t * 4 * 2 * math.pi
            x = x0 + (x1 - x0) * t - r * math.sin(th)
            dy = -r * (1 - math.cos(th)) * 1.15
        else:
            dy = 0
        pts.append((x, y + dy))
    if kind == "steps":                           # 계단은 세로로 곧게 꺾는다
        out = [pts[0]]
        for p in pts[1:]:
            if abs(p[1] - out[-1][1]) > 1:
                out.append((p[0], out[-1][1]))
            out.append(p)
        pts = out
    return pts


# ---------------------------------------------------------------- 공통 틀

def _frame(spec: dict, page: dict, no: int, total: int, assets: Assets, blog_url: str, guide: str | None):
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    # 맨 위 색 띠 + 제목
    d.rounded_rectangle([M - 20, 60, W - M + 20, 290], radius=40, fill=PAPER_TINT)
    title = page["title"]
    tf = _fit(d, title, "bold", 92, W - 2 * M - 520)
    d.text((M + 30, 86), title, font=tf, fill=INK)
    meta = f"{spec.get('age', '')} · {spec.get('domain', '') or PAGE_TYPES.get(page['type'], '')}"
    d.text((M + 32, 222), meta, font=font("regular", 34), fill=SOFT)
    nf = font("bold", 36)
    for i, label in enumerate(("이름", "날짜")):
        y = 110 + i * 76
        d.text((W - M - 470, y), label, font=nf, fill=INK)
        d.line([(W - M - 370, y + 46), (W - M - 20, y + 46)], fill=SOFT, width=3)
    # 안내 문장(안내 캐릭터가 있으면 옆에)
    box = [M, 330, W - M, 500]
    d.rounded_rectangle(box, radius=36, outline=YELLOW, width=6, fill=(255, 253, 244))
    tx = M + 40
    if guide:
        assets.paste(img, guide, (M + 18, 336, M + 178, 496))
        tx = M + 200
    inf = _fit(d, page["instruction"], "bold", 56, W - M - 40 - tx)
    l, t, r, b = d.textbbox((0, 0), page["instruction"], font=inf)
    d.text((tx, (box[1] + box[3] - (b - t)) / 2 - t), page["instruction"], font=inf, fill=INK)
    # 브랜드 띠(무료 나눔: 출처 표시)
    y0 = H - BAND_H
    d.rectangle([0, y0, W, H], fill=GREEN)
    d.rectangle([0, y0, W, y0 + 7], fill=YELLOW)
    _center_text(d, (0, y0 + 14, W, y0 + 66), "ⓒ 꾸쓰쌤 · 더 많은 교육자료는 블로그에", font("bold", 36), "white")
    if blog_url:
        _center_text(d, (0, y0 + 64, W, y0 + 108), blog_url, font("regular", 30), (255, 238, 180))
    if total > 1:
        d.text((W - M - 60, y0 - 56), f"{no}/{total}", font=font("regular", 30), fill=SOFT)
    return img, d


def _rows(n: int, top=CONTENT_TOP, bottom=CONTENT_BOTTOM):
    h = (bottom - top) / n
    return [(top + i * h, top + (i + 1) * h) for i in range(n)]


def _shuffled(items: list, seed: str) -> list[int]:
    """짝 잇기 오른쪽 순서: 같은 자리에 오는 짝이 없게 섞는다(설계서마다 같은 결과)."""
    idx = list(range(len(items)))
    rnd = random.Random(seed)
    for _ in range(200):
        rnd.shuffle(idx)
        if all(i != j for j, i in enumerate(idx)):
            return idx
    return idx[1:] + idx[:1]


# ---------------------------------------------------------------- 활동 종류별

def _trace_lines(img, d, page, assets, seed):
    rows = page["rows"]
    for (y0, y1), r in zip(_rows(len(rows)), rows):
        h = y1 - y0
        s = min(h * 0.74, 300)
        cy = (y0 + y1) / 2
        assets.paste(img, r["from"], (M, cy - s / 2, M + s, cy + s / 2))
        assets.paste(img, r["to"], (W - M - s, cy - s / 2, W - M, cy + s / 2))
        xa, xb = M + s + 40, W - M - s - 40
        pts = path_points(r.get("path", "straight"), xa, xb, cy + (h * 0.12 if r.get("path") == "arc" else 0),
                          amp=h * 0.2)
        _dashed(d, pts)
        d.ellipse([xa - 18, pts[0][1] - 18, xa + 18, pts[0][1] + 18], fill=GREEN)
    return {}


def _trace_letters(img, d, page, assets, seed):
    words = page["words"]
    for (y0, y1), w in zip(_rows(len(words)), words):
        h = y1 - y0
        s = min(h * 0.72, 280)
        cy = (y0 + y1) / 2
        assets.paste(img, w["asset"], (M, cy - s / 2, M + s, cy + s / 2))
        x = M + s + 40
        slot_w = (W - M - x - 2 * 24) / 3
        slot_h = min(h * 0.66, 250)
        word = w["word"]
        f = _fit(d, word, "bold", int(slot_h * 0.7), int(slot_w * 0.86))
        for i in range(3):
            box = (x + i * (slot_w + 24), cy - slot_h / 2, x + i * (slot_w + 24) + slot_w, cy + slot_h / 2)
            d.rounded_rectangle(box, radius=26, outline=(225, 225, 225), width=4)
            d.line([(box[0] + 16, cy), (box[2] - 16, cy)], fill=(238, 238, 238), width=3)   # 가운데 보조선
            _center_text(d, box, word, f, INK if i == 0 else TRACE)
    return {}


def _count_write(img, d, page, assets, seed):
    rows = page["rows"]
    for (y0, y1), r in zip(_rows(len(rows)), rows):
        h = y1 - y0
        cy = (y0 + y1) / 2
        bh = min(h * 0.8, 330)
        box = (M, cy - bh / 2, W - M - 300, cy + bh / 2)
        d.rounded_rectangle(box, radius=30, outline=(225, 225, 225), width=4)
        n = r["count"]
        per = 5 if n > 5 else n
        lines = 2 if n > 5 else 1
        cell = min((box[2] - box[0] - 40) / 5, (bh - 30) / lines)
        for k in range(n):
            row, col = divmod(k, per)
            cols_here = per if row < lines - 1 or n % per == 0 else n % per
            x0 = box[0] + (box[2] - box[0] - cols_here * cell) / 2 + col * cell
            yy = cy - lines * cell / 2 + row * cell
            assets.paste(img, r["asset"], (x0 + 6, yy + 6, x0 + cell - 6, yy + cell - 6))
        ans = (W - M - 230, cy - 115, W - M, cy + 115)
        d.rounded_rectangle(ans, radius=30, outline=GREEN, width=6)
    return {"answers": [r["count"] for r in rows]}


def _match(img, d, page, assets, seed, right_draw):
    left = page.get("assets") or [p["asset"] for p in page["pairs"]]
    order = _shuffled(left, seed + page["type"])
    rows = _rows(len(left))
    for i, ((y0, y1), k) in enumerate(zip(rows, left)):
        s = min((y1 - y0) * 0.78, 300)
        cy = (y0 + y1) / 2
        assets.paste(img, k, (M + 20, cy - s / 2, M + 20 + s, cy + s / 2))
        d.ellipse([M + s + 70, cy - 16, M + s + 102, cy + 16], fill=INK)
    for slot, i in enumerate(order):
        y0, y1 = rows[slot]
        s = min((y1 - y0) * 0.78, 300)
        cy = (y0 + y1) / 2
        right_draw(i, (W - M - 20 - s, cy - s / 2, W - M - 20, cy + s / 2))
        d.ellipse([W - M - s - 102, cy - 16, W - M - s - 70, cy + 16], fill=INK)
    return {"answers": [order.index(i) + 1 for i in range(len(left))]}     # 왼쪽 i번 → 오른쪽 몇 번째


def _match_shadow(img, d, page, assets, seed):
    keys = page["assets"]
    return _match(img, d, page, assets, seed,
                  lambda i, box: assets.paste(img, keys[i], box, shadow=True))


def _match_word(img, d, page, assets, seed):
    pairs = page["pairs"]

    def word_box(i, box):
        x0, y0, x1, y1 = box
        wbox = (x0 - 60, (y0 + y1) / 2 - 85, x1, (y0 + y1) / 2 + 85)
        d.rounded_rectangle(wbox, radius=36, outline=YELLOW, width=6, fill=(255, 253, 244))
        _center_text(d, wbox, pairs[i]["word"], _fit(d, pairs[i]["word"], "bold", 96, int(wbox[2] - wbox[0] - 40)), INK)
    return _match(img, d, page, assets, seed, word_box)


def _coloring(img, d, page, assets, seed):
    box = (M + 30, CONTENT_TOP, W - M - 30, CONTENT_BOTTOM - 170)
    d.rounded_rectangle(box, radius=40, outline=(225, 225, 225), width=4)
    pad = 60
    assets.paste(img, page["asset"], (box[0] + pad, box[1] + pad, box[2] - pad, box[3] - pad), cut=False)
    colors = [(239, 83, 80), (255, 167, 38), (255, 213, 79), (102, 187, 106), (66, 165, 245), (171, 71, 188)]
    y = CONTENT_BOTTOM - 100
    gap = (W - 2 * M - 300) / len(colors)
    d.text((M + 30, y - 28), "이런 색은 어때요?", font=font("bold", 40), fill=SOFT)
    for i, c in enumerate(colors):
        x = M + 400 + i * gap * 0.82
        d.ellipse([x, y - 34, x + 68, y + 34], fill=c)
    return {}


def _find_same(img, d, page, assets, seed):
    rows = page["rows"]
    answers = []
    for (y0, y1), r in zip(_rows(len(rows)), rows):
        h = y1 - y0
        cy = (y0 + y1) / 2
        s = min(h * 0.7, 250)
        tbox = (M, cy - s / 2 - 16, M + s + 32, cy + s / 2 + 16)
        d.rounded_rectangle(tbox, radius=30, fill=PAPER_TINT, outline=YELLOW, width=6)
        assets.paste(img, r["target"], (tbox[0] + 16, tbox[1] + 16, tbox[2] - 16, tbox[3] - 16))
        ax = tbox[2] + 30
        d.polygon([(ax, cy - 30), (ax + 50, cy), (ax, cy + 30)], fill=YELLOW)
        x = ax + 90
        cw = (W - M - x) / 4
        for j, k in enumerate(r["options"]):
            box = (x + j * cw + 10, cy - s / 2, x + (j + 1) * cw - 10, cy + s / 2)
            d.rounded_rectangle(box, radius=26, outline=(225, 225, 225), width=4)
            assets.paste(img, k, (box[0] + 14, box[1] + 14, box[2] - 14, box[3] - 14))
        answers.append(r["options"].index(r["target"]) + 1)
    return {"answers": answers}


DRAW = {"trace_lines": _trace_lines, "trace_letters": _trace_letters, "count_write": _count_write,
        "match_shadow": _match_shadow, "match_word": _match_word, "coloring": _coloring, "find_same": _find_same}


def render(spec: dict, lib: Path, out_dir: Path, blog_url: str = "") -> dict:
    """장 PNG(원본 크기)·블로그용 PNG·PDF·미리보기를 만든다. 만든 파일과 정답을 돌려준다."""
    assets = Assets(lib)
    guide = spec.get("guide") if spec.get("guide") and library.path(lib, spec["guide"]).exists() else None
    pages, blog, answers = [], [], {}
    total = len(spec["pages"])
    out_dir.mkdir(parents=True, exist_ok=True)
    for no, page in enumerate(spec["pages"], 1):
        img, d = _frame(spec, page, no, total, assets, blog_url, guide)
        info = DRAW[page["type"]](img, d, page, assets, spec["set_id"])
        if info.get("answers"):
            answers[f"p{no}"] = info["answers"]
        full = out_dir / f"page{no}_full.png"
        img.save(full, "PNG", optimize=True)
        pages.append(full)
        small = out_dir / f"worksheet_p{no}.png"
        img.resize((BLOG_WIDTH, round(H * BLOG_WIDTH / W)), Image.LANCZOS).save(small, "PNG", optimize=True)
        blog.append(small)
    pdf = out_dir / f"{spec['set_id']}.pdf"
    first, *rest = [Image.open(p).convert("RGB") for p in pages]
    first.save(pdf, "PDF", resolution=DPI, save_all=True, append_images=rest)
    cover = make_cover(pages, out_dir / "worksheet_cover.png")
    return {"pages": [str(p) for p in pages], "blog_images": [p.name for p in blog], "pdf": str(pdf),
            "cover": cover.name, "answers": answers}


def make_cover(pages: list[Path], out: Path) -> Path:
    """16:9 미리보기: 연한 바탕에 장들을 살짝 기울여 겹쳐 놓는다(썸네일이 가운데 정사각형을 잘라 써도 보이게)."""
    cw, ch = 1600, 900
    bg = Image.new("RGB", (cw, ch), (253, 243, 220))
    ph = 800
    pw = round(W * ph / H)
    angles = [-5, 4] if len(pages) > 1 else [0]
    centers = [cw / 2 - 150, cw / 2 + 150] if len(pages) > 1 else [cw / 2]
    for p, a, cx in zip(pages, angles, centers):
        im = Image.open(p).convert("RGB").resize((pw, ph), Image.LANCZOS)
        shadow = Image.new("RGBA", (pw + 30, ph + 30), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).rectangle([15, 15, pw + 15, ph + 15], fill=(0, 0, 0, 60))
        sh = shadow.rotate(a, expand=True, resample=Image.BICUBIC)
        bg.paste(sh, (int(cx - sh.width / 2 + 10), int(ch / 2 - sh.height / 2 + 14)), sh)
        rim = im.convert("RGBA").rotate(a, expand=True, resample=Image.BICUBIC)
        bg.paste(rim, (int(cx - rim.width / 2), int(ch / 2 - rim.height / 2)), rim)
    bg.save(out, "PNG", optimize=True)
    return out
