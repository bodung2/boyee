"""발행 이력(data/published.json): 하루 1편 보장, 중복 주제 점검, 내부 링크 후보."""
from __future__ import annotations

import csv
import json
from pathlib import Path


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def published_on(path: Path, date: str) -> dict | None:
    for entry in load(path):
        if entry.get("source") == "autopost" and entry.get("date") == date and entry.get("url"):
            return entry
    return None


def append(path: Path, entry: dict) -> None:
    entries = load(path)
    entries.append(entry)
    save(path, entries)


def import_csv(path: Path, csv_path: Path) -> int:
    """콘텐츠 마스터 시트를 CSV로 내려받은 파일에서 제목·링크를 가져온다.

    열 이름은 '제목'이 들어간 열과 '링크'/'URL'이 들어간 열을 자동으로 찾는다.
    """
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return 0
    headers = list(rows[0].keys())

    def find(*keywords: str) -> str | None:
        for h in headers:
            if h and any(k in h for k in keywords):
                return h
        return None

    title_col = find("제목", "title")
    url_col = find("링크", "URL", "url")
    date_col = find("발행일", "날짜", "date")
    cat_col = find("카테고리", "category")
    if not title_col:
        raise ValueError(f"'제목' 열을 찾지 못했습니다: {headers}")

    entries = load(path)
    known = {(e.get("title"), e.get("url")) for e in entries}
    added = 0
    for row in rows:
        title = (row.get(title_col) or "").strip()
        url = (row.get(url_col) or "").strip() if url_col else ""
        if not title or (title, url) in known:
            continue
        entries.append({
            "date": (row.get(date_col) or "").strip() if date_col else "",
            "title": title,
            "url": url,
            "category": (row.get(cat_col) or "").strip() if cat_col else "",
            "source": "sheet-import",
        })
        known.add((title, url))
        added += 1
    save(path, entries)
    return added
