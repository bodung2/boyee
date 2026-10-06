"""하루 1편: (구글 로그인 확인) → Codex 글쓰기(korea-explained-blogger) → 구조 검증 → Codex 팩트체크·수정
→ 블로거 초안 → 발행(또는 예약) → 이력 기록 → 알림. 멈추면 다음 실행이 멈춘 단계부터 이어서 한다."""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from naver_autopost import history, persona
from naver_autopost.errors import ExternalAccountError
from naver_autopost.notify import send_text
from naver_autopost.pipeline import KST, _Lock, today_kst

from . import api, content, illustrations, infographic, photos, seo, writer
from .config import BloggerConfig

log = logging.getLogger(__name__)
LABEL = "구글 블로거"


class Rejected(Exception):
    """이번 글이 발행 기준에 못 미침(다른 주제로 다시 쓴다)."""


def notify(cfg: BloggerConfig, text: str) -> None:
    send_text(cfg.telegram_bot_token, cfg.telegram_chat_id, text)


def setup_logging(cfg: BloggerConfig, name: str) -> None:
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


def sync_history(cfg: BloggerConfig) -> tuple[int, int, set[str]]:
    """블로그와 발행 이력을 맞춘다. 블로그에 있는데 이력에 없는 글(직접 쓴 글 포함)은 넣고,
    이력에 있는데 블로그에서 지운 글(공개·예약 어디에도 없음)은 뺀다. 주제 중복 피하기·내부 링크·오늘 발행 여부에 쓴다.
    (추가 수, 삭제 수, 블로그에 지금 있는 글 ID들)"""
    live = api.list_posts(cfg, status="live")
    alive = live + api.list_posts(cfg, status="scheduled")
    ids = {str(p.get("id")) for p in alive if p.get("id")}
    entries = history.load(cfg.history_file)
    kept = [e for e in entries if not (e.get("source") in ("autopost", "blog") and e.get("post_id")
                                       and str(e["post_id"]) not in ids)]
    removed = len(entries) - len(kept)
    for e in entries:
        if e not in kept:
            log.info("블로그에서 지운 글을 이력에서 뺍니다: %s %s", e.get("date"), e.get("title"))
    known = {e.get("url", "").rstrip("/") for e in kept} | {str(e.get("post_id")) for e in kept if e.get("post_id")}
    added = 0
    for p in live:
        url = (p.get("url") or "").rstrip("/")
        if not url or url in known or str(p.get("id")) in known:
            continue
        kept.append({"date": (p.get("published") or "")[:10], "title": p.get("title", ""), "url": url,
                     "labels": p.get("labels", []), "post_id": p.get("id"), "source": "blog"})
        known.add(url)
        added += 1
    if added or removed:
        history.save(cfg.history_file, kept)
    return added, removed, ids


def published_today(cfg: BloggerConfig, today: str) -> dict | None:
    """오늘 자동 발행(예약 포함)한 글. 예약 글은 주소가 아직 없을 수 있어 주소 유무는 보지 않는다."""
    for e in history.load(cfg.history_file):
        if e.get("source") == "autopost" and e.get("date") == today:
            return e
    return None


def _check_and_fix(cfg: BloggerConfig, out_dir: Path) -> dict:
    """Codex 팩트체크(별도 세션). 지적이 있으면 Codex가 근거를 다시 확인해 고치고, 다시 검사해 pass여야 통과."""
    post = _load_post(out_dir)
    last = cfg.fix_rounds + 1
    for round_no in range(1, last + 1):
        review = writer.factcheck(cfg, post)
        _save(out_dir / f"factcheck_{round_no}.json", review)
        if review["verdict"] == "pass":
            return post
        if review["verdict"] == "fail" or round_no == last:
            raise Rejected(f"팩트체크 불합격({review['verdict']}): {review.get('summary', '')}\n"
                           + json.dumps(review.get("issues", [])[:8], ensure_ascii=False))
        applied = writer.apply_fixes(cfg, out_dir, review["issues"])
        log.info("팩트체크 지적 반영: 적용 %d건, 반박 %d건",
                 len(applied.get("applied", [])), len(applied.get("rejected", [])))
        post = _load_post(out_dir)
        _save(out_dir / "post.json", post)
    return post


