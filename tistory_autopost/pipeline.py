"""하루 1편: (티스토리 로그인 확인) → 화제 제보 받기 → 주제 선정 → Claude 글쓰기 → 구조 검증
→ Claude 팩트체크 → ChatGPT(Codex) 교차 팩트체크 → 티스토리 발행 → 이력 기록 → 알림.
멈추면 다음 실행이 멈춘 단계부터 이어서 한다."""
from __future__ import annotations

import json
import logging
import shutil
import time
from datetime import date, datetime
from pathlib import Path

from naver_autopost import generate, history
from naver_autopost.notify import send_text
from naver_autopost.pipeline import KST, _Lock, today_kst

from . import content, inbox, topics, writer
from .config import TistoryConfig

log = logging.getLogger(__name__)
LABEL = "티스토리 통계"


class Rejected(Exception):
    """이번 글이 발행 기준에 못 미침(다른 주제로 다시 쓴다)."""


def notify(cfg: TistoryConfig, text: str) -> None:
    send_text(cfg.telegram_bot_token, cfg.telegram_chat_id, text)


def setup_logging(cfg: TistoryConfig, name: str) -> None:
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.FileHandler(cfg.log_dir / f"{name}.log", encoding="utf-8"),
                                  logging.StreamHandler()])


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}


