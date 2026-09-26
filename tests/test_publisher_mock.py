"""가짜 에디터 페이지로 발행 흐름(제목·붙여넣기·이미지·태그·발행·URL 확인)을 점검한다.

실제 네이버 화면은 로그인이 필요해 테스트할 수 없으므로, 셀렉터 구조만 흉내 낸 페이지를 쓴다.
"""
import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

from naver_autopost import images, publisher  # noqa: E402
from naver_autopost.config import Config  # noqa: E402
from tests.sample_post import make_post  # noqa: E402

MOCK = """<!doctype html><meta charset="utf-8"><body>
<div class="se-documentTitle"><p class="se-text-paragraph" contenteditable="true"></p></div>
<div class="se-content" id="content">
  <div class="se-component se-text"><p class="se-text-paragraph" contenteditable="true"></p></div>
</div>
<button class="se-image-toolbar-button" onclick="document.getElementById('f').click()">사진</button>
<input type="file" id="f" style="display:none">
<button class="publish_btn__x" onclick="document.getElementById('layer').style.display='block'">발행</button>
<div id="layer" style="display:none">
  <input id="tag-input" placeholder="태그 입력"><div id="tags"></div>
  <button data-testid="seOnePublishBtn" onclick="location.href='/testblog/223456789'">발행</button>
</div>
<script>
const content = document.getElementById('content');
function textComp(html) {
  const d = document.createElement('div'); d.className = 'se-component se-text';
  d.innerHTML = '<div class="se-text-paragraph" contenteditable="true">' + html + '</div>';
  content.appendChild(d);
}
document.addEventListener('paste', e => {
  e.preventDefault();
  textComp(e.clipboardData.getData('text/html'));
});
document.getElementById('f').addEventListener('change', e => {
  setTimeout(() => {
    const d = document.createElement('div'); d.className = 'se-component se-image';
    d.tabIndex = 0; d.textContent = 'IMG:' + e.target.files[0].name; content.appendChild(d);
    e.target.value = '';
  }, 200);
});
document.getElementById('tag-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') { document.getElementById('tags').textContent += '#' + e.target.value; e.target.value = ''; }
});
</script>"""


def test_publish_flow_on_mock_editor(tmp_path, monkeypatch):
    cfg = Config.load()
    cfg.blog_id = "testblog"
    cfg.category = ""
    cfg.headless = True
    cfg.browser_channel = ""
    cfg.log_dir = tmp_path / "logs"
    post = make_post()
    imgs = {
        "thumbnail": images.make_thumbnail(post["thumbnail"], tmp_path / "thumb.png"),
        "card": images.make_card(post["card"], tmp_path / "card.png"),
    }
    seen = {}

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:
            pytest.skip(f"Chromium 없음: {e}")
        ctx = browser.new_context(permissions=["clipboard-read", "clipboard-write"])
        ctx.route("https://blog.naver.com/testblog?Redirect=Write&",
                  lambda r: r.fulfill(body=MOCK, content_type="text/html; charset=utf-8"))
        ctx.route("https://blog.naver.com/testblog/223456789",
                  lambda r: r.fulfill(body="<p>ok</p>", content_type="text/html"))
        page = ctx.new_page()

        orig_find = publisher._Editor.find

        def spy_find(self, key, *a, **kw):
            if key == "publish_confirm":
                seen["title"] = page.locator(".se-documentTitle").inner_text()
                seen["content"] = page.locator("#content").inner_text()
                seen["tags"] = page.locator("#tags").inner_text()
            return orig_find(self, key, *a, **kw)

        monkeypatch.setattr(publisher._Editor, "find", spy_find)
        url = publisher._publish(page, cfg, post, imgs, dry_run=False)
        browser.close()

    assert url == "https://blog.naver.com/testblog/223456789"
    assert seen["title"] == post["title"]
    content = seen["content"]
    assert content.index("IMG:thumb.png") < content.index("무엇이 바뀌나요") < content.index("IMG:card.png") \
        < content.index("언제부터인가요")
    assert seen["tags"] == "#" + "#".join(post["tags"])
