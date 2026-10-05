"""Playwright로 티스토리 글쓰기 화면을 조작해 글을 발행한다.

티스토리 Open API는 2024년 2월에 종료되어, 네이버와 같이 집 PC에 저장한 로그인 세션(브라우저 프로필)으로
사람처럼 에디터를 조작한다. 본문은 에디터의 HTML 모드에 통째로 넣는다(표·막대그래프 스타일 유지).
화면이 바뀌어 실패하면 `python -m tistory_autopost diagnose`로 화면 구조를 저장해 SELECTORS를 고친다.
"""
from __future__ import annotations

import html
import json
import logging
import re
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Locator, Page, sync_playwright

from naver_autopost.publisher import _launch

from .config import TistoryConfig

log = logging.getLogger(__name__)

# 여러 후보를 순서대로 시도한다. 티스토리가 화면을 바꾸면 여기에 새 후보를 추가한다.
SELECTORS = {
    "title": ["#post-title-inp", "textarea[placeholder*='제목']", "input[placeholder*='제목']"],
    "mode_open": ["#editor-mode-layer-btn-open", "button:has-text('기본모드')", "button:has-text('마크다운')"],
    "mode_html": ["#editor-mode-html", "#editor-mode-html-text", "[id*='editor-mode-html']", "text=HTML"],
    "codemirror": [".CodeMirror"],
    "category_open": ["#category-btn", "button:has-text('카테고리')"],
    "category_item": ["#category-list [role='option']", "#category-list .mce-menu-item", "[class*='category'] [role='option']"],
    "tag_input": ["#tagText", "input[placeholder*='태그']"],
    "publish_open": ["#publish-layer-btn", "button:has-text('완료')"],
    "visibility_public": ["#open20", "input[name='basicSet'][value='20']", "label[for='open20']"],
    "publish_confirm": ["#publish-btn", "button:has-text('공개 발행')", "button:has-text('발행')"],
}


class PublishError(RuntimeError):
    pass


class SessionExpired(PublishError):
    pass


class PublishUncertain(PublishError):
    """발행 버튼을 누른 뒤의 실패. 중복 발행 위험이 있어 재시도하지 않는다."""


def _newpost_url(cfg: TistoryConfig) -> str:
    return f"{cfg.blog_url}/manage/newpost/"


def _on_login_page(url: str) -> bool:
    return "/auth/login" in url or "accounts.kakao.com" in url or "logins.daum.net" in url


