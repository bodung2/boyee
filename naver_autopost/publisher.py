"""Playwright로 네이버 스마트에디터 ONE을 조작해 글을 발행한다.

네이버에는 공식 글쓰기 API가 없어서, 집 PC에 저장한 로그인 세션(브라우저 프로필)으로
사람처럼 에디터를 조작한다. 에디터 화면이 바뀌면 SELECTORS만 고치면 된다.
"""
from __future__ import annotations

import html
import json
import logging
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import BrowserContext, Frame, Locator, Page, sync_playwright

from .config import Config
from . import se_markup
from .content import html_to_text, split_segments

log = logging.getLogger(__name__)

MOD = "Meta" if sys.platform == "darwin" else "Control"

# 여러 후보를 순서대로 시도한다. 네이버가 클래스명을 바꾸면 여기에 새 후보를 추가한다.
SELECTORS = {
    "draft_popup_cancel": [".se-popup-button-cancel"],
    "help_close": [".se-help-panel-close-button", "button.se-help-close-button"],
    "title": [".se-documentTitle .se-text-paragraph", ".se-section-documentTitle .se-text-paragraph"],
    "body": [".se-component.se-text .se-text-paragraph", ".se-content .se-text-paragraph"],
    "image_button": ["button.se-image-toolbar-button", "button[data-name='image']", "button[data-log='dot.img']"],
    "image_component": [".se-component.se-image"],
    "publish_open": ["button[class*='publish_btn']", "button:has-text('발행')"],
    "tag_input": ["input#tag-input", "input[placeholder*='태그']"],
    "category_open": ["button[class*='selectbox_button']", "button[aria-label*='카테고리']"],
    "publish_confirm": ["button[data-testid='seOnePublishBtn']", "button[class*='confirm_btn']"],
}

POST_URL = re.compile(r"blog\.naver\.com/(?:[^\s\"']*?[?&]logNo=(\d{6,})|(?!PostWriteForm|PostUpdateForm)[^/?#]+/(\d{6,}))")


class PublishError(RuntimeError):
    pass


class SessionExpired(PublishError):
    pass


class PublishUncertain(PublishError):
    """발행 버튼을 누른 뒤의 실패. 중복 발행 위험이 있어 재시도하지 않는다."""


def _launch(p, cfg: Config, headless: bool) -> BrowserContext:
    cfg.profile_dir.mkdir(parents=True, exist_ok=True)
    kwargs = dict(
        user_data_dir=str(cfg.profile_dir),
        headless=headless,
        locale="ko-KR",
        timezone_id="Asia/Seoul",
        viewport={"width": 1400, "height": 1000},
        permissions=["clipboard-read", "clipboard-write"],
    )
    if cfg.browser_channel:
        try:
            return p.chromium.launch_persistent_context(channel=cfg.browser_channel, **kwargs)
        except Exception as e:  # 크롬 미설치 등 → Playwright 내장 Chromium으로
            log.warning("브라우저 채널 '%s' 실행 실패(%s). 내장 Chromium을 씁니다.", cfg.browser_channel, e)
    return p.chromium.launch_persistent_context(**kwargs)


def _logged_in(ctx: BrowserContext) -> bool:
    return any(c["name"] == "NID_AUT" for c in ctx.cookies("https://naver.com"))


