"""매일 시황(--profile market): 투자 블로그에 함께 올리는 시황 글 — 설정·제목 형식·글감 연결."""
import json

from naver_autopost import content, generate, openai_client, profiles
from naver_autopost.config import Config
from tests.sample_post import make_post

MARKET = profiles.get("market")


def market_post(**over):
    post = make_post(lane="G", thumbnail={"chip": "매일 시황", "main_lines": ["11월 3일", "200일선 21%"], "sub": "한 주 새 −3%p"})
    post["title"] = "11월 3일 시황 | 200일선 위 종목 21%로 줄었어요"
    post["sources"] = post["sources"][:4]
    post["body_html"] += "<h2>계속 지켜볼 것</h2><p>" + "다음 주 금통위 전까지 200일선 위 비율이 어디로 가는지 볼게요. " * 8 + "</p>"
    post.update(over)
    return post


def test_market_post_is_valid():
    assert content.validate(market_post(), MARKET) == []


def test_market_title_must_start_with_date_and_sihwang():
    errors = content.validate(market_post(title="오늘 시황 | 코스피 정리"), MARKET)
    assert any("제목 형식" in e for e in errors)


def test_market_blocks_advice():
    post = market_post()
    post["body_html"] += "<p>이 종목 지금 사야 해요</p>"
    assert any("금지 표현" in e for e in content.validate(post, MARKET))


def test_market_uses_invest_blog_and_login(monkeypatch):
    for k in ("NAVER_BLOG_ID_MARKET", "BROWSER_PROFILE_DIR_MARKET", "BROWSER_PROFILE_DIR_INVEST",
              "NAVER_CATEGORY_MARKET", "RETRY_TIME_MARKET", "SOCIAL_DRAFT"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("NAVER_BLOG_ID_INVEST", "moneyblog")
    c = Config.load("market")
    assert c.blog_id == "moneyblog"
    assert c.profile_dir.name == ".browser-profile-invest"      # 같은 네이버 로그인을 쓴다
    assert c.category == "매일 시황"
    assert c.history_file.name == "published_market.json"
    assert c.retry_time == "19:30" and c.social_draft is False
    monkeypatch.setenv("NAVER_BLOG_ID_MARKET", "other")
    assert Config.load("market").blog_id == "other"


def test_market_gpt_check_does_not_hunt_dashboard_numbers():
    text = openai_client._instructions(Config.load("market"))
    assert "brief.json" in text and "인과" in text


def test_market_write_prompt_passes_brief(tmp_path, monkeypatch):
    c = Config.load("market")
    out = tmp_path / "out"
    seen = {}

    def fake_for_post(today, path, site_url=None):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"date": today}), encoding="utf-8")
        return path

    def fake_run(cfg, prompt, log_file, **kw):
        seen["prompt"] = prompt
        (out / "post.json").write_text("{}", encoding="utf-8")

    from market_dashboard import brief
    monkeypatch.setattr(brief, "for_post", fake_for_post)
    monkeypatch.setattr(generate, "_run_claude", fake_run)
    generate.write_post(c, out, "2026-11-03")
    assert "/market-auto-post" in seen["prompt"]
    assert "MARKET_BRIEF=" in seen["prompt"] and "market_brief.json" in seen["prompt"]
    assert "DASHBOARD_URL=https://" in seen["prompt"]
    assert (out / "market_brief.json").exists()


def test_other_profiles_get_no_brief(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(generate, "_run_claude", lambda cfg, prompt, log_file, **kw: (
        seen.update(p=prompt), (tmp_path / "post.json").write_text("{}", encoding="utf-8")))
    generate.write_post(Config.load("invest"), tmp_path, "2026-11-03")
    assert "MARKET_BRIEF" not in seen["p"]
