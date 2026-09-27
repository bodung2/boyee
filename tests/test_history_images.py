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


def test_forget_removes_by_url_or_date(tmp_path):
    path = tmp_path / "published.json"
    history.append(path, {"date": "2026-09-28", "title": "a", "url": "https://blog.naver.com/x/1", "source": "autopost"})
    history.append(path, {"date": "2026-09-27", "title": "b", "url": "https://blog.naver.com/x/2", "source": "autopost"})
    assert [e["title"] for e in history.remove(path, "https://blog.naver.com/x/1/")] == ["a"]
    assert history.published_on(path, "2026-09-28") is None
    assert [e["title"] for e in history.remove(path, "2026-09-27")] == ["b"]


def test_post_url_patterns():
    from naver_autopost.publisher import POST_URL
    ok = ["https://blog.naver.com/kkus_i/224424354626",
          "https://blog.naver.com/kkus_i?Redirect=Log&logNo=224424354626",
          "https://blog.naver.com/PostView.naver?blogId=kkus_i&logNo=224424354626&redirect=Dlog",
          "https://blog.naver.com/PostView.nhn?blogId=kkus_i&logNo=224424354626"]
    for u in ok:
        m = POST_URL.search(u)
        assert m and (m.group(1) or m.group(2)) == "224424354626", u
    for u in ["https://blog.naver.com/kkus_i?Redirect=Write&", "https://blog.naver.com/PostWriteForm.naver?blogId=kkus_i"]:
        assert not POST_URL.search(u), u


def test_find_post_url_by_title_from_rss():
    from naver_autopost.publisher import find_post_url_by_title

    xml = ("<rss><channel><item><title><![CDATA[다른 글]]></title><link>https://blog.naver.com/kkus_i/111111111?fromRss=true</link></item>"
           "<item><title><![CDATA[초등 입학 전 한글, 어디까지 떼야 할까? | 준비]]></title>"
           "<link><![CDATA[https://blog.naver.com/kkus_i/224424354626?fromRss=true&trackingCode=rss]]></link></item></channel></rss>")

    class Resp:
        def text(self):
            return xml

    class Req:
        def get(self, url, timeout):
            assert url == "https://rss.blog.naver.com/kkus_i.xml"
            return Resp()

    class Page:
        request = Req()

    assert find_post_url_by_title(Page(), "kkus_i", "초등 입학 전 한글, 어디까지 떼야 할까? | 준비") == \
        "https://blog.naver.com/kkus_i/224424354626"
    assert find_post_url_by_title(Page(), "kkus_i", "없는 제목") is None


RSS = """<?xml version="1.0" encoding="UTF-8"?><rss><channel>
<item><title><![CDATA[초등 입학 전 한글, 어디까지 떼야 할까?]]></title>
<link><![CDATA[https://blog.naver.com/kkus_i/224424354626?fromRss=true&trackingCode=rss]]></link>
<category><![CDATA[유아 발달]]></category><tag><![CDATA[유아교육,누리과정]]></tag>
<pubDate>Mon, 28 Sep 2026 05:46:00 +0900</pubDate></item>
<item><title><![CDATA[한글 활동지 &amp; 나눔]]></title>
<link>https://blog.naver.com/kkus_i/224403985633?fromRss=true</link><category>활동지</category></item>
</channel></rss>"""


def test_sync_from_rss_adds_only_missing_posts(tmp_path):
    path = tmp_path / "published.json"
    history.append(path, {"date": "2026-09-28", "title": "x", "url": "https://blog.naver.com/kkus_i/224424354626",
                          "source": "autopost"})
    assert history.sync_from_rss(path, "kkus_i", xml=RSS) == 1
    entries = history.load(path)
    assert entries[-1]["title"] == "한글 활동지 & 나눔"
    assert entries[-1]["url"] == "https://blog.naver.com/kkus_i/224403985633"
    assert entries[-1]["source"] == "rss"
    assert history.sync_from_rss(path, "kkus_i", xml=RSS) == 0
    # rss 글은 '오늘 이미 발행함' 판단에 쓰이지 않는다
    assert history.published_on(path, "2026-09-29") is None


def test_fetch_all_posts_paginates_until_total():
    import json as _json
    from urllib.parse import quote_plus
    pages = {
        1: {"postList": [{"logNo": str(100000 + i), "title": quote_plus(f"글 {i} | 제목"), "categoryNo": "3",
                          "addDate": quote_plus("2026. 9. 1.")} for i in range(30)], "totalCount": "45"},
        2: {"postList": [{"logNo": str(100030 + i), "title": quote_plus(f"글 {30 + i}"), "categoryNo": "4",
                          "addDate": "2025. 1. 1."} for i in range(15)], "totalCount": "45"},
    }
    calls = []

    def fetch(url):
        page = int(url.split("currentPage=")[1].split("&")[0])
        calls.append(page)
        # 실제 응답처럼 비표준 \' 이스케이프가 섞여 있어도 읽혀야 한다
        return _json.dumps(pages.get(page, {"postList": []}), ensure_ascii=False).replace("글 1 ", "글 1 \\'")

    posts = history.fetch_all_posts("flw3148", fetch=fetch)
    assert len(posts) == 45 and calls == [1, 2]
    assert posts[0]["url"] == "https://blog.naver.com/flw3148/100000"
    assert posts[0]["title"] == "글 0 | 제목"


def test_sync_all_adds_missing_only(tmp_path):
    import json as _json
    path = tmp_path / "published.json"
    history.append(path, {"date": "", "title": "기존", "url": "https://blog.naver.com/flw3148/100000", "source": "sheet-import"})

    def fetch(url):
        page = int(url.split("currentPage=")[1].split("&")[0])
        if page > 1:
            return _json.dumps({"postList": []})
        return _json.dumps({"postList": [{"logNo": "100000", "title": "기존"}, {"logNo": "100001", "title": "새글"}],
                            "totalCount": "2"})

    assert history.sync_all(path, "flw3148", fetch=fetch) == (1, 2)
    assert history.sync_all(path, "flw3148", fetch=fetch) == (0, 2)
