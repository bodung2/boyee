"""활동지 설계서(spec.json) 형식과 검사. 활동 종류는 「경량 활동 12종 상세 프롬프트 명세서」를 따른다.

{
  "set_id": "2026-11-24-winter", "theme": "겨울", "title": "겨울 준비물 활동지", "age": "3~5세",
  "domain": "소근육", "competency": "M5 그래포모터·그리기", "nuri": "신체운동·건강 – 신체 활동 즐기기",
  "characters": ["rabbit", "bear", "fox", "squirrel"],          # 머리에 세울 고정 캐릭터(보관함 key)
  "assets": [{"key": "mitten", "name": "장갑", "kind": "color", "prompt": "..."}],
  "pages": [{"type": "trace_outline", "title": "겨울 준비물 따라 그려요", "instruction": "옅은 선을 따라 그려 보세요.",
             "header": "characters", "items": [{"asset": "mitten", "word": "장갑"}]}],
  "parent_tip": "…"
}
"""
from __future__ import annotations

import re

# 종류: (이름, 항목 수 범위, 필요한 값)
PAGE_TYPES = {
    "word_cards": "그림 한글 카드",
    "cut_lines": "오리기 연습",
    "trace_outline": "흐린 밑그림 따라 그리기",
    "coloring": "색칠하기",
    "match_same": "같은 그림 선 잇기",
    "match_shadow": "그림자 찾기",
    "half_draw": "반쪽 그림 완성",
    "cut_paste": "오려 붙이기 미니판",
    "trace_letters": "낱말 따라 쓰기",
    "vocab_poster": "그림 낱말판",
    "emotion_match": "기분 찾기",
    "check_game": "찾으면 콕! 체크 놀이",
    "trace_lines": "선 따라 그리기",
    "count_write": "세어 보고 숫자 쓰기",
}
COUNTS = {
    "word_cards": (4, 8), "cut_lines": (3, 4), "trace_outline": (4, 4), "coloring": (2, 4), "match_same": (3, 4),
    "match_shadow": (3, 4), "half_draw": (4, 4), "cut_paste": (2, 3), "trace_letters": (3, 4), "vocab_poster": (6, 8),
    "emotion_match": (3, 4), "check_game": (4, 6), "trace_lines": (3, 4), "count_write": (6, 8),
}
NEEDS_WORD = {"word_cards", "trace_letters", "vocab_poster", "emotion_match", "check_game"}
LINE_ONLY = {"coloring"}
PATHS = ("straight", "wave", "zigzag", "curve", "loop", "steps")
HANGUL_WORD = re.compile(r"^[가-힣]{1,5}$")


def _keys(spec: dict) -> dict[str, dict]:
    return {a.get("key"): a for a in spec.get("assets") or [] if isinstance(a, dict)}


def used_assets(spec: dict) -> list[str]:
    """실제로 쓰는 그림 key(머리 캐릭터 포함, 순서 유지, 중복 없음)."""
    seen: list[str] = []

    def add(k):
        if k and k not in seen:
            seen.append(k)
    for k in spec.get("characters") or []:
        add(k)
    for p in spec.get("pages") or []:
        for k in p.get("characters") or []:
            add(k)
        add(p.get("container"))
        for it in p.get("items") or []:
            add(it.get("asset"))
    return seen


