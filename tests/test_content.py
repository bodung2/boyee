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


def test_edu_blog_rejects_early_childhood_topics():
    """유아 주제는 유아 블로그 몫: 교육 블로그 글이면 발행 전에 막고 글쓰기에 이유를 돌려준다."""
    from naver_autopost import profiles
    edu, child = profiles.get("edu"), profiles.get("childhood")
    post = content.normalize(make_post())
    assert not [e for e in content.validate(post, edu) if "블로그 주제" in e]
    baby = {**post, "title": "유치원 입학 신청 총정리 / 2027 처음학교로 일정"}
    assert any("유아 블로그" in e for e in content.validate(baby, edu))
    assert not [e for e in content.validate(baby, child) if "블로그 주제" in e]


def test_edu_daily_skips_lane_b_and_series_requires_strict_sources():
    """교육 매일 글은 A·C·D·E만, 교직 실무(B)는 '저경력 교사 필수' 시리즈로만 — 시리즈는 1차 출처 기준이 더 높다."""
    from naver_autopost import profiles
    edu, series = profiles.get("edu"), profiles.get("edu_series")
    post = content.normalize(make_post())
    b_daily = {**post, "lane": "B"}
    assert any("시리즈" in e for e in content.validate(b_daily, edu))
    assert not [e for e in content.validate({**post, "lane": "D"}, edu) if "갈래" in e]
    s = {**post, "lane": "B", "title": "[저경력 교사 필수 시리즈 ⑨] 비정기 전보 내신, 언제 쓰나?",
         "thumbnail": {"chip": "저경력 교사 필수 ⑨", "main_lines": ["전보 내신,", "언제 쓸까?"], "sub": "기한이 있어요"}}
    errors = content.validate(s, series)
    assert not [e for e in errors if "제목 형식" in e or "갈래" in e]
    primary = sum(1 for x in s["sources"] if x.get("primary"))
    assert (primary < 4) == any("1차 출처가 4개" in e for e in errors)
    assert any("제목 형식" in e for e in content.validate({**s, "title": "비정기 전보 총정리"}, series))


def test_edu_series_shares_the_edu_blog_and_posts_to_tips_category(monkeypatch):
    from naver_autopost import config
    for k in ("NAVER_CATEGORY_EDU_SERIES", "NAVER_CATEGORY_EDU", "NAVER_CATEGORY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("NAVER_BLOG_ID_EDU", "edublog")
    s, e = config.Config.load("edu_series"), config.Config.load("edu")
    assert s.blog_id == "edublog" and s.profile_dir == e.profile_dir
    assert s.history_file.name == "published_edu_series.json" and s.category_for("B") == "교직 꿀팁"


def test_edu_series_title_and_scene_thumbnail():
    from naver_autopost import profiles
    from tests.sample_post import make_post
    prof = profiles.get("edu_series")
    assert prof.thumbnail_style == "edu_scene"
    post = make_post(title="[저경력 교사 필수 시리즈 ②] 신규 교사 첫 월급, 실수령 얼마일까?", lane="B",
                     thumbnail={"chip": "저경력 교사 필수 ②", "main_lines": ["신규 교사", "첫 월급,", "얼마일까?"],
                                "sub": "공제만 7가지예요"})
    errs = content.validate(post, prof)
    assert not any("제목 형식" in e or "썸네일" in e for e in errs), errs
    old = make_post(title="[저경력 교사 필수 시리즈 2] 첫 월급 명세서 읽는 법", lane="B")     # 아라비아 숫자는 안 됨
    assert any("제목 형식" in e for e in content.validate(old, prof))
