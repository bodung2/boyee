"""Playwright로 네이버 스마트에디터 ONE을 조작해 글을 발행한다.

네이버에는 공식 글쓰기 API가 없어서, 집 PC에 저장한 로그인 세션(브라우저 프로필)으로
사람처럼 에디터를 조작한다. 에디터 화면이 바뀌면 SELECTORS만 고치면 된다.
"""
from __future__ import annotations

import logging
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import BrowserContext, Frame, Locator, Page, sync_playwright

from .config import Config
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

POST_URL = re.compile(r"blog\.naver\.com/(?:PostView\.naver\?.*logNo=(\d+)|[^/?#]+/(\d+))")


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

    def paste_html(self, fragment: str) -> None:
        plain = html_to_text(fragment)
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


def publish(cfg: Config, post: dict, images: dict[str, Path], dry_run: bool = False) -> str:
    """글을 발행하고 발행된 글 URL을 돌려준다. dry_run이면 발행 버튼 직전에 멈춘다."""
    if not cfg.blog_id:
        raise PublishError(".env에 NAVER_BLOG_ID가 없습니다")
    with sync_playwright() as p:
        ctx = _launch(p, cfg, headless=cfg.headless)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            return _publish(page, cfg, post, images, dry_run)
        except Exception:
            _shot(page, cfg, "publish-error")
            raise
        finally:
            ctx.close()


def _publish(page: Page, cfg: Config, post: dict, images: dict[str, Path], dry_run: bool) -> str:
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
    for kind, value in split_segments(post["body_html"]):
        if kind == "html":
            ed.paste_html(value)
            ed.move_to_end()
        else:
            ed.upload_image(images[value])

    _shot(page, cfg, "before-publish")
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
    raise PublishUncertain("발행 버튼은 눌렀지만 글 주소를 확인하지 못했습니다. 블로그에서 직접 확인하세요.")
