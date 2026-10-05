"""이웃 후보 추천: 내 블로그와 주제가 비슷하고 최근 7일 안에 글을 쓴 블로그를 찾아 콘텐츠 관리 시트에 하루 5곳씩 적는다.

네이버에는 아무것도 쓰지 않는다(댓글·이웃 신청은 사람이 직접). 공개된 검색 결과·RSS·글만 읽는다.
  ① 검색: 프로필 기본 키워드 + 최근 내 글 태그로 네이버 블로그 최신 글 검색
         (네이버 검색 오픈 API 키가 있으면 API, 없으면 검색 결과 화면)
  ② 거르기: 내 블로그·이미 추천한 블로그 제외, RSS로 최근 7일 안에 글이 있는지·최근 30일 글 수 확인
  ③ 고르기(Claude): 후보 글 본문을 읽고 광고·체험단 위주 블로그를 빼고 5곳 선정, 요약·추천 이유·댓글 아이디어
  ④ 기록: 시트의 '<유아|교육> 이웃 후보' 탭에 줄 추가('방문함' 체크박스), data/neighbors_<프로필>.json
"""
from __future__ import annotations

import html
import json
import logging
import os
import random
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

from . import history, notify, profiles
from .config import Config
from .pipeline import KST, _Lock, setup_logging, today_kst

log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"
DEFAULT_SHEET_ID = "1uGQH525NEZjKnUR-tOshU61tbAv4Ws2-6CXukfAvHO0"  # 블로그_콘텐츠_관리시트

HEADER = ["추천일", "블로그 이름", "블로그 주소", "최근 글 제목", "최근 글 링크", "글 날짜", "최근 30일 글 수",
          "추천 이유", "글 요약", "댓글 아이디어", "방문함", "메모"]
WIDTHS = [90, 160, 230, 260, 260, 90, 100, 260, 320, 320, 70, 200]
COL_URL = "C"
COL_VISITED = 10
INPUT_COLS = (10, 11)   # 방문함·메모는 직접 입력하는 칸(시트 색상 규칙: 노란색)

# 광고·체험단 위주 블로그를 거르는 1차 신호(최종 판단은 Claude)
AD_WORDS = ("체험단", "협찬", "원고료", "제품을 제공받", "업체로부터", "광고 포함", "소정의")

_BLOG_POST = re.compile(r"blog\.naver\.com/(?:PostView\.naver\?blogId=([A-Za-z0-9_-]+)&(?:amp;)?logNo=(\d{6,})"
                        r"|([A-Za-z0-9_-]{3,30})/(\d{9,}))")
_NOT_BLOG_ID = {"PostView", "PostList", "prologue", "BlogHome", "MyBlog", "SympathyHistoryList"}


@dataclass
class Settings:
    count: int
    recent_days: int
    min_recent_posts: int
    max_candidates: int
    sheet_id: str
    tab: str
    keywords: list[str]
    client_id: str
    client_secret: str

    @classmethod
    def load(cls, cfg: Config) -> "Settings":
        env = os.environ.get
        name = cfg.profile.name.upper()
        custom = env(f"NEIGHBOR_KEYWORDS_{name}", "").strip()
        return cls(
            count=int(env("NEIGHBOR_COUNT", "5")),
            recent_days=int(env("NEIGHBOR_RECENT_DAYS", "7")),
            min_recent_posts=int(env("NEIGHBOR_MIN_POSTS_30D", "2")),
            max_candidates=int(env("NEIGHBOR_MAX_CANDIDATES", "15")),
            sheet_id=env("CONTENT_SHEET_ID", "").strip() or DEFAULT_SHEET_ID,
            tab=env(f"NEIGHBOR_TAB_{name}", "").strip() or cfg.profile.neighbor_tab,
            keywords=[k.strip() for k in custom.split(",") if k.strip()] or list(cfg.profile.neighbor_keywords),
            client_id=env("NAVER_SEARCH_CLIENT_ID", "").strip(),
            client_secret=env("NAVER_SEARCH_CLIENT_SECRET", "").strip(),
        )


