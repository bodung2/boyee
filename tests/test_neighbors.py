"""이웃 후보 추천: 가짜 네이버 응답·가짜 시트·가짜 Claude로 전체 흐름을 확인한다."""
import json
from datetime import datetime, timedelta
from email.utils import format_datetime

import pytest

from naver_autopost import generate, neighbors, sheets
from naver_autopost.config import Config
from naver_autopost.pipeline import KST, today_kst

NOW = datetime.now(KST)


def rss(name: str, blog_id: str, days_ago: list[int], titles: list[str] | None = None) -> str:
    items = "".join(
        f"<item><title><![CDATA[{(titles or [])[i] if titles and i < len(titles) else f'글 {i}'}]]></title>"
        f"<link>https://blog.naver.com/{blog_id}/22300000000{i}?fromRss=true</link>"
        f"<description><![CDATA[<p>누리과정 놀이 이야기 {i}</p>]]></description>"
        f"<pubDate>{format_datetime(NOW - timedelta(days=d))}</pubDate></item>"
        for i, d in enumerate(days_ago))
    return f"<rss><channel><title>{name}</title>{items}</channel></rss>"


BLOGS = {
    "active1": rss("놀이하는 엄마", "active1", [1, 3, 10]),
    "active2": rss("유치원 선생님 일기", "active2", [0, 2, 5, 20]),
    "stale": rss("쉬는 블로그", "stale", [40, 60]),           # 최근 7일 글 없음 → 제외
    "lonely": rss("가끔 블로그", "lonely", [2]),             # 최근 30일 글 1편 → 제외
    "listed": rss("이미 추천", "listed", [1, 2]),            # 시트에 이미 있음 → 제외
    "kkus_i": rss("내 블로그", "kkus_i", [0, 1]),            # 내 블로그 → 제외
}


def fake_fetch(url, headers=None):
    if "openapi.naver.com" in url:
        assert headers["X-Naver-Client-Id"] == "cid"
        items = [{"link": f"https://blog.naver.com/{b}/223000000001", "title": "<b>누리과정</b>", "bloggername": b}
                 for b in BLOGS]
        return json.dumps({"items": items})
    if url.startswith("https://rss.blog.naver.com/"):
        return BLOGS[url.rsplit("/", 1)[-1].removesuffix(".xml")]
    if "PostView.naver" in url:
        return '<div class="se-main-container"><p>오늘은 &quot;숫자 놀이&quot;를 했어요.</p><script>x()</script></div>'
    raise AssertionError(url)


class FakeSheet:
    def __init__(self, listed=()):
        self.tabs: dict[str, list[list]] = {}
        self.listed = list(listed)
        self.checks = []

    def ensure_tab(self, title, header, widths, input_cols=()):
        self.tabs.setdefault(title, [header] + [[""] * 2 + [u] for u in self.listed])
        return 7

    def column(self, title, col):
        return [r[2] for r in self.tabs[title][1:]]

    def append(self, title, rows):
        first = len(self.tabs[title]) + 1
        self.tabs[title] += rows
        return first, first + len(rows) - 1

    def checkboxes(self, sheet_id, col, first, last):
        self.checks.append((sheet_id, col, first, last))


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("NAVER_BLOG_ID", "kkus_i")
    monkeypatch.setenv("NAVER_SEARCH_CLIENT_ID", "cid")
    monkeypatch.setenv("NAVER_SEARCH_CLIENT_SECRET", "secret")
    c = Config.load("childhood")
    c.output_dir = tmp_path / "out"
    c.data_dir = tmp_path / "data"
    c.log_dir = tmp_path / "logs"
    c.history_file = c.data_dir / "published_childhood.json"
    c.telegram_bot_token = ""
    return c


def fake_claude(picks):
    def run(cfg, prompt, log_file):
        out = log_file.parent / "picks.json"
        cands = json.loads((log_file.parent / "candidates.json").read_text(encoding="utf-8"))
        assert {c["blog_id"] for c in cands} == {"active1", "active2"}
        out.write_text(json.dumps({"picks": picks}, ensure_ascii=False), encoding="utf-8")
    return run


