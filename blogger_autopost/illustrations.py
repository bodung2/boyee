"""본문 생성 그림: Codex(ChatGPT 구독) 이미지 생성 → Codex가 눈으로 검수 → 드라이브에 올려 본문에 넣는다.

- 기본 그림(illustrations)은 일러스트 화풍으로 만든다.
- 커먼즈에서 실제 사진을 못 찾은 자리(post["photo_misses"])에는 실제 사진 같은 느낌의 이미지를 대신 만든다.
  독자가 실제 사진으로 오해하지 않게 캡션에 'AI가 만든 이미지이며 실제 사진이 아님'을 분명히 적는다.
어느 단계든 실패하면 그 그림만 빼고 발행한다.
"""
from __future__ import annotations

import html
import logging
from pathlib import Path
from types import SimpleNamespace

from naver_autopost import codex_image
from naver_autopost.errors import ExternalAccountError

from . import api, hosting, photos, writer
from .config import BloggerConfig

log = logging.getLogger(__name__)

STYLE = ("\nStyle: a clean editorial illustration (flat or soft digital painting), clearly an illustration and "
         "NOT a photorealistic photo. Do not draw a specific real landmark in a way that could be mistaken for a photo.")


PHOTO_STYLE = ("\nStyle: photorealistic, like a natural editorial travel photograph taken in South Korea, realistic "
               "lighting, lens and detail. Korean setting must look authentically Korean (not Japanese or Chinese). "
               "No readable text, signs with writing, logos or watermarks.")
LABELS = {"illustration": "AI-generated illustration", "photo": "AI-generated image (not an actual photo)"}


def figure_html(url: str, want: dict, kind: str = "illustration") -> str:
    e = html.escape
    caption = e(want.get("caption") or "")
    return (f'<figure style="margin:1.5em 0;text-align:center">'
            f'<img src="{e(url)}" alt="{e(want.get("alt") or caption)}" style="max-width:100%;height:auto" '
            f'loading="lazy"><figcaption style="font-size:0.85em;color:#666;margin-top:0.4em">'
            f'{caption + "<br>" if caption else ""}{LABELS[kind]}</figcaption></figure>')


def _image_cfg(cfg: BloggerConfig) -> SimpleNamespace:
    return SimpleNamespace(codex_bin=cfg.codex_bin, codex_model=cfg.image_model,
                           codex_image_timeout=cfg.image_timeout)


def _photo_prompt(want: dict) -> str:
    """실제 사진을 못 찾은 자리의 대체 이미지 프롬프트(글쓴이가 준 fallback_prompt가 있으면 그것)."""
    base = want.get("fallback_prompt") or (
        f"A realistic photograph of {want.get('subject') or want.get('search')} in South Korea. "
        f"{want.get('caption') or ''}")
    return base.strip() + PHOTO_STYLE


def _jobs(cfg: BloggerConfig, post: dict) -> list[tuple[str, dict, str, str]]:
    """(id, want, kind, prompt) 목록: 일러스트 + 실제 사진을 못 찾은 자리의 실사풍 대체 이미지."""
    jobs = [(f"i{i}", w, "illustration", w["prompt"] + STYLE)
            for i, w in enumerate([w for w in (post.get("illustrations") or [])
                                   if isinstance(w, dict) and w.get("prompt")][:cfg.illustrations], 1)]
    if cfg.photo_fallback:
        jobs += [(f"p{i}", w, "photo", _photo_prompt(w))
                 for i, w in enumerate(post.get("photo_misses") or [], 1) if isinstance(w, dict)]
    return jobs


def add_illustrations(cfg: BloggerConfig, post: dict, out_dir: Path) -> tuple[int, str]:
    """그림을 만들어 넣는다. (넣은 장수, 알림용 메모)"""
    jobs = _jobs(cfg, post)
    if not jobs:
        return 0, "생성 그림 0장(글쓴이가 그림 자리를 정하지 않음)"
    if not api.has_scope(cfg, api.DRIVE_SCOPE):
        return 0, "⚠️ 생성 그림을 뺐습니다: 드라이브 권한이 없습니다 → python -m blogger_autopost auth 다시 실행"

    made = []
    for cid, want, kind, prompt in jobs:
        path = out_dir / (f"illust_{cid[1:]}.png" if kind == "illustration" else f"photo_ai_{cid[1:]}.png")
        if not path.exists():
            try:
                codex_image.generate_image(_image_cfg(cfg), prompt, path)
                log.info("생성 그림 %s(%s) 완료", cid, kind)
            except ExternalAccountError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("생성 그림 %s 실패: %s", cid, e)
                continue
        made.append((cid, want, kind, path))
    if not made:
        return 0, "⚠️ 생성 그림을 만들지 못했습니다(로그 확인)"

    verdicts = writer.review_illustrations(cfg, post["title"], [
        {"id": cid, "kind": kind, "path": p,
         "desc": w.get("alt") or w.get("subject") or w.get("prompt", "")[:200]} for cid, w, kind, p in made])
    added, body, problems, counts = 0, post["body_html"], [], {"illustration": 0, "photo": 0}
    for cid, want, kind, path in sorted(made, key=lambda m: -int(m[1].get("section") or 0)):
        verdict = verdicts.get(cid, "missing")
        if verdict != "ok":
            problems.append(f"{cid}: {verdict}")
            continue
        try:
            url = hosting.upload(cfg, path, f"{out_dir.name}-{path.stem}.jpg")
        except hosting.HostingError as e:
            log.warning("그림 올리기 실패: %s", e)
            problems.append(str(e))
            continue
        body = photos.insert(body, int(want.get("section") or 0), figure_html(url, want, kind))
        added += 1
        counts[kind] += 1
    post["body_html"] = body
    note = f"생성 그림 {counts['illustration']}장"
    if counts["photo"]:
        note += f" + 사진 대신 실사풍 생성 이미지 {counts['photo']}장"
    if problems:
        log.warning("빠진 생성 그림: %s", problems)
        note += f" (빠짐: {'; '.join(problems)[:200]})"
    return added, note
