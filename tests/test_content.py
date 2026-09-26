from naver_autopost import content
from tests.sample_post import make_post


def test_valid_post_passes():
    post = content.normalize(make_post())
    assert content.validate(post) == []


def test_normalize_tags_and_links():
    post = content.normalize(make_post())
    assert post["tags"] == ["교육정책", "늘봄학교", "교육부"]
    assert "<a " not in post["body_html"]
    assert "https://blog.naver.com/x/1" in post["body_html"]


def test_sanitize_strips_styles():
    out = content.sanitize_html('<style>p{}</style><p style="color:red" class="x">안녕</p>')
    assert out == "<p>안녕</p>"


def test_placeholder_blocks_publish():
    post = make_post()
    post["body_html"] += "<p>✍️ 여기에 본인 경험</p>"
    errors = content.validate(content.normalize(post))
    assert any("✍️" in e for e in errors)


def test_uncertain_marker_blocks_publish():
    post = make_post()
    post["body_html"] += "<p>시행일은 3월(확인 필요)입니다.</p>"
    assert any("확인 필요" in e for e in content.validate(content.normalize(post)))


def test_card_marker_required_once():
    post = make_post()
    post["body_html"] = post["body_html"].replace("<p>[[IMAGE:card]]</p>", "")
    assert any("IMAGE:card" in e for e in content.validate(content.normalize(post)))


def test_too_few_sources():
    post = make_post(sources=make_post()["sources"][:5])
    assert any("출처가 부족" in e for e in content.validate(content.normalize(post)))


def test_split_segments_order():
    segs = content.split_segments("<p>앞</p><p>[[IMAGE:card]]</p><p>뒤</p>")
    assert segs == [("html", "<p>앞</p>"), ("image", "card"), ("html", "<p>뒤</p>")]


def test_heading_dash_becomes_bar_but_body_keeps_dash():
    post = make_post(title="AIDT 총정리 — 핵심만")
    post["body_html"] = "<h2>2. 언제 바뀌었나 — 타임라인</h2><p>설명 — 그대로</p>" + post["body_html"]
    post = content.normalize(post)
    assert post["title"] == "AIDT 총정리 | 핵심만"
    assert "<h2>2. 언제 바뀌었나 | 타임라인</h2>" in post["body_html"]
    assert "<p>설명 — 그대로</p>" in post["body_html"]
