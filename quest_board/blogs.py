"""퀘스트 보드의 '자동화 블로그 분석' 칸: 블로그마다 지금 상태와 추진 중인 개선을 한 장의 카드로 보여 준다.

읽기만 한다. 재료는 집 PC에만 있는 파일들이다(GitHub에 올라가지 않음).
- 발행 이력 data/published_*.json
- 성장 실험실 data/lab/: daily_<블로그>.json(일별 글 조회수), ledger_<블로그>.json(주제 장부), learned_<블로그>.md(확정 규칙)
- 마지막 주간 리뷰 output/lab/<블로그>/review-*/review.json
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html import escape
from pathlib import Path

from .checks import Paths
from .schedule import ROOT

NOTES_DIR = ROOT / "diagnostics" / "notes"     # Claude가 대화에서 쓴 블로그별 분석(저장소에 올라감 — 글 제목·주소 없이)

log = logging.getLogger(__name__)

# (키, 이름, 발행 이력 파일, 한 줄 설명)
BLOGS = [
    ("invest", "네이버 투자", "published_invest.json", "돈·생활 질문을 공식 숫자로"),
    ("tistory", "티스토리", "published_tistory.json", "방금 나온 것을 먼저 정리하는 선점형"),
    ("edu", "네이버 교육", "published_edu.json", "매일 글: 교육 정책·학부모 교육정보(A·C·D·E)"),
    ("edu_series", "교육 · 저경력 교사 필수 시리즈", "published_edu_series.json", "교직 실무 시리즈(월·수·금, 교육 블로그)"),
    ("childhood", "네이버 유아", "published_childhood.json", "유아교육 정보"),
    ("market", "네이버 시황", "published_market.json", "평일 매일 시황(투자 블로그)"),
    ("place", "아이와 가볼 곳", "published_place.json", "직접 다녀온 장소(유아 블로그)"),
    ("blogger", "구글 블로거", "published_blogger.json", "영어 글"),
]
WINDOW = 14            # 최근 조회 비교 기간(일)
SPARK_DAYS = 28
STATUS_KO = {"testing": "시험 중", "promising": "유망", "core": "주력", "neutral": "보통", "saturated": "포화",
             "dead": "무덤", "hold": "보류"}
STAGE_KO = {"색인": "구글 색인에 아직 거의 안 들어감", "수요": "찾는 사람이 적은 검색어", "노출": "검색에 잘 안 보임", "클릭": "보이는데 안 누름",
            "읽기": "들어와서 금방 나감", "채널": "블로그 유입 자체가 적음", "데이터 부족": "아직 판단할 데이터가 모자람"}


@dataclass
class Card:
    key: str
    name: str
    desc: str
    mode: str = "off"                  # lab 실험실 운영 / watch 조회수만 수집 / off 실험실 밖
    today: int = 0
    week: int = 0
    last: str = "-"
    views: int | None = None           # 최근 WINDOW일 조회
    prev: int | None = None            # 그 전 WINDOW일 조회
    spark: list[tuple[str, int | None]] = field(default_factory=list)
    days_collected: int = 0
    stage: str = ""
    evidence: str = ""
    report: str = ""
    review_date: str = ""
    promising: list[str] = field(default_factory=list)
    testing: int = 0
    graveyard: list[str] = field(default_factory=list)
    rules: list[tuple[str, str]] = field(default_factory=list)    # (적용일, 규칙)
    changes: list[tuple[str, str]] = field(default_factory=list)  # (날짜, 무엇을)
    experiment: str = ""
    explore: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    top_posts: list[tuple[str, str, int]] = field(default_factory=list)   # (제목, 주소, 최근 조회)
    login: str = ""
    index: dict = field(default_factory=dict)       # 구글 블로거 색인 감시 마지막 요약
    index_first: dict = field(default_factory=dict)  # 색인 감시 첫날 요약(변화 비교용)
    note_date: str = ""
    note_html: str = ""
    titles: dict = field(default_factory=dict)       # 글 주소 → 제목(검색에 나온 글 표시용)
    error: str = ""


def _json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _entries(path: Path) -> list[dict]:
    data = _json(path, [])
    if isinstance(data, dict):
        data = data.get("posts") or data.get("entries") or []
    return [e for e in data if isinstance(e, dict) and e.get("url")]


def _key(url: str) -> str:
    return (url or "").split("?")[0].split("#")[0].rstrip("/")


def _lab_modes() -> tuple[list[str], list[str], list[str]]:
    """(실험실 운영 블로그, 조회수만 모으는 블로그, 제안 자동 적용 블로그)."""
    try:
        from growth_lab.config import LabConfig
        cfg = LabConfig.load()
        return [b for b in cfg.blogs if b not in cfg.watch_only], cfg.watch_only, cfg.auto_decide
    except Exception as e:  # noqa: BLE001
        log.warning("실험실 설정을 읽지 못했습니다: %s", e)
        return [], [], []


def _views(card: Card, lab: Path, entries: list[dict], now: datetime) -> None:
    daily = _json(lab / f"daily_{card.key}.json", {})
    fetched = set(daily.get("fetched") or [])
    posts = daily.get("posts") or {}
    card.days_collected = len(fetched)
    if not fetched:
        return
    per_day: dict[str, int] = {}
    for by_day in posts.values():
        for d, v in by_day.items():
            per_day[d] = per_day.get(d, 0) + int(v or 0)
    days = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, 2 * WINDOW + 1)]
    recent, before = days[:WINDOW], days[WINDOW:]
    if sum(d in fetched for d in recent) >= WINDOW // 2:
        card.views = sum(per_day.get(d, 0) for d in recent if d in fetched)
    if sum(d in fetched for d in before) >= WINDOW // 2:
        card.prev = sum(per_day.get(d, 0) for d in before if d in fetched)
    card.spark = [(d, per_day.get(d, 0) if d in fetched else None)
                  for d in reversed([(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, SPARK_DAYS + 1)])]
    titles = {_key(e["url"]): (e.get("title") or "", e["url"]) for e in entries}
    top = []
    for k, by_day in posts.items():
        if k not in titles:
            continue
        n = sum(int(v or 0) for d, v in by_day.items() if d in recent)
        if n:
            top.append((titles[k][0], titles[k][1], n))
    card.top_posts = sorted(top, key=lambda t: -t[2])[:3]


def _ledger(card: Card, lab: Path) -> None:
    led = _json(lab / f"ledger_{card.key}.json", {})
    topics = led.get("topics") or {}
    ranked = sorted(topics.items(), key=lambda x: -(x[1].get("ratio") or 0))
    card.promising = [f"{n} ({t.get('ratio')})" for n, t in ranked if t.get("status") in ("promising", "core")][:4]
    card.testing = sum(1 for t in topics.values() if t.get("status") == "testing")
    card.graveyard = [g.get("name", "") for g in led.get("graveyard") or []][-4:]
    card.explore = [c.get("name", "") for c in (led.get("explore_queue") or [])[:3]]
    exp = led.get("experiment")
    if exp:
        card.experiment = f"그림 스타일 {exp['arms'][0]} vs {exp['arms'][1]} — " + (
            "번갈아 쓰는 중" if exp.get("status") == "running" else "조회수 모으는 중")
    try:
        from growth_lab.review import PREFIX
        pre = PREFIX.get(card.key, "")
    except Exception:  # noqa: BLE001
        pre = ""
    card.pending = [f"{pre}{p['id']} {p['text']}" for p in led.get("proposals") or [] if p.get("status") == "pending"]
    card.changes = [(c.get("date", ""), c.get("what", "")) for c in (led.get("changelog") or [])[-4:]][::-1]
    text = ""
    try:
        text = (lab / f"learned_{card.key}.md").read_text(encoding="utf-8")
    except OSError:
        pass
    i = text.find("## 확정 규칙")
    if i >= 0:
        for line in text[i:].splitlines()[1:]:
            if line.startswith("## "):
                break
            if line.startswith("- "):
                body = line[2:].strip()
                date = body[1:11] if body.startswith("(") else ""
                card.rules.append((date, body[13:].strip() if date else body))


def _review(card: Card, output: Path) -> None:
    reviews = sorted((output / "lab" / card.key).glob("review-*/review.json"))
    if not reviews:
        return
    r = _json(reviews[-1], {})
    card.review_date = reviews[-1].parent.name.removeprefix("review-")
    funnel = r.get("funnel") or {}
    card.stage = str(funnel.get("stage") or "")
    card.evidence = str(funnel.get("evidence") or "")[:220]
    card.report = str(r.get("report") or "")[:400]


def _login(data: Path) -> str:
    try:
        from types import SimpleNamespace

        from tistory_autopost import login_log
        cfg = SimpleNamespace(data_dir=data)
        events = login_log.load(cfg).get("events", [])
        if not events:
            return ""
        last = events[-1]
        ok = last.get("event") in ("ok", "manual_login")
        return f"카카오 로그인 {'정상' if ok else '끊김'} · 마지막 점검 {str(last.get('at', ''))[5:16]}"
    except Exception:  # noqa: BLE001
        return ""


_BOLD = re.compile(r"\*\*(.+?)\*\*")


def _inline(text: str) -> str:
    return _BOLD.sub(r"<b>\1</b>", escape(text))


def md(text: str) -> str:
    """분석 노트용 아주 작은 마크다운: ### 제목, - 목록, | 표 |, **굵게**, 빈 줄 = 문단."""
    out, items, rows = [], [], []

    def flush():
        if items:
            out.append("<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>")
            items.clear()
        if rows:
            body = [r for r in rows if not set(r.replace("|", "").strip()) <= set("-: ")]
            cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in body]
            if cells:
                head = "".join(f"<th>{_inline(c)}</th>" for c in cells[0])
                trs = "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in cells[1:])
                out.append(f'<div class="nt"><table><tr>{head}</tr>{trs}</table></div>')
            rows.clear()
    for line in text.splitlines():
        t = line.strip()
        if t.startswith("|"):
            if items:
                flush()
            rows.append(t)
            continue
        if rows:
            flush()
        if t.startswith(("- ", "* ")):
            items.append(_inline(t[2:]))
        elif t.startswith("#"):
            flush()
            out.append(f"<h5>{_inline(t.lstrip('#').strip())}</h5>")
        elif t:
            flush()
            out.append(f"<p>{_inline(t)}</p>")
        else:
            flush()
    flush()
    return "".join(out)


