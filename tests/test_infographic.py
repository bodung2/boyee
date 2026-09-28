"""한 줄 요약 앞 핵심 인포그래픽(Codex onepage 스킬)."""
import pytest
from PIL import Image

from naver_autopost import content, images, infographic, pipeline, profiles
from naver_autopost.config import Config
from tests.sample_post import make_post

ONELINE = '<div data-block="oneline"><p>핵심 결론입니다.</p></div>'
RELATED = '<div data-block="related"><p>https://blog.naver.com/x/1</p></div>'


@pytest.fixture
def cfg(tmp_path):
    c = Config.load("edu")
    c.output_dir = tmp_path / "out"
    return c


def _fake_codex(tmp_path, make_image=True):
    """가짜 codex: 프롬프트를 저장하고, 작업 폴더에 세로형 infographic.png를 만든다."""
    script = tmp_path / "codex_info"
    script.write_text(f"""#!{__import__('sys').executable}
import sys, pathlib
(pathlib.Path({str(tmp_path)!r}) / "prompt.txt").write_text(sys.stdin.read(), encoding="utf-8")
if {make_image!r}:
    from PIL import Image
    Image.new("RGB", (2048, 3072), "#ffffff").save("infographic.png")
""", encoding="utf-8")
    script.chmod(0o755)
    return script


def test_marker_goes_right_before_oneline():
    body = "<p>본문</p>" + ONELINE + RELATED
    out = infographic.insert_marker(body)
    assert out == "<p>본문</p>" + infographic.MARKER + ONELINE + RELATED
    assert infographic.insert_marker(out) == out            # 두 번 넣지 않는다


def test_marker_fallbacks():
    assert infographic.insert_marker("<p>a</p>" + RELATED) == "<p>a</p>" + infographic.MARKER + RELATED
    assert infographic.insert_marker("<p>a</p>") == "<p>a</p>" + infographic.MARKER
    legacy = "<p>a</p><p>한 줄 요약: 결론</p>"
    assert infographic.insert_marker(legacy) == "<p>a</p>" + infographic.MARKER + "<p>한 줄 요약: 결론</p>"


def test_validate_accepts_infographic_marker():
    post = make_post()
    post["body_html"] = infographic.insert_marker(post["body_html"] + ONELINE)
    assert content.validate(content.normalize(post), profiles.get("edu")) == []


def test_add_infographic_uses_skill_and_keeps_aspect(cfg, tmp_path):
    cfg.codex_bin = str(_fake_codex(tmp_path))
    out_dir = tmp_path / "day"
    out_dir.mkdir()
    post = content.normalize(make_post())
    post["body_html"] += ONELINE
    post["image_names"] = {"thumbnail": "늘봄_썸네일_2026", "card": "늘봄_요약카드_2026"}
    assert pipeline.add_infographic(cfg, post, out_dir) is True

    prompt = (tmp_path / "prompt.txt").read_text(encoding="utf-8")
    assert "$onepage" in prompt and post["title"] in prompt and "첫째 요점" in prompt
    assert "핵심 결론입니다." in prompt
    assert Image.open(out_dir / "infographic.png").size == (1600, 2400)   # 세로형 그대로, 폭만 줄임
    assert "[[IMAGE:infographic]]" in (out_dir / "post.json").read_text(encoding="utf-8")

    imgs = pipeline.render_images(cfg, post, out_dir)
    assert imgs["infographic"].name == "늘봄_인포그래픽_2026.png"
    assert imgs["thumbnail"].name == "늘봄_썸네일_2026.png"
    names = [v for k, v in content.split_segments(post["body_html"]) if k == "image"]
    assert names[-1] == "infographic"


def test_add_infographic_failure_publishes_without_it(cfg, tmp_path):
    cfg.codex_bin = str(_fake_codex(tmp_path, make_image=False))
    out_dir = tmp_path / "day"
    out_dir.mkdir()
    post = content.normalize(make_post())
    post["body_html"] += ONELINE
    assert pipeline.add_infographic(cfg, post, out_dir) is False
    assert "[[IMAGE:infographic]]" not in post["body_html"]


def test_add_infographic_can_be_turned_off(cfg, tmp_path):
    cfg.infographic = False
    cfg.codex_bin = "/nonexistent/codex"
    post = content.normalize(make_post())
    assert pipeline.add_infographic(cfg, post, tmp_path) is True
    assert "[[IMAGE:infographic]]" not in post["body_html"]


def test_both_thumbnails_are_600(tmp_path):
    post = make_post()
    edu = images.make_thumbnail(post["thumbnail"], tmp_path / "e.png")
    child = images.make_thumbnail_childhood(
        {"chip": "연령별 발달 · 4세", "main_lines": ["4세 숫자,", "어디까지"], "sub": "단계가 먼저"}, "N", tmp_path / "c.png")
    assert Image.open(edu).size == (600, 600)
    assert Image.open(child).size == (600, 600)
