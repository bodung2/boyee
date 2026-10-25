"""주간 리뷰: 판정(코드 규칙) → 실험 진행 → 원인 진단·리서치(Claude, growth-lab-review 스킬) → 장부·플레이북 갱신 → 알림.

Claude에게는 판단 재료(점수표·통계 화면 원본)만 주고, 장부를 바꾸는 일은 여기 코드가 한다.
Claude는 output/lab/ 아래에만 쓸 수 있고(review.json), 스킬·코드 파일을 고치면 되돌린다(핵심 규칙 잠금)."""
from __future__ import annotations

import json
import logging
import re
import subprocess
from datetime import date, timedelta
from pathlib import Path

from naver_autopost import generate, history
from naver_autopost.config import ROOT
from naver_autopost.notify import send_text

from . import brief, demand, scoring, store, styles
from .config import BLOGS, LabConfig

log = logging.getLogger(__name__)
PREFIX = {"invest": "투", "tistory": "티"}          # 텔레그램 답장에서 블로그를 가리는 글자("승인 투3")
STATUS_KO = {"testing": "시험 중", "promising": "유망", "core": "주력", "neutral": "보통", "saturated": "포화",
             "dead": "중단(무덤)", "hold": "보류(채널 점검)"}
MAX_PROPOSALS = 3
MAX_QUEUE = 15
REVIEW_TOOLS = ["WebSearch", "WebFetch", "Read", "Glob", "Grep", "Skill"]


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/") if path.is_relative_to(ROOT) else str(path)


def apply_verdicts(ledger: dict, verdicts: list[dict], today: str) -> list[str]:
    notes = []
    for v in verdicts:
        name = v["topic"]
        if name == scoring.OWN:
            continue
        t = ledger["topics"].setdefault(name, {"first": today, "keywords": []})
        prev = t.get("status")
        t.update({k: v[k] for k in ("status", "ratio", "evaluated", "posts", "best_rank")}, updated=today)
        if prev != v["status"]:
            why = f"점수 {v['ratio']}(중간값 대비), 판정한 글 {v['evaluated']}편, 최고 검색 순위 {v['best_rank'] or '-'}"
            store.log_change(ledger, today, f"주제 「{name}」 {STATUS_KO.get(prev, prev or '새로')} → {STATUS_KO[v['status']]}", why)
            notes.append(f"「{name}」 {STATUS_KO[v['status']]} ({why})")
        if v["status"] == "dead" and not brief.in_graveyard(ledger, name):
            ledger["graveyard"].append({"name": name, "keywords": t.get("keywords", [])[:10], "date": today,
                                        "ratio": v["ratio"],
                                        "reason": f"시험 글 {v['evaluated']}편 점수 {v['ratio']}(블로그 중간값의 {v['ratio']}배), "
                                                  f"검색 상위 10위 없음"})
            ledger["explore_queue"] = [c for c in ledger["explore_queue"] if not brief.similar(c.get("name", ""), name)]
    return notes


def advance_experiment(blog: str, ledger: dict, table: list[dict], today: str, ready: bool) -> str:
    """실험 시작·마감·판정. ready: 점수를 낼 수 있고 채널이 정상일 때만 새 실험을 시작한다."""
    exp = ledger.get("experiment")
    spec = BLOGS[blog]
    if not exp:
        if not ready:
            return ""
        exp = styles.start(blog, ledger, today)
        if not exp:
            return ""
        store.log_change(ledger, today, f"화풍 실험 시작: {exp['arms'][0]} vs {exp['arms'][1]}",
                         f"{exp['post_until']}까지 하루씩 번갈아 쓰고, {spec.eval_days[0]}일째 조회수로 비교")
        return f"🧪 화풍 실험 시작: {exp['arms'][0]} vs {exp['arms'][1]} (~{exp['post_until']})"
    if exp["status"] == "running" and today > exp["post_until"]:
        exp["status"] = "collecting"
    if exp["status"] == "collecting":
        judge_day = (date.fromisoformat(exp["post_until"]) + timedelta(days=spec.eval_days[0] + 2)).isoformat()
        if today < judge_day:
            return f"🧪 화풍 실험 조회수 모으는 중({judge_day}에 판정)"
        scores = scoring.arm_scores(table, "image_style", exp["arms"], exp["start"], exp["post_until"])
        winner, why = styles.decide(scores, exp["arms"])
        winner = winner or exp["arms"][0]
        ledger["adopted"]["image_style"] = winner
        ledger["experiments_done"].append({**exp, "scores": scores, "winner": winner, "why": why, "ended": today})
        ledger["experiment"] = None
        store.log_change(ledger, today, f"화풍 실험 끝: {winner}", why)
        return f"🧪 화풍 실험 끝: {why}"
    return f"🧪 화풍 실험 중: {exp['arms'][0]} vs {exp['arms'][1]} (~{exp['post_until']})"


