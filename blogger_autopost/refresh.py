"""이미 발행·예약한 글을 새 양식으로 바꾼다(글 내용은 그대로 두고 덧붙이기만 한다).

- 사진 1장(커먼즈 실제 사진, 없으면 실사풍 생성 이미지) + 생성 그림 2장 — 글에 그림이 이미 있으면 건너뜀
- 페르소나 경험 0~2문단 + 끝의 "내 생각" 문단(기존 문장은 고치지 않고 사이에 끼워 넣기만 한다)
- 글 끝 원페이지 인포그래픽(대표 이미지) + 관련 글 링크

기본은 미리보기(output/blogger/refresh-<글ID>/preview.html)만 만들고, --apply를 주면 바꾸기 전 본문을
output/blogger/backup/<시각>/<글ID>.html에 저장한 뒤 블로그 글을 고친다. 미리보기 때 만든 그림은 --apply에서 다시 쓴다.
"""
from __future__ import annotations

import dataclasses
import html
import json
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path

from naver_autopost import history, persona
from naver_autopost.content import html_to_text
from naver_autopost.pipeline import KST, today_kst

from . import api, fixposts, infographic, pipeline, seo, writer
from .config import BloggerConfig

log = logging.getLogger(__name__)

_COVER = re.compile(rf'<div\b[^>]*class=["\']{infographic.COVER_CLASS}["\'][^>]*>.*?</div\s*>', re.I | re.S)
_INFO = re.compile(rf'<figure\b[^>]*class=["\']{infographic.FIGURE_CLASS}["\'][^>]*>.*?</figure\s*>', re.I | re.S)
_RELATED = re.compile(rf'<div\b[^>]*class=["\']{seo.RELATED_CLASS}["\'][^>]*>.*?</ul>\s*</div\s*>', re.I | re.S)
_PARA = re.compile(r"<p\b[^>]*>(.*?)</p\s*>", re.I | re.S)
_H2 = re.compile(r"<h2\b[^>]*>(.*?)</h2\s*>", re.I | re.S)

PLAN_PROMPT = """REFRESH PLAN. Below is a blog post that is ALREADY PUBLISHED on my Google Blogger blog "Korea, Explained".
I am updating it to my blog's new format. Do NOT rewrite it; plan only additions. Do not use web search.

[Title] {title}
[Labels] {labels}
[Section headings (h2), numbered]
{headings}
[Body text]
{text}
{persona}
Output ONLY one JSON object (no code fence), exactly this shape:
{{
  "topic": "one-line description of the topic",
  "illustrations": [{{"section": 1, "prompt": "detailed English image-generation prompt", "alt": "alt text",
                     "caption": "short caption"}}],
  "photos": [{{"section": 2, "subject": "exactly what the photo must show", "search": "Wikimedia Commons search words",
              "alternatives": ["other search words", "..."], "fallback_prompt": "photorealistic English image prompt",
              "alt": "alt text", "caption": "short caption"}}],
  "insertions": [{{"after": "the first 8-12 words of an existing paragraph, copied exactly", "html": "<p>...</p>"}}],
  "closing": "<p>...</p>",
  "persona_used": ["E05"]
}}
Rules:
- "illustrations": exactly {illustrations} explanatory illustrations, "photos": exactly {photos} real-photo slot(s).
  "section" is the number of the h2 heading the image goes under (never the Sources/References heading); use
  different sections for different images when possible. Prompts must not ask for any text, letters or logos.
- "insertions": 0-2 short first-person paragraphs (1-3 sentences each) from the author persona that genuinely fit
  the paragraph they follow. Copy "after" exactly from the body so I can find the paragraph. Leave the list empty if
  nothing fits — never force it, and never invent experiences.
- "closing": a short "my take" paragraph (2-4 sentences) in the persona's voice, phrased as opinion. Use "" if the
  post already ends with a personal take or there is no persona below.
- "persona_used": the episode IDs you used (empty list if none).
- Plain English sentences only inside the <p> tags (no links, no headings, no images, no Markdown).
"""


def _kst_date(stamp: str) -> str:
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(KST).strftime("%Y-%m-%d")
    except ValueError:
        return (stamp or "")[:10]


