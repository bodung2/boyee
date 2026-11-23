"""무료 활동지: 설계서 검사 → 원화 보관함(없는 것만 새로 그림·검수 통과 그림 재사용) → 그리기 → 검수 → 공유 → 나눔글."""
import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from naver_autopost import content, generate, openai_client, pipeline, profiles
from naver_autopost.config import Config
from tests.sample_post import make_post
from worksheets import build, library, render, share, spec as sp

pytest.importorskip("PIL")


def _font_ok():
    try:
        from worksheets import style
        style.font("title", 20)
        return True
    except Exception:  # noqa: BLE001
        return False


needs_font = pytest.mark.skipif(not _font_ok(), reason="한글 글꼴 없음")


def fake_gen(cfg, prompt, out, refs):
    """원화 대신 단색 도형(검은 테두리)을 그린다."""
    img = Image.new("RGB", (1024, 1024), "white")
    d = ImageDraw.Draw(img)
    d.ellipse([200, 200, 824, 824], fill=(230, 80, 60) if "line" not in out.stem else "white", outline="black", width=14)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    fake_gen.calls.append((out.stem, len(refs), prompt))


fake_gen.calls = []


def SPEC(**over):
    s = {
        "set_id": "2026-11-24-winter-clothes", "theme": "겨울 옷", "title": "겨울 옷 활동지", "age": "3~5세",
        "domain": "소근육", "nuri": "신체운동·건강 – 신체 활동 즐기기",
        "assets": [{"key": "mitten", "name": "장갑", "kind": "color", "prompt": "red mittens"},
                   {"key": "hat", "name": "모자", "kind": "color", "prompt": "a knitted hat"},
                   {"key": "scarf", "name": "목도리", "kind": "color", "prompt": "a striped scarf"},
                   {"key": "boot", "name": "장화", "kind": "color", "prompt": "a yellow boot"}],
        "pages": [
            {"type": "trace_lines", "title": "장갑을 찾아가요", "instruction": "점선을 따라 선을 그어요",
             "items": [{"asset": "mitten", "path": p} for p in ("straight", "wave", "zigzag")]},
            {"type": "match_shadow", "title": "그림자 찾기", "instruction": "같은 모양의 그림자를 찾아 이어요",
             "items": [{"asset": k, "name": n} for k, n in (("hat", "모자"), ("boot", "장화"), ("scarf", "목도리"))]},
        ],
        "parent_tip": "정답보다 대화가 먼저예요.",
    }
    s.update(over)
    return s


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.delenv("WORKSHEET_ASSETS", raising=False)
    monkeypatch.setattr("worksheets.style.ensure_fonts", lambda *a, **k: None)
    c = Config.load("worksheet")
    c.output_dir = tmp_path / "out"
    c.data_dir = tmp_path / "data"
    c.log_dir = tmp_path / "logs"
    c.history_file = c.data_dir / "published_worksheet.json"
    c.blog_id = "example"
    fake_gen.calls.clear()
    return c


# ---------------------------------------------------------------- 설정

def test_worksheet_profile_posts_to_childhood_blog_without_infographic(monkeypatch):
    monkeypatch.delenv("BROWSER_PROFILE_DIR", raising=False)
    w, child = Config.load("worksheet"), Config.load("childhood")
    assert w.profile.worksheet and not w.profile.illustrations
    assert w.profile_dir == child.profile_dir and w.blog_id == child.blog_id
    assert w.category == "무료 활동지" and w.infographic is False and w.social_draft is False
    assert w.retry_time == "off"


def share_post(**over):
    post = make_post(title="[유아 무료 활동지 나눔] 겨울 옷으로 배우는 선 긋기", lane="E",
                     thumbnail={"chip": "무료 나눔 · 활동지", "main_lines": ["겨울 옷", "선 긋기 세트"], "sub": "3~5세"})
    post.pop("card", None)
    post["body_html"] = (post["body_html"].replace("<p>[[IMAGE:card]]</p>", "")
                         + "<h2>📥 무료 다운로드</h2><p>[[IMAGE:worksheet_pdf]]</p>")
    post.update(over)
    return post


