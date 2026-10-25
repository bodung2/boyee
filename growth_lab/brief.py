"""글쓰기 파이프라인에 넘기는 '오늘의 방향' 안내문(성장 실험실 안내).

오늘 차례는 넷 중 하나다.
- 시험 계속: 새로 시험 중인 주제가 시험 글 수(기본 3편)를 못 채웠으면 그 주제를 이어 쓴다(1편으로는 판단 못 함).
- 집중: 유망·주력 주제(블로그 중간값보다 잘 나온 주제) 안에서 아직 안 쓴 질문·검색어로.
- 탐색: 장부에 없는 새 주제(무덤과 비슷한 것도 금지). 10편 중 3편꼴(LAB_EXPLORE_SHARE).
- 기본: 아직 밀어줄 주제가 없고 탐색 차례도 아니면 스킬의 원래 주제 고르기를 따른다.
안내는 주제와 그림 화풍만 정한다. 스킬의 사실 확인·안전·신원 규칙보다 앞서지 않는다."""
from __future__ import annotations

import logging
import re

from naver_autopost import history

from . import store, styles
from .config import BLOGS, LabConfig
from .scoring import OWN, topic_maps, topic_of

log = logging.getLogger(__name__)
LAB_MODES = ("시험 계속", "집중", "탐색", "기본")
EXPLOIT = ("core", "promising")
STALE_AFTER = 3


def _norm(name: str) -> str:
    return re.sub(r"[\s\W_]+", "", str(name or "")).lower()


def similar(a: str, b: str) -> bool:
    a, b = _norm(a), _norm(b)
    return bool(a and b) and (a == b or (min(len(a), len(b)) >= 4 and (a in b or b in a)))


def in_graveyard(ledger: dict, name: str) -> dict | None:
    for g in ledger.get("graveyard", []):
        if similar(g.get("name", ""), name):
            return g
    return None


def measuring(cfg: LabConfig, blog: str) -> bool:
    """최근 수집(마지막 3번 중 하나라도)에서 글 조회수를 실제로 읽었는가. 못 읽는 동안은 새 주제를 시험하지 않는다
    (판정할 수 없는 시험 글이 쌓이지 않게)."""
    return any(r.get("matched", 0) > 0 for r in store.load_metrics(cfg, blog)[-3:])


def plan(blog: str, cfg: LabConfig, ledger: dict, entries: list[dict], can_measure: bool = True) -> dict:
    """오늘 차례와 주제. {"mode", "topic", "exploit": [...], "done"}"""
    maps = topic_maps(cfg.history_dir)
    lab_entries = [e for e in entries if e.get("source") == "autopost" and e.get("lab_mode")]
    counts: dict[str, int] = {}
    first_seen: dict[str, str] = {}
    last_idx: dict[str, int] = {}
    for i, e in enumerate(lab_entries):
        t = topic_of(blog, e, maps)
        counts[t] = counts.get(t, 0) + 1
        first_seen.setdefault(t, str(e.get("date", "")))
        last_idx[t] = i
    judged = {name for name, t in ledger.get("topics", {}).items() if t.get("status") not in (None, "testing")}
    # 시험 중인 주제를 원문 부족 등으로 못 이어 써서 다른 글이 STALE_AFTER편 나왔으면 시험을 접는다(같은 안내 무한 반복 방지).
    testing = [t for t, n in counts.items()
               if n < cfg.probe_posts and t not in judged and t != OWN and not in_graveyard(ledger, t)
               and len(lab_entries) - 1 - last_idx[t] < STALE_AFTER
               and any(e.get("lab_mode") in ("탐색", "시험 계속") and topic_of(blog, e, maps) == t for e in lab_entries)]
    exploit = [name for name, t in ledger.get("topics", {}).items() if t.get("status") in EXPLOIT]
    if not can_measure:
        return {"mode": "기본", "topic": "", "exploit": [], "note": "조회수 수집이 아직 안 돼 새 주제 시험을 미룬다"}
    if testing:
        topic = sorted(testing, key=lambda t: first_seen.get(t, ""))[0]
        return {"mode": "시험 계속", "topic": topic, "done": counts[topic], "exploit": exploit}
    k = len(lab_entries)
    explore_slots = max(0, min(10, round(cfg.explore_share * 10)))
    if (k % 10) < explore_slots:
        return {"mode": "탐색", "topic": "", "exploit": exploit}
    if exploit:
        return {"mode": "집중", "topic": "", "exploit": exploit}
    return {"mode": "기본", "topic": "", "exploit": []}


