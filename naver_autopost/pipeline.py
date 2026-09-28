"""하루 1편: 글쓰기 → 구조 검증 → 일러스트(ChatGPT·Codex) → Claude 팩트체크 → ChatGPT 팩트체크
→ 핵심 인포그래픽(Codex onepage 스킬) → 이미지 → 네이버 발행 → 이력 기록 → 알림."""
from __future__ import annotations

import json
import logging
import re
import os
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import (codex_image, content, gemini_client, generate, history, images, infographic, notify,
               openai_client, social)
from .config import Config
from .errors import ExternalAccountError

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")


class Rejected(Exception):
    """이번 시도의 글이 발행 기준에 못 미침(다른 주제로 다시 시도)."""


def today_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d")


def setup_logging(cfg: Config, name: str) -> None:
    cfg.log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(cfg.log_dir / f"{name}.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


class _Lock:
    """같은 시간에 두 번 실행되는 것(예: 작업 스케줄러 중복 실행)을 막는다."""

    def __init__(self, path: Path):
        self.path = path

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            age = datetime.now().timestamp() - self.path.stat().st_mtime
            if age < 4 * 3600:
                raise RuntimeError(f"이미 실행 중입니다({self.path}). 멈춘 실행이면 이 파일을 지우세요.")
            self.path.unlink()
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return self

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)


def _load_post(path: Path) -> dict:
    return content.normalize(json.loads(path.read_text(encoding="utf-8")))


def _save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _drop_images(post: dict, names: set[str], out_dir: Path, why: str) -> None:
    if not names:
        return
    log.warning("일러스트 %s 제외(%s)", sorted(names), why)
    post["body_html"] = content.remove_markers(post["body_html"], names)
    post["illustrations"] = [i for i in post.get("illustrations") or [] if i.get("name") not in names]
    for name in names:
        (out_dir / f"{name}.png").unlink(missing_ok=True)


def image_generator(cfg: Config):
    """IMAGE_BACKEND: codex(ChatGPT 구독, 기본) / gemini / openai(API)"""
    return {"codex": codex_image, "gemini": gemini_client, "openai": openai_client}.get(cfg.image_backend, codex_image)


def _make_illustrations(cfg: Config, post: dict, out_dir: Path) -> None:
    failed = set()
    for ill in post.get("illustrations") or []:
        name = ill.get("name", "")
        if (out_dir / f"{name}.png").exists():      # 이어서 실행할 때 이미 만든 그림은 재사용
            continue
        try:
            image_generator(cfg).generate_image(cfg, ill["prompt"], out_dir / f"{name}.png")
            log.info("일러스트 생성(%s): %s", cfg.image_backend, name)
        except ExternalAccountError:
            raise                                    # 잔액·키 문제는 그림만 빼지 말고 멈춘다
        except Exception as e:
            log.warning("일러스트 %s 생성 실패: %s", name, e)
            failed.add(name)
    _drop_images(post, failed, out_dir, "생성 실패")


def _published_issues(post: dict, issues: list[dict]) -> list[dict]:
    """실제로 블로그에 보이는 글(제목·본문·썸네일·카드)에 있는 문장에 대한 지적만 남긴다.
    발행되지 않는 내부 출처 목록(sources)의 표기 지적 때문에 좋은 글을 버리지 않기 위해서다."""
    def norm(text: str) -> str:
        return re.sub(r"\s+", "", text or "")
    visible = norm(" ".join([
        post.get("title", ""), content.html_to_text(post.get("body_html", "")),
        json.dumps(post.get("thumbnail", {}), ensure_ascii=False),
        json.dumps(post.get("card", {}), ensure_ascii=False),
    ]))
    kept = []
    for issue in issues:
        text = norm(issue.get("text", ""))
        if not text or text in visible or text[:30] in visible:
            kept.append(issue)
    return kept


