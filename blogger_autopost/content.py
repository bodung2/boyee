"""블로거용 post.json 정리·검증. 사람 검토 없이 발행되므로 형식 문제는 코드에서 한 번 더 막는다."""
from __future__ import annotations

import re

from naver_autopost.content import html_to_text

# 자동 발행 글에 남아 있으면 안 되는 자리표시자·초안용 문구(대소문자 무시)
FORBIDDEN = [
    "lorem ipsum", "TODO", "TBD", "[insert", "[image", "[[", "{{", "확인 필요",
    "as an ai", "i cannot browse", "placeholder", "✍️",
]
_BAD_PAIRED = re.compile(r"<(script|style|iframe|object|form)\b.*?</\1\s*>", re.I | re.S)
_BAD_SINGLE = re.compile(r"</?(script|style|iframe|object|embed|form)\b[^>]*>", re.I)
_WRAPPERS = re.compile(r"</?(html|head|body|meta|link|!doctype)\b[^>]*>", re.I)
_H1 = re.compile(r"<(/?)h1\b", re.I)
_MD_HEADING = re.compile(r"^\s*#{1,6}\s+\S", re.M)
_MD_BOLD = re.compile(r"\*\*[^*\n]+\*\*")
_CODE_FENCE = re.compile(r"^\s*```\w*\s*$", re.M)


def sanitize_html(body: str) -> str:
    body = _CODE_FENCE.sub("", body)
    body = _BAD_SINGLE.sub("", _BAD_PAIRED.sub("", body))
    body = _WRAPPERS.sub("", body)
    body = re.sub(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*')", "", body, flags=re.I)   # onclick 등
    body = _H1.sub(r"<\1h2", body)          # 제목(h1)은 블로거가 따로 붙이므로 본문은 h2부터
    return body.strip()


def normalize(post: dict) -> dict:
    post = dict(post)
    post["title"] = re.sub(r"\s+", " ", str(post.get("title", ""))).strip()
    post["body_html"] = sanitize_html(str(post.get("body_html") or post.get("content") or ""))
    labels = post.get("labels") or post.get("tags") or []
    if isinstance(labels, str):
        labels = labels.split(",")
    seen: list[str] = []
    for label in labels:
        label = str(label).strip().lstrip("#").strip()
        if label and label.lower() not in {s.lower() for s in seen}:
            seen.append(label[:60])
    post["labels"] = seen[:10]
    post["sources"] = [s for s in (post.get("sources") or []) if isinstance(s, dict) and s.get("url")]
    return post


def validate(post: dict, min_sources: int = 3, min_body_chars: int = 2000) -> list[str]:
    errors: list[str] = []
    title, body = post.get("title", ""), post.get("body_html", "")
    text = html_to_text(body)
    if not title:
        errors.append("제목이 없습니다")
    elif len(title) > 150:
        errors.append(f"제목이 너무 깁니다({len(title)}자)")
    if len(text) < min_body_chars:
        errors.append(f"본문이 너무 짧습니다({len(text)}자 < {min_body_chars}자)")
    if not re.search(r"<(p|h2|h3|ul|ol|table)\b", body, re.I):
        errors.append("본문이 HTML이 아닙니다(<p>·<h2> 등이 없음)")
    if _MD_HEADING.search(text) or len(_MD_BOLD.findall(body)) >= 3:
        errors.append("본문에 마크다운(#, **)이 섞여 있습니다")
    lowered = (title + "\n" + text).lower()
    for phrase in FORBIDDEN:
        if phrase.lower() in lowered:
            errors.append(f"자리표시자·초안 문구가 남아 있습니다: {phrase}")
    if len(post.get("sources", [])) < min_sources:
        errors.append(f"확인한 출처가 부족합니다({len(post.get('sources', []))}개 < {min_sources}개)")
    if not post.get("labels"):
        errors.append("라벨(labels)이 없습니다")
    return errors
