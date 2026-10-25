"""블로그 통계 화면 읽기(네이버 블로그 통계, 티스토리 관리 > 통계).

두 곳 모두 공식 통계 API가 없다. 그래서 발행에 쓰는 자동화용 크롬(로그인 저장됨)으로 통계 화면을 열고,
화면이 받아 오는 데이터(JSON 응답)와 화면 글자를 통째로 저장한 뒤, 우리가 쓴 글의 제목·글 번호가 들어 있는
항목에서 조회수로 보이는 숫자를 찾는다. 읽기만 하고 아무것도 누르지 않는다(메뉴 이동 제외).

통계 화면 주소·메뉴 이름은 블로그 서비스가 바꿀 수 있어서 후보를 여러 개 두고, .env의
LAB_NAVER_STAT_URLS / LAB_TISTORY_STAT_URLS로 바꿀 수 있게 했다. 못 찾으면 `python -m growth_lab diagnose`로
화면을 저장해 Claude에게 보여 준다.
"""
from __future__ import annotations

import html
import json
import logging
import re
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

NAVER_URLS = [
    "https://admin.blog.naver.com/{blog}/stat/today",
    "https://admin.blog.naver.com/{blog}/stat/cv",
    "https://admin.blog.naver.com/{blog}/stat/rank/cv",
    "https://admin.blog.naver.com/{blog}/stat/referer/total",
    "https://admin.blog.naver.com/{blog}/stat/referer/search",
]
NAVER_NAV = ["조회수 순위", "게시물 통계", "게시글 통계", "유입분석", "검색어", "조회수"]
TISTORY_URLS = [
    "{url}/manage",
    "{url}/manage/statistics/blog",
    "{url}/manage/statistics/entry",
    "{url}/manage/statistics/keyword",
]
TISTORY_NAV = ["방문 통계", "인기글", "유입 키워드", "유입 경로", "게시글 통계", "통계"]

# 조회수로 보이는 필드 이름(앞쪽일수록 우선). 댓글·공감·순위 같은 숫자는 뺀다.
_COUNT_KEYS = ["cv", "pv", "view", "hit", "read", "visit", "cnt", "count"]
_NOT_COUNT = re.compile(r"comment|reply|like|sympathy|share|scrap|tag|page|rank|order|sort|size|limit|offset|"
                        r"total_?page|year|month|date|stamp|no$|id$|seq|width|height", re.I)
_DATE_LIKE = re.compile(r"\d{2,4}[.\-/]\d{1,2}")


@dataclass
class Capture:
    responses: list[dict] = field(default_factory=list)   # [{url, json}]
    pages: list[dict] = field(default_factory=list)       # [{url, nav, text}]
    errors: list[str] = field(default_factory=list)
    logged_in: bool = True


def post_key(url: str) -> str:
    return (url or "").split("?")[0].split("#")[0].rstrip("/")


def id_tokens(url: str) -> set[str]:
    """글을 가리키는 번호·주소 조각(통계 데이터 속에서 우리 글을 찾는 열쇠)."""
    url = url or ""
    out = set()
    for pattern in (r"logNo=(\d+)", r"/(\d{6,})(?:[/?#]|$)", r"tistory\.com/(\d+)(?:[/?#]|$)"):
        out |= set(re.findall(pattern, url))
    m = re.search(r"/entry/([^/?#]+)", url)
    if m:
        out.add(urllib.parse.unquote(m.group(1)))
    return {t for t in out if len(t) >= 2}


