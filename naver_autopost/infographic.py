"""'한 줄 요약' 바로 앞에 넣을 한 장짜리 핵심 인포그래픽을 Codex(ChatGPT 구독)의 onepage 스킬로 만든다.

팩트체크를 모두 통과한 최종 글로 만들고, 글에 없는 사실은 넣지 않게 한다.
만들지 못하면 인포그래픽만 빼고 발행은 계속한다.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

from . import codex_image, content
from .config import Config

NAME = "infographic"
MARKER = f"<p>[[IMAGE:{NAME}]]</p>"
MAX_BODY_CHARS = 6000

_ONELINE_BLOCK = re.compile(r'<div\b[^>]*data-block="oneline"', re.I)
_ONELINE_PARA = re.compile(r"<p>\s*[📌✅🔑⭐]?\s*\[?\s*한\s*줄\s*(요약|정리)")
_RELATED_BLOCK = re.compile(r'<div\b[^>]*data-block="related"', re.I)

PROMPT = """Use the ${skill} skill ("onepage 한 장 핵심 인포그래픽") to make ONE single-page infographic image
that summarizes the Korean blog post below at a glance.

Rules:
- Write every word in the image in Korean, exactly as spelled in the post.
- Use ONLY facts, numbers, dates and names that appear in the post below. Do not add, round or guess anything.
- No logos, no watermark, no URLs. Put the source line at the bottom if the post gives one.
- Save the finished image as infographic.png in the current working directory.
  If you make it with the built-in image generation tool, just leave the file where the tool saved it.
- Do not ask questions. Finish in one go and stop.

--- POST ---
제목: {title}

요약 카드: {card_title}
{card_bullets}

챕터: {chapters}

한 줄 요약: {oneline}

출처 표기: {footer}

본문:
{body}
"""


def insert_marker(body_html: str) -> str:
    """'한 줄 요약' 바로 앞에 인포그래픽 자리를 넣는다(없으면 '함께 보면 좋은 글' 앞, 그것도 없으면 맨 끝)."""
    if f"[[IMAGE:{NAME}]]" in body_html:
        return body_html
    for pattern in (_ONELINE_BLOCK, _ONELINE_PARA, _RELATED_BLOCK):
        m = pattern.search(body_html)
        if m:
            return body_html[:m.start()] + MARKER + body_html[m.start():]
    return body_html + MARKER


def _oneline_text(body_html: str) -> str:
    m = re.search(r'<div\b[^>]*data-block="oneline"[^>]*>(.*?)</div>', body_html, re.I | re.S)
    return content.html_to_text(m.group(1)) if m else ""


def build_prompt(skill: str, post: dict) -> str:
    body = post.get("body_html", "")
    card = post.get("card") or {}
    chapters = [content.html_to_text(h) for h in re.findall(r"<h2>(.*?)</h2>", body, re.S)]
    text = content.html_to_text(content.IMAGE_MARKER.sub("", body))
    return PROMPT.replace("${skill}", f"${skill.lstrip('$')}").format(
        title=post.get("title", ""),
        card_title=card.get("title", ""),
        card_bullets="\n".join(f"- {b}" for b in card.get("bullets") or []),
        chapters=" / ".join(html.unescape(c) for c in chapters),
        oneline=_oneline_text(body),
        footer=card.get("footer", ""),
        body=text[:MAX_BODY_CHARS],
    )


def generate(cfg: Config, post: dict, out: Path) -> Path:
    return codex_image.run_for_image(cfg, build_prompt(cfg.infographic_skill, post), out,
                                     codex_image._to_png, cfg.infographic_timeout, what="인포그래픽")