def test_share_post_format_rules():
    prof = profiles.get("worksheet")
    assert content.validate(share_post(), prof) == []
    errs = content.validate(share_post(title="겨울 선긋기 활동지 무료 나눔"), prof)
    assert any("제목 형식" in e for e in errs)
    no_pdf = share_post()
    no_pdf["body_html"] = no_pdf["body_html"].replace("<p>[[IMAGE:worksheet_pdf]]</p>", "")
    assert any("PDF 첨부" in e for e in content.validate(no_pdf, prof))
    with_card = share_post(card={"bullets": ["a", "b", "c"]})
    with_card["body_html"] += "<p>[[IMAGE:card]]</p>"
    assert any("요약 카드" in e for e in content.validate(with_card, prof))


def test_sales_words_blocked_in_worksheet_post():
    post = share_post()
    post["body_html"] += "<p>크몽에서 구매하기</p>"
    errs = content.validate(post, profiles.get("worksheet"))
    assert any("구매하기" in e for e in errs) and any("크몽" in e for e in errs)


# ---------------------------------------------------------------- 설계서

def test_spec_ok_and_problems():
    assert sp.problems(SPEC()) == []
    bad = SPEC(set_id="겨울", pages=[{"type": "maze", "title": "x", "instruction": "y"}])
    errs = sp.problems(bad)
    assert any("set_id" in e for e in errs) and any("모르는 활동" in e for e in errs)


def test_spec_checks_activity_rules():
    s = SPEC()
    s["pages"][1]["items"].append({"asset": "hat", "name": "모자"})          # 그림자 짝이 겹침
    s["pages"].append({"type": "coloring", "title": "색칠", "instruction": "칠해요",
                       "items": [{"asset": "mitten", "word": "장갑"}, {"asset": "hat", "word": "모자"}]})
    s["pages"].append({"type": "trace_letters", "title": "쓰기", "instruction": "써요",
                       "items": [{"asset": "hat", "word": "Hat"}]})
    errs = sp.problems(s)
    assert any("1~2장" in e for e in errs)
    assert any("서로 달라야" in e for e in errs)
    assert any("선 그림" in e for e in errs)
    assert any("한글 1~5자" in e for e in errs) and any("항목은 3~4개" in e for e in errs)


def test_spec_reuses_library_assets_without_prompt():
    s = SPEC(assets=[{"key": "mitten"}, {"key": "hat"}, {"key": "scarf"}, {"key": "boot"}])
    lib = {k: {"kind": "color", "status": "ok"} for k in ("mitten", "hat", "scarf", "boot")}
    assert sp.problems(s, lib) == []
    assert any("prompt" in e for e in sp.problems(s, {}))


def test_used_assets_order_includes_header_characters():
    assert sp.used_assets(SPEC(characters=["rabbit", "bear"])) == ["rabbit", "bear", "mitten", "hat", "boot", "scarf"]


# ---------------------------------------------------------------- 원화 보관함

def test_library_draws_only_missing_and_uses_references(cfg):
    lib = library.root(cfg.data_dir)
    assets = SPEC()["assets"]
    made = library.ensure(cfg, lib, assets, gen=fake_gen)
    assert made == ["mitten", "hat", "scarf", "boot"]
    assert all(c[1] == 0 for c in fake_gen.calls)            # 처음엔 참고 그림이 없다
    assert library.catalog(lib) == []                         # 검수 전(new)은 다시 쓸 목록에 안 나온다
    library.accept(lib, ["mitten", "hat"], "set1")
    library.reject(lib, ["scarf"], {"scarf": "bad: 글자"})
    assert {a["key"] for a in library.catalog(lib)} == {"mitten", "hat"}
    assert not library.path(lib, "scarf").exists()
    assert json.loads((lib / "rejected.json").read_text(encoding="utf-8"))[0]["reason"] == "bad: 글자"
    fake_gen.calls.clear()
    assert library.ensure(cfg, lib, assets, gen=fake_gen) == ["scarf"]    # 지운 것만 다시
    assert fake_gen.calls[0][1] == 2 and "master illustrations" in fake_gen.calls[0][2]


