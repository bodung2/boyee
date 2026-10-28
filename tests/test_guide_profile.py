"""생활 절차 블로그(--profile guide): 실제 이미지(공식 화면 캡처·커먼즈 사진), 요약 카드 없음, AI 상투어 차단."""
import json

import pytest
from PIL import Image

from naver_autopost import captures, content, generate, images, openai_client, pipeline, profiles, realphotos, se_markup
from naver_autopost.config import Config
from tests.sample_post import make_post

GUIDE = profiles.get("guide")


def guide_post(**over):
    body = (
        "<p>정보처리기사 실기 원서는 10월 20일 오전 10시부터 받아요. 큐넷에서만 접수돼요.</p>"
        "<p>[[IMAGE:cap_a]]</p>"
        "<h2>접수는 언제부터 받나요</h2><p>" + "접수 기간과 시각을 공고문 기준으로 적었어요. " * 60 + "</p>"
        "<table border=\"1\"><tr><th>구분</th><th>기간</th></tr><tr><td>원서접수</td><td>10.20~10.23</td></tr></table>"
        "<h2>준비물은 이것만 챙기면 돼요</h2><p>" + "신분증과 수험표, 필기구를 챙겨요. " * 60 + "</p>"
        "<p>[[IMAGE:photo_a]]</p>"
        "<p>접수 확인은 마이페이지에서 할 수 있어요.</p>"
    )
    post = make_post(
        lane="A", format="steps", title="정보처리기사 실기 접수, 10월 20일부터예요",
        thumbnail={"chip": "시험·자격증", "main_lines": ["정보처리기사", "실기 접수일"], "sub": "2026년 4회 기준"},
        captures=[{"name": "cap_a", "url": "https://www.q-net.or.kr/notice", "focus": "시험일정", "highlight": ["원서접수"],
                   "caption": "큐넷 시험일정 공고", "desc_ko": "일정표"}],
        photos=[{"name": "photo_a", "search": "Korea test center", "subject": "시험장 건물", "caption": "시험장"}],
        body_html=body,
    )
    post.pop("card")
    post["sources"] = post["sources"][:6]
    post.update(over)
    return post


# ---------------------------------------------------------------- 구조 검사

def test_guide_post_without_card_is_valid():
    assert content.validate(content.normalize(guide_post()), GUIDE) == []


def test_guide_rejects_card_marker():
    post = guide_post()
    post["body_html"] += "<p>[[IMAGE:card]]</p>"
    assert any("요약 카드를 쓰지 않습니다" in e for e in content.validate(content.normalize(post), GUIDE))


@pytest.mark.parametrize("phrase", ["오늘은 전입신고에 대해 알아보겠습니다", "이번 포스팅에서는 정리해요",
                                    "시험 일정 총정리", "결론적으로 접수가 중요해요", "도움이 되셨길 바라요",
                                    "이렇게 하면 무조건 승소합니다", "현직 교사로서 말하면"])
def test_guide_blocks_ai_cliches_and_certainty(phrase):
    post = guide_post()
    post["body_html"] += f"<p>{phrase}</p>"
    assert any("금지 표현" in e for e in content.validate(content.normalize(post), GUIDE))


def test_guide_unknown_real_image_marker_blocks():
    post = guide_post()
    post["body_html"] += "<p>[[IMAGE:cap_z]]</p>"
    assert any("알 수 없는" in e for e in content.validate(content.normalize(post), GUIDE))


def test_fix_card_marker_is_skipped_for_guide(tmp_path):
    path = tmp_path / "post.json"
    path.write_text(json.dumps(guide_post(), ensure_ascii=False), encoding="utf-8")
    assert "[[IMAGE:card]]" not in pipeline._load_fixed(path, GUIDE)["body_html"]
    assert "[[IMAGE:card]]" in pipeline._load_fixed(path, profiles.get("edu"))["body_html"]


# ---------------------------------------------------------------- 설정

