"""교육 블로그 썸네일: 주제 레인(A~E)마다 배경색이 다르다."""
from naver_autopost import images


def test_each_lane_has_its_own_color():
    tones = [images.edu_tone(l) for l in "ABCDE"]
    assert len(set(tones)) == 5
    assert images.edu_tone("C") == images.BG                       # 전국 교육부 정책은 기존 남색 그대로
    assert images.edu_tone("(b)") == images.edu_tone("B 레인") == images.EDU_TONES["B"]
    assert images.edu_tone(None) == images.edu_tone("") == images.edu_tone("Z") == images.BG


def test_pipeline_passes_lane_color(tmp_path, monkeypatch):
    from naver_autopost import pipeline
    from naver_autopost.config import Config
    seen = {}
    monkeypatch.setattr(images, "make_thumbnail", lambda t, out, tone=images.BG: seen.setdefault("thumb", tone) and out)
    monkeypatch.setattr(images, "make_card", lambda c, out, tone=images.BG: seen.setdefault("card", tone) and out)
    cfg = Config.load("edu")
    pipeline.render_images(cfg, {"lane": "D", "body_html": "<p>x</p>", "thumbnail": {"main": "x"}, "card": {"title": "t", "bullets": []}}, tmp_path)
    assert seen == {"thumb": images.EDU_TONES["D"], "card": images.EDU_TONES["D"]}
