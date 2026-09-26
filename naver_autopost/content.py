"""post.json 검증·정리와 본문 HTML 분할."""
from __future__ import annotations

import html
import re

IMAGE_MARKER = re.compile(r"(?:<p>\s*)?\[\[IMAGE:(\w+)\]\](?:\s*</p>)?")

# 자동 발행 글에 남아 있으면 안 되는 자리표시자·초안용 문구
FORBIDDEN_PHRASES = [
    "확인 필요", "TBD", "○○", "✍️", "나노바나나", "발행 전", "자동 생성 초안",
    "프롬프트 #", "[이미지", "링크 추가)", "여기에 본인",
]

MIN_BODY_CHARS = 1500
MIN_SOURCES = 10
MIN_PRIMARY_SOURCES = 2
MIN_CLAIMS = 5


def html_to_text(fragment: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    text = re.sub(r"</(p|h[1-6]|li|tr)>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def sanitize_html(fragment: str) -> str:
    """네이버 에디터에 붙여넣을 때 깨지는 요소를 정리한다."""
    fragment = re.sub(r"<(script|style)\b.*?</\1>", "", fragment, flags=re.I | re.S)
    fragment = re.sub(r"</?(html|head|body|meta|link)\b[^>]*>", "", fragment, flags=re.I)
    fragment = re.sub(r'\s(style|class|id)="[^"]*"', "", fragment, flags=re.I)
    # 네이버는 raw URL을 자동 링크하므로 <a>는 주소 텍스트로 바꾼다.
    fragment = re.sub(
        r'<a\b[^>]*href="([^"]+)"[^>]*>.*?</a>', lambda m: html.escape(m.group(1)), fragment,
        flags=re.I | re.S,
    )
    return fragment.strip()


def split_segments(body_html: str) -> list[tuple[str, str]]:
    """본문을 [("html", 조각), ("image", 이름), ...] 순서로 나눈다."""
    segments: list[tuple[str, str]] = []
    pos = 0
    for m in IMAGE_MARKER.finditer(body_html):
        chunk = body_html[pos:m.start()].strip()
        if chunk:
            segments.append(("html", chunk))
        segments.append(("image", m.group(1)))
        pos = m.end()
    tail = body_html[pos:].strip()
    if tail:
        segments.append(("html", tail))
    return segments


def normalize(post: dict) -> dict:
    post["body_html"] = sanitize_html(post.get("body_html", ""))
    tags = []
    for tag in post.get("tags", []):
        tag = str(tag).strip().lstrip("#").replace(" ", "")
        if tag and tag not in tags:
            tags.append(tag)
    post["tags"] = tags[:30]
    post["title"] = str(post.get("title", "")).strip()
    return post


def validate(post: dict) -> list[str]:
    """발행을 막아야 하는 문제 목록. 비어 있으면 통과."""
    errors: list[str] = []
    for key in ("title", "body_html", "tags", "sources", "claims", "thumbnail", "card"):
        if not post.get(key):
            errors.append(f"필수 항목 없음: {key}")
    if errors:
        return errors

    title = post["title"]
    if len(title) > 100:
        errors.append(f"제목이 너무 깁니다({len(title)}자)")

    body = post["body_html"]
    markers = [m.group(1) for m in IMAGE_MARKER.finditer(body)]
    if markers.count("card") != 1:
        errors.append(f"[[IMAGE:card]] 표시는 정확히 1번이어야 합니다(현재 {markers.count('card')}번)")
    unknown = sorted(set(markers) - {"card"})
    if unknown:
        errors.append(f"알 수 없는 이미지 표시: {unknown}")

    text = html_to_text(IMAGE_MARKER.sub("", body))
    everything = "\n".join([title, text, str(post["thumbnail"]), str(post["card"])])
    for phrase in FORBIDDEN_PHRASES:
        if phrase in everything:
            errors.append(f"자리표시자/초안 문구가 남아 있습니다: '{phrase}'")
    if len(text) < MIN_BODY_CHARS:
        errors.append(f"본문이 너무 짧습니다({len(text)}자 < {MIN_BODY_CHARS}자)")

    sources = post["sources"]
    if len(sources) < MIN_SOURCES:
        errors.append(f"출처가 부족합니다({len(sources)}개 < {MIN_SOURCES}개)")
    if sum(1 for s in sources if s.get("primary")) < MIN_PRIMARY_SOURCES:
        errors.append(f"1차 출처가 {MIN_PRIMARY_SOURCES}개 미만입니다")
    if len(post["claims"]) < MIN_CLAIMS:
        errors.append(f"검증 대상 사실이 {MIN_CLAIMS}개 미만입니다")

    thumb = post["thumbnail"]
    if not thumb.get("main"):
        errors.append("썸네일 메인 문구가 없습니다")
    elif len(thumb["main"]) > 16:
        errors.append(f"썸네일 메인 문구가 깁니다({len(thumb['main'])}자)")
    if len(thumb.get("sub", "")) > 26:
        errors.append(f"썸네일 보조 문구가 깁니다({len(thumb['sub'])}자)")
    bullets = post["card"].get("bullets") or []
    if not 3 <= len(bullets) <= 6:
        errors.append(f"카드 요점은 3~6개여야 합니다(현재 {len(bullets)}개)")
    if not post["tags"]:
        errors.append("태그가 없습니다")
    return errors
