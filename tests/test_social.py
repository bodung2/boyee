"""인스타·쓰레드: 초안 검사, 이미지 변환, 토큰 갱신, 발행 흐름(Meta API는 가짜)."""
import json
from datetime import date, timedelta

import pytest
from PIL import Image

from naver_autopost import content, history, pipeline, profiles, social
from naver_autopost.config import Config
from tests.sample_post import make_post

URL = "https://blog.naver.com/flw3148/224425042666"


def good_social(**over):
    s = {
        "blog_url": URL,
        "threads": {"text": f"늘봄학교 2026 핵심만 짚어볼게요.\n첫째 요점부터요.\n더 자세한 건 블로그에 👉 {URL}\n여러분 학교는요? 👇",
                    "topic_tag": "교육정책"},
        "instagram": {"caption": f"2026 늘봄학교, 이렇게 바뀝니다.\n저장해두고 보세요.\n자세한 내용 👉 {URL}",
                      "hashtags": ["#교육정책", "#학부모", "#늘봄학교"]},
    }
    s.update(over)
    return s


@pytest.fixture
def cfg(tmp_path):
    c = Config.load("edu")
    c.output_dir = tmp_path / "out"
    c.data_dir = tmp_path / "data"
    c.history_file = c.data_dir / "published_edu.json"
    c.log_dir = tmp_path / "logs"
    c.telegram_bot_token = ""
    c.threads_token, c.instagram_token, c.imgbb_api_key = "TH", "IG", "KEY"
    c.threads_user_id = c.instagram_user_id = ""
    return c


@pytest.fixture(autouse=True)
def fake_hosts(monkeypatch):
    """이미지 업로드·확인은 가짜로(두 곳에 올린 것처럼)."""
    monkeypatch.setattr(social, "_HOSTS", (
        ("imgbb", lambda c, p: "https://i.ibb.co/x/social_image.jpg"),
        ("litterbox", lambda c, p: "https://litter.catbox.moe/abc.jpg"),
    ))
    monkeypatch.setattr(social, "_is_image_url", lambda url: True)


def test_good_draft_passes():
    assert social.validate(good_social(), make_post(), URL, profiles.get("edu")) == []


def test_missing_url_and_invented_number_are_caught():
    s = good_social()
    s["threads"]["text"] = "참여율이 87% 늘었대요!"
    errors = social.validate(s, make_post(), URL)
    assert any("블로그 주소" in e for e in errors)
    assert any("블로그에 없는 숫자" in e and "87" in e for e in errors)


def test_numbers_in_url_and_hashtags_are_ignored():
    s = good_social()
    s["instagram"]["hashtags"] = ["#교육정책2027"]
    assert social.validate(s, make_post(), URL) == []


def test_limits_and_placeholders():
    s = good_social()
    s["threads"]["text"] = "가" * 501 + URL
    s["instagram"]["caption"] += " ✍️"
    s["instagram"]["hashtags"] = ["교육 정책"]
    errors = social.validate(s, make_post(), URL)
    assert any("500자" in e for e in errors)
    assert any("✍️" in e for e in errors)
    assert any("해시태그 형식" in e for e in errors)


def test_childhood_guardrail_applies_to_social():
    s = good_social()
    s["threads"]["text"] = f"4세라면 이걸 통과해야 해요. {URL}"
    assert any("통과해야" in e for e in social.validate(s, make_post(), URL, profiles.get("childhood")))


def test_tall_infographic_is_padded_to_4x5_jpeg(tmp_path):
    src = tmp_path / "i.png"
    Image.new("RGB", (600, 900), "#123456").save(src)
    out = social.to_instagram_jpeg(src, tmp_path / "o.jpg")
    img = Image.open(out)
    assert img.format == "JPEG" and img.size == (1080, 1350)


def test_token_is_refreshed_weekly_and_env_change_wins(cfg, monkeypatch):
    calls = []

    def fake(method, url, params, timeout=60):
        calls.append(params["access_token"])
        return {"access_token": f"new-{len(calls)}"}

    monkeypatch.setattr(social, "_request", fake)
    assert social.token(cfg, "threads") == "new-1"            # 처음엔 갱신해서 저장
    assert social.token(cfg, "threads") == "new-1"            # 일주일 안에는 저장한 것 그대로
    state = json.loads(social._tokens_file(cfg).read_text())
    state["threads"]["refreshed"] = (date.today() - timedelta(days=8)).isoformat()
    social._tokens_file(cfg).write_text(json.dumps(state))
    assert social.token(cfg, "threads") == "new-2" and calls[-1] == "new-1"
    cfg.threads_token = "TH2"                                 # .env에 새 토큰을 넣으면 그것부터
    assert social.token(cfg, "threads") == "new-3" and calls[-1] == "TH2"


