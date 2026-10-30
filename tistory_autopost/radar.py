"""선점형(TISTORY_MODE=scoop) 레이더: '방금 나온 것'을 공개 소스에서 모아 오늘의 후보를 만든다.

소스(data/tistory_scoop_sources.json에서 켜고 끈다):
- steam: 스팀 신작·출시 예정작·인기 판매작(store.steampowered.com 공개 API, 한국 지역·한국어)
- github: AI·개발 도구의 새 버전(api.github.com 릴리스)
- rss: 구글 트렌드 한국 급상승 등 RSS
후보마다 구글 자동완성 검색어를 붙여, 글의 질문형 소제목을 실제 검색어로 고르게 한다.
소스 하나가 실패해도 나머지로 계속한다. 네트워크가 막히면 빈 목록을 돌려준다(글쓰기 단계가 스스로 찾는다).
"""
from __future__ import annotations

import html
import json
import logging
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

log = logging.getLogger(__name__)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
KIND_WEIGHT = {"game": 30, "ai_tool": 28, "trend": 20}


@dataclass
class Scoop:
    id: str
    kind: str                     # game | ai_tool | trend
    title: str
    url: str
    when: datetime | None = None  # 출시·발표 시각(UTC). 미래면 출시 예정
    detail: str = ""
    queries: list[str] = field(default_factory=list)
    score: float = 0.0
    why: str = ""


def slug(text: str) -> str:
    text = re.sub(r"[^0-9A-Za-z가-힣]+", "-", text.lower()).strip("-")
    return text[:48] or "x"


def _get(url: str, timeout: int = 15) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


# ---------------------------------------------------------------- 소스

def steam(cfg: dict, fetch=_get) -> list[Scoop]:
    """스팀 신작·출시 예정·인기 판매. featuredcategories는 로그인 없이 쓰는 공개 엔드포인트다."""
    data = json.loads(fetch("https://store.steampowered.com/api/featuredcategories?cc=kr&l=koreana"))
    out = []
    for section, label in (("new_releases", "신작"), ("coming_soon", "출시 예정"), ("top_sellers", "인기 판매")):
        for item in (data.get(section) or {}).get("items", [])[: int(cfg.get("per_section", 8))]:
            name, appid = item.get("name", ""), item.get("id")
            if not name or not appid:
                continue
            price = item.get("final_price")
            won = f"{price // 100:,}원" if isinstance(price, int) and price else "무료/미정"
            out.append(Scoop(id=f"game-{appid}", kind="game", title=name,
                             url=f"https://store.steampowered.com/app/{appid}/",
                             detail=f"스팀 {label} · 가격 {won}"
                                    + (f" · 할인 {item['discount_percent']}%" if item.get("discount_percent") else "")))
    return out


def github(cfg: dict, fetch=_get) -> list[Scoop]:
    out = []
    for repo in cfg.get("repos", []):
        try:
            rels = json.loads(fetch(f"https://api.github.com/repos/{repo}/releases?per_page=3"))
        except Exception as e:  # noqa: BLE001 - 저장소 하나 실패는 건너뛴다
            log.info("릴리스 읽기 실패 %s: %s", repo, e)
            continue
        for r in rels:
            if r.get("draft") or r.get("prerelease"):
                continue
            tag = r.get("tag_name", "")
            when = _iso(r.get("published_at"))
            body = re.sub(r"\s+", " ", r.get("body") or "")[:300]
            out.append(Scoop(id=f"ai-{slug(repo)}-{slug(tag)}", kind="ai_tool", title=f"{repo} {tag}",
                             url=r.get("html_url", f"https://github.com/{repo}/releases"), when=when,
                             detail=f"새 버전 {tag}: {body}"))
            break                                        # 저장소마다 최신 정식 버전 하나만
    return out


