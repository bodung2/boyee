"""구글 블로거 자동 발행: 가짜 Codex CLI와 가짜 Blogger API로 전체 흐름을 확인한다."""
import json
import sys
from datetime import datetime

import pytest

from blogger_autopost import api, content, hosting, illustrations, photos, pipeline, writer
from blogger_autopost.config import BloggerConfig
from naver_autopost import history
from naver_autopost.pipeline import KST

BODY = ("<p>Intro paragraph about the topic.</p><h2>How it works</h2>"
        + "<p>" + "A verified sentence about Korea. " * 80 + "</p>"
        + "<h2>Sources</h2><ul><li><a href=\"https://www.korea.net/a\">Korea.net</a></li></ul>")
POST = {"title": "How the T-money Card Works in Seoul", "body_html": BODY, "labels": ["Transport", "Seoul"],
        "topic": "T-money", "summary": "One line.",
        "sources": [{"title": f"s{i}", "publisher": "p", "url": f"https://example.org/{i}"} for i in range(3)]}


def fake_codex(tmp_path, verdicts=("pass",), refuse=()):
    """가짜 codex: 글쓰기 프롬프트면 post.json을, 팩트체크면 판정 JSON을, 수정 요청이면 고친 post.json을 만든다."""
    state = tmp_path / "codex_state"
    state.mkdir(exist_ok=True)
    (state / "verdicts.json").write_text(json.dumps(list(verdicts)))
    (state / "post.json").write_text(json.dumps(POST))
    (state / "refuse.json").write_text(json.dumps(list(refuse)))
    script = tmp_path / "codex"
    script.write_text(f"""#!{sys.executable}
import json, pathlib, sys
state = pathlib.Path({str(state)!r})
args = sys.argv[1:]
out = pathlib.Path(args[args.index("--output-last-message") + 1])
prompt = sys.stdin.read()
if "--model" in args and args[args.index("--model") + 1] in json.loads((state / "refuse.json").read_text()):
    sys.stderr.write("ERROR: The 'gpt-5.6-sol' model is not supported when using Codex with a ChatGPT account.")
    sys.exit(1)
(state / f"args_{{len(list(state.glob('args_*.txt')))}}.txt").write_text(json.dumps(args))
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
elif "PHOTO REVIEW" in prompt:
    import re
    slots = re.findall(r"Slot (s\\d+)", prompt)
    out.write_text(json.dumps({{"choices": {{s: s + "c1" for s in slots}}, "notes": {{}}}}))
elif "ILLUSTRATION REVIEW" in prompt:
    import re
    ids = re.findall(r"= ([ip]\\d+) ", prompt)
    out.write_text(json.dumps({{i: ("ok" if i != "i2" or "REJECT_I2" not in prompt else "text in image") for i in ids}}))
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
        self.drafts, self.published, self.live, self.scheduled = {}, [], [], []

    def install(self, monkeypatch):
        monkeypatch.setattr(api, "resolve_blog_id", lambda cfg: "123")
        monkeypatch.setattr(api, "list_posts", lambda cfg, status="live", limit=2000:
                            list(self.live) if status == "live" else list(self.scheduled) if status == "scheduled" else [])
        monkeypatch.setattr(api, "create_draft", self.create_draft)
        monkeypatch.setattr(api, "publish", self.publish)

    def create_draft(self, cfg, title, content_html, labels):
        pid = str(len(self.drafts) + 1)
        self.drafts[pid] = {"title": title, "content": content_html, "labels": labels}
        return {"id": pid, "status": "DRAFT"}

    def publish(self, cfg, post_id, when=None):
        self.published.append((post_id, when))
        post = {"id": post_id, "status": "SCHEDULED" if when else "LIVE", "title": self.drafts[post_id]["title"],
                "url": f"https://myblog.blogspot.com/2026/09/post-{post_id}.html"}
        (self.scheduled if when else self.live).append(post)
        return post

    def delete(self, post_id):
        self.live = [p for p in self.live if p["id"] != post_id]
        self.scheduled = [p for p in self.scheduled if p["id"] != post_id]


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
    c.photos = 0
    c.illustrations = 0
    c.photo_fallback = False
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


def commons_page(i, title, license="CC BY-SA 4.0", width=4000, mime="image/jpeg", restrictions=""):
    return {"index": i, "title": f"File:{title}.jpg", "imageinfo": [{
        "mime": mime, "width": width, "height": 3000,
        "thumburl": f"https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/{title}.jpg/1200px-{title}.jpg",
        "thumbwidth": 1200, "thumbheight": 900,
        "descriptionurl": f"https://commons.wikimedia.org/wiki/File:{title}.jpg",
        "extmetadata": {"LicenseShortName": {"value": license}, "Artist": {"value": "<a href='u'>Kim</a>"},
                        "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0"},
                        "ImageDescription": {"value": f"{title} in Seoul"},
                        "Restrictions": {"value": restrictions}}}]}


def fake_commons(url):
    return {"query": {"pages": [
        commons_page(1, "NC_photo", license="CC BY-NC-SA 2.0"),
        commons_page(2, "Tiny", width=300),
        commons_page(3, "Person", restrictions="personality"),
        commons_page(4, "Gyeongbokgung"),
        commons_page(5, "Gyeongbokgung_2", license="Public domain"),
    ]}}


def test_license_filter():
    infos = {p["title"]: p["imageinfo"][0] for p in fake_commons("")["query"]["pages"]}
    assert not photos.license_ok(infos["File:NC_photo.jpg"])
    assert not photos.license_ok(infos["File:Person.jpg"])
    assert photos.license_ok(infos["File:Gyeongbokgung.jpg"])
    gfdl = commons_page(9, "g", license="GFDL")["imageinfo"][0]
    kogl = commons_page(9, "k", license="KOGL Type 1")["imageinfo"][0]
    assert not photos.license_ok(gfdl) and photos.license_ok(kogl)
    assert [c["title"] for c in photos.search("x", fetch=fake_commons)] == \
        ["File:Gyeongbokgung.jpg", "File:Gyeongbokgung_2.jpg"]


def test_insert_positions():
    body = "<p>a</p><h2>One</h2><p>b</p><h2>Two</h2><p>c</p>"
    assert photos.insert(body, 0, "[F]").startswith("<p>a</p>[F]<h2>One")       # 글은 그림으로 시작하지 않는다
    assert photos.insert(body, 2, "[F]") == "<p>a</p><h2>One</h2><p>b</p><h2>Two</h2>[F]<p>c</p>"
    assert photos.insert(body, 9, "[F]").endswith("<h2>Two</h2>[F]<p>c</p>")


def test_run_with_photos(cfg, tmp_path, monkeypatch):
    script, state = fake_codex(tmp_path)
    post = dict(POST, photos=[{"section": 1, "subject": "Gyeongbokgung palace", "search": "Gyeongbokgung",
                               "alt": "Palace", "caption": "Gyeongbokgung in spring"}])
    (state / "post.json").write_text(json.dumps(post))
    cfg.codex_bin = str(script)
    cfg.photos = 3
    monkeypatch.setattr(photos, "_get", lambda params, fetch=None: fake_commons(""))
    monkeypatch.setattr(photos, "_download", lambda url, out, fb=None: (out.parent.mkdir(parents=True, exist_ok=True),
                                                                         out.write_bytes(b"jpg"), out)[2])
    fake = FakeBlogger()
    fake.install(monkeypatch)
    assert pipeline.run(cfg) == 0
    body = fake.drafts["1"]["content"]
    assert '<h2>How it works</h2><figure' in body
    assert "1200px-Gyeongbokgung.jpg" in body and "CC BY-SA 4.0" in body and "Kim" in body
    assert "NC_photo" not in body
    review_args = [json.loads(p.read_text()) for p in state.glob("args_*.txt")
                   if "--image" in json.loads(p.read_text())]
    assert len(review_args) == 1
    imgs = [a for i, a in enumerate(review_args[0]) if review_args[0][i - 1] == "--image"]
    assert len(imgs) == 2 and all(a.endswith(".jpg") for a in imgs)
    assert "-" == review_args[0][-1]


def test_photo_failure_still_publishes(cfg, tmp_path, monkeypatch):
    script, state = fake_codex(tmp_path)
    (state / "post.json").write_text(json.dumps(dict(POST, photos=[{"section": 0, "search": "x", "subject": "x"}])))
    cfg.codex_bin = str(script)
    cfg.photos = 3

    def boom(params, fetch=None):
        raise OSError("network down")
    monkeypatch.setattr(photos, "_get", boom)
    fake = FakeBlogger()
    fake.install(monkeypatch)
    assert pipeline.run(cfg) == 0
    assert "<figure" not in fake.drafts["1"]["content"]


def test_model_and_effort_args_and_fallback(cfg, tmp_path, monkeypatch):
    script, state = fake_codex(tmp_path, refuse=("gpt-5.6-sol",))
    cfg.codex_bin = str(script)
    cfg.codex_model, cfg.codex_effort, cfg.codex_fallback_model = "gpt-5.6-sol", "low", "gpt-5.6-terra"
    fake = FakeBlogger()
    fake.install(monkeypatch)
    assert pipeline.run(cfg) == 0
    args = json.loads((state / "args_0.txt").read_text())
    assert args[args.index("--model") + 1] == "gpt-5.6-terra"
    assert "model_reasoning_effort=low" in args
    assert "gpt-5.6-terra" in cfg.model_note


def _with_drive_token(cfg, tmp_path, scope=api.SCOPE):
    cfg.token_file = tmp_path / "tok.json"
    cfg.token_file.write_text(json.dumps({"refresh_token": "r", "access_token": "a", "expires_at": 9e12,
                                          "scope": scope}))


def test_photos_and_illustrations_in_one_post(cfg, tmp_path, monkeypatch):
    script, state = fake_codex(tmp_path)
    body = BODY.replace("<h2>Sources</h2>", "<h2>Getting there</h2><p>x</p><h2>Sources</h2>")
    post = dict(POST, body_html=body,
                photos=[{"section": 2, "subject": "Gyeongbokgung palace", "search": "nothing-here",
                         "alternatives": ["Gyeongbokgung"], "alt": "Palace", "caption": "Real palace"}],
                illustrations=[{"section": 0, "prompt": "a traveller tapping a card", "alt": "tap", "caption": "Tap in"},
                               {"section": 1, "prompt": "a map-free subway scene", "alt": "sub", "caption": "Ride"}])
    (state / "post.json").write_text(json.dumps(post))
    cfg.codex_bin = str(script)
    cfg.photos, cfg.illustrations = 1, 2
    _with_drive_token(cfg, tmp_path)
    searched = []

    def fake_get(params, fetch=None):
        searched.append(params["gsrsearch"])
        return fake_commons("") if "Gyeongbokgung" in params["gsrsearch"] else {"query": {"pages": []}}
    monkeypatch.setattr(photos, "_get", fake_get)
    monkeypatch.setattr(photos, "_download", lambda url, out, fb=None: (out.parent.mkdir(parents=True, exist_ok=True),
                                                                         out.write_bytes(b"jpg"), out)[2])
    generated = []

    def fake_generate(img_cfg, prompt, out):
        generated.append(prompt)
        from PIL import Image
        Image.new("RGB", (64, 36)).save(out)
        return out
    monkeypatch.setattr(illustrations.codex_image, "generate_image", fake_generate)
    uploads = []
    monkeypatch.setattr(illustrations.hosting, "upload",
                        lambda c, path, name: uploads.append(name) or f"https://lh3.googleusercontent.com/d/{path.stem}")
    fake = FakeBlogger()
    fake.install(monkeypatch)
    assert pipeline.run(cfg) == 0

    html = fake.drafts["1"]["content"]
    assert searched[:2] == ["filetype:bitmap nothing-here", "filetype:bitmap Gyeongbokgung"]
    assert html.startswith("<p>Intro paragraph about the topic.</p><figure") and "/d/illust_1" in html.split("<h2>")[0]
    assert '<h2>How it works</h2><figure' in html and "/d/illust_2" in html
    assert '<h2>Getting there</h2><figure' in html and "Gyeongbokgung.jpg" in html
    assert html.count("AI-generated illustration") == 2 and html.count("<figure") == 3
    assert all("NOT a photorealistic photo" in p for p in generated) and len(uploads) == 2
    stage = json.loads((cfg.output_dir / pipeline.today_kst() / "stage.json").read_text())
    assert stage["illustrations_note"] == "생성 그림 2장" and stage["photos_note"] == "실제 사진 1장"
    write_prompt = (state / "prompt_0.txt").read_text(encoding="utf-8")
    assert "follow\nits guidance on images" in write_prompt and "exactly 2" in write_prompt


def test_rejected_illustration_is_dropped(cfg, tmp_path, monkeypatch):
    script, state = fake_codex(tmp_path)
    post = dict(POST, title="REJECT_I2 post", illustrations=[{"section": 0, "prompt": "a"}, {"section": 1, "prompt": "b"}])
    (state / "post.json").write_text(json.dumps(post))
    cfg.codex_bin = str(script)
    cfg.illustrations = 2
    _with_drive_token(cfg, tmp_path)

    def fake_generate(img_cfg, prompt, out):
        from PIL import Image
        Image.new("RGB", (64, 36)).save(out)
        return out
    monkeypatch.setattr(illustrations.codex_image, "generate_image", fake_generate)
    monkeypatch.setattr(illustrations.hosting, "upload", lambda c, path, name: f"https://x/{path.stem}")
    fake = FakeBlogger()
    fake.install(monkeypatch)
    assert pipeline.run(cfg) == 0
    html = fake.drafts["1"]["content"]
    assert "https://x/illust_1" in html and "illust_2" not in html


def test_illustrations_skipped_without_drive_scope(cfg, tmp_path, monkeypatch):
    post = dict(POST, illustrations=[{"section": 0, "prompt": "a"}])
    cfg.illustrations = 2
    _with_drive_token(cfg, tmp_path, scope=api.BLOGGER_SCOPE)
    monkeypatch.setattr(illustrations.codex_image, "generate_image",
                        lambda *a: (_ for _ in ()).throw(AssertionError("should not generate")))
    n, note = illustrations.add_illustrations(cfg, post, tmp_path)
    assert n == 0 and "auth" in note


def test_drive_upload_returns_working_url(cfg, tmp_path, monkeypatch):
    _with_drive_token(cfg, tmp_path)
    from PIL import Image
    img = tmp_path / "a.png"
    Image.new("RGB", (2000, 1125)).save(img)
    calls = []

    def fake_call(c, url, body=None, content_type="application/json", method=None):
        calls.append((url, content_type))
        if "folder" in (body or b"").decode("latin-1") and "upload" not in url:
            return {"id": "FOLDER"}
        if "upload" in url:
            assert b'"parents": ["FOLDER"]' in body
            return {"id": "FILE1"}
        return {}
    monkeypatch.setattr(hosting, "_call", fake_call)
    checked = []
    url = hosting.upload(cfg, img, "x.jpg", check=lambda u: checked.append(u) or "thumbnail" in u, wait=0)
    assert url == "https://drive.google.com/thumbnail?id=FILE1&sz=w1600"
    assert checked[0] == "https://lh3.googleusercontent.com/d/FILE1"
    assert any(u.endswith("/files/FILE1/permissions") for u, _ in calls)
    assert json.loads(cfg.token_file.with_name("blogger_drive_folder.json").read_text())["id"] == "FOLDER"


def test_missing_photo_is_replaced_by_photorealistic_ai_image(cfg, tmp_path, monkeypatch):
    script, state = fake_codex(tmp_path)
    post = dict(POST,
                photos=[{"section": 1, "subject": "Namsan tower at dusk", "search": "zzz",
                         "fallback_prompt": "Namsan Seoul Tower at dusk seen from a street", "caption": "Namsan"}],
                illustrations=[{"section": 0, "prompt": "a traveller with a map-free phone", "caption": "Plan"}])
    (state / "post.json").write_text(json.dumps(post))
    cfg.codex_bin = str(script)
    cfg.photos, cfg.illustrations, cfg.photo_fallback = 1, 1, True
    _with_drive_token(cfg, tmp_path)
    monkeypatch.setattr(photos, "_get", lambda params, fetch=None: {"query": {"pages": []}})
    prompts = {}

    def fake_generate(img_cfg, prompt, out):
        prompts[out.name] = prompt
        from PIL import Image
        Image.new("RGB", (64, 36)).save(out)
        return out
    monkeypatch.setattr(illustrations.codex_image, "generate_image", fake_generate)
    monkeypatch.setattr(illustrations.hosting, "upload", lambda c, path, name: f"https://x/{path.stem}")
    fake = FakeBlogger()
    fake.install(monkeypatch)
    assert pipeline.run(cfg) == 0

    html = fake.drafts["1"]["content"]
    assert '<h2>How it works</h2><figure' in html and "https://x/photo_ai_1" in html
    assert "AI-generated image (not an actual photo)" in html and "AI-generated illustration" in html
    assert "photorealistic" in prompts["photo_ai_1.png"] and "Namsan Seoul Tower" in prompts["photo_ai_1.png"]
    assert "NOT a photorealistic" in prompts["illust_1.png"]
    review = [p.read_text(encoding="utf-8") for p in state.glob("prompt_*.txt")
              if "ILLUSTRATION REVIEW" in p.read_text(encoding="utf-8")][0]
    assert "p1 (kind=photo)" in review and "i1 (kind=illustration)" in review
    stage = json.loads((cfg.output_dir / pipeline.today_kst() / "stage.json").read_text())
    assert "실사풍 생성 이미지 1장" in stage["illustrations_note"]


def test_no_fallback_when_disabled(cfg, tmp_path):
    post = dict(POST, photo_misses=[{"section": 1, "subject": "x"}])
    cfg.illustrations, cfg.photo_fallback = 0, False
    assert illustrations._jobs(cfg, post) == []


def test_deleted_scheduled_post_is_rewritten_on_rerun(cfg, tmp_path, monkeypatch):
    script, state = fake_codex(tmp_path)
    cfg.codex_bin = str(script)
    fake = FakeBlogger()
    fake.install(monkeypatch)
    monkeypatch.setattr(pipeline, "publish_at", lambda c: "2026-10-01T21:00:00+09:00")
    assert pipeline.run(cfg) == 0
    assert pipeline.run(cfg) == 0                     # 예약 글이 살아 있으면 다시 쓰지 않는다
    assert len(fake.published) == 1

    fake.delete("1")                                   # 사용자가 블로거에서 예약 글을 지움
    assert pipeline.run(cfg) == 0
    assert [p[0] for p in fake.published] == ["1", "2"]
    entries = history.load(cfg.history_file)
    assert [e["post_id"] for e in entries if e["source"] == "autopost"] == ["2"]
    assert sum("DELIVERABLE" in p.read_text(encoding="utf-8") for p in state.glob("prompt_*.txt")) == 2


def test_diagnose_collects_report(cfg, tmp_path, monkeypatch):
    from blogger_autopost import diagnose
    _with_drive_token(cfg, tmp_path)
    post = {"id": "1", "title": "T-money guide", "url": "https://kb.blogspot.com/2026/10/t.html",
            "published": "2026-10-01T21:00:00+09:00", "labels": ["Transport"],
            "content": '<p>Hello world text</p><h2>A</h2><img src="x" alt="a"><img src="y">'
                       '<a href="https://kb.blogspot.com/2026/09/o.html">o</a><a href="https://gov.kr">g</a>'}

    def fake_request(c, method, path, params=None, body=None):
        if path.endswith("/posts"):
            return {"items": [post]}
        return {"name": "Korea Breakdown", "url": "https://kb.blogspot.com/", "posts": {"totalItems": 1}}
    monkeypatch.setattr(api, "resolve_blog_id", lambda c: "123")
    monkeypatch.setattr(api, "request", fake_request)
    monkeypatch.setattr(api, "list_posts", lambda c, status="live", limit=2000: [])
    page = ('<html><head><title>T-money guide</title><meta name="robots" content="index,follow">'
            '<link rel="canonical" href="https://kb.blogspot.com/2026/10/t.html"></head></html>')
    monkeypatch.setattr(diagnose, "_fetch", lambda url: (200, "<loc>a</loc><loc>b</loc>" if "sitemap" in url else page, {}))
    calls = []

    def fake_google(c, url, body=None):
        calls.append(url)
        if url.endswith("/sites"):
            return {"siteEntry": [{"siteUrl": "https://kb.blogspot.com/"}]}
        if "searchAnalytics" in url:
            return {"rows": [{"keys": ["2026-10-02"], "clicks": 0, "impressions": 3}]}
        if "inspect" in url:
            return {"inspectionResult": {"indexStatusResult": {"coverageState": "Discovered - currently not indexed"}}}
        return {}
    monkeypatch.setattr(diagnose, "_google", fake_google)

    report = json.loads(diagnose.run(cfg, tmp_path / "diag").read_text(encoding="utf-8"))
    p = report["posts"][0]
    assert (p["images"], p["images_without_alt"], p["internal_links"], p["external_links"]) == (2, 1, 1, 1)
    home = report["public_pages"]["home"]
    assert home["meta_description"] is None and home["meta_robots"] == "index,follow"
    assert report["public_pages"]["sitemap"]["url_count"] == 2
    sc = report["search_console"]
    assert sc["site"] == "https://kb.blogspot.com/"
    assert sc["inspections"][0]["coverageState"] == "Discovered - currently not indexed"
    assert "content" not in json.dumps(report["posts"])        # 본문 전체는 담지 않는다


def test_diagnose_without_search_console_scope(cfg, tmp_path):
    from blogger_autopost import diagnose
    _with_drive_token(cfg, tmp_path, scope=f"{api.BLOGGER_SCOPE} {api.DRIVE_SCOPE}")
    assert "auth" in diagnose.search_console(cfg, "https://kb.blogspot.com/", [])["_error"]


AUTO_BODY = ('<figure style="margin:1.5em 0;text-align:center"><img src="https://x/1" alt="a"><figcaption>'
             'Editorial illustration: sizes<br>AI-generated illustration</figcaption></figure>'
             '<p>A Korean apartment can be described as 84 square meters.</p><h2>Why</h2><p>Because.</p>')


def test_move_leading_images_for_auto_and_editor_posts():
    from blogger_autopost import seo
    new, n = seo.move_leading_images(AUTO_BODY)
    assert n == 1 and new.startswith("<p>A Korean apartment") and new.index("<figure") < new.index("<h2>")
    editor = ('<table align="center" class="tr-caption-container"><tbody><tr><td><a href="u"><img src="i"></a></td></tr>'
              '<tr><td class="tr-caption">Editorial illustration</td></tr></tbody></table><br>'
              '<p>Quick answer: phones are banned during class.</p><p>More.</p>')
    new, n = seo.move_leading_images(editor)
    assert n == 1 and new.startswith("<br><p>Quick answer") and new.index("tr-caption") > new.index("</p>")
    assert seo.move_leading_images("<p>Text first</p><figure>x</figure>") == ("<p>Text first</p><figure>x</figure>", 0)


def test_related_links_are_picked_by_labels_and_replaced_not_duplicated():
    from blogger_autopost import seo
    cands = [{"url": "https://b/1", "title": "Trash", "labels": ["Life in Korea"], "published": "2026-10-02"},
             {"url": "https://b/2", "title": "Jeonse", "labels": ["Housing in Korea", "Renting"], "published": "2026-09-01"},
             {"url": "https://b/3", "title": "Me", "labels": ["Housing in Korea"], "published": "2026-10-03"},
             {"url": "https://b/4", "title": "Hagwon", "labels": ["Education"], "published": "2026-08-28"},
             {"url": "https://b/5", "title": "Teachers", "labels": ["Education"], "published": "2026-08-31"}]
    body, ch = seo.improve(AUTO_BODY, "https://b/3", "Me", ["Housing in Korea", "Life in Korea"], cands)
    assert ch["related"] == ["Trash", "Jeonse", "Teachers"]     # 라벨 겹침 1개끼리는 최근 글 먼저
    assert body.count('class="kb-related"') == 1 and "https://b/3" not in body
    again, _ = seo.improve(body, "https://b/3", "Me", ["Housing in Korea", "Life in Korea"], cands)
    assert again == body                                   # 여러 번 고쳐도 같은 결과


def test_fix_posts_preview_and_apply(cfg, tmp_path, monkeypatch):
    from blogger_autopost import fixposts
    live = [{"id": "3", "title": "Sizes", "url": "https://b/3", "labels": ["Housing"], "published": "2026-10-03",
             "content": AUTO_BODY},
            {"id": "2", "title": "Jeonse", "url": "https://b/2", "labels": ["Housing"], "published": "2026-09-01",
             "content": "<p>Jeonse text</p>"}]
    monkeypatch.setattr(api, "resolve_blog_id", lambda c: "123")
    monkeypatch.setattr(api, "request", lambda c, m, path, params=None, body=None:
                        {"items": live if params["status"] == "live" else []})
    updates = {}
    monkeypatch.setattr(api, "update_content", lambda c, pid, content: updates.__setitem__(pid, content))

    preview = fixposts.run(cfg)
    assert {r["id"] for r in preview} == {"2", "3"} and not updates
    sizes = next(r for r in preview if r["id"] == "3")
    assert sizes["moved_images"] == 1 and sizes["opening_after"].startswith("A Korean apartment")

    fixposts.run(cfg, apply=True)
    assert set(updates) == {"2", "3"} and 'href="https://b/2"' in updates["3"]
    backup = next((cfg.output_dir / "backup").iterdir())
    assert (backup / "3.html").read_text(encoding="utf-8") == AUTO_BODY
    restored = {}
    monkeypatch.setattr(api, "update_content", lambda c, pid, content: restored.__setitem__(pid, content))
    assert fixposts.restore(cfg, backup) == 2 and restored["3"] == AUTO_BODY


def test_check_meta_counts_description_tags(cfg, monkeypatch):
    from blogger_autopost import diagnose
    monkeypatch.setattr(api, "list_posts", lambda c, status="live", limit=2000: [
        {"title": "A", "url": "https://b/a"}, {"title": "B", "url": "https://b/b"}, {"title": "C", "url": "https://b/c"}])
    pages = {"https://b/a": '<meta content="Short answer about A." name="description"/>',
             "https://b/b": "<title>B</title>",
             "https://b/c": '<meta name="description" content="x"><meta content="y" name="description"/>'}
    monkeypatch.setattr(diagnose, "_fetch", lambda url: (200, pages[url], {}))
    rows = {r["title"]: r for r in diagnose.check_meta(cfg)}
    assert rows["A"]["meta_description"] == "Short answer about A." and rows["A"]["tags"] == 1
    assert rows["B"]["tags"] == 0 and rows["C"]["tags"] == 2
