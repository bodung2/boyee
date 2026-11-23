"""활동지 그리기(A4 300dpi): 블로그 주인의 무료 나눔 활동지 양식(worksheets/style.py)과
「경량 활동 12종 상세 프롬프트 명세서」의 활동 엔진을 코드로 옮겼다.

원화(AI 그림)는 그림만 맡고, 글자·점·선·점선·칸·절취선은 모두 코드가 정확한 자리에 그린다(명세서의 '후편집' 규칙).
장마다 원본 PNG(2480×3508), 블로그용 PNG(폭 1000), 묶음 PDF, 16:9 미리보기를 만든다.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from . import library, style as S
from .style import H, W

DPI = 300
BLOG_WIDTH = 1000
M = 130                                   # 좌우 여백(약 11mm)
CONTENT_BOTTOM = H - S.BAND_H - 150       # 풀 장식 위
PATHS = ("straight", "wave", "zigzag", "curve", "loop", "steps")


# ---------------------------------------------------------------- 원화

class Assets:
    def __init__(self, lib: Path):
        self.lib = lib
        self.index = library.load(lib)
        self._cache: dict = {}

    def has(self, key: str | None) -> bool:
        return bool(key) and library.path(self.lib, key).exists()

    def _src(self, key: str, size: int) -> Image.Image:
        ck = ("src", key, size)
        if ck not in self._cache:
            img = Image.open(library.path(self.lib, key)).convert("RGB")
            self._cache[ck] = img.resize((size, size), Image.LANCZOS)
        return self._cache[ck]

    def art(self, key: str, size: int) -> Image.Image:
        """흰 배경을 지운 그림(바깥 흰색만), 그림 부분만 잘라 낸 RGBA."""
        ck = ("art", key, size)
        if ck not in self._cache:
            cut = library.cutout(self._src(key, size))
            box = cut.getchannel("A").getbbox() or (0, 0, size, size)
            self._cache[ck] = cut.crop(box)
        return self._cache[ck]

    def shadow(self, key: str, size: int) -> Image.Image:
        art = self.art(key, size)
        sh = Image.new("RGBA", art.size, (96, 84, 76, 255))
        sh.putalpha(art.getchannel("A"))
        return sh

    def _edges(self, key: str, size: int) -> Image.Image:
        """색 그림에서 바로 뽑은 윤곽선(같은 그림이라 원화와 정확히 겹친다). opencv가 없으면 바깥 외곽선만."""
        src = self._src(key, size)
        alpha = library.cutout(src).getchannel("A")
        try:
            import cv2
            import numpy as np
        except ImportError:
            k = max(3, size // 90) | 1
            return ImageChops.subtract(alpha, alpha.filter(ImageFilter.MinFilter(k))).filter(ImageFilter.MaxFilter(3))
        rgb = np.asarray(src).astype(np.int16)
        g = cv2.cvtColor(np.asarray(src), cv2.COLOR_RGB2GRAY)
        sat = rgb.max(axis=2) - rgb.min(axis=2)
        # 그림 몸통: 바깥 흰색이 아니면서, 연한 회갈색 바닥 그림자(밝고 채도 낮음)는 뺀다
        body = (np.asarray(alpha) > 128) & ((g < 215) | (sat > 45))
        body = body.astype(np.uint8) * 255
        k = max(5, size // 60) | 1
        body = cv2.morphologyEx(body, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
        body = cv2.morphologyEx(body, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
        n, lab, st, _ = cv2.connectedComponentsWithStats(body)
        if n > 1:                                   # 가장 큰 덩어리 + 그 절반 이상인 덩어리만(떨어진 얼룩 제거)
            big = st[1:, 4].max()
            body = np.isin(lab, [i for i in range(1, n) if st[i][4] >= big * 0.08]).astype(np.uint8) * 255
        body = (cv2.GaussianBlur(body, (k * 2 + 1, k * 2 + 1), 0) > 127).astype(np.uint8) * 255   # 계단 줄이기
        w = max(4, size // 110)
        rim = cv2.subtract(cv2.dilate(body, np.ones((w, w), np.uint8)), body)
        gb = cv2.GaussianBlur(cv2.bilateralFilter(g.astype(np.uint8), 9, 60, 9), (5, 5), 0)
        inner = cv2.Canny(gb, 60, 140) & cv2.erode(body, np.ones((k * 2, k * 2), np.uint8))
        n, lab, st, _ = cv2.connectedComponentsWithStats(inner)
        keep = np.zeros_like(inner)
        for i in range(1, n):                       # 안쪽 선은 긴 것만(수채 질감 점은 버림)
            if st[i][4] > size // 4:
                keep[lab == i] = 255
        keep = cv2.dilate(keep, np.ones((max(3, w - 2),) * 2, np.uint8))
        return Image.fromarray(cv2.bitwise_or(rim, keep))

    def outline(self, key: str, size: int, dashed: bool = True, color=S.TRACE, same_art: bool = False) -> Image.Image:
        """따라 그리기용 흐린 점선 밑그림. 돌려주는 그림은 art(key, size)와 같은 크기·같은 자리다.
        same_art(반쪽 그림)면 원화 자체의 윤곽선을, 아니면 검수를 통과한 선 그림(<key>_line)을 쓰고 없으면 원화 윤곽선."""
        ck = ("outline", key, size, dashed, same_art)
        if ck in self._cache:
            return self._cache[ck]
        line_key = key if key.endswith("_line") else f"{key}_line"
        if not same_art and self.has(line_key) and not self.index.get(line_key, {}).get("clipped"):
            g = self._src(line_key, size).convert("L")
            mask = g.point(lambda v: 255 if v < 150 else 0)
            alpha_src = library.cutout(self._src(line_key, size)).getchannel("A")
        else:
            mask = self._edges(key, size)
            alpha_src = library.cutout(self._src(key, size)).getchannel("A")
        if dashed:                                     # 칸무늬를 곱해 선을 짧은 점선으로 끊는다
            step = max(8, size // 45)
            pat = Image.new("L", mask.size, 0)
            pd = ImageDraw.Draw(pat)
            for y in range(0, size, step):
                for x in range(0, size, step):
                    if ((x // step) + (y // step)) % 2 == 0:
                        pd.rectangle([x, y, x + step - 1, y + step - 1], fill=255)
            mask = ImageChops.multiply(mask, pat)
        out = Image.new("RGBA", mask.size, color + (0,))
        out.putalpha(mask)
        box = (alpha_src.getbbox() or (0, 0, size, size))
        self._cache[ck] = out.crop(box)
        return self._cache[ck]


def paste_fit(img: Image.Image, rgba: Image.Image, box, align="center") -> tuple[int, int, int, int]:
    """비율을 지켜 칸 안에 꽉 차게 붙인다. 실제로 붙은 자리를 돌려준다."""
    x0, y0, x1, y1 = (int(v) for v in box)
    s = min((x1 - x0) / rgba.width, (y1 - y0) / rgba.height)
    w, h = max(1, int(rgba.width * s)), max(1, int(rgba.height * s))
    im = rgba.resize((w, h), Image.LANCZOS)
    x = x0 + (x1 - x0 - w) // 2 if align == "center" else (x0 if align == "left" else x1 - w)
    y = y0 + (y1 - y0 - h) // 2
    img.paste(im, (x, y), im)
    return x, y, x + w, y + h


def grid(cols: int, rows: int, top: float, bottom: float, gap: float = 56, left: float = M, right: float = W - M):
    cw = (right - left - gap * (cols - 1)) / cols
    ch = (bottom - top - gap * (rows - 1)) / rows
    return [(left + c * (cw + gap), top + r * (ch + gap), left + c * (cw + gap) + cw, top + r * (ch + gap) + ch)
            for r in range(rows) for c in range(cols)]


def _shuffled(n: int, seed: str) -> list[int]:
    """오른쪽 순서: 같은 줄에 정답이 오지 않게 섞는다(설계서마다 같은 결과)."""
    idx = list(range(n))
    rnd = random.Random(seed)
    for _ in range(300):
        rnd.shuffle(idx)
        if all(i != j for j, i in enumerate(idx)):
            return idx
    return idx[1:] + idx[:1]


# ---------------------------------------------------------------- 머리(제목·안내)

def _title_lines(title: str, two: bool) -> list[str]:
    if "\n" in title:
        return title.split("\n")[:2]
    if not two or len(title) <= 7:
        return [title]
    words = title.split(" ")
    best = min(range(1, len(words)), key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))),
               default=None)
    return [" ".join(words[:best]), " ".join(words[best:])] if best else [title]


def header(img, d, spec: dict, page: dict, A: Assets) -> float:
    """제목·안내를 그리고 본문이 시작할 y를 돌려준다."""
    chars = [k for k in (page.get("characters") or spec.get("characters") or []) if A.has(k)][:4]
    if page.get("header", "characters" if len(chars) >= 2 else "leaves") == "characters" and len(chars) >= 2:
        lines = _title_lines(page["title"], True)
        size = 150 if max(len(x) for x in lines) <= 6 else 128
        pw = max(S.tw(d, x, S.font("title", size)) for x in lines) + 220
        box = (W / 2 - pw / 2, 250, W / 2 + pw / 2, 250 + size * 1.18 * len(lines) + 150)
        S.pill(img, d, box, lines, size)
        left = chars[: (len(chars) + 1) // 2]
        right = chars[(len(chars) + 1) // 2:]
        side_w = (box[0] - 60) / max(1, len(left))
        for i, k in enumerate(left):
            paste_fit(img, A.art(k, 900), (40 + i * side_w * 0.92, 170, 40 + (i + 1) * side_w * 0.92 + 40, box[3] + 40))
        side_w = (W - box[2] - 60) / max(1, len(right))
        for i, k in enumerate(right):
            x = box[2] + 20 + i * side_w * 0.92
            paste_fit(img, A.art(k, 900), (x, 170, x + side_w * 0.92 + 40, box[3] + 40))
        S.leaf(img, box[2] - 40, box[1] + 10, 70, 35)
        y = box[3] + 70
    else:
        lines = [page["title"]]
        f = S.fit(d, page["title"], "title", 150, W - 2 * M - 560)
        size = f.size
        pw = S.tw(d, page["title"], f) + 240
        box = (W / 2 - pw / 2, 230, W / 2 + pw / 2, 230 + size * 1.18 + 130)
        S.pill(img, d, box, lines, size)
        S.sprig(img, box[0] - 110, box[3] - 10, 230)
        S.sprig(img, box[2] + 110, box[3] - 10, 230, mirror=True)
        y = box[3] + 60
    f = S.fit(d, page["instruction"], "body", 62, W - 2 * M - 220)
    text_w = S.tw(d, page["instruction"], f)
    x = W / 2 - (text_w + 130) / 2
    S.leaf_icon(img, x, y + 45, 110)
    d.text((x + 130, y + 45), page["instruction"], font=f, fill=S.INK_SOFT, anchor="lm")
    return y + 150


# ---------------------------------------------------------------- 활동(명세서 12종 + 세기)

def _word_grid(img, d, page, A, top, cols, rows, check=False, scissors=False):
    items = page["items"]
    boxes = grid(cols, rows, top, CONTENT_BOTTOM, gap=44)
    if scissors:
        _scissors(d, M - 10, top - 100, 60)
    for b, it in zip(boxes, items):
        S.card(d, b, radius=50)
        x0, y0, x1, y1 = b
        lh = min((y1 - y0) * 0.24, 190)
        paste_fit(img, A.art(it["asset"], 900), (x0 + 60, y0 + 40, x1 - 60, y1 - lh - 50))
        if it.get("word"):
            S.label(d, (x0 + 60, y1 - lh - 34, x1 - 60, y1 - 44), it["word"], size=int(lh * 0.62))
        if check:
            r = 46
            d.ellipse([x1 - 60 - 2 * r, y0 + 50, x1 - 60, y0 + 50 + 2 * r], outline=S.DOT, width=7, fill=(255, 255, 255))
    return {}


def word_cards(img, d, page, A, top, seed):
    n = len(page["items"])
    return _word_grid(img, d, page, A, top, 2, (n + 1) // 2, scissors=True)


def vocab_poster(img, d, page, A, top, seed):
    n = len(page["items"])
    return _word_grid(img, d, page, A, top, 4 if n == 8 else 3, 2)


def check_game(img, d, page, A, top, seed):
    n = len(page["items"])
    return _word_grid(img, d, page, A, top, 3 if n > 4 else 2, 2, check=True)


def coloring(img, d, page, A, top, seed):
    items = page["items"]
    n = len(items)
    boxes = grid(2, 1, top, CONTENT_BOTTOM) if n == 2 else grid(2, 2, top, CONTENT_BOTTOM)
    for b, it in zip(boxes, items):
        S.card(d, b)
        x0, y0, x1, y1 = b
        lh = 150 if it.get("word") else 0
        paste_fit(img, A.art(it["asset"], 1200), (x0 + 80, y0 + 80, x1 - 80, y1 - 70 - lh))
        if it.get("word"):
            S.center_text(d, (x0, y1 - 70 - lh, x1, y1 - 50), it["word"], S.font("title", 96))
    return {}


def trace_outline(img, d, page, A, top, seed):
    """흐린 밑그림 따라 그리기: 왼쪽에 작은 기준 그림, 오른쪽에 크게 점선 밑그림."""
    for b, it in zip(grid(2, 2, top, CONTENT_BOTTOM), page["items"]):
        S.card(d, b)
        x0, y0, x1, y1 = b
        w = x1 - x0
        ref = paste_fit(img, A.art(it["asset"], 700), (x0 + 60, y0 + (y1 - y0) * 0.28, x0 + w * 0.34, y1 - (y1 - y0) * 0.3))
        if it.get("word"):
            S.center_text(d, (x0 + 40, ref[3] + 20, x0 + w * 0.36, ref[3] + 120), it["word"], S.font("title", 74))
        paste_fit(img, A.outline(it["asset"], 1100), (x0 + w * 0.38, y0 + 90, x1 - 70, y1 - 90))
    return {}


def half_draw(img, d, page, A, top, seed):
    """반쪽 그림 완성: 왼쪽 반은 원화, 오른쪽 반은 같은 원화의 점선 윤곽(정확히 이어지게), 가운데 기준선."""
    for b, it in zip(grid(2, 2, top, CONTENT_BOTTOM), page["items"]):
        S.card(d, b)
        x0, y0, x1, y1 = b
        lh = 170
        area = (x0 + 90, y0 + 80, x1 - 90, y1 - lh - 60)
        art = A.art(it["asset"], 1100)
        ghost = A.outline(it["asset"], 1100, same_art=True)          # art와 같은 크기·같은 자리
        s = min((area[2] - area[0]) / art.width, (area[3] - area[1]) / art.height)
        w, h = int(art.width * s), int(art.height * s)
        px, py = int(area[0] + (area[2] - area[0] - w) / 2), int(area[1] + (area[3] - area[1] - h) / 2)
        art, ghost = art.resize((w, h), Image.LANCZOS), ghost.resize((w, h), Image.LANCZOS)
        half = w // 2
        left = art.crop((0, 0, half, h))
        right = ghost.crop((half, 0, w, h))
        img.paste(left, (px, py), left)
        img.paste(right, (px + half, py), right)
        cx = px + half
        S.dashed_line(d, [(cx, py - 30), (cx, py + h + 30)], fill=(190, 180, 170), width=5, dash=20, gap=14)
        if it.get("word"):
            S.label(d, (x0 + 110, y1 - lh - 30, x1 - 110, y1 - 50), it["word"])
    return {}


def _pencil(d, x, y, s, color):
    d.polygon([(x, y), (x - s * 0.5, y - s * 0.2), (x - s * 0.5, y + s * 0.2)], fill=(246, 214, 160))
    d.polygon([(x - s * 0.5, y - s * 0.2), (x - s * 2.4, y - s * 0.2), (x - s * 2.4, y + s * 0.2), (x - s * 0.5, y + s * 0.2)],
              fill=color)
    d.ellipse([x - s * 0.14, y - s * 0.07, x + s * 0.02, y + s * 0.07], fill=(60, 60, 60))


def _scissors(d, x, y, s):
    d.ellipse([x, y, x + s * 0.6, y + s * 0.6], outline=S.DOT, width=6)
    d.ellipse([x, y + s * 0.8, x + s * 0.6, y + s * 1.4], outline=S.DOT, width=6)
    d.line([(x + s * 0.55, y + s * 0.45), (x + s * 1.6, y + s * 1.1)], fill=S.DOT, width=8)
    d.line([(x + s * 0.55, y + s * 0.95), (x + s * 1.6, y + s * 0.3)], fill=S.DOT, width=8)


def path_points(kind: str, x0: float, x1: float, y: float, amp: float, n: int = 300):
    pts = []
    for i in range(n + 1):
        t = i / n
        x = x0 + (x1 - x0) * t
        if kind == "wave":
            dy = -amp * math.sin(t * math.pi * 6)
        elif kind == "zigzag":
            ph = (t * 7) % 1
            dy = -amp * (1 - 4 * abs(ph - 0.5))
        elif kind == "curve":
            dy = -amp * 1.2 * math.sin(t * math.pi)
        elif kind == "steps":
            dy = -amp * 0.8 if int(t * 6) % 2 else amp * 0.8
        elif kind == "loop":
            r = (x1 - x0) / 5 / (2 * math.pi) * 1.9
            th = t * 5 * 2 * math.pi
            x = x0 + (x1 - x0) * t - r * math.sin(th)
            dy = -r * (1 - math.cos(th)) * 1.1
        else:
            dy = 0
        pts.append((x, y + dy))
    if kind == "steps":
        out = [pts[0]]
        for p in pts[1:]:
            if abs(p[1] - out[-1][1]) > 1:
                out.append((p[0], out[-1][1]))
            out.append(p)
        pts = out
    return pts


PENCILS = [(110, 170, 80), (70, 130, 210), (240, 140, 60), (220, 90, 110)]


def _lines(img, d, page, A, top, cut: bool):
    items = page["items"]
    rows = grid(1, len(items), top, CONTENT_BOTTOM, gap=50)
    for i, (b, it) in enumerate(zip(rows, items)):
        S.card(d, b, radius=50)
        x0, y0, x1, y1 = b
        cy = (y0 + y1) / 2
        if cut:
            _scissors(d, x0 + 60, cy - 50, 70)
            xa = x0 + 210
        else:
            r = 92
            d.ellipse([x0 + 50, cy - r, x0 + 50 + 2 * r, cy + r], fill=(255, 255, 255), outline=S.LEAF_DARK, width=8)
            S.center_text(d, (x0 + 50, cy - r, x0 + 50 + 2 * r, cy + r), "시작", S.font("title", 70), S.LEAF_DARK)
            d.polygon([(x0 + 260, cy - 28), (x0 + 310, cy), (x0 + 260, cy + 28)], fill=S.LEAF_DARK)
            xa = x0 + 350
        end = x1 - 90
        if it.get("asset"):
            s = min(y1 - y0 - 80, 300)
            paste_fit(img, A.art(it["asset"], 600), (x1 - 60 - s, cy - s / 2, x1 - 60, cy + s / 2))
            end = x1 - 100 - s
        else:
            _pencil(d, x1 - 70, cy, 70, PENCILS[i % 4])
            end = x1 - 260
        pts = path_points(it.get("path", "straight"), xa, end, cy + (40 if it.get("path") == "curve" else 0),
                          amp=(y1 - y0) * 0.2)
        S.dashed_line(d, pts, fill=S.DOT if cut else (120, 100, 85), width=12 if cut else 10, dash=34, gap=22)
    return {}


def trace_lines(img, d, page, A, top, seed):
    return _lines(img, d, page, A, top, cut=False)


def cut_lines(img, d, page, A, top, seed):
    return _lines(img, d, page, A, top, cut=True)


def _match(img, d, page, A, top, seed, right):
    items = page["items"]
    n = len(items)
    order = _shuffled(n, seed + page["type"])
    rows = grid(1, n, top, CONTENT_BOTTOM, gap=30)
    for (x0, y0, x1, y1), it in zip(rows, items):
        s = min(y1 - y0 - 40, 470)
        lab = 90 if it.get("name") else 0
        pos = paste_fit(img, A.art(it["asset"], 900), (M + 40, y0 + 10, M + 40 + s, y1 - lab - 10))
        if lab:
            S.center_text(d, (pos[0] - 40, y1 - lab - 10, pos[2] + 40, y1), it["name"], S.font("body", 54))
        r = 24
        d.ellipse([M + s + 150 - r, (y0 + y1) / 2 - r, M + s + 150 + r, (y0 + y1) / 2 + r], fill=S.DOT)
    for slot, i in enumerate(order):
        x0, y0, x1, y1 = rows[slot]
        s = min(y1 - y0 - 40, 470)
        cy = (y0 + y1) / 2
        lab = 90 if items[i].get("name") else 0
        rx = right(i, (W - M - 40 - s, y0 + 10, W - M - 40, y1 - lab - 10))
        r = 24
        d.ellipse([rx - 110 - r, cy - r, rx - 110 + r, cy + r], fill=S.DOT)
    return {"answers": [order.index(i) + 1 for i in range(n)]}


def match_same(img, d, page, A, top, seed):
    items = page["items"]
    return _match(img, d, page, A, top, seed,
                  lambda i, box: paste_fit(img, A.art(items[i]["asset"], 900), box)[0])


def match_shadow(img, d, page, A, top, seed):
    items = page["items"]
    return _match(img, d, page, A, top, seed,
                  lambda i, box: paste_fit(img, A.shadow(items[i]["asset"], 900), box)[0])


def emotion_match(img, d, page, A, top, seed):
    items = page["items"]

    def word(i, box):
        x0, y0, x1, y1 = box
        cy = (y0 + y1) / 2
        b = (x1 - 560, cy - 120, x1, cy + 120)
        S.label(d, b, items[i]["word"], size=120)
        return b[0]
    return _match(img, d, page, A, top, seed, word)


def trace_letters(img, d, page, A, top, seed):
    """낱말 따라 쓰기: 그림 + 점선 글자 + 빈 쓰기 칸."""
    rows = grid(1, len(page["items"]), top, CONTENT_BOTTOM, gap=40)
    for (x0, y0, x1, y1), it in zip(rows, page["items"]):
        S.card(d, (x0, y0, x1, y1), radius=50)
        h = y1 - y0
        paste_fit(img, A.art(it["asset"], 700), (x0 + 60, y0 + 50, x0 + 60 + h - 100, y1 - 50))
        word = it["word"]
        gx0, gx1 = x0 + h + 20, x1 - h * 0.95
        f = S.fit(d, word, "title", int(h * 0.62), gx1 - gx0 - 40)
        layer = Image.new("L", (int(gx1 - gx0), int(h)), 0)
        S.center_text(ImageDraw.Draw(layer), (0, 0, layer.width, layer.height), word, f, 255)
        edge = ImageChops.subtract(layer.filter(ImageFilter.MaxFilter(9)), layer.filter(ImageFilter.MinFilter(5)))
        step = 12
        pat = Image.new("L", layer.size, 0)
        pd = ImageDraw.Draw(pat)
        for yy in range(0, layer.height, step):
            for xx in range(0, layer.width, step):
                if ((xx // step) + (yy // step)) % 2 == 0:
                    pd.rectangle([xx, yy, xx + step - 1, yy + step - 1], fill=255)
        mask = ImageChops.multiply(edge, pat)
        col = Image.new("RGBA", layer.size, (170, 150, 135, 0))
        col.putalpha(mask)
        img.paste(col, (int(gx0), int(y0)), col)
        bx = (x1 - h * 0.95 + 20, y0 + 50, x1 - 50, y1 - 50)
        d.rounded_rectangle(bx, radius=40, fill=(255, 255, 255), outline=S.LABEL_EDGE, width=6)
    return {}


def cut_paste(img, d, page, A, top, seed):
    """오려붙이기 미니판: 위에 큰 붙임 공간(바구니 등 선 그림), 아래 절취선과 조각."""
    split = top + (CONTENT_BOTTOM - top) * 0.64
    big = (M, top, W - M, split)
    S.card(d, big)
    paste_fit(img, A.art(page["container"], 1400), (M + 160, top + 80, W - M - 160, split - 140))
    S.center_text(d, (M, split - 130, W - M, split - 50), "여기에 자유롭게 붙여요", S.font("body", 50), S.INK_SOFT)
    y = split + 90
    S.dashed_line(d, [(M, y), (W - M, y)], fill=S.DOT, width=6, dash=26, gap=18)
    _scissors(d, W - M - 120, y - 52, 60)
    S.center_text(d, (M, y - 46, M + 260, y + 46), "오려요", S.font("title", 52), S.INK_SOFT)
    items = page["items"]
    boxes = grid(len(items), 1, y + 80, CONTENT_BOTTOM, gap=90, left=M + 60, right=W - M - 60)
    for b, it in zip(boxes, items):
        S.cut_box(d, b)
        x0, y0, x1, y1 = b
        paste_fit(img, A.art(it["asset"], 700), (x0 + 50, y0 + 50, x1 - 50, y1 - 50))
    return {}


def count_write(img, d, page, A, top, seed):
    """세어 보고 숫자 쓰기: 6~8문제. 그림은 한 줄(많으면 두 줄)로 작게, 오른쪽에 숫자 칸."""
    items = page["items"]
    cols = 1 if len(items) <= 6 else 2
    rows = grid(cols, math.ceil(len(items) / cols), top, CONTENT_BOTTOM, gap=34)
    for (x0, y0, x1, y1), it in zip(rows, items):
        h = y1 - y0
        ans = min(h - 50, 300)
        S.card(d, (x0, y0, x1 - ans - 50, y1), radius=40)
        n = it["count"]
        inner_w = x1 - ans - 50 - x0 - 100
        one_line = inner_w / n
        lines = 1 if one_line >= (h - 60) * 0.6 or n <= 5 else 2
        per = n if lines == 1 else math.ceil(n / 2)
        cell = min(inner_w / per, (h - 60) / lines)
        for k in range(n):
            row, col = divmod(k, per)
            here = per if row < lines - 1 else n - per * (lines - 1)
            cx0 = x0 + 50 + (inner_w - here * cell) / 2 + col * cell
            cy0 = (y0 + y1) / 2 - lines * cell / 2 + row * cell
            paste_fit(img, A.art(it["asset"], 400), (cx0 + 8, cy0 + 8, cx0 + cell - 8, cy0 + cell - 8))
        b = (x1 - ans - 10, (y0 + y1) / 2 - ans / 2, x1 - 10, (y0 + y1) / 2 + ans / 2)
        d.rounded_rectangle(b, radius=40, fill=(255, 255, 255), outline=S.LABEL_EDGE, width=8)
    return {"answers": [it["count"] for it in items]}


DRAW = {
    "word_cards": word_cards, "cut_lines": cut_lines, "trace_outline": trace_outline, "coloring": coloring,
    "match_same": match_same, "match_shadow": match_shadow, "half_draw": half_draw, "cut_paste": cut_paste,
    "trace_letters": trace_letters, "vocab_poster": vocab_poster, "emotion_match": emotion_match,
    "check_game": check_game, "trace_lines": trace_lines, "count_write": count_write,
}


def render_page(spec: dict, page: dict, A: Assets, blog_url: str) -> tuple[Image.Image, dict]:
    img = Image.new("RGB", (W, H), S.PAPER)
    d = ImageDraw.Draw(img)
    top = header(img, d, spec, page, A)
    info = DRAW[page["type"]](img, d, page, A, top + 20, spec["set_id"])
    S.grass(img, H - S.BAND_H - 30)
    S.band(img, blog_url)
    return img, info


def render(spec: dict, lib: Path, out_dir: Path, blog_url: str = "") -> dict:
    S.ensure_fonts()
    A = Assets(lib)
    pages, blog, answers = [], [], {}
    out_dir.mkdir(parents=True, exist_ok=True)
    for no, page in enumerate(spec["pages"], 1):
        img, info = render_page(spec, page, A, blog_url)
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
    """16:9 미리보기: 크림 바탕에 장들을 살짝 기울여 겹쳐 놓는다."""
    cw, ch = 1600, 900
    bg = Image.new("RGB", (cw, ch), (250, 236, 210))
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
