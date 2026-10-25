"""검색 순위(선행 지표): 글의 대표 검색어로 네이버 검색 오픈 API를 불러 우리 글이 몇 위에 나오는지 본다.

조회수는 며칠~몇 주 뒤에야 쌓이지만, 검색 순위는 색인되자마자 보인다. "아직 조회수는 적지만 1페이지에 올라왔다"를
입질로 보고 섣불리 무덤에 넣지 않는 데 쓴다. 키는 이웃 추천과 같은 NAVER_SEARCH_CLIENT_ID/SECRET(무료, 하루 25,000회)."""
from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request

from .stats import id_tokens, post_key

log = logging.getLogger(__name__)
API = "https://openapi.naver.com/v1/search/{kind}.json?"
DEPTH = {"blog": 100, "webkr": 30}      # API가 한 번에 주는 최대 개수


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


def check(entries: list[dict], platform: str, client_id: str, client_secret: str, today: str,
          max_queries: int = 30, fetch=None) -> dict[str, dict]:
    """최근 글(45일 안)부터 검색 순위를 확인한다. {글 주소: {query, blog, web}}"""
    from datetime import date

    if not (client_id and client_secret):
        return {}
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
    for _, e in sorted(recent, key=lambda x: x[0])[:max_queries]:
        try:
            out[post_key(e["url"])] = search_rank(keyword_for(e), e["url"], platform, client_id, client_secret, fetch)
        except Exception as e2:  # noqa: BLE001 - 검색어 하나 실패는 건너뛴다
            log.warning("검색 순위 확인 실패(%s): %s", e.get("title", "")[:30], e2)
    return out
