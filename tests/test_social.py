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
    def __init__(self):
        self.calls = []

    def __call__(self, method, url, params, timeout=60):
        self.calls.append((method, url, dict(params)))
        if "refresh_access_token" in url:
            return {"access_token": params["access_token"]}
        if "imgbb" in url:
            return {"data": {"url": "https://i.ibb.co/x/social_image.jpg"}}
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


def test_without_infographic_threads_is_text_and_instagram_fails(cfg, monkeypatch):
    today, out = _published_day(cfg, good_social(), infographic=False)
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
