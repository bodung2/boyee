"""검색 수요 확인(쓰기 전 거르기): 네이버 데이터랩 검색어 트렌드 API로 후보 주제의 검색량을 기준 검색어와 비교한다.

데이터랩은 절대 검색량이 아니라 '한 요청 안에서 가장 많은 것 = 100'인 상대값만 준다. 그래서 블로그마다 꾸준히
검색되는 기준 검색어(anchor)를 한 묶음에 같이 넣고, 후보 ÷ 기준 비율로 비교한다(1.0 = 기준만큼 찾는다).
네이버 개발자센터 애플리케이션의 사용 API에 '데이터랩(검색어트렌드)'을 추가해야 한다(이웃 추천과 같은 키)."""
from __future__ import annotations

import json
import logging
import os
import urllib.error
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
        return {"_error": "NAVER_SEARCH_CLIENT_ID/SECRET이 없습니다"}
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