def _save(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _mark(out_dir: Path, **flags) -> None:
    _save(out_dir / "stage.json", {**_load(out_dir / "stage.json"), **flags})


def _load_post(out_dir: Path) -> dict:
    try:
        return content.normalize(_load(out_dir / "post.json"))
    except json.JSONDecodeError as e:
        raise Rejected(f"post.json이 올바른 JSON이 아닙니다: {e}") from e


def _validate(cfg: TistoryConfig, post: dict) -> list[str]:
    return content.validate(post, cfg.min_sources, cfg.min_primary_sources, cfg.min_data_points,
                            cfg.min_body_chars)


def topic_brief(cfg: TistoryConfig, today: date) -> str:
    entries = history.load(cfg.history_file)
    ranked = topics.rank(topics.load(cfg.topics_file), entries, today)
    if not ranked and not inbox.pending(cfg):
        raise RuntimeError("주제 큐를 모두 썼습니다. data/tistory_topics.json에 주제를 추가하세요.")
    return topics.brief(ranked, inbox.pending(cfg))


def _gpt_check(cfg: TistoryConfig, out_dir: Path) -> dict:
    """ChatGPT 교차검증. 지적이 있으면 Claude가 원문으로 재확인해 맞는 것만 반영하고, ChatGPT가 다시 본다."""
    post = _load_post(out_dir)
    last = cfg.gpt_fix_rounds + 1
    for round_no in range(1, last + 1):
        review = writer.gpt_factcheck(cfg, post)
        _save(out_dir / f"gpt_factcheck_{round_no}.json", review)
        if review["verdict"] == "pass":
            return post
        if review["verdict"] == "fail" or round_no == last:
            raise Rejected(f"ChatGPT 팩트체크 불합격({review['verdict']}): {review.get('summary', '')}\n"
                           + json.dumps(review.get("issues", [])[:8], ensure_ascii=False))
        _save(out_dir / "gpt_review.json", review)
        applied = writer.apply_gpt_review(cfg, out_dir, round_no)
        log.info("ChatGPT 지적 반영: 적용 %d건, 반박 %d건",
                 len(applied.get("applied", [])), len(applied.get("rejected", [])))
        post = _load_post(out_dir)
        _save(out_dir / "post.json", post)
    return post


def _attempt(cfg: TistoryConfig, today: str, out_dir: Path, feedback: str, resume: bool) -> dict:
    stage = _load(out_dir / "stage.json") if resume else {}
    if not stage.get("written"):
        brief = topic_brief(cfg, date.fromisoformat(today))
        writer.write_post(cfg, out_dir, today, brief, feedback)
        _mark(out_dir, written=True)
    else:
        log.info("이미 쓴 글을 이어서 처리합니다")
    post = _load_post(out_dir)
    _save(out_dir / "post.json", post)
    errors = _validate(cfg, post)
    if errors:
        raise Rejected("구조 검증 실패:\n- " + "\n- ".join(errors))

    if not stage.get("claude_pass"):
        fc = writer.factcheck(cfg, out_dir)
        if fc.get("verdict") != "pass":
            raise Rejected(f"Claude 팩트체크 불합격: {fc.get('summary', '')}\n"
                           + json.dumps(fc.get("issues", [])[:10], ensure_ascii=False))
        log.info("Claude 팩트체크 통과: %s", fc.get("summary", ""))
        _mark(out_dir, claude_pass=True)
        post = _load_post(out_dir)

    if cfg.gpt_factcheck and not stage.get("gpt_pass"):
        post = _gpt_check(cfg, out_dir)
        _mark(out_dir, gpt_pass=True)
        log.info("ChatGPT 팩트체크 통과")

    errors = _validate(cfg, post)
    if errors:
        raise Rejected("팩트체크 수정 후 구조 검증 실패:\n- " + "\n- ".join(errors))
    return post


def produce(cfg: TistoryConfig, today: str, out_dir: Path) -> dict:
    """발행할 글을 만든다. 떨어지면 TISTORY_MAX_ATTEMPTS번까지 다시 쓴다(Claude 한도는 기다렸다 이어서)."""
    feedback = ""
    resume = bool(_load(out_dir / "stage.json").get("written")) and (out_dir / "post.json").exists()
    for attempt in range(1, cfg.max_attempts + 1):
        if not resume and out_dir.exists() and any(out_dir.iterdir()):
            stamp = datetime.now(KST).strftime("%H%M%S")
            shutil.move(str(out_dir), str(out_dir.with_name(f"{out_dir.name}-rejected-{stamp}")))
        log.info("[tistory] 글쓰기 시도 %d/%d%s", attempt, cfg.max_attempts, " (이어서)" if resume else "")
        try:
            return _attempt(cfg, today, out_dir, feedback, resume)
        except Rejected as e:
            feedback = str(e)
            log.warning(feedback)
            resume = False
    raise RuntimeError(f"{cfg.max_attempts}번 시도했지만 발행 기준을 통과한 글을 만들지 못했습니다.\n{feedback[:800]}")


def _refresh_note(cfg: TistoryConfig, today: date) -> str:
    try:
        due = topics.refresh_due(topics.load(cfg.topics_file), history.load(cfg.history_file), today)
    except Exception as e:  # noqa: BLE001 - 알림 보조 정보라 실패해도 발행은 계속한다
        log.warning("갱신 목록 확인 실패: %s", e)
        return ""
    if not due:
        return ""
    lines = [f"- {d['title']} ({d['url']})" for d in due[:5]]
    return "🔄 새 통계가 나와 갱신하면 좋은 글:\n" + "\n".join(lines)


def run(cfg: TistoryConfig, dry_run: bool = False, force: bool = False) -> int:
    from . import publisher

    today = today_kst()
    setup_logging(cfg, f"tistory-{today}")
    try:
        with _Lock(cfg.log_dir / ".run-tistory.lock"):
            done = history.published_on(cfg.history_file, today)
            if done and not force:
                log.info("오늘(%s)은 이미 발행했습니다: %s", today, done["url"])
                return 0
            if not cfg.blog_name:
                raise RuntimeError(".env에 TISTORY_BLOG(블로그 주소 이름)가 없습니다")
            out_dir = cfg.output_dir / today
            if _load(out_dir / "stage.json").get("published"):
                if not force:
                    log.info("오늘(%s) 글은 이미 발행했습니다", today)
                    return 0
                stamp = datetime.now(KST).strftime("%H%M%S")
                shutil.move(str(out_dir), str(out_dir.with_name(f"{out_dir.name}-published-{stamp}")))
            # 글쓰기(수십 분) 전에 로그인부터 확인한다.
            if not publisher.check_session(cfg):
                raise publisher.SessionExpired(
                    "티스토리 로그인이 풀려 있습니다. `python -m tistory_autopost login`으로 다시 로그인하세요.")
            try:
                log.info("텔레그램 화제 제보 %d건을 받았습니다", inbox.pull(cfg))
            except Exception as e:  # noqa: BLE001 - 제보는 보조 입력이라 실패해도 큐로 진행한다
                log.warning("화제 제보 받기 실패(큐로 진행): %s", e)

            post = None
            deadline = datetime.now(KST).timestamp() + cfg.limit_wait_max_min * 60
            while post is None:
                try:
                    post = produce(cfg, today, out_dir)
                except generate.ClaudeLimitError as e:
                    if e.reset_at.timestamp() > deadline:
                        raise
                    notify(cfg, f"[{LABEL}] Claude 사용 한도 → {e.reset_at:%H:%M}에 이어서 진행합니다.")
                    while datetime.now(KST) < e.reset_at:
                        _sleep(min(300, max(1, (e.reset_at - datetime.now(KST)).total_seconds())))

            url = publisher.publish(cfg, post, out_dir, dry_run=dry_run)
            cat_note = f"카테고리: {cfg.category or '(없음)'}"
            if post.get("_category_ok") is False:
                cat_note += " ⚠️ 카테고리를 찾지 못해 카테고리 없이 올렸습니다"
            if dry_run:
                notify(cfg, f"[{LABEL} 테스트] 공개 발행 직전까지 확인했습니다: {post['title']}\n{cat_note}\n"
                            f"스크린샷: {out_dir}")
                return 0
            _mark(out_dir, published=True, url=url)
            history.append(cfg.history_file, {
                "date": today, "title": post["title"], "url": url, "topic_id": post.get("topic_id", ""),
                "lane": post.get("lane", "queue"), "tip_id": post.get("tip_id", ""),
                "tags": post.get("tags", []), "source": "autopost",
            })
            if post.get("tip_id"):
                inbox.mark_used(cfg, post["tip_id"], url)
            refresh = _refresh_note(cfg, date.fromisoformat(today))
            notify(cfg, f"[{LABEL} 자동발행 완료] {post['title']}\n{url}\n{cat_note}"
                        + (f"\n{refresh}" if refresh else ""))
            return 0
    except Exception as e:
        log.exception("티스토리 자동 발행 실패")
        notify(cfg, f"[{LABEL} 자동발행 실패] {today}\n{e}")
        return 1


_sleep = time.sleep
