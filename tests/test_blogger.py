"""구글 블로거 자동 발행: 가짜 Codex CLI와 가짜 Blogger API로 전체 흐름을 확인한다."""
import json
import sys
from datetime import datetime

import pytest

from blogger_autopost import api, content, pipeline, writer
from blogger_autopost.config import BloggerConfig
from naver_autopost import history
from naver_autopost.pipeline import KST

BODY = ("<p>Intro paragraph about the topic.</p><h2>How it works</h2>"
        + "<p>" + "A verified sentence about Korea. " * 80 + "</p>"
        + "<h2>Sources</h2><ul><li><a href=\"https://www.korea.net/a\">Korea.net</a></li></ul>")
POST = {"title": "How the T-money Card Works in Seoul", "body_html": BODY, "labels": ["Transport", "Seoul"],
        "topic": "T-money", "summary": "One line.",
        "sources": [{"title": f"s{i}", "publisher": "p", "url": f"https://example.org/{i}"} for i in range(3)]}


def fake_codex(tmp_path, verdicts=("pass",)):
    """가짜 codex: 글쓰기 프롬프트면 post.json을, 팩트체크면 판정 JSON을, 수정 요청이면 고친 post.json을 만든다."""
    state = tmp_path / "codex_state"
    state.mkdir(exist_ok=True)
    (state / "verdicts.json").write_text(json.dumps(list(verdicts)))
    (state / "post.json").write_text(json.dumps(POST))
    script = tmp_path / "codex"
    script.write_text(f"""#!{sys.executable}
import json, pathlib, sys
state = pathlib.Path({str(state)!r})
args = sys.argv[1:]
out = pathlib.Path(args[args.index("--output-last-message") + 1])
prompt = sys.stdin.read()
n = len(list(state.glob("prompt_*.txt")))
(state / f"prompt_{{n}}.txt").write_text(prompt, encoding="utf-8")
if "DELIVERABLE" in prompt:
    pathlib.Path("post.json").write_text((state / "post.json").read_text())
    out.write_text("done")
elif "independent fact-checker" in prompt:
    verdicts = json.loads((state / "verdicts.json").read_text())
    v = verdicts.pop(0) if len(verdicts) > 1 else verdicts[0]
    (state / "verdicts.json").write_text(json.dumps(verdicts))
    issues = [] if v == "pass" else [{{"text": "A verified sentence", "problem": "x", "correction": "y",
                                        "evidence_url": "https://e.org"}}]
    out.write_text(json.dumps({{"verdict": v, "checked": 9, "issues": issues, "summary": v}}))
elif "FINDINGS" in prompt:
    post = json.loads(pathlib.Path("post.json").read_text())
    post["title"] = post["title"] + " (fixed)"
    pathlib.Path("post.json").write_text(json.dumps(post))
    pathlib.Path("review_applied.json").write_text(json.dumps({{"applied": ["y"], "rejected": []}}))
    out.write_text("done")
""", encoding="utf-8")
    script.chmod(0o755)
    return script, state


class FakeBlogger:
    def __init__(self):
        self.drafts, self.published, self.live = {}, [], []

    def install(self, monkeypatch):
        monkeypatch.setattr(api, "resolve_blog_id", lambda cfg: "123")
        monkeypatch.setattr(api, "list_posts", lambda cfg, status="live", limit=2000:
                            list(self.live) if status == "live" else [])
        monkeypatch.setattr(api, "create_draft", self.create_draft)
        monkeypatch.setattr(api, "publish", self.publish)

    def create_draft(self, cfg, title, content_html, labels):
        pid = str(len(self.drafts) + 1)
        self.drafts[pid] = {"title": title, "content": content_html, "labels": labels}
        return {"id": pid, "status": "DRAFT"}

    def publish(self, cfg, post_id, when=None):
        self.published.append((post_id, when))
        return {"id": post_id, "status": "SCHEDULED" if when else "LIVE",
                "url": f"https://myblog.blogspot.com/2026/09/post-{post_id}.html"}


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex_home"))
    c = BloggerConfig.load()
    c.output_dir = tmp_path / "out"
    c.history_file = tmp_path / "published_blogger.json"
    c.log_dir = tmp_path / "logs"
    c.publish_time = ""
    c.codex_args = "exec --search"
    c.codex_model = ""
    c.telegram_bot_token = c.telegram_chat_id = ""
    return c


def test_normalize_and_validate_ok():
    post = content.normalize({**POST, "labels": "#Seoul, seoul, Transport", "body_html": "<h1>T</h1>" + BODY})
    assert post["labels"] == ["Seoul", "Transport"]
    assert "<h1" not in post["body_html"] and "<h2>T</h2>" in post["body_html"]
    assert content.validate(post) == []


def test_validate_blocks_bad_posts():
    bad = content.normalize({**POST, "body_html": "<p>short [insert photo]</p>", "sources": [], "labels": []})
    errors = " ".join(content.validate(bad))
    for part in ("짧습니다", "[insert", "출처", "라벨"):
        assert part in errors
    md = content.normalize({**POST, "body_html": "<p>x</p>\n## Heading\n" + BODY})
    assert any("마크다운" in e for e in content.validate(md))


def test_sanitize_removes_scripts_and_handlers():
    html = content.sanitize_html('<p onclick="x()">a</p><script>alert(1)</script><iframe src="x"></iframe>')
    assert html == "<p>a</p>"