def login(cfg: TistoryConfig, wait_minutes: int = 5) -> None:
    """최초 1회: 열린 창에서 카카오 계정으로 직접 로그인하면 세션이 프로필에 저장된다."""
    with sync_playwright() as p:
        ctx = _launch(p, cfg, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://www.tistory.com/auth/login")
        print("열린 브라우저에서 티스토리(카카오 계정)에 로그인하세요. '로그인 상태 유지'를 체크하세요.")
        deadline = time.time() + wait_minutes * 60
        ok = False
        while time.time() < deadline:
            time.sleep(3)
            if any(c["name"] == "TSSESSION" for c in ctx.cookies("https://www.tistory.com")):
                ok = True
                break
        time.sleep(2)
        ctx.close()
    if not ok:
        raise SessionExpired(f"{wait_minutes}분 안에 로그인이 확인되지 않았습니다")
    if not check_session(cfg):
        raise SessionExpired("로그인은 됐지만 글쓰기 화면이 열리지 않습니다. 블로그 주소(TISTORY_BLOG)와 "
                             "'로그인 상태 유지' 체크를 확인하세요.")
    print("로그인 확인. 창을 다시 열어도 로그인이 유지됩니다.")


def check_session(cfg: TistoryConfig) -> bool:
    """저장된 프로필로 글쓰기 화면이 열리는지 확인한다(약 10초)."""
    with sync_playwright() as p:
        ctx = _launch(p, cfg, headless=cfg.headless)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.on("dialog", lambda d: d.dismiss())
            page.goto(_newpost_url(cfg), wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            return not _on_login_page(page.url) and "/manage" in page.url
        finally:
            ctx.close()


def _find(page: Page, key: str, timeout: float = 10_000) -> Locator:
    deadline = time.time() + timeout / 1000
    while True:
        for sel in SELECTORS[key]:
            loc = page.locator(sel)
            try:
                if loc.count() and loc.first.is_visible():
                    return loc.first
            except Exception:  # noqa: BLE001 - 화면 전환 중이면 다시 찾는다
                pass
        if time.time() > deadline:
            raise PublishError(f"화면에서 '{key}'를 찾지 못했습니다(후보: {SELECTORS[key]})")
        page.wait_for_timeout(300)


def _maybe(page: Page, key: str, timeout: float = 3_000) -> Locator | None:
    try:
        return _find(page, key, timeout)
    except PublishError:
        return None


def _on_dialog(dialog) -> None:
    """'작성 중인 글을 이어서 쓸까요?'는 거절(새로 쓴다), HTML 모드 전환 확인 등은 수락한다."""
    message = dialog.message or ""
    log.info("대화상자: %s", message[:80])
    if "이어서" in message or "저장된 글" in message or "임시저장" in message:
        dialog.dismiss()
    else:
        dialog.accept()


def _switch_to_html(page: Page) -> None:
    if page.locator(".CodeMirror").count():
        return
    _find(page, "mode_open").click()
    page.wait_for_timeout(500)
    _find(page, "mode_html").click()
    page.wait_for_timeout(1500)
    _find(page, "codemirror", timeout=10_000)


def _set_body(page: Page, body_html: str) -> None:
    ok = page.evaluate(
        """(html) => {
            const el = document.querySelector('.CodeMirror');
            if (!el || !el.CodeMirror) return false;
            el.CodeMirror.setValue(html);
            if (el.CodeMirror.save) el.CodeMirror.save();
            return el.CodeMirror.getValue().length;
        }""",
        body_html,
    )
    if not ok:
        raise PublishError("HTML 편집기(CodeMirror)에 본문을 넣지 못했습니다")
    log.info("본문 입력(HTML %d자)", ok)


def _select_category(page: Page, name: str) -> bool:
    if not name:
        return True
    opener = _maybe(page, "category_open")
    if not opener:
        log.warning("카테고리 버튼을 찾지 못했습니다")
        return False
    opener.click()
    page.wait_for_timeout(500)
    for sel in SELECTORS["category_item"]:
        items = page.locator(sel)
        for i in range(items.count()):
            item = items.nth(i)
            label = re.sub(r"\s+", " ", item.inner_text()).strip().lstrip("-").strip()
            if label == name:
                item.click()
                log.info("카테고리 선택: %s", name)
                return True
    page.keyboard.press("Escape")
    log.warning("카테고리 '%s'를 찾지 못해 카테고리 없이 올립니다", name)
    return False


def _add_tags(page: Page, tags: list[str]) -> None:
    box = _maybe(page, "tag_input")
    if not box:
        log.warning("태그 입력칸을 찾지 못해 태그 없이 올립니다")
        return
    for tag in tags:
        box.click()
        box.fill(tag)
        box.press("Enter")
        page.wait_for_timeout(150)


def _shot(page: Page, out_dir: Path, name: str) -> None:
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out_dir / f"{name}.png"), full_page=True)
    except Exception as e:  # noqa: BLE001
        log.warning("스크린샷 실패: %s", e)


def _norm_title(text: str) -> str:
    return re.sub(r"\s+", "", html.unescape(text or ""))


