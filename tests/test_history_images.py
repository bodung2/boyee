from PIL import Image

from naver_autopost import history, images
from tests.sample_post import make_post


def test_published_on_only_counts_autopost(tmp_path):
    path = tmp_path / "published.json"
    history.append(path, {"date": "2026-09-27", "title": "수동 글", "url": "u1", "source": "sheet-import"})
    assert history.published_on(path, "2026-09-27") is None
    history.append(path, {"date": "2026-09-27", "title": "자동 글", "url": "u2", "source": "autopost"})
    assert history.published_on(path, "2026-09-27")["url"] == "u2"


def test_import_csv(tmp_path):
    csv_path = tmp_path / "sheet.csv"
    csv_path.write_text("발행일,제목,카테고리,발행 글 링크\n2026-09-01,교원 육아지원 제도 총정리,실무,https://blog.naver.com/a/1\n",
                        encoding="utf-8-sig")
    path = tmp_path / "published.json"
    assert history.import_csv(path, csv_path) == 1
    assert history.import_csv(path, csv_path) == 0
    assert history.load(path)[0]["url"] == "https://blog.naver.com/a/1"


def test_images_render(tmp_path):
    post = make_post()
    thumb = images.make_thumbnail(post["thumbnail"], tmp_path / "t.png")
    card = images.make_card(post["card"], tmp_path / "c.png")
    assert Image.open(thumb).size == (1200, 1200)
    assert Image.open(card).size[0] == 1200


def test_import_csv_resaved_by_excel_cp949(tmp_path):
    csv_path = tmp_path / "sheet.csv"
    csv_path.write_bytes("제목,발행 글 링크\n4세 블록 놀이,https://blog.naver.com/a/2\n".encode("cp949"))
    path = tmp_path / "published.json"
    assert history.import_csv(path, csv_path) == 1
    assert history.load(path)[0]["title"] == "4세 블록 놀이"
