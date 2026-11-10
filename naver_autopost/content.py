"""post.json 검증·정리와 본문 HTML 분할."""
from __future__ import annotations

import html
import json
import re

from .profiles import Profile

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
_AGE = re.compile(r"\d+\s*(?:~\s*\d+\s*)?(?:살|세|개월)")
MIN_PHOTOS_IN_POST = 2      # 직접 찍은 사진으로 쓰는 글(장소 글)의 본문 사진 최소 장수


def photo_names(post: dict) -> set[str]:
    """직접 찍은 사진(장소 글)의 이미지 이름들."""
    return {str(p.get("name")) for p in post.get("photos") or [] if p.get("name")}


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


_DASH_SEPARATOR = re.compile(r"\s+[—–]\s+")


def _heading_separators(fragment: str) -> str:
    """제목류 구분자는 '|'(원본 스킬 규칙). 본문 문장 속 대시는 그대로 둔다."""
    def fix(m: re.Match) -> str:
        tag, inner = m.group(1), m.group(2)
        return f"<{tag}>" + _DASH_SEPARATOR.sub(" | ", inner) + f"</{tag}>"

    return re.sub(r"<(h[1-6])>(.*?)</\1>", fix, fragment, flags=re.S)


def normalize(post: dict) -> dict:
    post["body_html"] = _heading_separators(sanitize_html(post.get("body_html", "")))
    post["title"] = _DASH_SEPARATOR.sub(" | ", str(post.get("title", "")))
    tags = []
    for tag in post.get("tags", []):
        tag = str(tag).strip().lstrip("#").replace(" ", "")
        if tag and tag not in tags:
            tags.append(tag)
    post["tags"] = tags[:30]
    post["title"] = post["title"].strip()
    return post


_NEGATION = re.compile(r"아니|아닙|않|없|말고|금물")


def _affirmative_use(text: str, phrase: str) -> bool:
    """금지 표현이 부정문 속에 쓰인 경우("통과해야 하는 기준이 아니라")는 허용한다.
    URL·판매 문구처럼 부정할 일이 없는 표현은 항상 금지."""
    for m in re.finditer(re.escape(phrase), text):
        if "." in phrase:          # 도메인
            return True
        window = text[m.end():m.end() + 25]
        if not _NEGATION.search(window):
            return True
    return False


def remove_markers(body_html: str, names: set[str]) -> str:
    """빠진 이미지(생성 실패·검수 탈락)의 자리 표시를 본문에서 지운다."""
    return IMAGE_MARKER.sub(lambda m: "" if m.group(1) in names else m.group(0), body_html)


_H2 = re.compile(r"<h2\b", re.I)


def fix_card_marker(body_html: str) -> tuple[str, bool]:
    """요약 카드 자리([[IMAGE:card]])가 없으면 1번 챕터 끝(2번 챕터 제목 바로 앞)에 넣고, 여러 개면 첫 번째만 남긴다.
    (카드는 post["card"]로 프로그램이 그리므로 자리만 맞으면 된다) (고친 본문, 바뀌었는지)"""
    count = [0]

    def keep_first(m: re.Match) -> str:
        if m.group(1) != "card":
            return m.group(0)
        count[0] += 1
        return m.group(0) if count[0] == 1 else ""
    body = IMAGE_MARKER.sub(keep_first, body_html)
    if count[0] >= 1:
        return body, count[0] > 1
    marker = "<p>[[IMAGE:card]]</p>"
    heads = list(_H2.finditer(body))
    if len(heads) >= 2:
        at = heads[1].start()
    else:
        tail = re.search(r'<div\b[^>]*data-block=["\'](?:oneline|related)', body, re.I)
        at = tail.start() if tail else len(body)
    return body[:at] + marker + body[at:], True


