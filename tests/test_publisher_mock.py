"""가짜 에디터 페이지로 발행 흐름(제목·붙여넣기·이미지·태그·발행·URL 확인)을 점검한다.

실제 네이버 화면은 로그인이 필요해 테스트할 수 없으므로, 셀렉터 구조만 흉내 낸 페이지를 쓴다.
"""
import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

from naver_autopost import images, publisher  # noqa: E402
from naver_autopost.config import Config  # noqa: E402
from tests.sample_post import make_post  # noqa: E402

MOCK = r"""<!doctype html><meta charset="utf-8"><body>
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
  const h = e.clipboardData.getData('text/html');
  if (h.includes('data-input-buffer')) {           // 실제 에디터처럼: 내부 복사 표식이면 저장소의 문서 데이터로
    const data = JSON.parse(localStorage.getItem('se3#SE_COPIED_DATA'));
    data.copyData.forEach(c => {
      const d = document.createElement('div');
      d.className = 'se-component se-' + c.ctype + ' se-l-' + (c.layout || 'default');
      if (c.ctype === 'text') {
        d.innerHTML = c.value.map(p => '<p class="se-text-paragraph" contenteditable="true">' +
          p.nodes.map(n => n.value).join('') + '</p>').join('');
      } else { d.textContent = c.ctype + ':' + JSON.stringify(c).length; }
      content.appendChild(d);
    });
  } else {
    textComp(h);
  }
});
document.addEventListener('keydown', e => {             // 주소만 있는 줄에서 Enter → 링크 카드
  if (e.key !== 'Enter') return;
  const p = document.activeElement && document.activeElement.closest && document.activeElement.closest('.se-text-paragraph');
  if (p && /^https?:\/\/\S+$/.test(p.textContent.trim())) {
    const d = document.createElement('div'); d.className = 'se-component se-oglink';
    d.tabIndex = 0; d.textContent = 'CARD:' + p.textContent.trim(); content.appendChild(d);
  }
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
    cfg.style_mode = "plain"
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


def test_native_style_publish_on_mock_editor(tmp_path, monkeypatch):
    """네이티브 서식: 요약표·인용구 챕터·포스트잇·링크 카드가 순서대로 들어가는지."""
    cfg = Config.load()
    cfg.blog_id = "testblog"
    cfg.category = ""
    cfg.headless = True
    cfg.browser_channel = ""
    cfg.log_dir = tmp_path / "logs"
    cfg.style_mode = "native"
    post = make_post()
    post["body_html"] = (
        "<ol><li>요약 하나</li><li>요약 둘</li><li>요약 셋</li></ol><p>도입</p>"
        "<h2>1. 무엇이 다른가요?</h2><p>본문</p><p>[[IMAGE:card]]</p>"
        "<table><tr><th>구분</th><th>핵심</th></tr><tr><td>가</td><td>나</td></tr></table>"
        '<div data-block="oneline"><p>한 줄 결론입니다.</p></div>'
        '<div data-block="related"><p>「관련 글」 — 이유</p><p>https://blog.naver.com/testblog/1</p></div>'
    )
    imgs = {
        "thumbnail": images.make_thumbnail(post["thumbnail"], tmp_path / "thumb.png"),
        "card": images.make_card(post["card"], tmp_path / "card.png"),
    }
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
        diag = tmp_path / "diag"
        url = publisher._publish(page, cfg, post, imgs, dry_run=False, diag_dir=diag)
        browser.close()
    assert url.endswith("/223456789")
    import json
    kinds = [c["class"] for c in json.loads((diag / "components.json").read_text(encoding="utf-8"))]
    joined = " | ".join(kinds)
    order = ["se-table", "se-l-quotation_line", "se-image", "se-table", "se-l-quotation_postit", "se-oglink"]
    pos = -1
    for k in order:
        nxt = next((i for i, c in enumerate(kinds) if k in c and i > pos), None)
        assert nxt is not None, f"{k} not found after {pos}: {joined}"
        pos = nxt


# 실제 에디터(diagnostics/style/editor_dom.html)의 사진 컴포넌트·도구 모음 구조를 흉내 낸다.
IMAGE_MOCK = r"""<!doctype html><meta charset="utf-8"><body>
<div class="se-content" id="content">
  <div class="se-component se-image se-l-default"><div class="se-component-content se-component-content-fit">
    <div class="se-section se-section-image se-l-default se-section-align-left">
      <img class="se-image-resource" width="886" src="data:image/gif;base64,R0lGODlhAQABAAAAACw=" style="width:886px;height:40px">
      <ul class="se-toolbar se-context-toolbar se-context-toolbar-image" style="display:none">
        <li><button class="se-context-toolbar-group-toggle-button" data-name="content-mode-without-pagefull"
             data-value="fit" onclick="document.getElementById('modes').style.display='block'">문서 너비</button></li>
        <li id="modes" style="display:none">
          <button class="se-context-toolbar-group-toggle-button" data-name="content-mode-without-pagefull"
             data-value="normal" onclick="document.querySelector('.se-image-resource').setAttribute('width','600')">작게</button>
        </li>
      </ul>
    </div></div></div>
  <div class="se-component se-text"><p class="se-text-paragraph" contenteditable="true"></p></div>
</div>
<button class="se-align-left-toolbar-button" data-name="align-drop-down-with-justify"
  onclick="document.getElementById('aligns').style.display='block'">정렬</button>
<div id="aligns" style="display:none">
  <button data-value="center" onclick="const s=document.querySelector('.se-section-image');
    s.classList.remove('se-section-align-left'); s.classList.add('se-section-align-center')">가운데</button>
</div>
<script>
document.querySelector('.se-image-resource').addEventListener('click',
  () => document.querySelector('.se-context-toolbar-image').style.display = 'block');
</script>"""


def test_thumbnail_is_made_small_and_centered(tmp_path):
    cfg = Config.load()
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:
            pytest.skip(f"Chromium 없음: {e}")
        page = browser.new_page()
        page.set_content(IMAGE_MOCK)
        ed = publisher._Editor(page, cfg)
        assert ed.center_small_image(600) is True
        assert "se-section-align-center" in page.locator(".se-section-image").get_attribute("class")
        assert page.locator(".se-image-resource").get_attribute("width") == "600"
        browser.close()
