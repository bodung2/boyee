"""발행 이력(data/published.json): 하루 1편 보장, 중복 주제 점검, 내부 링크 후보."""
from __future__ import annotations

import csv
import html
import io
import json
import re
import urllib.parse
import urllib.request
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


def _norm_url(url: str) -> str:
    return (url or "").split("?")[0].rstrip("/")


def _norm_title(title: str) -> str:
    return re.sub(r"\s+", "", html.unescape(title or ""))


def autopost_entry(date: str, post: dict, url: str) -> dict:
    """자동 발행 글 한 편의 이력 항목(글 폴더의 post.json 기준)."""
    return {
        "date": date, "title": post.get("title", ""), "url": _norm_url(url), "topic": post.get("topic", ""),
        "category": post.get("blog_category", ""), "lane": post.get("lane", ""), "cluster": post.get("cluster", ""),
        "domain": post.get("domain"), "tags": post.get("tags", []), "source": "autopost",
    }


def upsert(path: Path, entry: dict) -> dict:
    """같은 주소의 항목이 있으면 합치고(새 값 우선, 빈 값은 기존 값 유지), 없으면 추가한다."""
    entries = load(path)
    key = _norm_url(entry.get("url", ""))
    for i, old in enumerate(entries):
        if key and _norm_url(old.get("url", "")) == key:
            merged = {**old, **{k: v for k, v in entry.items() if v not in ("", None, [])}}
            entries[i] = merged
            save(path, entries)
            return merged
    entries.append(entry)
    save(path, entries)
    return entry


def find_published(path: Path, date: str, title: str) -> dict | None:
    """그날 자동 발행한 글의 이력. 날짜로 못 찾으면(발행 주소를 확인하지 못해 기록이 빠졌고
    나중에 블로그 목록 동기화로만 들어온 경우) 제목이 같은 항목을 찾는다."""
    entry = published_on(path, date)
    if entry or not title:
        return entry
    want = _norm_title(title)
    for e in reversed(load(path)):
        if e.get("url") and _norm_title(e.get("title", "")) == want:
            return e
    return None


def import_csv(path: Path, csv_path: Path) -> int:
    """콘텐츠 마스터 시트를 CSV로 내려받은 파일에서 제목·링크를 가져온다.

    열 이름은 '제목'이 들어간 열과 '링크'/'URL'이 들어간 열을 자동으로 찾는다.
    """
    # 구글 시트 CSV는 UTF-8, 엑셀에서 다시 저장한 CSV는 CP949(한글 윈도우)다.
    try:
        text = csv_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = csv_path.read_text(encoding="cp949")
    rows = list(csv.DictReader(io.StringIO(text, newline="")))
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


def remove(path: Path, url_or_date: str) -> list[dict]:
    """네이버에서 지운 글을 발행 이력에서 뺀다(주소 또는 날짜 YYYY-MM-DD로 지정).
    이력에 남아 있으면 '오늘 이미 발행함'으로 건너뛰거나 지운 글로 내부 링크를 걸 수 있다."""
    entries = load(path)
    key = url_or_date.strip().rstrip("/")
    removed = [e for e in entries if e.get("url", "").rstrip("/") == key or e.get("date") == key]
    save(path, [e for e in entries if e not in removed])
    return removed


_ITEM = re.compile(r"<item>(.*?)</item>", re.S)


def _tag(item: str, name: str) -> str:
    m = re.search(rf"<{name}>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{name}>", item, re.S)
    return html.unescape(m.group(1)).strip() if m else ""


def parse_rss(xml: str, blog_id: str) -> list[dict]:
    """네이버 블로그 RSS에서 글 목록(제목·주소·카테고리·날짜)을 뽑는다."""
    posts = []
    for item in _ITEM.findall(xml):
        link = _tag(item, "link")
        m = re.search(r"blog\.naver\.com/(?:[^/?#]+/(\d{6,})|.*?logNo=(\d{6,}))", link)
        if not m:
            continue
        posts.append({
            "title": _tag(item, "title"),
            "url": f"https://blog.naver.com/{blog_id}/{m.group(1) or m.group(2)}",
            "category": _tag(item, "category"),
            "pub_date": _tag(item, "pubDate"),
            "tags": [t.strip() for t in _tag(item, "tag").split(",") if t.strip()],
        })
    return posts


