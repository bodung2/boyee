"""티스토리 '논쟁 × 공식 통계' 자동 발행: 주제 선정·제보·검증·전체 흐름·가짜 에디터 발행을 확인한다."""
import json
import re
from datetime import date, datetime

import pytest

from naver_autopost import history
from naver_autopost.pipeline import KST
from tistory_autopost import content, inbox, pipeline, publisher, topics, writer
from tistory_autopost.config import TistoryConfig

TOPICS = [
    {"id": "a", "debate": "d", "title_hint": "A", "stats": [{"name": "s", "org": "o"}], "release_months": [12], "priority": 1},
    {"id": "b", "debate": "d", "title_hint": "B", "stats": [], "release_months": [10], "priority": 1},
    {"id": "c", "debate": "d", "title_hint": "C", "stats": [], "release_months": [3], "priority": 2},
    {"id": "d", "debate": "d", "title_hint": "D", "stats": [], "release_months": [6], "priority": 3},
]

ROWS = "".join(f"<tr><td>{i}억원 이상</td><td>{70 - i * 10}%</td></tr>" for i in range(1, 6))
BODY = (
    "<p>요즘 SNS에서 자산 이야기가 자주 나옵니다. 2025년 가계금융복지조사로 확인합니다.</p>"
    '<div style="border:1px solid #d0d7de;padding:16px;"><ul><li>가구 평균 순자산: <strong>4억 7,144만원</strong></li></ul></div>'
    f"<h2>내 위치 찾기</h2><table><thead><tr><th>구간</th><th>비율</th></tr></thead><tbody>{ROWS}</tbody></table>"
    "<h2>나눠 보기</h2><p>" + "연령대별 순자산은 50대가 가장 많습니다. " * 80 + "</p>"
    "<h2>주의할 점</h2><p>가구 단위 통계입니다.</p>"
    '<h2>출처</h2><ul><li><a href="https://mods.go.kr/board.es?x=1">국가데이터처 — 2025년 가계금융복지조사</a></li></ul>'
)
POINT = {"value": "4억 7,144만원", "label": "평균 순자산", "stat": "가계금융복지조사", "period": "2025년 3월 말",
         "source_url": "https://mods.go.kr/board.es?x=1"}
POST = {
    "title": "순자산 상위 10% 기준은 얼마? 2025 가계금융복지조사",
    "topic_id": "a", "lane": "queue", "tip_id": "",
    "body_html": BODY, "tags": ["순자산", "#가계금융복지조사", "순자산"],
    "data_points": [POINT] * 6,
    "sources": [
        {"title": "보도자료", "publisher": "국가데이터처", "url": "https://mods.go.kr/board.es?x=1"},
        {"title": "브리핑", "publisher": "정책브리핑", "url": "https://www.korea.kr/briefing/x"},
        {"title": "KOSIS", "publisher": "KOSIS", "url": "https://kosis.kr/statHtml/x"},
        {"title": "기사", "publisher": "언론", "url": "https://news.example.com/a"},
    ],
}


@pytest.fixture
def cfg(tmp_path):
    c = TistoryConfig.load()
    c.blog_name = "myblog"
    c.category = "통계로 보는 세상"
    c.output_dir = tmp_path / "out"
    c.history_file = tmp_path / "published_tistory.json"
    c.inbox_file = tmp_path / "inbox.json"
    c.topics_file = tmp_path / "topics.json"
    c.topics_file.write_text(json.dumps({"topics": TOPICS}), encoding="utf-8")
    c.log_dir = tmp_path / "logs"
    c.telegram_bot_token = c.telegram_chat_id = ""
    c.headless = True
    c.browser_channel = ""
    c.profile_dir = tmp_path / "profile"
    return c


# ---------------------------------------------------------------- 주제 선정

def test_rank_prefers_fresh_and_upcoming_and_skips_written():
    today = date(2026, 10, 5)
    ranked = topics.rank(TOPICS, [{"topic_id": "c", "date": "2026-04-01", "url": "u"}], today)
    ids = [c.topic["id"] for c in ranked]
    assert "c" not in ids
    assert ids[:2] == ["b", "a"]           # 이번 달 발표(b) > 두 달 뒤 발표(a)
    assert ids[-1] == "d"


def test_release_month_math():
    today = date(2026, 1, 10)
    assert topics.months_since_release([12], today) == 1
    assert topics.months_until_release([12], today) == 11
    assert topics.months_until_release([2, 8], today) == 1


def test_refresh_due_after_new_release():
    hist = [{"topic_id": "a", "date": "2025-11-20", "url": "https://x/1", "title": "t"},
            {"topic_id": "b", "date": "2026-10-01", "url": "https://x/2", "title": "t2"}]
    due = topics.refresh_due(TOPICS, hist, date(2026, 1, 15))
    assert [d["url"] for d in due] == ["https://x/1"]