def _gpt_factcheck(cfg: Config, post_path: Path, out_dir: Path) -> dict:
    """ChatGPT 교차검증. 지적이 있으면 Claude가 원문으로 재확인해 반영한 뒤 ChatGPT가 다시 본다."""
    post = _load_post(post_path)
    last_round = cfg.gpt_fix_rounds + 1          # 반영 N번 + 마지막 재검사 1번
    for round_no in range(1, last_round + 1):
        review = openai_client.factcheck(cfg, post)
        _save_json(out_dir / f"gpt_factcheck_{round_no}.json", review)
        if review["verdict"] == "fix":
            visible = _published_issues(post, review.get("issues", []))
            if not visible:
                log.info("ChatGPT 지적 %d건은 모두 발행되지 않는 출처 목록 표기라 통과로 봅니다",
                         len(review.get("issues", [])))
                return post
            review["issues"] = visible
        if review["verdict"] == "pass":
            return post
        if review["verdict"] == "fail" or round_no == last_round:
            raise Rejected(f"ChatGPT 팩트체크 불합격({review['verdict']}): {review.get('summary', '')}\n"
                           + json.dumps(review.get("issues", [])[:8], ensure_ascii=False))
        _save_json(out_dir / "gpt_review.json", review)
        applied = generate.apply_gpt_review(cfg, out_dir, round_no)
        log.info("ChatGPT 지적 반영: 적용 %d건, 반박 %d건",
                 len(applied.get("applied", [])), len(applied.get("rejected", [])))
        post = _load_post(post_path)
        _save_json(post_path, post)
    return post


def _stage(out_dir: Path) -> dict:
    path = out_dir / "stage.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except json.JSONDecodeError:
        return {}


def _mark(out_dir: Path, **flags) -> None:
    _save_json(out_dir / "stage.json", {**_stage(out_dir), **flags})


def _attempt(cfg: Config, today: str, out_dir: Path, feedback: str, resume: bool = False) -> dict:
    """글 1편을 발행 가능한 상태로 만든다. resume이면 지난 실행이 멈춘 단계부터 이어서 한다
    (예: OpenAI 잔액 부족으로 멈췄을 때 이미 쓴 글·통과한 검수를 다시 하지 않음)."""
    post_path = out_dir / "post.json"
    stage = _stage(out_dir) if resume else {}
    if not stage.get("written"):
        generate.write_post(cfg, out_dir, today, feedback)
        post = _load_post(post_path)
        _save_json(post_path, post)
        errors = content.validate(post, cfg.profile)
        if errors:
            raise Rejected("구조 검증 실패:\n- " + "\n- ".join(errors))
        _mark(out_dir, written=True)
    else:
        log.info("이미 쓴 글을 이어서 처리합니다: %s", _load_post(post_path)["title"])
    post = _load_post(post_path)

    if cfg.profile.illustrations and not stage.get("illustrated"):
        post["illustrations"] = (post.get("illustrations") or [])[:cfg.illustration_count]
        extra = {m.group(1) for m in content.IMAGE_MARKER.finditer(post["body_html"])} - {"card", infographic.NAME} \
            - {i.get("name") for i in post["illustrations"]}
        post["body_html"] = content.remove_markers(post["body_html"], extra)
        _make_illustrations(cfg, post, out_dir)
        _save_json(post_path, post)
        _mark(out_dir, illustrated=True)

    if not stage.get("claude_pass"):
        fc = generate.factcheck(cfg, out_dir)
        post = _load_post(post_path)
        bad = {name for name, verdict in (fc.get("images") or {}).items() if not str(verdict).startswith("ok")}
        _drop_images(post, bad, out_dir, "검수 탈락")
        _save_json(post_path, post)
        if fc.get("verdict") != "pass":
            raise Rejected(f"Claude 팩트체크 불합격: {fc.get('summary', '')}\n"
                           + json.dumps(fc.get("issues", [])[:10], ensure_ascii=False))
        log.info("Claude 팩트체크 통과: %s", fc.get("summary", ""))
        _mark(out_dir, claude_pass=True)

    if cfg.gpt_factcheck:
        post = _gpt_factcheck(cfg, post_path, out_dir)
        log.info("ChatGPT 팩트체크 통과")

    errors = content.validate(post, cfg.profile)
    if errors:
        raise Rejected("팩트체크 수정 후 구조 검증 실패:\n- " + "\n- ".join(errors))
    return post