def test_line_prompt_asks_for_coloring_art():
    p = library.prompt_for({"prompt": "a snowman", "kind": "line"})
    assert "coloring-book" in p and "no text" in p and "a snowman" in p


def test_silhouette_keeps_shape_only():
    img = Image.new("RGB", (100, 100), "white")
    ImageDraw.Draw(img).rectangle([30, 30, 70, 70], fill=(255, 0, 0))
    sh = library.silhouette(img)
    assert sh.getpixel((5, 5))[3] == 0 and sh.getpixel((50, 50))[:3] == (120, 120, 128)


# ---------------------------------------------------------------- 그리기

@needs_font
def test_render_makes_pages_pdf_cover_and_answers(cfg, tmp_path):
    lib = library.root(cfg.data_dir)
    s = SPEC()
    s["pages"] = [s["pages"][1], {"type": "count_write", "title": "몇 개일까요?", "instruction": "세어 보고 써요",
                                  "items": [{"asset": k, "count": c} for k, c in
                                            (("hat", 3), ("boot", 7), ("mitten", 10), ("scarf", 2), ("hat", 5), ("boot", 1))]}]
    library.ensure(cfg, lib, s["assets"], gen=fake_gen)
    r = render.render(s, lib, tmp_path / "o", "https://blog.naver.com/example")
    assert r["answers"]["p2"] == [3, 7, 10, 2, 5, 1] and sorted(r["answers"]["p1"]) == [1, 2, 3]
    assert Image.open(tmp_path / "o" / "page1_full.png").size == (2480, 3508)          # A4 300dpi
    assert Image.open(tmp_path / "o" / "worksheet_p1.png").width == render.BLOG_WIDTH
    assert Image.open(tmp_path / "o" / "worksheet_cover.png").size == (1600, 900)
    assert Path(r["pdf"]).read_bytes()[:4] == b"%PDF"


@needs_font
def test_every_activity_type_renders(cfg, tmp_path):
    lib = library.root(cfg.data_dir)
    keys = ["a1", "a2", "a3", "a4", "a5", "a6"]
    library.ensure(cfg, lib, [{"key": k, "prompt": "x"} for k in keys] +
                   [{"key": "big_line", "prompt": "x", "kind": "line"}, {"key": "a1_line", "prompt": "x", "kind": "line"}],
                   gen=fake_gen)
    it = lambda n, **kw: [{"asset": keys[i % 6], "word": "사과", "name": "사과", **kw} for i in range(n)]
    pages = {
        "word_cards": it(8), "vocab_poster": it(6), "check_game": it(6), "trace_letters": it(4),
        "trace_lines": it(4, path="wave"), "cut_lines": it(3, path="zigzag"), "trace_outline": it(4),
        "half_draw": it(4), "coloring": [{"asset": "big_line", "word": "공"}] * 2, "match_same": it(4),
        "match_shadow": it(3), "emotion_match": it(3), "cut_paste": it(3), "count_write": it(8, count=9),
    }
    assert set(pages) == set(sp.PAGE_TYPES)
    for t, items in pages.items():
        page = {"type": t, "title": "제목", "instruction": "안내", "items": items, "container": "big_line"}
        img, _ = render.render_page({"set_id": "2026-11-24-x", "pages": [page]}, page, render.Assets(lib), "")
        assert img.size == (2480, 3508), t


def test_shuffle_never_keeps_a_pair_in_place():
    for n in range(3, 6):
        order = render._shuffled(n, f"seed{n}")
        assert sorted(order) == list(range(n)) and all(i != j for j, i in enumerate(order))


# ---------------------------------------------------------------- 한 세트 만들기(설계 → 검수 → 공유)