def note(key: str, notes_dir: Path | None = None) -> tuple[str, str]:
    """diagnostics/notes/<블로그>.md → (날짜, HTML). 첫 줄 'updated: YYYY-MM-DD'."""
    path = (notes_dir or NOTES_DIR) / f"{key}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "", ""
    first, _, rest = text.partition("\n")
    if first.lower().startswith("updated:"):
        return first.split(":", 1)[1].strip(), md(rest)
    return "", md(text)


def _index(card: Card, data: Path, now: datetime) -> None:
    """구글 블로거: 색인 감시 결과(blogger_autopost.index_watch)."""
    days = (_json(data / "blogger_index.json", {}) or {}).get("days") or []
    if not days:
        return
    card.mode = "index"
    card.index, card.index_first = days[-1], days[0]
    by_day = card.index.get("by_day") or {}
    card.views = card.index.get("impressions")
    card.spark = [(d, (by_day.get(d) or {}).get("impressions", 0))
                  for d in reversed([(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, SPARK_DAYS + 1)])]
    card.stage = "색인"


def collect(paths: Paths | None = None, now: datetime | None = None) -> list[Card]:
    p = paths or Paths.load()
    now = now or datetime.now()
    today = now.strftime("%Y-%m-%d")
    week = {(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)}
    lab_on, watch, auto = _lab_modes()
    cards = []
    for key, name, fname, desc in BLOGS:
        hist = p.data / fname
        if not hist.exists():
            continue
        card = Card(key, name, desc, mode="lab" if key in lab_on else "watch" if key in watch else "off")
        if card.mode == "lab" and key in auto:
            card.mode = "lab-auto"
        try:
            entries = _entries(hist)
            card.titles = {_key(e["url"]): e.get("title") or "" for e in entries}
            card.note_date, card.note_html = note(key)
            auto_posts = [e for e in entries if e.get("source") == "autopost"]
            dates = [str(e.get("date", ""))[:10] for e in auto_posts]
            card.today = dates.count(today)
            card.week = sum(d in week for d in dates)
            card.last = max(dates, default="-")
            if card.mode != "off":
                _views(card, p.data / "lab", entries, now)
                _ledger(card, p.data / "lab")
                _review(card, p.output)
            if key == "tistory":
                card.login = _login(p.data)
            if key == "blogger":
                _index(card, p.data, now)
        except Exception as e:  # noqa: BLE001 - 한 블로그를 못 읽어도 나머지는 보여 준다
            log.warning("[%s] 블로그 분석 카드 실패: %s", name, e)
            card.error = str(e)[:120]
        cards.append(card)
    return cards


