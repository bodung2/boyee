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
    assert c.retry_time == "10:00"
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


def test_invest_thumbnail_uses_first_illustration_as_background(tmp_path):
    from naver_autopost import pipeline
    c = Config.load("invest")
    Image.new("RGB", (1536, 864), "#ffffff").save(tmp_path / "illust_a.png")   # 흰 장면
    imgs = pipeline.render_images(c, invest_post(lane="B"), tmp_path)
    thumb = Image.open(imgs["thumbnail"]).convert("RGB")
    solid = images.INVEST_TONES["B"]
    top, bottom = thumb.getpixel((5, 5)), thumb.getpixel((5, thumb.height - 5))
    assert "#%02x%02x%02x" % bottom != solid and sum(bottom) > sum(top)   # 아래쪽은 그림이 비친다


def test_invest_thumbnail_falls_back_to_solid_when_scene_unreadable(tmp_path):
    (tmp_path / "bad.png").write_bytes(b"not an image")
    out = images.make_thumbnail_scene({"chip": "x", "main_lines": ["질문"], "sub": ""}, tmp_path / "bad.png",
                                      tmp_path / "t.png", images.INVEST_TONES["C"])
    px = Image.open(out).convert("RGB").getpixel((5, 590))
    assert "#%02x%02x%02x" % px == images.INVEST_TONES["C"]


def test_invest_title_must_be_short_for_mobile_home_feed():
    long_title = "순자산 3억이면 상위 몇 %일까? 통계로 확인해 봤어요"
    assert any("제목이 너무 깁니다" in e for e in content.validate(invest_post(title=long_title), INVEST))
    assert content.validate(invest_post(title="순자산 3억, 상위 몇 %일까?"), INVEST) == []


def test_invest_neighbor_prompt_does_not_reveal_teacher(tmp_path, monkeypatch):
    from naver_autopost import neighbors
    seen = {}
    monkeypatch.setattr(generate, "_run_claude", lambda c, p, log_file, light=False: seen.setdefault("p", p))
    neighbors.choose(Config.load("invest"), [], 5, tmp_path)
    assert "꾸쓰" not in seen["p"] and "교사" not in seen["p"]
    assert "재테크" in seen["p"] and "리딩방" in seen["p"]


HIST = [
    {"date": "2026-10-13", "title": "4대보험료 얼마나 올랐을까?", "url": "https://blog.naver.com/acridortt/1", "lane": "F"},
    {"date": "2026-10-16", "title": "순자산 10억, 상위 몇 %일까?", "url": "https://blog.naver.com/acridortt/2", "lane": "A"},
    {"date": "2026-10-17", "title": "자가보유율 청년은?", "url": "https://blog.naver.com/acridortt/3", "lane": "B"},
    {"date": "2026-10-15", "title": "정년 몇 살에 그만둘까?", "url": "https://blog.naver.com/acridortt/4", "lane": "D"},
    {"title": "주소 없는 글", "url": "", "lane": "A"},
]


def test_related_links_filled_from_history_same_lane_first():
    body = "<p>본문</p><div data-block=\"oneline\"><p>한 줄</p></div><p>출처: 국가데이터처 — 자료(2025)</p>"
    out, added = content.ensure_related(body, HIST, lane="A", title="연봉 4천, 상위 몇 %일까?")
    assert added
    block = out[out.index('data-block="related"'):out.index("출처:")]
    assert block.index("acridortt/2") < block.index("acridortt/3") < block.index("acridortt/4")   # 같은 레인 → 최근 순
    assert "acridortt/1" not in block and "주소 없는 글" not in block                            # 3개까지
    assert "같은 주제를 다른 숫자로" in block


def test_related_links_kept_when_writer_added_them():
    body = '<p>본문</p><div data-block="related"><p>「x」 — y</p><p>https://blog.naver.com/a/9</p></div>'
    assert content.ensure_related(body, HIST, "A") == (body, False)
    assert content.ensure_related("<p>본문</p>", [], "A") == ("<p>본문</p>", False)


def test_related_links_skip_this_post_itself():
    out, _ = content.ensure_related("<p>x</p>", HIST[:1], "F", title="4대보험료 얼마나 올랐을까?")
    assert out == "<p>x</p>"
