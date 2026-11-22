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

STYLE = {
    "color": ("Cute, warm children's picture-book clip art for a preschool worksheet (ages 3-6). "
              "Soft rounded shapes, clean dark-brown outlines of even thickness, flat pastel colors with gentle shading, "
              "friendly and simple so a 4-year-old recognizes it at a glance. "
              "ONE subject only, centered, filling about 80% of the square, fully inside the frame (nothing cut off). "
              "Plain pure white background (#FFFFFF), no floor, no cast shadow, no scenery, no frame."),
    "line": ("Black-and-white coloring-book line art for preschoolers (ages 3-6). Thick, clean, closed black outlines "
             "(about 8px at 1024px), large simple areas that are easy to color, no shading, no gray, no hatching, "
             "no filled black areas. ONE subject only, centered, filling about 80% of the square, fully inside the frame. "
             "Plain pure white background, no scenery, no frame."),
}
TAIL = """
Square image, 1024x1024.
Absolutely no text, no letters, no numbers, no captions, no logos, no watermark anywhere in the image.

Use your built-in image generation tool to create this image. After it is generated, STOP.
Do not move, copy, rename, save, or relocate the file, and do not run any shell command to find it.
Leave it in your default generated-images directory; it will be collected automatically."""
REF_NOTE = ("The attached images are earlier illustrations from the same worksheet series. Match their drawing style, "
            "line weight and color palette exactly, but draw the new subject described below (do not copy their subjects).\n")


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
    """설계 단계에 넘기는 목록: 검수를 통과해 다시 쓸 수 있는 그림만."""
    return [{"key": k, "name": v.get("name", ""), "kind": v.get("kind", "color"), "used": len(v.get("used") or [])}
            for k, v in sorted(load(lib).items()) if v.get("status") == "ok" and path(lib, k).exists()]


def to_square(src: Path, out: Path) -> None:
    """가운데 정사각형으로 맞추고(모자라면 흰 여백) SIZE로 저장한다."""
    img = Image.open(src).convert("RGB")
    w, h = img.size
    side = max(w, h)
    canvas = Image.new("RGB", (side, side), "white")
    canvas.paste(img, ((side - w) // 2, (side - h) // 2))
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.resize((SIZE, SIZE), Image.LANCZOS).save(out, "PNG", optimize=True)


def prompt_for(asset: dict) -> str:
    kind = asset.get("kind", "color")
    return f"{STYLE.get(kind, STYLE['color'])}\nSubject: {asset['prompt'].strip()}\n{TAIL}"


def _references(lib: Path, index: dict, kind: str, limit: int = 2) -> list[Path]:
    ok = [k for k, v in index.items() if v.get("status") == "ok" and v.get("kind", "color") == kind
          and path(lib, k).exists()]
    ok.sort(key=lambda k: -len(index[k].get("used") or []))      # 많이 쓴(대표) 그림을 기준으로
    return [path(lib, k) for k in ok[:limit]]


def draw(cfg, lib: Path, asset: dict, gen=None) -> Path:
    """그림 한 장을 새로 그려 보관함에 넣는다(status new). gen(cfg, prompt, out, refs)는 테스트용."""
    index = load(lib)
    out = path(lib, asset["key"])
    refs = _references(lib, index, asset.get("kind", "color"))
    prompt = (REF_NOTE if refs else "") + prompt_for(asset)
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
    index = load(lib)
    index[asset["key"]] = {"name": asset.get("name", ""), "prompt": asset["prompt"], "kind": asset.get("kind", "color"),
                           "status": "new", "created": date.today().isoformat(), "used": []}
    save(lib, index)
    log.info("원화 새로 그림: %s (%s)", asset["key"], asset.get("name", ""))
    return out


def ensure(cfg, lib: Path, assets: list[dict], gen=None) -> list[str]:
    """spec의 그림이 보관함에 없으면 그린다. 새로 그린 key 목록을 돌려준다."""
    index, made = load(lib), []
    for a in assets:
        known = index.get(a["key"])
        if known and known.get("status") in ("ok", "new") and path(lib, a["key"]).exists():
            continue
        draw(cfg, lib, a, gen)
        made.append(a["key"])
    return made


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
    """흰 배경을 투명하게(그림자 찾기·겹쳐 그리기용). 바깥에서 이어진 흰색만 지운다."""
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
