"""통계 화면 진단: 수집기가 조회수를 못 찾을 때 화면이 어떤 데이터를 받아 오는지 '구조만' 저장한다.

저장소가 공개라서 값(제목·닉네임·숫자 원본)은 올리지 않는다. 응답 주소의 경로, 필드 이름과 값의 종류,
우리 글이 매칭됐는지(예/아니오)만 diagnostics/growth/<블로그>/에 남긴다. 스크린샷과 원본은 집 PC의 output/lab/에만."""
from __future__ import annotations

import json
import re
import urllib.parse
from pathlib import Path

from naver_autopost import history

from . import rank, stats
from .config import BLOGS, LabConfig
from .metrics import blog_ident, capture, _platform_cfg


def shape(obj, depth: int = 0, max_depth: int = 6):
    """값을 지우고 구조만: 문자열 → "str", 숫자 → "int"/"float", 목록은 첫 항목 구조 + 개수."""
    if depth > max_depth:
        return "…"
    if isinstance(obj, dict):
        # 날짜·검색어·제목이 키인 표(값이 키에 들어 있음)는 키를 지운다
        if obj and not all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,39}", str(k)) for k in obj):
            return {"__map__": len(obj), "value": shape(next(iter(obj.values())), depth + 1)}
        return {str(k): shape(v, depth + 1) for k, v in list(obj.items())[:40]}
    if isinstance(obj, list):
        return {"__list__": len(obj), "item": shape(obj[0], depth + 1)} if obj else []
    if isinstance(obj, bool):
        return "bool"
    if isinstance(obj, int):
        return "int"
    if isinstance(obj, float):
        return "float"
    if obj is None:
        return "null"
    return "str"


def _path_only(url: str, ident: str) -> str:
    url = url.replace(ident, "<BLOG>") if ident else url
    url = re.sub(r"/[^/]*(%[0-9A-Fa-f]{2}|[^\x00-\x7f])[^/]*", "/<x>", url)   # 한글·인코딩된 경로 조각
    return re.sub(r"/\d{5,}", "/<N>", url)


def _query_shape(query: str) -> dict[str, str]:
    """요청 매개변수의 이름과 값 '모양'만: 영문 대문자 상수(DATE 등)는 그대로, 나머지는 숫자→9·글자→a."""
    out = {}
    for k, v in urllib.parse.parse_qsl(query, keep_blank_values=True)[:20]:
        out[k[:30]] = v if re.fullmatch(r"[A-Z_]{1,20}", v) else re.sub(r"[^\W\d_]", "a", re.sub(r"\d", "9", v))[:30]
    return out


_UI_WORDS = ("계정", "로그인", "계속", "비밀번호", "간편", "다른", "추가", "확인", "선택", "카카오", "취소", "다음",
             "아이디", "이메일", "전화번호", "인증", "유지", "저장", "<계정>")


def _ui_only(text: str) -> str:
    """화면 글자에서 UI 단어(로그인·계정 등)만 남기고 나머지 단어(이름 등)는 가린다. 공개 저장소에 올라가므로."""
    out = []
    for tok in str(text or "").split():
        out.append(tok if any(w in tok for w in _UI_WORDS) else re.sub(r"[^\W\d_]", "x", tok))
    return " ".join(out)


def _search_page(blog: str, entries: list[dict], local: Path, ident: str) -> dict:
    """가장 최근 글 하나로 검색 결과 화면을 불러, 순위를 읽었는지와 화면 구조를 남긴다."""
    recent = [e for e in entries if rank.keyword_for(e)][-1:]
    if not recent:
        return {"skipped": "검색어가 있는 글이 없음"}
    e = recent[0]
    platform = BLOGS[blog].platform
    try:
        with rank.page_fetcher(platform) as get:
            got = rank.page_rank(rank.keyword_for(e), e["url"], platform, get, debug_dir=local)
        return {"ok": True, "found_rank": {k: v for k, v in got.items() if k != "query"}}
    except Exception as err:  # noqa: BLE001
        path = local / f"search_{platform}.html"
        out = {"ok": False, "error": str(err)[:200]}
        if path.exists():
            out["shape"] = rank.page_shape(path.read_text(encoding="utf-8"), [ident])
        return out


def run(blog: str, cfg: LabConfig, today: str) -> Path:
    pcfg = _platform_cfg(blog)
    ident = blog_ident(pcfg)
    local = cfg.output_dir / blog / f"diagnose-{today}"
    local.mkdir(parents=True, exist_ok=True)
    cap = capture(blog, cfg, pcfg, shots=local, today=today)
    stats.save_capture(cap, local, {ident: "<BLOG>"} if ident else None, max_json=5_000_000)
    entries = [e for e in history.load(cfg.history_file(blog)) if e.get("url")]
    matched = stats.match_posts(cap, entries)
    report = {
        "date": today, "blog": blog, "logged_in": cap.logged_in,
        "errors": [_path_only(e, ident) for e in cap.errors],
        "pages": [{"url": _path_only(p["url"], ident), "nav": p.get("nav", ""), "text_lines": len(p.get("text", "").splitlines()),
                   "has_numbers": bool(re.search(r"\d", p.get("text", "")))} for p in cap.pages],
        "responses": [{"url": _path_only(r.get("url", ""), ident), "query": _query_shape(r.get("query") or ""),
                       "shape": shape(r.get("json"))}
                      for r in cap.responses[:80]],
        "posts_known": len(entries), "posts_matched": len(matched),
        "daily_days": len(cap.daily), "daily_posts_matched": len(stats.daily_views(cap, entries)),
        "matched_fields": sorted({c["field"] for m in matched.values() for c in m["candidates"]}),
    }
    report["search_page"] = _search_page(blog, entries, local, ident)
    login = pcfg.output_dir / "login_failed.json" if hasattr(pcfg, "output_dir") else None
    if not cap.logged_in and login and login.exists():
        page = json.loads(login.read_text(encoding="utf-8"))
        page["title"] = _ui_only(page.get("title", ""))
        page["items"] = [{**i, "text": _ui_only(i.get("text", ""))} for i in page.get("items", [])]
        report["login_page"] = page
    out = cfg.diagnostics_dir / blog / "stat_structure.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return out