def test_guide_config(monkeypatch):
    for k in ("NAVER_BLOG_ID_GUIDE", "RETRY_TIME_GUIDE", "NAVER_CATEGORY_GUIDE", "NAVER_CATEGORY_GUIDE_A"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("NAVER_BLOG_ID", "kkus_i")
    c = Config.load("guide")
    assert c.blog_id == ""                       # 유아 블로그 아이디로 대신 채우지 않는다(잘못 발행 방지)
    assert c.profile_dir.name == ".browser-profile-guide"
    assert c.history_file.name == "published_guide.json"
    assert c.retry_time == "18:30"
    assert c.social_draft is False
    assert generate._persona_lines(c) == "PERSONA_FILE=(없음)\n"
    assert (c.category_for("A"), c.category_for("B"), c.category_for("C")) == ("시험·자격증", "생활 민원", "생활 법률")
    assert Config.load("childhood").blog_id == "kkus_i"
    monkeypatch.setenv("NAVER_BLOG_ID_GUIDE", "guideblog")
    assert Config.load("guide").blog_id == "guideblog"


def test_run_skips_quietly_without_blog_id(tmp_path, monkeypatch):
    monkeypatch.delenv("NAVER_BLOG_ID_GUIDE", raising=False)
    c = Config.load("guide")
    c.log_dir = tmp_path
    sent = []
    monkeypatch.setattr(pipeline.notify, "send", lambda cfg, msg: sent.append(msg))
    assert pipeline.run(c) == 0 and sent == []


def test_guide_gpt_instructions_mention_schedule_and_captions():
    text = openai_client._instructions(Config.load("guide"))
    assert "시험 일정" in text and "▲" in text


def test_write_prompt_has_image_limits(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(generate, "_run_claude", lambda cfg, prompt, log_file, **kw: seen.setdefault("p", prompt))
    c = Config.load("guide")
    c.data_dir = tmp_path
    c.history_file = tmp_path / "published_guide.json"
    with pytest.raises(generate.NoPostError):
        generate.write_post(c, tmp_path / "out", "2026-10-28")
    assert "CAPTURES_MAX=3" in seen["p"] and "PHOTOS_MAX=2" in seen["p"] and "ILLUSTRATIONS=0" in seen["p"]


# ---------------------------------------------------------------- 캡션·서식

def test_caption_follows_marker_and_goes_with_it():
    body = "<p>[[IMAGE:cap_a]]</p><p>본문</p>"
    body = content.add_caption(body, "cap_a", "큐넷 공고 (2026.10.28 캡처)")
    assert body.startswith('<p>[[IMAGE:cap_a]]</p><p data-block="caption" data-for="cap_a">▲ 큐넷 공고')
    assert content.add_caption(body, "cap_a", "다른 설명").count("data-block=\"caption\"") == 1
    assert content.remove_markers(body, {"cap_a"}) == "<p>본문</p>"
    assert content.sanitize_html(body) == body          # 정리 단계가 캡션 표시를 지우지 않는다


def test_plain_headings_caption_and_no_summary_box():
    body = ("<ul><li>하나</li><li>둘</li></ul><p>[[IMAGE:cap_a]]</p>"
            '<p data-block="caption" data-for="cap_a">▲ 큐넷 공고</p><h2>접수는 언제부터</h2><p>본문</p>')
    segs = se_markup.to_segments(body, summary_box=False, heading="plain")
    comps = [c for kind, v in segs if kind == "se" for c in v]
    assert not any(c.get("ctype") in ("table", "quotation") for c in comps)
    paras = [p for c in comps if c.get("ctype") == "text" for p in c["value"]]
    caption = next(p for p in paras if p["nodes"][0]["value"] == "▲ 큐넷 공고")
    assert caption["style"]["align"] == "center" and caption["nodes"][0]["style"]["fontSizeCode"] == "fs13"
    heading = next(p for p in paras if p["nodes"][0]["value"] == "접수는 언제부터")
    assert heading["nodes"][0]["style"]["bold"] and heading["nodes"][0]["style"]["fontSizeCode"] == "fs19"
    # 기본(다른 블로그)은 그대로: 요약 상자 + 인용구 챕터
    default = [c for kind, v in se_markup.to_segments(body) if kind == "se" for c in v]
    assert any(c.get("ctype") == "table" for c in default) and any(c.get("ctype") == "quotation" for c in default)


def test_ensure_related_uses_profile_notes():
    entries = [{"title": "여권 재발급 준비물", "url": "https://blog.naver.com/g/2", "lane": "B", "date": "2026-10-01"}]
    body, added = content.ensure_related("<p>x</p>", entries, "B", "새 글", notes=GUIDE.related_notes)
    assert added and GUIDE.related_notes[0] in body


# ---------------------------------------------------------------- 공식 화면 캡처

@pytest.mark.parametrize("url,ok", [
    ("https://www.q-net.or.kr/crf005.do?id=crf00505", True),
    ("https://www.gov.kr/portal/main", True),
    ("https://www.easylaw.go.kr/CSP/Main.laf", True),
    ("https://www.kice.re.kr/", True),
    ("https://blog.naver.com/someone/1", False),
    ("https://q-net.or.kr.evil.com/", False),
    ("ftp://www.gov.kr/", False),
])
def test_is_official(url, ok):
    assert captures.is_official(url) is ok


def test_extra_capture_hosts(monkeypatch):
    monkeypatch.setenv("CAPTURE_EXTRA_HOSTS", "example.or.kr")
    assert captures.is_official("https://www.example.or.kr/a")


PAGE = """<html><head><title>시험일정 안내</title></head><body style="margin:0;font-family:sans-serif">
<div style="height:900px;background:#f4f6f8">머리</div>
<h3 style="margin:20px">2026년 국가기술자격 시험일정</h3>
<table border="1" style="margin:20px;width:700px"><tr><th>회차</th><th>원서접수</th></tr>
<tr><td>4회</td><td>10.20 ~ 10.23</td></tr></table>
<button style="margin:20px;width:140px;height:44px">원서접수</button>
<div style="height:1200px"></div>
<div style="position:fixed;left:200px;top:100px;width:700px;height:500px;z-index:999;background:#fff;border:2px solid #000">
레이어 팝업 오늘 하루 보지 않기</div>
</body></html>"""


def _browser(p):
    return p.chromium.launch()


def test_capture_crops_focus_hides_popup_and_draws_box(tmp_path, monkeypatch):
    page_file = tmp_path / "notice.html"
    page_file.write_text(PAGE, encoding="utf-8")
    monkeypatch.setattr(captures, "is_official", lambda url: True)
    post = {"captures": [{"name": "cap_a", "url": page_file.as_uri(), "focus": "2026년 국가기술자격 시험일정",
                          "highlight": ["원서접수"], "caption": "큐넷 시험일정"}]}
    cfg = type("C", (), {"capture_count": 3, "browser_channel": ""})()
    ok, notes = captures.capture_all(cfg, post, tmp_path, "2026-10-28", open_browser=_browser)
    assert ok == {"cap_a"} and notes == []
    img = Image.open(tmp_path / "cap_a.png").convert("RGB")
    assert img.width >= captures.MIN_W * captures.SCALE - 2
    px = img.load()
    reds = sum(1 for x in range(0, img.width, 2) for y in range(0, img.height, 2) if px[x, y] == captures.BOX_COLOR)
    assert reds > 50                                       # 빨간 네모가 그려졌다
    spec = post["captures"][0]
    assert spec["captured"]["focused"] and spec["captured"]["boxes"] == 1 and spec["captured"]["date"] == "2026-10-28"
    assert captures.caption_text(spec) == "큐넷 시험일정 (2026.10.28 캡처)"


def test_hide_overlays_hides_layer_popup_only(tmp_path):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport=captures.VIEWPORT)
        page.set_content(PAGE)
        assert page.evaluate(captures._HIDE_OVERLAYS) == 1
        assert page.get_by_text("레이어 팝업").is_visible() is False
        assert page.get_by_text("2026년 국가기술자격 시험일정").is_visible()
        b.close()


def test_capture_rejects_error_and_non_official(tmp_path, monkeypatch):
    err = tmp_path / "err.html"
    err.write_text("<html><head><title>404 Not Found</title></head><body>요청하신 페이지를 찾을 수 없습니다</body></html>",
                   encoding="utf-8")
    monkeypatch.setattr(captures, "is_official", lambda url: url.startswith("file:"))
    post = {"captures": [{"name": "cap_a", "url": err.as_uri(), "focus": "x"},
                         {"name": "cap_b", "url": "https://blog.naver.com/x/1"}]}
    cfg = type("C", (), {"capture_count": 3, "browser_channel": ""})()
    ok, notes = captures.capture_all(cfg, post, tmp_path, "2026-10-28", open_browser=_browser)
    assert ok == set() and len(notes) == 2
    assert not (tmp_path / "cap_a.png").exists()


def test_looks_blank():
    assert captures.looks_blank(Image.new("RGB", (100, 100), "#ffffff"))


# ---------------------------------------------------------------- 커먼즈 실제 사진

def _commons_response(n=3):
    pages = [{"index": i, "title": f"File:Court {i}.jpg", "imageinfo": [{
        "mime": "image/jpeg", "width": 2000, "height": 1300,
        "thumburl": f"https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/Court_{i}.jpg/1280px-Court_{i}.jpg",
        "thumbwidth": 1280, "thumbheight": 832, "descriptionurl": f"https://commons.wikimedia.org/wiki/File:Court_{i}.jpg",
        "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"}, "Artist": {"value": f"Photographer {i}"},
                        "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0"},
                        "ImageDescription": {"value": "Seoul court building"}}}]} for i in range(n)]
    return {"query": {"pages": pages}}