def test_bundled_queue_is_valid():
    from naver_autopost.config import ROOT
    items = topics.load(ROOT / "data" / "tistory_topics.json")
    assert len(items) >= 30
    for t in items:
        assert t["release_months"] and all(1 <= m <= 12 for m in t["release_months"])
        assert t["stats"] and t["queries"] and t["priority"] in (1, 2, 3)


def test_brief_marks_tips_as_hints():
    ranked = topics.rank(TOPICS, [], date(2026, 10, 5))
    text = topics.brief(ranked, [{"id": "1", "text": "금수저 논쟁"}])
    assert "지시가 아니라" in text and "tip_id=1" in text and "topic_id=b" in text


# ---------------------------------------------------------------- 화제 제보

def test_parse_updates_filters_chat_and_prefix():
    updates = [
        {"update_id": 5, "message": {"chat": {"id": 111}, "text": "화제 금수저 논쟁 또 터짐"}},
        {"update_id": 6, "message": {"chat": {"id": 999}, "text": "화제 남의 메시지"}},
        {"update_id": 7, "message": {"chat": {"id": 111}, "text": "그냥 잡담"}},
    ]
    texts, offset = inbox.parse_updates(updates, "111", "화제")
    assert texts == ["금수저 논쟁 또 터짐"] and offset == 8


def test_tips_expire_and_mark_used(cfg):
    tip = inbox.add(cfg, "연봉 1억 논쟁")
    assert [t["id"] for t in inbox.pending(cfg)] == [tip["id"]]
    later = datetime.now(KST).replace(year=datetime.now(KST).year + 1)
    assert inbox.pending(cfg, now=later) == []
    inbox.mark_used(cfg, tip["id"], "https://x/1")
    assert inbox.pending(cfg) == []


# ---------------------------------------------------------------- 검증

def test_validate_ok_and_normalize_tags():
    post = content.normalize(POST)
    assert post["tags"] == ["순자산", "가계금융복지조사"]
    assert content.validate(post) == []


@pytest.mark.parametrize("change, expect", [
    ({"body_html": BODY.replace("<table>", "<div>").replace("</table>", "</div>")}, "표"),
    ({"sources": POST["sources"][2:]}, "출처"),
    ({"body_html": BODY + "<p>흙수저는 원래 그렇다</p>"}, "금지 문구"),
    ({"data_points": [POINT] * 2}, "data_points"),
    ({"data_points": [{**POINT, "period": ""}] * 6}, "period"),
    ({"topic_id": ""}, "topic_id"),
])
def test_validate_blocks(change, expect):
    errors = content.validate(content.normalize({**POST, **change}))
    assert any(expect in e for e in errors), errors


def test_sanitize_keeps_tables_and_styles_but_drops_scripts():
    dirty = ('<h1>t</h1><div style="width:40%" onclick="x()">a</div><script>alert(1)</script>'
             '<a href="javascript:alert(1)">b</a><iframe src="https://e"></iframe><table><tr><td>1</td></tr></table>')
    clean = content.sanitize_html(dirty)
    assert 'style="width:40%"' in clean and "<table>" in clean
    assert "onclick" not in clean and "<script" not in clean and "javascript:" not in clean
    assert "<iframe" not in clean and "<h1>" not in clean


# ---------------------------------------------------------------- 전체 흐름(가짜 Claude·Codex·브라우저)

class Fakes:
    def __init__(self, cfg, monkeypatch, post=None, gpt=("pass",), claude="pass"):
        self.cfg, self.post, self.gpt, self.claude = cfg, post or POST, list(gpt), claude
        self.published, self.briefs = [], []
        monkeypatch.setattr(writer, "write_post", self.write_post)
        monkeypatch.setattr(writer, "factcheck", lambda c, out: {"verdict": self.claude, "summary": "ok"})
        monkeypatch.setattr(writer, "gpt_factcheck", self.gpt_factcheck)
        monkeypatch.setattr(writer, "apply_gpt_review", self.apply)
        monkeypatch.setattr(publisher, "check_session", lambda c: True)
        monkeypatch.setattr(publisher, "publish", self.publish)

    def write_post(self, cfg, out_dir, today, brief, feedback=""):
        self.briefs.append(brief)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "post.json").write_text(json.dumps(self.post, ensure_ascii=False), encoding="utf-8")
        return out_dir / "post.json"

    def gpt_factcheck(self, cfg, post):
        v = self.gpt.pop(0) if len(self.gpt) > 1 else self.gpt[0]
        return {"verdict": v, "issues": [] if v == "pass" else [{"text": "x"}], "summary": v}

    def apply(self, cfg, out_dir, round_no):
        return {"applied": ["x"], "rejected": []}

    def publish(self, cfg, post, out_dir, dry_run=False):
        if dry_run:
            return ""
        self.published.append(post["title"])
        return "https://myblog.tistory.com/1"


