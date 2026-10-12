"""투자 블로그(--profile invest): 숫자깡패 돈 편 — 썸네일·검증 규칙·신원 보호."""
import pytest
from PIL import Image

from naver_autopost import content, generate, images, openai_client, profiles
from naver_autopost.config import Config
from tests.sample_post import make_post

INVEST = profiles.get("invest")


def invest_post(**over):
    post = make_post(
        lane="A",
        thumbnail={"chip": "내 위치", "main_lines": ["순자산 3억", "상위 몇 %?"], "sub": "가계금융복지조사"},
        illustrations=[{"name": "illust_a", "prompt": "commuter on a subway ...", "desc_ko": "도입", "alt": "지하철"}],
    )
    post["body_html"] = "<p>[[IMAGE:illust_a]]</p>" + post["body_html"]
    post["sources"] = post["sources"][:6]
    post.update(over)
    return post


def test_invest_post_with_six_sources_is_valid():
    assert content.validate(invest_post(), INVEST) == []


def test_invest_needs_question_thumbnail_lines():
    errors = content.validate(invest_post(thumbnail={"chip": "내 위치", "main": "순자산"}), INVEST)
    assert any("썸네일 메인은 1~3줄" in e for e in errors)


@pytest.mark.parametrize("phrase", ["이 종목 매수 추천합니다", "수익 보장되는 방법", "현직 교사로서 말하면",
                                    "서울 집값 무조건 오른다"])
def test_invest_blocks_advice_and_identity(phrase):
    post = invest_post()
    post["body_html"] += f"<p>{phrase}</p>"
    assert any("금지 표현" in e for e in content.validate(post, INVEST))


def test_invest_allows_teacher_as_statistics_topic():
    post = invest_post()
    post["body_html"] += "<p>공무원·교사 연금 수령액 통계도 같이 보자.</p>"
    assert content.validate(post, INVEST) == []


def test_invest_config_hides_persona_and_skips_social(monkeypatch):
    for k in ("SOCIAL_DRAFT", "RETRY_TIME_INVEST", "NAVER_BLOG_ID_INVEST"):
        monkeypatch.delenv(k, raising=False)
    c = Config.load("invest")
    assert c.social_draft is False
    assert c.retry_time == "17:00"
    assert c.profile_dir.name == ".browser-profile-invest"
    assert c.history_file.name == "published_invest.json"
    assert generate._persona_lines(c) == "PERSONA_FILE=(없음)\n"


def test_invest_factcheck_prompt_mentions_advice():
    c = Config.load("invest")
    text = openai_client._instructions(c)
    assert "매수/매도 권유" in text and "명목/실질" in text


def test_invest_thumbnail_uses_lane_tone(tmp_path):
    out = images.make_thumbnail_childhood({"chip": "내 위치", "main_lines": ["순자산 3억", "상위 몇 %?"], "sub": "x"},
                                          None, tmp_path / "t.png", tone=images.invest_tone("D"))
    px = Image.open(out).convert("RGB").getpixel((5, 5))
    assert "#%02x%02x%02x" % px == images.INVEST_TONES["D"]
    assert images.invest_tone("?") == images.INVEST_TONES["A"]
    assert set(images.INVEST_TONES) == set("ABCDEFG")      # 스킬의 레인 7개마다 색이 있다


def test_invest_render_images_uses_bold_thumbnail(tmp_path, monkeypatch):
    from naver_autopost import pipeline
    c = Config.load("invest")
    post = invest_post(lane="B")
    imgs = pipeline.render_images(c, post, tmp_path)
    px = Image.open(imgs["thumbnail"]).convert("RGB").getpixel((5, 5))
    assert "#%02x%02x%02x" % px == images.INVEST_TONES["B"]
    assert imgs["card"].exists()
