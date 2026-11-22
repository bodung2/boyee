"""검색 수요 확인(쓰기 전 거르기): 네이버 데이터랩 검색어 트렌드 API로 후보 주제의 검색량을 기준 검색어와 비교한다.

데이터랩은 절대 검색량이 아니라 '한 요청 안에서 가장 많은 것 = 100'인 상대값만 준다. 그래서 블로그마다 꾸준히
검색되는 기준 검색어(anchor)를 한 묶음에 같이 넣고, 후보 ÷ 기준 비율로 비교한다(1.0 = 기준만큼 찾는다).
네이버 개발자센터 애플리케이션의 사용 API에 '데이터랩(검색어트렌드)'을 추가해야 한다(이웃 추천과 같은 키)."""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

log = logging.getLogger(__name__)
API = "https://openapi.naver.com/v1/datalab/search"
ANCHORS = {"invest": "연봉 실수령액", "tistory": "파이썬 오류"}


def anchor_for(blog: str) -> str:
    return (os.environ.get(f"LAB_DEMAND_ANCHOR_{blog.upper()}") or ANCHORS.get(blog, "")).strip()


def _post(body: dict, client_id: str, client_secret: str) -> dict:
    req = urllib.request.Request(API, data=json.dumps(body).encode(), method="POST", headers={
        "X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def compare(candidates: dict[str, list[str]], anchor: str, client_id: str, client_secret: str,
            today: date | None = None, post=None) -> dict[str, float | None] | dict[str, str]:
    """{후보 이름: 기준 대비 최근 3달 평균 검색량 비율}. 키가 없거나 권한이 없으면 {"_error": 이유}."""
    if not (client_id and client_secret):
        return {"_error": "꺼짐(네이버 검색 API 키 없음 — 2026-07부터 개발자센터 신규 발급 중단, 필요하면 NAVER API HUB)"}
    if not anchor:
        return {"_error": "기준 검색어가 없습니다"}
    today = today or date.today()
    start = (today - timedelta(days=95)).replace(day=1)
    out: dict = {}
    names = [n for n, kws in candidates.items() if kws]
    for i in range(0, len(names), 4):                       # 한 요청에 묶음 5개까지: 기준 + 후보 4개
        chunk = names[i:i + 4]
        body = {"startDate": start.isoformat(), "endDate": today.isoformat(), "timeUnit": "month",
                "keywordGroups": [{"groupName": "__anchor__", "keywords": [anchor]}]
                + [{"groupName": n[:50], "keywords": [k[:50] for k in candidates[n][:20]]} for n in chunk]}
        try:
            res = (post or _post)(body, client_id, client_secret)
        except urllib.error.HTTPError as e:
            return {"_error": f"데이터랩 HTTP {e.code}(개발자센터 앱에 '데이터랩(검색어트렌드)' 추가 필요할 수 있음)"}
        except Exception as e:  # noqa: BLE001
            return {"_error": f"데이터랩 호출 실패: {e}"[:200]}
        means = {}
        for r in res.get("results", []):
            vals = [d.get("ratio", 0) for d in r.get("data", [])][-3:]
            means[r.get("title")] = sum(vals) / len(vals) if vals else 0.0
        base = means.get("__anchor__") or 0.0
        for n in chunk:
            v = means.get(n[:50])
            out[n] = round(v / base, 2) if (base and v is not None) else (0.0 if v == 0 else None)
    return out


# ---- API 키 없이: 자동완성으로 수요 대신 재기(2026-11-22) ----
# 네이버 데이터랩 키를 새로 받을 수 없어 후보의 수요가 늘 비어 있었다. 사람들이 실제로 치는 검색어면 네이버·구글 자동완성에
# 그 말로 시작하는 검색어가 여럿 뜬다. 검색어마다 '그 말로 시작하는 자동완성 개수(최대 10)'를 세어 0~1로 바꾸고 평균낸다.
# 절대 검색량은 아니지만 '아무도 안 찾는 말'(자동완성 0개)은 확실히 걸러진다.
NAVER_AC = "https://ac.search.naver.com/nx/ac"
GOOGLE_AC = "https://suggestqueries.google.com/complete/search"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"


def _get(url: str, timeout: int = 8) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def suggestions(keyword: str, fetch=None) -> list[str] | None:
    """네이버·구글 자동완성 검색어(합쳐서). 둘 다 실패하면(인터넷 문제 등) None — 수요 0으로 오해하지 않게."""
    fetch = fetch or _get
    out: list[str] = []
    ok = 0
    try:
        data = json.loads(fetch(NAVER_AC + "?" + urllib.parse.urlencode(
            {"q": keyword, "con": 1, "frm": "nv", "ans": 2, "r_format": "json", "r_enc": "UTF-8", "r_unicode": 0,
             "t_koreng": 1, "run": 2, "rev": 4, "q_enc": "UTF-8", "st": 100})).decode("utf-8", "replace"))
        for group in data.get("items") or []:
            out += [str(item[0]) for item in group if isinstance(item, list) and item]
        ok += 1
    except Exception as e:  # noqa: BLE001
        log.info("네이버 자동완성 실패 %s: %s", keyword, e)
    try:
        data = json.loads(fetch(GOOGLE_AC + "?" + urllib.parse.urlencode(
            {"client": "firefox", "hl": "ko", "gl": "kr", "q": keyword})).decode("utf-8", "replace"))
        out += [str(x) for x in data[1]]
        ok += 1
    except Exception as e:  # noqa: BLE001
        log.info("구글 자동완성 실패 %s: %s", keyword, e)
    return out if ok else None


def _squash(text: str) -> str:
    return "".join(str(text).split()).lower()


def suggest_score(keywords: list[str], fetch=None) -> float | None:
    """검색어들의 자동완성 수요(0~1). 검색어마다 그 말로 시작하는 자동완성 수 ÷ 10(최대 1)의 평균.
    자동완성을 하나도 못 받았으면 None(모름)."""
    vals = []
    for kw in [k for k in keywords if k.strip()][:5]:
        got = suggestions(kw, fetch)
        if got is None:
            continue
        head = _squash(kw)
        hits = {_squash(s) for s in got if _squash(s).startswith(head)}
        vals.append(min(1.0, len(hits) / 10))
    return round(sum(vals) / len(vals), 2) if vals else None


def compare_by_suggest(candidates: dict[str, list[str]], fetch=None) -> dict[str, float | None]:
    return {name: suggest_score(kws, fetch) for name, kws in candidates.items() if kws}
