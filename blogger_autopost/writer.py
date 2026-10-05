"""Codex CLI(ChatGPT 구독)로 korea-explained-blogger 스킬을 실행해 글을 쓰고, 별도 세션으로 팩트체크한다."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from naver_autopost.codex_image import codex_home
from naver_autopost.content import html_to_text
from naver_autopost.openai_client import CodexAccountError, CodexUnavailable, _extract_json, run_codex

from .config import BloggerConfig

log = logging.getLogger(__name__)
HISTORY_IN_PROMPT = 80

WRITE_PROMPT = """${skill}

Use the {skill} skill to write TODAY's one blog post for my Google Blogger blog.
{skill_hint}
TODAY={today}

This run is fully automatic: nobody reviews the post before it goes live on the blog.
- Do not ask questions. Pick the topic yourself following the skill's rules and finish in one go.
- Accuracy comes first. Check every number, date, name, price, law and rule with web search against reliable,
  preferably official sources. If you cannot verify something, leave it out. Never invent facts,
  quotes or personal experiences.
- Do not write a post on the same topic as one already published (list below). You may link to a
  related published post with its exact URL when it genuinely helps the reader.

Already published posts (newest first):
{history}
{feedback}
DELIVERABLE (this replaces only the skill's output/delivery format; keep ALL of its writing rules, and follow
its guidance on images — what to show, style, placement — when you fill "illustrations" and "photos" below):
Save ONE file named post.json (UTF-8) in the current working directory, exactly this shape:
{{
  "title": "post title",
  "body_html": "the full post body as Blogger-ready HTML",
  "labels": ["3 to 8 Blogger labels"],
  "topic": "one-line description of the topic",
  "summary": "one-sentence summary",
  "search_description": "the exact text of the opening paragraph (120-155 characters)",
  "sources": [{{"title": "source page title", "publisher": "who published it", "url": "https://..."}}],
  "illustrations": [{{"section": 1, "prompt": "detailed English image-generation prompt", "alt": "alt text",
                     "caption": "short caption"}}],
  "photos": [{{"section": 2, "subject": "exactly what the photo must show", "search": "Wikimedia Commons search words",
              "alternatives": ["other search words", "..."], "fallback_prompt": "photorealistic English image prompt",
              "alt": "alt text", "caption": "short caption"}}]
}}
body_html rules:
- An HTML fragment only: <p>, <h2>, <h3>, <ul>/<ol>/<li>, <table>, <blockquote>, <strong>, <em>, <a href>, <hr>.
- No <html>, <head>, <body>, <h1> (Blogger shows the title itself), no <script>, <style>, <iframe>, no Markdown.
- Start body_html with a <p> that directly answers the reader's main question in 1-2 sentences, 120-155
  characters, containing the main search phrase. The blog uses this opening paragraph as the page's meta
  description in search results, so make it a complete, self-contained summary (no "In this post..." filler).
  Put the same text in "search_description". Never start with an image, a caption or a heading.
- Do not put <img> tags or image placeholders in body_html. Images are inserted automatically from
  "illustrations" and "photos" ("section": 0 = right after that opening paragraph, N = right after the N-th <h2>).
  Spread them over different sections where a picture really helps the reader.
- Internal links: where it genuinely helps, link to 2-3 related posts from the "Already published posts" list
  inside the text, using their exact URLs. Never invent URLs. (A short related-posts list is also added
  automatically at the end, so do not add your own "related posts" section.)
- If the skill asks for a sources/references section, put it inside body_html as HTML with real links.
"illustrations" (exactly {illustrations}): pictures an image model will draw for this post.
- "prompt": a detailed English prompt in an illustration style (not a photorealistic photo) that explains or
  sets the scene for that section. No text, letters, numbers, logos or maps in the picture.
"photos" (exactly {photos}, always): a real photo to find on Wikimedia Commons.
- "subject": a concrete, checkable subject in English (e.g. "Seoul subway ticket gates with a T-money card reader"),
  something that really exists in Korea. A reviewer will reject photos that do not clearly show it.