def _runner(qa_results):
    """Claude 대신: 설계는 SPEC을 쓰고, 검수는 qa_results를 차례로 낸다."""
    calls = []

    def run(cfg, prompt, log_file):
        out = Path(next(l.split("=", 1)[1] for l in prompt.splitlines() if l.startswith("OUTPUT_DIR=")))
        out = out if out.is_absolute() else Path(cfg.output_dir).parent / out
        calls.append(prompt.split("\n", 1)[0])
        if prompt.startswith("/worksheet-design"):
            (out / "spec.json").write_text(json.dumps(SPEC(), ensure_ascii=False), encoding="utf-8")
        else:
            (out / "qa.json").write_text(json.dumps(qa_results.pop(0), ensure_ascii=False), encoding="utf-8")
    run.calls = calls
    return run


@needs_font
def test_build_redraws_rejected_asset_then_shares(cfg, monkeypatch):
    monkeypatch.setattr(build, "_rel", lambda p: p)
    run = _runner([{"verdict": "fail", "assets": {"scarf": "bad: 글자가 있음"},
                    "fix_prompts": {"scarf": "a plain striped scarf"}, "summary": "목도리 다시"},
                   {"verdict": "pass", "assets": {"scarf": "ok"}, "summary": "좋음"}])
    shared = []

    def upload(pdf, name, state_dir):
        shared.append((pdf, name))
        return {"id": "F1", "url": "https://drive.google.com/file/d/F1/view?usp=sharing"}
    out = cfg.output_dir / "2026-11-24"
    info = build.build(cfg, out, "2026-11-24", run=run, gen=fake_gen, upload=upload)
    assert run.calls == ["/worksheet-design", "/worksheet-qa", "/worksheet-qa"]
    drawn = [c[0] for c in fake_gen.calls]
    assert drawn.count("scarf") == 2 and len(drawn) == 5
    assert "a plain striped scarf" in fake_gen.calls[-1][2]
    lib = library.root(cfg.data_dir)
    assert {a["key"] for a in library.catalog(lib)} == {"hat", "mitten", "boot", "scarf"}
    assert info["pdf_url"].endswith("usp=sharing") and shared[0][1].endswith("2026-11-24-winter-clothes.pdf")
    saved = json.loads((out / "worksheet.json").read_text(encoding="utf-8"))
    assert [p["image"] for p in saved["pages"]] == ["worksheet_p1", "worksheet_p2"]
    assert sorted(saved["answers"]["p2"]) == [1, 2, 3]


@needs_font
def test_build_rejects_when_activity_itself_fails(cfg, monkeypatch):
    monkeypatch.setattr(build, "_rel", lambda p: p)
    run = _runner([{"verdict": "fail", "assets": {}, "pages": {"2": "정답이 둘"}, "summary": "활동 오류"}])
    with pytest.raises(build.WorksheetRejected, match="활동 오류"):
        build.build(cfg, cfg.output_dir / "d", "2026-11-24", run=run, gen=fake_gen, upload=lambda *a: {})
    assert library.catalog(library.root(cfg.data_dir)) == []       # 통과 못 한 새 그림은 다시 쓸 목록에 없다


def test_share_creates_folder_upload_and_public_link(tmp_path):
    sent = []

    def send(url, body, ctype, method, token):
        sent.append((method, url.split("?")[0].rsplit("/", 2)[-2:], body[:200]))
        return {"id": "FOLDER" if b"folder" in body else "FILE"}
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    link = share.publish_pdf(pdf, "x.pdf", tmp_path / "drive", token="t", send=send)
    assert link == {"id": "FILE", "url": "https://drive.google.com/file/d/FILE/view?usp=sharing"}
    assert [s[0] for s in sent] == ["POST", "POST", "POST"]
    assert b'"anyone"' in sent[-1][2] and b'"reader"' in sent[-1][2]
    sent.clear()
    share.publish_pdf(pdf, "x.pdf", tmp_path / "drive", token="t", send=send)      # 같은 세트면 내용만 바꾼다
    assert [s[0] for s in sent] == ["PATCH", "POST"]


