"""위키미디어 커먼즈에서 상업 이용이 허용된 실제 사진을 찾아 본문에 넣는다(API 키 불필요).

글쓴이(Codex)가 post.json의 "photos"에 어떤 사진이 필요한지 적으면, 여기서 커먼즈를 검색해
라이선스로 먼저 거르고, 후보를 Codex가 눈으로 보고 '그 대상이 맞는지·한국이 맞는지' 고른 것만 넣는다.
블로거 API는 이미지 업로드가 없으므로 커먼즈 이미지 주소를 그대로 쓰고, 사진 아래에 작가·라이선스를 표기한다.
"""
from __future__ import annotations

import html
import json
import logging
import re
import urllib.parse
import urllib.request
from pathlib import Path

from naver_autopost.content import html_to_text

from . import writer
from .config import BloggerConfig

log = logging.getLogger(__name__)
API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "boyee-blogger-autopost/1.0 (https://github.com/bodung2/boyee)"
THUMB_WIDTH = 1200
REVIEW_WIDTH = 640
MIN_WIDTH = 800

# 상업 이용·출처 표기만으로 쓸 수 있는 라이선스(GFDL 단독, NC, ND, 비자유 이미지는 쓰지 않는다)
_ALLOWED = re.compile(r"^(cc0|cc[- ]zero|public domain|pd\b|pdm|cc[- ]by(-sa)?[- ]\d|cc[- ]by(-sa)?$|kogl type ?1)", re.I)
_BLOCKED = re.compile(r"\bnc\b|\bnd\b|non-?commercial|no ?deriv|fair use|non-?free", re.I)
_RESTRICTED = re.compile(r"personality|trademark|insignia", re.I)