def test_find_skill_in_nested_folder(cfg, tmp_path):
    nested = tmp_path / "codex_home" / "skills" / "korea-explained-blogger" / "korea-explained-blogger"
    nested.mkdir(parents=True)
    (nested / "SKILL.md").write_text("---\nname: korea-explained-blogger\n---")
    assert writer.find_skill(cfg) == nested / "SKILL.md"


def test_publish_at(cfg):
    now = datetime(2026, 9, 28, 6, 0, tzinfo=KST)
    assert pipeline.publish_at(cfg, now) is None
    cfg.publish_time = "21:30"
    assert pipeline.publish_at(cfg, now) == "2026-09-28T21:30:00+09:00"
    assert pipeline.publish_at(cfg, datetime(2026, 9, 28, 22, 0, tzinfo=KST)) is None


def test_run_publishes_and_records(cfg, tmp_path, monkeypatch):
    script, state = fake_codex(tmp_path)
    cfg.codex_bin = str(script)
    fake = FakeBlogger()
    fake.live = [{"id": "9", "title": "Old post", "url": "https://myblog.blogspot.com/old.html",
                  "published": "2026-09-01T10:00:00+09:00", "labels": ["Food"]}]
    fake.install(monkeypatch)

    assert pipeline.run(cfg) == 0
    assert fake.published == [("1", None)]
    assert fake.drafts["1"]["title"] == POST["title"]
    write_prompt = (state / "prompt_0.txt").read_text(encoding="utf-8")
    assert "$korea-explained-blogger" in write_prompt and "Old post" in write_prompt
    entries = history.load(cfg.history_file)
    assert [e["source"] for e in entries] == ["blog", "autopost"]
    assert entries[-1]["url"].endswith("post-1.html")

    assert pipeline.run(cfg) == 0                   # 같은 날 다시 돌려도 두 번 올리지 않는다
    assert len(fake.published) == 1


def test_factcheck_fix_round_then_pass(cfg, tmp_path, monkeypatch):
    script, state = fake_codex(tmp_path, verdicts=("fix", "pass"))
    cfg.codex_bin = str(script)
    fake = FakeBlogger()
    fake.install(monkeypatch)
    assert pipeline.run(cfg) == 0
    assert fake.drafts["1"]["title"].endswith("(fixed)")


def test_factcheck_fail_retries_then_gives_up(cfg, tmp_path, monkeypatch):
    script, state = fake_codex(tmp_path, verdicts=("fail",))
    cfg.codex_bin = str(script)
    fake = FakeBlogger()
    fake.install(monkeypatch)
    assert pipeline.run(cfg) == 1
    assert fake.drafts == {}
    prompts = sorted(state.glob("prompt_*.txt"))
    assert sum("DELIVERABLE" in p.read_text(encoding="utf-8") for p in prompts) == cfg.max_attempts
    assert "rejected for the reasons" in prompts[-2].read_text(encoding="utf-8")


def test_resume_reuses_draft_after_publish_error(cfg, tmp_path, monkeypatch):
    script, state = fake_codex(tmp_path)
    cfg.codex_bin = str(script)
    fake = FakeBlogger()
    fake.install(monkeypatch)
    calls = {"n": 0}

    def flaky_publish(c, post_id, when=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise api.BloggerError("HTTP 500")
        return FakeBlogger.publish(fake, c, post_id, when)
    monkeypatch.setattr(api, "publish", flaky_publish)

    assert pipeline.run(cfg) == 1
    assert pipeline.run(cfg) == 0
    assert len(fake.drafts) == 1 and fake.published == [("1", None)]
    assert sum("DELIVERABLE" in p.read_text(encoding="utf-8") for p in state.glob("prompt_*.txt")) == 1


def test_draft_mode_does_not_publish(cfg, tmp_path, monkeypatch):
    script, _ = fake_codex(tmp_path)
    cfg.codex_bin = str(script)
    fake = FakeBlogger()
    fake.install(monkeypatch)
    assert pipeline.run(cfg, draft=True) == 0
    assert fake.drafts and not fake.published
    assert history.load(cfg.history_file) == []


def test_scheduled_publish(cfg, tmp_path, monkeypatch):
    script, _ = fake_codex(tmp_path)
    cfg.codex_bin = str(script)
    fake = FakeBlogger()
    fake.install(monkeypatch)
    monkeypatch.setattr(pipeline, "publish_at", lambda c: "2026-09-28T21:30:00+09:00")
    assert pipeline.run(cfg) == 0
    assert fake.published == [("1", "2026-09-28T21:30:00+09:00")]


def test_access_token_refresh(cfg, tmp_path, monkeypatch):
    cfg.client_secret_file = tmp_path / "cs.json"
    cfg.client_secret_file.write_text(json.dumps({"installed": {"client_id": "id", "client_secret": "sec"}}))
    cfg.token_file = tmp_path / "tok.json"
    cfg.token_file.write_text(json.dumps({"refresh_token": "r1", "access_token": "old", "expires_at": 0}))
    sent = {}

    def fake_post(url, fields):
        sent.update(fields)
        return {"access_token": "new", "expires_in": 3600}
    monkeypatch.setattr(api, "_post_form", fake_post)
    assert api.access_token(cfg) == "new"
    assert sent["grant_type"] == "refresh_token" and sent["refresh_token"] == "r1"
    assert json.loads(cfg.token_file.read_text())["refresh_token"] == "r1"
    assert api.access_token(cfg) == "new"            # 만료 전에는 다시 요청하지 않는다
