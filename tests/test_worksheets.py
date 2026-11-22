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
        render.font("bold", 20)
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
             "rows": [{"from": "hat", "to": "mitten", "path": p} for p in ("straight", "wave", "zigzag")]},
            {"type": "find_same", "title": "똑같은 그림", "instruction": "같은 그림에 동그라미 해요",
             "rows": [{"target": t, "options": ["mitten", "hat", "scarf", "boot"]} for t in ("hat", "boot", "scarf")]},
        ],
        "parent_tip": "정답보다 대화가 먼저예요.",
    }
    s.update(over)
    return s


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.delenv("WORKSHEET_ASSETS", raising=False)
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


def test_sales_words_blocked_in_worksheet_post():
    post = make_post(title="겨울 선긋기 활동지 무료 나눔", body_html=make_post()["body_html"] + "<p>크몽에서 구매하기</p>")
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
    s["pages"][1]["rows"][0]["options"] = ["mitten", "mitten", "scarf", "boot"]   # target 없음·중복
    s["pages"].append({"type": "coloring", "title": "색칠", "instruction": "칠해요", "asset": "mitten"})
    s["pages"].append({"type": "trace_letters", "title": "쓰기", "instruction": "써요",
                       "words": [{"asset": "hat", "word": "Hat"}]})
    errs = sp.problems(s)
    assert any("1~2장" in e for e in errs)
    assert any("보기 4개" in e for e in errs)
    assert any("선 그림" in e for e in errs)
    assert any("한글 1~4자" in e for e in errs)


def test_spec_reuses_library_assets_without_prompt():
    s = SPEC(assets=[{"key": "mitten"}, {"key": "hat"}, {"key": "scarf"}, {"key": "boot"}])
    lib = {k: {"kind": "color", "status": "ok"} for k in ("mitten", "hat", "scarf", "boot")}
    assert sp.problems(s, lib) == []
    assert any("prompt" in e for e in sp.problems(s, {}))


def test_used_assets_order():
    assert sp.used_assets(SPEC()) == ["hat", "mitten", "scarf", "boot"]


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
    assert fake_gen.calls[0][1] == 2 and "same worksheet series" in fake_gen.calls[0][2]


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
    s["pages"].append({"type": "count_write", "title": "몇 개?", "instruction": "세어 보고 써요",
                       "rows": [{"asset": "hat", "count": 3}, {"asset": "boot", "count": 7}, {"asset": "mitten", "count": 10}]})
    s["pages"] = s["pages"][1:]
    library.ensure(cfg, lib, s["assets"], gen=fake_gen)
    r = render.render(s, lib, tmp_path / "o", "https://blog.naver.com/example")
    assert r["answers"] == {"p1": [2, 4, 3], "p2": [3, 7, 10]}
    assert Image.open(tmp_path / "o" / "page1_full.png").size == (render.W, render.H)
    assert Image.open(tmp_path / "o" / "worksheet_p1.png").width == render.BLOG_WIDTH
    assert Image.open(tmp_path / "o" / "worksheet_cover.png").size == (1600, 900)
    assert Path(r["pdf"]).read_bytes()[:4] == b"%PDF"


def test_shuffle_never_keeps_a_pair_in_place():
    for n in range(3, 6):
        order = render._shuffled(list(range(n)), f"seed{n}")
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
    assert drawn.count("scarf") == 2 and drawn.count("guide_bear") == 1
    assert "a plain striped scarf" in fake_gen.calls[-1][2]
    lib = library.root(cfg.data_dir)
    assert {a["key"] for a in library.catalog(lib)} == {"guide_bear", "hat", "mitten", "boot", "scarf"}
    assert info["pdf_url"].endswith("usp=sharing") and shared[0][1].endswith("2026-11-24-winter-clothes.pdf")
    saved = json.loads((out / "worksheet.json").read_text(encoding="utf-8"))
    assert [p["image"] for p in saved["pages"]] == ["worksheet_p1", "worksheet_p2"]
    assert saved["answers"] == {"p2": [2, 4, 3]}


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
        post = make_post(title="겨울 선긋기 활동지 무료 나눔 | 3~5세", lane="E")
        (out_dir / "post.json").write_text(json.dumps(post, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(generate, "write_post", fake_write)

    def fake_fc(c, out_dir):
        fc = {"verdict": "pass", "images": {}}
        (out_dir / "factcheck.json").write_text(json.dumps(fc), encoding="utf-8")
        return fc
    monkeypatch.setattr(generate, "factcheck", fake_fc)
    monkeypatch.setattr(openai_client, "factcheck", lambda c, p: {"verdict": "pass", "issues": []})
    post = pipeline._attempt(cfg, "2026-11-24", out, "")
    assert post["title"].startswith("겨울 선긋기")
    assert json.loads((out / "stage.json").read_text())["worksheet"] is True


def test_write_prompt_points_to_worksheet_file(cfg, monkeypatch):
    seen = {}
    monkeypatch.setattr(generate, "_run_claude", lambda c, prompt, log_file, **k: seen.setdefault("p", prompt))
    out = cfg.output_dir / "d"
    out.mkdir(parents=True)
    with pytest.raises(generate.NoPostError):
        generate.write_post(cfg, out, "2026-11-24")
    assert "/worksheet-post" in seen["p"] and "WORKSHEET_FILE=" in seen["p"] and "pdf_url" in seen["p"]