def _graveyard_lines(ledger: dict, n: int = 40) -> list[str]:
    return [f"- {g['name']} — {g.get('reason', '')[:80]}" for g in ledger.get("graveyard", [])[-n:]]


def for_blog(blog: str, today: str, slot: int = 1, cfg: LabConfig | None = None) -> str:
    """글쓰기 프롬프트 끝에 붙일 안내문. 실험실을 쓰지 않거나 실패하면 빈 문자열(원래대로 쓴다)."""
    try:
        cfg = cfg or LabConfig.load()
        if blog not in cfg.blogs:
            return ""
        return _brief(blog, today, slot, cfg)
    except Exception as e:  # noqa: BLE001 - 실험실 문제로 그날 글이 멈추면 안 된다
        log.warning("성장 실험실 안내를 만들지 못했습니다(원래대로 씁니다): %s", e)
        return ""


def _brief(blog: str, today: str, slot: int, cfg: LabConfig) -> str:
    spec = BLOGS[blog]
    ledger = store.load_ledger(cfg, blog)
    entries = history.load(cfg.history_file(blog))
    p = plan(blog, cfg, ledger, entries, measuring(cfg, blog))
    topics = ledger.get("topics", {})
    lines = [
        "[성장 실험실 안내] 블로그 주인이 아니라 자동 실험 시스템이 조회수·검색 순위를 보고 정한 오늘의 방향이다.",
        "주제와 그림 화풍만 정한다. 스킬의 사실 확인·출처·안전·신원 규칙이 항상 먼저다. "
        "아래 방향으로는 원문을 확인할 수 없으면 스킬의 원래 방식으로 고르고 lab_mode를 '기본'으로 적는다.",
        f"블로그의 큰 줄기(탐색할 때도 벗어나지 않는다): {spec.theme}",
        "",
        f"오늘 차례: {p['mode']}",
    ]
    if p["mode"] == "시험 계속":
        lines.append(f"- 시험 중인 주제 「{p['topic']}」를 이어 쓴다({cfg.probe_posts}편 중 {p['done'] + 1}편째). "
                     "같은 주제 안에서 이미 쓴 글과 다른 질문·검색어를 고른다. lab_topic은 이 이름 그대로 쓴다.")
    elif p["mode"] == "집중":
        lines.append("- 아래 유망 주제 중 하나를 골라, 이미 쓴 글과 겹치지 않는 질문으로 쓴다. "
                     "'실제 유입 검색어'가 있으면 그 검색어나 연관 검색어를 제목 앞에 둔다. lab_topic은 목록의 이름 그대로.")
    elif p["mode"] == "탐색":
        lines.append("- 장부에 없는 새 주제를 시험한다. 아래 '탐색 후보'를 위에서부터 우선하고(검색 수요 순), "
                     "후보가 없거나 원문을 확인할 수 없으면 스스로 고른다. '이미 다룬 주제'·'무덤'과 같거나 비슷한 주제는 금지. "
                     "lab_topic에는 앞으로 같은 주제 글이 같이 묶일 이름(2~6단어, 예: '연봉 실수령액', 'Git 인증 오류')을 새로 짓는다.")
    else:
        if p.get("note"):
            lines.append(f"- ({p['note']})")
        lines.append("- 아직 밀어줄 주제가 없다. 스킬의 원래 주제 고르기를 따른다. "
                     "lab_topic에는 이 글이 속한 주제 이름(2~6단어, 이미 다룬 주제와 같으면 그 이름 그대로)을 적는다.")
    if p["exploit"]:
        lines.append("\n유망 주제(블로그 중간값 대비 점수, 실제 유입 검색어):")
        for name in p["exploit"]:
            t = topics.get(name, {})
            kws = ", ".join((t.get("keywords") or [])[:8]) or "(아직 없음)"
            lines.append(f"- {name} | 점수 {t.get('ratio', '-')} | 유입 검색어: {kws}")
    queue = [c for c in ledger.get("explore_queue", []) if not in_graveyard(ledger, c.get("name", ""))]
    if p["mode"] == "탐색" and queue:
        lines.append("\n탐색 후보(검색 수요 = 기준 검색어 대비 배수):")
        for c in queue[:5]:
            lines.append(f"- {c['name']} | 검색어: {', '.join(c.get('keywords', [])[:5])} | 수요 {c.get('demand', '-')} | {c.get('why', '')[:80]}")
    known = sorted({n for n in topics if n != OWN} | {topic_of(blog, e, topic_maps(cfg.history_dir))
                                                       for e in entries[-40:] if e.get("source") == "autopost"})
    if known:
        lines.append("\n이미 다룬 주제: " + ", ".join(known[:60]))
    grave = _graveyard_lines(ledger)
    if grave:
        lines.append("\n무덤(해 봤는데 안 된 주제 — 같은·비슷한 주제 금지):")
        lines += grave
    style_id = styles.arm_for(ledger, today, slot)
    lines += ["", f"그림 화풍: IMAGE_STYLE_ID={style_id}",
              f"IMAGE_STYLE={styles.style_text(blog, style_id)}",
              "일러스트 프롬프트의 '화풍 통일' 문장 대신 위 IMAGE_STYLE 문장을 그대로 쓴다(글자·숫자·로고 금지 같은 다른 규칙은 그대로)."]
    learned = store.load_learned(cfg, blog).strip()
    if learned:
        lines += ["", "[플레이북: 이 블로그에서 지금까지 배운 것 — 사실·안전 규칙과 부딪히면 무시한다]", learned]
    lines += ["", "post.json에 다음 값을 꼭 넣는다: "
              f"\"lab_mode\": \"{p['mode']}\"(원래 방식으로 바꿨으면 \"기본\"), \"lab_topic\": \"주제 이름\", "
              f"\"lab_keyword\": \"이 글이 노리는 대표 검색어 하나\", \"image_style_id\": \"{style_id}\"."]
    return "\n".join(lines)