def test_run_adds_picks_to_sheet(cfg, monkeypatch):
    monkeypatch.setattr(generate, "_run_claude", fake_claude([
        {"blog_id": "active2", "reason": "유치원 현장 글", "summary": "숫자 놀이 기록", "comment_idea": "놀이 순서 질문"},
        {"blog_id": "unknown", "reason": "x", "summary": "x", "comment_idea": "x"},     # 후보에 없는 아이디 → 무시
        {"blog_id": "active1", "reason": "엄마표 놀이", "summary": "s", "comment_idea": "c"},
    ]))
    sheet = FakeSheet(listed=["https://blog.naver.com/listed"])
    assert neighbors.run(cfg, sheet=sheet, fetch=fake_fetch) == 0

    rows = sheet.tabs["유아 이웃 후보"]
    assert rows[0] == neighbors.HEADER
    added = rows[2:]
    assert [r[2] for r in added] == ["https://blog.naver.com/active2", "https://blog.naver.com/active1"]
    first = added[0]
    assert first[0] == today_kst() and first[1] == "유치원 선생님 일기"
    assert first[4] == "https://blog.naver.com/active2/223000000000"   # 가장 최근 글
    assert first[6] == 4 and first[7] == "유치원 현장 글" and first[10] is False
    assert sheet.checks == [(7, neighbors.COL_VISITED, 3, 4)]

    # 같은 날 다시 실행하면 아무것도 하지 않는다
    assert neighbors.run(cfg, sheet=sheet, fetch=fake_fetch) == 0
    assert len(sheet.tabs["유아 이웃 후보"]) == 4


def test_claude_failure_falls_back_to_activity(cfg, monkeypatch):
    def boom(cfg, prompt, log_file):
        raise generate.GenerationError("down")
    monkeypatch.setattr(generate, "_run_claude", boom)
    sheet = FakeSheet(listed=["https://blog.naver.com/listed"])
    assert neighbors.run(cfg, sheet=sheet, fetch=fake_fetch) == 0
    added = sheet.tabs["유아 이웃 후보"][2:]
    assert [r[2].rsplit("/", 1)[-1] for r in added] == ["active2", "active1"]   # 최근 30일 글 많은 순
    assert "AI 요약 실패" in added[0][7]


def test_no_candidates_writes_nothing(cfg, monkeypatch):
    monkeypatch.setattr(generate, "_run_claude", fake_claude([]))
    sheet = FakeSheet(listed=["https://blog.naver.com/active1", "https://blog.naver.com/active2", "https://blog.naver.com/listed"])
    assert neighbors.run(cfg, sheet=sheet, fetch=fake_fetch) == 0
    assert len(sheet.tabs["유아 이웃 후보"]) == 4 and sheet.checks == []


def test_search_web_extracts_blog_posts():
    page = ('<a href="https://blog.naver.com/abc_12/223456789012">x</a>'
            '<a href="https://blog.naver.com/PostView.naver?blogId=def&amp;logNo=223456789013">y</a>'
            '<a href="https://blog.naver.com/abc_12/223456789012">dup</a>'
            '<a href="https://blog.naver.com/PostList/223456789014">no</a>')
    hits = neighbors.search_web("누리과정", fetch=lambda url, h: page)
    assert [(h["blog_id"], h["log_no"]) for h in hits] == [("abc_12", "223456789012"), ("def", "223456789013")]


def test_pick_queries_mixes_tags_and_is_stable():
    hist = [{"tags": ["#한글놀이", "4세"]}, {"tags": ["숫자 감각"]}]
    q1 = neighbors.pick_queries(["누리과정", "유아 발달", "엄마표 놀이", "유아 독서", "한글 떼기"], hist, "2026-10-05")
    q2 = neighbors.pick_queries(["누리과정", "유아 발달", "엄마표 놀이", "유아 독서", "한글 떼기"], hist, "2026-10-05")
    assert q1 == q2 and len(q1) == 6 and len(set(q1)) == 6
    assert {"한글놀이", "숫자 감각"} & set(q1)


def test_sheet_creates_tab_and_parses_append_range():
    calls = []

    def request(method, url, body=None):
        calls.append((method, url, body))
        if method == "GET" and "fields=" in url:
            return {"sheets": [{"properties": {"sheetId": 0, "title": "콘텐츠 마스터"}}]}
        if url.endswith(":batchUpdate") and body["requests"][0].get("addSheet"):
            return {"replies": [{"addSheet": {"properties": {"sheetId": 99}}}]}
        if ":append" in url:
            return {"updates": {"updatedRange": "'유아 이웃 후보'!A5:L9"}}
        return {}

    sheet = sheets.Sheet("sid", "tok", request=request)
    assert sheet.ensure_tab("유아 이웃 후보", ["a", "b"], [10, 20], input_cols=(1,)) == 99
    fmt = calls[2][2]["requests"]
    assert fmt[0]["updateCells"]["rows"][0]["values"][1]["userEnteredFormat"]["backgroundColor"]["blue"] == 0.6
    assert sheet.append("유아 이웃 후보", [["x"]]) == (5, 9)
    assert "valueInputOption=RAW" in calls[-1][1]
