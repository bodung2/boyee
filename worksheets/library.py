"""원화 보관함: 활동지에 쓰는 그림을 한 장씩 고품질로 만들어 모아 두고 다음 활동지에서도 다시 쓴다.

- 위치: data/worksheets/assets/<key>.png + index.json (WORKSHEET_ASSETS로 바꿀 수 있음, 저장소에는 올리지 않는다)
- 종류(kind): color(색이 있는 그림) / line(색칠용 검은 선 그림)
- 새로 그린 그림은 status "new"로 두었다가 검수(QA)를 통과하면 "ok"가 된다. 떨어지면 지우고 다시 그린다.
- 같은 그림체를 지키려고, 새 그림을 그릴 때 보관함의 검수 통과 그림 2장을 참고 그림으로 함께 보낸다.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date
from pathlib import Path

from PIL import Image

log = logging.getLogger(__name__)
SIZE = 1024
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_]{1,40}$")

# 블로그 주인 워크북(「동물 친구들의 소풍 준비」) 원화와 같은 수준·그림체. 첫 원화부터 출판 그림책 수준을 요구한다.
STYLE = {
    "color": ("Premium hand-painted children's picture-book illustration, the quality of a published Korean picture book. "
              "Soft layered watercolor washes with fine colored-pencil texture on top, warm natural palette, delicate "
              "warm-brown pencil outlines (never thick black lines), gentle highlights and soft shading with light from "
              "the upper left, subtle paper grain. Rounded, friendly proportions; animals have cute expressive eyes and "
              "a small smile. Rich detail inside, but a clean, instantly recognizable silhouette (the most typical shape "
              "of this subject that a 4-year-old would know). "
              "ONE subject only, centered, filling about 75% of the square, fully inside the frame with a clear white "
              "margin on every side (nothing cut off). Plain pure white background (#FFFFFF), only a very faint soft "
              "contact shadow under it, no scenery, no frame."),
    "line": ("Clean black-and-white coloring-book line art for preschoolers (ages 3-6), traced in the same proportions as "
             "a premium picture-book illustration. Smooth, closed black outlines of even weight (about 6-8px at 1024px), "
             "a few simple inner details that help coloring, no shading, no gray, no hatching, no filled black areas, no "
             "broken or sketchy lines. ONE subject only, centered, filling about 75% of the square, fully inside the "
             "frame with a clear white margin. Plain pure white background, no scenery, no frame."),
}
QUALITY_CHECK = ("Before you finish, check the image yourself: the subject exactly matches the description, its shape is "
                 "the typical one a child recognizes, the style matches the reference images, there is no text at all, "
                 "and nothing touches or is cut off by the edges. If any check fails, generate it again.\n")
TAIL = """
Square image, 1024x1024.
Absolutely no text, no letters, no numbers, no captions, no logos, no watermark anywhere in the image.