def login(cfg: Config, wait_minutes: int = 5) -> None:
    """최초 1회: 브라우저 창에서 직접 로그인하면 세션이 프로필에 저장된다."""
    with sync_playwright() as p:
        ctx = _launch(p, cfg, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://nid.naver.com/nidlogin.login")
        print("열린 브라우저에서 네이버에 로그인하세요. ('로그인 상태 유지'를 꼭 체크하세요)")
        deadline = time.time() + wait_minutes * 60
        while time.time() < deadline and not _logged_in(ctx):
            time.sleep(2)
        if not _logged_in(ctx):
            ctx.close()
            raise SessionExpired(f"{wait_minutes}분 안에 로그인이 확인되지 않았습니다")
        time.sleep(3)
        ctx.close()
    # '로그인 상태 유지'를 안 하면 창을 닫는 순간 로그인이 사라진다 → 다시 열어서 남아 있는지 확인
    if not check_session(cfg):
        raise SessionExpired("로그인은 됐지만 창을 닫자 풀렸습니다. 다시 실행해서 '로그인 상태 유지'를 꼭 체크하고 로그인하세요.")
    print("로그인 확인. 창을 다시 열어도 로그인이 유지됩니다.")


def check_session(cfg: Config) -> bool:
    """저장된 브라우저 프로필에 네이버 로그인이 살아 있고 글쓰기 화면이 열리는지 확인한다(약 10초)."""
    with sync_playwright() as p:
        ctx = _launch(p, cfg, headless=cfg.headless)
        try:
            if not _logged_in(ctx):
                return False
            if not cfg.blog_id:
                return True
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(f"https://blog.naver.com/{cfg.blog_id}?Redirect=Write&", wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            return "nid.naver.com" not in page.url
        finally:
            ctx.close()


class _Editor:
    def __init__(self, page: Page, cfg: Config):
        self.page = page
        self.cfg = cfg

    @property
    def scopes(self) -> list[Page | Frame]:
        frame = self.page.frame(name="mainFrame")
        return [frame, self.page] if frame else [self.page]

    def find(self, key: str, timeout: float = 10_000, visible_only: bool = True) -> Locator:
        deadline = time.time() + timeout / 1000
        while True:
            for scope in self.scopes:
                for sel in SELECTORS[key]:
                    loc = scope.locator(sel)
                    try:
                        if loc.count() and (not visible_only or loc.first.is_visible()):
                            return loc
                    except Exception:
                        continue
            if time.time() > deadline:
                raise PublishError(f"화면 요소를 찾지 못했습니다: {key} {SELECTORS[key]}")
            time.sleep(0.5)

    def try_click(self, key: str, timeout: float = 3_000) -> bool:
        try:
            self.find(key, timeout).first.click()
            return True
        except PublishError:
            return False

    def paste_html(self, fragment: str, plain: str | None = None) -> None:
        plain = html_to_text(fragment) if plain is None else plain
        self.page.evaluate(
            """async ([h, t]) => {
                const item = new ClipboardItem({
                    'text/html': new Blob([h], {type: 'text/html'}),
                    'text/plain': new Blob([t], {type: 'text/plain'}),
                });
                await navigator.clipboard.write([item]);
            }""",
            [fragment, plain],
        )
        self.page.keyboard.press(f"{MOD}+V")
        self.page.wait_for_timeout(1500)

    def paste_native(self, components: list[dict]) -> None:
        """에디터 고유 방식으로 붙여넣는다: 문서 데이터(JSON)를 에디터의 복사 저장소에 넣고
        '내부 복사' 표식을 붙여넣으면, 에디터가 저장소의 JSON으로 인용구·표·글자 크기를 그대로 만든다."""
        data = se_markup.copied_data(components)
        for scope in self.scopes:
            scope.evaluate("([k, v]) => localStorage.setItem(k, v)", [se_markup.STORAGE_KEY, data])
        ua = self.page.evaluate("navigator.userAgent")
        self.paste_html(se_markup.clipboard_html(ua), plain=se_markup.plain_text(components))
        self.page.wait_for_timeout(1000)

    def insert_oglink(self, url: str) -> None:
        """빈 줄에 주소를 입력하고 Enter → 네이버가 링크 카드를 만든다."""
        scope = self.scopes[0]
        before = scope.locator(".se-component.se-oglink").count()
        self.move_to_end()
        self.page.keyboard.press("Enter")
        self.page.keyboard.insert_text(url)
        self.page.keyboard.press("Enter")
        deadline = time.time() + 12
        while scope.locator(".se-component.se-oglink").count() <= before and time.time() < deadline:
            time.sleep(0.5)
        if scope.locator(".se-component.se-oglink").count() <= before:
            log.warning("링크 카드가 만들어지지 않았습니다(주소만 남습니다): %s", url)
        self.page.wait_for_timeout(500)
        self.move_to_end()

    def move_to_end(self) -> None:
        """마지막 컴포넌트 뒤로 커서를 옮긴다(이미지 뒤에는 빈 문단을 만든다)."""
        scope = self.scopes[0]
        last = scope.locator(".se-component").last
        classes = last.get_attribute("class") or ""
        if "se-text" in classes:
            last.locator(".se-text-paragraph").last.click()
            self.page.keyboard.press("End")
        else:
            last.click()
            self.page.keyboard.press("ArrowRight")
            self.page.keyboard.press("Enter")
        self.page.wait_for_timeout(300)

    def upload_image(self, path: Path) -> None:
        before = self.scopes[0].locator(SELECTORS["image_component"][0]).count()
        with self.page.expect_file_chooser(timeout=15_000) as fc:
            self.find("image_button").first.click()
        fc.value.set_files(str(path))
        deadline = time.time() + 60
        while self.scopes[0].locator(SELECTORS["image_component"][0]).count() <= before:
            if time.time() > deadline:
                raise PublishError(f"이미지 업로드가 끝나지 않았습니다: {path.name}")
            time.sleep(1)
        self.page.wait_for_timeout(1500)
        self.move_to_end()


def _shot(page: Page, cfg: Config, name: str) -> None:
    try:
        cfg.log_dir.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(cfg.log_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{name}.png"), full_page=True)
    except Exception:
        pass


def publish(cfg: Config, post: dict, images: dict[str, Path], dry_run: bool = False,
            diag_dir: Path | None = None) -> str:
    """글을 발행하고 발행된 글 URL을 돌려준다. dry_run이면 발행 버튼 직전에 멈춘다."""
    if not cfg.blog_id:
        raise PublishError(".env에 NAVER_BLOG_ID가 없습니다")
    with sync_playwright() as p:
        ctx = _launch(p, cfg, headless=cfg.headless)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            return _publish(page, cfg, post, images, dry_run, diag_dir)
        except Exception:
            _shot(page, cfg, "publish-error")
            raise
        finally:
            ctx.close()


def _dump_editor(page: Page, ed: "_Editor", out_dir: Path) -> None:
    """미리보기 진단: 에디터에 실제로 만들어진 컴포넌트 종류와 전체 화면을 남긴다."""
    out_dir.mkdir(parents=True, exist_ok=True)
    comps = ed.scopes[0].locator(".se-component")
    rows = []
    for i in range(comps.count()):
        c = comps.nth(i)
        cls = c.get_attribute("class") or ""
        inner = c.inner_html()
        rows.append({
            "class": cls,
            "font_sizes": sorted(set(re.findall(r"se-fs\d+", inner))),
            "fonts": sorted(set(re.findall(r"se-ff-[\w-]+", inner))),
            "aligns": sorted(set(re.findall(r"se-text-paragraph-align-(\w+)", inner))),
            "line_heights": sorted(set(re.findall(r"line-height: ([\d.]+)", inner))),
            "backgrounds": sorted(set(re.findall(r"background-color: (rgb\([^)]*\))", inner)))[:4],
            "bold": "<b>" in inner,
            "lists": "se-text-list" in inner,
            "text": c.inner_text()[:80],
        })
    (out_dir / "components.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    page.screenshot(path=str(out_dir / "editor_full.png"), full_page=True)


def _publish(page: Page, cfg: Config, post: dict, images: dict[str, Path], dry_run: bool,
             diag_dir: Path | None = None) -> str:
    page.goto(f"https://blog.naver.com/{cfg.blog_id}?Redirect=Write&", wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    if "nid.naver.com" in page.url:
        raise SessionExpired("네이버 로그인이 풀렸습니다. `python -m naver_autopost login`으로 다시 로그인하세요.")

    ed = _Editor(page, cfg)
    ed.find("title", timeout=30_000)
    ed.try_click("draft_popup_cancel")   # "작성 중인 글이 있습니다" → 새로 쓰기
    ed.try_click("help_close")

    ed.find("title").first.click()
    page.keyboard.insert_text(post["title"])

    ed.find("body").last.click()
    ed.upload_image(images["thumbnail"])
    if cfg.style_mode == "native":
        # SR 기존 글과 같은 서식(인용구 챕터·요약표·16pt 본문·포스트잇 한 줄 요약·링크 카드)
        for kind, value in se_markup.to_segments(post["body_html"]):
            if kind == "se":
                ed.paste_native(value)
                ed.move_to_end()
            elif kind == "oglink":
                ed.insert_oglink(value)
            elif value in images:
                ed.upload_image(images[value])
    else:
        for kind, value in split_segments(post["body_html"]):
            if kind == "html":
                ed.paste_html(value)
                ed.move_to_end()
            else:
                ed.upload_image(images[value])

    _shot(page, cfg, "before-publish")
    if diag_dir:
        _dump_editor(page, ed, diag_dir)
    if dry_run:
        log.info("dry-run: 발행 직전에 멈췄습니다. 브라우저 창을 확인하세요(60초 후 닫힘).")
        page.wait_for_timeout(60_000)
        return ""

    ed.find("publish_open").first.click()
    page.wait_for_timeout(1500)

    if cfg.category:
        if ed.try_click("category_open"):
            page.wait_for_timeout(700)
            picked = False
            for scope in ed.scopes:
                opt = scope.locator(f"label:has-text('{cfg.category}'), span:text-is('{cfg.category}')")
                if opt.count():
                    opt.first.click()
                    picked = True
                    break
            if not picked:
                log.warning("카테고리 '%s'를 찾지 못해 기본 카테고리로 발행합니다.", cfg.category)
        else:
            log.warning("카테고리 선택 버튼을 찾지 못해 기본 카테고리로 발행합니다.")

    try:
        tag_input = ed.find("tag_input", timeout=5_000).first
        for tag in post.get("tags", [])[:30]:
            tag_input.click()
            page.keyboard.insert_text(tag)
            page.keyboard.press("Enter")
            page.wait_for_timeout(150)
    except PublishError:
        log.warning("태그 입력칸을 찾지 못해 태그 없이 발행합니다.")

    ed.find("publish_confirm").first.click()
    # 여기부터는 이미 발행됐을 수 있으므로, 실패해도 절대 재시도하지 않는다(중복 발행 방지).
    deadline = time.time() + 60
    while time.time() < deadline:
        for url in [page.url] + [f.url for f in page.frames]:
            m = POST_URL.search(url)
            if m:
                return f"https://blog.naver.com/{cfg.blog_id}/{m.group(1) or m.group(2)}"
        time.sleep(1)
    _shot(page, cfg, "after-publish")
    # 화면 주소로 못 찾으면 블로그 RSS에서 방금 올린 글을 제목으로 찾는다.
    for _ in range(6):
        url = find_post_url_by_title(page, cfg.blog_id, post["title"])
        if url:
            log.info("RSS에서 발행된 글 주소를 찾았습니다: %s", url)
            return url
        time.sleep(10)
    raise PublishUncertain("발행 버튼은 눌렀지만 글 주소를 확인하지 못했습니다. 블로그에서 직접 확인하세요.")


def _norm_title(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", html.unescape(text or "")).lower()


def find_post_url_by_title(page: Page, blog_id: str, title: str) -> str | None:
    """blog RSS(https://rss.blog.naver.com/<id>.xml)에서 제목이 같은 최근 글의 주소를 찾는다."""
    try:
        resp = page.request.get(f"https://rss.blog.naver.com/{blog_id}.xml", timeout=20_000)
        xml = resp.text()
    except Exception as e:
        log.warning("RSS 조회 실패: %s", e)
        return None
    want = _norm_title(title)
    for item in re.findall(r"<item>(.*?)</item>", xml, flags=re.S)[:10]:
        t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", item, flags=re.S)
        link = re.search(r"<link>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</link>", item, flags=re.S)
        if t and link and _norm_title(t.group(1)) == want:
            m = POST_URL.search(link.group(1))
            if m:
                return f"https://blog.naver.com/{blog_id}/{m.group(1) or m.group(2)}"
    return None


# ---------------------------------------------------------------- 디자인 캡처(진단용)

_POST_URL_PARTS = re.compile(r"blog\.naver\.com/(?:PostView\.naver\?blogId=([^&]+)&logNo=(\d+)|([^/?#]+)/(\d+))")


def capture_style(cfg: Config, post_url: str, out_dir: Path) -> list[Path]:
    """기존 글의 디자인 구조를 떠서 파일로 남긴다. 글은 수정·저장하지 않는다.

    1) 발행된 화면의 본문 HTML(se-main-container)  2) 수정 화면(에디터)의 컴포넌트 DOM
    3) 에디터에서 전체 선택·복사했을 때의 클립보드 HTML(에디터 고유 형식)  4) 스크린샷
    """
    m = _POST_URL_PARTS.search(post_url)
    if not m:
        raise PublishError(f"네이버 글 주소를 알아보지 못했습니다: {post_url}")
    blog_id, log_no = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []

    def save(name: str, text: str) -> None:
        path = out_dir / name
        path.write_text(text or "", encoding="utf-8")
        saved.append(path)

    with sync_playwright() as p:
        ctx = _launch(p, cfg, headless=cfg.headless)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("dialog", lambda d: d.accept())          # '페이지를 나가시겠습니까?' → 저장하지 않고 나감
        try:
            page.goto(f"https://blog.naver.com/PostView.naver?blogId={blog_id}&logNo={log_no}",
                      wait_until="domcontentloaded")
            page.wait_for_timeout(4000)
            view = page.locator(".se-main-container")
            save("view.html", view.first.inner_html() if view.count() else page.content())
            page.screenshot(path=str(out_dir / "view.png"), full_page=True)
            saved.append(out_dir / "view.png")

            page.goto(f"https://blog.naver.com/PostUpdateForm.naver?blogId={blog_id}&logNo={log_no}",
                      wait_until="domcontentloaded")
            page.wait_for_timeout(6000)
            if "nid.naver.com" in page.url:
                raise SessionExpired("네이버 로그인이 풀려 있습니다")
            ed = _Editor(page, cfg)
            ed.try_click("draft_popup_cancel")
            ed.try_click("help_close")
            scope = ed.scopes[0]
            wrap = scope.locator(".se-components-wrap, .se-content").first
            save("editor_dom.html", wrap.inner_html() if wrap.count() else scope.content())
            page.screenshot(path=str(out_dir / "editor.png"), full_page=True)
            saved.append(out_dir / "editor.png")

            # 본문 첫 문단을 클릭하고 전체 선택 → 복사 → 클립보드에 담긴 에디터 고유 HTML을 읽는다.
            try:
                scope.locator(".se-component.se-text .se-text-paragraph").first.click()
                page.keyboard.press(f"{MOD}+A")
                page.keyboard.press(f"{MOD}+C")
                page.wait_for_timeout(1000)
                clip = page.evaluate("""async () => {
                    const out = {};
                    for (const item of await navigator.clipboard.read()) {
                        for (const type of item.types) {
                            if (type.startsWith('text/') || type.includes('html') || type.includes('json'))
                                out[type] = await (await item.getType(type)).text();
                        }
                    }
                    return out;
                }""")
                for kind, text in (clip or {}).items():
                    save("clipboard_" + re.sub(r"[^a-z0-9]+", "_", kind.lower()) + ".txt", text)
            except Exception as e:
                save("clipboard_error.txt", repr(e))
        finally:
            page.goto("about:blank")                       # 저장 버튼은 누르지 않는다
            ctx.close()
    return saved


# ---------------------------------------------------------------- 서식 실험(진단용, 발행하지 않음)

_COMPONENT_SPLIT = re.compile(r'(?=<div[^>]*class="se-component )')


def _sample_components(html: str) -> dict[str, str]:
    """캡처한 글에서 종류별 첫 컴포넌트 HTML을 뽑는다(표는 요약표·비교표 두 개)."""
    parts = [p for p in _COMPONENT_SPLIT.split(html) if p.startswith("<div")]
    found: dict[str, str] = {}
    tables = 0
    for part in parts:
        head = part[:200]
        if "se-l-quotation_line" in head:
            found.setdefault("quote_line", part)
        elif "se-l-quotation_postit" in head:
            found.setdefault("quote_postit", part)
        elif "se-table" in head:
            tables += 1
            found.setdefault("table_summary" if tables == 1 else "table_compare", part)
        elif "se-text" in head and "se-fs16" in part:
            found.setdefault("text16", part)
        elif "se-horizontalLine" in head:
            found.setdefault("hr", part)
    return found


PLAIN_SAMPLES = {
    "plain_blockquote": "<blockquote><p><b>1. 테스트 챕터 제목</b></p></blockquote>",
    "plain_styled_text": '<p style="font-size:16pt;line-height:1.8">본문 16pt 줄간격 1.8 테스트 문장입니다.</p>',
    "plain_table_styled": (
        '<table style="border-collapse:collapse" border="1"><tr>'
        '<td style="background-color:#fafafa;text-align:center"><b>구분</b></td>'
        '<td style="background-color:#fafafa;text-align:center"><b>핵심</b></td></tr>'
        '<tr><td style="text-align:center">가</td><td style="text-align:center">나</td></tr></table>'),
}


def style_lab(cfg: Config, sample_dir: Path, out_dir: Path, link_url: str) -> dict:
    """새 글쓰기 화면에서 서식을 넣는 여러 방법을 시험하고, 결과로 생긴 에디터 구조를 기록한다.
    발행·저장 버튼은 누르지 않는다(네이버 자동 임시저장이 남을 수는 있다)."""
    samples: dict[str, str] = {}
    for name, fname in (("editor", "editor_dom.html"), ("view", "view.html")):
        path = sample_dir / fname
        if path.exists():
            for kind, html in _sample_components(path.read_text(encoding="utf-8")).items():
                samples[f"paste_{name}_{kind}"] = html
    samples.update({f"paste_{k}": v for k, v in PLAIN_SAMPLES.items()})
    out_dir.mkdir(parents=True, exist_ok=True)
    results: dict = {"experiments": {}}

    with sync_playwright() as p:
        ctx = _launch(p, cfg, headless=cfg.headless)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("dialog", lambda d: d.accept())
        try:
            page.goto(f"https://blog.naver.com/{cfg.blog_id}?Redirect=Write&", wait_until="domcontentloaded")
            page.wait_for_timeout(5000)
            if "nid.naver.com" in page.url:
                raise SessionExpired("네이버 로그인이 풀려 있습니다")
            ed = _Editor(page, cfg)
            ed.find("title", timeout=30_000)
            ed.try_click("draft_popup_cancel")
            ed.try_click("help_close")
            ed.find("title").first.click()
            page.keyboard.insert_text("서식 실험(발행 안 함)")
            ed.find("body").last.click()
            scope = ed.scopes[0]

            def new_components(before: int) -> list[str]:
                comps = scope.locator(".se-component")
                return [comps.nth(i).evaluate("e => e.outerHTML")[:6000] for i in range(before, comps.count())]

            for name, html in samples.items():
                try:
                    ed.move_to_end()
                    before = scope.locator(".se-component").count()
                    ed.paste_html(html)
                    page.wait_for_timeout(1200)
                    made = new_components(before)
                    results["experiments"][name] = {
                        "ok": True,
                        "classes": [re.search(r'class="([^"]*)"', m).group(1) if re.search(r'class="([^"]*)"', m) else "" for m in made],
                        "html": made,
                    }
                except Exception as e:
                    results["experiments"][name] = {"ok": False, "error": repr(e)[:500]}

            # 링크 카드: 주소를 치고 Enter
            try:
                ed.move_to_end()
                before = scope.locator(".se-component").count()
                page.keyboard.press("Enter")
                page.keyboard.insert_text(link_url)
                page.keyboard.press("Enter")
                page.wait_for_timeout(6000)
                made = new_components(before)
                results["experiments"]["type_url_enter"] = {
                    "ok": True, "classes": [re.search(r'class="([^"]*)"', m).group(1) for m in made], "html": made}
            except Exception as e:
                results["experiments"]["type_url_enter"] = {"ok": False, "error": repr(e)[:500]}

            # 툴바 구조(인용구·글자크기·줄간격 버튼 위치 파악용)
            for label, sel in (("toolbar", ".se-toolbar, .se-header, header"), ("property_toolbar", ".se-property-toolbar")):
                try:
                    loc = scope.locator(sel)
                    results[label] = loc.first.evaluate("e => e.outerHTML")[:60000] if loc.count() else ""
                except Exception as e:
                    results[label] = repr(e)
            page.screenshot(path=str(out_dir / "lab.png"), full_page=True)
        finally:
            page.goto("about:blank")
            ctx.close()
    (out_dir / "lab.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return results


def _read_clipboard_all(page: Page) -> dict:
    """클립보드의 모든 형식(에디터 고유의 'web ...' 형식 포함)을 읽는다."""
    return page.evaluate("""async () => {
        const out = {};
        try {
            for (const item of await navigator.clipboard.read({unsanitized: ['text/html']})) {
                for (const type of item.types) {
                    try { out[type] = (await (await item.getType(type)).text()).slice(0, 300000); }
                    catch (e) { out[type] = 'ERR ' + e; }
                }
            }
        } catch (e) { out.__error = String(e); }
        return out;
    }""")


def style_lab2(cfg: Config, post_url: str, out_dir: Path) -> dict:
    """2차 서식 실험: (1) 에디터 고유 복사 형식 캡처 (2) 인용구·글자크기·줄간격 메뉴 구조
    (3) 인용구 버튼으로 넣고 빠져나오는 동작. 발행·저장하지 않는다."""
    m = _POST_URL_PARTS.search(post_url)
    blog_id, log_no = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
    out_dir.mkdir(parents=True, exist_ok=True)
    res: dict = {}

    def layer_html(scope) -> str:
        loc = scope.locator(".se-popup, .se-toolbar-layer, .se-layer, [class*='option-layer'], [class*='-layer']")
        htmls = []
        for i in range(min(loc.count(), 30)):
            try:
                if loc.nth(i).is_visible():
                    htmls.append(loc.nth(i).evaluate("e => e.outerHTML")[:20000])
            except Exception:
                pass
        return "\n\n".join(htmls)

    with sync_playwright() as p:
        ctx = _launch(p, cfg, headless=cfg.headless)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("dialog", lambda d: d.accept())
        try:
            # (1) 기존 글 수정 화면에서 복사 형식 캡처 — 전체, 인용구 하나, 표 하나
            page.goto(f"https://blog.naver.com/PostUpdateForm.naver?blogId={blog_id}&logNo={log_no}",
                      wait_until="domcontentloaded")
            page.wait_for_timeout(6000)
            ed = _Editor(page, cfg)
            ed.try_click("draft_popup_cancel")
            ed.try_click("help_close")
            scope = ed.scopes[0]
            for name, sel in (("quote_line", ".se-component.se-l-quotation_line"),
                              ("quote_postit", ".se-component.se-l-quotation_postit"),
                              ("table", ".se-component.se-table"),
                              ("text", ".se-component.se-text")):
                try:
                    comp = scope.locator(sel).first
                    comp.locator(".se-text-paragraph").first.click(timeout=8000)
                    page.keyboard.press(f"{MOD}+A")
                    page.keyboard.press(f"{MOD}+C")
                    page.wait_for_timeout(800)
                    res[f"clip_{name}_ctrlA"] = _read_clipboard_all(page)
                except Exception as e:
                    res[f"clip_{name}_ctrlA"] = {"__error": repr(e)[:300]}
            # 컴포넌트 자체를 선택(가장자리 클릭)해서 복사
            try:
                comp = scope.locator(".se-component.se-l-quotation_line").first
                box = comp.bounding_box(timeout=8000)
                page.mouse.click(box["x"] + 3, box["y"] + box["height"] / 2)
                page.keyboard.press(f"{MOD}+C")
                page.wait_for_timeout(800)
                res["clip_quote_line_component"] = _read_clipboard_all(page)
            except Exception as e:
                res["clip_quote_line_component"] = {"__error": repr(e)[:300]}
            page.goto("about:blank")

            # (2)(3) 새 글쓰기 화면에서 메뉴 구조와 인용구 삽입 동작
            page.goto(f"https://blog.naver.com/{cfg.blog_id}?Redirect=Write&", wait_until="domcontentloaded")
            page.wait_for_timeout(5000)
            ed = _Editor(page, cfg)
            ed.find("title", timeout=30_000)
            ed.try_click("draft_popup_cancel")
            ed.try_click("help_close")
            ed.find("title").first.click(timeout=8000)
            page.keyboard.insert_text("서식 실험2(발행 안 함)")
            ed.find("body").last.click()
            page.keyboard.insert_text("첫 문단")
            scope = ed.scopes[0]
            for name, sel in (("quote_options", ".se-insert-quotation-default-toolbar-button + .se-document-toolbar-select-option-button"),
                              ("font_size_options", ".se-font-size-code-toolbar-button"),
                              ("line_height_options", ".se-line-height-toolbar-button"),
                              ("font_family_options", ".se-font-family-toolbar-button")):
                try:
                    scope.locator(sel).first.click(timeout=8000)
                    page.wait_for_timeout(800)
                    res[name] = layer_html(scope)
                    page.screenshot(path=str(out_dir / f"{name}.png"))
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(300)
                except Exception as e:
                    res[name] = "ERR " + repr(e)[:300]

            def comps() -> list[str]:
                c = scope.locator(".se-component")
                return [c.nth(i).evaluate("e => e.outerHTML")[:3000] for i in range(c.count())]

            try:
                ed.find("body").last.click()
                page.keyboard.press("End")
                scope.locator(".se-insert-quotation-default-toolbar-button").first.click(timeout=8000)
                page.wait_for_timeout(1000)
                page.keyboard.insert_text("인용구 안 글자")
                res["after_quote_insert"] = comps()
                page.keyboard.press("ArrowDown")
                page.keyboard.press("ArrowDown")
                page.keyboard.insert_text("아래로 빠져나온 뒤 글자")
                res["after_arrowdown"] = comps()
                page.screenshot(path=str(out_dir / "quote_flow.png"), full_page=True)
            except Exception as e:
                res["quote_flow_error"] = repr(e)[:500]
        finally:
            page.goto("about:blank")
            ctx.close()
    (out_dir / "lab2.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


_DUMP_STORAGE_JS = """() => {
    const dump = (s) => { const o = {}; try { for (let i = 0; i < s.length; i++) { const k = s.key(i); o[k] = s.getItem(k); } } catch (e) { o.__error = String(e); } return o; };
    return {origin: location.origin, local: dump(localStorage), session: dump(sessionStorage)};
}"""


def _storage_snapshot(page: Page) -> list[dict]:
    snaps = []
    for frame in page.frames:
        try:
            snap = frame.evaluate(_DUMP_STORAGE_JS)
            snap["frame"] = frame.name or frame.url[:80]
            snaps.append(snap)
        except Exception:
            pass
    return snaps


def _storage_diff(before: list[dict], after: list[dict]) -> list[dict]:
    diffs = []
    for a in after:
        b = next((x for x in before if x.get("frame") == a.get("frame")), {"local": {}, "session": {}})
        for area in ("local", "session"):
            for k, v in (a.get(area) or {}).items():
                if (b.get(area) or {}).get(k) != v:
                    diffs.append({"frame": a.get("frame"), "origin": a.get("origin"), "area": area,
                                  "key": k, "len": len(v or ""), "value": (v or "")[:200000]})
    return diffs


def style_lab3(cfg: Config, post_url: str, out_dir: Path) -> dict:
    """3차 실험: 에디터가 복사할 때 내용을 어디(브라우저 저장소)에 두는지 찾는다. 저장·발행하지 않는다."""
    m = _POST_URL_PARTS.search(post_url)
    blog_id, log_no = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
    out_dir.mkdir(parents=True, exist_ok=True)
    res: dict = {}
    with sync_playwright() as p:
        ctx = _launch(p, cfg, headless=cfg.headless)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("dialog", lambda d: d.accept())
        try:
            page.goto(f"https://blog.naver.com/PostUpdateForm.naver?blogId={blog_id}&logNo={log_no}",
                      wait_until="domcontentloaded")
            page.wait_for_timeout(6000)
            ed = _Editor(page, cfg)
            ed.try_click("draft_popup_cancel")
            ed.try_click("help_close")
            scope = ed.scopes[0]
            res["window_keys"] = scope.evaluate(
                "() => Object.keys(window).filter(k => /se|editor|smart|clip|buffer/i.test(k)).slice(0, 200)")
            for name, sel in (("postit", ".se-component.se-l-quotation_postit"),
                              ("table", ".se-component.se-table"),
                              ("quote_line", ".se-component.se-l-quotation_line")):
                try:
                    before = _storage_snapshot(page)
                    comp = scope.locator(sel).first
                    comp.scroll_into_view_if_needed(timeout=8000)
                    box = comp.bounding_box(timeout=8000)
                    page.mouse.click(box["x"] + 3, box["y"] + box["height"] / 2)
                    page.keyboard.press(f"{MOD}+C")
                    page.wait_for_timeout(1500)
                    res[f"copy_{name}"] = {"diff": _storage_diff(before, _storage_snapshot(page)),
                                           "clipboard": _read_clipboard_all(page)}
                except Exception as e:
                    res[f"copy_{name}"] = {"error": repr(e)[:400]}
            res["storage_after"] = [{"frame": s.get("frame"), "origin": s.get("origin"),
                                     "local_keys": {k: len(v or "") for k, v in (s.get("local") or {}).items()},
                                     "session_keys": {k: len(v or "") for k, v in (s.get("session") or {}).items()}}
                                    for s in _storage_snapshot(page)]
        finally:
            page.goto("about:blank")
            ctx.close()
    (out_dir / "lab3.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res