def decide(blog: str, cfg: LabConfig, ledger: dict, pid: int, verb: str, today: str, text: str = "") -> str | None:
    """제안 하나를 승인·거절한다. 승인된 규칙은 플레이북의 '확정 규칙'이 된다(text가 있으면 고친 문장으로).
    처리했으면 알림 문구, 없는 제안·이미 정한 제안이면 None."""
    prop = next((p for p in ledger["proposals"] if p["id"] == pid), None)
    if not prop or prop["status"] != "pending" or verb not in ("승인", "거절"):
        return None
    prop["status"] = "approved" if verb == "승인" else "rejected"
    prop["decided"] = today
    if text.strip():
        prop["text"] = text.strip()[:300]
    if prop["status"] == "approved":
        store.add_approved_rule(cfg, blog, prop["text"], today)
    store.log_change(ledger, today, f"제안 {PREFIX[blog]}{prop['id']} {verb}", prop["text"][:120])
    return f"제안 {PREFIX[blog]}{prop['id']} {verb}: {prop['text'][:60]}"


def handle_commands(blog: str, cfg: LabConfig, ledger: dict, today: str, inbox_file: Path) -> list[str]:
    """텔레그램 답장("승인 투3"/"거절 투3")으로 제안을 처리한다."""
    from tistory_autopost import inbox

    notes = []
    for c in inbox.pending_commands(inbox_file):
        if c.get("prefix") and c["prefix"] != PREFIX[blog]:
            continue
        if not c.get("prefix") and len(cfg.blogs) > 1:
            inbox.mark_command(inbox_file, c.get("update_id"), "블로그 글자(투/티)가 없어 무시")
            continue
        note = decide(blog, cfg, ledger, c["id"], c["verb"], today)
        inbox.mark_command(inbox_file, c.get("update_id"), "처리" if note else "없는 제안")
        if note:
            notes.append(note)
    return notes


DECISIONS_FILE = "lab_decisions.json"     # data/ 아래, git에 올라감 — Claude 대화에서 정한 승인·거절을 PC로 보낸다


def apply_repo_decisions(blog: str, cfg: LabConfig, ledger: dict, today: str) -> list[str]:
    """저장소의 data/lab_decisions.json({"decisions": [{"blog", "id", "verb", "text"?}]})을 한 번씩만 반영한다.
    PC는 예약 작업마다 최신 코드를 받아 오므로, PR이 병합되면 다음 실행 때 들어온다."""
    path = cfg.history_dir / DECISIONS_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except json.JSONDecodeError as e:
        return [f"⚠️ {DECISIONS_FILE}를 읽지 못했습니다: {e}"]
    done = {tuple(x) for x in ledger.setdefault("applied_decisions", [])}
    notes = []
    for d in data.get("decisions", []):
        try:
            key = (str(d["blog"]), int(d["id"]))
        except (KeyError, TypeError, ValueError):
            continue
        if key[0] != blog or key in done:
            continue
        note = decide(blog, cfg, ledger, key[1], str(d.get("verb", "")), today, str(d.get("text") or ""))
        ledger["applied_decisions"].append(list(key))
        done.add(key)
        if note:
            notes.append(note)
    return notes


_URL = re.compile(r"https?://\S+")


def scrub(text: str, titles: list[str], idents: list[str]) -> str:
    """공개 저장소에 올리기 전에 글 제목·주소·블로그 아이디를 지운다(투자 블로그가 다른 블로그와 이어지지 않게)."""
    text = _URL.sub("(주소)", str(text or ""))
    for t in sorted({t for t in titles if len(t) >= 6}, key=len, reverse=True):
        text = text.replace(t, "(글 제목)")
    for i in idents:
        if i:
            text = text.replace(i, "<BLOG>")
    return text