# ---------------------------------------------------------------- 화면

MODE = {"index": ("🔎 색인 감시 중", "m-watch"), "lab-auto": ("🧪 실험실 · 자동 개선", "m-lab"), "lab": ("🧪 실험실 운영", "m-lab"),
        "watch": ("👀 조회수 수집 중", "m-watch"), "off": ("발행만", "m-off")}

CSS = """
.bp-sum{display:flex;flex-wrap:wrap;gap:8px;margin:4px 0 12px}
.bcards{display:flex;flex-direction:column;gap:12px}
.bc{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.bc h3{margin:0;font-size:16px;display:flex;flex-wrap:wrap;align-items:center;gap:6px 8px}
.bc .ds{color:var(--sub);font-size:12px;margin-top:2px}
.mb{font-size:11px;font-weight:700;border-radius:999px;padding:2px 8px}
.m-lab{color:var(--done);background:var(--done-bg)}.m-watch{color:var(--run);background:var(--run-bg)}
.m-off{color:var(--mute);background:var(--mute-bg)}
.kp{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:8px;margin:12px 0 4px}
.kp div{background:var(--bg);border-radius:8px;padding:8px 10px}
.kp small{display:block;color:var(--sub);font-size:11px}
.kp b{font-size:20px;font-variant-numeric:tabular-nums}
.kp .up{color:var(--done);font-size:12px;font-weight:700}.kp .dn{color:var(--fail);font-size:12px;font-weight:700}
.spark{display:flex;align-items:flex-end;gap:2px;height:44px;margin:8px 0 2px}
.spark i{flex:1;background:var(--run);opacity:.75;border-radius:2px 2px 0 0;min-height:1px}
.spark i.no{background:var(--mute-bg);opacity:1;height:4px!important}
.sl{display:flex;justify-content:space-between;color:var(--mute);font-size:11px}
.sec{margin-top:12px}.sec h4{margin:0 0 4px;font-size:13px;color:var(--sub);font-weight:700}
.sec ul{margin:0;padding-left:18px;font-size:13px;line-height:1.6}
.sec ul li small{color:var(--mute)}
.stage{display:inline-block;font-weight:700;color:var(--warn);background:var(--warn-bg);border-radius:6px;padding:1px 8px;
font-size:13px;margin-right:6px}
.ev{font-size:13px;color:var(--sub)}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{font-size:12px;border-radius:6px;padding:2px 8px;background:var(--mute-bg);color:var(--sub)}
.chip.ok{background:var(--done-bg);color:var(--done)}.chip.dead{text-decoration:line-through}
.bc details{margin-top:10px;font-size:13px}.bc summary{cursor:pointer;color:var(--sub)}
.bc a{color:var(--ink)}
.bc.off .kp{grid-template-columns:repeat(3,1fr)}
.note-box{margin-top:12px;background:var(--bg);border:1px solid var(--line);border-left:4px solid var(--run);border-radius:8px;
padding:10px 12px;font-size:13px;line-height:1.6}
.note-box>h4{margin:0 0 4px;font-size:13px;color:var(--run)}
.note-box h5{margin:10px 0 2px;font-size:13px}.note-box p{margin:4px 0}.note-box ul{margin:2px 0;padding-left:18px}
.nt{overflow-x:auto;margin:6px 0}.nt table{font-size:12px;width:auto;min-width:60%;background:var(--card);border-radius:6px}
.nt th,.nt td{padding:3px 8px;text-align:left;white-space:normal;position:static}
.rv{margin:4px 0 0;font-size:13px;line-height:1.6}
"""


