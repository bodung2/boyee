"""검색 유입 진단: 블로그 글·공개 페이지·서치 콘솔 데이터를 모아 diagnostics/blogger/에 저장한다.

집 PC에서 `python -m blogger_autopost diagnose`로 실행하면 결과를 GitHub에 올려 Claude가 분석할 수 있게 한다.
토큰·비밀번호 같은 비밀 값은 담지 않는다.
"""
from __future__ import annotations

import html
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from naver_autopost.content import html_to_text

from . import api
from .config import BloggerConfig

log = logging.getLogger(__name__)
WEBMASTERS = "https://www.googleapis.com/webmasters/v3"
INSPECT = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
# 서치 콘솔의 '리디렉션 오류'는 구글이 휴대폰용 로봇(Googlebot Smartphone)으로 읽을 때 난다 → 같은 신분으로 따라가 본다.
AGENTS = {
    "googlebot_mobile": ("Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/126.0.0.0 Mobile Safari/537.36 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"),
    "mobile": ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
               "Chrome/126.0.0.0 Mobile Safari/537.36"),
    "desktop": UA,
}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _hop(url: str, ua: str) -> tuple[int, str, str]:
    """리디렉션을 따라가지 않고 한 번만 요청한다. (상태 코드, Location, 본문 앞부분)"""
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(urllib.request.Request(url, headers={"User-Agent": ua}), timeout=30) as resp:
            return resp.status, "", resp.read(200_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location", "") if e.headers else "", ""
    except Exception as e:  # noqa: BLE001
        return 0, "", str(e)[:200]


def redirect_chain(url: str, ua: str, max_hops: int = 10, hop=None) -> dict:
    """주소를 한 단계씩 따라간 기록과 판정(ok / loop / too_many / broken / error)."""
    hop = hop or _hop
    hops, seen, current = [], set(), url
    for _ in range(max_hops):
        status, location, body = hop(current, ua)
        item = {"url": current, "status": status}
        if location:
            item["location"] = location
        hops.append(item)
        if status in (301, 302, 303, 307, 308):
            if not location:
                return {"verdict": "broken", "hops": hops}
            nxt = urllib.parse.urljoin(current, location)
            if nxt in seen or nxt == current:
                return {"verdict": "loop", "hops": hops}
            seen.add(current)
            current = nxt
            continue
        verdict = "ok" if status == 200 else "error"
        result = {"verdict": verdict, "hops": hops}
        if status == 200:
            seo = page_seo(body)
            result.update({k: seo[k] for k in ("canonical", "og_url", "meta_robots", "meta_refresh", "js_redirect")})
        return result
    return {"verdict": "too_many", "hops": hops}


def _fetch(url: str) -> tuple[int, str, dict]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8", "replace"), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:2000], dict(e.headers or {})
    except Exception as e:  # noqa: BLE001
        return 0, str(e), {}


def _google(cfg: BloggerConfig, url: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 method="POST" if body is not None else "GET",
                                 headers={"Authorization": f"Bearer {api.access_token(cfg)}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        return {"_error": f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:500]}"}


def page_seo(html_text: str) -> dict:
    """한 페이지의 검색 관련 태그(제목, 설명, robots, canonical, 구조)."""
    def meta(name: str) -> str | None:
        m = re.search(rf'<meta[^>]+(?:name|property)=["\']{re.escape(name)}["\'][^>]*content=["\']([^"\']*)', html_text, re.I) \
            or re.search(rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:name|property)=["\']{re.escape(name)}["\']', html_text, re.I)
        return html.unescape(m.group(1)) if m else None
    title = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.I | re.S)
    # 블로거는 <link href='...' rel='canonical'/>처럼 href를 먼저 쓴다 → 순서 상관없이 찾는다.
    canon = (re.search(r'<link[^>]+rel=["\']canonical["\'][^>]*href=["\']([^"\']+)', html_text, re.I)
             or re.search(r'<link[^>]+href=["\']([^"\']+)["\'][^>]*rel=["\']canonical["\']', html_text, re.I))
    refresh = re.search(r'<meta[^>]+http-equiv=["\']refresh["\'][^>]*>', html_text, re.I)
    head = html_text[:html_text.lower().find("</head>")] if "</head>" in html_text.lower() else html_text
    js_redirect = re.search(r"(?:window\.|document\.)?location(?:\.href)?\s*=(?!=)|location\.(?:replace|assign)\s*\(",
                            head)
    return {
        "title_tag": html.unescape(title.group(1).strip()) if title else None,
        "meta_description": meta("description"),
        "meta_description_tags": len(re.findall(r'<meta[^>]+name=["\']description["\']', html_text, re.I)),
        "meta_robots": meta("robots"),
        "og_image": meta("og:image"),
        "og_description": meta("og:description"),
        "canonical": html.unescape(canon.group(1)) if canon else None,
        "og_url": meta("og:url"),
        "meta_refresh": refresh.group(0) if refresh else None,
        "js_redirect": head[max(js_redirect.start() - 80, 0):js_redirect.end() + 80] if js_redirect else None,
        "h1_count": len(re.findall(r"<h1\b", html_text, re.I)),
        "has_adsense": "adsbygoogle" in html_text,
        "has_search_console_verification": bool(meta("google-site-verification")),
        "html_bytes": len(html_text),
    }


def post_stats(post: dict) -> dict:
    body = post.get("content") or ""
    text = html_to_text(body)
    imgs = re.findall(r"<img\b[^>]*>", body, re.I)
    links = re.findall(r'<a\b[^>]*href=["\']([^"\']+)', body, re.I)
    host = urllib.parse.urlparse(post.get("url", "")).netloc
    return {
        "title": post.get("title"), "url": post.get("url"), "published": post.get("published"),
        "labels": post.get("labels", []),
        "words": len(re.findall(r"\b\w+\b", text)), "chars": len(text),
        "h2": len(re.findall(r"<h2\b", body, re.I)), "h3": len(re.findall(r"<h3\b", body, re.I)),
        "images": len(imgs), "images_without_alt": sum(1 for i in imgs if not re.search(r'alt=["\'][^"\']+', i)),
        "ai_labelled_images": body.count("AI-generated"),
        "internal_links": sum(1 for u in links if host and host in u),
        "external_links": sum(1 for u in links if u.startswith("http") and host not in u),
        "first_200_chars": text[:200],
    }


def search_console(cfg: BloggerConfig, blog_url: str, post_urls: list[str]) -> dict:
    if not api.has_scope(cfg, api.SEARCH_CONSOLE_SCOPE):
        return {"_error": "서치 콘솔 권한이 없습니다 → python -m blogger_autopost auth 다시 실행 후 diagnose"}
    sites = _google(cfg, f"{WEBMASTERS}/sites")
    if "_error" in sites:
        return {"_error": f"서치 콘솔 API 오류(구글 클라우드에서 'Google Search Console API' 사용 설정 필요할 수 있음): {sites['_error']}"}
    entries = sites.get("siteEntry", [])
    host = urllib.parse.urlparse(blog_url).netloc
    site = next((e["siteUrl"] for e in entries if host in e["siteUrl"]), None)
    out: dict = {"registered_sites": [e.get("siteUrl") for e in entries], "site": site}
    if not site:
        out["_error"] = f"서치 콘솔에 {blog_url} 이 등록되어 있지 않습니다"
        return out
    end = date.today()
    start = end - timedelta(days=90)
    q = urllib.parse.quote(site, safe="")
    for dim in ("date", "query", "page", "country"):
        out[f"by_{dim}"] = _google(cfg, f"{WEBMASTERS}/sites/{q}/searchAnalytics/query", {
            "startDate": start.isoformat(), "endDate": end.isoformat(), "dimensions": [dim], "rowLimit": 100})
    out["sitemaps"] = _google(cfg, f"{WEBMASTERS}/sites/{q}/sitemaps")
    out["inspections"] = []
    for url in post_urls[:20]:
        r = _google(cfg, INSPECT, {"inspectionUrl": url, "siteUrl": site})
        idx = ((r.get("inspectionResult") or {}).get("indexStatusResult") or {})
        out["inspections"].append({"url": url, "error": r.get("_error"), **{k: idx.get(k) for k in (
            "verdict", "coverageState", "indexingState", "robotsTxtState", "pageFetchState", "lastCrawlTime",
            "googleCanonical", "userCanonical", "crawledAs")}})
    return out


def redirects(blog_url: str, post_urls: list[str], hop=None) -> list[dict]:
    """글 주소마다 구글 휴대폰 로봇·휴대폰·PC로, 그리고 http:// 주소와 ?m=1 주소도 따라가 본다."""
    rows = []
    for url in [blog_url, *post_urls]:
        row = {"url": url}
        for name, ua in AGENTS.items():
            row[name] = redirect_chain(url, ua, hop=hop)
        row["http_googlebot_mobile"] = redirect_chain(url.replace("https://", "http://", 1), AGENTS["googlebot_mobile"], hop=hop)
        row["m1_googlebot_mobile"] = redirect_chain(url + ("&" if "?" in url else "?") + "m=1", AGENTS["googlebot_mobile"],
                                                    hop=hop)
        rows.append(row)
    return rows


def run(cfg: BloggerConfig, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    blog_id = api.resolve_blog_id(cfg)
    blog = api.request(cfg, "GET", f"/blogs/{blog_id}")
    blog_url = blog.get("url", cfg.blog_url).rstrip("/") + "/"
    report: dict = {"blog": {k: blog.get(k) for k in ("name", "description", "url", "published", "updated")}
                    | {"total_posts": (blog.get("posts") or {}).get("totalItems")}}

    posts: list[dict] = []
    token = None
    while True:
        params = {"maxResults": 100, "fetchBodies": "true", "status": "live",
                  "fields": "nextPageToken,items(id,title,url,published,labels,content)"}
        if token:
            params["pageToken"] = token
        data = api.request(cfg, "GET", f"/blogs/{blog_id}/posts", params)
        posts += data.get("items", [])
        token = data.get("nextPageToken")
        if not token or len(posts) >= 300:
            break
    report["scheduled"] = [{"title": p.get("title"), "published": p.get("published")}
                           for p in api.list_posts(cfg, status="scheduled")]
    report["posts"] = [post_stats(p) for p in posts]

    public: dict = {}
    for name, url in (("home", blog_url), ("robots", blog_url + "robots.txt"), ("sitemap", blog_url + "sitemap.xml"),
                      ("feed", blog_url + "feeds/posts/default")):
        status, text, headers = _fetch(url)
        public[name] = {"url": url, "status": status, "x_robots_tag": headers.get("X-Robots-Tag")}
        if name == "home":
            public[name].update(page_seo(text))
        elif name == "robots":
            public[name]["text"] = text[:1500]
        elif name == "sitemap":
            public[name]["url_count"] = len(re.findall(r"<loc>", text))
            public[name]["head"] = text[:600]
    public["posts"] = []
    for p in posts[:15]:
        status, text, headers = _fetch(p["url"])
        public["posts"].append({"url": p["url"], "status": status, "x_robots_tag": headers.get("X-Robots-Tag"),
                                **page_seo(text)})
    report["public_pages"] = public
    report["redirects"] = redirects(blog_url, [p["url"] for p in posts[:8]])
    report["search_console"] = search_console(cfg, blog_url, [p["url"] for p in posts])

    path = out_dir / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def render(urls: list[str]) -> dict[str, str]:
    """구글처럼 스크립트를 실행한 뒤의 페이지 HTML(Playwright 크롬). 실패하면 빈 dict."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {}
    out: dict[str, str] = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=UA)
            for url in urls:
                try:
                    page.goto(url, wait_until="load", timeout=45000)
                    page.wait_for_timeout(500)
                    out[url] = page.content()
                except Exception as e:  # noqa: BLE001
                    log.warning("렌더링 실패(%s): %s", url, e)
            browser.close()
    except Exception as e:  # noqa: BLE001
        log.warning("브라우저를 띄우지 못했습니다(스크립트 실행 전 HTML로 확인): %s", e)
    return out


def check_meta(cfg: BloggerConfig, limit: int = 8, renderer=render) -> list[dict]:
    """최근 공개 글 페이지에 검색 설명(meta description)이 나오는지 확인한다.
    테마 스크립트가 채우는 설명도 보이도록, 가능하면 스크립트를 실행한 뒤의 페이지로 본다."""
    posts = api.list_posts(cfg, status="live")[:limit]
    rendered = renderer([p["url"] for p in posts]) if renderer else {}
    out = []
    for p in posts:
        if p["url"] in rendered:
            status, text = 200, rendered[p["url"]]
        else:
            status, text, _ = _fetch(p["url"])
        seo = page_seo(text) if status == 200 else {}
        out.append({"title": p.get("title"), "url": p["url"], "status": status, "rendered": p["url"] in rendered,
                    "meta_description": seo.get("meta_description"), "tags": seo.get("meta_description_tags", 0),
                    "og_description": seo.get("og_description")})
    return out
