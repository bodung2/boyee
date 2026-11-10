"""아이와 가볼 곳(장소 글): 사진 폴더 → 위치 정보 삭제·얼굴 흐림 → 글 → 검수 → 발행 → 폴더 정리."""
import json
import os
import sys
import time
from pathlib import Path

import pytest
from PIL import Image

from naver_autopost import content, generate, openai_client, pipeline, places, profiles
from naver_autopost.config import ROOT, Config
from tests.sample_post import make_post

PLACE = profiles.get("place")
OLD = time.time() - 3600
MEMO = ("장소: 국립과천과학관\n다녀온 날: 2026-10-18\n첫째(6살)는 천체투영관, 둘째(4살)는 유아체험관.\n"
        "둘째가 \"별이 머리 위로 지나가!\"라고 함. 아쉬운 점: 주말 11시 대기 40분.\n")


def place_post(**over):
    post = make_post(
        lane="P", cluster="과학관·박물관", domain=None, topic="국립과천과학관",
        title="국립과천과학관 아이와 가볼 만한 곳 | 반나절 코스",
        thumbnail={"chip": "아이와 가볼 곳", "main_lines": ["과천과학관", "아이랑 가면"], "sub": "반나절 코스"},
        photos=[{"name": "photo_01"}, {"name": "photo_02"}, {"name": "photo_03"}],
        cover_photo="photo_02",
    )
    post["body_html"] = ("<p>[[IMAGE:photo_01]]</p>" + post["body_html"]
                         + "<p>[[IMAGE:photo_02]]</p><p>[[IMAGE:photo_03]]</p>")
    post.update(over)
    return post


def _jpeg_with_gps(path, color=(200, 120, 40), taken="2026:10:18 10:00:00"):
    img = Image.new("RGB", (2400, 1800), color)
    exif = Image.Exif()
    exif[271] = "Phone Maker"                                   # 기기
    exif.get_ifd(0x8769)[36867] = taken                         # 촬영 시각
    exif.get_ifd(0x8825).update({1: "N", 2: (37.0, 26.0, 0.0), 3: "E", 4: (127.0, 0.0, 0.0)})   # GPS
    img.save(path, "JPEG", exif=exif)
    os.utime(path, (OLD, OLD))


def make_folder(root, name="국립과천과학관", photos=3, memo=MEMO, memo_encoding="utf-8"):
    folder = root / name
    folder.mkdir(parents=True)
    for i in range(photos):
        _jpeg_with_gps(folder / f"IMG_{i}.jpg", taken=f"2026:10:18 1{3 - i}:00:00")   # 이름과 촬영 순서가 반대
    if memo is not None:
        (folder / "메모.txt").write_bytes(memo.encode(memo_encoding))
    for p in [*folder.iterdir(), folder]:
        os.utime(p, (OLD, OLD))
    return folder


NO_FACES = object()     # 가짜 얼굴 찾기(테스트에서 모델을 받지 않게)


@pytest.fixture
def no_faces(monkeypatch):
    monkeypatch.setattr(places, "find_faces", lambda img, detector=None: [])
    monkeypatch.setattr(places, "FaceFinder", lambda models_dir=None: NO_FACES)
    return NO_FACES


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    c = Config.load("place")
    c.output_dir = tmp_path / "out"
    c.data_dir = tmp_path / "data"
    c.log_dir = tmp_path / "logs"
    c.history_file = c.data_dir / "published_place.json"
    c.places_inbox = tmp_path / "places_inbox"
    return c


# ---------------------------------------------------------------- 설정·구조 검사

def test_place_uses_childhood_blog_login_and_own_category(monkeypatch):
    monkeypatch.delenv("BROWSER_PROFILE_DIR", raising=False)
    place, child = Config.load("place"), Config.load("childhood")
    assert place.profile_dir == child.profile_dir == ROOT / ".browser-profile"
    assert place.blog_id == child.blog_id
    assert place.category == "아이와 가볼 곳"
    assert place.infographic is False and place.social_draft is False
    assert place.retry_time == "off"


def test_place_post_valid():
    assert content.validate(content.normalize(place_post()), PLACE) == []


def test_unknown_photo_marker_blocks():
    post = place_post()
    post["body_html"] += "<p>[[IMAGE:photo_09]]</p>"
    assert any("알 수 없는" in e for e in content.validate(content.normalize(post), PLACE))


def test_too_few_photos_in_body_blocks():
    post = place_post()
    post["body_html"] = content.remove_markers(post["body_html"], {"photo_02", "photo_03"})
    assert any("사진이 1장" in e for e in content.validate(content.normalize(post), PLACE))