def _fmt(n: int | None) -> str:
    return "-" if n is None else f"{n:,}"


def _change(card: Card) -> str:
    if card.views is None or not card.prev:
        return ""
    pct = (card.views - card.prev) / card.prev * 100
    cls = "up" if pct >= 0 else "dn"
    return f' <span class="{cls}">{"▲" if pct >= 0 else "▼"}{abs(pct):.0f}%</span>'


def _spark(card: Card) -> str:
    vals = [v for _, v in card.spark if v is not None]
    if not vals:
        return ""
    top = max(vals) or 1
    bars = "".join(f'<i class="no" title="{d} 기록 없음"></i>' if v is None else
                   f'<i style="height:{max(4, 100 * v / top):.0f}%" title="{d} {v:,}회"></i>' for d, v in card.spark)
    first, last = card.spark[0][0][5:].replace("-", "/"), card.spark[-1][0][5:].replace("-", "/")
    return (f'<div class="spark" role="img" aria-label="최근 {SPARK_DAYS}일 하루 조회 막대">{bars}</div>'
            f'<div class="sl"><span>{first}</span><span>하루 조회(최근 {SPARK_DAYS}일)</span><span>{last}</span></div>')


def _li(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"


def _card(c: Card) -> str:
    label, cls = MODE[c.mode]
    kp = [f'<div><small>오늘 발행</small><b>{c.today}</b>편</div>',
          f'<div><small>최근 7일 발행</small><b>{c.week}</b>편</div>']
    if c.mode == "index":
        ix = c.index
        rate = f"{ix.get('indexed', 0) * 100 // ix['posts']}%" if ix.get("posts") else "-"
        kp = [f'<div><small>구글 색인</small><b>{ix.get("indexed", 0)}</b>/{ix.get("posts", 0)}편 <span class="up">{rate}</span></div>',
              f'<div><small>최근 28일 검색 노출</small><b>{_fmt(ix.get("impressions"))}</b>회</div>',
              f'<div><small>최근 28일 클릭</small><b>{_fmt(ix.get("clicks"))}</b>회</div>',
              f'<div><small>오늘 발행</small><b>{c.today}</b>편</div>']
    elif c.mode != "off":
        kp.append(f'<div><small>최근 {WINDOW}일 조회</small><b>{_fmt(c.views)}</b>{_change(c)}</div>')
    else:
        kp.append(f'<div><small>마지막 발행</small><b style="font-size:15px">{escape(c.last[5:] or "-")}</b></div>')
    out = [f'<div class="bc {"off" if c.mode == "off" else ""}"><h3>{escape(c.name)}<span class="mb {cls}">{label}</span></h3>',
           f'<div class="ds">{escape(c.desc)}{" · " + escape(c.login) if c.login else ""}</div>',
           f'<div class="kp">{"".join(kp)}</div>']
    if c.error:
        out.append(f'<div class="ev">⚠️ 읽지 못한 자료가 있어요: {escape(c.error)}</div>')
    if c.mode == "off":
        if c.note_html:
            out.append(f'<div class="note-box"><h4>🧠 Claude 분석'
                       f'{" · " + escape(c.note_date) if c.note_date else ""}</h4>{c.note_html}</div>')
        return "".join(out) + "</div>"
    out.append(_spark(c).replace("하루 조회", "하루 검색 노출") if c.mode == "index" else _spark(c))
    if c.note_html:
        out.append(f'<div class="note-box"><h4>🧠 Claude 분석'
                   f'{" · " + escape(c.note_date) if c.note_date else ""}</h4>{c.note_html}</div>')
    if c.mode == "index":
        ix, first = c.index, c.index_first
        moved = (f"감시를 시작한 {first.get('date', '')[5:]}에는 {first.get('indexed', 0)}편이었어요."
                 if first and first.get("date") != ix.get("date") else "오늘부터 매일 22:30에 확인해요.")
        lag = f" 새 글이 색인되기까지 보통 {ix['days_to_index']}일." if ix.get("days_to_index") is not None else ""
        out.append('<div class="sec"><h4>지금 단계</h4><div class="ev">'
                   + escape(f"조회수 실험 전에 색인부터 올리는 단계예요. {moved}{lag} "
                            "색인이 절반을 넘고 검색 노출이 주 100회쯤 되면 성장 실험실로 넘어가요.") + "</div></div>")
        states = ix.get("states") or {}
        if states:
            out.append('<div class="sec"><h4>색인 안 된 이유</h4><div class="chips">' + "".join(
                f'<span class="chip">{escape(k)} {v}편</span>' for k, v in states.items()) + "</div></div>")
        pages = ix.get("top_pages") or []
        if pages:
            out.append('<div class="sec"><h4>검색에 나온 글 (최근 90일)</h4>' + _li(
                [f'<a href="{escape(p["url"])}" target="_blank" rel="noopener">'
                 f'{escape((c.titles.get(_key(p["url"])) or p["url"].rsplit("/", 1)[-1])[:60])}</a> '
                 f'<small>노출 {p["impressions"]} · 클릭 {p["clicks"]} · 평균 {p["position"]}위</small>' for p in pages[:6]])
                + "</div>")
        if ix.get("errors"):
            out.append(f'<div class="ev">⚠️ 서치 콘솔 오류: {escape(str(ix["errors"][0])[:150])}</div>')
        return "".join(out) + "</div>"
    if c.mode == "watch":
        msg = (f"조회수 {c.days_collected}일치를 모았어요. 2주쯤 쌓이면 주제 판정·개선 실험을 켤 수 있어요."
               if c.days_collected else "오늘 밤 22:30 수집부터 조회수가 쌓여요(첫날 60일치를 한꺼번에 받아요).")
        out.append(f'<div class="sec"><h4>지금 단계</h4><div class="ev">{escape(msg)}</div></div>')
    if c.stage:
        out.append(f'<div class="sec"><h4>막힌 곳 <small>({escape(c.review_date)} 주간 리뷰)</small></h4>'
                   f'<span class="stage">{escape(c.stage)}</span><span class="ev">{escape(STAGE_KO.get(c.stage, ""))}</span>'
                   f'<div class="ev" style="margin-top:4px">{escape(c.evidence)}</div></div>')
    improve = [f"{escape(r)} <small>{escape(d[5:])}부터</small>" for d, r in c.rules]
    if c.experiment:
        improve.append("🧪 " + escape(c.experiment))
    if improve:
        out.append(f'<div class="sec"><h4>🚀 지금 적용 중인 개선</h4>{_li(improve)}</div>')
    if c.pending:
        out.append(f'<div class="sec"><h4>💬 답을 기다리는 제안</h4>{_li([escape(x[:140]) for x in c.pending])}</div>')
    chips = ([f'<span class="chip ok">⭐ {escape(x)}</span>' for x in c.promising]
             + ([f'<span class="chip">시험 중 {c.testing}개</span>'] if c.testing else [])
             + [f'<span class="chip dead">⚰️ {escape(x)}</span>' for x in c.graveyard])
    if chips:
        out.append(f'<div class="sec"><h4>주제 상태</h4><div class="chips">{"".join(chips)}</div></div>')
    if c.explore:
        out.append(f'<div class="sec"><h4>🔍 다음에 시험할 주제</h4><div class="chips">'
                   + "".join(f'<span class="chip">{escape(x)}</span>' for x in c.explore) + "</div></div>")
    if c.top_posts:
        out.append(f'<div class="sec"><h4>최근 {WINDOW}일 많이 읽힌 글</h4>' + _li(
            [f'<a href="{escape(u)}" target="_blank" rel="noopener">{escape(t[:60] or u)}</a> <small>{n:,}회</small>'
             for t, u, n in c.top_posts]) + "</div>")
    if c.report:
        out.append(f'<div class="sec"><h4>📝 주간 리뷰 요약 <small>({escape(c.review_date)})</small></h4>'
                   f'<p class="rv">{escape(c.report)}</p></div>')
    more = []
    if c.changes:
        more.append(_li([f"<small>{escape(d[5:])}</small> {escape(w)}" for d, w in c.changes]))
    if more:
        out.append(f'<details><summary>최근 변경 기록</summary>{"".join(more)}</details>')
    return "".join(out) + "</div>"


def render(cards: list[Card], now: datetime | None = None) -> str:
    """'자동화 블로그 분석' 칸(HTML 조각). 퀘스트 보드 화면 안에 들어간다."""
    if not cards:
        return '<p class="stamp">아직 읽을 발행 기록이 없습니다.</p>'
    lab = [c for c in cards if c.mode not in ("off", "index")]      # 블로거 색인 카드는 조회가 아니라 검색 노출이라 뺀다
    done = sum(1 for c in cards if c.today)
    total = sum(c.views or 0 for c in lab)
    pending = sum(len(c.pending) for c in cards)
    pills = [f'<span class="pill s-done" style="color:var(--c);background:var(--b)"><b>{done}</b>/{len(cards)}곳 오늘 발행</span>',
             f'<span class="pill s-running" style="color:var(--c);background:var(--b)"><b>{total:,}</b> 최근 {WINDOW}일 조회'
             f'(분석 중 {len(lab)}곳)</span>']
    if pending:
        pills.append(f'<span class="pill s-retry" style="color:var(--c);background:var(--b)"><b>{pending}</b> 답 기다리는 제안</span>')
    return (f'<div class="bp-sum">{"".join(pills)}</div><div class="bcards">{"".join(_card(c) for c in cards)}</div>'
            '<div class="legend"><span>🧪 실험실 = 주제 판정·개선을 스스로 돌림</span><span>👀 조회수 수집 = 데이터만 쌓는 중</span>'
            '<span>점수 = 같은 나이 글 조회수 ÷ 블로그 중간값</span></div>')


def panel(paths: Paths | None = None, now: datetime | None = None) -> str:
    try:
        return render(collect(paths, now), now)
    except Exception as e:  # noqa: BLE001 - 분석 칸이 실패해도 퀘스트 보드는 그대로 나온다
        log.warning("블로그 분석 칸 실패: %s", e)
        return f'<div class="note">블로그 분석을 읽지 못했습니다: {escape(str(e)[:150])}</div>'
