"""본문 생성 그림: Codex(ChatGPT 구독) 이미지 생성 → Codex가 눈으로 검수 → 드라이브에 올려 본문에 넣는다.

실제 사진처럼 보이면 독자가 '한국의 실제 모습'으로 오해할 수 있어 일러스트 화풍으로 만들고,
캡션에 AI로 만든 그림임을 적는다. 어느 단계든 실패하면 그 그림만 빼고 발행한다.
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


def figure_html(url: str, want: dict) -> str:
    e = html.escape
    caption = e(want.get("caption") or "")
    return (f'<figure style="margin:1.5em 0;text-align:center">'
            f'<img src="{e(url)}" alt="{e(want.get("alt") or caption)}" style="max-width:100%;height:auto" '
            f'loading="lazy"><figcaption style="font-size:0.85em;color:#666;margin-top:0.4em">'
            f'{caption + "<br>" if caption else ""}AI-generated illustration</figcaption></figure>')


def _image_cfg(cfg: BloggerConfig) -> SimpleNamespace:
    return SimpleNamespace(codex_bin=cfg.codex_bin, codex_model=cfg.image_model,
                           codex_image_timeout=cfg.image_timeout)


def add_illustrations(cfg: BloggerConfig, post: dict, out_dir: Path) -> tuple[int, str]:
    """post["illustrations"]대로 그림을 만들어 넣는다. (넣은 장수, 알림용 메모)"""
    wants = [w for w in (post.get("illustrations") or []) if isinstance(w, dict) and w.get("prompt")]
    wants = wants[:cfg.illustrations]
    if not wants:
        return 0, "생성 그림 0장(글쓴이가 그림 자리를 정하지 않음)"
    if not api.has_scope(cfg, api.DRIVE_SCOPE):
        return 0, "⚠️ 생성 그림을 뺐습니다: 드라이브 권한이 없습니다 → python -m blogger_autopost auth 다시 실행"

    made = []
    for i, want in enumerate(wants, 1):
        path = out_dir / f"illust_{i}.png"
        if not path.exists():
            try:
                codex_image.generate_image(_image_cfg(cfg), want["prompt"] + STYLE, path)
                log.info("그림 %d 생성", i)
            except ExternalAccountError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("그림 %d 생성 실패: %s", i, e)
                continue
        made.append((f"i{i}", want, path))
    if not made:
        return 0, "⚠️ 생성 그림을 만들지 못했습니다(로그 확인)"

    verdicts = writer.review_illustrations(cfg, post["title"],
                                           [{"id": cid, "desc": w.get("alt") or w["prompt"][:200], "path": p}
                                            for cid, w, p in made])
    added, body, problems = 0, post["body_html"], []
    for cid, want, path in sorted(made, key=lambda m: -int(m[1].get("section") or 0)):
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
        body = photos.insert(body, int(want.get("section") or 0), figure_html(url, want))
        added += 1
    post["body_html"] = body
    note = f"생성 그림 {added}장"
    if problems:
        log.warning("빠진 생성 그림: %s", problems)
        note += f" (빠짐: {'; '.join(problems)[:200]})"
    return added, note