def test_find_candidates_and_apply_choice(tmp_path):
    cfg = type("C", (), {"photo_count": 2})()
    post = guide_post()
    got = []
    found, notes = realphotos.find_candidates(cfg, post, tmp_path, fetch=lambda url: _commons_response(),
                                              fetch_bytes=lambda url: got.append(url) or b"jpg")
    assert found == {"photo_a"} and notes == []
    cands = post["photo_candidates"]["photo_a"]
    assert [c["id"] for c in cands] == ["photo_a_c1", "photo_a_c2", "photo_a_c3"]
    assert all((tmp_path / c["file"]).exists() for c in cands)
    assert all("/500px-" in u for u in got)                # 검수용은 작게 받는다

    big = []
    chosen, dropped = realphotos.apply_choice(post, tmp_path, {"photo_a": "photo_a_c2"},
                                              fetch_bytes=lambda url: big.append(url) or b"big")
    assert chosen == {"photo_a"} and dropped == set()
    assert (tmp_path / "photo_a.jpg").read_bytes() == b"big" and "/1280px-" in big[0]
    assert "▲ 시험장 · 사진: Photographer 1 / CC BY-SA 4.0 / 위키미디어 커먼즈" in post["body_html"]
    assert post["photos"][0]["chosen"]["id"] == "photo_a_c2"


