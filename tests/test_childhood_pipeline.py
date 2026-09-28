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


def test_limit_reset_time_parsing():
    from datetime import datetime
    now = datetime(2026, 9, 27, 5, 10, tzinfo=generate.KST)
    msg = "You've hit your session limit · resets 7:30am (Asia/Seoul)"
    assert generate.limit_reset_at(msg, now) == datetime(2026, 9, 27, 7, 30, tzinfo=generate.KST)
    assert generate.limit_reset_at("5-hour limit reached ∙ resets 3pm", now).hour == 15
    late = datetime(2026, 9, 27, 23, 0, tzinfo=generate.KST)
    assert generate.limit_reset_at(msg, late).day == 28          # 이미 지난 시각이면 다음 날
    assert generate.limit_reset_at("Claude 오류: 파일 없음", now) is None


def test_run_claude_raises_limit_error(cfg, monkeypatch, tmp_path):
    import subprocess

    out = json.dumps({"type": "result", "is_error": True, "api_error_status": 429,
                      "result": "You've hit your session limit · resets 7:30am (Asia/Seoul)"})
    monkeypatch.setattr(generate, "_claude_bin", lambda c: "claude")
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 1, stdout=out, stderr=""))
    with pytest.raises(generate.ClaudeLimitError) as e:
        generate._run_claude(cfg, "x", tmp_path / "log.txt")
    assert (e.value.reset_at.hour, e.value.reset_at.minute) == (7, 30)


def test_limit_waits_then_resumes_same_post(cfg, monkeypatch):
    """Claude 한도에 걸리면 실패하지 않고 풀릴 때까지 기다린 뒤, 쓴 글을 버리지 않고 이어서 한다."""
    from datetime import datetime, timedelta
    out = cfg.output_dir / "2026-09-27"
    cfg.gpt_factcheck = False
    writes, sleeps, sent = [], [], []
    monkeypatch.setattr(generate, "write_post",
                        lambda *a, **k: writes.append(1) or _fake_write(child_post())(*a, **k))
    monkeypatch.setattr(gemini_client, "generate_image", lambda c, p, path: path.write_bytes(b"png") or path)
    calls = iter(["limit", "pass"])

    def fake_fc(c, out_dir):
        if next(calls) == "limit":
            raise generate.ClaudeLimitError("limit", datetime.now(generate.KST) + timedelta(minutes=10))
        return {"verdict": "pass", "images": {"illust_a": "ok", "illust_b": "ok"}}
    monkeypatch.setattr(generate, "factcheck", fake_fc)
    monkeypatch.setattr(pipeline, "_sleep", lambda s: sleeps.append(s) or clock.append(s))
    clock = []
    real_now = datetime.now

    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return real_now(tz) + timedelta(seconds=sum(clock))
    monkeypatch.setattr(pipeline, "datetime", FakeDT)
    monkeypatch.setattr(pipeline.notify, "send", lambda c, t: sent.append(t))

    post = pipeline.produce(cfg, "2026-09-27", out)
    assert post["title"] and writes == [1]
    assert sum(sleeps) >= 11 * 60 and sent and "이어서" in sent[0]
    assert not list(cfg.output_dir.glob("*-rejected-*"))


def test_limit_too_long_stops(cfg, monkeypatch):
    from datetime import datetime, timedelta
    cfg.limit_wait_max_min = 30
    monkeypatch.setattr(generate, "write_post", lambda *a, **k: (_ for _ in ()).throw(
        generate.ClaudeLimitError("limit", datetime.now(generate.KST) + timedelta(hours=3))))
    monkeypatch.setattr(pipeline, "_sleep", lambda s: pytest.fail("기다리면 안 됨"))
    with pytest.raises(generate.GenerationError, match="최대 대기"):
        pipeline.produce(cfg, "2026-09-27", cfg.output_dir / "2026-09-27")


def test_codex_partial_verification_becomes_fix_not_api_fallback(cfg, tmp_path, monkeypatch):
    """웹 검색은 했지만 일부 원문을 못 열어 'error'로 답하면 유료 API로 넘기지 않고 수정 요청(fix)으로 다룬다."""
    script, _ = _fake_codex(tmp_path, '{"verdict": "error", "checked": 20, "issues": [], '
                                      '"summary": "첨부 법령안 원문 접근 실패로 2030년 부칙 미검증"}')
    cfg.codex_bin = str(script)
    monkeypatch.setattr(openai_client, "_post", lambda *a, **k: pytest.fail("API로 넘기면 안 됩니다"))
    result = openai_client.factcheck(cfg, content.normalize(child_post()))
    assert result["verdict"] == "fix"
    assert any("원문 확인 불가" in i["problem"] and "2030" in i["problem"] for i in result["issues"])