def _wait_for_limit(cfg: Config, err: "generate.ClaudeLimitError", deadline: datetime) -> None:
    """Claude 사용 한도가 풀릴 때까지 기다린다. 너무 오래 걸리면 그날은 멈추고 알린다."""
    resume_at = err.reset_at + timedelta(minutes=2)
    if resume_at > deadline:
        raise generate.GenerationError(
            f"{err} — {err.reset_at:%H:%M}에 풀리지만 최대 대기({cfg.limit_wait_max_min}분)를 넘어 오늘은 멈춥니다. "
            "다음 실행 때 멈춘 단계부터 이어서 합니다.")
    msg = (f"[{cfg.profile.label}] Claude 사용 한도에 걸려 {err.reset_at:%H:%M}(한국 시각)에 풀린 뒤 "
           f"{resume_at:%H:%M}부터 이어서 진행합니다.")
    log.warning(msg)
    notify.send(cfg, msg)
    while (left := (resume_at - datetime.now(KST)).total_seconds()) > 0:
        _sleep(min(left, 300))


_sleep = time.sleep


def produce(cfg: Config, today: str, out_dir: Path) -> dict:
    """발행 가능한 post를 만든다. 떨어지면 최대 MAX_ATTEMPTS번까지 새로 쓴다."""
    ready = out_dir / "ready.json"
    if ready.exists() and (out_dir / "post.json").exists():
        post = _load_post(out_dir / "post.json")
        if not content.validate(post, cfg.profile):
            log.info("검수를 통과한 오늘 글이 이미 있어 재사용합니다: %s", post["title"])
            return post

    feedback = ""
    resume = _stage(out_dir).get("written") and (out_dir / "post.json").exists()
    deadline = datetime.now(KST) + timedelta(minutes=cfg.limit_wait_max_min)
    for attempt in range(1, cfg.max_attempts + 1):
        if not resume and out_dir.exists() and any(out_dir.iterdir()):
            stamp = datetime.now(KST).strftime("%H%M%S")
            shutil.move(str(out_dir), str(out_dir.with_name(f"{out_dir.name}-rejected-{stamp}")))
        while True:
            log.info("[%s] 글쓰기 시도 %d/%d%s", cfg.profile.name, attempt, cfg.max_attempts,
                     " (이어서)" if resume else "")
            try:
                post = _attempt(cfg, today, out_dir, feedback, resume=bool(resume))
            except generate.ClaudeLimitError as e:
                _wait_for_limit(cfg, e, deadline)
                resume = True  # 한도가 풀리면 같은 글을 멈춘 단계부터 이어서 한다
                continue
            except Rejected as e:
                feedback = str(e)
                log.warning(feedback)
                post = None
            break
        if post is None:
            resume = False
            continue
        _save_json(ready, {"title": post["title"], "at": datetime.now(KST).isoformat()})
        return post
    raise RuntimeError(f"{cfg.max_attempts}번 시도했지만 발행 기준을 통과한 글을 만들지 못했습니다.\n{feedback[:800]}")


def add_infographic(cfg: Config, post: dict, out_dir: Path) -> bool:
    """팩트체크를 통과한 최종 글로 핵심 인포그래픽을 만들어 '한 줄 요약' 앞에 넣는다.
    만들지 못하면 인포그래픽만 빼고 발행은 계속한다(False)."""
    if not cfg.infographic:
        return True
    path = out_dir / f"{infographic.NAME}.png"
    if not path.exists():
        try:
            infographic.generate(cfg, post, path)
            log.info("인포그래픽 생성(codex %s 스킬)", cfg.infographic_skill)
        except Exception as e:  # noqa: BLE001 - 사용 한도·로그인 문제여도 글은 발행한다
            log.warning("인포그래픽 생성 실패(인포그래픽 없이 발행): %s", e)
            return False
    post["body_html"] = infographic.insert_marker(post["body_html"])
    _save_json(out_dir / "post.json", post)
    return True