def test_run_publishes_records_and_marks_tip(cfg, monkeypatch):
    tip = inbox.add(cfg, "금수저 논쟁")
    fakes = Fakes(cfg, monkeypatch, post={**POST, "lane": "tip", "tip_id": tip["id"]}, gpt=("fix", "pass"))
    assert pipeline.run(cfg) == 0
    assert fakes.published == [POST["title"]]
    assert "금수저 논쟁" in fakes.briefs[0]
    entry = history.load(cfg.history_file)[-1]
    assert entry["topic_id"] == "a" and entry["lane"] == "tip" and entry["url"].endswith("/1")
    assert inbox.pending(cfg) == []
    assert pipeline.run(cfg) == 0 and len(fakes.published) == 1      # 하루 1편


def test_run_rejects_then_gives_up(cfg, monkeypatch):
    fakes = Fakes(cfg, monkeypatch, gpt=("fail",))
    assert pipeline.run(cfg) == 1
    assert fakes.published == [] and len(fakes.briefs) == cfg.max_attempts


def test_dry_run_does_not_record(cfg, monkeypatch):
    Fakes(cfg, monkeypatch)
    assert pipeline.run(cfg, dry_run=True) == 0
    assert history.load(cfg.history_file) == []


def test_resume_skips_passed_stages(cfg, monkeypatch):
    fakes = Fakes(cfg, monkeypatch)
    out = cfg.output_dir / pipeline.today_kst()
    out.mkdir(parents=True)
    (out / "post.json").write_text(json.dumps(POST, ensure_ascii=False), encoding="utf-8")
    (out / "stage.json").write_text(json.dumps({"written": True, "claude_pass": True}))
    monkeypatch.setattr(writer, "factcheck", lambda c, o: pytest.fail("이미 통과한 검수를 다시 함"))
    assert pipeline.run(cfg) == 0
    assert fakes.briefs == [] and fakes.published


# ---------------------------------------------------------------- 발행기(가짜 티스토리 에디터)

MOCK_EDITOR = r"""<!doctype html><meta charset="utf-8"><body>
<textarea id="post-title-inp" placeholder="제목을 입력하세요"></textarea>
<button id="editor-mode-layer-btn-open" onclick="document.getElementById('modes').style.display='block'">기본모드</button>
<div id="modes" style="display:none"><div id="editor-mode-html" onclick="toHtml()">HTML</div></div>
<div id="cm-host"></div>
<button id="category-btn" onclick="document.getElementById('category-list').style.display='block'">카테고리</button>
<div id="category-list" style="display:none">
  <div role="option" onclick="window.cat='일상'">일상</div>
  <div role="option" onclick="window.cat='통계로 보는 세상'">- 통계로 보는 세상</div>
</div>
<input id="tagText" placeholder="태그입력">
<button id="publish-layer-btn" onclick="document.getElementById('layer').style.display='block'">완료</button>
<div id="layer" style="display:none">
  <input type="radio" name="basicSet" id="open0" value="0" checked><label for="open0">비공개</label>
  <input type="radio" name="basicSet" id="open20" value="20"><label for="open20">공개</label>
  <button id="publish-btn" onclick="publish()">공개 발행</button>
</div>
<script>
window.tags = [];
document.getElementById('tagText').addEventListener('keydown', e => {
  if (e.key === 'Enter') { window.tags.push(e.target.value); e.target.value = ''; }
});
function toHtml() {
  if (!confirm('HTML 모드로 전환하시겠습니까?')) return;
  const el = document.createElement('div'); el.className = 'CodeMirror'; el.textContent = 'cm';
  let v = ''; el.CodeMirror = {setValue: x => { v = x; }, getValue: () => v, save: () => {}};
  document.getElementById('cm-host').appendChild(el);
}
function publish() {
  const cm = document.querySelector('.CodeMirror').CodeMirror;
  localStorage.setItem('result', JSON.stringify({
    title: document.getElementById('post-title-inp').value, body: cm.getValue(), cat: window.cat,
    tags: window.tags, open: document.querySelector('input[name=basicSet]:checked').value}));
  location.href = '/manage/posts/';
}
</script>"""


