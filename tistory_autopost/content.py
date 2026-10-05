"""post.json 정리·검증. 티스토리는 HTML 모드로 넣으므로 표·인라인 스타일(막대그래프)을 살린다."""
from __future__ import annotations

import re
from urllib.parse import urlparse

from naver_autopost.content import FORBIDDEN_PHRASES, html_to_text

# 공식(1차) 출처로 인정하는 도메인. 통계 원문·보도자료가 여기 있다.
PRIMARY_DOMAINS = (
    ".go.kr", "kosis.kr", "korea.kr", "bok.or.kr", "nps.or.kr", "oecd.org", "index.go.kr",
    "kdi.re.kr", "kihasa.re.kr", "krivet.re.kr", "kicce.re.kr",
)
# 계층·성별 갈등 소재라 평가·조롱으로 읽히는 말은 막는다(숫자와 해석만 쓴다).
JUDGMENT_WORDS = ("흙수저는", "루저", "패배자", "한남", "김치녀", "개념녀", "거지들", "노력을 안", "노력 부족")
EXTRA_FORBIDDEN = ("[[IMAGE", "<!--", "이 글은 AI")
MAX_TAGS = 10


def sanitize_html(fragment: str) -> str:
    """스크립트·외부 삽입·이벤트 속성만 지운다. 표와 style 속성(막대그래프)은 남긴다."""
    fragment = re.sub(r"<(script|style|iframe|object|embed|form)\b.*?</\1>", "", fragment, flags=re.I | re.S)
    fragment = re.sub(r"<(script|iframe|object|embed|input|button|form)\b[^>]*/?>", "", fragment, flags=re.I)
    fragment = re.sub(r"</?(html|head|body|meta|link|h1)\b[^>]*>", "", fragment, flags=re.I)
    fragment = re.sub(r"\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", fragment, flags=re.I)
    fragment = re.sub(r"(href|src)\s*=\s*([\"'])\s*javascript:[^\"']*\2", r'\1="#"', fragment, flags=re.I)
    return fragment.strip()


def normalize(post: dict) -> dict:
    post = dict(post)
    post["title"] = re.sub(r"\s+", " ", str(post.get("title", ""))).strip()
    post["body_html"] = sanitize_html(str(post.get("body_html", "")))
    tags = post.get("tags") or []
    if isinstance(tags, str):
        tags = re.split(r"[,#]", tags)
    seen, clean = set(), []
    for t in tags:
        t = re.sub(r"[#,]", "", str(t)).strip()
        if t and t not in seen:
            seen.add(t)
            clean.append(t)
    post["tags"] = clean[:MAX_TAGS]
    post["sources"] = [s for s in post.get("sources") or [] if isinstance(s, dict) and s.get("url")]
    post["data_points"] = [d for d in post.get("data_points") or [] if isinstance(d, dict)]
    post["lane"] = str(post.get("lane") or "queue").strip()
    post["topic_id"] = str(post.get("topic_id") or "").strip()
    return post


def is_primary(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    for d in PRIMARY_DOMAINS:
        if host.endswith(d) if d.startswith(".") else (host == d or host.endswith("." + d)):
            return True
    return False


def validate(post: dict, min_sources: int = 4, min_primary: int = 2, min_data_points: int = 6,
             min_body_chars: int = 1800) -> list[str]:
    errors = []
    title, body = post.get("title", ""), post.get("body_html", "")
    text = html_to_text(body)
    if not 10 <= len(title) <= 60:
        errors.append(f"제목 길이 {len(title)}자(10~60자)")
    if len(text) < min_body_chars:
        errors.append(f"본문이 짧습니다({len(text)}자 < {min_body_chars}자)")
    if not post.get("topic_id"):
        errors.append("topic_id가 없습니다")
    if "<table" not in body.lower():
        errors.append("본문에 표(<table>)가 없습니다(내 위치를 찾는 표가 핵심)")
    if len(re.findall(r"<h2\b", body, flags=re.I)) < 3:
        errors.append("소제목(<h2>)이 3개 미만입니다")
    sources = post.get("sources") or []
    if len(sources) < min_sources:
        errors.append(f"출처가 {len(sources)}개(최소 {min_sources}개)")
    primary = [s for s in sources if is_primary(s.get("url", ""))]
    if len(primary) < min_primary:
        errors.append(f"공식(1차) 출처가 {len(primary)}개(최소 {min_primary}개)")
    points = post.get("data_points") or []
    if len(points) < min_data_points:
        errors.append(f"검증용 수치(data_points)가 {len(points)}개(최소 {min_data_points}개)")
    for i, d in enumerate(points):
        missing = [k for k in ("value", "stat", "period", "source_url") if not str(d.get(k, "")).strip()]
        if missing:
            errors.append(f"data_points[{i}]에 {', '.join(missing)} 없음")
    if not post.get("tags"):
        errors.append("태그가 없습니다")
    visible = f"{title}\n{text}"
    for phrase in (*FORBIDDEN_PHRASES, *EXTRA_FORBIDDEN, *JUDGMENT_WORDS):
        if phrase in visible or phrase in body:
            errors.append(f"금지 문구: {phrase}")
    links = re.findall(r'<a\b[^>]*href="(https?://[^"]+)"', body, flags=re.I)
    if not any(is_primary(u) for u in links):
        errors.append("본문 출처 섹션에 공식 출처 링크가 없습니다")
    return errors

