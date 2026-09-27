import json

import pytest

from naver_autopost import content, gemini_client, generate, openai_client, pipeline, profiles
from naver_autopost.config import Config
from tests.sample_post import make_post

CHILD = profiles.get("childhood")


def child_post(**over):
    post = make_post(
        thumbnail={"chip": "연령별 발달 · 4세", "main_lines": ["4세 숫자,", "어디까지", "배워야 할까?"], "sub": "단계가 먼저"},
        illustrations=[{"name": "illust_a", "prompt": "a Korean living room ...", "desc_ko": "도입", "alt": "숫자 놀이"},
                       {"name": "illust_b", "prompt": "a kindergarten classroom ...", "desc_ko": "2장", "alt": "교실"}],
        domain="N", cluster="4세 초기수학", lane="B",
    )
    post["body_html"] = "<p>[[IMAGE:illust_a]]</p>" + post["body_html"] + "<p>[[IMAGE:illust_b]]</p>"
    post.update(over)
    return post


def test_childhood_post_valid():
    assert content.validate(content.normalize(child_post()), CHILD) == []


def test_childhood_guardrail_phrase_blocks():
    post = child_post()
    post["body_html"] += "<p>4세라면 이 단계를 통과해야 합니다.</p>"
    assert any("통과해야" in e for e in content.validate(content.normalize(post), CHILD))


def test_sales_link_blocks():
    post = child_post()
    post["body_html"] += "<p>https://smartstore.naver.com/abc</p>"
    assert any("smartstore" in e for e in content.validate(content.normalize(post), CHILD))


def test_thumbnail_lines_limit():
    post = child_post(thumbnail={"main_lines": ["a", "b", "c", "d"], "sub": ""})
    assert any("1~3줄" in e for e in content.validate(content.normalize(post), CHILD))


def test_unknown_illust_marker_blocks():
    post = child_post()
    post["body_html"] += "<p>[[IMAGE:illust_z]]</p>"
    assert any("알 수 없는" in e for e in content.validate(content.normalize(post), CHILD))


def test_remove_markers_keeps_others():
    body = "<p>[[IMAGE:illust_a]]</p><p>x</p><p>[[IMAGE:card]]</p>"
    assert content.remove_markers(body, {"illust_a"}) == "<p>x</p><p>[[IMAGE:card]]</p>"


def test_openai_output_parsing():
    resp = {"output": [{"type": "web_search_call"},
                       {"type": "message", "content": [{"type": "output_text",
                                                        "text": '```json\n{"verdict": "pass", "issues": []}\n```'}]}]}
    assert openai_client._extract_json(openai_client._output_text(resp))["verdict"] == "pass"


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    c = Config.load("childhood")
    c.output_dir = tmp_path / "out"
    c.data_dir = tmp_path / "data"
    c.history_file = c.data_dir / "published_childhood.json"
    c.image_backend = "gemini"      # 파이프라인 테스트는 gemini_client를 가짜로 바꿔 쓴다
    return c


def _fake_write(post):
    def write_post(cfg, out_dir, today, feedback=""):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "post.json").write_text(json.dumps(post, ensure_ascii=False), encoding="utf-8")
        return out_dir / "post.json"
    return write_post


def test_attempt_full_flow_with_gpt_fix(cfg, monkeypatch):
    out = cfg.output_dir / "2026-09-27"
    monkeypatch.setattr(generate, "write_post", _fake_write(child_post()))

    def fake_image(c, prompt, path):
        if "classroom" in prompt:
            raise gemini_client.GeminiError("blocked")   # illust_b 생성 실패 → 본문에서 빠져야 함
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png")
        return path
    monkeypatch.setattr(gemini_client, "generate_image", fake_image)

    def fake_claude_fc(c, out_dir):
        fc = {"verdict": "pass", "images": {"illust_a": "ok"}, "summary": "ok"}
        (out_dir / "factcheck.json").write_text(json.dumps(fc), encoding="utf-8")
        return fc
    monkeypatch.setattr(generate, "factcheck", fake_claude_fc)

    reviews = iter([
        {"verdict": "fix", "issues": [{"text": "정책 설명 문장입니다.", "correction": "삭제"}], "summary": "1건"},
        {"verdict": "pass", "issues": [], "summary": "ok"},
    ])
    monkeypatch.setattr(openai_client, "factcheck", lambda c, p: next(reviews))
    applied = []
    monkeypatch.setattr(generate, "apply_gpt_review",
                        lambda c, d, r: applied.append(r) or {"applied": [{}], "rejected": []})

    post = pipeline._attempt(cfg, "2026-09-27", out, "")
    assert applied == [1]
    assert "[[IMAGE:illust_b]]" not in post["body_html"]
    assert "[[IMAGE:illust_a]]" in post["body_html"]
    assert (out / "gpt_factcheck_1.json").exists() and (out / "gpt_factcheck_2.json").exists()


