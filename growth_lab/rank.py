"""검색 순위(선행 지표): 글의 대표 검색어로 검색했을 때 우리 글이 몇 위에 나오는지 본다.

조회수는 며칠~몇 주 뒤에야 쌓이지만, 검색 순위는 색인되자마자 보인다. "아직 조회수는 적지만 1페이지에 올라왔다"를
입질로 보고 섣불리 무덤에 넣지 않는 데 쓴다.

- 키가 있으면(NAVER_SEARCH_CLIENT_ID/SECRET, 2026-07 이전 발급분) 네이버 검색 오픈 API(블로그 100위·웹문서 30위).
- 키가 없으면(2026-07-31부터 개발자센터 신규 발급 중단) 검색 결과 화면을 읽는다: 투자 블로그는 네이버 블로그 탭,
  티스토리는 다음 블로그 탭(티스토리 유입은 다음·구글이 대부분). 첫 페이지에 보이는 글 주소 순서로 순위를 매기고,
  하루 몇십 번만, 사이사이 쉬어 가며 부른다(이웃 추천과 같은 방식). 화면이 바뀌면 순위만 비고 다른 일은 계속된다."""
from __future__ import annotations

import html
import json
import logging
import re
import time
import urllib.parse
import urllib.request

from .stats import id_tokens, post_key

log = logging.getLogger(__name__)
API = "https://openapi.naver.com/v1/search/{kind}.json?"
DEPTH = {"blog": 100, "webkr": 30}      # API가 한 번에 주는 최대 개수
PAGES = {   # 키 없이 읽는 검색 결과 화면(관련도순)
    "naver": ("blog", "https://search.naver.com/search.naver?{}", "ssc", "tab.blog.all", "query"),
    "tistory": ("daum", "https://search.daum.net/search?{}", "w", "blog", "q"),
}
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
# 결과 화면 속 블로그 글 주소(네이버 블로그·티스토리·블로거·브런치). 나오는 순서가 곧 순위다.
_POST_LINK = re.compile(
    r"https?://(?:m\.)?blog\.naver\.com/(?:PostView\.naver\?blogId=[A-Za-z0-9_-]+&(?:amp;)?logNo=\d{6,}|[A-Za-z0-9_-]{3,30}/\d{9,})"
    r"|https?://[a-z0-9-]+\.tistory\.com/(?:entry/[^\"'\s<>?#]+|m/\d+|\d+)"
    r"|https?://[a-z0-9-]+\.blogspot\.com/\d{4}/\d{2}/[^\"'\s<>?#]+"
    r"|https?://brunch\.co\.kr/@[^/\"'\s<>]+/\d+")
PAGE_PAUSE_SEC = 2.0
PAGE_MAX_QUERIES = 20


def _get(url: str, headers: dict) -> str:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", "replace")


def keyword_for(entry: dict) -> str:
    """이력 한 줄의 대표 검색어: 실험실이 정한 검색어 → 첫 태그 → 주제."""
    for k in (entry.get("lab_keyword"), *(entry.get("tags") or [])[:1], entry.get("topic")):
        k = str(k or "").strip().lstrip("#")
        if 2 <= len(k) <= 40:
            return k
    return ""


def _position(items: list[dict], url: str) -> int | None:
    key, ids = post_key(url), id_tokens(url)
    host = urllib.parse.urlparse(key).netloc
    for i, it in enumerate(items, 1):
        link = post_key(it.get("link", ""))
        if link == key or (host and host.split(".")[0] in link and any(t in link for t in ids)):
            return i
    return None


def search_rank(query: str, url: str, platform: str, client_id: str, client_secret: str, fetch=None) -> dict:
    """{"query", "blog": 순위|None, "web": 순위|None}. 순위는 1부터, 못 찾으면 None(상위 100 밖)."""
    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
    kinds = ["blog"] if platform == "naver" else ["blog", "webkr"]
    out: dict = {"query": query}
    for kind in kinds:
        q = urllib.parse.urlencode({"query": query, "display": DEPTH[kind], "sort": "sim"} if kind == "blog"
                                   else {"query": query, "display": DEPTH[kind]})
        raw = (fetch or _get)(API.format(kind=kind) + q, headers)
        out["blog" if kind == "blog" else "web"] = _position(json.loads(raw).get("items", []), url)
    return out


def ordered_posts(page_html: str) -> list[dict]:
    """검색 결과 화면에서 블로그 글 주소를 처음 나온 순서대로(같은 글은 한 번만)."""
    seen, out = set(), []
    for m in _POST_LINK.finditer(html.unescape(page_html or "")):
        u = m.group(0).replace("://m.blog.naver.com", "://blog.naver.com").replace("/m/", "/")
        pm = re.search(r"blogId=([A-Za-z0-9_-]+)&logNo=(\d+)", u)
        if pm:
            u = f"https://blog.naver.com/{pm.group(1)}/{pm.group(2)}"
        key = post_key(u)
        if key not in seen:
            seen.add(key)
            out.append({"link": key})
    return out


def _get_page(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", "replace")


def page_rank(query: str, url: str, platform: str, fetch=None) -> dict:
    """키 없이: 검색 결과 첫 화면에서의 순위. {"query", "blog"|"daum": 순위|None(첫 화면 밖)}"""
    name, base, k1, v1, qk = PAGES[platform]
    raw = (fetch or _get_page)(base.format(urllib.parse.urlencode({k1: v1, qk: query})))
    items = ordered_posts(raw)
    if not items:
        raise RuntimeError("검색 결과 화면에서 글 주소를 찾지 못했습니다(화면이 바뀌었을 수 있음)")
    return {"query": query, name: _position(items, url)}


def check(entries: list[dict], platform: str, client_id: str, client_secret: str, today: str,
          max_queries: int = 30, fetch=None, sleep=time.sleep) -> dict[str, dict]:
    """최근 글(45일 안)부터 검색 순위를 확인한다. {글 주소: {query, blog/web/daum: 순위}}
    키가 없으면 검색 결과 화면을 읽는다(하루 PAGE_MAX_QUERIES번까지, 사이사이 쉬며)."""
    from datetime import date

    use_api = bool(client_id and client_secret)
    if not use_api:
        max_queries = min(max_queries, PAGE_MAX_QUERIES)
    d0 = date.fromisoformat(today)
    recent = []
    for e in entries:
        try:
            age = (d0 - date.fromisoformat(str(e.get("date", ""))[:10])).days
        except ValueError:
            continue
        if e.get("url") and 0 <= age <= 45 and keyword_for(e):
            recent.append((age, e))
    out: dict[str, dict] = {}
    failures = 0
    for i, (_, e) in enumerate(sorted(recent, key=lambda x: x[0])[:max_queries]):
        try:
            if use_api:
                out[post_key(e["url"])] = search_rank(keyword_for(e), e["url"], platform, client_id, client_secret, fetch)
            else:
                if i:
                    sleep(PAGE_PAUSE_SEC)
                out[post_key(e["url"])] = page_rank(keyword_for(e), e["url"], platform, fetch)
        except Exception as e2:  # noqa: BLE001 - 검색어 하나 실패는 건너뛴다
            failures += 1
            log.warning("검색 순위 확인 실패(%s): %s", e.get("title", "")[:30], e2)
            if not use_api and failures >= 3 and not out:
                log.warning("검색 결과 화면을 연달아 못 읽어 오늘 검색 순위 확인을 멈춥니다")
                break
    return out