def test_home_distance_phrase_blocks():
    post = place_post()
    post["body_html"] += "<p>집에서 차로 20분이라 자주 가요.</p>"
    assert any("집에서 차로" in e for e in content.validate(content.normalize(post), PLACE))


def test_place_needs_fewer_sources_than_info_posts():
    post = place_post(sources=[{"title": "관람 안내", "url": "https://x", "primary": True},
                               {"title": "구석구석", "url": "https://y", "primary": False}],
                      claims=[{"text": f"사실 {i}"} for i in range(3)])
    assert content.validate(content.normalize(post), PLACE) == []


# ---------------------------------------------------------------- 폴더 고르기

def test_inspect_reports_missing_pieces(tmp_path):
    f = places.inspect(make_folder(tmp_path, photos=2, memo=None))
    assert not f.ready
    assert any("메모" in p for p in f.problems) and any("사진이 2장" in p for p in f.problems)
    short = places.inspect(make_folder(tmp_path, "짧은메모", memo="좋았음"))
    assert any("짧습니다" in p for p in short.problems)


def test_recently_changed_folder_waits(tmp_path):
    folder = make_folder(tmp_path)
    (folder / "IMG_9.jpg").write_bytes((folder / "IMG_0.jpg").read_bytes())    # 방금 복사 중
    f = places.inspect(folder)
    assert not f.ready and any("방금" in p for p in f.problems)


def test_pick_skips_underscore_folders_and_takes_ready_one(tmp_path):
    root = tmp_path / "inbox"
    places.ensure_inbox(root)
    make_folder(root, "덜됨", photos=1)
    make_folder(root, "준비됨")
    folder, waiting = places.pick(root)
    assert folder.name == "준비됨"
    assert [w.name for w in waiting] == ["덜됨"]          # _발행됨 같은 폴더는 후보가 아니다


def test_memo_saved_by_old_notepad_cp949_is_read(tmp_path):
    f = places.inspect(make_folder(tmp_path, memo_encoding="cp949"))
    assert f.ready and "천체투영관" in places.read_memo(f.memo)


def test_folder_key_changes_with_memo(tmp_path):
    a = places.inspect(make_folder(tmp_path / "a"))
    b = places.inspect(make_folder(tmp_path / "b", memo=MEMO + "두 번째 방문.\n"))
    assert a.name == b.name and a.key != b.key


# ---------------------------------------------------------------- 사진 처리

def test_prepare_strips_exif_resizes_and_orders_by_time(tmp_path, no_faces):
    folder = places.inspect(make_folder(tmp_path / "in"))
    out = tmp_path / "out"
    photos = places.prepare(folder, out, detector=NO_FACES)
    assert [p["original"] for p in photos] == ["IMG_2.jpg", "IMG_1.jpg", "IMG_0.jpg"]   # 촬영 시각 순서
    for p in photos:
        with Image.open(out / p["file"]) as img:
            assert max(img.size) == places.LONG_SIDE
            exif = img.getexif()
            assert len(exif) == 0 and not exif.get_ifd(0x8825)                          # 위치 정보 없음
    assert "천체투영관" in (out / "memo.txt").read_text(encoding="utf-8")
    saved = json.loads((out / "photos.json").read_text(encoding="utf-8"))
    assert saved["place_folder"] == "국립과천과학관" and len(saved["photos"]) == 3


def test_prepare_blurs_detected_faces(tmp_path, monkeypatch, no_faces):
    folder = places.inspect(make_folder(tmp_path / "in"))

    def fake_faces(img, detector=None):
        return [(100, 100, 200, 200)]
    monkeypatch.setattr(places, "find_faces", fake_faces)
    photos = places.prepare(folder, tmp_path / "out", detector=NO_FACES)
    assert all(p["faces_blurred"] == 1 for p in photos)


def test_blur_faces_changes_only_face_area():
    img = Image.new("RGB", (400, 400), "white")
    for x in range(150, 250, 4):                     # 얼굴 자리에 무늬
        for y in range(150, 250):
            img.putpixel((x, y), (0, 0, 0))
    out = places.blur_faces(img, [(150, 150, 100, 100)])
    assert out.getpixel((10, 10)) == (255, 255, 255)
    stripes = [out.getpixel((x, 200))[0] for x in range(150, 250)]
    assert max(stripes) - min(stripes) < 80          # 무늬가 뭉개졌다


def test_no_opencv_means_no_upload(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "cv2", None)
    folder = places.inspect(make_folder(tmp_path / "in"))
    with pytest.raises(places.PhotoError, match="OpenCV"):
        places.prepare(folder, tmp_path / "out")
    assert not (tmp_path / "out" / "photo_01.jpg").exists()