def find_post(cfg: BloggerConfig, target: str = "today") -> tuple[dict, list[dict]]:
    """target: "today" / YYYY-MM-DD(한국 날짜) / 글 주소 / 글 ID. (찾은 글, 공개 글 목록)"""
    live = fixposts._posts(cfg, "live")
    posts = live + fixposts._posts(cfg, "scheduled")
    target = (target or "today").strip()
    if target == "today":
        target = today_kst()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", target):
        found = [p for p in posts if _kst_date(p.get("published", "")) == target]
    elif target.startswith("http"):
        found = [p for p in posts if seo._norm(p.get("url", "")) == seo._norm(target)]
    else:
        found = [p for p in posts if str(p.get("id")) == target]
    if not found:
        raise RuntimeError(f"'{target}'에 해당하는 글을 블로그(공개·예약)에서 찾지 못했습니다.")
    if len(found) > 1:
        names = "\n".join(f"  - {p.get('title')}  {p.get('url') or '(예약)'}" for p in found)
        raise RuntimeError(f"'{target}'에 해당하는 글이 {len(found)}편입니다. 글 주소로 골라 주세요:\n{names}")
    return found[0], live


def strip_blocks(body: str) -> str:
    """이전에 넣은 대표 이미지·인포그래픽·관련 글 묶음을 뺀다(다시 넣는다)."""
    return _RELATED.sub("", _INFO.sub("", _COVER.sub("", body))).strip()


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _paragraphs(text: str) -> str:
    """Codex가 준 문단을 우리가 만든 깔끔한 <p>로(태그·링크는 버리고 글자만)."""
    parts = [p.strip() for p in re.split(r"\n\s*\n", html_to_text(text or "")) if p.strip()]
    return "".join(f"<p>{html.escape(' '.join(p.split()))}</p>" for p in parts)


def add_persona(body: str, plan: dict) -> tuple[str, int]:
    """기존 문장은 그대로 두고, 맞는 문단 뒤에 경험 문단을, 글 끝(출처 앞)에 '내 생각' 문단을 넣는다. (본문, 넣은 문단 수)"""
    added = 0
    for ins in plan.get("insertions") or []:
        if not isinstance(ins, dict):
            continue
        anchor, para = _key(str(ins.get("after") or "")), _paragraphs(str(ins.get("html") or ""))
        if len(anchor) < 15 or not para:
            continue
        for m in _PARA.finditer(body):
            if _key(html_to_text(m.group(1))).startswith(anchor[:120]):
                body = body[:m.end()] + para + body[m.end():]
                added += 1
                break
        else:
            log.warning("경험 문단을 넣을 자리를 찾지 못해 뺍니다: %s", anchor[:60])
    closing = _paragraphs(str(plan.get("closing") or ""))
    if closing:
        heads = list(infographic._SOURCES_H2.finditer(body))
        body = body[:heads[-1].start()] + closing + body[heads[-1].start():] if heads else body.rstrip() + closing
        added += 1
    return body, added


def plan(cfg: BloggerConfig, post: dict, use_persona: bool) -> dict:
    heads = [html_to_text(h) for h in _H2.findall(post["body_html"])]
    prompt = PLAN_PROMPT.format(
        title=post["title"], labels=", ".join(post.get("labels", [])),
        headings="\n".join(f"{i}. {h}" for i, h in enumerate(heads, 1)) or "(none)",
        text=html_to_text(post["body_html"])[:12000],
        persona=writer.persona_block(cfg) if use_persona else "\n(No author persona: return empty insertions and closing.)\n",
        illustrations=cfg.illustrations, photos=cfg.photos)
    result = writer._extract_json(writer._codex(cfg, prompt, None, "read-only", cfg.codex_timeout))
    if not isinstance(result, dict):
        raise RuntimeError(f"새 양식 계획을 이해하지 못했습니다: {str(result)[:300]}")
    return result


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _save(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _preview_page(title: str, body: str) -> str:
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(title)}</title>'
            '<style>body{max-width:760px;margin:2em auto;padding:0 16px;font-family:Georgia,serif;line-height:1.7}'
            '.kb-cover{display:block!important;border:2px dashed #c33;padding:4px}'
            '.kb-cover:before{content:"(hidden on the blog: cover image)";font:12px sans-serif;color:#c33}'
            f'img{{max-width:100%}}</style></head><body><h1>{html.escape(title)}</h1>{body}</body></html>')


