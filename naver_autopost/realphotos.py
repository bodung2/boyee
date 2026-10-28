"""실제 사진: 글쓴이가 post.json "photos"에 적은 대상(시험장·법원·주민센터 건물 같은 실제 장소·사물)을
위키미디어 커먼즈에서 찾아 상업 이용 가능한 라이선스만 후보로 내려받는다(구글 블로거와 같은 검색·라이선스 규칙).

후보 고르기는 따로 모델을 부르지 않고 Claude 팩트체크가 그림 검수와 함께 한다(factcheck.json "photo_choice").
고른 사진은 크게 다시 내려받고, 사진 아래 캡션에 작가·라이선스를 적는다(CC BY 계열 표기 의무).
"""
from __future__ import annotations

import logging
import shutil
import urllib.request
from pathlib import Path

from blogger_autopost import photos as commons

log = logging.getLogger(__name__)
CANDIDATES = 3


def photo_specs(post: dict, limit: int) -> list[dict]:
    return [p for p in (post.get("photos") or [])
            if isinstance(p, dict) and p.get("name") and (p.get("search") or p.get("subject"))][:limit]


def find_candidates(cfg, post: dict, out_dir: Path, fetch=None, fetch_bytes=None) -> tuple[set[str], list[str]]:
    """사진 자리마다 후보를 내려받아 post["photo_candidates"]에 적는다. (후보가 있는 자리 이름들, 메모)"""
    found: set[str] = set()
    notes: list[str] = []
    table = post.setdefault("photo_candidates", {})
    for spec in photo_specs(post, cfg.photo_count):
        name = spec["name"]
        if table.get(name) and all((out_dir / c["file"]).exists() for c in table[name]):
            found.add(name)             # 이어서 실행: 내려받아 둔 후보 그대로
            continue
        pool: list[dict] = []
        for q in commons._queries(spec):
            try:
                for c in commons.search(q, CANDIDATES, fetch):
                    if c["title"] not in {x["title"] for x in pool}:
                        pool.append(c)
            except Exception as e:  # noqa: BLE001
                log.warning("커먼즈 검색 실패(%s): %s", q, e)
            if len(pool) >= CANDIDATES:
                break
        cands = []
        for j, c in enumerate(pool[:CANDIDATES], 1):
            cid = f"{name}_c{j}"
            try:
                commons._download(c["thumb_url"], out_dir / "photos" / f"{cid}.jpg", fetch_bytes)
            except Exception as e:  # noqa: BLE001
                log.warning("사진 후보 내려받기 실패(%s): %s", c["title"], e)
                continue
            cands.append({"id": cid, "file": f"photos/{cid}.jpg", "title": c["title"],
                          "description": c["description"][:300], "artist": c["artist"][:120],
                          "license": c["license"], "license_url": c["license_url"], "page_url": c["page_url"],
                          "thumb_url": c["thumb_url"]})
        if cands:
            table[name] = cands
            found.add(name)
        else:
            table.pop(name, None)
            notes.append(f"{name}: 커먼즈에서 쓸 수 있는 라이선스의 사진을 찾지 못함({', '.join(commons._queries(spec))[:80]})")
    return found, notes


def credit_text(c: dict) -> str:
    """캡션 꼬리: '사진: 작가 / CC BY-SA 4.0 / 위키미디어 커먼즈'"""
    artist = " ".join(str(c.get("artist") or "").split())[:60] or "작가 미상"
    return f"사진: {artist} / {c.get('license', '')} / 위키미디어 커먼즈"


def apply_choice(post: dict, out_dir: Path, choice: dict, fetch_bytes=None) -> tuple[set[str], set[str]]:
    """팩트체크가 고른 후보를 본문 사진으로 확정한다. (확정한 이름들, 뺄 이름들)
    choice: {"photo_a": "photo_a_c2" | "none" | 이유}"""
    from . import content

    table = post.get("photo_candidates") or {}
    specs = {s["name"]: s for s in post.get("photos") or [] if isinstance(s, dict) and s.get("name")}
    chosen, dropped = set(), set()
    for name in specs:
        cands = {c["id"]: c for c in table.get(name, [])}
        pick = cands.get(str((choice or {}).get(name) or "").strip())
        if not pick:
            dropped.add(name)
            continue
        dst = out_dir / f"{name}.jpg"
        try:
            _fetch_large(pick["thumb_url"], dst, fetch_bytes)
        except Exception as e:  # noqa: BLE001 - 큰 사진을 못 받으면 검수한 작은 사진을 쓴다
            log.warning("사진 크게 받기 실패(%s), 검수용 사진을 씁니다: %s", pick["title"], e)
            shutil.copyfile(out_dir / pick["file"], dst)
        specs[name]["chosen"] = {k: pick[k] for k in ("id", "title", "artist", "license", "license_url", "page_url")}
        base = str(specs[name].get("caption") or specs[name].get("subject") or "").strip().rstrip(".")
        post["body_html"] = content.add_caption(post["body_html"], name,
                                                f"{base} · {credit_text(pick)}" if base else credit_text(pick))
        chosen.add(name)
    return chosen, dropped


def _fetch_large(url: str, dst: Path, fetch_bytes=None) -> None:
    if fetch_bytes:
        data = fetch_bytes(url)
    else:
        req = urllib.request.Request(url, headers={"User-Agent": commons.USER_AGENT})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
    dst.write_bytes(data)