def _published_day(cfg, social_data=None, infographic=True):
    today = pipeline.today_kst()
    out = cfg.output_dir / today
    out.mkdir(parents=True)
    (out / "post.json").write_text(json.dumps(make_post(), ensure_ascii=False), encoding="utf-8")
    if social_data is not None:
        (out / "social.json").write_text(json.dumps(social_data, ensure_ascii=False), encoding="utf-8")
    if infographic:
        Image.new("RGB", (600, 900), "white").save(out / "infographic.png")
    history.append(cfg.history_file, {"date": today, "url": URL, "source": "autopost"})
    return today, out


class FakeMeta:
    def __init__(self, reject=()):
        self.calls = []
        self.reject = reject          # 이 주소의 이미지는 가져오지 못한 것처럼 거절

    def __call__(self, method, url, params, timeout=60):
        self.calls.append((method, url, dict(params)))
        if params.get("image_url") in self.reject:
            raise social.SocialError(f"{url} → HTTP 400: Only photo or video can be accepted as media type.")
        if "refresh_access_token" in url:
            return {"access_token": params["access_token"]}
        if url.endswith("/me"):
            return {"id": "T1", "user_id": "I1", "username": "kkus"}
        if url.endswith("/threads") or url.endswith("/media"):
            return {"id": "C1"}
        if url.endswith("_publish"):
            return {"id": "M1"}
        if "fields" in params and params["fields"] in ("status", "status_code"):
            return {params["fields"]: "FINISHED"}
        if params.get("fields") == "permalink":
            return {"permalink": ("https://www.threads.net/@kkus/post/1" if "threads" in url
                                  else "https://www.instagram.com/p/1/")}
        return {}


def test_publish_posts_both_channels_once(cfg, monkeypatch):
    today, out = _published_day(cfg, good_social())
    meta = FakeMeta()
    monkeypatch.setattr(social, "_request", meta)
    monkeypatch.setattr(social, "_sleep", lambda s: None)
    assert social.publish(cfg, today) == 0
    th = [c for c in meta.calls if c[1].endswith("/T1/threads")][0][2]
    assert th["media_type"] == "IMAGE" and URL in th["text"] and th["image_url"].startswith("https://i.ibb.co")
    ig = [c for c in meta.calls if c[1].endswith("/I1/media")][0][2]
    assert "#교육정책" in ig["caption"] and URL in ig["caption"]
    state = json.loads((out / "social_state.json").read_text(encoding="utf-8"))
    assert state["threads"]["url"].startswith("https://www.threads.net")
    assert state["instagram"]["url"].startswith("https://www.instagram.com")
    n = len(meta.calls)
    assert social.publish(cfg, today) == 0 and len(meta.calls) == n     # 두 번 올리지 않는다


def test_missing_infographic_is_made_before_posting(cfg, monkeypatch):
    today, out = _published_day(cfg, good_social(), infographic=False)
    made = []

    def fake_generate(c, post, path):
        made.append(path)
        Image.new("RGB", (600, 900), "white").save(path)

    monkeypatch.setattr(social.infographic, "generate", fake_generate)
    meta = FakeMeta()
    monkeypatch.setattr(social, "_request", meta)
    monkeypatch.setattr(social, "_sleep", lambda s: None)
    assert social.publish(cfg, today) == 0
    assert made == [out / "infographic.png"]
    assert any(c[1].endswith("/I1/media") for c in meta.calls)


def test_without_infographic_threads_is_text_and_instagram_fails(cfg, monkeypatch):
    today, out = _published_day(cfg, good_social(), infographic=False)
    cfg.infographic = False
    meta = FakeMeta()
    monkeypatch.setattr(social, "_request", meta)
    assert social.publish(cfg, today) == 1
    th = [c for c in meta.calls if c[1].endswith("/T1/threads")][0][2]
    assert th["media_type"] == "TEXT"
    state = json.loads((out / "social_state.json").read_text(encoding="utf-8"))
    assert "threads" in state and "instagram" not in state