def run(cfg: BloggerConfig, target: str = "today", apply: bool = False, again: bool = False,
        use_persona: bool = True, images: bool = False) -> dict:
    """(보고: 제목, 주소, 넣은 그림·문단 수, 미리보기 경로, 저장 여부)"""
    post, live = find_post(cfg, target)
    pid = str(post["id"])
    current = post.get("content") or ""
    refreshed = bool(_COVER.search(current) or _INFO.search(current))
    if refreshed and not again:
        raise RuntimeError(f"'{post.get('title')}'은(는) 이미 새 양식입니다(인포그래픽 있음). "
                           "그래도 다시 하려면 --again을 붙이세요(경험 문단은 다시 넣지 않습니다).")
    use_persona = use_persona and not refreshed
    out_dir = cfg.output_dir / f"refresh-{pid}"
    if again and out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stage = _load(out_dir / "stage.json")
    if stage.get("original") is not None and stage["original"] != current:
        raise RuntimeError("미리보기를 만든 뒤 블로그 글이 바뀌었습니다. --again을 붙여 처음부터 다시 만드세요.")
    if not stage:
        stage = {"original": current, "post_id": pid}
        _save(out_dir / "stage.json", stage)

    report = {"id": pid, "title": post.get("title", ""), "url": post.get("url", ""), "dir": str(out_dir)}
    if not (out_dir / "post.json").exists():
        body = strip_blocks(current)
        work = {"title": post.get("title", ""), "body_html": body, "labels": post.get("labels", []),
                "had_images": len(re.findall(r"<img\b", body, re.I))}
        use_persona = use_persona and bool(persona.load())
        p = plan(cfg, work, use_persona)
        _save(out_dir / "plan.json", p)
        work["topic"] = str(p.get("topic") or work["title"])
        work["illustrations"] = [w for w in p.get("illustrations") or [] if isinstance(w, dict)]
        work["photos"] = [w for w in p.get("photos") or [] if isinstance(w, dict)]
        work["body_html"], work["persona_paragraphs"] = add_persona(body, p) if use_persona else (body, 0)
        work["persona_used"] = persona.clean_used(p.get("persona_used"), persona.load()) if use_persona else []
        _save(out_dir / "post.json", work)
    work = _load(out_dir / "post.json")

    step_cfg = cfg
    if work.get("had_images") and not images:
        log.info("글에 그림이 이미 %d개 있어 사진·생성 그림은 건너뜁니다(--images로 강제)", work["had_images"])
        step_cfg = dataclasses.replace(cfg, photos=0, illustrations=0, photo_fallback=False)
    report["images_note"] = pipeline._add_images(step_cfg, work, out_dir)
    candidates = [{"url": p.get("url"), "title": p.get("title"), "labels": p.get("labels", []),
                   "published": p.get("published")} for p in live]
    new, changes = seo.improve(work["body_html"], post.get("url", ""), work["title"], work.get("labels", []),
                               candidates)
    if len(html_to_text(new)) < len(html_to_text(strip_blocks(current))):
        raise RuntimeError("새 본문이 원래 글보다 짧아졌습니다. 블로그 글은 고치지 않았습니다.")
    (out_dir / "refreshed.html").write_text(new, encoding="utf-8")
    preview = out_dir / "preview.html"
    preview.write_text(_preview_page(work["title"], new), encoding="utf-8")
    report.update(preview=str(preview), related=changes["related"], persona_paragraphs=work.get("persona_paragraphs", 0),
                  persona_used=work.get("persona_used", []), images=len(re.findall(r"<img\b", new, re.I)),
                  saved=False)
    if apply:
        backup = cfg.output_dir / "backup" / datetime.now(KST).strftime("%Y%m%d-%H%M%S")
        backup.mkdir(parents=True, exist_ok=True)
        (backup / f"{pid}.html").write_text(current, encoding="utf-8")
        api.update_content(cfg, pid, new)
        report.update(saved=True, backup=str(backup))
        _record_persona(cfg, pid, work.get("persona_used", []))
        log.info("새 양식으로 고침: %s", work["title"])
    return report


def _record_persona(cfg: BloggerConfig, pid: str, used: list[str]) -> None:
    """다음 글이 같은 경험을 바로 또 쓰지 않도록 발행 이력에 남긴다."""
    if not used:
        return
    entries = history.load(cfg.history_file)
    for e in entries:
        if str(e.get("post_id")) == pid:
            e["persona_used"] = list(dict.fromkeys([*(e.get("persona_used") or []), *used]))
            history.save(cfg.history_file, entries)
            return