def _attempt(cfg: BloggerConfig, today: str, out_dir: Path, feedback: str, resume: bool) -> dict:
    stage = _load(out_dir / "stage.json") if resume else {}
    if not stage.get("written"):
        writer.write_post(cfg, out_dir, today, history.load(cfg.history_file), feedback)
        _mark(out_dir, written=True)
    else:
        log.info("이미 쓴 글을 이어서 처리합니다")
    post = _load_post(out_dir)
    _save(out_dir / "post.json", post)
    errors = content.validate(post, cfg.min_sources, cfg.min_body_chars)
    if errors:
        raise Rejected("구조 검증 실패:\n- " + "\n- ".join(errors))
    if cfg.factcheck and not stage.get("checked"):
        post = _check_and_fix(cfg, out_dir)
        errors = content.validate(post, cfg.min_sources, cfg.min_body_chars)
        if errors:
            raise Rejected("팩트체크 수정 후 구조 검증 실패:\n- " + "\n- ".join(errors))
        _mark(out_dir, checked=True)
    return post


def _add_images(cfg: BloggerConfig, post: dict, out_dir: Path) -> str:
    """팩트체크를 통과한 글에 실제 사진(커먼즈)과 생성 그림을 넣는다. 그림 때문에 발행이 멈추지는 않는다.
    알림용 메모를 돌려준다. 이미 넣은 단계는 이어서 실행할 때 다시 하지 않는다."""
    notes = []
    fallback = cfg.photos if cfg.photo_fallback else 0      # 못 찾은 사진 자리를 채울 실사풍 생성 이미지
    steps = (("photos", cfg.photos, photos.add_photos),
             ("illustrations", cfg.illustrations + fallback, illustrations.add_illustrations),
             ("infographic", int(cfg.infographic), infographic.add))
    for name, count, step in steps:
        stage = _load(out_dir / "stage.json")
        if count <= 0:
            continue
        if stage.get(f"{name}_done"):
            notes.append(stage.get(f"{name}_note", ""))
            continue
        try:
            n, note = step(cfg, post, out_dir)
        except Exception as e:  # noqa: BLE001 - 사용 한도·네트워크 문제여도 글은 발행한다
            log.warning("%s 넣기 실패(빼고 발행): %s", name, e)
            if name == "photos":                 # 사진 검색 자체가 실패해도 그 자리는 생성 이미지로 채운다
                post["photo_misses"] = photos.photo_wants(cfg, post)
            what = {"photos": "실제 사진", "illustrations": "생성 그림", "infographic": "인포그래픽"}[name]
            notes.append(f"⚠️ {what}을 넣지 못했습니다: {str(e)[:150]}")
            continue
        _save(out_dir / "post.json", post)
        _mark(out_dir, **{f"{name}_done": True, f"{name}_note": note})
        log.info(note)
        notes.append(note)
    return " · ".join(n for n in notes if n)


def related_candidates(cfg: BloggerConfig) -> list[dict]:
    """관련 글 후보: 이력 중 주소가 있는(공개된) 글."""
    return [e for e in history.load(cfg.history_file) if e.get("url") and e.get("title")]


def _polish(cfg: BloggerConfig, post: dict, out_dir: Path) -> None:
    """발행 직전: 글이 그림으로 시작하지 않게 하고, 끝에 관련 글 링크를 넣는다(여러 번 해도 같은 결과)."""
    post["body_html"], changes = seo.improve(post["body_html"], "", post["title"], post.get("labels", []),
                                             related_candidates(cfg))
    _save(out_dir / "post.json", post)
    log.info("본문 다듬기: 그림 %d개를 첫 문단 뒤로, 관련 글 %s", changes["moved_images"], changes["related"])


def produce(cfg: BloggerConfig, today: str, out_dir: Path) -> dict:
    """발행할 글을 만든다. 떨어지면 BLOGGER_MAX_ATTEMPTS번까지 다른 주제로 새로 쓴다."""
    feedback = ""
    resume = bool(_load(out_dir / "stage.json").get("written")) and (out_dir / "post.json").exists()
    for attempt in range(1, cfg.max_attempts + 1):
        if not resume and out_dir.exists() and any(out_dir.iterdir()):
            stamp = datetime.now(KST).strftime("%H%M%S")
            shutil.move(str(out_dir), str(out_dir.with_name(f"{out_dir.name}-rejected-{stamp}")))
        log.info("[blogger] 글쓰기 시도 %d/%d%s", attempt, cfg.max_attempts, " (이어서)" if resume else "")
        try:
            return _attempt(cfg, today, out_dir, feedback, resume)
        except Rejected as e:
            feedback = str(e)
            log.warning(feedback)
            resume = False
    raise RuntimeError(f"{cfg.max_attempts}번 시도했지만 발행 기준을 통과한 글을 만들지 못했습니다.\n{feedback[:800]}")


def publish_at(cfg: BloggerConfig, now: datetime | None = None) -> str | None:
    """BLOGGER_PUBLISH_TIME(한국 시각 HH:MM)이 아직 오지 않았으면 그 시각(RFC3339), 지났거나 비었으면 None(바로 발행)."""
    if not cfg.publish_time:
        return None
    now = now or datetime.now(KST)
    hour, minute = (int(x) for x in cfg.publish_time.split(":"))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now + timedelta(minutes=5):
        return None
    return target.isoformat()