def problems(spec: dict, library_index: dict | None = None) -> list[str]:
    """설계서가 그릴 수 없는 모양이면 문제 목록(비면 통과)."""
    from .library import KEY_RE
    errs: list[str] = []
    for f in ("set_id", "theme", "title", "age", "pages"):
        if not spec.get(f):
            errs.append(f"필수 항목 없음: {f}")
    if errs:
        return errs
    if not re.match(r"^\d{4}-\d{2}-\d{2}-[a-z0-9-]{2,40}$", str(spec["set_id"])):
        errs.append(f"set_id 형식: YYYY-MM-DD-영문소문자 ({spec['set_id']})")
    lib = library_index or {}
    assets = _keys(spec)

    def kind(k):
        return (assets.get(k) or {}).get("kind") or (lib.get(k) or {}).get("kind") or "color"
    for k, a in assets.items():
        if not KEY_RE.match(str(k or "")):
            errs.append(f"그림 key는 영문 소문자·숫자·_만: {k}")
        if a.get("kind", "color") not in ("color", "line"):
            errs.append(f"그림 kind는 color/line: {k}")
        if not a.get("prompt") and k not in lib:
            errs.append(f"새 그림에는 영어 prompt가 필요합니다: {k}")
    pages = spec["pages"]
    if not 1 <= len(pages) <= 2:
        errs.append(f"활동지는 1~2장입니다(현재 {len(pages)}장)")
    for i, p in enumerate(pages, 1):
        t = p.get("type")
        if t not in PAGE_TYPES:
            errs.append(f"{i}장: 모르는 활동 종류 {t} (가능: {', '.join(PAGE_TYPES)})")
            continue
        title = str(p.get("title") or "")
        if not title or len(title.replace("\n", "")) > 14:
            errs.append(f"{i}장: 제목은 1~14자({title})")
        if not p.get("instruction") or len(p["instruction"]) > 32:
            errs.append(f"{i}장: 안내 문장은 한 문장 1~32자({p.get('instruction')})")
        items = p.get("items") or []
        lo, hi = COUNTS[t]
        if not lo <= len(items) <= hi:
            errs.append(f"{i}장 {PAGE_TYPES[t]}: 항목은 {lo}~{hi}개(현재 {len(items)}개)")
        if t in ("word_cards",) and len(items) % 2:
            errs.append(f"{i}장: 한글 카드는 짝수 개(2열)")
        for it in items:
            if not it.get("asset"):
                if t not in ("trace_lines", "cut_lines"):
                    errs.append(f"{i}장: 항목에 asset이 없습니다")
            if t in NEEDS_WORD and not HANGUL_WORD.match(str(it.get("word", ""))):
                errs.append(f"{i}장: 낱말은 한글 1~5자({it.get('word')})")
            if t in ("trace_letters",) and len(str(it.get("word", ""))) > 4:
                errs.append(f"{i}장: 따라 쓸 낱말은 4자 이하({it.get('word')})")
            if t in ("trace_lines", "cut_lines") and it.get("path") not in PATHS:
                errs.append(f"{i}장: path는 {'/'.join(PATHS)}")
            if t == "count_write" and not (isinstance(it.get("count"), int) and 1 <= it["count"] <= 10):
                errs.append(f"{i}장: count는 1~10({it.get('count')})")
            if t in LINE_ONLY and it.get("asset") and kind(it["asset"]) != "line":
                errs.append(f"{i}장: 색칠하기 그림은 선 그림(kind line)이어야 합니다({it.get('asset')})")
            if t in ("match_shadow", "half_draw", "trace_outline", "emotion_match") and it.get("asset") \
                    and kind(it["asset"]) != "color":
                errs.append(f"{i}장: {PAGE_TYPES[t]}는 색 그림(color)만({it.get('asset')})")
        if t in ("match_same", "match_shadow") and len({it.get("asset") for it in items}) != len(items):
            errs.append(f"{i}장: 짝 잇기 그림은 서로 달라야 합니다")
        if t == "cut_paste":
            c = p.get("container")
            if kind(c) != "line":
                errs.append(f"{i}장: 오려 붙이기 큰 그림(container)은 선 그림이어야 합니다({c})")
            if not ((assets.get(c) or {}).get("open") or (lib.get(c) or {}).get("open")):
                errs.append(f"{i}장: 오려 붙이기 큰 그림은 뚜껑 없이 열린 그릇·상자·접시처럼 안에 붙일 자리가 보이는 것이어야 합니다"
                            f"(assets에 \"open\": true와 열린 모양 프롬프트, {c})")
        if p.get("header") == "characters" and len(p.get("characters") or spec.get("characters") or []) < 2:
            errs.append(f"{i}장: 캐릭터 머리는 characters 2~4개가 필요합니다")
    for k in used_assets(spec):
        if k not in assets and k not in lib:
            errs.append(f"assets에 없는 그림: {k}")
    return errs