def test_haar_detector_runs_without_model(tmp_path):
    pytest.importorskip("cv2")
    finder = places.FaceFinder(models_dir=None)       # 모델 없이도(인터넷이 안 돼도) 옛 방식으로 찾는다
    assert finder.cascades and finder.yunet is None
    assert finder.find(Image.new("RGB", (800, 600), (90, 160, 90))) == []   # 얼굴 없는 사진에서 헛잡지 않는다


def test_yunet_download_failure_falls_back(tmp_path, monkeypatch):
    import urllib.request

    def boom(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert places.yunet_model(tmp_path / "models") is None


def test_yunet_rejects_wrong_file(tmp_path, monkeypatch):
    import io
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: io.BytesIO(b"not a model"))
    assert places.yunet_model(tmp_path / "models") is None
    assert not list((tmp_path / "models").iterdir())  # 해시가 다른 파일은 남기지 않는다


def test_yunet_used_when_model_present(tmp_path, monkeypatch):
    cv2 = pytest.importorskip("cv2")
    created = []

    class FakeYN:
        def setInputSize(self, size):
            self.size = size

        def detect(self, bgr):
            import numpy as np
            return 1, np.array([[10, 20, 30, 40] + [0] * 10 + [0.9]], dtype=np.float32)
    model = tmp_path / "m.onnx"
    model.write_bytes(b"model-bytes")
    monkeypatch.setattr(places, "yunet_model", lambda d: model)
    monkeypatch.setattr(cv2.FaceDetectorYN, "create", lambda *a: created.append(a) or FakeYN(), raising=False)
    finder = places.FaceFinder(models_dir=tmp_path)
    assert created and (10, 20, 30, 40) in finder.find(Image.new("RGB", (200, 200), "white"))
    # 윈도우 OpenCV는 한글 경로를 못 연다 → 경로가 아니라 파일 내용(메모리)을 넘긴다
    assert created[0][0] == "onnx" and created[0][1].tobytes() == b"model-bytes"
    assert finder.cascades == []                      # YuNet을 쓰면 무늬를 얼굴로 착각하는 옛 방식은 끈다


def test_yunet_load_error_falls_back_to_haar(tmp_path, monkeypatch):
    cv2 = pytest.importorskip("cv2")
    model = tmp_path / "m.onnx"
    model.write_bytes(b"x")
    monkeypatch.setattr(places, "yunet_model", lambda d: model)

    def broken(*a):
        raise cv2.error("Can't read ONNX file")
    monkeypatch.setattr(cv2.FaceDetectorYN, "create", broken, raising=False)
    finder = places.FaceFinder(models_dir=tmp_path)       # 멈추지 않고 옛 방식으로
    assert finder.yunet is None and len(finder.cascades) == 3


def test_haar_files_load_from_korean_path(tmp_path):
    cv2 = pytest.importorskip("cv2")
    korean = tmp_path / "박보영" / "data"
    korean.mkdir(parents=True)
    src = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    (korean / src.name).write_bytes(src.read_bytes())
    cascade = places._load_cascade(cv2, korean / src.name)
    assert cascade is not None and not cascade.empty()
    assert places._load_cascade(cv2, korean / "없는파일.xml") is None


def test_archive_moves_folder_with_date(tmp_path):
    root = tmp_path / "inbox"
    folder = make_folder(root)
    moved = places.archive(folder, root, "2026-11-07")
    assert moved == root / "_발행됨" / "2026-11-07 국립과천과학관" and not folder.exists()


# ---------------------------------------------------------------- 파이프라인

def test_no_folder_means_quiet_day_without_browser(cfg, monkeypatch, caplog):
    caplog.set_level("INFO")
    from naver_autopost import publisher
    monkeypatch.setattr(publisher, "check_session", lambda c: pytest.fail("폴더가 없으면 브라우저를 열지 않는다"))
    sent = []
    monkeypatch.setattr(pipeline.notify, "send", lambda c, m: sent.append(m))
    assert pipeline.run(cfg) == 0
    assert sent == []
    assert (cfg.places_inbox / places.EXAMPLE_MEMO).exists()
    assert pipeline.NO_PLACE_LOG in caplog.text


def test_incomplete_folder_is_reported(cfg, monkeypatch):
    make_folder(cfg.places_inbox, "메모없음", memo=None)
    sent = []
    monkeypatch.setattr(pipeline.notify, "send", lambda c, m: sent.append(m))
    assert pipeline._pick_place(cfg, cfg.output_dir / "d") is None
    assert len(sent) == 1 and "메모없음" in sent[0] and "메모.txt가 없습니다" in sent[0]


