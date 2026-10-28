"""글 한 편이 '어떻게 만들어졌는지' 꼬리표. 발행 이력에 같이 남겨 두면 나중에 조회수와 맞대어 원인을 찾을 수 있다.

꼬리표는 글에서 기계적으로 뽑을 수 있는 것만 쓴다(글쓴이가 지어낼 수 없게)."""
from __future__ import annotations

import re

from naver_autopost.content import html_to_text

# 위에서부터 처음 맞는 것 하나. 투자 블로그 스킬의 제목 유형 + 티스토리 오류 글.
TITLE_TYPES = [
    ("오류형", re.compile(r"오류|에러|error|exception|안 ?될|안 ?돼|실패|해결", re.I)),
    ("실수령형", re.compile(r"실수령|세후|손에 쥐")),
    ("위치형", re.compile(r"상위|몇 ?등|몇 ?%|평균일까|어디쯤|내 위치")),
    ("기준형", re.compile(r"몇 ?점|기준|언제|조건|얼마면")),
    ("진짜형", re.compile(r"진짜|정말|사실일까|맞을까")),
    ("비교형", re.compile(r"다들|vs|차이|비교|보다")),
    ("얼마형", re.compile(r"얼마|몇 ?년|몇 ?명|몇 ?개")),
]
_MARKER = re.compile(r"\[\[IMAGE:(\w+)\]\]")


def title_type(title: str) -> str:
    for name, pattern in TITLE_TYPES:
        if pattern.search(title or ""):
            return name
    return "기타"


def post_features(post: dict) -> dict:
    """post.json(발행 직전 최종본) → 꼬리표."""
    title = str(post.get("title") or "")
    body = str(post.get("body_html") or "")
    text = html_to_text(body)
    first = re.search(r"<p\b[^>]*>(.*?)</p>", body, re.S | re.I)
    images = set(_MARKER.findall(body)) | ({"img"} if "<img" in body.lower() else set())
    return {
        "title_type": title_type(title),
        "title_len": len(title),
        "title_question": title.rstrip().endswith("?"),
        "title_has_number": bool(re.search(r"\d", title)),
        "body_chars": len(text),
        "h2": len(re.findall(r"<h2\b", body, re.I)),
        "tables": len(re.findall(r"<table\b", body, re.I)),
        "images": len(images),
        "captures": sum(1 for n in images if n.startswith("cap")),     # 공식 화면 캡처(생활 절차 블로그)
        "photos": sum(1 for n in images if n.startswith("photo")),     # 실제 사진(생활 절차 블로그)
        "faq": bool(re.search(r"자주 묻는|FAQ", body)),
        "first_para_chars": len(html_to_text(first.group(1))) if first else 0,
        "tags": len(post.get("tags") or []),
        "lane": str(post.get("lane") or ""),
        "format": str(post.get("format") or ""),          # 글 모양(생활 절차: steps/table/cases)
        "image_style": str(post.get("image_style_id") or "base"),
    }


def history_fields(post: dict) -> dict:
    """발행 이력 한 줄에 덧붙일 실험실 값. 실패해도 발행 기록은 남아야 하므로 예외를 내지 않는다."""
    try:
        out = {"lab_topic": str(post.get("lab_topic") or "").strip(),
               "lab_mode": str(post.get("lab_mode") or "").strip(),
               "lab": post_features(post)}
        if post.get("lab_keyword"):
            out["lab_keyword"] = str(post["lab_keyword"]).strip()   # 검색 순위를 확인할 대표 검색어
        return out
    except Exception:  # noqa: BLE001
        return {}
