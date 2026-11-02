"""공개용 화면(GitHub Pages): 매수 권유로 읽힐 수 있는 것(규칙상 편입·목표 비중·살 상품·전략 백테스트)을 데이터에서 빼고,
상태 표시는 '지금 어떤 상태인지'만 말하는 말로 바꾼다. 집 PC에서 보는 화면·텔레그램 요약은 그대로(공개용만 이 함수를 거친다).
"""
from __future__ import annotations

import copy
import re

QUAD_TEXT = {"주도": "강하고 강해지는 중", "둔화": "강하지만 약해지는 중", "회복": "약하지만 좋아지는 중",
             "회피": "약하고 약해지는 중"}
STOCK_TEXT = {"후보": "추세 강함", "관찰(추세 약함)": "추세 약함"}


def assets(d: dict) -> dict:
    d = copy.deepcopy(d)
    for a in d.get("assets", []):
        for k in ("weight",):
            a[k] = 0
        a["held"] = False
        a["why"] = ""
        a["eligible"] = False
        a["status"] = QUAD_TEXT.get(a.get("quadrant"), a.get("quadrant") or "")
    names = {"편입 조건 충족": "추세 0.5 초과·200일선 위", "미충족": "그 밖"}
    for row in (d.get("analysis") or {}).get("eligible") or []:
        row["bucket"] = names.get(row.get("bucket"), row.get("bucket"))
    d["frame_weights"] = []
    d["products"] = {}
    d["backtest"] = None
    d["next_rebalance"] = None
    d["public"] = True
    return d


def sectors(d: dict) -> dict:
    d = copy.deepcopy(d)
    for c in d.get("countries", []):
        c["backtest"] = None
        for s in c.get("sectors", []):
            s["weight"] = 0
            s["status"] = QUAD_TEXT.get(s.get("quadrant"), s.get("quadrant") or "")
            for r in s.get("stocks", []):
                r["status"] = STOCK_TEXT.get(r.get("status"), r.get("status"))
    d["public"] = True
    return d


def kr(d: dict) -> dict:
    d = copy.deepcopy(d)
    d["public"] = True
    return d


_PRIVATE = re.compile(r"<!--private-->.*?<!--/private-->", re.S)


def strip_private(html: str, public: bool) -> str:
    """<!--private-->…<!--/private--> 구간은 공개 화면에서 지운다(표시만 지우면 안 되는 곳)."""
    return _PRIVATE.sub("", html) if public else html.replace("<!--private-->", "").replace("<!--/private-->", "")