def test_edited_draft_that_breaks_rules_is_not_posted(cfg, monkeypatch):
    bad = good_social()
    bad["threads"]["text"] = "주소를 지워버렸어요"
    today, _ = _published_day(cfg, bad)
    meta = FakeMeta()
    monkeypatch.setattr(social, "_request", meta)
    assert social.publish(cfg, today) == 1
    assert not any("/threads" in c[1] or "/media" in c[1] for c in meta.calls)


def test_no_blog_today_means_no_social(cfg, monkeypatch):
    monkeypatch.setattr(social, "_request", lambda *a, **k: pytest.fail("API를 부르면 안 됩니다"))
    assert social.publish(cfg, pipeline.today_kst()) == 0


def test_draft_retries_with_feedback(cfg, monkeypatch):
    today, out = _published_day(cfg)
    prompts = []

    def fake_claude(c, prompt, log_file):
        prompts.append(prompt)
        data = good_social()
        if len(prompts) == 1:
            data["threads"]["text"] = "블로그에 없는 99% 이야기"
        (out / "social.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(social.generate, "_run_claude", fake_claude)
    result = social.draft(cfg, out, URL)
    assert len(prompts) == 2 and "99" in prompts[1] and "/social-auto-post" in prompts[0]
    assert result["blog_url"] == URL
    assert URL in (out / "social_preview.md").read_text(encoding="utf-8")


def test_morning_draft_failure_does_not_break_blog_run(cfg, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("claude down")
    monkeypatch.setattr(social, "draft", boom)
    note = pipeline._social_drafts(cfg, cfg.output_dir, URL)
    assert "소셜 초안을 만들지 못했습니다" in note
    cfg.social_draft = False
    assert pipeline._social_drafts(cfg, cfg.output_dir, URL) == ""


def test_social_accounts_are_per_profile(monkeypatch):
    monkeypatch.setenv("THREADS_ACCESS_TOKEN_EDU", "edu-token")
    monkeypatch.delenv("THREADS_ACCESS_TOKEN_CHILDHOOD", raising=False)
    assert Config.load("edu").threads_token == "edu-token"
    assert Config.load("childhood").threads_token == ""        # 다른 계정 토큰으로 새지 않는다


@pytest.mark.parametrize("tag", ["#현직교 사", "#현직교\u3000사", "#현직교\u200b사", "현직교사", "##현직교사"])
def test_hashtag_with_any_space_or_missing_hash_is_rejected(tag):
    s = good_social()
    s["instagram"]["hashtags"] = ["#교육정책", tag]
    assert any("해시태그 형식" in e for e in social.validate(s, make_post(), URL))


def test_unrecorded_post_is_found_by_title_and_history_is_fixed(cfg, monkeypatch):
    """발행 주소 확인 실패로 날짜 기록이 빠지고, 목록 동기화로만(날짜 없이) 들어온 글도 찾는다."""
    today = pipeline.today_kst()
    out = cfg.output_dir / today
    out.mkdir(parents=True)
    post = make_post(title="유아 레벨테스트 금지 총정리 | 10월부터")
    (out / "post.json").write_text(json.dumps(post, ensure_ascii=False), encoding="utf-8")
    history.append(cfg.history_file, {"date": "", "title": "유아 레벨테스트 금지 총정리  |  10월부터",
                                      "url": URL, "source": "blog-list", "category_no": "3"})
    found_post, url = social.blog_post(cfg, today)
    assert url == URL and found_post["title"] == post["title"]
    entries = history.load(cfg.history_file)
    assert len(entries) == 1                                     # 새로 쌓지 않고 합친다
    e = entries[0]
    assert e["date"] == today and e["source"] == "autopost" and e["category_no"] == "3"
    assert e["lane"] == post["lane"] and history.published_on(cfg.history_file, today)


def test_no_post_folder_means_no_blog(cfg):
    assert social.blog_post(cfg, "2020-01-01") == ({}, "")


def test_record_merges_with_synced_entry(tmp_path):
    path = tmp_path / "h.json"
    history.append(path, {"date": "", "title": "t", "url": URL + "/", "source": "rss", "pub_date": "x"})
    history.upsert(path, history.autopost_entry("2026-09-28", {"title": "t", "lane": "D"}, URL + "?from=rss"))
    [e] = history.load(path)
    assert e["date"] == "2026-09-28" and e["source"] == "autopost" and e["pub_date"] == "x" and e["lane"] == "D"


def test_rejected_image_host_falls_back_to_next(cfg, monkeypatch):
    today, out = _published_day(cfg, good_social())
    meta = FakeMeta(reject={"https://i.ibb.co/x/social_image.jpg"})
    monkeypatch.setattr(social, "_request", meta)
    monkeypatch.setattr(social, "_sleep", lambda s: None)
    assert social.publish(cfg, today) == 0
    ig = [c[2]["image_url"] for c in meta.calls if c[1].endswith("/I1/media")]
    assert ig == ["https://i.ibb.co/x/social_image.jpg", "https://litter.catbox.moe/abc.jpg"]
    state = json.loads((out / "social_state.json").read_text(encoding="utf-8"))
    assert state["instagram"]["url"].startswith("https://www.instagram.com")


def test_threads_goes_text_only_when_every_image_is_rejected(cfg, monkeypatch):
    today, out = _published_day(cfg, good_social())
    meta = FakeMeta(reject={"https://i.ibb.co/x/social_image.jpg", "https://litter.catbox.moe/abc.jpg"})
    monkeypatch.setattr(social, "_request", meta)
    monkeypatch.setattr(social, "_sleep", lambda s: None)
    assert social.publish(cfg, today) == 1                       # 인스타는 실패로 남는다
    kinds = [c[2]["media_type"] for c in meta.calls if c[1].endswith("/T1/threads")]
    assert kinds == ["IMAGE", "IMAGE", "TEXT"]
    state = json.loads((out / "social_state.json").read_text(encoding="utf-8"))
    assert "threads" in state and "instagram" not in state


def test_host_that_serves_a_web_page_is_skipped(cfg, monkeypatch, tmp_path):
    monkeypatch.setattr(social, "_is_image_url", lambda url: "catbox" in url)
    jpg = tmp_path / "a.jpg"
    Image.new("RGB", (10, 10)).save(jpg)
    assert social.host_images(cfg, jpg) == ["https://litter.catbox.moe/abc.jpg"]


def test_unreachable_from_this_pc_is_kept_but_tried_last(cfg, monkeypatch, tmp_path):
    monkeypatch.setattr(social, "_is_image_url", lambda url: None if "ibb" in url else True)
    jpg = tmp_path / "a.jpg"
    Image.new("RGB", (10, 10)).save(jpg)
    assert social.host_images(cfg, jpg) == ["https://litter.catbox.moe/abc.jpg", "https://i.ibb.co/x/social_image.jpg"]


def test_tmpfiles_link_is_turned_into_direct_download(monkeypatch, cfg, tmp_path):
    jpg = tmp_path / "a.jpg"
    Image.new("RGB", (10, 10)).save(jpg)
    monkeypatch.setattr(social, "_upload_form", lambda *a, **k: '{"status":"success","data":{"url":"http://tmpfiles.org/123/a.jpg"}}')
    assert social._host_tmpfiles(cfg, jpg) == "https://tmpfiles.org/dl/123/a.jpg"


def test_litterbox_upload_request_shape(monkeypatch, tmp_path, cfg):
    jpg = tmp_path / "social_image.jpg"
    Image.new("RGB", (10, 10)).save(jpg, "JPEG")
    seen = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"https://litter.catbox.moe/abc123.jpg\n"

    def fake_urlopen(req, timeout=0):
        seen["url"], seen["body"], seen["ctype"] = req.full_url, req.data, req.headers["Content-type"]
        return Resp()

    monkeypatch.setattr(social.urllib.request, "urlopen", fake_urlopen)
    assert social._host_litterbox(cfg, jpg) == "https://litter.catbox.moe/abc123.jpg"
    boundary = seen["ctype"].split("boundary=")[1]
    assert seen["url"].startswith("https://litterbox.catbox.moe/")
    assert b'name="reqtype"\r\n\r\nfileupload' in seen["body"] and b'name="time"\r\n\r\n24h' in seen["body"]
    assert b'name="fileToUpload"; filename="social_image.jpg"' in seen["body"] and jpg.read_bytes() in seen["body"]
    assert seen["body"].endswith(f"--{boundary}--\r\n".encode())


def test_imgbb_uses_direct_image_url(monkeypatch, cfg, tmp_path):
    jpg = tmp_path / "a.jpg"
    Image.new("RGB", (10, 10)).save(jpg)
    monkeypatch.setattr(social, "_request", lambda *a, **k: {"data": {
        "url": "https://i.ibb.co/x/a.jpg", "url_viewer": "https://ibb.co/x",
        "image": {"url": "https://i.ibb.co/x/a.jpg"}}})
    assert social._host_imgbb(cfg, jpg) == "https://i.ibb.co/x/a.jpg"