# ---------------------------------------------------------------- 발행 흐름에 끼우기

def test_attempt_builds_worksheet_first_and_maps_rejection(cfg, monkeypatch):
    import worksheets.build as wb
    order = []

    def fake_build(c, out_dir, today, feedback=""):
        order.append("build")
        raise wb.WorksheetRejected("원화 검수 3번 실패")
    monkeypatch.setattr(wb, "build", fake_build)
    monkeypatch.setattr(generate, "write_post", lambda *a, **k: order.append("write"))
    with pytest.raises(pipeline.Rejected, match="원화 검수"):
        pipeline._attempt(cfg, "2026-11-24", cfg.output_dir / "d", "")
    assert order == ["build"]


def test_attempt_writes_post_after_worksheet(cfg, monkeypatch):
    import worksheets.build as wb
    out = cfg.output_dir / "d"
    monkeypatch.setattr(wb, "build", lambda c, o, t, f="": o.mkdir(parents=True, exist_ok=True))

    def fake_write(c, out_dir, today, feedback=""):
        post = share_post()
        (out_dir / "post.json").write_text(json.dumps(post, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(generate, "write_post", fake_write)

    def fake_fc(c, out_dir):
        fc = {"verdict": "pass", "images": {}}
        (out_dir / "factcheck.json").write_text(json.dumps(fc), encoding="utf-8")
        return fc
    monkeypatch.setattr(generate, "factcheck", fake_fc)
    monkeypatch.setattr(openai_client, "factcheck", lambda c, p: {"verdict": "pass", "issues": []})
    post = pipeline._attempt(cfg, "2026-11-24", out, "")
    assert post["title"].startswith("[유아 무료 활동지 나눔]")
    assert json.loads((out / "stage.json").read_text())["worksheet"] is True


def test_write_prompt_points_to_worksheet_file(cfg, monkeypatch):
    seen = {}
    monkeypatch.setattr(generate, "_run_claude", lambda c, prompt, log_file, **k: seen.setdefault("p", prompt))
    out = cfg.output_dir / "d"
    out.mkdir(parents=True)
    with pytest.raises(generate.NoPostError):
        generate.write_post(cfg, out, "2026-11-24")
    assert "/worksheet-post" in seen["p"] and "WORKSHEET_FILE=" in seen["p"] and "worksheet_pdf" in seen["p"]


# ---------------------------------------------------------------- 워크북 원화(master) 넣기

def _fake_docx(path: Path):
    import io
    import zipfile
    with zipfile.ZipFile(path, "w") as z:
        for n in (4, 8, 10, 12):
            page = Image.new("RGB", (2480, 3508), (250, 247, 238))
            ImageDraw.Draw(page).rectangle([0, 0, 2480, 3508], fill=(250, 247, 238))
            for k, info in json.loads(library.SEED_FILE.read_text(encoding="utf-8"))["assets"].items():
                if info["image"] == f"image{n}.png":
                    x, y, w, h = info["box"]
                    ImageDraw.Draw(page).ellipse([x + 10, y + 10, x + w - 10, y + h - 10], fill=(200, 90, 40))
            buf = io.BytesIO()
            page.save(buf, "PNG")
            z.writestr(f"word/media/image{n}.png", buf.getvalue())


def test_seed_from_workbook_docx_makes_masters_and_style_references(cfg, tmp_path):
    lib = library.root(cfg.data_dir)
    docx = cfg.data_dir / "worksheets" / "명세서.docx"
    docx.parent.mkdir(parents=True)
    _fake_docx(docx)
    added = build.seed_masters(lib, cfg.data_dir)
    assert {"rabbit", "bear", "fox", "squirrel", "apple", "apple_line"} <= set(added)
    cat = {a["key"]: a for a in library.catalog(lib)}
    assert cat["rabbit"].get("character") and cat["apple"].get("master") and cat["apple"].get("has_line")
    assert build.seed_masters(lib, cfg.data_dir) == []                  # 두 번째는 건드리지 않는다
    refs = library._references(lib, library.load(lib), "color")
    index = library.load(lib)
    assert index[refs[0].stem].get("character") and not index[refs[1].stem].get("character")


def test_master_art_is_never_deleted_by_qa(cfg, monkeypatch):
    monkeypatch.setattr(build, "_rel", lambda p: p)
    lib = library.root(cfg.data_dir)
    docx = cfg.data_dir / "worksheets" / "w.docx"
    docx.parent.mkdir(parents=True)
    _fake_docx(docx)
    spec = SPEC(characters=["rabbit", "bear"])
    run = _runner([{"verdict": "fail", "assets": {"rabbit": "bad: 다름"}, "summary": "캐릭터 문제"}])

    def design_run(cfg, prompt, log_file):
        if prompt.startswith("/worksheet-design"):
            out = cfg.output_dir / "d"
            (out / "spec.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        else:
            run(cfg, prompt, log_file)
    with pytest.raises(build.WorksheetRejected):
        build.build(cfg, cfg.output_dir / "d", "2026-11-24", run=design_run, gen=fake_gen, upload=lambda *a: {})
    assert library.path(lib, "rabbit").exists()


def test_count_write_needs_six_to_eight_problems():
    page = {"type": "count_write", "title": "몇 개일까요?", "instruction": "세어 보고 써요",
            "items": [{"asset": "hat", "count": 3}] * 3}
    assert any("6~8개" in e for e in sp.problems(SPEC(pages=[page])))


def test_cut_paste_container_must_be_open():
    s = SPEC(assets=SPEC()["assets"] + [{"key": "basket_line", "kind": "line", "prompt": "a basket with a lid"}])
    s["pages"] = [{"type": "cut_paste", "title": "바구니 꾸미기", "instruction": "오려서 붙여요",
                   "container": "basket_line", "items": [{"asset": "hat"}, {"asset": "boot"}]}]
    assert any("열린" in e for e in sp.problems(s))
    s["assets"][-1]["open"] = True
    assert sp.problems(s) == []


def test_clipped_art_is_redrawn_with_margin_then_flagged(cfg):
    lib = library.root(cfg.data_dir)
    prompts = []

    def cut_gen(cfg, prompt, out, refs):                     # 늘 오른쪽 가장자리에 닿는 그림
        prompts.append(prompt)
        img = Image.new("RGB", (1024, 1024), "white")
        ImageDraw.Draw(img).rectangle([400, 300, 1023, 700], fill=(200, 120, 40))
        img.save(out)
    library.draw(cfg, lib, {"key": "box", "prompt": "a box"}, gen=cut_gen)
    assert len(prompts) == 2 and "wide white margin" in prompts[1]
    assert library.load(lib)["box"]["clipped"] is True
    assert library.touches_edge(Image.new("RGB", (100, 100), "white")) is False


@needs_font
def test_half_draw_ghost_lines_up_with_art(cfg):
    lib = library.root(cfg.data_dir)
    library.ensure(cfg, lib, [{"key": "ball", "prompt": "x"}], gen=fake_gen)
    A = render.Assets(lib)
    art, ghost = A.art("ball", 800), A.outline("ball", 800, same_art=True)
    assert art.size == ghost.size                            # 같은 그림에서 뽑아 자리가 정확히 같다


def test_seed_skips_clipped_example_art():
    seeds = json.loads(library.SEED_FILE.read_text(encoding="utf-8"))["assets"]
    assert seeds["picnic_basket_line"].get("skip")


def test_busy_pattern_is_simplified_to_outline_and_one_inner_line(cfg, monkeypatch):
    pytest.importorskip("cv2")
    lib = library.root(cfg.data_dir)

    def striped(cfg, prompt, out, refs):                     # 바구니 짜임처럼 안쪽 무늬가 아주 많은 그림
        img = Image.new("RGB", (1024, 1024), "white")
        d = ImageDraw.Draw(img)
        d.ellipse([150, 150, 874, 874], fill=(220, 160, 80), outline=(90, 50, 20), width=10)
        for y in range(220, 820, 28):
            d.line([(200, y), (824, y)], fill=(90, 50, 20), width=6)
        img.save(out)
    library.draw(cfg, lib, {"key": "weave", "prompt": "x"}, gen=striped)
    monkeypatch.setattr(render, "BUSY_RATIO", 99)
    full = sum(1 for v in render.Assets(lib)._edges("weave", 800).getdata() if v)
    monkeypatch.setattr(render, "BUSY_RATIO", 3.5)
    simple = sum(1 for v in render.Assets(lib)._edges("weave", 800).getdata() if v)
    assert simple < full * 0.6


def test_restyle_reopens_published_post_for_new_format(tmp_path, monkeypatch):
    from naver_autopost import history
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    c = Config.load("edu_series")
    c.output_dir, c.data_dir = tmp_path / "out", tmp_path / "data"
    c.history_file = c.data_dir / "published_edu_series.json"
    out = c.output_dir / "2026-11-23"
    out.mkdir(parents=True)
    (out / "post.json").write_text(json.dumps(make_post(title="[저경력 교사 필수 ⑦] 41조 연수"), ensure_ascii=False),
                                   encoding="utf-8")
    (out / "stage.json").write_text(json.dumps({"written": True, "illustrated": True, "claude_pass": True,
                                                "gpt_pass": True}), encoding="utf-8")
    (out / "ready.json").write_text("{}", encoding="utf-8")
    history.append(c.history_file, {"date": "2026-11-23", "title": "[저경력 교사 필수 ⑦] 41조 연수",
                                    "url": "https://blog.naver.com/x/1", "source": "autopost"})
    other = c.data_dir / "published_edu.json"
    history.append(other, {"date": "", "title": "[저경력 교사 필수 ⑦] 41조 연수", "url": "https://blog.naver.com/x/1"})
    seen = {}

    def fake_restyle(cfg, out_dir, number):
        seen["no"] = number
        post = json.loads((out_dir / "post.json").read_text(encoding="utf-8"))
        post["title"] = f"[저경력 교사 필수 시리즈 {chr(0x2460 + number - 1)}] 방학엔 학교 안 가도 될까?"
        (out_dir / "post.json").write_text(json.dumps(post, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(generate, "restyle_post", fake_restyle)
    lines = pipeline.restyle(c, "2026-11-23")
    assert seen["no"] == 1 and history.published_on(c.history_file, "2026-11-23") is None
    assert history.load(other) == [] and not (out / "ready.json").exists()
    stage = json.loads((out / "stage.json").read_text())
    assert stage["claude_pass"] is False and stage["gpt_pass"] is True and stage["written"] is True
    assert "시리즈 ①" in lines[-1]


def _thumb_font_ok():
    try:
        from naver_autopost.images import _font
        _font("bold", 20)
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _thumb_font_ok(), reason="썸네일용 한글 글꼴 없음")
def test_rethumb_uses_circled_number_and_uploads(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    c = Config.load("edu_series")
    c.output_dir, c.data_dir = tmp_path / "out", tmp_path / "data"
    out = c.output_dir / "2026-11-23"
    out.mkdir(parents=True)
    Image.new("RGB", (1600, 900), (120, 160, 200)).save(out / "illust_a.png")
    post = make_post(title="[저경력 교사 필수 시리즈 1] 방학엔 학교 안 가도 될까?", lane="B",
                     thumbnail={"chip": "저경력 교사 필수 1", "main_lines": ["방학엔", "학교 안 가도", "될까?"], "sub": "x"},
                     illustrations=[{"name": "illust_a"}])
    (out / "post.json").write_text(json.dumps(post, ensure_ascii=False), encoding="utf-8")
    got = {}
    path = pipeline.rethumb(c, "2026-11-23", upload=lambda data, name, mime, state: got.update(name=name, n=len(data)))
    assert path.exists() and got["name"] == "thumb_edu_series_2026-11-23.png" and got["n"] > 1000