def write_weekly(blog: str, cfg: LabConfig, ledger: dict, verdicts: list[dict], channel: str, result: dict,
                 today: str, titles: list[str], idents: list[str]) -> Path:
    """GitHub에 올리는 주간 보고(diagnostics/growth/<블로그>/weekly.md). 주제 단위 숫자와 제안만, 글 제목·주소는 지운다."""
    spec = BLOGS[blog]
    s = lambda t: scrub(t, titles, idents)  # noqa: E731
    funnel = result.get("funnel") or {}
    lines = [f"# 성장 실험실 주간 보고 · {spec.label} · {today}", "",
             f"- 채널: {s(channel)}",
             f"- 막힌 단계: {s(funnel.get('stage', '-'))} — {s(str(funnel.get('evidence', ''))[:300])}", "",
             "## 주제 점수 (블로그 중간값 대비, 판정 나이 조회수)", "",
             "| 주제 | 상태 | 점수 | 판정한 글 / 쓴 글 | 최고 검색 순위 |", "|---|---|---|---|---|"]
    for v in verdicts:
        if v["topic"] == scoring.OWN:
            continue
        lines.append(f"| {s(v['topic'])} | {STATUS_KO[v['status']]} | {v['ratio'] if v['ratio'] is not None else '-'} "
                     f"| {v['evaluated']} / {v['posts']} | {v['best_rank'] or '-'} |")
    if not verdicts:
        lines.append("| (아직 판정할 데이터가 모자람) | | | | |")
    exp = ledger.get("experiment")
    lines += ["", "## 실험", f"- 채택된 화풍: {(ledger.get('adopted') or {}).get('image_style', 'base')}",
              f"- 진행 중: {exp['arms'][0]} vs {exp['arms'][1]} ({exp['status']}, ~{exp['post_until']})" if exp else "- 진행 중: 없음"]
    lines += ["", "## 무덤"] + ([f"- {s(g['name'])} — {s(g.get('reason', ''))}" for g in ledger["graveyard"]] or ["- (없음)"])
    lines += ["", "## 탐색 후보 (검색 수요 = 기준 검색어 대비 배수)"] + (
        [f"- {s(c['name'])} (수요 {c.get('demand', '-')})" for c in ledger["explore_queue"][:10]] or ["- (없음)"])
    pend = [p for p in ledger["proposals"] if p["status"] == "pending"]
    lines += ["", "## 결정이 필요한 제안"] + ([f"- **{PREFIX[blog]}{p['id']}** {s(p['text'])}  \n  근거: {s(p.get('evidence', ''))}"
                                         for p in pend] or ["- (없음)"])
    if result.get("report"):
        lines += ["", "## 요약", s(str(result["report"])[:900])]
    out = cfg.diagnostics_dir / blog / "weekly.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def review_input(blog: str, cfg: LabConfig, ledger: dict, table: list[dict], verdicts: list[dict], channel: str,
                 gain, today: str) -> dict:
    spec = BLOGS[blog]
    recent = sorted(table, key=lambda p: p["date"])[-60:]
    caps = sorted((cfg.output_dir / blog).glob("*/capture.json"))[-3:]
    return {
        "blog": blog, "label": spec.label, "platform": spec.platform, "theme": spec.theme, "today": today,
        "eval_days": spec.eval_days, "channel": channel, "views_gain_14d": gain,
        "baseline_v1": scoring.baseline(table, "v1", cfg.min_baseline_posts),
        "verdicts": verdicts,
        "posts": [{k: p.get(k) for k in ("title", "date", "age", "topic", "mode", "views_now", "v1", "v2", "ratio",
                                         "best_rank", "features")} for p in recent],
        "capture_files": [_rel(c) for c in caps],
        "graveyard": ledger["graveyard"], "explore_queue": ledger["explore_queue"],
        "topics": ledger["topics"],
        "proposals": [p for p in ledger["proposals"] if p["status"] in ("pending", "rejected")][-20:],
        "experiment": ledger.get("experiment"), "experiments_done": ledger.get("experiments_done", [])[-5:],
        "learned_file": _rel(store.learned_path(cfg, blog)),
    }


def _git_dirty() -> set[str]:
    p = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return {line[3:].strip() for line in p.stdout.splitlines() if line.strip()} if p.returncode == 0 else set()