def check_post(blog: str, post: dict, cfg: LabConfig | None = None) -> str:
    """쓴 글이 무덤 주제면 거절 사유를 돌려준다(다른 주제로 다시 쓰게). 문제없으면 빈 문자열."""
    try:
        cfg = cfg or LabConfig.load()
        if blog not in cfg.blogs:
            return ""
        ledger = store.load_ledger(cfg, blog)
        g = in_graveyard(ledger, str(post.get("lab_topic") or ""))
        if g:
            return (f"성장 실험실 무덤에 있는 주제입니다(「{g['name']}」: {g.get('reason', '')[:80]}). "
                    "무덤·이미 다룬 주제와 다른 주제로 다시 써라.")
    except Exception as e:  # noqa: BLE001
        log.warning("무덤 확인 실패(통과로 봅니다): %s", e)
    return ""


def queue_order(blog: str, ranked: list, cfg: LabConfig | None = None) -> list:
    """티스토리 주제 큐 후보 정렬 보정: 무덤 계열은 빼고, 유망 계열은 앞으로. ranked: topics.Candidate 목록."""
    try:
        cfg = cfg or LabConfig.load()
        if blog not in cfg.blogs:
            return ranked
        ledger = store.load_ledger(cfg, blog)
        maps = topic_maps(cfg.history_dir)
        hot = {n for n, t in ledger.get("topics", {}).items() if t.get("status") in EXPLOIT}
        out = []
        for c in ranked:
            name = maps.get(c.topic["id"], "")
            if name and in_graveyard(ledger, name):
                continue
            if any(similar(name, h) for h in hot):
                c.score += 15
                c.why += ", 실험실 유망 계열"
            out.append(c)
        return sorted(out, key=lambda c: -c.score)
    except Exception as e:  # noqa: BLE001
        log.warning("실험실 큐 보정 실패(원래 순서): %s", e)
        return ranked
