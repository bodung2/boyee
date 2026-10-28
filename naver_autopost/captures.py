"""공식 사이트 화면 캡처: 글쓴이가 post.json "captures"에 적은 관공서·공공기관 페이지를 실제로 열어 찍고,
누를 곳(버튼·메뉴 글자)에 빨간 네모를 그려 본문에 넣는다. 생성 그림 대신 '진짜 화면'을 보여 주는 게 목적이다.

- 공식 주소만 연다(.go.kr 등 + 공공기관 목록). 로그인하지 않고, 로그인 화면으로 넘어가면 그 캡처는 뺀다.
- 레이어 팝업(오늘 하루 보지 않기 등)은 화면에서 숨긴다(누르지 않는다).
- 오류·점검 화면, 거의 빈 화면은 뺀다. 내용이 맞는지(캡션과 같은 화면인지)는 Claude 팩트체크가 눈으로 본다.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageChops, ImageDraw, ImageStat

log = logging.getLogger(__name__)

OFFICIAL_SUFFIXES = (".go.kr", ".mil.kr", ".re.kr")
# .or.kr 등 다른 주소를 쓰는 공공기관(시험 시행기관·공단). 더 넣으려면 .env의 CAPTURE_EXTRA_HOSTS(쉼표로).
OFFICIAL_HOSTS = {
    "gov.kr", "gosi.kr", "q-net.or.kr", "hrdkorea.or.kr", "license.korcham.net", "korcham.net",
    "kdata.or.kr", "dataq.or.kr", "kpc.or.kr", "kofia.or.kr", "kbi.or.kr", "kicpa.or.kr",
    "safedriving.or.kr", "koroad.or.kr", "khug.or.kr", "lh.or.kr", "nhis.or.kr", "nps.or.kr",
    "kcomwel.or.kr", "klac.or.kr", "kosha.or.kr", "kead.or.kr", "kotsa.or.kr", "kca.go.kr",
}
VIEWPORT = {"width": 1280, "height": 1000}
SCALE = 2                       # 선명하게 2배로 찍는다(모바일에서 글자가 보이게)
MIN_W, MIN_H = 880, 560         # 초점 영역을 잘라낼 때 최소 크기(CSS px)
MAX_W, MAX_H = 1280, 1000
BOX_COLOR = (229, 57, 53)
_ERROR_PAGE = re.compile(r"페이지를 찾을 수 없|요청하신 페이지|404 Not Found|서비스 점검|시스템 점검|접근이 제한|"
                         r"잘못된 접근|권한이 없습니다|Access Denied|Forbidden", re.I)
_LOGIN_URL = re.compile(r"login|logon|signin|/sso/", re.I)

# 화면을 덮는 레이어 팝업·쿠키 배너를 숨긴다(뷰포트의 15% 이상을 덮는 고정·절대 위치 요소 중 위에 뜬 것).
_HIDE_OVERLAYS = """() => {
  const vw = innerWidth, vh = innerHeight; let n = 0;
  for (const el of document.querySelectorAll('body *')) {
    const cs = getComputedStyle(el);
    if (cs.position !== 'fixed' && cs.position !== 'absolute') continue;
    if ((parseInt(cs.zIndex) || 0) < 50) continue;
    const r = el.getBoundingClientRect();
    if (r.width * r.height < vw * vh * 0.15) continue;
    if ((el.innerText || '').length > 4000) continue;      // 본문을 담은 틀은 그대로 둔다
    el.style.setProperty('display', 'none', 'important'); n++;
  }
  document.documentElement.style.overflow = 'auto'; document.body.style.overflow = 'auto';
  return n;
}"""


class CaptureError(RuntimeError):
    pass


def is_official(url: str) -> bool:
    try:
        u = urlparse(url)
    except ValueError:
        return False
    host = (u.hostname or "").lower()
    if u.scheme not in ("https", "http") or not host:
        return False
    extra = {h.strip().lower() for h in os.environ.get("CAPTURE_EXTRA_HOSTS", "").split(",") if h.strip()}
    if host.endswith(OFFICIAL_SUFFIXES):
        return True
    return any(host == h or host.endswith("." + h) for h in OFFICIAL_HOSTS | extra)


def _visible_box(page, text: str, exact: bool = False) -> dict | None:
    """화면에 보이는 요소 중 글자가 text인(또는 포함하는) 가장 작은 요소의 위치(뷰포트 기준, CSS px)."""
    text = (text or "").strip()
    if not text:
        return None
    for frame in [page.main_frame, *[f for f in page.frames if f is not page.main_frame]]:
        try:
            loc = frame.get_by_text(text, exact=exact)
            n = min(loc.count(), 8)
        except Exception:  # noqa: BLE001
            continue
        best = None
        for i in range(n):
            try:
                el = loc.nth(i)
                if not el.is_visible():
                    continue
                box = el.bounding_box()
            except Exception:  # noqa: BLE001
                continue
            if box and box["width"] > 2 and box["height"] > 2 and (best is None or
                                                                    box["width"] * box["height"] < best["width"] * best["height"]):
                best = box
        if best:
            return best
    return None


def _clip_around(box: dict | None, page_w: float, page_h: float) -> dict:
    """초점 요소를 가운데 두는 잘라낼 영역(뷰포트 기준). 초점이 없으면 화면 맨 위."""
    if not box:
        return {"x": 0, "y": 0, "width": min(MAX_W, page_w), "height": min(MAX_H * 0.8, page_h)}
    w = min(MAX_W, max(MIN_W, box["width"] + 160))
    h = min(MAX_H, max(MIN_H, box["height"] + 240))
    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
    x = max(0, min(cx - w / 2, page_w - w))
    y = max(0, min(cy - h / 3, page_h - h))     # 초점은 위쪽 1/3쯤에(위 문맥보다 아래 내용이 더 쓸모 있다)
    return {"x": x, "y": y, "width": min(w, page_w), "height": min(h, page_h)}


def draw_boxes(img: Image.Image, boxes: list[dict], clip: dict, scale: int = SCALE) -> Image.Image:
    """누를 곳에 빨간 둥근 네모(여러 개면 번호도). boxes는 뷰포트 기준 CSS px."""
    draw = ImageDraw.Draw(img)
    numbered = len(boxes) > 1
    for i, b in enumerate(boxes, 1):
        pad = 6
        x0 = (b["x"] - clip["x"] - pad) * scale
        y0 = (b["y"] - clip["y"] - pad) * scale
        x1 = (b["x"] + b["width"] - clip["x"] + pad) * scale
        y1 = (b["y"] + b["height"] - clip["y"] + pad) * scale
        if x1 < 0 or y1 < 0 or x0 > img.width or y0 > img.height:
            continue
        draw.rounded_rectangle([x0, y0, x1, y1], radius=6 * scale, outline=BOX_COLOR, width=3 * scale)
        if numbered:
            r = 13 * scale
            cx, cy = max(r, x0), max(r, y0)
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=BOX_COLOR)
            from .images import _font   # 글꼴 찾기는 썸네일과 같은 방법
            f = _font("bold", 16 * scale)
            t = str(i)
            tw = draw.textlength(t, font=f)
            draw.text((cx - tw / 2, cy - 10 * scale), t, font=f, fill="#ffffff")
    return img


def trim_margins(img: Image.Image, min_w: int, min_h: int, pad: int = 24) -> Image.Image:
    """오른쪽·아래의 빈 여백(오른쪽 아래 모서리와 같은 색)을 잘라 글자가 모바일에서 더 크게 보이게 한다.
    왼쪽·위는 자르지 않는다(초점·빨간 네모 위치가 그대로). 최소 크기 아래로는 줄이지 않는다."""
    bg = img.getpixel((img.width - 1, img.height - 1))
    box = ImageChops.difference(img, Image.new("RGB", img.size, bg)).convert("L").point(lambda v: 255 if v > 12 else 0).getbbox()
    if not box:
        return img
    right = min(img.width, max(min_w, box[2] + pad))
    bottom = min(img.height, max(min_h, box[3] + pad))
    return img.crop((0, 0, right, bottom)) if (right, bottom) != img.size else img


def looks_blank(img: Image.Image) -> bool:
    stat = ImageStat.Stat(img.convert("L"))
    return stat.stddev[0] < 6


def capture_one(page, spec: dict, out: Path) -> dict:
    """spec: {"url", "focus", "highlight": [..], ...} → {"path", "focused", "boxes", "final_url", "title"}"""
    url = str(spec.get("url") or "").strip()
    resp = page.goto(url, wait_until="domcontentloaded", timeout=40_000)
    try:
        page.wait_for_load_state("networkidle", timeout=8_000)
    except Exception:  # noqa: BLE001 - 계속 무언가를 받는 페이지도 있다
        pass
    page.wait_for_timeout(1500)
    if resp is not None and resp.status >= 400:
        raise CaptureError(f"HTTP {resp.status}")
    if _LOGIN_URL.search(urlparse(page.url).path + "?" + urlparse(page.url).query) and not _LOGIN_URL.search(url):
        raise CaptureError(f"로그인 화면으로 넘어갔습니다: {page.url[:120]}")
    if not is_official(page.url) and urlparse(page.url).scheme in ("http", "https"):
        raise CaptureError(f"공식 주소가 아닌 곳으로 넘어갔습니다: {page.url[:120]}")
    try:
        body_text = page.inner_text("body", timeout=5_000)[:5000]
    except Exception:  # noqa: BLE001
        body_text = ""
    title = page.title() or ""
    if _ERROR_PAGE.search(title) or (len(body_text) < 800 and _ERROR_PAGE.search(body_text)):
        raise CaptureError(f"오류·점검 화면입니다: {title[:60]}")
    try:
        hidden = page.evaluate(_HIDE_OVERLAYS)
        if hidden:
            log.info("캡처: 팝업 %d개를 숨겼습니다", hidden)
    except Exception:  # noqa: BLE001
        pass

    focus = str(spec.get("focus") or "").strip()
    box = None
    if focus:
        box = _visible_box(page, focus)
        if box:
            # 초점 글자를 화면 위쪽으로 스크롤한 뒤 위치를 다시 잰다
            page.evaluate("y => window.scrollBy(0, y)", max(0, box["y"] - VIEWPORT["height"] * 0.3))
            page.wait_for_timeout(500)
            box = _visible_box(page, focus)
    vw, vh = page.viewport_size["width"], page.viewport_size["height"]
    clip = _clip_around(box, vw, vh)
    boxes = []
    for text in (spec.get("highlight") or [])[:3]:
        b = _visible_box(page, str(text), exact=True) or _visible_box(page, str(text))
        if b and b["x"] >= clip["x"] - 4 and b["y"] >= clip["y"] - 4 \
                and b["x"] + b["width"] <= clip["x"] + clip["width"] + 4 \
                and b["y"] + b["height"] <= clip["y"] + clip["height"] + 4:
            boxes.append(b)
        else:
            log.info("캡처: 표시할 글자 '%s'를 잘라낸 화면 안에서 찾지 못했습니다", text)
    out.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(out), clip=clip)
    img = Image.open(out).convert("RGB")
    if looks_blank(img):
        raise CaptureError("거의 빈 화면입니다")
    scale = round(img.width / clip["width"]) or 1
    img = trim_margins(draw_boxes(img, boxes, clip, scale), MIN_W * scale, int(MIN_H * 0.6) * scale)
    img.save(out, "PNG", optimize=True)
    return {"path": out, "focused": bool(box), "boxes": len(boxes), "final_url": page.url, "title": title[:100]}


def capture_specs(post: dict, limit: int) -> list[dict]:
    return [c for c in (post.get("captures") or []) if isinstance(c, dict) and c.get("name") and c.get("url")][:limit]


def capture_all(cfg, post: dict, out_dir: Path, today: str, open_browser=None) -> tuple[set[str], list[str]]:
    """post["captures"]를 모두 찍는다. (찍은 이름들, 알림용 메모). 실패한 캡처는 빼고 계속한다.
    open_browser: 테스트용 — (playwright) → browser"""
    specs = capture_specs(post, cfg.capture_count)
    ok: set[str] = set()
    notes: list[str] = []
    todo = [s for s in specs if not (out_dir / f"{s['name']}.png").exists()]
    ok |= {s["name"] for s in specs if (out_dir / f"{s['name']}.png").exists()}   # 이어서 실행: 찍어 둔 것은 그대로
    if not todo:
        return ok, notes
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = open_browser(p) if open_browser else _launch(p, cfg)
        try:
            ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=SCALE, locale="ko-KR",
                                      timezone_id="Asia/Seoul")
            page = ctx.new_page()
            page.on("dialog", lambda d: d.dismiss())
            for spec in todo:
                name, url = spec["name"], spec["url"]
                if not is_official(url):
                    notes.append(f"{name}: 공식 사이트 주소가 아니라 캡처하지 않음({url[:80]})")
                    continue
                try:
                    info = capture_one(page, spec, out_dir / f"{name}.png")
                except Exception as e:  # noqa: BLE001 - 캡처 하나 실패해도 글은 계속
                    log.warning("캡처 실패 %s(%s): %s", name, url, e)
                    notes.append(f"{name}: {(str(e).strip().splitlines() or [''])[0][:120]}")
                    (out_dir / f"{name}.png").unlink(missing_ok=True)
                    continue
                spec["captured"] = {"date": today, "final_url": info["final_url"], "focused": info["focused"],
                                    "boxes": info["boxes"], "page_title": info["title"]}
                ok.add(name)
                log.info("캡처: %s (초점 %s, 표시 %d개)", name, "찾음" if info["focused"] else "못 찾음", info["boxes"])
        finally:
            browser.close()
    return ok, notes


def _launch(p, cfg):
    """로그인 정보가 없는 깨끗한 브라우저(블로그 계정 크롬 프로필과 섞지 않는다). 설치된 크롬이 있으면 그것을 쓴다."""
    try:
        return p.chromium.launch(headless=True, channel=cfg.browser_channel or None)
    except Exception:  # noqa: BLE001 - 크롬이 없으면 Playwright 크로미움
        return p.chromium.launch(headless=True)


def caption_text(spec: dict) -> str:
    """'▲ 큐넷 원서접수 화면 (2026.10.28 캡처)'"""
    base = str(spec.get("caption") or spec.get("desc_ko") or "").strip().rstrip(".")
    date = ((spec.get("captured") or {}).get("date") or "").replace("-", ".")
    return f"{base} ({date} 캡처)" if date else base