def test_apply_choice_none_drops_slot(tmp_path):
    post = guide_post(photo_candidates={"photo_a": [{"id": "photo_a_c1", "file": "photos/x.jpg", "title": "t",
                                                     "thumb_url": "u", "artist": "a", "license": "CC0",
                                                     "license_url": "", "page_url": ""}]})
    chosen, dropped = realphotos.apply_choice(post, tmp_path, {"photo_a": "none"})
    assert chosen == set() and dropped == {"photo_a"}


def test_no_license_ok_candidates_note(tmp_path):
    cfg = type("C", (), {"photo_count": 2})()
    post = guide_post()
    found, notes = realphotos.find_candidates(cfg, post, tmp_path, fetch=lambda url: {"query": {"pages": []}},
                                              fetch_bytes=lambda url: b"")
    assert found == set() and "photo_a" in notes[0]


# ---------------------------------------------------------------- 파이프라인

@pytest.fixture
def gcfg(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("NAVER_BLOG_ID_GUIDE", "guideblog")
    c = Config.load("guide")
    c.output_dir = tmp_path / "out"
    c.data_dir = tmp_path / "data"
    c.history_file = c.data_dir / "published_guide.json"
    c.gpt_factcheck = False
    return c


def test_attempt_with_real_images(gcfg, monkeypatch):
    out = gcfg.output_dir / "2026-10-28"
    post = guide_post()
    post["captures"].append({"name": "cap_b", "url": "https://www.gov.kr/x", "focus": "y", "caption": "정부24"})
    post["body_html"] = post["body_html"].replace("<h2>준비물", "<p>[[IMAGE:cap_b]]</p><h2>준비물")

    def write_post(cfg, out_dir, today, feedback=""):
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "post.json").write_text(json.dumps(post, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(generate, "write_post", write_post)

    def fake_capture_all(cfg, p, out_dir, today):
        Image.new("RGB", (1760, 1120), "#ffffff").save(out_dir / "cap_a.png")
        Image.new("RGB", (1760, 1120), "#ffffff").save(out_dir / "cap_b.png")
        for spec in p["captures"]:
            spec["captured"] = {"date": today}
        return {"cap_a", "cap_b"}, []
    monkeypatch.setattr(captures, "capture_all", fake_capture_all)
    monkeypatch.setattr(realphotos.commons, "search", lambda q, limit, fetch=None: [
        {"title": f"File:{i}.jpg", "description": "d", "thumb_url": f"https://upload.wikimedia.org/x/thumb/{i}/1280px-{i}.jpg",
         "page_url": "p", "artist": "Kim", "license": "CC BY 4.0", "license_url": "l"} for i in range(2)])
    monkeypatch.setattr(realphotos.commons, "_download",
                        lambda url, path, fetch_bytes=None: path.parent.mkdir(parents=True, exist_ok=True) or path.write_bytes(b"j"))
    monkeypatch.setattr(realphotos, "_fetch_large", lambda url, dst, fetch_bytes=None: dst.write_bytes(b"big"))

    def fake_fc(cfg, out_dir):
        fc = {"verdict": "pass", "images": {"cap_a": "ok", "cap_b": "bad: 로그인 화면"},
              "photo_choice": {"photo_a": "photo_a_c2"}, "summary": "ok"}
        (out_dir / "factcheck.json").write_text(json.dumps(fc), encoding="utf-8")
        return fc
    monkeypatch.setattr(generate, "factcheck", fake_fc)

    result = pipeline._attempt(gcfg, "2026-10-28", out, "")
    body = result["body_html"]
    assert "[[IMAGE:cap_a]]" in body and "▲ 큐넷 시험일정 공고 (2026.10.28 캡처)" in body
    assert "[[IMAGE:cap_b]]" not in body and "정부24" not in body and not (out / "cap_b.png").exists()
    assert "[[IMAGE:photo_a]]" in body and "사진: Kim / CC BY 4.0 / 위키미디어 커먼즈" in body
    assert (out / "photo_a.jpg").read_bytes() == b"big"
    assert json.loads((out / "stage.json").read_text())["visuals"] is True

    imgs = pipeline.render_images(gcfg, result, out)
    assert set(imgs) == {"thumbnail", "cap_a", "photo_a"}          # 요약 카드·인포그래픽 없음
    assert pipeline.add_infographic(gcfg, result, out) is True and not (out / "infographic.png").exists()
    note = pipeline._real_image_note(result, out)
    assert "캡처 1장" in note and "실제 사진 1장" in note


def test_photo_thumbnail_uses_real_image(tmp_path):
    bg = tmp_path / "photo_a.jpg"
    Image.new("RGB", (1600, 1000), "#3366cc").save(bg)
    out = images.make_thumbnail_photo({"chip": "생활 민원", "main_lines": ["전입신고", "온라인 5분"], "sub": "정부24"},
                                      bg, tmp_path / "t.png", images.guide_tone("B"))
    img = Image.open(out).convert("RGB")
    assert img.size == (images.THUMBNAIL_SIZE, images.THUMBNAIL_SIZE)
    r, g, b = img.getpixel((300, 40))
    assert b > r and b > 150                                # 위쪽은 사진 그대로(파랑)
    solid = images.make_thumbnail_photo({"main_lines": ["x"]}, tmp_path / "missing.jpg", tmp_path / "s.png", "#123456")
    assert Image.open(solid).convert("RGB").getpixel((5, 5)) == (0x12, 0x34, 0x56)
