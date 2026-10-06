"""글 끝에 넣을 '한 장 인포그래픽'(Codex onepage 스킬)을 만들고, 그 인포그래픽을 글의 대표 이미지로 쓴다.

- 팩트체크를 통과한 최종 글로 만든다(글에 없는 사실·숫자는 넣지 않게 한다).
- Codex가 인포그래픽을 직접 보고 글자·숫자가 글과 맞는지 검수한다. 틀리면 이유를 반영해 다시 만든다.
- 블로거는 본문의 '첫 번째 그림'을 대표 이미지(검색·공유·RSS 썸네일, Pinterest 핀 그림)로 쓴다.
  그래서 본문 맨 앞에 화면에는 보이지 않는 인포그래픽 사본을 하나 두고, 실제로 보이는 인포그래픽은 글 끝에 둔다.
- 어느 단계든 실패하면 인포그래픽 없이 발행한다(대표 이미지는 예전처럼 첫 그림).
"""
from __future__ import annotations

import html
import logging
import re
from pathlib import Path
from types import SimpleNamespace

from naver_autopost import codex_image
from naver_autopost.content import html_to_text
from naver_autopost.errors import ExternalAccountError

from . import api, hosting, writer
from .config import BloggerConfig

log = logging.getLogger(__name__)
COVER_CLASS = "kb-cover"
FIGURE_CLASS = "kb-infographic"
MAX_BODY_CHARS = 7000

PROMPT = """Use the ${skill} skill to make ONE single-page infographic image that summarizes the English blog post
below at a glance. It will be shown at the end of the post and used as the post's Pinterest pin.

Rules:
- Portrait 2:3 layout (about 1000x1500). Clean, readable at phone size, generous spacing.
- All text in English, spelled exactly as in the post. Big clear title, then 4-6 key points
  (numbers, steps, comparisons) from the post, then a short source line if the post names sources.
- Small footer text exactly: "Korea, Explained"
- Use ONLY facts, numbers, dates and names that appear in the post below. Do not add, round or guess anything.
- No logos (other than the footer text), no URLs, no watermark, no photos of real people.
- Save the finished image as infographic.png in the current working directory.
  If you make it with the built-in image generation tool, just leave the file where the tool saved it.
- Do not ask questions. Finish in one go and stop.
{retry}
--- POST ---
Title: {title}

{body}
"""

REVIEW_PROMPT = """INFOGRAPHIC REVIEW. The attached image is an infographic made for the English blog post below.
Read every word and number in the image and compare it with the post.
It is "ok" only if ALL are true:
- every number, date, name and claim in the image appears in the post (no invented or changed facts),
- the English text is spelled correctly and is readable (no garbled letters or pseudo-text),
- the layout is clean and not cut off.
Output ONLY one JSON object (no code fence): {{"verdict": "ok"}} or {{"verdict": "<short reason>"}}

--- POST ---
Title: {title}

{body}
"""


def _post_text(post: dict) -> str:
    body = re.sub(r"<figure\b.*?</figure>", "", post.get("body_html", ""), flags=re.I | re.S)
    return html_to_text(body)[:MAX_BODY_CHARS]


def build_prompt(cfg: BloggerConfig, post: dict, reason: str = "") -> str:
    retry = (f"\nA previous version was rejected because: {reason}. Fix that.\n" if reason else "")
    return PROMPT.replace("${skill}", f"${cfg.infographic_skill.lstrip('$')}").format(
        retry=retry, title=post.get("title", ""), body=_post_text(post))


def review(cfg: BloggerConfig, post: dict, path: Path) -> str:
    prompt = REVIEW_PROMPT.format(title=post.get("title", ""), body=_post_text(post))
    result = writer._extract_json(writer._codex(cfg, prompt, None, "read-only", cfg.codex_timeout, images=[path]))
    verdict = str(result.get("verdict", "")).strip()
    return "ok" if verdict.lower() == "ok" else (verdict or "no verdict")