def sync_from_rss(path: Path, blog_id: str, xml: str | None = None) -> int:
    """블로그 RSS에 있는데 이력에 없는 글(직접 쓴 글 포함)을 이력에 추가한다. 추가한 개수를 돌려준다."""
    if xml is None:
        req = urllib.request.Request(f"https://rss.blog.naver.com/{blog_id}.xml",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            xml = resp.read().decode("utf-8", "replace")
    entries = load(path)
    known = {e.get("url", "").rstrip("/") for e in entries}
    added = 0
    for post in parse_rss(xml, blog_id):
        if post["url"] in known:
            continue
        entries.append({"date": "", "title": post["title"], "url": post["url"],
                        "category": post["category"], "tags": post["tags"],
                        "pub_date": post["pub_date"], "source": "rss"})
        known.add(post["url"])
        added += 1
    if added:
        save(path, entries)
    return added


LIST_API = ("https://blog.naver.com/PostTitleListAsync.naver?blogId={blog_id}&viewdate=&currentPage={page}"
            "&categoryNo=0&parentCategoryNo=&countPerPage=30")


def _loose_json(raw: str) -> dict:
    """네이버 글 목록 응답은 JSON 안에 \\' 같은 비표준 이스케이프가 섞여 있어 느슨하게 읽는다."""
    raw = raw.strip().replace("\\'", "'")
    return json.loads(raw, strict=False)


def fetch_all_posts(blog_id: str, max_pages: int = 300, fetch=None) -> list[dict]:
    """블로그의 '전체 글' 목록을 페이지(30개씩)마다 끝까지 읽는다(공개 글 기준)."""
    def default_fetch(url: str) -> str:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                                   "Referer": f"https://blog.naver.com/{blog_id}"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read().decode("utf-8", "replace")

    fetch = fetch or default_fetch
    posts: list[dict] = []
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        data = _loose_json(fetch(LIST_API.format(blog_id=blog_id, page=page)))
        items = data.get("postList") or []
        new = 0
        for it in items:
            log_no = str(it.get("logNo", "")).strip()
            if not log_no or log_no in seen:
                continue
            seen.add(log_no)
            new += 1
            posts.append({
                "title": urllib.parse.unquote_plus(str(it.get("title", ""))).strip(),
                "url": f"https://blog.naver.com/{blog_id}/{log_no}",
                "category_no": str(it.get("categoryNo", "")),
                "add_date": urllib.parse.unquote_plus(str(it.get("addDate", ""))).strip(),
            })
        total = int(str(data.get("totalCount") or "0") or 0)
        if not new or (total and len(posts) >= total):
            break
    return posts


def sync_all(path: Path, blog_id: str, fetch=None) -> tuple[int, int]:
    """전체 글 목록으로 이력을 채운다(오래된 글·직접 쓴 글 포함). (추가한 수, 블로그 전체 글 수)."""
    posts = fetch_all_posts(blog_id, fetch=fetch)
    entries = load(path)
    known = {e.get("url", "").rstrip("/") for e in entries}
    added = 0
    for post in posts:
        if post["url"] in known:
            continue
        entries.append({"date": "", "title": post["title"], "url": post["url"], "category": "",
                        "category_no": post["category_no"], "pub_date": post["add_date"], "source": "blog-list"})
        known.add(post["url"])
        added += 1
    if added:
        save(path, entries)
    return added, len(posts)


def sync(path: Path, blog_id: str) -> str:
    """매일 실행 전 동기화: 전체 목록을 먼저 시도하고, 안 되면 RSS(최근 글)로 대신한다."""
    try:
        added, total = sync_all(path, blog_id)
        return f"전체 글 목록 {total}편 확인, 이력에 없던 {added}편 추가"
    except Exception as e:
        added = sync_from_rss(path, blog_id)
        return f"전체 목록 조회 실패({e}) → RSS로 최근 글 {added}편 추가"