def run_claude(blog: str, cfg: LabConfig, work: Path, today: str) -> dict:
    """growth-lab-review 스킬로 원인 진단·리서치. 쓰기는 이 리뷰 폴더 안으로만 허용한다."""
    out = work / "review.json"
    out.unlink(missing_ok=True)
    rel = _rel(work)
    # 쉘(python 포함)은 주지 않는다: 쓰기 범위 제한(Write 규칙)을 돌아갈 수 있기 때문이다.
    # 권한 규칙의 경로는 작업 폴더 기준 상대 경로, 밖이면 '//절대경로'로 쓴다.
    scope = rel if not Path(rel).is_absolute() else "/" + work.as_posix()
    tools = REVIEW_TOOLS + [f"Write({scope}/**)", f"Edit({scope}/**)"]
    prompt = (f"/growth-lab-review\n\nBLOG={blog}\nTODAY={today}\nINPUT={rel}/review_input.json\n"
              f"OUTPUT={rel}/review.json\n\n"
              "스킬 지침대로 이 블로그의 지난 성과를 진단하고, 리서치한 뒤 review.json을 저장하라. "
              "질문하지 말고 끝까지 진행하라. OUTPUT 폴더 밖의 파일은 만들거나 고치지 마라.")
    before = _git_dirty()
    try:
        generate._run_claude(cfg, prompt, work / "claude_review.log", tools=tools, permission_mode="default")
    finally:
        touched = _git_dirty() - before
        if touched:                                   # 핵심 규칙 잠금: 스킬·코드가 바뀌었으면 되돌린다
            log.warning("리뷰가 저장소 파일을 고쳐 되돌립니다: %s", sorted(touched))
            subprocess.run(["git", "checkout", "--", *sorted(touched)], cwd=ROOT, capture_output=True)
    if not out.exists():
        raise generate.GenerationError("review.json이 만들어지지 않았습니다")
    return json.loads(out.read_text(encoding="utf-8"))


def apply_review(blog: str, cfg: LabConfig, ledger: dict, result: dict, today: str, demand_post=None) -> list[str]:
    notes = []
    for name, kws in (result.get("topic_keywords") or {}).items():
        t = ledger["topics"].get(name)
        if t is not None and isinstance(kws, list):
            merged = list(dict.fromkeys([str(k).strip() for k in kws if str(k).strip()] + t.get("keywords", [])))
            t["keywords"] = merged[:15]
    cands = []
    for c in result.get("explore_candidates") or []:
        name = str(c.get("name") or "").strip()
        kws = [str(k).strip() for k in c.get("keywords") or [] if str(k).strip()][:5]
        if not name or not kws or brief.in_graveyard(ledger, name):
            continue
        if any(brief.similar(name, n) for n in ledger["topics"]) or any(
                brief.similar(name, q.get("name", "")) for q in ledger["explore_queue"]):
            continue
        cands.append({"name": name, "keywords": kws, "why": str(c.get("why") or "")[:200], "added": today})
    if cands:
        scores = demand.compare({c["name"]: c["keywords"] for c in cands}, demand.anchor_for(blog),
                                cfg.naver_search_id, cfg.naver_search_secret, date.fromisoformat(today), demand_post)
        if "_error" in scores:
            mark = "ℹ️" if scores["_error"].startswith("꺼짐") else "⚠️"
            notes.append(f"{mark} 검색 수요 확인 {scores['_error']}")
        for c in cands:
            c["demand"] = scores.get(c["name"]) if "_error" not in scores else None
        # 검색이 거의 없는 후보(기준의 5% 미만)는 쓰기 전에 거른다
        kept = [c for c in cands if c["demand"] is None or c["demand"] >= 0.05]
        if len(kept) < len(cands):
            notes.append(f"검색 수요가 거의 없는 후보 {len(cands) - len(kept)}개를 걸렀습니다")
        ledger["explore_queue"] = sorted(ledger["explore_queue"] + kept,
                                         key=lambda c: -(c.get("demand") if c.get("demand") is not None else -1))[:MAX_QUEUE]
    learned = str(result.get("learned_md") or "").strip()
    if len(learned) >= 50:
        store.save_learned(cfg, blog, learned, today)
        store.log_change(ledger, today, "플레이북 갱신", str((result.get("funnel") or {}).get("evidence", ""))[:160])
    rejected = [p["text"] for p in ledger["proposals"] if p["status"] == "rejected"]
    for prop in (result.get("proposals") or [])[:MAX_PROPOSALS]:
        text = str(prop.get("text") or "").strip()
        if not text or any(brief.similar(text, r) for r in rejected):
            continue
        pid = ledger["next_proposal_id"]
        ledger["next_proposal_id"] += 1
        ledger["proposals"].append({"id": pid, "text": text[:300], "evidence": str(prop.get("evidence") or "")[:300],
                                    "status": "pending", "date": today})
    return notes


