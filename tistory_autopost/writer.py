"""Claude Code로 글을 쓰고(stats-auto-post) 검수하며(stats-auto-factcheck), Codex(ChatGPT)로 교차 검증한다."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from naver_autopost import generate
from naver_autopost.content import html_to_text
from naver_autopost.openai_client import CodexUnavailable, _extract_json, run_codex

from .config import TistoryConfig

log = logging.getLogger(__name__)


def _rel(path: Path) -> Path:
    return generate._rel(path)


def write_post(cfg: TistoryConfig, out_dir: Path, today: str, topic_brief: str, feedback: str = "") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    prompt = (
        f"/{cfg.write_skill}\n\n"
        f"TODAY={today}\nOUTPUT_DIR={_rel(out_dir)}\nHISTORY_FILE={_rel(cfg.history_file)}\n"
        f"BLOG_URL={cfg.blog_url}\n\n{topic_brief}\n\n"
        "스킬 지침대로 오늘의 글 1편을 완성해 OUTPUT_DIR/post.json에 저장하라. "
        "사람 검토 없이 자동 발행되므로 수치 정확성이 최우선이다. 질문하지 말고 끝까지 진행하라."
    )
    if feedback:
        prompt += f"\n\n직전 시도는 아래 이유로 발행이 거부되었다. 문제를 해결하거나 다음 후보 주제를 써라:\n{feedback}"
    generate._run_claude(cfg, prompt, out_dir / "claude_write.log")
    path = out_dir / "post.json"
    if not path.exists():
        raise generate.NoPostError("post.json이 만들어지지 않았습니다(Claude가 글을 쓰지 않고 끝남)")
    return path


def factcheck(cfg: TistoryConfig, out_dir: Path) -> dict:
    prompt = (
        f"/{cfg.factcheck_skill}\n\nOUTPUT_DIR={_rel(out_dir)}\nMODE=check\n\n"
        "스킬 지침대로 post.json을 검수하고 factcheck.json을 저장하라. 질문하지 말고 끝까지 진행하라."
    )
    path = out_dir / "factcheck.json"
    path.unlink(missing_ok=True)
    generate._run_claude(cfg, prompt, out_dir / "claude_factcheck.log")
    if not path.exists():
        raise generate.GenerationError("factcheck.json이 만들어지지 않았습니다")
    return json.loads(path.read_text(encoding="utf-8"))


def apply_gpt_review(cfg: TistoryConfig, out_dir: Path, round_no: int) -> dict:
    prompt = (
        f"/{cfg.factcheck_skill}\n\nOUTPUT_DIR={_rel(out_dir)}\nMODE=apply_gpt_review\n\n"
        "스킬 지침의 MODE=apply_gpt_review 절차대로 gpt_review.json의 지적을 원문과 대조해 반영하고 "
        "gpt_applied.json을 저장하라. 질문하지 말고 끝까지 진행하라."
    )
    path = out_dir / "gpt_applied.json"
    path.unlink(missing_ok=True)
    generate._run_claude(cfg, prompt, out_dir / f"claude_apply_gpt_{round_no}.log")
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


GPT_FACTCHECK = """너는 한국 공식 통계 팩트체커다. 아래 블로그 글은 사람 검토 없이 티스토리에 자동 발행된다.
웹 검색으로 통계 원문(국가데이터처·KOSIS·각 부처 보도자료·한국은행·국민연금공단 등)을 직접 찾아
글 속 모든 수치를 하나씩 검증하라. 특히 아래를 본다.
- 값·단위(만원/억원, %/%p)와 기준 시점(조사 기준일, 발표 연도)이 원문과 같은가
- 가구 단위와 개인 단위, 평균과 중앙값, 총자산과 순자산을 섞지 않았는가
- 글쓴이가 원문 수치로 계산한 값(누적 비율, 배수, 증감률)이 맞는가
- 표의 숫자와 본문 숫자가 서로 맞는가
- 출처로 단 링크가 실제로 그 수치를 담고 있는가
규칙: 원문으로 확인되면 문제 없음. 다르면 올바른 값과 근거 URL. 어디서도 확인되지 않으면 삭제 권고.
해석·의견은 사실 오류가 아니면 지적하지 말 것. 근거 URL 없는 지적 금지.
웹 검색을 쓸 수 없으면 {"verdict": "error", "summary": "no web search"} 만 출력하라. 파일을 만들거나 명령을 실행하지 말 것.

오직 JSON 하나만 출력하라(코드블록 없이):
{"verdict": "pass" | "fix" | "fail", "checked": 검증한 수치 개수,
 "issues": [{"text": "본문 속 문제 문장(그대로)", "problem": "무엇이 틀렸나", "correction": "고친 문장 또는 '삭제'", "evidence_url": "https://..."}],
 "summary": "한 줄 요약"}
verdict: 문제 없음=pass, 고치면 되는 문제만=fix, 제목·핵심 수치가 틀렸거나 문제가 전체의 30% 초과=fail.
"""


def article(post: dict) -> str:
    sources = "\n".join(f"- {s.get('publisher', '')} | {s.get('title', '')} | {s.get('url', '')}"
                        for s in post.get("sources", []))
    return f"[제목] {post['title']}\n[출처]\n{sources}\n\n[본문]\n{html_to_text(post['body_html'])}"


def gpt_factcheck(cfg: TistoryConfig, post: dict) -> dict:
    result = _extract_json(run_codex(cfg, GPT_FACTCHECK + "\n\n" + article(post)))
    if result.get("verdict") == "error":
        raise CodexUnavailable(f"Codex에서 웹 검색을 쓸 수 없습니다: {result.get('summary', '')}")
    if result.get("verdict") not in ("pass", "fix", "fail"):
        raise CodexUnavailable(f"알 수 없는 판정: {result}")
    result.setdefault("issues", [])
    log.info("ChatGPT 팩트체크: %s, 지적 %d건", result["verdict"], len(result["issues"]))
    return result