def _get(url: str, headers: dict | None = None) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", "replace")


def _text(fragment: str) -> str:
    fragment = re.sub(r"<(script|style)\b.*?</\1>", " ", fragment, flags=re.S | re.I)
    fragment = re.sub(r"<br\s*/?>|</p>|</div>", "\n", fragment, flags=re.I)
    fragment = html.unescape(re.sub(r"<[^>]+>", " ", fragment)).replace("​", "")
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*\n+", "\n", fragment)).strip()


# ---------------------------------------------------------------- ① 검색

def pick_queries(keywords: list[str], own_history: list[dict], today: str, n: int = 6) -> list[str]:
    """기본 키워드와 최근 내 글 태그를 섞어 오늘 쓸 검색어를 고른다(날짜마다 다르게, 같은 날은 같게)."""
    tags: list[str] = []
    recent = [e for e in own_history if e.get("tags")][-10:]
    for e in reversed(recent):
        for t in e["tags"]:
            t = str(t).lstrip("#").strip()
            if 2 <= len(t) <= 15 and t not in tags:
                tags.append(t)
    rng = random.Random(today)
    base = list(keywords)
    rng.shuffle(base)
    rng.shuffle(tags)
    tag_part = [t for t in tags if t not in base][: n // 2]
    picked = base[: n - len(tag_part)] + tag_part
    return picked[:n]


def search_api(query: str, client_id: str, client_secret: str, fetch=None) -> list[dict]:
    """네이버 검색 오픈 API(블로그, 최신순). 하루 25,000회 무료."""
    url = ("https://openapi.naver.com/v1/search/blog.json?"
           + urllib.parse.urlencode({"query": query, "display": 50, "sort": "date"}))
    raw = (fetch or _get)(url, {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret})
    hits = []
    for it in json.loads(raw).get("items", []):
        m = _BLOG_POST.search(it.get("link", ""))
        if not m:
            continue
        blog_id, log_no = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        hits.append({"blog_id": blog_id, "log_no": log_no, "query": query,
                     "title": _text(it.get("title", "")), "blog_name": _text(it.get("bloggername", ""))})
    return hits


def search_web(query: str, fetch=None) -> list[dict]:
    """API 키가 없을 때: 네이버 검색 '블로그' 탭(최신순·1주일) 결과 화면에서 글 주소만 뽑는다."""
    url = ("https://search.naver.com/search.naver?"
           + urllib.parse.urlencode({"ssc": "tab.blog.all", "query": query, "nso": "so:dd,p:1w"}))
    raw = (fetch or _get)(url, None)
    hits, seen = [], set()
    for m in _BLOG_POST.finditer(raw):
        blog_id, log_no = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        if blog_id in _NOT_BLOG_ID or (blog_id, log_no) in seen:
            continue
        seen.add((blog_id, log_no))
        hits.append({"blog_id": blog_id, "log_no": log_no, "query": query, "title": "", "blog_name": ""})
    return hits


def search(settings: Settings, queries: list[str], fetch=None) -> list[dict]:
    hits: list[dict] = []
    for q in queries:
        try:
            if settings.client_id and settings.client_secret:
                found = search_api(q, settings.client_id, settings.client_secret, fetch)
            else:
                found = search_web(q, fetch)
            log.info("검색 '%s': 글 %d개", q, len(found))
            hits += found
        except Exception as e:  # noqa: BLE001 - 검색어 하나 실패는 건너뛴다
            log.warning("검색 '%s' 실패: %s", q, e)
    return hits


# ---------------------------------------------------------------- ② 활동 확인

def read_rss(blog_id: str, fetch=None) -> dict:
    """블로그 RSS에서 블로그 이름과 최근 글(제목·주소·날짜·발췌)을 읽는다."""
    xml = (fetch or _get)(f"https://rss.blog.naver.com/{blog_id}.xml", None)
    channel = xml.split("<item>", 1)[0]
    posts = []
    for item in history._ITEM.findall(xml):
        link = history._tag(item, "link")
        m = re.search(r"blog\.naver\.com/(?:[^/?#]+/(\d{6,})|.*?logNo=(\d{6,}))", link)
        if not m:
            continue
        try:
            date = parsedate_to_datetime(history._tag(item, "pubDate")).astimezone(KST)
        except (TypeError, ValueError):
            continue
        posts.append({
            "title": history._tag(item, "title"),
            "url": f"https://blog.naver.com/{blog_id}/{m.group(1) or m.group(2)}",
            "date": date,
            "excerpt": _text(history._tag(item, "description"))[:300],
        })
    posts.sort(key=lambda p: p["date"], reverse=True)
    return {"name": history._tag(channel, "title"), "posts": posts}


def post_text(url: str, fetch=None, limit: int = 1800) -> str:
    """글 본문(스마트에디터 본문 영역)을 글자로 읽는다. 실패하면 빈 문자열."""
    m = re.search(r"blog\.naver\.com/([^/?#]+)/(\d{6,})", url)
    if not m:
        return ""
    try:
        raw = (fetch or _get)(f"https://blog.naver.com/PostView.naver?blogId={m.group(1)}&logNo={m.group(2)}", None)
    except Exception as e:  # noqa: BLE001
        log.info("본문 읽기 실패 %s: %s", url, e)
        return ""
    start = raw.find("se-main-container")
    body = raw[start:] if start >= 0 else raw
    end = body.find("post_footer_contents")
    return _text(body[:end] if end > 0 else body)[:limit]


def profile_blog(blog_id: str, now: datetime, settings: Settings, fetch=None) -> dict | None:
    """최근 N일 안에 글이 있고 최근 30일 글이 기준 이상인 블로그만 후보로 남긴다."""
    try:
        rss = read_rss(blog_id, fetch)
    except Exception as e:  # noqa: BLE001 - RSS를 닫은 블로그 등
        log.info("RSS 읽기 실패 %s: %s", blog_id, e)
        return None
    posts = rss["posts"]
    recent = [p for p in posts if p["date"] >= now - timedelta(days=settings.recent_days)]
    month = [p for p in posts if p["date"] >= now - timedelta(days=30)]
    if not recent or len(month) < settings.min_recent_posts:
        return None
    latest = recent[0]
    ad_hits = sum(any(w in (p["title"] + p["excerpt"]) for w in AD_WORDS) for p in month)
    return {
        "blog_id": blog_id, "blog_name": rss["name"] or blog_id,
        "blog_url": f"https://blog.naver.com/{blog_id}",
        "post_title": latest["title"], "post_url": latest["url"],
        "post_date": latest["date"].strftime("%Y-%m-%d"),
        "posts_30d": len(month), "ad_posts_30d": ad_hits,
        "recent_titles": [p["title"] for p in month[:8]],
    }


# ---------------------------------------------------------------- ③ 고르기

def choose(cfg: Config, candidates: list[dict], count: int, out_dir: Path) -> tuple[list[dict], str]:
    """Claude가 후보 글을 읽고 count곳을 고른다. 실패하면 활동량 순으로 고르고 요약은 비운다."""
    from . import generate

    (out_dir / "candidates.json").write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")
    picks_path = out_dir / "picks.json"
    picks_path.unlink(missing_ok=True)
    prompt = (
        f"너는 교사 SR(꾸쓰쌤)의 네이버 {cfg.profile.label} 블로그 운영을 돕는다. "
        f"{generate._rel(out_dir / 'candidates.json')}에 오늘 찾은 이웃 후보 블로그 목록이 있다"
        "(블로그 이름, 최근 글 제목·본문 일부, 최근 30일 글 제목들, 광고성 글 수).\n\n"
        f"SR의 블로그 주제({cfg.profile.label}, {', '.join(cfg.profile.neighbor_keywords[:6])} 등)와 결이 맞는 "
        f"블로그를 최대 {count}곳 골라라. SR이 직접 방문해 글을 읽고 댓글을 달고 이웃 신청을 할 곳이다.\n"
        "고르는 기준:\n"
        "- 같은 관심사의 독자(학부모·교사)가 모이는, 직접 쓴 정보·경험 글 위주의 블로그\n"
        "- 체험단·협찬·광고·상품 판매·학원 홍보 위주 블로그, 다른 글을 짜깁기한 블로그, 자동 생성 글로 보이는 곳은 제외\n"
        "- 주제가 멀거나(맛집·여행 위주 등) 정치·논쟁 위주인 곳은 제외\n"
        "- 맞는 곳이 적으면 억지로 채우지 말고 적게 골라라\n\n"
        "고른 블로그마다 최근 글 본문을 바탕으로 아래를 한국어로 써라. 본문에 없는 내용은 지어내지 마라.\n"
        "- reason: 이웃으로 맺을 만한 이유 한 줄(40자 안팎)\n"
        "- summary: 최근 글 요약 1~2문장\n"
        "- comment_idea: SR이 직접 댓글을 쓸 때 참고할 아이디어 한 줄. 글의 구체적인 내용을 짚는 질문·공감 방향으로, "
        "그대로 복사해 붙일 완성 댓글이 아니라 무엇에 대해 말하면 좋은지 적는다. 홍보·내 블로그 링크 언급 금지.\n\n"
        f"결과를 {generate._rel(picks_path)}에 JSON으로 저장하라. 형식: "
        '{"picks": [{"blog_id": "...", "reason": "...", "summary": "...", "comment_idea": "..."}]} '
        "(좋은 순서대로). 웹 검색은 하지 말고 파일 내용만 보고 판단하라. 질문하지 말고 끝까지 진행하라."
    )
    by_id = {c["blog_id"]: c for c in candidates}
    try:
        generate._run_claude(cfg, prompt, out_dir / "claude_neighbors.log")
        data = json.loads(picks_path.read_text(encoding="utf-8"))
        picks: list[dict] = []
        for p in data.get("picks", []):
            c = by_id.get(str(p.get("blog_id", "")).strip())
            if c and all(c["blog_id"] != q["blog_id"] for q in picks):
                picks.append({**c, "reason": str(p.get("reason", "")).strip(),
                              "summary": str(p.get("summary", "")).strip(),
                              "comment_idea": str(p.get("comment_idea", "")).strip()})
        return picks[:count], ""
    except Exception as e:  # noqa: BLE001 - 고르기에 실패해도 후보는 시트에 남긴다
        log.warning("Claude 선정 실패 → 활동량 순으로 고릅니다: %s", e)
        ranked = sorted((c for c in candidates if not c["ad_posts_30d"]),
                        key=lambda c: c["posts_30d"], reverse=True)
        fallback = [{**c, "reason": "(자동 선정: AI 요약 실패)", "summary": c.get("excerpt", "")[:150],
                     "comment_idea": ""} for c in ranked[:count]]
        return fallback, f"AI 선정 실패로 활동량 순 선정({str(e)[:80]})"


# ---------------------------------------------------------------- ④ 실행

def _own_blog_ids() -> set[str]:
    env = os.environ.get
    ids = {env("NAVER_BLOG_ID", "")}
    ids |= {env(f"NAVER_BLOG_ID_{p.upper()}", "") for p in profiles.PROFILES}
    ids |= {i.strip() for i in env("NEIGHBOR_EXCLUDE", "").split(",")}
    return {i.strip().lower() for i in ids if i and i.strip()}


def _record_file(cfg: Config) -> Path:
    return cfg.data_dir / f"neighbors_{cfg.profile.name}.json"


def find(cfg: Config, settings: Settings, today: str, exclude: set[str], out_dir: Path,
         fetch=None, now: datetime | None = None) -> tuple[list[dict], str]:
    """후보를 찾고 골라 (추천 목록, 참고 문구)를 돌려준다. 시트·네이버에는 쓰지 않는다."""
    now = now or datetime.now(KST)
    queries = pick_queries(settings.keywords, history.load(cfg.history_file), today)
    log.info("검색어: %s (%s)", ", ".join(queries),
             "네이버 검색 API" if settings.client_id else "검색 결과 화면")
    hits = search(settings, queries, fetch)
    order: list[str] = []
    for h in hits:
        bid = h["blog_id"]
        if bid.lower() not in exclude and bid not in order:
            order.append(bid)
    rng = random.Random(today)
    rng.shuffle(order)   # 특정 검색어 결과만 몰리지 않게 섞는다
    candidates: list[dict] = []
    for bid in order:
        if len(candidates) >= settings.max_candidates:
            break
        info = profile_blog(bid, now, settings, fetch)
        if not info:
            continue
        info["excerpt"] = post_text(info["post_url"], fetch)
        candidates.append(info)
    log.info("검색으로 찾은 블로그 %d곳 → 최근 %d일 활동 후보 %d곳", len(order), settings.recent_days, len(candidates))
    if not candidates:
        return [], "조건에 맞는 새 블로그를 찾지 못했습니다"
    return choose(cfg, candidates, settings.count, out_dir)


def rows_for(picks: list[dict], today: str) -> list[list]:
    return [[today, p["blog_name"], p["blog_url"], p["post_title"], p["post_url"], p["post_date"],
             p["posts_30d"], p["reason"], p["summary"], p["comment_idea"], False, ""] for p in picks]


def run(cfg: Config, force: bool = False, sheet=None, fetch=None) -> int:
    from . import sheets

    today = today_kst()
    setup_logging(cfg, f"neighbors-{cfg.profile.name}-{today}")
    label = cfg.profile.label
    settings = Settings.load(cfg)
    try:
        with _Lock(cfg.log_dir / f".neighbors-{cfg.profile.name}.lock"):
            record = history.load(_record_file(cfg))
            if not force and any(r.get("date") == today for r in record):
                log.info("오늘(%s)은 이미 이웃 후보를 추천했습니다", today)
                return 0
            if sheet is None:
                sheet = sheets.Sheet(settings.sheet_id, sheets.access_token(sheets.SheetsAuth.load()))
            tab_id = sheet.ensure_tab(settings.tab, HEADER, WIDTHS, INPUT_COLS)
            listed = {u.rstrip("/").rsplit("/", 1)[-1].lower() for u in sheet.column(settings.tab, COL_URL)}
            exclude = _own_blog_ids() | listed | {str(r.get("blog_id", "")).lower() for r in record}

            out_dir = cfg.output_dir / "neighbors" / today
            out_dir.mkdir(parents=True, exist_ok=True)
            picks, note = find(cfg, settings, today, exclude, out_dir, fetch)
            if picks:
                first, last = sheet.append(settings.tab, rows_for(picks, today))
                sheet.checkboxes(tab_id, COL_VISITED, first, last)
                history.save(_record_file(cfg), record + [{"date": today, "blog_id": p["blog_id"],
                                                          "post_url": p["post_url"]} for p in picks])
            msg = f"[{label} 이웃 후보] {today} {len(picks)}곳을 시트 '{settings.tab}' 탭에 추가했습니다"
            if note:
                msg += f"\n{note}"
            notify.send(cfg, msg)
            return 0
    except Exception as e:
        log.exception("이웃 후보 추천 실패")
        notify.send(cfg, f"[{label} 이웃 후보 실패] {today}\n{e}")
        return 1
