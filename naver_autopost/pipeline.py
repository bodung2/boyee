"""하루 1편: 글쓰기 → 구조 검증 → 팩트체크 → 이미지 → 네이버 발행 → 이력 기록 → 알림."""
from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import content, generate, history, images, notify
from .config import Config

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")


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


def _save_post(path: Path, post: dict) -> None:
    path.write_text(json.dumps(post, ensure_ascii=False, indent=2), encoding="utf-8")


def _ready_post(out_dir: Path) -> dict | None:
    """이전 실행에서 팩트체크까지 통과했지만 발행 전에 멈춘 글이 있으면 다시 쓴다."""
    post_path, fc_path = out_dir / "post.json", out_dir / "factcheck.json"
    if not (post_path.exists() and fc_path.exists()):
        return None
    try:
        if json.loads(fc_path.read_text(encoding="utf-8")).get("verdict") != "pass":
            return None
        post = _load_post(post_path)
    except (json.JSONDecodeError, OSError):
        return None
    return None if content.validate(post) else post


def produce(cfg: Config, today: str, out_dir: Path) -> dict:
    """발행 가능한 post를 만든다. 실패하면 최대 MAX_ATTEMPTS번까지 새로 쓴다."""
    ready = _ready_post(out_dir)
    if ready:
        log.info("팩트체크를 통과한 오늘 글이 이미 있어 재사용합니다: %s", ready["title"])
        return ready

    feedback = ""
    for attempt in range(1, cfg.max_attempts + 1):
        if out_dir.exists() and any(out_dir.iterdir()):
            stamp = datetime.now(KST).strftime("%H%M%S")
            shutil.move(str(out_dir), str(out_dir.with_name(f"{out_dir.name}-rejected-{stamp}")))
        log.info("글쓰기 시도 %d/%d", attempt, cfg.max_attempts)
        post_path = generate.write_post(cfg, out_dir, today, feedback)
        post = _load_post(post_path)
        _save_post(post_path, post)

        errors = content.validate(post)
        if errors:
            feedback = "구조 검증 실패:\n- " + "\n- ".join(errors)
            log.warning(feedback)
            continue

        fc = generate.factcheck(cfg, out_dir)
        post = _load_post(post_path)          # 팩트체커가 고친 내용 반영
        _save_post(post_path, post)
        if fc.get("verdict") != "pass":
            feedback = f"팩트체크 불합격: {fc.get('summary', '')}\n" + json.dumps(fc.get("issues", [])[:10], ensure_ascii=False)
            log.warning(feedback)
            continue
        errors = content.validate(post)
        if errors:
            feedback = "팩트체크 수정 후 구조 검증 실패:\n- " + "\n- ".join(errors)
            log.warning(feedback)
            continue
        log.info("팩트체크 통과: %s", fc.get("summary", ""))
        return post
    raise RuntimeError(f"{cfg.max_attempts}번 시도했지만 발행 기준을 통과한 글을 만들지 못했습니다.\n{feedback[:800]}")


def render_images(post: dict, out_dir: Path) -> dict[str, Path]:
    names = post.get("image_names") or {}

    def fname(key: str, default: str) -> Path:
        stem = "".join(ch for ch in str(names.get(key) or default) if ch not in '\\/:*?"<>|').strip() or default
        return out_dir / f"{stem}.png"

    return {
        "thumbnail": images.make_thumbnail(post["thumbnail"], fname("thumbnail", "thumbnail")),
        "card": images.make_card(post["card"], fname("card", "card")),
    }


def run(cfg: Config, dry_run: bool = False, force: bool = False) -> int:
    # 브라우저 자동화는 무거우므로 필요할 때만 불러온다.
    from . import publisher

    today = today_kst()
    setup_logging(cfg, today)
    try:
        with _Lock(cfg.log_dir / ".run.lock"):
            done = history.published_on(cfg.history_file, today)
            if done and not force:
                log.info("오늘(%s)은 이미 발행했습니다: %s", today, done["url"])
                return 0

            out_dir = cfg.output_dir / today
            post = produce(cfg, today, out_dir)
            imgs = render_images(post, out_dir)

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

            if dry_run:
                notify.send(cfg, f"[자동발행 테스트] 발행 직전까지 확인했습니다: {post['title']}")
                return 0
            history.append(cfg.history_file, {
                "date": today, "title": post["title"], "url": url, "topic": post.get("topic", ""),
                "lane": post.get("lane", ""), "tags": post.get("tags", []), "source": "autopost",
            })
            notify.send(cfg, f"[자동발행 완료] {post['title']}\n{url}")
            return 0
    except Exception as e:
        log.exception("자동 발행 실패")
        notify.send(cfg, f"[자동발행 실패] {today}\n{e}")
        return 1