def validate(post: dict, profile: Profile | None = None, after_factcheck: bool = False) -> list[str]:
    """발행을 막아야 하는 문제 목록. 비어 있으면 통과.
    after_factcheck: 팩트체크가 틀린 문장을 지운 뒤라 분량 기준은 기본값(MIN_BODY_CHARS)만 본다
    (분량 때문에 검수까지 끝난 글을 버리지 않게)."""
    errors: list[str] = []
    for key in ("title", "body_html", "tags", "sources", "claims", "thumbnail", "card"):
        if not post.get(key):
            errors.append(f"필수 항목 없음: {key}")
    if errors:
        return errors

    title = post["title"]
    max_title = profile.max_title if profile else 100
    if len(title) > max_title:
        errors.append(f"제목이 너무 깁니다({len(title)}자 > {max_title}자). 검색어로 시작하는 짧은 질문으로 줄이세요")

    if profile and profile.title_pattern and not re.search(profile.title_pattern, title):
        errors.append(f"제목 형식이 다릅니다: '{title}' (이 블로그는 '{profile.title_pattern}' 형식으로 시작해야 합니다)")

    body = post["body_html"]
    markers = [m.group(1) for m in IMAGE_MARKER.finditer(body)]
    if markers.count("card") != 1:
        errors.append(f"[[IMAGE:card]] 표시는 정확히 1번이어야 합니다(현재 {markers.count('card')}번)")
    illust_names = {i.get("name") for i in post.get("illustrations") or []} | photo_names(post)
    unknown = sorted(set(markers) - {"card", "infographic"} - illust_names)  # 인포그래픽은 발행 직전에 넣는다
    if unknown:
        errors.append(f"알 수 없는 이미지 표시: {unknown}")
    dupes = sorted({m for m in markers if markers.count(m) > 1})
    if dupes:
        errors.append(f"이미지 표시가 중복됩니다: {dupes}")

    text = html_to_text(IMAGE_MARKER.sub("", body))
    everything = "\n".join([title, text, str(post["thumbnail"]), str(post["card"])])
    for phrase in FORBIDDEN_PHRASES:
        if phrase in everything:
            errors.append(f"자리표시자/초안 문구가 남아 있습니다: '{phrase}'")
    for phrase in profile.extra_forbidden if profile else ():
        if _affirmative_use(everything, phrase):
            errors.append(f"금지 표현이 있습니다: '{phrase}'")
    min_body = profile.min_body_chars if profile and not after_factcheck else MIN_BODY_CHARS
    if len(text) < min_body:
        errors.append(f"본문이 너무 짧습니다({len(text)}자 < {min_body}자)")

    sources = post["sources"]
    min_sources = profile.min_sources if profile else MIN_SOURCES
    if len(sources) < min_sources:
        errors.append(f"출처가 부족합니다({len(sources)}개 < {min_sources}개)")
    min_primary = profile.min_primary if profile else MIN_PRIMARY_SOURCES
    if sum(1 for s in sources if s.get("primary")) < min_primary:
        errors.append(f"1차 출처가 {min_primary}개 미만입니다")
    min_claims = profile.min_claims if profile else MIN_CLAIMS
    if len(post["claims"]) < min_claims:
        errors.append(f"검증 대상 사실이 {min_claims}개 미만입니다")
    if profile and profile.photos:
        # 장소 글 제목·썸네일에 우리 아이 나이(4살·2살)를 넣지 않는다: 검색에 도움이 안 되고 글을 좁게 보이게 한다
        shown = " ".join([title, json.dumps(post["thumbnail"], ensure_ascii=False)])
        ages = sorted(set(_AGE.findall(shown)))
        if ages:
            errors.append(f"제목·썸네일에 아이 나이가 있습니다({', '.join(ages)}). 나이는 본문에만 쓰고 제목·썸네일에서는 빼세요")
        used = [m for m in markers if m in photo_names(post)]
        if len(used) < MIN_PHOTOS_IN_POST:
            errors.append(f"본문에 넣은 사진이 {len(used)}장입니다(최소 {MIN_PHOTOS_IN_POST}장, photos.json의 이름으로 "
                          "<p>[[IMAGE:photo_01]]</p>처럼 넣기)")

    thumb = post["thumbnail"]
    if profile and profile.thumbnail_style in ("childhood", "bold", "photo"):
        lines = thumb.get("main_lines") or []
        if not 1 <= len(lines) <= 3:
            errors.append(f"썸네일 메인은 1~3줄이어야 합니다(현재 {len(lines)}줄)")
        elif any(len(line) > 10 for line in lines):
            errors.append(f"썸네일 메인 한 줄이 너무 깁니다: {lines}")
    elif not thumb.get("main"):
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


_RELATED_DIV = re.compile(r'<div\b[^>]*data-block=["\']related["\']', re.I)
_SOURCES_P = re.compile(r'<p>\s*(?:<strong>\s*)?(?:📚\s*)?(?:출처|참고 자료|자료 출처)', re.I)


def ensure_related(body_html: str, entries: list[dict], lane: str = "", title: str = "",
                   count: int = 3) -> tuple[str, bool]:
    """글 끝 '함께 보면 좋은 글'이 없으면 이 블로그의 발행 이력에서 골라 넣는다(교육·유아 글과 같은 서식).
    같은 레인 글 → 최근 글 순. 주소가 있는 이 블로그 글만 쓴다. (본문, 넣었는지)"""
    if _RELATED_DIV.search(body_html):
        return body_html, False
    seen, picks = set(), []
    pool = [e for e in entries if "blog.naver.com" in str(e.get("url", "")) and e.get("title")
            and e.get("title") != title]
    pool.sort(key=lambda e: str(e.get("date") or ""), reverse=True)
    lane_letter = str(lane or "").strip().upper()[:1]
    same = [e for e in pool if lane_letter and str(e.get("lane", "")).strip().upper()[:1] == lane_letter]
    for e in same + pool:
        if e["url"] in seen:
            continue
        seen.add(e["url"])
        picks.append((e, e in same))
        if len(picks) == count:
            break
    if not picks:
        return body_html, False
    items = "".join(
        f"<p>「{html.escape(e['title'])}」 — {'같은 주제를 다른 숫자로 본 글이에요' if same_lane else '함께 읽으면 좋은 최근 글이에요'}</p>"
        f"<p>{html.escape(e['url'])}</p>"
        for e, same_lane in picks)
    block = f'<div data-block="related">{items}</div>'
    m = _SOURCES_P.search(body_html)
    if m:
        return body_html[:m.start()] + block + body_html[m.start():], True
    return body_html + block, True
