"""구글 블로거 2편째(--slot trend): '한국의 최신 트렌드' 특화 글.

1편째(03:00)는 스킬이 고르는 기존 주제(한국 생활 설명), 2편째는 지난 7일 안에 한국에서 화제가 된 것 중
영어권 독자(한국에 사는·올 외국인)가 찾아볼 만한 것을 쓴다. 구글 트렌드 한국 급상승 검색어를 후보로 넘기지만,
글쓰기(Codex)가 웹 검색으로 더 맞는 화제를 찾으면 그것을 써도 된다.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)
DEFAULT_FEEDS = ["https://trends.google.com/trending/rss?geo=KR"]
# 블로그 성격에 맞지 않는 화제(정치·사건사고·인물 논란·건강 주장·투자 권유)는 후보에서 뺀다
AVOID = re.compile(r"대통령|국회|의원|선거|정당|탄핵|검찰|재판|구속|사망|숨진|사고|화재|살인|폭행|성범죄|"
                   r"열애|이혼|논란|폭로|주가|코인|비트코인|급등|급락", re.I)
SLOT = "trend"

FOCUS = """
FOCUS FOR THIS POST — "Korea right now" (the blog's second daily post):
- Write about something that has been trending in South Korea within the last 7 days and that English-speaking
  readers (foreigners living in, moving to or visiting Korea) would actually search for: a new rule or price that
  just took effect, a seasonal event or festival, a viral food/product/place, a new public service or app,
  a K-culture moment with practical meaning, weather/holiday-related changes.
- Explain what it is, why it is in the news now, what it means for a foreigner, and the practical details
  (dates, prices, where, how to apply/book). Put the month/year or "{today}" context in the title when it helps.
- Do NOT write about politics or elections, crimes, accidents or their victims, celebrity dating/scandals or
  rumors, medical/health claims, or stock/crypto moves. Never present rumors as facts.
- Use recent, reliable sources (official sites, major outlets) dated within the last 2 weeks for the "what's new"
  part, and say "as of {today}" for anything that may change. Do not repeat a topic already published.
- Keep every other rule of the skill (structure, sources, images, tone).
{candidates}"""


def candidates(feeds: list[str] | None = None, fetch=None, limit: int = 12) -> list[str]:
    """구글 트렌드 한국 급상승 검색어(맞지 않는 화제는 뺀다). 실패하면 빈 목록."""
    try:
        from tistory_autopost import radar
        kw = {"fetch": fetch} if fetch else {}
        items = radar.rss({"feeds": [{"url": u, "max": 25, "label": "구글 트렌드 한국"} for u in (feeds or DEFAULT_FEEDS)]},
                          **kw)
    except Exception as e:  # noqa: BLE001 - 후보가 없으면 글쓰기가 웹 검색으로 직접 찾는다
        log.info("트렌드 후보를 못 읽었습니다: %s", e)
        return []
    out = []
    for s in items:
        if AVOID.search(s.title) or s.title in out:
            continue
        out.append(s.title + (f" ({s.detail.split('·', 1)[-1].strip()})" if "검색량" in s.detail else ""))
    return out[:limit]


def focus(today: str, feeds: list[str] | None = None, fetch=None) -> str:
    found = candidates(feeds, fetch)
    lines = ("\nTrending searches in Korea today (Google Trends; many will be unsuitable — pick one only if it fits "
             "the rules above, otherwise find a better current topic with web search):\n"
             + "\n".join(f"- {c}" for c in found)) if found else ""
    return FOCUS.format(today=today, candidates=lines)