def test_already_published_folder_is_archived_not_reposted(cfg, monkeypatch):
    folder = places.inspect(make_folder(cfg.places_inbox))
    cfg.history_file.parent.mkdir(parents=True)
    cfg.history_file.write_text(json.dumps([{"date": "2026-11-06", "source": "autopost", "url": "u",
                                             "place_folder": folder.name, "place_key": folder.key}]),
                                encoding="utf-8")
    monkeypatch.setattr(pipeline.notify, "send", lambda c, m: None)
    assert pipeline._pick_place(cfg, cfg.output_dir / "d") is None
    assert not folder.path.exists() and list((cfg.places_inbox / "_발행됨").iterdir())


def test_attempt_prepares_photos_and_stops_when_review_drops_too_many(cfg, monkeypatch, no_faces):
    folder = places.inspect(make_folder(cfg.places_inbox))
    out = cfg.output_dir / "2026-11-07"

    def fake_write(c, out_dir, today, feedback=""):
        assert (out_dir / "photo_01.jpg").exists() and (out_dir / "memo.txt").exists()
        (out_dir / "post.json").write_text(json.dumps(place_post(), ensure_ascii=False), encoding="utf-8")
        return out_dir / "post.json"
    monkeypatch.setattr(generate, "write_post", fake_write)

    def fake_fc(c, out_dir):
        fc = {"verdict": "pass", "images": {"photo_01": "ok", "photo_02": "bad: 얼굴", "photo_03": "bad: 명찰"}}
        (out_dir / "factcheck.json").write_text(json.dumps(fc), encoding="utf-8")
        return fc
    monkeypatch.setattr(generate, "factcheck", fake_fc)
    with pytest.raises(places.PhotoError, match="1장"):
        pipeline._attempt(cfg, "2026-11-07", out, "", place=folder)
    assert not (out / "photo_02.jpg").exists()       # 검수에서 뺀 사진 파일도 지운다


def test_attempt_passes_with_reviewed_photos(cfg, monkeypatch, no_faces):
    folder = places.inspect(make_folder(cfg.places_inbox))
    out = cfg.output_dir / "2026-11-07"
    monkeypatch.setattr(generate, "write_post", lambda c, o, t, f="": (
        (o / "post.json").write_text(json.dumps(place_post(), ensure_ascii=False), encoding="utf-8"), o / "post.json")[1])

    def fake_fc(c, out_dir):
        fc = {"verdict": "pass", "images": {"photo_01": "ok", "photo_02": "ok", "photo_03": "bad: 번호판"}}
        (out_dir / "factcheck.json").write_text(json.dumps(fc), encoding="utf-8")
        return fc
    monkeypatch.setattr(generate, "factcheck", fake_fc)
    monkeypatch.setattr(openai_client, "factcheck", lambda c, p: {"verdict": "pass", "issues": []})
    post = pipeline._attempt(cfg, "2026-11-07", out, "", place=folder)
    assert "[[IMAGE:photo_03]]" not in post["body_html"]
    assert [p["name"] for p in post["photos"]] == ["photo_01", "photo_02"]

    imgs = pipeline.render_images(cfg, post, out)
    assert imgs["photo_01"].suffix == ".jpg" and "photo_03" not in imgs
    assert imgs["thumbnail"].exists() and imgs["card"].exists()


def test_place_prompt_points_at_memo_and_photos(cfg, tmp_path):
    prompt = generate._place_prompt(cfg, cfg.output_dir / "d", "2026-11-07", [])
    assert "/childhood-place-post" in prompt and "MEMO_FILE=" in prompt and "PHOTOS_FILE=" in prompt
    assert "지어내지 마라" in prompt


def test_gpt_factcheck_knows_place_experience_is_not_checked(cfg):
    assert "1인칭 문장은 검증 대상이 아니다" in openai_client._instructions(cfg)


def test_quest_board_shows_quiet_day_as_skip(tmp_path):
    from quest_board import checks
    from quest_board.schedule import Quest
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "place-2026-11-07.log").write_text(
        f"2026-11-07 18:10:01 INFO naver_autopost.pipeline: {pipeline.NO_PLACE_LOG}(C:/x)\n", encoding="utf-8")
    p = checks.Paths(data=tmp_path / "data", output=tmp_path / "out", logs=logs)
    q = Quest("NaverAutoPost-place", "run_daily.bat", "--profile place")
    assert checks._naver(p, q, "2026-11-07").state == "skip"
    assert checks._naver(p, q, "2026-11-08").state == "none"
    assert checks.NO_PLACE_LOG == pipeline.NO_PLACE_LOG