- "search": 2-5 English keywords with proper names (e.g. "Gyeongbokgung Geunjeongjeon"); no generic mood words.
  "alternatives": 1-2 other searches for the same subject in case the first finds nothing usable.
  "fallback_prompt": if no usable real photo is found, an image model will make a photorealistic image from this
  English prompt instead (labelled as AI-generated). Describe a typical, generic scene of the subject; no text or signs.
- Prefer well-known places, buildings, food, objects and signs over people.
"sources" lists every page you actually read to verify the facts (at least {min_sources}).
After saving post.json, reply with just: done
"""

FACTCHECK_PROMPT = """You are an independent fact-checker. The blog post below will be published automatically to a public
blog with no human review. Use web search to find primary or authoritative sources and verify every factual
claim: numbers, dates, prices, names, places, laws, rules, procedures, opening hours, and anything a reader
might act on.
Rules:
- Confirmed by a reliable source: no issue. Wrong: give the corrected sentence and the evidence URL.
  Not confirmable anywhere reliable: recommend deleting it ("삭제" or "delete").
- Also check that the links in the post and the listed sources really say what the post claims.
- Do not comment on style, opinions or tone unless they state something false.
- Only report issues you can back with an evidence URL.
If you cannot use web search, output only {{"verdict": "error", "summary": "no web search"}}.
Do not create files or run commands.

Output ONLY one JSON object (no code fence):
{{"verdict": "pass" | "fix" | "fail",
  "checked": <number of claims checked>,
  "issues": [{{"text": "the exact sentence from the post", "problem": "what is wrong",
              "correction": "corrected sentence or delete", "evidence_url": "https://..."}}],
  "summary": "one line"}}
verdict: nothing wrong = pass; only fixable problems = fix; the title's or main claim is wrong, or more than
30% of the claims are wrong = fail.

--- POST ---
{article}
"""

FIX_PROMPT = """post.json in the current working directory is a blog post that a fact-checker reviewed.
Its findings are below. For each finding, first check the evidence yourself with web search.
- If the finding is right, fix post.json (body_html, title, labels, summary, sources) accordingly; delete a
  sentence when the correct fact cannot be confirmed.
- If the finding is wrong, keep the original.
Change nothing else. Keep the same JSON shape and HTML rules. Save post.json, and also save review_applied.json:
{{"applied": ["..."], "rejected": [{{"text": "...", "reason": "..."}}]}}
Then reply with just: done

