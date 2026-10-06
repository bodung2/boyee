"""검색에 보이는 글 모양 다듬기(새 글과 이미 발행한 글에 똑같이 쓴다).

- 글이 그림·그림 설명으로 시작하지 않게, 맨 앞의 그림 블록을 첫 문단 뒤로 옮긴다.
  (메타 설명이 없으면 구글은 본문 첫머리로 검색 결과 요약을 만든다)
- 글 끝에 같은 블로그의 관련 글 링크 묶음을 넣는다(구글이 글에서 글로 따라가며 찾을 수 있게).
"""
from __future__ import annotations

import html
import re

RELATED_CLASS = "kb-related"
RELATED_TITLE = "Related guides on Korea, Explained"

# 맨 앞에 올 수 있는 그림 블록: 우리 자동 글의 <figure>, 블로거 편집기의 캡션 표·가운데 정렬 그림
_IMAGE_BLOCKS = (
    re.compile(r"<figure\b.*?</figure\s*>", re.I | re.S),
    re.compile(r"<table\b[^>]*tr-caption-container.*?</table\s*>", re.I | re.S),
    re.compile(r"<div\b[^>]*class=[\"'][^\"']*separator[^\"']*[\"'][^>]*>\s*(?:<a\b[^>]*>)?\s*<img\b[^>]*>\s*(?:</a>)?\s*</div\s*>",
               re.I | re.S),
    re.compile(r"<p\b[^>]*>\s*(?:<a\b[^>]*>)?\s*<img\b[^>]*>\s*(?:</a>)?\s*</p\s*>", re.I | re.S),
    re.compile(r"(?:<a\b[^>]*>)?\s*<img\b[^>]*>\s*(?:</a>)?", re.I | re.S),
)
_SPACE = re.compile(r"^(?:\s|&nbsp;|<br\s*/?>|<p>\s*</p>|<div>\s*</div>)+", re.I)
_FIRST_PARA = re.compile(r"<p\b[^>]*>(?:(?!</p>).)*?\w(?:(?!</p>).)*?</p\s*>", re.I | re.S)


_COVER = re.compile(r'^\s*<div\b[^>]*class=["\']kb-cover["\'][^>]*>.*?</div\s*>', re.I | re.S)


def move_leading_images(body: str) -> tuple[str, int]:
    """본문 맨 앞의 그림 블록들을 첫 글 문단 바로 뒤로 옮긴다. (새 본문, 옮긴 개수)
    대표 이미지용 숨은 인포그래픽 사본(kb-cover)은 맨 앞에 그대로 둔다."""
    cover = _COVER.match(body)
    if cover:
        new, n = move_leading_images(body[cover.end():])
        return body[:cover.end()] + new, n
    rest, moved = body, []
    while True:
        lead = _SPACE.match(rest)
        start = lead.end() if lead else 0
        for pattern in _IMAGE_BLOCKS:
            m = pattern.match(rest, start)
            if m:
                moved.append(m.group(0))
                rest = rest[m.end():]
                break
        else:
            break
    if not moved:
        return body, 0
    para = _FIRST_PARA.search(rest)
    if not para:
        return body, 0
    return rest[:para.end()] + "".join(moved) + rest[para.end():], len(moved)


def _norm(url: str) -> str:
    return (url or "").split("?")[0].split("#")[0].rstrip("/").replace("http://", "https://")


def pick_related(url: str, title: str, labels: list[str], candidates: list[dict], n: int = 3) -> list[dict]:
    """같은 라벨이 많은 글부터, 같으면 최근 글부터 n개(자기 자신 제외)."""
    mine = {l.lower() for l in labels or []}
    seen, pool = {_norm(url)}, []
    for c in candidates:
        u = _norm(c.get("url", ""))
        if not u or u in seen or not c.get("title") or c.get("title") == title:
            continue
        seen.add(u)
        score = len(mine & {l.lower() for l in c.get("labels") or []})
        pool.append((score, c.get("published") or c.get("date") or "", c))
    pool.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [c for _, _, c in pool[:n]]


def related_html(posts: list[dict]) -> str:
    items = "".join(f'<li><a href="{html.escape(p["url"])}">{html.escape(p["title"])}</a></li>' for p in posts)
    return (f'<div class="{RELATED_CLASS}" style="margin-top:2em;padding-top:1em;border-top:1px solid #ddd">'
            f"<h3>{RELATED_TITLE}</h3><ul>{items}</ul></div>")


_RELATED_BLOCK = re.compile(rf'<div\b[^>]*class=["\']{RELATED_CLASS}["\'][^>]*>.*?</ul>\s*</div\s*>', re.I | re.S)


def set_related(body: str, posts: list[dict]) -> str:
    """관련 글 묶음을 글 끝에 넣는다(이미 있으면 바꾼다). 후보가 없으면 그대로."""
    body = _RELATED_BLOCK.sub("", body).rstrip()
    return body + related_html(posts) if posts else body


def improve(body: str, url: str, title: str, labels: list[str], candidates: list[dict]) -> tuple[str, dict]:
    """A(그림을 첫 문단 뒤로) + B(관련 글 링크). (새 본문, 바뀐 내용 요약)"""
    new, moved = move_leading_images(body)
    related = pick_related(url, title, labels, candidates)
    new = set_related(new, related)
    return new, {"moved_images": moved, "related": [r["title"] for r in related]}