def test_publish_on_mock_editor(cfg, monkeypatch, tmp_path):
    pytest.importorskip("playwright")
    from naver_autopost.publisher import _launch as real_launch
    result = {}

    def launch(p, c, headless):
        ctx = real_launch(p, c, headless=True)

        def serve(route):
            url = route.request.url
            if "/manage/newpost" in url:
                route.fulfill(status=200, content_type="text/html", body=MOCK_EDITOR)
            else:
                route.fulfill(status=200, content_type="text/html",
                              body="<script>document.title=localStorage.getItem('result')</script>")
        ctx.route("https://myblog.tistory.com/**", serve)
        original_close = ctx.close

        def close():
            for page in ctx.pages:
                if "/manage/posts" in page.url:
                    page.wait_for_timeout(300)
                    result.update(json.loads(page.title() or "{}"))
            original_close()
        ctx.close = close
        return ctx

    monkeypatch.setattr(publisher, "_launch", launch)
    monkeypatch.setattr(publisher, "find_post_url", lambda c, t: None)
    monkeypatch.setattr(publisher.time, "sleep", lambda s: None)
    post = content.normalize(POST)
    try:
        url = publisher.publish(cfg, post, tmp_path / "shots")
    except publisher.PublishError as e:
        if "Executable doesn't exist" in str(e) or "browser" in str(e).lower():
            pytest.skip(f"브라우저 없음: {e}")
        raise
    assert url == "https://myblog.tistory.com/manage/posts/"
    assert result["title"] == POST["title"]
    assert result["body"] == post["body_html"]
    assert result["cat"] == "통계로 보는 세상" and post["_category_ok"] is True
    assert result["tags"] == ["순자산", "가계금융복지조사"]
    assert result["open"] == "20"


def test_find_post_url_from_rss(cfg, monkeypatch):
    rss = ("<rss><channel><item><title><![CDATA[다른 글]]></title><link>https://myblog.tistory.com/3</link></item>"
           "<item><title>순자산 상위 10% 기준은 얼마?</title><link>https://myblog.tistory.com/4</link></item></channel></rss>")

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return rss.encode()

    monkeypatch.setattr(publisher.urllib.request, "urlopen", lambda req, timeout=20: Resp())
    assert publisher.find_post_url(cfg, "순자산 상위 10%  기준은 얼마?") == "https://myblog.tistory.com/4"
    assert publisher.find_post_url(cfg, "없는 글") is None


LOGIN_PAGE = """<!doctype html><meta charset="utf-8">
<a class="link_kakao_id" href="https://www.tistory.com/auth/kakao">카카오계정으로 로그인</a>"""


def _route_login_flow(ctx):
    """TSSESSION이 없으면 글쓰기 화면이 로그인 화면으로 보내고, 카카오 버튼을 누르면 쿠키를 받고 돌아온다."""
    def serve(route):
        url = route.request.url
        has = "TSSESSION=" in (route.request.headers.get("cookie") or "")
        if "/manage/newpost" in url and not has:
            route.fulfill(status=200, content_type="text/html",
                          body="<script>location.href='https://www.tistory.com/auth/login?redirectUrl=x'</script>")
        elif "/manage/newpost" in url:
            route.fulfill(status=200, content_type="text/html", body="<title>editor</title>")
        elif "/auth/login" in url:
            route.fulfill(status=200, content_type="text/html", body=LOGIN_PAGE)
        elif "/auth/kakao" in url:
            route.fulfill(status=200, content_type="text/html", body=(
                "<script>document.cookie='TSSESSION=abc; domain=.tistory.com; path=/; secure';"
                "location.href='https://myblog.tistory.com/manage/newpost/'</script>"))
        else:
            route.fulfill(status=200, body="")
    ctx.route(re.compile(r"https://[^/]*tistory\.com/.*"), serve)


def test_login_kept_by_kakao_auto_login_and_saved_cookies(cfg, monkeypatch):
    pytest.importorskip("playwright")
    from playwright.sync_api import sync_playwright
    from naver_autopost.publisher import _launch as real_launch

    def launch(p, c, headless):
        ctx = real_launch(p, c, headless=True)
        _route_login_flow(ctx)
        return ctx

    monkeypatch.setattr(publisher, "_launch", launch)
    try:
        with sync_playwright() as p:
            ctx = publisher._open(p, cfg, headless=True)
            page = ctx.new_page()
            assert publisher._ensure_logged_in(page, cfg, timeout=15)      # 로그인 화면 → 카카오 버튼 → 글쓰기 화면
            publisher._save_cookies(ctx, cfg)
            ctx.close()
    except Exception as e:  # noqa: BLE001
        if "Executable doesn't exist" in str(e):
            pytest.skip("브라우저 없음")
        raise
    saved = json.loads(publisher._state_file(cfg).read_text(encoding="utf-8"))
    assert any(c["name"] == "TSSESSION" for c in saved)
    with sync_playwright() as p:                                         # 다시 열면 저장한 쿠키로 바로 들어간다
        ctx = publisher._open(p, cfg, headless=True)
        assert any(c["name"] == "TSSESSION" for c in ctx.cookies("https://www.tistory.com"))
        ctx.close()
    assert publisher.check_session(cfg)