def find_post_url(cfg: TistoryConfig, title: str) -> str | None:
    """블로그 RSS에서 같은 제목의 글 주소를 찾는다(발행 확인·중복 발행 방지)."""
    try:
        req = urllib.request.Request(f"{cfg.blog_url}/rss", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            xml = resp.read().decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        log.warning("RSS를 읽지 못했습니다: %s", e)
        return None
    want = _norm_title(title)
    for item in re.findall(r"<item>(.*?)</item>", xml, flags=re.S):
        t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", item, flags=re.S)
        link = re.search(r"<link>(.*?)</link>", item, flags=re.S)
        if t and link and _norm_title(t.group(1)) == want:
            return link.group(1).strip()
    return None


def _fill_editor(cfg: TistoryConfig, page: Page, post: dict, out_dir: Path) -> Locator:
    """제목·본문·카테고리·태그를 넣고 발행 창에서 '공개'를 고른 뒤, 마지막 발행 버튼을 돌려준다."""
    try:
        page.goto(_newpost_url(cfg), wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        if _on_login_page(page.url):
            raise SessionExpired("티스토리 로그인이 풀려 있습니다. `python -m tistory_autopost login`으로 다시 로그인하세요.")
        _find(page, "title", timeout=20_000)
        _switch_to_html(page)
        _set_body(page, post["body_html"])
        title_box = _find(page, "title")
        title_box.click()
        title_box.fill(post["title"])
        post["_category_ok"] = _select_category(page, cfg.category)
        _add_tags(page, post.get("tags", []))
        _shot(page, out_dir, "editor_filled")

        _find(page, "publish_open").click()
        page.wait_for_timeout(1200)
        public = _maybe(page, "visibility_public", timeout=5_000)
        if public:
            public.click()
        else:
            log.warning("'공개' 선택 버튼을 찾지 못했습니다(블로그 기본 공개 설정으로 발행)")
        _shot(page, out_dir, "publish_layer")
        return _find(page, "publish_confirm")
    except PublishError:
        _shot(page, out_dir, "publish_error")
        raise
    except Exception as e:
        _shot(page, out_dir, "publish_error")
        raise PublishError(str(e)) from e


def publish(cfg: TistoryConfig, post: dict, out_dir: Path, dry_run: bool = False) -> str:
    """글을 발행하고 주소를 돌려준다. dry_run이면 마지막 '공개 발행' 직전에 멈춘다."""
    if not dry_run:
        same = find_post_url(cfg, post["title"])
        if same:
            log.warning("같은 제목의 글이 이미 블로그에 있어 새로 올리지 않습니다: %s", same)
            return same
    with sync_playwright() as p:
        ctx = _launch(p, cfg, headless=cfg.headless)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.on("dialog", _on_dialog)
            confirm = _fill_editor(cfg, page, post, out_dir)
            if dry_run:
                log.info("테스트 실행: 공개 발행 직전에 멈춥니다. 스크린샷: %s", out_dir)
                page.wait_for_timeout(5000 if cfg.headless else 20_000)
                return ""
            try:
                confirm.click()
                page.wait_for_url(lambda u: "/manage/newpost" not in u, timeout=30_000)
                page.wait_for_timeout(2000)
            except Exception as e:
                _shot(page, out_dir, "after_publish_error")
                raise PublishUncertain(f"발행 버튼을 누른 뒤 확인하지 못했습니다(블로그에서 직접 확인하세요): {e}") from e
        finally:
            ctx.close()
    for _ in range(6):                      # RSS 반영까지 잠깐 걸릴 수 있다
        url = find_post_url(cfg, post["title"])
        if url:
            return url
        time.sleep(10)
    log.warning("발행은 했지만 RSS에서 글 주소를 찾지 못했습니다")
    return f"{cfg.blog_url}/manage/posts/"


def diagnose(cfg: TistoryConfig, out_dir: Path) -> Path:
    """글쓰기 화면의 버튼·입력칸 목록과 스크린샷을 저장한다(화면이 바뀌어 발행이 실패할 때)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = _launch(p, cfg, headless=cfg.headless)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("dialog", _on_dialog)
        try:
            page.goto(_newpost_url(cfg), wait_until="domcontentloaded")
            page.wait_for_timeout(4000)
            _shot(page, out_dir, "newpost")
            controls = page.evaluate(
                """() => [...document.querySelectorAll('button, input, textarea, select, [role=option], .CodeMirror')]
                    .slice(0, 400).map(e => ({tag: e.tagName, id: e.id, cls: String(e.className).slice(0, 80),
                      name: e.getAttribute('name'), type: e.getAttribute('type'),
                      placeholder: e.getAttribute('placeholder'), text: (e.innerText || e.value || '').slice(0, 40)}))"""
            )
            found = {key: [s for s in sels if page.locator(s).count()] for key, sels in SELECTORS.items()}
            report = {"url": page.url, "selectors_found": found, "controls": controls}
            path = out_dir / "newpost_controls.json"
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            (out_dir / "newpost.html").write_text(page.content(), encoding="utf-8")
            return path
        finally:
            ctx.close()