def report_text(blog: str, ledger: dict, verdicts: list[dict], channel: str, notes: list[str], result: dict) -> str:
    spec = BLOGS[blog]
    lines = [f"[성장 실험실 · {spec.label}] 주간 리뷰", f"채널: {channel}"]
    funnel = result.get("funnel") or {}
    if funnel:
        lines.append(f"막힌 곳: {funnel.get('stage', '-')} — {str(funnel.get('evidence', ''))[:160]}")
    top = [v for v in verdicts if v["topic"] != scoring.OWN][:6]
    if top:
        lines.append("주제 점수(중간값 대비): " + ", ".join(
            f"{v['topic']} {v['ratio'] if v['ratio'] is not None else '-'}({STATUS_KO[v['status']]})" for v in top))
    lines += notes
    if result.get("report"):
        lines.append(str(result["report"])[:900])
    pend = [p for p in ledger["proposals"] if p["status"] == "pending"]
    if pend:
        lines.append("제안(답장으로 결정: 승인 " + PREFIX[blog] + "번호 / 거절 " + PREFIX[blog] + "번호):")
        lines += [f"  {PREFIX[blog]}{p['id']}. {p['text'][:160]}" for p in pend[-5:]]
    if ledger["graveyard"]:
        lines.append(f"무덤 {len(ledger['graveyard'])}개 · 탐색 후보 {len(ledger['explore_queue'])}개")
    return "\n".join(lines)


def run(blog: str, cfg: LabConfig, today: str, use_claude: bool = True, demand_post=None,
        inbox_file: Path | None = None, idents: list[str] | None = None) -> dict:
    """idents: 공개 보고에서 지울 블로그 아이디들."""
    ledger = store.load_ledger(cfg, blog)
    entries = history.load(cfg.history_file(blog))
    rows = store.load_metrics(cfg, blog)
    daily = store.load_daily(cfg, blog)
    table = scoring.post_table(blog, entries, rows, today, scoring.topic_maps(cfg.history_dir), daily)
    gain = scoring.health_daily(daily, today) if daily["fetched"] else scoring.health(rows, today)
    verdicts, channel = scoring.judge(table, cfg, gain)
    notes = handle_commands(blog, cfg, ledger, today, inbox_file or cfg.history_dir / "tistory_inbox.json")
    notes += apply_repo_decisions(blog, cfg, ledger, today)
    notes += apply_verdicts(ledger, verdicts, today)
    exp_note = advance_experiment(blog, ledger, table, today, ready=bool(verdicts) and channel == "정상")
    if exp_note:
        notes.append(exp_note)
    work = cfg.output_dir / blog / f"review-{today}"
    work.mkdir(parents=True, exist_ok=True)
    (work / "review_input.json").write_text(json.dumps(
        review_input(blog, cfg, ledger, table, verdicts, channel, gain, today), ensure_ascii=False, indent=1),
        encoding="utf-8")
    result: dict = {}
    if use_claude:
        try:
            result = run_claude(blog, cfg, work, today)
            notes += apply_review(blog, cfg, ledger, result, today, demand_post)
        except generate.ClaudeLimitError as e:
            notes.append(f"⚠️ Claude 사용 한도로 진단·리서치는 건너뜀({e.reset_at:%H:%M} 이후 `python -m growth_lab review`)")
        except Exception as e:  # noqa: BLE001 - 진단이 실패해도 판정·장부는 남긴다
            log.exception("리뷰(Claude) 실패")
            notes.append(f"⚠️ 진단·리서치 실패: {str(e)[:200]}")
    store.save_ledger(cfg, blog, ledger)
    if cfg.push_report:
        try:
            write_weekly(blog, cfg, ledger, verdicts, channel, result, today,
                         [e.get("title", "") for e in entries], idents or [])
        except Exception as e:  # noqa: BLE001 - 보고 파일 실패로 리뷰 결과를 잃지 않게
            log.warning("주간 보고 파일 실패: %s", e)
    text = report_text(blog, ledger, verdicts, channel, notes, result)
    (work / "report.txt").write_text(text, encoding="utf-8")
    send_text(cfg.telegram_bot_token, cfg.telegram_chat_id, text)
    return {"verdicts": verdicts, "channel": channel, "notes": notes, "report": text}