--- FINDINGS ---
{issues}
"""


def find_skill(cfg: BloggerConfig) -> Path | None:
    """설치된 스킬의 SKILL.md 위치(.env의 BLOGGER_SKILL_PATH가 있으면 그것, 없으면 ~/.codex/skills 아래를 찾는다)."""
    if cfg.skill_path:
        p = Path(cfg.skill_path).expanduser()
        return p if p.exists() else None
    root = codex_home() / "skills"
    if not root.is_dir():
        return None
    matches = sorted((p for p in root.rglob("SKILL.md") if cfg.skill in p.parts), key=lambda p: len(p.parts))
    return matches[0] if matches else None


def _history_lines(entries: list[dict]) -> str:
    rows = sorted(entries, key=lambda e: e.get("date") or e.get("published") or "", reverse=True)
    lines = [f"- {e.get('date') or (e.get('published') or '')[:10]} | {e.get('title', '')} | {e.get('url', '')}"
             + (f" | labels: {', '.join(e['labels'])}" if e.get("labels") else "")
             for e in rows[:HISTORY_IN_PROMPT]]
    return "\n".join(lines) or "(none yet)"


_MODEL_REFUSED = re.compile(r"model.{0,80}(not supported|not available|does not exist|not found|unknown|access)"
                            r"|(unsupported|unknown|invalid) model", re.I | re.S)


def _codex(cfg: BloggerConfig, prompt: str, cwd: Path | None, sandbox: str, timeout: int,
           images: list[Path] | None = None) -> str:
    try:
        try:
            return run_codex(cfg, prompt, cwd=cwd, sandbox=sandbox, timeout=timeout, images=images)
        except CodexUnavailable as e:
            # ChatGPT 로그인(구독)으로는 Sol을 못 쓰는 경우가 있다 → 대체 모델로 이번 실행을 계속한다.
            if not (cfg.codex_fallback_model and cfg.codex_model != cfg.codex_fallback_model
                    and _MODEL_REFUSED.search(str(e))):
                raise
            log.warning("모델 %s을(를) 쓸 수 없어 %s(으)로 바꿉니다: %s", cfg.codex_model, cfg.codex_fallback_model, e)
            cfg.model_note = f"⚠️ {cfg.codex_model}을(를) 쓸 수 없어 {cfg.codex_fallback_model}(으)로 썼습니다"
            cfg.codex_model = cfg.codex_fallback_model
            return run_codex(cfg, prompt, cwd=cwd, sandbox=sandbox, timeout=timeout, images=images)
    except CodexUnavailable as e:
        # 미설치·로그인 풀림·구독 사용 한도: 다시 써 봐야 소용없으니 멈추고 알린다(다음 실행에서 이어서).
        raise CodexAccountError(f"Codex(ChatGPT)를 쓸 수 없습니다: {e}") from e


def write_post(cfg: BloggerConfig, out_dir: Path, today: str, history: list[dict], feedback: str = "") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    skill_file = find_skill(cfg)
    hint = (f"(If the skill is not loaded automatically, read its instructions from {skill_file} and follow them.)"
            if skill_file else "")
    fb = (f"\nThe previous attempt was rejected for the reasons below. Choose a different topic or fix them:\n"
          f"{feedback}\n") if feedback else ""
    prompt = WRITE_PROMPT.replace("${skill}", f"${cfg.skill}").format(
        skill=cfg.skill, skill_hint=hint, today=today, history=_history_lines(history), feedback=fb,
        min_sources=cfg.min_sources, photos=cfg.photos,
        illustrations=cfg.illustrations)
    (out_dir / "write_prompt.txt").write_text(prompt, encoding="utf-8")
    log.info("Codex 글쓰기 시작(%s 스킬)", cfg.skill)
    reply = _codex(cfg, prompt, out_dir, "workspace-write", cfg.write_timeout)
    (out_dir / "codex_write.log").write_text(reply, encoding="utf-8")
    post_path = out_dir / "post.json"
    if not post_path.exists():
        raise RuntimeError(f"Codex가 post.json을 만들지 않았습니다. 마지막 답변: {reply.strip()[-300:]}")
    return post_path


def article_text(post: dict) -> str:
    sources = "\n".join(f"- {s.get('publisher', '')} | {s.get('title', '')} | {s.get('url', '')}"
                        for s in post.get("sources", []))
    links = "\n".join(sorted(set(re.findall(r'href="([^"]+)"', post.get("body_html", "")))))
    return (f"[Title] {post['title']}\n[Labels] {', '.join(post.get('labels', []))}\n"
            f"[Sources the writer listed]\n{sources}\n[Links in the post]\n{links}\n\n"
            f"[Body]\n{html_to_text(post['body_html'])}")


def factcheck(cfg: BloggerConfig, post: dict) -> dict:
    result = _extract_json(_codex(cfg, FACTCHECK_PROMPT.format(article=article_text(post)), None, "read-only",
                                  cfg.codex_timeout))
    if result.get("verdict") == "error":
        raise CodexAccountError(f"Codex에서 웹 검색을 쓸 수 없습니다: {result.get('summary', '')}")
    if result.get("verdict") not in ("pass", "fix", "fail"):
        raise RuntimeError(f"팩트체크 결과를 이해하지 못했습니다: {str(result)[:300]}")
    result.setdefault("issues", [])
    if result["verdict"] == "fix" and not result["issues"]:
        result["verdict"] = "pass"
    log.info("팩트체크: %s, 지적 %d건 — %s", result["verdict"], len(result["issues"]), result.get("summary", ""))
    return result


def apply_fixes(cfg: BloggerConfig, out_dir: Path, issues: list[dict]) -> dict:
    prompt = FIX_PROMPT.format(issues=json.dumps(issues, ensure_ascii=False, indent=2))
    applied = out_dir / "review_applied.json"
    applied.unlink(missing_ok=True)
    _codex(cfg, prompt, out_dir, "workspace-write", cfg.write_timeout)
    try:
        return json.loads(applied.read_text(encoding="utf-8")) if applied.exists() else {}
    except json.JSONDecodeError:
        return {}


PHOTO_REVIEW_PROMPT = """PHOTO REVIEW. You are choosing photos for a public blog post about Korea.
The attached images are candidates from Wikimedia Commons, in the order listed below. Look at each image itself.
Blog post title: {title}

