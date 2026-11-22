"""활동지 설계서(spec.json) 형식과 검사.

{
  "set_id": "2026-11-24-winter-clothes",     # 날짜-영문 주제(파일 이름에 씀)
  "theme": "겨울 옷", "title": "겨울 옷 입기 활동지", "age": "3~5세",
  "domain": "소근육", "nuri": "신체운동·건강 - 신체 활동 즐기기", "skills": ["눈과 손 협응"],
  "assets": [{"key": "mitten", "name": "장갑", "prompt": "a pair of red knitted mittens", "kind": "color"}],
  "pages": [{"type": "trace_lines", "title": "장갑을 찾아가요", "instruction": "점선을 따라 선을 그어요",
             "rows": [{"from": "bear", "to": "mitten", "path": "wave"}]}],
  "parent_tip": "…", "answers": "…"
}
"""
from __future__ import annotations

import re

PAGE_TYPES = {
    "trace_lines": "선 따라 긋기",
    "trace_letters": "낱말 따라 쓰기",
    "count_write": "세어 보고 숫자 쓰기",
    "match_shadow": "그림자 짝 잇기",
    "match_word": "그림과 낱말 잇기",
    "coloring": "색칠하기",
    "find_same": "같은 그림 찾기",
}
PATHS = ("straight", "wave", "zigzag", "loop", "steps", "arc")
HANGUL_WORD = re.compile(r"^[가-힣]{1,4}$")


def _keys(spec: dict) -> dict[str, dict]:
    return {a.get("key"): a for a in spec.get("assets") or [] if isinstance(a, dict)}


def used_assets(spec: dict) -> list[str]:
    """페이지에서 실제로 쓰는 그림 key(순서 유지, 중복 없음)."""
    seen: list[str] = []

    def add(k):
        if k and k not in seen:
            seen.append(k)
    for p in spec.get("pages") or []:
        for r in p.get("rows") or []:
            for k in (r.get("from"), r.get("to"), r.get("asset"), r.get("target"), *(r.get("options") or [])):
                add(k)
        for k in p.get("assets") or []:
            add(k)
        for pr in p.get("pairs") or []:
            add(pr.get("asset"))
        for w in p.get("words") or []:
            add(w.get("asset"))
        add(p.get("asset"))
    return seen


def problems(spec: dict, library_index: dict | None = None) -> list[str]:
    """설계서가 그릴 수 없는 모양이면 문제 목록(비면 통과)."""
    from .library import KEY_RE
    errs: list[str] = []
    for f in ("set_id", "theme", "title", "age", "assets", "pages"):
        if not spec.get(f):
            errs.append(f"필수 항목 없음: {f}")
    if errs:
        return errs
    if not re.match(r"^\d{4}-\d{2}-\d{2}-[a-z0-9-]{2,40}$", str(spec["set_id"])):
        errs.append(f"set_id 형식: YYYY-MM-DD-영문소문자 ({spec['set_id']})")
    lib = library_index or {}
    assets = _keys(spec)
    for k, a in assets.items():
        if not KEY_RE.match(str(k or "")):
            errs.append(f"그림 key는 영문 소문자·숫자·_만: {k}")
        if a.get("kind", "color") not in ("color", "line"):
            errs.append(f"그림 kind는 color/line: {k}")
        if not a.get("prompt") and k not in lib:
            errs.append(f"새 그림에는 영어 prompt가 필요합니다: {k}")
    def kind(k):
        return (assets.get(k) or {}).get("kind") or (lib.get(k) or {}).get("kind") or "color"
    pages = spec["pages"]
    if not 1 <= len(pages) <= 2:
        errs.append(f"활동지는 1~2장입니다(현재 {len(pages)}장)")
    for i, p in enumerate(pages, 1):
        t = p.get("type")
        if t not in PAGE_TYPES:
            errs.append(f"{i}장: 모르는 활동 종류 {t} (가능: {', '.join(PAGE_TYPES)})")
            continue
        if not p.get("title") or len(p["title"]) > 18:
            errs.append(f"{i}장: 제목은 1~18자({p.get('title')})")
        if not p.get("instruction") or len(p["instruction"]) > 30:
            errs.append(f"{i}장: 안내 문장은 1~30자({p.get('instruction')})")
        rows = p.get("rows") or []
        if t == "trace_lines":
            if not 3 <= len(rows) <= 5:
                errs.append(f"{i}장: 선 긋기 줄은 3~5개")
            errs += [f"{i}장: path는 {'/'.join(PATHS)}" for r in rows if r.get("path") not in PATHS]
        elif t == "trace_letters":
            words = p.get("words") or []
            if not 3 <= len(words) <= 4:
                errs.append(f"{i}장: 따라 쓸 낱말은 3~4개")
            errs += [f"{i}장: 낱말은 한글 1~4자({w.get('word')})" for w in words
                     if not HANGUL_WORD.match(str(w.get("word", "")))]
        elif t == "count_write":
            if not 3 <= len(rows) <= 4:
                errs.append(f"{i}장: 세기 줄은 3~4개")
            errs += [f"{i}장: count는 1~10({r.get('count')})" for r in rows
                     if not isinstance(r.get("count"), int) or not 1 <= r["count"] <= 10]
        elif t == "match_shadow":
            if not 3 <= len(p.get("assets") or []) <= 5:
                errs.append(f"{i}장: 그림자 잇기 그림은 3~5개")
            errs += [f"{i}장: 그림자 잇기는 색 그림(color)만({k})" for k in p.get("assets") or []
                     if kind(k) != "color"]
        elif t == "match_word":
            pairs = p.get("pairs") or []
            if not 3 <= len(pairs) <= 5:
                errs.append(f"{i}장: 낱말 잇기 짝은 3~5개")
            errs += [f"{i}장: 낱말은 한글 1~4자({x.get('word')})" for x in pairs
                     if not HANGUL_WORD.match(str(x.get("word", "")))]
        elif t == "coloring":
            k = p.get("asset")
            if kind(k) != "line":
                errs.append(f"{i}장: 색칠하기 그림은 선 그림(kind line)이어야 합니다({k})")
        elif t == "find_same":
            if not 3 <= len(rows) <= 4:
                errs.append(f"{i}장: 같은 그림 찾기 줄은 3~4개")
            for r in rows:
                opts = r.get("options") or []
                if len(opts) != 4 or r.get("target") not in opts or len(set(opts)) != 4:
                    errs.append(f"{i}장: 보기 4개(서로 다름) 안에 target이 하나 있어야 합니다")
    for k in used_assets(spec):
        if k not in assets and k not in lib:
            errs.append(f"assets에 없는 그림: {k}")
    return errs