def test_codex_down_and_api_out_of_credit_reports_codex_first(cfg, tmp_path, monkeypatch):
    script, _ = _fake_codex(tmp_path, '{"verdict": "error", "summary": "no web search"}')
    cfg.codex_bin = str(script)
    cfg.openai_api_key = "k"

    def no_credit(*a, **k):
        raise openai_client.OpenAIAccountError("HTTP 429 credit_balance_exhausted")

    monkeypatch.setattr(openai_client, "_post", no_credit)
    with pytest.raises(openai_client.CodexAccountError) as e:
        openai_client.factcheck(cfg, content.normalize(child_post()))
    msg = str(e.value)
    assert msg.index("no web search") < msg.index("credit_balance_exhausted")


def test_codex_crash_is_retried_once_and_logged(cfg, tmp_path):
    """Codex는 진행 기록을 stderr로 내보내 끝부분엔 원인이 없다 → 전체를 파일로 남기고 오류 줄만 보여준다."""
    state = tmp_path / "count"
    script = tmp_path / "codex_flaky"
    script.write_text(f"""#!{__import__('sys').executable}
import sys, pathlib
p = pathlib.Path({str(state)!r}); n = int(p.read_text()) if p.exists() else 0; p.write_text(str(n + 1))
args = sys.argv[1:]; sys.stdin.read()
if n == 0:
    sys.stderr.write("ERROR: stream disconnected before completion\\n...Clements(1999), Duncan 외(2007)\\ncodex\\n"); sys.exit(1)
pathlib.Path(args[args.index("--output-last-message") + 1]).write_text('{{"verdict": "pass", "issues": []}}')
""", encoding="utf-8")
    script.chmod(0o755)
    cfg.codex_bin = str(script)
    cfg.log_dir = tmp_path / "logs"
    assert openai_client.factcheck(cfg, content.normalize(child_post()))["verdict"] == "pass"
    assert state.read_text() == "2"
    assert "stream disconnected" in (cfg.log_dir / "codex_last_error.log").read_text(encoding="utf-8")



def test_retry_note_before_and_after_retry_time(cfg):
    from datetime import datetime
    cfg.retry_time = "11:00"
    assert "11:00에 자동으로 한 번 더" in pipeline.retry_note(cfg, datetime(2026, 9, 29, 5, 33, tzinfo=pipeline.KST))
    assert "지나" in pipeline.retry_note(cfg, datetime(2026, 9, 29, 11, 20, tzinfo=pipeline.KST))
    cfg.retry_time = "off"
    assert pipeline.retry_note(cfg) == ""



def test_codex_out_of_credits_is_an_account_problem_not_retried(cfg, tmp_path):
    state = tmp_path / "count"
    script = tmp_path / "codex_broke"
    script.write_text(f"""#!{__import__('sys').executable}
import sys, pathlib
p = pathlib.Path({str(state)!r}); p.write_text(str(int(p.read_text()) + 1 if p.exists() else 1))
sys.stdin.read()
sys.stderr.write('{{"verdict": "error", "summary": "no web search"}} 만 출력하라\\n'
                 'ERROR: Your workspace is out of credits. Ask your workspace owner to refill in order to continue.\\n'
                 'ERROR: Your workspace is out of credits. Ask your workspace owner to refill in order to continue.\\n')
sys.exit(1)
""", encoding="utf-8")
    script.chmod(0o755)
    cfg.codex_bin = str(script)
    cfg.log_dir = tmp_path / "logs"
    cfg.openai_api_key = ""
    with pytest.raises(openai_client.CodexAccountError) as e:
        openai_client.factcheck(cfg, content.normalize(child_post()))
    msg = str(e.value)
    assert "크레딧 문제" in msg and "out of credits" in msg
    assert '"verdict"' not in msg and msg.count("out of credits") == 1
    assert state.read_text() == "1"                      # 크레딧 문제는 다시 해 봐야 소용없다


def test_publish_lock_waits_for_the_other_blog(tmp_path, monkeypatch):
    lock = tmp_path / ".publishing.lock"
    lock.write_text("123")                                   # 다른 블로그가 발행 중
    naps = []

    def fake_sleep(sec):
        naps.append(sec)
        lock.unlink()                                        # 그사이 다른 쪽이 끝남

    monkeypatch.setattr(pipeline, "_sleep", fake_sleep)
    with pipeline._PublishLock(lock, poll=5):
        assert lock.exists()
    assert naps == [5] and not lock.exists()


def test_publish_lock_clears_stale_lock_and_gives_up_eventually(tmp_path, monkeypatch):
    import os
    import time
    lock = tmp_path / ".publishing.lock"
    lock.write_text("dead")
    old = time.time() - 3600
    os.utime(lock, (old, old))                               # 비정상 종료로 남은 잠금
    with pipeline._PublishLock(lock, stale_sec=1800):
        pass
    lock.write_text("busy")
    monkeypatch.setattr(pipeline, "_sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="기다리다 멈췄"):
        with pipeline._PublishLock(lock, wait_sec=0):
            pass