def render_images(cfg: Config, post: dict, out_dir: Path) -> dict[str, Path]:
    names = post.get("image_names") or {}

    def fname(key: str, default: str) -> Path:
        stem = "".join(ch for ch in str(names.get(key) or default) if ch not in '\\/:*?"<>|').strip() or default
        return out_dir / f"{stem}.png"

    if cfg.profile.thumbnail_style == "childhood":
        tone = images.childhood_tone(post.get("domain"))
        imgs = {
            "thumbnail": images.make_thumbnail_childhood(post["thumbnail"], post.get("domain"),
                                                         fname("thumbnail", "thumbnail")),
            "card": images.make_card(post["card"], fname("card", "card"), tone=tone),
        }
    else:
        imgs = {
            "thumbnail": images.make_thumbnail(post["thumbnail"], fname("thumbnail", "thumbnail")),
            "card": images.make_card(post["card"], fname("card", "card")),
        }
    for ill in post.get("illustrations") or []:
        path = out_dir / f"{ill.get('name')}.png"
        if path.exists():
            imgs[ill["name"]] = path
    info = out_dir / f"{infographic.NAME}.png"
    if info.exists():
        thumb_name = str(names.get("thumbnail") or "")
        default = (thumb_name.replace("썸네일", "인포그래픽") if "썸네일" in thumb_name
                   else f"{thumb_name}_인포그래픽" if thumb_name else infographic.NAME)
        named = fname(infographic.NAME, default)
        if named == info:
            named = out_dir / f"{infographic.NAME}_{images.INFOGRAPHIC_WIDTH}.png"
        # 원본(고해상도)은 두고, 올릴 파일만 가로 600px로 줄인다(세로는 비율대로).
        imgs[infographic.NAME] = images.fit_width(info, named, images.INFOGRAPHIC_WIDTH)
    # 본문에 표시가 남아 있는데 파일이 없는 이미지는 지운다(발행 중 오류 방지).
    missing = {m.group(1) for m in content.IMAGE_MARKER.finditer(post["body_html"])} - set(imgs)
    post["body_html"] = content.remove_markers(post["body_html"], missing)
    return imgs


def _social_drafts(cfg: Config, out_dir: Path, url: str) -> str:
    """블로그 발행 직후 인스타·쓰레드 초안을 만든다(저녁 예약 작업이 발행). 실패해도 블로그 발행 결과에는 영향 없음."""
    if not cfg.social_draft:
        return ""
    try:
        social.draft(cfg, out_dir, url)
    except Exception as e:  # noqa: BLE001 - 저녁 발행 때 다시 만들어 본다
        log.warning("소셜 초안 실패: %s", e)
        return f"\n⚠️ 소셜 초안을 만들지 못했습니다(저녁 발행 때 다시 시도): {str(e)[:200]}"
    return f"\n📱 인스타·쓰레드 초안 준비 → 저녁 예약 시각에 발행(고치려면 {out_dir / 'social.json'})"


def _preflight(cfg: Config) -> None:
    if not cfg.blog_id:
        raise RuntimeError(".env에 NAVER_BLOG_ID가 없습니다")
    if cfg.profile.illustrations and cfg.illustration_count > 0:
        if cfg.image_backend == "codex" and not shutil.which(cfg.codex_bin):
            raise RuntimeError("Codex CLI를 찾지 못했습니다(ChatGPT 구독 그림 생성에 필요)")
        if cfg.image_backend == "gemini" and not cfg.gemini_api_key:
            raise RuntimeError(".env에 GEMINI_API_KEY가 없습니다(Gemini 일러스트 생성에 필요)")
        if cfg.image_backend == "openai" and not cfg.openai_api_key:
            raise RuntimeError(".env에 OPENAI_API_KEY가 없습니다(IMAGE_BACKEND=openai)")
    if cfg.gpt_factcheck:
        has_codex = cfg.factcheck_backend == "codex" and shutil.which(cfg.codex_bin)
        if not has_codex and not cfg.openai_api_key:
            raise RuntimeError("ChatGPT 팩트체크에 쓸 Codex CLI(ChatGPT 로그인)도 OPENAI_API_KEY도 없습니다")


def retry_note(cfg: Config, now: datetime | None = None) -> str:
    """아침 실패 알림에 붙이는 안내: 재시도 시각 전이면 그때 자동으로 한 번 더 돈다고 알려 준다.
    (재시도는 예약 작업이 같은 명령을 다시 실행하는 것. 이미 발행했으면 바로 끝나고, 멈춘 단계부터 이어서 한다)"""
    if not cfg.retry_time or cfg.retry_time.lower() == "off":
        return ""
    now = now or datetime.now(KST)
    try:
        hh, mm = (int(x) for x in cfg.retry_time.split(":"))
    except ValueError:
        return ""
    if (now.hour, now.minute) >= (hh, mm):
        return "\n(오늘 자동 재시도 시각이 지나 더는 시도하지 않습니다. 원인을 해결한 뒤 직접 실행하세요)"
    return f"\n→ {cfg.retry_time}에 자동으로 한 번 더 시도합니다(멈춘 단계부터 이어서)."