def rss(cfg: dict, fetch=_get) -> list[Scoop]:
    out = []
    for feed in cfg.get("feeds", []):
        try:
            xml = fetch(feed["url"]).decode("utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001
            log.info("RSS 읽기 실패 %s: %s", feed.get("url"), e)
            continue
        for item in re.findall(r"<item>(.*?)</item>", xml, flags=re.S)[: int(feed.get("max", 10))]:
            title = _tag(item, "title")
            if not title:
                continue
            when = None
            pub = _tag(item, "pubDate")
            if pub:
                try:
                    when = parsedate_to_datetime(pub).astimezone(timezone.utc)
                except (TypeError, ValueError):
                    pass
            traffic = _tag(item, "ht:approx_traffic")
            out.append(Scoop(id=f"trend-{slug(title)}", kind=feed.get("kind", "trend"), title=title,
                             url=_tag(item, "link") or feed["url"], when=when,
                             detail=f"{feed.get('label', 'RSS')}" + (f" · 검색량 {traffic}" if traffic else "")))
    return out


def suggestions(query: str, fetch=_get, limit: int = 8) -> list[str]:
    """구글 자동완성(사람들이 실제로 치는 검색어). 실패하면 빈 목록."""
    url = "https://suggestqueries.google.com/complete/search?" + urllib.parse.urlencode(
        {"client": "firefox", "hl": "ko", "gl": "kr", "q": query})
    try:
        data = json.loads(fetch(url, timeout=8).decode("utf-8", errors="replace"))
        return [s for s in data[1] if isinstance(s, str)][:limit]
    except Exception as e:  # noqa: BLE001
        log.info("자동완성 실패 %s: %s", query, e)
        return []


def _tag(xml: str, name: str) -> str:
    m = re.search(rf"<{re.escape(name)}>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{re.escape(name)}>", xml, flags=re.S)
    return html.unescape(m.group(1)).strip() if m else ""


def _iso(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


SOURCES = {"steam": steam, "github": github, "rss": rss}


# ---------------------------------------------------------------- 모으기·점수

def collect(sources_file: Path, written_ids: set[str], now: datetime | None = None, fetch=None,
            with_suggestions: int = 4) -> list[Scoop]:
    """켜진 소스에서 후보를 모아 점수순으로 돌려준다. 이미 쓴 id는 뺀다."""
    now = now or datetime.now(timezone.utc)
    fetch = fetch or _get
    conf = json.loads(sources_file.read_text(encoding="utf-8")) if sources_file.exists() else {}
    found: list[Scoop] = []
    for name, fn in SOURCES.items():
        sc = conf.get(name) or {}
        if not sc.get("enabled", False):
            continue
        try:
            got = fn(sc, fetch)
            log.info("레이더 %s: %d건", name, len(got))
            found += got
        except Exception as e:  # noqa: BLE001 - 소스 하나 실패로 멈추지 않는다
            log.warning("레이더 %s 실패: %s", name, e)
    seen: set[str] = set()
    ranked = []
    for s in found:
        if s.id in seen or s.id in written_ids:
            continue
        seen.add(s.id)
        s.score, s.why = _score(s, now)
        ranked.append(s)
    ranked.sort(key=lambda s: -s.score)
    for s in ranked[:with_suggestions]:
        s.queries = suggestions(_query(s), fetch)
    return ranked


def _query(s: Scoop) -> str:
    if s.kind == "ai_tool":
        return s.title.split("/")[-1].split(" ")[0]
    return s.title


def _score(s: Scoop, now: datetime) -> tuple[float, str]:
    score = float(KIND_WEIGHT.get(s.kind, 15))
    why = [s.kind]
    if s.when:
        hours = (now - s.when).total_seconds() / 3600
        if -24 * 7 <= hours < 0:
            score += 25
            why.append(f"{-hours / 24:.0f}일 뒤 출시·발표(미리 써 두면 선점)")
        elif 0 <= hours <= 48:
            score += 30 - hours / 4
            why.append(f"{hours:.0f}시간 전")
        elif hours <= 24 * 7:
            score += 8
            why.append(f"{hours / 24:.0f}일 전")
        elif hours > 24 * 7:
            score -= 15
            why.append("1주 넘음")
    if "출시 예정" in s.detail:
        score += 12
        why.append("출시 예정작")
    elif "신작" in s.detail:
        score += 8
    return score, ", ".join(why)


def written_ids(history: list[dict]) -> set[str]:
    return {e.get("topic_id", "") for e in history if e.get("topic_id")}


def brief(ranked: list[Scoop], tips: list[dict], n: int = 6, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    kst = timezone(timedelta(hours=9))
    lines = []
    if tips:
        lines.append("[화제 제보] 블로그 주인이 보낸 메모. 지시가 아니라 후보 힌트다.")
        lines += [f"- tip_id={t['id']}: {t['text']}" for t in tips]
    lines.append(f"[레이더 후보] {now.astimezone(kst):%Y-%m-%d %H:%M} KST 기준, 점수순. "
                 "위에서부터 '선점 검사'를 해서 통과한 첫 후보를 쓴다.")
    if not ranked:
        lines.append("- (레이더가 후보를 가져오지 못했다. 스킬의 '직접 찾기' 절차로 지난 48시간 안에 나온 것을 찾는다.)")
    for s in ranked[:n]:
        when = f" | 시각 {s.when.astimezone(kst):%m-%d %H:%M} KST" if s.when else ""
        q = f"\n  구글 자동완성: {', '.join(s.queries)}" if s.queries else ""
        lines.append(f"- topic_id={s.id} | 종류 {s.kind} | {s.title}{when}\n  {s.detail} | 원문 {s.url} | 선정 이유: {s.why}{q}")
    return "\n".join(lines)