def _norm(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", html.unescape(str(text or ""))).lower()


def _loose_json(raw: str):
    """JSON 앞뒤에 콜백 이름·보안 접두어(`)]}',`)가 붙은 응답도 읽는다."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (raw.find("{"), raw.find("[")) if i >= 0]
    if not starts:
        return None
    body = raw[min(starts):]
    for end in (body.rfind("}"), body.rfind("]")):
        if end > 0:
            try:
                return json.loads(body[:end + 1])
            except json.JSONDecodeError:
                continue
    return None


def _count_fields(d: dict) -> list[tuple[str, int]]:
    out = []
    for k, v in d.items():
        if isinstance(v, bool) or _NOT_COUNT.search(str(k)):
            continue
        if isinstance(v, str) and re.fullmatch(r"\d[\d,]*", v.strip()):
            v = int(v.replace(",", ""))
        if not isinstance(v, int) or v < 0:
            continue
        low = str(k).lower()
        prio = next((i for i, name in enumerate(_COUNT_KEYS) if name in low), None)
        if prio is not None:
            out.append((k, v, prio))
    return [(k, v) for k, v, _ in sorted(out, key=lambda x: x[2])]


def _walk(obj, visit) -> None:
    if isinstance(obj, dict):
        visit(obj)
        for v in obj.values():
            _walk(v, visit)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, visit)


def _matches(d: dict, title: str, ids: set[str]) -> bool:
    for v in d.values():
        if isinstance(v, (dict, list)):
            continue
        s = str(v)
        if s in ids or any(i in s for i in ids if len(i) >= 6):
            return True
        n = _norm(s)
        if len(title) >= 8 and n and (n == title or (len(n) >= 8 and (title in n or n in title))):
            return True
    return False


def match_posts(cap: Capture, posts: list[dict]) -> dict[str, dict]:
    """통계 데이터에서 우리 글의 조회수를 찾는다. {글 주소: {views, candidates}}
    여러 화면에서 서로 다른 숫자(기간 조회수·누적 조회수)가 나오면 가장 큰 값(누적일 가능성이 높음)을 쓴다."""
    found: dict[str, list[dict]] = {}
    for p in posts:
        key, title, ids = post_key(p.get("url", "")), _norm(p.get("title", "")), id_tokens(p.get("url", ""))
        if not key:
            continue
        cands: list[dict] = []

        def visit(d: dict, src: str) -> None:
            if _matches(d, title, ids):
                fields = _count_fields(d)
                if fields:
                    cands.append({"src": src, "field": fields[0][0], "value": fields[0][1]})

        for r in cap.responses:
            _walk(r.get("json"), lambda d, s=r.get("url", ""): visit(d, s))
        if not cands and len(title) >= 8:
            cands += _text_candidates(cap, title, p.get("title", ""))
        if cands:
            found[key] = cands
    return {k: {"views": max(c["value"] for c in v), "candidates": v[:6]} for k, v in found.items()}


def _text_candidates(cap: Capture, title: str, raw_title: str) -> list[dict]:
    """JSON에서 못 찾았을 때만: 화면 글자에서 제목 줄과 그다음 몇 줄에 나오는 첫 숫자
    (날짜 모양, 제목 속 숫자는 뺀다)."""
    out = []
    in_title = set(re.findall(r"\d[\d,]*", raw_title))
    for page in cap.pages:
        lines = (page.get("text") or "").splitlines()
        for i, line in enumerate(lines):
            if title[:20] not in _norm(line):
                continue
            tail = " ".join(lines[i:i + 4])
            for tok in re.findall(r"[\d.,/\-]+", tail):
                tok = tok.strip(".,/-")
                if _DATE_LIKE.search(tok) or not re.fullmatch(r"\d[\d,]*", tok) or tok in in_title:
                    continue
                out.append({"src": f"text:{page.get('url', '')}", "field": "text", "value": int(tok.replace(",", ""))})
                break
    return out


# ---- 브라우저로 통계 화면 열기 ----

def _start_urls(platform: str, blog: str, base_url: str, override: list[str]) -> list[str]:
    urls = override or (NAVER_URLS if platform == "naver" else TISTORY_URLS)
    return [u.format(blog=blog, url=base_url.rstrip("/")) for u in urls]


def _page_text(page) -> str:
    parts = []
    for frame in page.frames:
        try:
            parts.append(frame.inner_text("body", timeout=3000))
        except Exception:  # noqa: BLE001 - 숨은 프레임·광고 프레임
            continue
    return "\n".join(parts)[:60000]


def _click_nav(page, word: str) -> bool:
    for frame in page.frames:
        for role in ("tab", "link", "button", "menuitem"):
            try:
                loc = frame.get_by_role(role, name=re.compile(re.escape(word)))
                if loc.count() and loc.first.is_visible():
                    loc.first.click(timeout=4000)
                    return True
            except Exception:  # noqa: BLE001
                continue
        try:
            loc = frame.get_by_text(word, exact=True)
            if loc.count() and loc.first.is_visible():
                loc.first.click(timeout=4000)
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _browse(ctx, starts: list[str], nav: list[str], cap: Capture, shots: Path | None, login_hosts: tuple[str, ...]) -> None:
    def on_response(resp) -> None:
        try:
            kind = resp.request.resource_type
            ctype = (resp.headers or {}).get("content-type", "")
            if kind not in ("xhr", "fetch", "script") and "json" not in ctype:
                return
            if kind == "script" and "json" not in ctype and "callback" not in resp.url:
                return
            body = resp.text()
            if len(body) > 2_000_000:
                return
            data = _loose_json(body)
            if data is not None:
                cap.responses.append({"url": resp.url.split("?")[0], "query": resp.url.partition("?")[2][:300],
                                      "json": data})
        except Exception:  # noqa: BLE001 - 응답 하나 못 읽어도 계속한다
            return

    ctx.on("response", on_response)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.on("dialog", lambda d: d.dismiss())
    step = 0
    for url in starts:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(4000)
        except Exception as e:  # noqa: BLE001
            cap.errors.append(f"{url}: {e}"[:300])
            continue
        if any(h in page.url for h in login_hosts):
            cap.logged_in = False
            cap.errors.append(f"로그인 화면으로 넘어갔습니다: {page.url[:120]}")
            return
        step += 1
        cap.pages.append({"url": page.url, "nav": "", "text": _page_text(page)})
        if shots:
            page.screenshot(path=str(shots / f"{step:02d}.png"), full_page=True)
        for word in nav:
            if not _click_nav(page, word):
                continue
            page.wait_for_timeout(3000)
            step += 1
            cap.pages.append({"url": page.url, "nav": word, "text": _page_text(page)})
            if shots:
                page.screenshot(path=str(shots / f"{step:02d}-{word}.png"), full_page=True)


def capture_naver(cfg, override: list[str], shots: Path | None = None) -> Capture:
    """cfg: naver_autopost.config.Config(투자 프로필) — 발행용 크롬 프로필을 그대로 쓴다."""
    from playwright.sync_api import sync_playwright

    from naver_autopost.publisher import _launch, _logged_in

    cap = Capture()
    with sync_playwright() as p:
        ctx = _launch(p, cfg, headless=cfg.headless)
        try:
            if not _logged_in(ctx):
                cap.logged_in = False
                cap.errors.append("네이버 로그인이 풀려 있습니다")
                return cap
            _browse(ctx, _start_urls("naver", cfg.blog_id, "", override), NAVER_NAV, cap, shots, ("nid.naver.com",))
        finally:
            ctx.close()
    return cap


def capture_tistory(cfg, override: list[str], shots: Path | None = None) -> Capture:
    """cfg: tistory_autopost.config.TistoryConfig — 발행용 크롬 프로필과 저장 쿠키를 그대로 쓴다."""
    from playwright.sync_api import sync_playwright

    from tistory_autopost.publisher import _close, _ensure_logged_in, _open, _save_cookies

    cap = Capture()
    with sync_playwright() as p:
        ctx = _open(p, cfg, headless=cfg.headless)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.on("dialog", lambda d: d.dismiss())
            if not _ensure_logged_in(page, cfg):
                cap.logged_in = False
                cap.errors.append("티스토리(카카오) 로그인이 풀려 있습니다")
                return cap
            _save_cookies(ctx, cfg)
            _browse(ctx, _start_urls("tistory", cfg.blog_name, cfg.blog_url, override), TISTORY_NAV, cap, shots,
                    ("accounts.kakao.com", "/auth/login", "logins.daum.net"))
        finally:
            _close(ctx, cfg)
    return cap


def save_capture(cap: Capture, out_dir: Path, redact: dict[str, str] | None = None, max_json: int = 400_000) -> Path:
    """통계 화면 원본을 저장한다(주간 리뷰가 유입 검색어·경로를 읽는 자료). redact: 지울 문자열 → 대체 문자열."""
    out_dir.mkdir(parents=True, exist_ok=True)

    def clean(text: str) -> str:
        for old, new in (redact or {}).items():
            if old:
                text = text.replace(old, new)
        return text

    data = {"logged_in": cap.logged_in, "errors": cap.errors,
            "pages": [{**p, "text": clean(p.get("text", ""))} for p in cap.pages],
            "responses": []}
    used = 0
    for r in cap.responses:
        raw = clean(json.dumps(r, ensure_ascii=False))
        if used + len(raw) > max_json:
            data["responses"].append({"url": clean(r.get("url", "")), "json": "(크기 제한으로 생략)"})
            continue
        used += len(raw)
        data["responses"].append(json.loads(raw))
    path = out_dir / "capture.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return path