def run(cfg: Config, dry_run: bool = False, force: bool = False) -> int:
    # 브라우저 자동화는 무거우므로 필요할 때만 불러온다.
    from . import publisher

    today = today_kst()
    label = f"{cfg.profile.label}"
    setup_logging(cfg, f"{cfg.profile.name}-{today}")
    try:
        with _Lock(cfg.log_dir / f".run-{cfg.profile.name}.lock"):
            done = history.published_on(cfg.history_file, today)
            if done and not force:
                log.info("오늘(%s)은 이미 발행했습니다: %s", today, done["url"])
                return 0
            _preflight(cfg)
            # 글쓰기(30분+) 전에 네이버 로그인부터 확인한다.
            if not publisher.check_session(cfg):
                raise publisher.SessionExpired(
                    "네이버 로그인이 풀려 있습니다. `python -m naver_autopost login`으로 다시 로그인하세요"
                    "('로그인 상태 유지' 체크).")

            # 직접 쓴 글까지 이력에 반영(주제 중복 피하기·내부 링크 후보). 실패해도 발행은 계속한다.
            try:
                log.info("발행 목록 동기화: %s", history.sync(cfg.history_file, cfg.blog_id))
            except Exception as e:
                log.warning("발행 목록 동기화 실패(계속 진행): %s", e)

            out_dir = cfg.output_dir / today
            # 발행 버튼은 눌렀지만 주소를 확인하지 못해 기록이 빠진 경우: 블로그 목록에 같은 제목이 있으면
            # 다시 발행하지 않고 기록만 바로잡는다(중복 발행 방지).
            if not force and (out_dir / "ready.json").exists() and (out_dir / "post.json").exists():
                ready_post = _load_post(out_dir / "post.json")
                found = history.find_published(cfg.history_file, today, ready_post["title"])
                if found:
                    history.upsert(cfg.history_file, history.autopost_entry(today, ready_post, found["url"]))
                    log.info("오늘 글은 이미 블로그에 있습니다(기록만 바로잡음): %s", found["url"])
                    return 0
            post = produce(cfg, today, out_dir)
            info_ok = add_infographic(cfg, post, out_dir)
            imgs = render_images(cfg, post, out_dir)
            post["blog_category"] = cfg.category_for(post.get("lane"))
            log.info("카테고리: %s (레인 %s)", post["blog_category"] or "(기본)", post.get("lane", "-"))

            last_error: Exception | None = None
            for attempt in (1, 2):
                try:
                    url = publisher.publish(cfg, post, imgs, dry_run=dry_run)
                    break
                except (publisher.SessionExpired, publisher.PublishUncertain):
                    raise
                except Exception as e:
                    last_error = e
                    log.warning("발행 시도 %d 실패: %s", attempt, e)
            else:
                raise RuntimeError(f"네이버 발행 실패: {last_error}")

            cat_note = f"카테고리: {post.get('blog_category') or '(기본)'}"
            if post.get("_category_ok") is False:
                cat_note += " ⚠️ 이 카테고리를 찾지 못해 기본 카테고리로 들어갔습니다"
            if not info_ok:
                cat_note += "\n⚠️ 인포그래픽을 만들지 못해 빼고 올렸습니다(로그 확인)"
            if dry_run:
                notify.send(cfg, f"[{label} 자동발행 테스트] 최종 발행 직전까지 확인했습니다: {post['title']}\n{cat_note}")
                return 0
            history.append(cfg.history_file, {
                "date": today, "title": post["title"], "url": url, "topic": post.get("topic", ""),
                "category": post.get("blog_category", ""),
                "lane": post.get("lane", ""), "cluster": post.get("cluster", ""), "domain": post.get("domain"),
                "tags": post.get("tags", []), "source": "autopost",
            })
            notify.send(cfg, f"[{label} 자동발행 완료] {post['title']}\n{url}\n{cat_note}{_social_drafts(cfg, out_dir, url)}")
            return 0
    except Exception as e:
        log.exception("자동 발행 실패")
        notify.send(cfg, f"[{label} 자동발행 실패] {today}\n{e}{retry_note(cfg)}")
        return 1