def _publish(cfg: BloggerConfig, post: dict, out_dir: Path, draft_only: bool) -> dict:
    stage = _load(out_dir / "stage.json")
    post_id = stage.get("draft_id")
    if post_id:
        log.info("만들어 둔 블로거 초안을 이어서 씁니다: %s", post_id)
    else:
        # 같은 제목의 글이 이미 있으면(지난 실행이 발행 직후 멈춘 경우) 다시 올리지 않는다.
        for status in ("live", "scheduled"):
            same = [p for p in api.list_posts(cfg, status=status, limit=50) if p.get("title") == post["title"]]
            if same:
                log.warning("같은 제목의 글이 이미 블로그에 있어 새로 올리지 않습니다: %s", same[0].get("url"))
                return same[0]
        draft = api.create_draft(cfg, post["title"], post["body_html"], post["labels"])
        post_id = draft["id"]
        _mark(out_dir, draft_id=post_id)
        log.info("블로거 초안 저장: %s", post_id)
    if draft_only:
        return {"id": post_id, "status": "DRAFT", "url": ""}
    when = publish_at(cfg)
    result = api.publish(cfg, post_id, when)
    _mark(out_dir, published=True, post_id=str(result.get("id") or post_id), url=result.get("url", ""),
          status=result.get("status", ""))
    return result


def run(cfg: BloggerConfig, draft: bool = False, force: bool = False) -> int:
    today = today_kst()
    setup_logging(cfg, f"blogger-{today}")
    try:
        with _Lock(cfg.log_dir / ".run-blogger.lock"):
            # 글쓰기(수십 분) 전에 구글 로그인·블로그부터 확인하고, 블로그와 발행 이력을 맞춘다
            # (블로그에서 지운 글은 이력에서 빠지므로, 오늘 글을 지우면 다시 실행할 때 새로 쓴다).
            blog_id = api.resolve_blog_id(cfg)
            log.info("블로그 확인: %s", blog_id)
            alive: set[str] | None = None
            try:
                added, removed, alive = sync_history(cfg)
                log.info("발행 목록 동기화: 이력에 없던 %d편 추가, 블로그에서 지운 %d편 제외", added, removed)
            except ExternalAccountError:
                raise
            except Exception as e:  # noqa: BLE001 - 동기화 실패로 발행을 멈추지는 않는다
                log.warning("발행 목록 동기화 실패(계속 진행): %s", e)

            done = published_today(cfg, today)
            if done and not force:
                log.info("오늘(%s)은 이미 발행(예약)했습니다: %s %s", today, done.get("title"), done.get("url"))
                return 0
            out_dir = cfg.output_dir / today
            stage = _load(out_dir / "stage.json")
            if stage.get("published"):
                deleted = alive is not None and str(stage.get("post_id")) not in alive
                if not (force or deleted):
                    log.info("오늘(%s) 글은 이미 발행(예약)했습니다", today)
                    return 0
                log.info("오늘 글을 새로 씁니다(%s)", "블로그에서 지운 글" if deleted else "--force")
                stamp = datetime.now(KST).strftime("%H%M%S")
                shutil.move(str(out_dir), str(out_dir.with_name(f"{out_dir.name}-published-{stamp}")))

            post = produce(cfg, today, out_dir)
            photo_note = _add_images(cfg, post, out_dir)
            _polish(cfg, post, out_dir)
            result = _publish(cfg, post, out_dir, draft_only=draft)
            if draft:
                notify(cfg, f"[{LABEL} 테스트] 초안으로만 저장했습니다(발행 안 함): {post['title']}\n"
                            "블로거 관리 화면 > 글 목록에서 확인하세요." + (f"\n{photo_note}" if photo_note else ""))
                return 0
            url = result.get("url", "")
            scheduled = str(result.get("status", "")).upper() == "SCHEDULED"
            history.append(cfg.history_file, {
                "date": today, "title": post["title"], "url": url, "labels": post["labels"],
                "topic": post.get("topic", ""), "post_id": result.get("id"), "source": "autopost",
                "persona_used": persona.clean_used(post.get("persona_used"), persona.load()),
            })
            when = f" ({cfg.publish_time} 예약)" if scheduled else ""
            notes = "\n".join(n for n in (photo_note, cfg.model_note) if n)
            notify(cfg, f"[{LABEL} 자동발행 완료{when}] {post['title']}\n{url}" + (f"\n{notes}" if notes else ""))
            return 0
    except Exception as e:
        log.exception("블로거 자동 발행 실패")
        notify(cfg, f"[{LABEL} 자동발행 실패] {today}\n{e}")
        return 1