def _get(params: dict, fetch=None) -> dict:
    url = API + "?" + urllib.parse.urlencode({**params, "format": "json", "formatversion": "2"})
    if fetch:
        return fetch(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _meta(info: dict, key: str) -> str:
    return str(((info.get("extmetadata") or {}).get(key) or {}).get("value") or "")


def license_ok(info: dict) -> bool:
    short = html_to_text(_meta(info, "LicenseShortName")).strip()
    if _meta(info, "NonFree").lower() == "true" or _BLOCKED.search(short):
        return False
    if _RESTRICTED.search(_meta(info, "Restrictions")):
        return False
    return bool(_ALLOWED.search(short))


def search(query: str, limit: int = 4, fetch=None) -> list[dict]:
    """커먼즈 파일 검색 → 라이선스·크기·형식을 통과한 후보(최대 limit개)."""
    data = _get({
        "action": "query", "generator": "search", "gsrsearch": f"filetype:bitmap {query}",
        "gsrnamespace": 6, "gsrlimit": 20, "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata", "iiurlwidth": THUMB_WIDTH,
    }, fetch)
    pages = sorted((data.get("query") or {}).get("pages") or [], key=lambda p: p.get("index", 0))
    found = []
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        if info.get("mime") not in ("image/jpeg", "image/png", "image/webp"):
            continue
        if int(info.get("width") or 0) < MIN_WIDTH or not license_ok(info):
            continue
        found.append({
            "title": page.get("title", ""),
            "description": html_to_text(_meta(info, "ImageDescription")),
            "thumb_url": info.get("thumburl") or info.get("url"),
            "thumb_width": info.get("thumbwidth") or info.get("width"),
            "thumb_height": info.get("thumbheight") or info.get("height"),
            "page_url": info.get("descriptionurl") or "",
            "artist": html_to_text(_meta(info, "Artist")) or "Unknown author",
            "license": html_to_text(_meta(info, "LicenseShortName")),
            "license_url": _meta(info, "LicenseUrl"),
        })
        if len(found) >= limit:
            break
    return found


def _download(url: str, out: Path, fetch_bytes=None) -> Path:
    small = re.sub(r"/(\d+)px-", f"/{REVIEW_WIDTH}px-", url) if "/thumb/" in url else url
    if fetch_bytes:
        data = fetch_bytes(small)
    else:
        req = urllib.request.Request(small, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return out


def figure_html(photo: dict, want: dict) -> str:
    e = html.escape
    alt = e(want.get("alt") or want.get("subject") or "")
    caption = e(want.get("caption") or "")
    credit = (f'Photo: <a href="{e(photo["page_url"])}">{e(photo["artist"][:80])}</a>, '
              + (f'<a href="{e(photo["license_url"])}">{e(photo["license"])}</a>' if photo.get("license_url")
                 else e(photo["license"]))
              + ", via Wikimedia Commons")
    return (f'<figure style="margin:1.5em 0;text-align:center">'
            f'<img src="{e(photo["thumb_url"])}" alt="{alt}" width="{photo["thumb_width"]}" '
            f'height="{photo["thumb_height"]}" style="max-width:100%;height:auto" loading="lazy">'
            f'<figcaption style="font-size:0.85em;color:#666;margin-top:0.4em">'
            f'{caption + "<br>" if caption else ""}{credit}</figcaption></figure>')


def insert(body: str, section: int, fig: str) -> str:
    """section 0 = 맨 위, N = N번째 <h2> 바로 다음(없으면 맨 끝 앞의 마지막 h2 다음)."""
    if section <= 0:
        return fig + body
    heads = list(re.finditer(r"</h2\s*>", body, re.I))
    if not heads:
        return fig + body
    m = heads[min(section, len(heads)) - 1]
    return body[:m.end()] + fig + body[m.end():]


def _queries(want: dict) -> list[str]:
    alts = want.get("alternatives") or []
    if isinstance(alts, str):
        alts = [alts]
    seen: list[str] = []
    for q in [want.get("search"), *alts[:2], want.get("subject")]:
        q = str(q or "").strip()
        if q and q.lower() not in {s.lower() for s in seen}:
            seen.append(q)
    return seen


def _candidates(cfg: BloggerConfig, want: dict, fetch=None) -> list[dict]:
    """첫 검색어부터 차례로 찾아 후보를 모은다(라이선스·크기에서 다 떨어지면 다음 검색어)."""
    found: list[dict] = []
    for q in _queries(want):
        try:
            for c in search(q, cfg.photo_candidates, fetch):
                if c["title"] not in {f["title"] for f in found}:
                    found.append(c)
        except Exception as e:  # noqa: BLE001
            log.warning("커먼즈 검색 실패(%s): %s", q, e)
        if len(found) >= cfg.photo_candidates:
            break
    return found[:cfg.photo_candidates]


def add_photos(cfg: BloggerConfig, post: dict, out_dir: Path, fetch=None, fetch_bytes=None) -> tuple[int, str]:
    """post["photos"]대로 사진을 찾아·검수해 body_html에 넣는다. (넣은 장수, 알림용 메모). 실패해도 예외 없이."""
    wants = [w for w in (post.get("photos") or []) if isinstance(w, dict) and (w.get("search") or w.get("subject"))]
    wants = wants[:cfg.photos]
    if not wants:
        return 0, "실제 사진 0장(글쓴이가 사진 자리를 정하지 않음)"
    # 못 찾은 자리는 생성 그림 단계가 실사풍 이미지로 대신 채운다.
    post["photo_misses"] = []
    slots, pool = [], {}
    for i, want in enumerate(wants, 1):
        slot = {"id": f"s{i}", "subject": want.get("subject") or want.get("search"), "candidates": []}
        for j, c in enumerate(_candidates(cfg, want, fetch), 1):
            cid = f"s{i}c{j}"
            try:
                c["path"] = _download(c["thumb_url"], out_dir / "photos" / f"{cid}.jpg", fetch_bytes)
            except Exception as e:  # noqa: BLE001
                log.warning("사진 내려받기 실패(%s): %s", c["title"], e)
                continue
            c["id"] = cid
            pool[cid] = c
            slot["candidates"].append(c)
        if slot["candidates"]:
            slots.append((want, slot))
        else:
            log.warning("사진 '%s': 쓸 수 있는 라이선스의 후보가 없습니다(검색어 %s)", slot["subject"], _queries(want))
            post["photo_misses"].append(want)
    if not slots:
        return 0, "실제 사진 0장(커먼즈에 쓸 수 있는 후보 없음)"
    choices = writer.review_photos(cfg, post["title"], [s for _, s in slots])

    body, added, chosen, used = post["body_html"], 0, [], set()
    # 뒤쪽 섹션부터 넣어야 앞쪽 h2 위치가 밀리지 않는다.
    for want, slot in sorted(slots, key=lambda ws: -int(ws[0].get("section") or 0)):
        pick = pool.get(choices.get(slot["id"], ""))
        if not pick or pick["title"] in used:
            log.warning("사진 '%s': 후보 %d장이 모두 검수에서 떨어졌습니다", slot["subject"], len(slot["candidates"]))
            post["photo_misses"].append(want)
            continue
        used.add(pick["title"])
        body = insert(body, int(want.get("section") or 0), figure_html(pick, want))
        chosen.append({k: v for k, v in pick.items() if k != "path"} | {"section": want.get("section", 0)})
        added += 1
    post["body_html"] = body
    post["photo_credits"] = chosen
    return added, f"실제 사진 {added}장" + ("" if added == len(wants) else "(후보가 검수에서 떨어짐)")