Use your built-in image generation tool to create this image. After it is generated, STOP.
Do not move, copy, rename, save, or relocate the file, and do not run any shell command to find it.
Leave it in your default generated-images directory; it will be collected automatically."""
REF_NOTE = ("The attached images are the master illustrations of this worksheet series (the owner's own workbook art). "
            "Match their drawing style, texture, line weight and color palette exactly, but draw the new subject "
            "described below (do not copy their subjects).\n")


def root(data_dir: Path) -> Path:
    return Path(os.environ.get("WORKSHEET_ASSETS") or data_dir / "worksheets" / "assets")


def load(lib: Path) -> dict:
    try:
        return json.loads((lib / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save(lib: Path, index: dict) -> None:
    lib.mkdir(parents=True, exist_ok=True)
    tmp = lib / "index.json.tmp"
    tmp.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(lib / "index.json")


def path(lib: Path, key: str) -> Path:
    return lib / f"{key}.png"


def catalog(lib: Path) -> list[dict]:
    """설계 단계에 넘기는 목록: 검수를 통과해 다시 쓸 수 있는 그림만. character는 머리에 세울 고정 캐릭터."""
    index = load(lib)
    return [{"key": k, "name": v.get("name", ""), "kind": v.get("kind", "color"), "used": len(v.get("used") or []),
             **({"character": True} if v.get("character") else {}), **({"master": True} if v.get("master") else {}),
             **({"open": True} if v.get("open") else {}),
             **({"has_line": True} if f"{k}_line" in index else {})}
            for k, v in sorted(index.items())
            if v.get("status") == "ok" and not v.get("clipped") and path(lib, k).exists()]


SEED_FILE = Path(__file__).with_name("seed_assets.json")


def _clean_crop(img: Image.Image, box) -> Image.Image:
    x, y, w, h = box
    c = img.convert("RGB").crop((x - 6, y - 6, x + w + 6, y + h + 6))
    px = c.load()
    for yy in range(c.height):                  # 크림색 종이·흰 칸 배경을 흰색으로
        for xx in range(c.width):
            r, g, b = px[xx, yy]
            if r > 243 and g > 240 and b > 228 and max(r, g, b) - min(r, g, b) < 22:
                px[xx, yy] = (255, 255, 255)
    side = int(max(c.size) * 1.12)
    sq = Image.new("RGB", (side, side), "white")
    sq.paste(c, ((side - c.width) // 2, (side - c.height) // 2))
    return sq.resize((SIZE, SIZE), Image.LANCZOS)


def seed(docx: Path, lib: Path) -> list[str]:
    """블로그 주인 워크북 명세서(docx)의 예시 페이지에서 고정 캐릭터·사물 원화를 잘라 보관함에 넣는다(검수 통과로).
    이 그림들이 새 그림의 그림체 기준(master)이 된다. 이미 있는 그림은 건드리지 않는다."""
    import zipfile
    seeds = json.loads(SEED_FILE.read_text(encoding="utf-8"))["assets"]
    index, added = load(lib), []
    with zipfile.ZipFile(docx) as z:
        media = {Path(n).name: n for n in z.namelist() if n.startswith("word/media/")}
        pages: dict[str, Image.Image] = {}
        for key, info in seeds.items():
            if info.get("skip") or (key in index and path(lib, key).exists()):
                continue
            name = info["image"]
            if name not in media:
                raise ValueError(f"docx에 {name}이 없습니다(같은 명세서 파일인지 확인)")
            if name not in pages:
                import io
                pages[name] = Image.open(io.BytesIO(z.read(media[name])))
            if pages[name].size != (2480, 3508):
                raise ValueError(f"{name} 크기가 다릅니다({pages[name].size}). 같은 명세서 파일인지 확인하세요")
            lib.mkdir(parents=True, exist_ok=True)
            _clean_crop(pages[name], info["box"]).save(path(lib, key), "PNG", optimize=True)
            index[key] = {"name": info["name"], "kind": info["kind"], "prompt": info["prompt"], "status": "ok",
                          "master": True, **({"character": True} if info.get("character") else {}),
                          "created": date.today().isoformat(), "used": []}
            added.append(key)
    save(lib, index)
    return added


def to_square(src: Path, out: Path) -> None:
    """가운데 정사각형으로 맞추고(모자라면 흰 여백) SIZE로 저장한다."""
    img = Image.open(src).convert("RGB")
    w, h = img.size
    side = max(w, h)
    canvas = Image.new("RGB", (side, side), "white")
    canvas.paste(img, ((side - w) // 2, (side - h) // 2))
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.resize((SIZE, SIZE), Image.LANCZOS).save(out, "PNG", optimize=True)


def prompt_for(asset: dict, margin: bool = False) -> str:
    kind = asset.get("kind", "color")
    return (f"{MARGIN_NOTE if margin else ''}{STYLE.get(kind, STYLE['color'])}\n"
            f"Subject: {asset['prompt'].strip()}\n{QUALITY_CHECK}{TAIL}")


def _references(lib: Path, index: dict, kind: str, limit: int = 2) -> list[Path]:
    """그림체 기준 그림: 워크북 원화(master)를 먼저, 그다음 많이 쓴 그림. 색 그림은 캐릭터 1 + 사물 1."""
    ok = [k for k, v in index.items() if v.get("status") == "ok" and v.get("kind", "color") == kind
          and path(lib, k).exists()]
    ok.sort(key=lambda k: (not index[k].get("master"), -len(index[k].get("used") or [])))
    if kind == "color":
        chars = [k for k in ok if index[k].get("character")]
        things = [k for k in ok if not index[k].get("character")]
        ok = chars[:1] + things[:1] + [k for k in ok if k not in chars[:1] + things[:1]]
    return [path(lib, k) for k in ok[:limit]]


MARGIN_NOTE = ("IMPORTANT: draw the subject smaller (about 70% of the square) with a wide white margin on every side. "
               "No part of it may touch or be cut off by the edges of the image.\n")


def touches_edge(img: Image.Image, border: int = 4, threshold: int = 235) -> bool:
    """그림이 정사각형 가장자리에 닿았는지(잘린 그림). 흰 배경 위 한 가지 사물이어야 하므로 닿으면 잘린 것이다."""
    g = img.convert("L")
    w, h = g.size
    for box in ((0, 0, w, border), (0, h - border, w, h), (0, 0, border, h), (w - border, 0, w, h)):
        if g.crop(box).getextrema()[0] < threshold:
            return True
    return False


def _draw_once(cfg, out: Path, prompt: str, refs: list[Path], gen=None) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if gen is not None:
        gen(cfg, prompt, out, refs)
    elif cfg.image_backend == "codex":
        from naver_autopost import codex_image
        codex_image.run_for_image(cfg, prompt, out, to_square, cfg.codex_image_timeout, what="원화", images=refs)
    else:                                   # gemini·openai는 16:9로 나오므로 가운데를 정사각형으로 맞춘다
        from naver_autopost.pipeline import image_generator
        tmp = out.with_suffix(".tmp.png")
        image_generator(cfg).generate_image(cfg, prompt, tmp)
        img = Image.open(tmp)
        side = min(img.size)
        img.crop(((img.width - side) // 2, (img.height - side) // 2,
                  (img.width + side) // 2, (img.height + side) // 2)).save(tmp)
        to_square(tmp, out)
        tmp.unlink(missing_ok=True)


def candidates_count(lib: Path) -> int:
    """원화 하나에 몇 장을 그려 고를지. 보관함이 작은 초반(새 원화 40장 미만)에는 2장 그려 더 나은 것을 고른다."""
    import os
    if os.environ.get("WORKSHEET_CANDIDATES"):
        return max(1, int(os.environ["WORKSHEET_CANDIDATES"]))
    made = sum(1 for v in load(lib).values() if v.get("status") == "ok" and not v.get("master"))
    return 2 if made < 40 else 1


def _draw_one(cfg, out: Path, asset: dict, refs: list[Path], gen=None) -> bool:
    """한 장 그리기. 가장자리에서 잘리면 여백을 크게 해서 한 번 더. 잘렸으면 True."""
    _draw_once(cfg, out, (REF_NOTE if refs else "") + prompt_for(asset), refs, gen)
    if touches_edge(Image.open(out)):
        log.warning("원화가 가장자리에서 잘렸습니다(다시 그림): %s", asset["key"])
        _draw_once(cfg, out, (REF_NOTE if refs else "") + prompt_for(asset, margin=True), refs, gen)
    return touches_edge(Image.open(out))


def _register(lib: Path, asset: dict, clipped: bool) -> None:
    index = load(lib)
    index[asset["key"]] = {"name": asset.get("name", ""), "prompt": asset["prompt"], "kind": asset.get("kind", "color"),
                           "status": "new", "created": date.today().isoformat(), "used": [],
                           **({"open": True} if asset.get("open") else {}),
                           **({"character": True} if asset.get("character") else {}),
                           **({"clipped": True} if clipped else {})}
    save(lib, index)
    log.info("원화 새로 그림: %s (%s)", asset["key"], asset.get("name", ""))


def draw(cfg, lib: Path, asset: dict, gen=None) -> Path:
    """그림 한 장을 새로 그려 보관함에 넣는다(status new). gen(cfg, prompt, out, refs)는 테스트용."""
    out = path(lib, asset["key"])
    refs = _references(lib, load(lib), asset.get("kind", "color"))
    _register(lib, asset, _draw_one(cfg, out, asset, refs, gen))
    return out


def ensure(cfg, lib: Path, assets: list[dict], gen=None, pick=None) -> list[str]:
    """spec의 그림이 보관함에 없으면 그린다. 새로 그린 key 목록을 돌려준다.
    pick(후보 {key: [경로…]}, 기준 그림 [경로…]) → {key: 고른 번호(1부터) 또는 0(모두 별로)}을 주면,
    초반에는 원화마다 후보를 여러 장 그려 Claude가 워크북 원화와 비교해 가장 나은 것을 고른다."""
    import shutil
    index = load(lib)
    todo = [a for a in assets if not (index.get(a["key"], {}).get("status") in ("ok", "new")
                                      and path(lib, a["key"]).exists())]
    n = candidates_count(lib) if pick else 1
    if n <= 1 or not todo:
        for a in todo:
            draw(cfg, lib, a, gen)
        return [a["key"] for a in todo]
    cand_dir = lib / "_candidates"
    cands: dict[str, list[Path]] = {}
    clipped: dict[Path, bool] = {}
    refs_all: list[Path] = []
    for a in todo:
        refs = _references(lib, load(lib), a.get("kind", "color"))
        refs_all += [r for r in refs if r not in refs_all]
        cands[a["key"]] = []
        for i in range(1, n + 1):
            p = cand_dir / f"{a['key']}__{i}.png"
            clipped[p] = _draw_one(cfg, p, a, refs, gen)
            cands[a["key"]].append(p)
    choice = pick(cands, refs_all) or {}
    for a in todo:
        ps = cands[a["key"]]
        k = int(choice.get(a["key"], 1) or 0)
        if 1 <= k <= len(ps):
            chosen = ps[k - 1]
        else:                                   # 후보가 모두 별로: 고칠 프롬프트로 한 장 더(그다음은 검수가 본다)
            fix = (choice.get("_fix") or {}).get(a["key"])
            a = {**a, "prompt": fix or a["prompt"]}
            chosen = cand_dir / f"{a['key']}__fix.png"
            clipped[chosen] = _draw_one(cfg, chosen, a, _references(lib, load(lib), a.get("kind", "color")), gen)
        shutil.copyfile(chosen, path(lib, a["key"]))
        _register(lib, a, clipped.get(chosen, False))
    shutil.rmtree(cand_dir, ignore_errors=True)
    return [a["key"] for a in todo]


def accept(lib: Path, keys: list[str], set_id: str) -> None:
    """검수를 통과한 활동지에 쓰인 그림: new → ok, 쓰인 활동지 기록."""
    index = load(lib)
    for k in keys:
        if k in index:
            index[k]["status"] = "ok"
            used = index[k].setdefault("used", [])
            if set_id not in used:
                used.append(set_id)
    save(lib, index)


def reject(lib: Path, keys: list[str], reasons: dict | None = None) -> None:
    """검수에서 떨어진 그림은 지운다(다음에 다시 그린다). 이유는 rejected.json에 남겨 프롬프트를 고칠 때 본다."""
    index = load(lib)
    log_path = lib / "rejected.json"
    try:
        past = json.loads(log_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        past = []
    for k in keys:
        info = index.pop(k, None)
        path(lib, k).unlink(missing_ok=True)
        past.append({"key": k, "date": date.today().isoformat(), "reason": (reasons or {}).get(k, ""),
                     "prompt": (info or {}).get("prompt", "")})
    save(lib, index)
    log_path.write_text(json.dumps(past[-200:], ensure_ascii=False, indent=1), encoding="utf-8")


def cutout(img: Image.Image, threshold: int = 238) -> Image.Image:
    """흰 배경을 투명하게(그림자 찾기·겹쳐 그리기용). 바깥에서 이어진 흰색만 지운다(흰 토끼 몸은 남는다)."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return _cutout_py(img, threshold)
    rgb = np.asarray(img.convert("RGB"))
    light = (rgb.min(axis=2) >= threshold).astype(np.uint8)
    h, w = light.shape
    pad = np.ones((h + 2, w + 2), np.uint8)
    pad[1:-1, 1:-1] = light                     # 가장자리를 흰색으로 둘러 어느 모서리에서든 바깥이 이어지게
    mask = np.zeros((h + 4, w + 4), np.uint8)
    cv2.floodFill(pad, mask, (0, 0), 2, loDiff=0, upDiff=0, flags=4)
    outside = pad[1:-1, 1:-1] == 2
    alpha = np.where(outside, 0, 255).astype(np.uint8)
    alpha = cv2.GaussianBlur(alpha, (3, 3), 0)  # 가장자리 계단 줄이기
    out = img.convert("RGBA")
    out.putalpha(Image.fromarray(alpha))
    return out


def _cutout_py(img: Image.Image, threshold: int = 238) -> Image.Image:
    rgba = img.convert("RGBA")
    w, h = rgba.size
    px = rgba.load()
    seen = bytearray(w * h)
    stack = [(x, y) for x in range(w) for y in (0, h - 1)] + [(x, y) for y in range(h) for x in (0, w - 1)]
    while stack:
        x, y = stack.pop()
        i = y * w + x
        if seen[i]:
            continue
        seen[i] = 1
        r, g, b, _ = px[x, y]
        if min(r, g, b) < threshold:
            continue
        px[x, y] = (255, 255, 255, 0)
        if x > 0: stack.append((x - 1, y))
        if x < w - 1: stack.append((x + 1, y))
        if y > 0: stack.append((x, y - 1))
        if y < h - 1: stack.append((x, y + 1))
    return rgba


def silhouette(img: Image.Image, color=(120, 120, 128)) -> Image.Image:
    """그림의 그림자(단색 실루엣)."""
    cut = cutout(img)
    alpha = cut.getchannel("A")
    shadow = Image.new("RGBA", cut.size, color + (255,))
    shadow.putalpha(alpha)
    return shadow