def test_place_skills_exist():
    for name in (PLACE.write_skill, PLACE.factcheck_skill):
        assert (ROOT / ".claude" / "skills" / name / "SKILL.md").exists()


# ---------------------------------------------------------------- 첫 글 검토 뒤 규칙

def test_child_age_in_title_or_thumbnail_blocks():
    post = place_post(title="광명스피돔 아이와 가볼 만한 곳 | 4살·2살 실내 놀이")
    errors = content.validate(content.normalize(post), PLACE)
    assert any("아이 나이" in e and "4살" in e for e in errors)
    post = place_post(thumbnail={"chip": "아이와 가볼 곳", "main_lines": ["광명스피돔"], "sub": "4살·2살 실내 신체놀이"})
    assert any("아이 나이" in e for e in content.validate(content.normalize(post), PLACE))


def test_child_age_in_body_is_fine():
    post = place_post()
    post["body_html"] = "<p>첫째(4살)와 둘째(2살)를 데리고 다녀왔어요.</p>" + post["body_html"]
    assert content.validate(content.normalize(post), PLACE) == []


def test_research_narration_blocks():
    post = place_post()
    post["body_html"] += "<p>공식 홈페이지는 열리지 않아 직접 확인하지 못했고, 2025년 9월 기사 기준이에요.</p>"
    errors = content.validate(content.normalize(post), PLACE)
    assert any("확인하지 못했" in e for e in errors) and any("기사 기준" in e for e in errors)


URL = "https://blog.naver.com/kkus_i/224472398545"


def _published_setup(cfg, day="2026-11-11"):
    folder = places.inspect(make_folder(cfg.places_inbox, "광명 스피돔"))
    moved = places.archive(folder.path, cfg.places_inbox, day)
    cfg.history_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.history_file.write_text(json.dumps([
        {"date": day, "title": "광명스피돔 아이와 가볼 만한 곳", "url": URL, "source": "autopost",
         "place_folder": folder.name, "place_key": folder.key},
        {"date": "2026-11-01", "title": "다른 글", "url": "https://blog.naver.com/kkus_i/1", "source": "sync"},
    ], ensure_ascii=False), encoding="utf-8")
    child = cfg.data_dir / "published_childhood.json"
    child.write_text(json.dumps([{"date": day, "title": "광명", "url": URL, "source": "sync"}]), encoding="utf-8")
    out = cfg.output_dir / day
    out.mkdir(parents=True)
    (out / "ready.json").write_text("{}", encoding="utf-8")
    return folder, moved, out, child


def test_place_redo_puts_folder_back_and_clears_records(cfg):
    folder, moved, out, child = _published_setup(cfg)
    lines = pipeline.redo_place(cfg, URL + "/")
    assert (cfg.places_inbox / "광명 스피돔").is_dir() and not moved.exists()
    assert [e["url"] for e in json.loads(cfg.history_file.read_text(encoding="utf-8"))] == ["https://blog.naver.com/kkus_i/1"]
    assert json.loads(child.read_text(encoding="utf-8")) == []          # 유아 글 내부 링크 후보에서도 빠짐
    assert not out.exists() and list(cfg.output_dir.glob("2026-11-11-redo-*"))   # 옛 글을 다시 올리지 않게
    assert any("되돌렸습니다" in line for line in lines)
    # 되돌린 폴더는 다시 글감 후보가 된다(이미 발행한 폴더로 보지 않음)
    again = pipeline._pick_place(cfg, cfg.output_dir / "2026-11-12")
    assert again is not None and again.name == "광명 스피돔"


def test_place_redo_by_date_and_unknown_target(cfg):
    _published_setup(cfg)
    with pytest.raises(ValueError, match="발행 이력이 없습니다"):
        pipeline.redo_place(cfg, "https://blog.naver.com/kkus_i/999")
    assert pipeline.redo_place(cfg, "2026-11-11")


def test_place_redo_refuses_to_overwrite_existing_folder(cfg):
    _published_setup(cfg)
    make_folder(cfg.places_inbox, "광명 스피돔")
    with pytest.raises(ValueError, match="같은 이름"):
        pipeline.redo_place(cfg, URL)


def test_place_redo_command(cfg, monkeypatch, capsys):
    from naver_autopost import __main__ as cli
    monkeypatch.setattr(cli.Config, "load", lambda name: cfg if name == "place" else pytest.fail(name))
    _published_setup(cfg)
    assert cli.main(["place-redo", URL]) == 0
    assert "run_daily.bat --profile place" in capsys.readouterr().out