def _image_cfg(cfg: BloggerConfig) -> SimpleNamespace:
    return SimpleNamespace(codex_bin=cfg.codex_bin, codex_model=cfg.image_model,
                           codex_image_timeout=cfg.infographic_timeout)


def make(cfg: BloggerConfig, post: dict, out_dir: Path) -> Path | None:
    """검수를 통과한 인포그래픽 파일. 끝내 못 만들면 None."""
    reason = ""
    for attempt in range(1, max(cfg.image_tries, 1) + 1):
        path = out_dir / ("infographic.png" if attempt == 1 else f"infographic_try{attempt}.png")
        if not path.exists():
            try:
                codex_image.run_for_image(_image_cfg(cfg), build_prompt(cfg, post, reason), path,
                                          codex_image._to_png, cfg.infographic_timeout, what="인포그래픽")
            except ExternalAccountError:
                raise
            except Exception as e:  # noqa: BLE001
                reason = f"generation failed: {str(e)[:100]}"
                log.warning("인포그래픽 %d번째 생성 실패: %s", attempt, e)
                continue
        verdict = review(cfg, post, path)
        if verdict == "ok":
            log.info("인포그래픽 검수 통과(%d번째)", attempt)
            return path
        reason = verdict
        log.warning("인포그래픽 %d번째 검수 탈락: %s", attempt, verdict)
    return None


def _figure(url: str, title: str) -> str:
    e = html.escape
    return (f'<figure class="{FIGURE_CLASS}" style="margin:2em 0;text-align:center">'
            f'<img src="{e(url)}" alt="{e(title)} — infographic summary" style="max-width:100%;height:auto" '
            f'loading="lazy"><figcaption style="font-size:0.85em;color:#666;margin-top:0.4em">'
            f'At a glance: {e(title)}</figcaption></figure>')


def _cover(url: str, title: str) -> str:
    return (f'<div class="{COVER_CLASS}" style="display:none">'
            f'<img src="{html.escape(url)}" alt="{html.escape(title)}"></div>')


_SOURCES_H2 = re.compile(r"<h2\b[^>]*>(?:(?!</h2>).)*(source|reference|further reading)(?:(?!</h2>).)*</h2>",
                         re.I | re.S)
_COVER_BLOCK = re.compile(rf'<div\b[^>]*class=["\']{COVER_CLASS}["\'][^>]*>.*?</div\s*>', re.I | re.S)
_FIGURE_BLOCK = re.compile(rf'<figure\b[^>]*class=["\']{FIGURE_CLASS}["\'][^>]*>.*?</figure\s*>', re.I | re.S)


def place(body: str, url: str, title: str) -> str:
    """보이는 인포그래픽은 글 끝(출처 소제목이 있으면 그 앞)에, 대표 이미지용 사본은 맨 앞에. 여러 번 해도 하나만."""
    body = _FIGURE_BLOCK.sub("", _COVER_BLOCK.sub("", body))
    fig = _figure(url, title)
    heads = list(_SOURCES_H2.finditer(body))
    body = body[:heads[-1].start()] + fig + body[heads[-1].start():] if heads else body.rstrip() + fig
    return _cover(url, title) + body


def add(cfg: BloggerConfig, post: dict, out_dir: Path) -> tuple[int, str]:
    if not cfg.infographic:
        return 0, ""
    if not api.has_scope(cfg, api.DRIVE_SCOPE):
        return 0, "⚠️ 인포그래픽을 뺐습니다: 드라이브 권한이 없습니다 → python -m blogger_autopost auth 다시 실행"
    path = make(cfg, post, out_dir)
    if not path:
        return 0, "⚠️ 인포그래픽이 검수를 통과하지 못해 빼고 올렸습니다(로그 확인)"
    url = hosting.upload(cfg, path, f"{out_dir.name}-infographic.jpg")
    post["body_html"] = place(post["body_html"], url, post.get("title", ""))
    return 1, "인포그래픽 1장(대표 이미지)"