def test_gpt_fail_rejects(cfg, monkeypatch):
    out = cfg.output_dir / "d"
    out.mkdir(parents=True)
    (out / "post.json").write_text(json.dumps(child_post(), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(openai_client, "factcheck",
                        lambda c, p: {"verdict": "fail", "issues": [], "summary": "핵심 수치 오류"})
    with pytest.raises(pipeline.Rejected, match="ChatGPT"):
        pipeline._gpt_factcheck(cfg, out / "post.json", out)


def test_gpt_fix_twice_then_pass(cfg, monkeypatch):
    out = cfg.output_dir / "d"
    out.mkdir(parents=True)
    (out / "post.json").write_text(json.dumps(child_post(), ensure_ascii=False), encoding="utf-8")
    reviews = iter([{"verdict": "fix", "issues": [{}]}, {"verdict": "fix", "issues": [{}]}, {"verdict": "pass"}])
    monkeypatch.setattr(openai_client, "factcheck", lambda c, p: next(reviews))
    applied = []
    monkeypatch.setattr(generate, "apply_gpt_review", lambda c, d, r: applied.append(r) or {})
    pipeline._gpt_factcheck(cfg, out / "post.json", out)
    assert applied == [1, 2]


def test_gpt_still_fix_after_last_round_rejects(cfg, monkeypatch):
    out = cfg.output_dir / "d"
    out.mkdir(parents=True)
    (out / "post.json").write_text(json.dumps(child_post(), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(openai_client, "factcheck", lambda c, p: {"verdict": "fix", "issues": [{}], "summary": ""})
    monkeypatch.setattr(generate, "apply_gpt_review", lambda c, d, r: {})
    with pytest.raises(pipeline.Rejected):
        pipeline._gpt_factcheck(cfg, out / "post.json", out)


def test_bad_image_from_claude_review_is_dropped(cfg, monkeypatch):
    out = cfg.output_dir / "2026-09-27"
    monkeypatch.setattr(generate, "write_post", _fake_write(child_post()))
    monkeypatch.setattr(gemini_client, "generate_image",
                        lambda c, p, path: path.parent.mkdir(parents=True, exist_ok=True) or path.write_bytes(b"x") or path)

    def fake_claude_fc(c, out_dir):
        fc = {"verdict": "pass", "images": {"illust_a": "ok", "illust_b": "bad: 글자 보임"}}
        return fc
    monkeypatch.setattr(generate, "factcheck", fake_claude_fc)
    cfg.gpt_factcheck = False
    post = pipeline._attempt(cfg, "2026-09-27", out, "")
    assert "illust_b" not in post["body_html"]
    assert not (out / "illust_b.png").exists()
    imgs = pipeline.render_images(cfg, post, out)
    assert set(imgs) == {"thumbnail", "card", "illust_a"}


def test_generate_image_falls_back_to_standard_size(cfg, monkeypatch, tmp_path):
    import base64
    calls = []

    def fake_post(c, path, payload, timeout):
        calls.append(dict(payload))
        if payload["size"] != "1536x1024":
            raise openai_client.OpenAIError('HTTP 400: {"error": {"message": "Invalid size"}}')
        return {"data": [{"b64_json": base64.b64encode(b"PNGDATA").decode()}]}
    monkeypatch.setattr(openai_client, "_post", fake_post)
    out = openai_client.generate_image(cfg, "a scene", tmp_path / "i.png")
    assert out.read_bytes() == b"PNGDATA"
    assert [c["size"] for c in calls] == ["1536x864", "1536x1024"]
    assert "no text" in calls[0]["prompt"].lower()


def test_gpt_factcheck_payload_uses_web_search(cfg, monkeypatch):
    seen = {}

    def fake_post(c, path, payload, timeout):
        seen.update(path=path, payload=payload)
        return {"output_text": '{"verdict": "pass", "checked": 3, "issues": [], "summary": "ok"}'}
    monkeypatch.setattr(openai_client, "_post", fake_post)
    cfg.factcheck_backend = "api"
    result = openai_client.factcheck(cfg, content.normalize(child_post()))
    assert result["verdict"] == "pass"
    assert seen["path"] == "/responses"
    assert seen["payload"]["tools"] == [{"type": "web_search"}]
    assert "발달 안전" in seen["payload"]["instructions"]
    assert "[[IMAGE" not in seen["payload"]["input"]


def test_negated_guardrail_phrase_allowed():
    post = child_post()
    post["body_html"] += "<p>이 표는 아이가 반드시 통과해야 하는 순서표가 아니라 흐름을 보여주는 참고입니다.</p>"
    assert content.validate(content.normalize(post), CHILD) == []


def test_sales_domain_blocked_even_with_negation_nearby():
    post = child_post()
    post["body_html"] += "<p>smartstore.naver.com/x 는 광고가 아닙니다</p>"
    assert content.validate(content.normalize(post), CHILD)


def test_account_error_stops_and_resume_skips_finished_steps(cfg, monkeypatch):
    """잔액 부족이면 그림을 빼지 않고 멈추고, 다음 실행은 글쓰기·통과한 검수를 건너뛰고 이어서 한다."""
    out = cfg.output_dir / "2026-09-27"
    writes = []

    def write_post(c, out_dir, today, feedback=""):
        writes.append(1)
        return _fake_write(child_post())(c, out_dir, today, feedback)
    monkeypatch.setattr(generate, "write_post", write_post)

    def no_money(c, prompt, path):
        raise gemini_client.GeminiAccountError("RESOURCE_EXHAUSTED")
    monkeypatch.setattr(gemini_client, "generate_image", no_money)
    with pytest.raises(gemini_client.GeminiAccountError):
        pipeline.produce(cfg, "2026-09-27", out)
    assert "[[IMAGE:illust_a]]" in (out / "post.json").read_text(encoding="utf-8")   # 그림 자리 유지

    # 충전 후 다시 실행
    def ok_image(c, prompt, path):
        path.write_bytes(b"png")
        return path
    monkeypatch.setattr(gemini_client, "generate_image", ok_image)
    claude_calls = []

    def fake_claude_fc(c, out_dir):
        claude_calls.append(1)
        return {"verdict": "pass", "images": {"illust_a": "ok", "illust_b": "ok"}}
    monkeypatch.setattr(generate, "factcheck", fake_claude_fc)
    gpt = iter([openai_client.OpenAIAccountError("no credits"), {"verdict": "pass", "issues": []}])

    def fake_gpt(c, p):
        r = next(gpt)
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(openai_client, "factcheck", fake_gpt)
    with pytest.raises(openai_client.OpenAIAccountError):
        pipeline.produce(cfg, "2026-09-27", out)
    post = pipeline.produce(cfg, "2026-09-27", out)
    assert writes == [1]                 # 글은 한 번만 썼다
    assert claude_calls == [1]           # Claude 검수도 한 번만
    assert "[[IMAGE:illust_b]]" in post["body_html"]
    assert (out / "ready.json").exists()


def test_quota_429_is_account_error_without_retry(cfg, monkeypatch):
    import io
    import urllib.error
    calls = []

    def fake_urlopen(req, timeout):
        calls.append(1)
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {},
                                     io.BytesIO(b'{"error": {"code": "credit_balance_exhausted"}}'))
    monkeypatch.setattr(openai_client.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(openai_client.OpenAIAccountError):
        openai_client._post(cfg, "/responses", {}, timeout=5)
    assert calls == [1]


# ---------------------------------------------------------------- Gemini

def _png_b64():
    import base64
    import io as _io

    from PIL import Image
    buf = _io.BytesIO()
    Image.new("RGB", (32, 18), "#abcdef").save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def test_gemini_generate_image_requests_16x9_and_saves_png(cfg, monkeypatch, tmp_path):
    cfg.gemini_api_key = "g"
    seen = {}

    def fake_call(c, model, payload):
        seen.update(model=model, payload=payload)
        return {"candidates": [{"content": {"parts": [{"text": "here"}, {"inlineData": {"mimeType": "image/png", "data": _png_b64()}}]}}]}
    monkeypatch.setattr(gemini_client, "_call", fake_call)
    out = gemini_client.generate_image(cfg, "a scene", tmp_path / "a.png")
    from PIL import Image
    assert Image.open(out).size == (32, 18)
    assert seen["model"] == cfg.gemini_image_model
    assert seen["payload"]["generationConfig"]["imageConfig"]["aspectRatio"] == "16:9"
    assert "no text" in seen["payload"]["contents"][0]["parts"][0]["text"].lower()


def test_gemini_falls_back_when_model_missing(cfg, monkeypatch, tmp_path):
    cfg.gemini_api_key = "g"
    cfg.gemini_image_model = "retired-model"
    tried = []

    def fake_call(c, model, payload):
        tried.append(model)
        if len(tried) == 1:
            raise gemini_client.GeminiError(f"model-not-found {model}")
        return {"candidates": [{"content": {"parts": [{"inlineData": {"data": _png_b64()}}]}}]}
    monkeypatch.setattr(gemini_client, "_call", fake_call)
    gemini_client.generate_image(cfg, "x", tmp_path / "a.png")
    assert tried == ["retired-model", gemini_client.FALLBACK_MODELS[0]]


def test_gemini_missing_key_is_account_error(cfg, tmp_path):
    cfg.gemini_api_key = ""
    with pytest.raises(gemini_client.GeminiAccountError):
        gemini_client.generate_image(cfg, "x", tmp_path / "a.png")


# ---------------------------------------------------------------- Codex(ChatGPT 구독) 팩트체크

def _fake_codex(tmp_path, body: str, reject_first_variant=False):
    """가짜 codex 실행 파일: 인자를 기록하고 --output-last-message 파일에 결과를 쓴다."""
    script = tmp_path / "codex"
    log = tmp_path / "codex_args.log"
    script.write_text(f"""#!{__import__('sys').executable}
import sys, pathlib
args = sys.argv[1:]
pathlib.Path({str(log)!r}).open("a").write(" ".join(args) + "\\n")
if {reject_first_variant!r} and args[:2] == ["exec", "--search"]:
    sys.stderr.write("error: unexpected argument '--search' found\\nUsage: codex exec"); sys.exit(2)
prompt = sys.stdin.read()
import os
assert "OPENAI_API_KEY" not in os.environ, "API key leaked to codex"
assert "[본문]" in prompt
out = args[args.index("--output-last-message") + 1]
pathlib.Path(out).write_text({body!r}, encoding="utf-8")
""", encoding="utf-8")
    script.chmod(0o755)
    return script, log


def test_codex_factcheck_uses_subscription_cli(cfg, tmp_path):
    script, log = _fake_codex(tmp_path, '{"verdict": "pass", "checked": 5, "issues": [], "summary": "ok"}')
    cfg.codex_bin = str(script)
    result = openai_client.factcheck(cfg, content.normalize(child_post()))
    assert result["verdict"] == "pass"
    args = log.read_text().splitlines()[0]
    assert args.startswith("exec --search") and "--sandbox read-only" in args


def test_codex_tries_next_search_variant(cfg, tmp_path):
    script, log = _fake_codex(tmp_path, '{"verdict": "fix", "issues": [{"text": "a"}], "summary": ""}',
                              reject_first_variant=True)
    cfg.codex_bin = str(script)
    assert openai_client.factcheck(cfg, content.normalize(child_post()))["verdict"] == "fix"
    assert log.read_text().splitlines()[1].startswith("--search exec")


def test_codex_without_web_search_falls_back_or_stops(cfg, tmp_path, monkeypatch):
    script, _ = _fake_codex(tmp_path, '{"verdict": "error", "summary": "no web search"}')
    cfg.codex_bin = str(script)
    cfg.openai_api_key = ""
    with pytest.raises(openai_client.CodexAccountError):
        openai_client.factcheck(cfg, content.normalize(child_post()))
    cfg.openai_api_key = "k"
    monkeypatch.setattr(openai_client, "_post", lambda c, p, payload, timeout: {"output_text": '{"verdict": "pass"}'})
    assert openai_client.factcheck(cfg, content.normalize(child_post()))["verdict"] == "pass"


# ---------------------------------------------------------------- Codex 내장 이미지 생성(ChatGPT 구독)

def _fake_codex_image(tmp_path, codex_home, make_image=True, size=(1536, 1024)):
    """가짜 codex: 세션 id를 출력하고 CODEX_HOME/generated_images/<세션>/ig_1.png 를 만든다."""
    script = tmp_path / "codex_img"
    script.write_text(f"""#!{__import__('sys').executable}
import sys, os, pathlib
prompt = sys.stdin.read()
assert "image generation tool" in prompt and "no text" in prompt.lower()
assert "OPENAI_API_KEY" not in os.environ
sid = "0199aaaa-bbbb-cccc-dddd-eeeeffff0000"
print("session id: " + sid)
if {make_image!r}:
    from PIL import Image
    d = pathlib.Path(os.environ["CODEX_HOME"]) / "generated_images" / sid
    d.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", {size!r}, "#88aacc").save(d / "ig_1.png")
""", encoding="utf-8")
    script.chmod(0o755)
    return script


def test_codex_image_collects_file_and_crops_to_16x9(cfg, tmp_path, monkeypatch):
    from naver_autopost import codex_image
    home = tmp_path / "codex_home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.setenv("OPENAI_API_KEY", "should-not-leak")
    cfg.codex_bin = str(_fake_codex_image(tmp_path, home))
    out = codex_image.generate_image(cfg, "a child stacking blocks", tmp_path / "out" / "illust_a.png")
    from PIL import Image
    assert Image.open(out).size == (1536, 864)


def test_codex_image_missing_file_is_plain_error(cfg, tmp_path, monkeypatch):
    from naver_autopost import codex_image
    home = tmp_path / "codex_home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    cfg.codex_bin = str(_fake_codex_image(tmp_path, home, make_image=False))
    with pytest.raises(codex_image.CodexImageError):      # 그 그림만 빠지고 발행은 계속
        codex_image.generate_image(cfg, "x", tmp_path / "a.png")


def test_default_image_backend_is_codex(monkeypatch):
    monkeypatch.delenv("IMAGE_BACKEND", raising=False)
    from naver_autopost import codex_image
    c = Config.load("childhood")
    assert c.image_backend == "codex"
    assert pipeline.image_generator(c) is codex_image


def test_gpt_issue_only_in_unpublished_sources_list_passes(cfg, monkeypatch):
    out = cfg.output_dir / "d"
    out.mkdir(parents=True)
    (out / "post.json").write_text(json.dumps(child_post(), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(openai_client, "factcheck", lambda c, p: {
        "verdict": "fix", "issues": [{"text": "National Institute for Literacy (NELP)", "correction": "NIFL"}]})
    monkeypatch.setattr(generate, "apply_gpt_review", lambda *a: pytest.fail("should not apply"))
    pipeline._gpt_factcheck(cfg, out / "post.json", out)


def test_gpt_issue_in_body_is_still_applied(cfg, monkeypatch):
    out = cfg.output_dir / "d"
    out.mkdir(parents=True)
    (out / "post.json").write_text(json.dumps(child_post(), ensure_ascii=False), encoding="utf-8")
    reviews = iter([{"verdict": "fix", "issues": [{"text": "시행 일정 설명입니다."}]}, {"verdict": "pass"}])
    monkeypatch.setattr(openai_client, "factcheck", lambda c, p: next(reviews))
    applied = []
    monkeypatch.setattr(generate, "apply_gpt_review", lambda c, d, r: applied.append(r) or {})
    pipeline._gpt_factcheck(cfg, out / "post.json", out)
    assert applied == [1]