For each slot pick the ONE best candidate, or null if none is clearly right. A candidate is acceptable only if:
- it clearly shows the slot's subject (not just something loosely related),
- it is really in / of Korea (reject anything that looks like Japan, China or elsewhere),
- no watermark, no large overlaid text or logo, not a screenshot, map or diagram unless the subject asks for it,
- no identifiable private person as the main subject, nothing graphic, offensive or misleading,
- reasonable quality (not blurry, not tiny, not badly cropped).

{slots}

Output ONLY one JSON object (no code fence):
{{"choices": {{"<slot id>": "<candidate id>" or null}}, "notes": {{"<candidate id>": "why rejected / chosen"}}}}
"""


def review_photos(cfg: BloggerConfig, title: str, slots: list[dict]) -> dict:
    """slots: [{"id", "subject", "candidates": [{"id", "title", "description", "path"}]}] → {slot id: candidate id}"""
    lines, images = [], []
    for slot in slots:
        lines.append(f"Slot {slot['id']} — must show: {slot['subject']}")
        for c in slot["candidates"]:
            images.append(c["path"])
            lines.append(f"  image #{len(images)} = candidate {c['id']}: {c['title']} — {c['description'][:200]}")
    prompt = PHOTO_REVIEW_PROMPT.format(title=title, slots="\n".join(lines))
    result = _extract_json(_codex(cfg, prompt, None, "read-only", cfg.codex_timeout, images=images))
    choices = result.get("choices") or {}
    log.info("사진 검수: %s", choices)
    return {str(k): str(v) for k, v in choices.items() if v}


ILLUSTRATION_REVIEW_PROMPT = """ILLUSTRATION REVIEW. The attached images were generated by an image model for a public blog post
about Korea, in the order listed below. Look at each image itself.
Blog post title: {title}

{items}

Each image is either kind=illustration (must look like an illustration) or kind=photo (must look like a natural,
realistic photograph; it will be labelled as AI-generated).
An image is "ok" only if ALL are true:
- it fits its description and would help a reader of this post,
- no text, letters, numbers, signs with writing, logos or watermarks (garbled pseudo-text counts as text),
- no distorted faces, hands or bodies, no obvious generation glitches,
- nothing offensive, sexual, graphic, or culturally wrong for Korea (e.g. Japanese or Chinese clothing,
  architecture or flags presented as Korean),
- kind=illustration: it does not look like a real photograph. kind=photo: it looks realistic and natural.
Otherwise give a short reason.

Output ONLY one JSON object (no code fence): {{"<id>": "ok" or "reason", ...}}
"""


def review_illustrations(cfg: BloggerConfig, title: str, items: list[dict]) -> dict:
    """items: [{"id", "desc", "path"}] → {id: "ok" | 이유}"""
    lines = [f"image #{n} = {it['id']} (kind={it.get('kind', 'illustration')}): {it['desc']}"
             for n, it in enumerate(items, 1)]
    prompt = ILLUSTRATION_REVIEW_PROMPT.format(title=title, items="\n".join(lines))
    result = _extract_json(_codex(cfg, prompt, None, "read-only", cfg.codex_timeout,
                                  images=[it["path"] for it in items]))
    log.info("생성 그림 검수: %s", result)
    return {str(k): str(v).strip().lower() if str(v).strip().lower() == "ok" else str(v) for k, v in result.items()}
