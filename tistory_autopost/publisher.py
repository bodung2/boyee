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

from naver_autopost.content import html_to_text
from naver_autopost.publisher import MOD, _launch

from . import style
from .config import TistoryConfig

log = logging.getLogger(__name__)

# 여러 후보를 순서대로 시도한다. 티스토리가 화면을 바꾸면 여기에 새 후보를 추가한다.
SELECTORS = {
    "title": ["#post-title-inp", "textarea[placeholder*='제목']", "input[placeholder*='제목']"],
    "mode_open": ["#editor-mode-layer-btn-open", "button:has-text('기본모드')", "button:has-text('마크다운')"],
    "mode_html": ["#editor-mode-html", "#editor-mode-html-text", "[id*='editor-mode-html']", "text=HTML"],
    "codemirror": [".CodeMirror"],
    "category_open": ["#category-btn", "button:has-text('카테고리')"],
    "category_item": ["#category-list [role='option']", "#category-list .mce-menu-item", "#category-list li",
                      "[class*='category'] [role='option']", "[id*='category'] li", "[class*='category'] li",
                      "[role='listbox'] [role='option']"],
    "tag_input": ["#tagText", "input[placeholder*='태그']"],
    "publish_open": ["#publish-layer-btn", "button:has-text('완료')"],
    "visibility_public": ["#open20", "input[name='basicSet'][value='20']", "label[for='open20']"],
    "publish_confirm": ["#publish-btn", "button:has-text('공개 발행')", "button:has-text('발행')"],
    "attach_open": ["#mceu_0-open", "#mceu_0 button", "button[aria-label*='첨부']", "button:has-text('첨부')",
                    "[id*='attach'] button"],
    "attach_photo": ["#attach-image", "[id*='attach-image']", "[role='menuitem']:has-text('사진')",
                     "li:has-text('사진')", "button:has-text('사진')"],
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


# 티스토리 로그인 쿠키(TSSESSION)는 브라우저를 닫으면 사라지는 세션 쿠키라서, 로그인 직후 쿠키를
# 파일로 따로 저장해 두었다가 브라우저를 열 때마다 다시 넣는다. 서버에서 만료됐으면 카카오 자동 로그인
# ('로그인 상태 유지')으로 다시 들어간다.
KAKAO_LOGIN_BUTTONS = ["a.link_kakao_id", "a:has-text('카카오계정으로 로그인')", "button:has-text('카카오계정으로 로그인')",
                       "a:has-text('카카오 계정으로 로그인')"]


# 카카오 '간편 로그인' 화면(accounts.kakao.com/login/simple, 티스토리가 prompt=select_account로 보낸다):
# 저장된 계정을 한 번 누르면 비밀번호 없이 들어간다(카카오 '로그인 상태 유지'가 살아 있을 때).
KAKAO_ACCOUNT_BUTTONS = ["#simpleLogin a", "#simpleLogin button", ".list_easy a", ".list_easy button",
                         "[class*='item_account'] a", "[class*='item_account'] button", "a.link_profile",
                         "button.btn_g.highlight", "button:has-text('계속하기')", "button:has-text('로그인')"]


def _click_first(page: Page, selectors: list[str]) -> str:
    for sel in selectors:
        loc = page.locator(sel)
        try:
            if loc.count() and loc.first.is_visible():
                loc.first.click()
                return sel
        except Exception:  # noqa: BLE001 - 화면 전환 중
            pass
    return ""


def _state_file(cfg: TistoryConfig) -> Path:
    return cfg.profile_dir / "tistory_cookies.json"


def _open(p, cfg: TistoryConfig, headless: bool):
    ctx = _launch(p, cfg, headless=headless)
    path = _state_file(cfg)
    if path.exists():
        try:
            cookies = json.loads(path.read_text(encoding="utf-8"))
            now = time.time()
            # 이미 만료된 쿠키는 넣지 않는다(세션 쿠키는 expires=-1).
            ctx.add_cookies([c for c in cookies if c.get("expires", -1) in (-1, None) or c["expires"] > now])
        except Exception as e:  # noqa: BLE001 - 저장 쿠키가 깨져도 프로필 로그인으로 계속한다
            log.warning("저장된 로그인 쿠키를 읽지 못했습니다: %s", e)
    return ctx


def _save_cookies(ctx, cfg: TistoryConfig) -> None:
    cookies = [c for c in ctx.cookies() if any(d in c.get("domain", "") for d in ("tistory.com", "kakao.com", "daum.net"))]
    path = _state_file(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cookies, ensure_ascii=False), encoding="utf-8")


def _ensure_logged_in(page: Page, cfg: TistoryConfig, timeout: float = 45) -> bool:
    """글쓰기 화면을 연다. 로그인 화면으로 가면 카카오 자동 로그인 버튼을 눌러 기다린다."""
    page.goto(_newpost_url(cfg), wait_until="domcontentloaded")
    deadline = time.time() + timeout
    clicked = picked = 0
    while time.time() < deadline:
        page.wait_for_timeout(1500)
        url = page.url
        if "/manage" in url and not _on_login_page(url):
            return True
        if "/auth/login" in url and clicked < 2:
            for sel in KAKAO_LOGIN_BUTTONS:
                btn = page.locator(sel)
                try:
                    if btn.count() and btn.first.is_visible():
                        log.info("카카오 자동 로그인 시도")
                        btn.first.click()
                        clicked += 1
                        break
                except Exception:  # noqa: BLE001 - 화면 전환 중
                    pass
        elif "accounts.kakao.com" in url:
            if page.locator("input[type='password']:visible").count():
                log.warning("카카오 비밀번호 입력 화면입니다(카카오 로그인 상태 유지가 풀림)")
                _login_debug(page, cfg)
                return False
            if picked < 3:
                sel = _click_first(page, KAKAO_ACCOUNT_BUTTONS)
                if sel:
                    picked += 1
                    log.info("카카오 간편 로그인: 저장된 계정 선택(%s)", sel)
    _login_debug(page, cfg)
    return False


def _login_debug(page: Page, cfg: TistoryConfig) -> None:
    """로그인이 막힌 화면을 남긴다(다음에 버튼 위치를 고칠 때 쓴다). 비밀번호 같은 입력값은 담기지 않는다."""
    out = cfg.output_dir / "diagnostics"
    try:
        out.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out / "login_blocked.png"), full_page=True)
        buttons = page.evaluate("""() => [...document.querySelectorAll('a,button')].filter(e => e.offsetParent)
            .slice(0, 40).map(e => ({tag: e.tagName, id: e.id, cls: e.className, text: (e.innerText || '').slice(0, 40)}))""")
        (out / "login_blocked.json").write_text(json.dumps({"url": page.url, "buttons": buttons}, ensure_ascii=False,
                                                           indent=2), encoding="utf-8")
        log.info("로그인 화면을 저장했습니다: %s", out / "login_blocked.png")
    except Exception as e:  # noqa: BLE001
        log.warning("로그인 화면 저장 실패: %s", e)


def login(cfg: TistoryConfig, wait_minutes: int = 5) -> None:
    """최초 1회: 열린 창에서 카카오 계정으로 직접 로그인하면 세션을 저장한다."""
    with sync_playwright() as p:
        ctx = _open(p, cfg, headless=False)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.on("dialog", lambda d: d.dismiss())
            page.goto("https://www.tistory.com/auth/login")
            print("열린 브라우저에서 티스토리(카카오 계정)에 로그인하세요. '로그인 상태 유지'를 꼭 체크하세요.")
            deadline = time.time() + wait_minutes * 60
            ok = False
            while time.time() < deadline:
                page.wait_for_timeout(3000)
                if any(c["name"] == "TSSESSION" for c in ctx.cookies("https://www.tistory.com")):
                    ok = True
                    break
            if not ok:
                raise SessionExpired(f"{wait_minutes}분 안에 로그인이 확인되지 않았습니다")
            # 블로그 글쓰기 화면까지 열어 두 도메인의 로그인 쿠키를 모두 만든 뒤 저장한다.
            if not _ensure_logged_in(page, cfg, timeout=60):
                raise SessionExpired(f"로그인은 됐지만 {_newpost_url(cfg)} 글쓰기 화면이 열리지 않습니다. "
                                     ".env의 TISTORY_BLOG가 이 계정의 블로그 주소인지 확인하세요.")
            page.wait_for_timeout(3000)
            _save_cookies(ctx, cfg)
        finally:
            ctx.close()
    if not check_session(cfg):
        raise SessionExpired("창을 다시 열자 로그인이 풀렸습니다. 다시 `login`을 실행하고 "
                             "카카오 로그인 화면에서 '로그인 상태 유지'를 체크하세요.")
    print("로그인 확인. 창을 다시 열어도 로그인이 유지됩니다.")


def check_session(cfg: TistoryConfig) -> bool:
    """저장된 로그인으로 글쓰기 화면이 열리는지 확인한다(10~45초)."""
    with sync_playwright() as p:
        ctx = _open(p, cfg, headless=cfg.headless)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.on("dialog", lambda d: d.dismiss())
            ok = _ensure_logged_in(page, cfg)
            if ok:
                _save_cookies(ctx, cfg)          # 새로 받은 쿠키로 갱신
            else:
                log.warning("로그인 확인 실패. 마지막 화면: %s", page.url)
            return ok
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


# 글쓰기 화면에는 숨겨진 HTML 편집기(.CodeMirror)가 처음부터 있을 수 있다. 반드시 '보이는' 편집기만 쓴다.
_VISIBLE_CM = """() => [...document.querySelectorAll('.CodeMirror')]
    .find(e => e.CodeMirror && e.offsetParent !== null && e.getBoundingClientRect().height > 0) || null"""

_BODY_LENGTH = """() => {
    const cm = (%s)();
    if (cm) return {mode: 'html', length: cm.CodeMirror.getValue().length};
    const ed = window.tinymce && window.tinymce.activeEditor;
    if (ed) return {mode: 'basic', length: ed.getContent().length};
    return {mode: 'none', length: 0};
}""" % _VISIBLE_CM


def _visible_cm(page: Page) -> bool:
    return bool(page.evaluate(f"() => !!({_VISIBLE_CM})()"))


def _switch_to_html(page: Page) -> None:
    if _visible_cm(page):
        return
    _find(page, "mode_open").click()
    page.wait_for_timeout(500)
    _find(page, "mode_html").click()
    page.wait_for_timeout(800)
    # 브라우저 확인창이 아니라 화면 속 확인 창으로 묻는 경우
    confirm = page.locator("button:visible", has_text=re.compile(r"^\s*확인\s*$"))
    if confirm.count():
        confirm.first.click()
    deadline = time.time() + 10
    while not _visible_cm(page):
        if time.time() > deadline:
            raise PublishError("HTML 모드로 바꾸지 못했습니다(보이는 HTML 편집기가 없음)")
        page.wait_for_timeout(300)
    log.info("HTML 모드로 전환")


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _cm_value(page: Page) -> str:
    return page.evaluate(f"() => {{ const e = ({_VISIBLE_CM})(); return e ? e.CodeMirror.getValue() : ''; }}")


def _set_body(page: Page, body_html: str) -> None:
    """보이는 HTML 편집기에 사람이 입력하듯 넣는다(편집기 값을 코드로 바꾸면 티스토리가 저장하지 않는다)."""
    cm = page.locator(".CodeMirror:visible").first
    cm.click()
    page.keyboard.press(f"{MOD}+A")
    page.keyboard.press("Delete")
    page.keyboard.insert_text(body_html)
    page.wait_for_timeout(800)
    value = _cm_value(page)
    if _squash(value) != _squash(body_html):
        # 자동 들여쓰기·태그 자동 닫기 등으로 내용이 바뀌었으면 값을 바로잡는다(입력 이벤트는 이미 났다).
        log.warning("입력 결과가 원문과 달라 편집기 값을 바로잡습니다(%d자 → %d자)", len(value), len(body_html))
        page.evaluate(
            """([html, findCm]) => { const e = (eval(findCm))(); e.CodeMirror.setValue(html); }""",
            [body_html, _VISIBLE_CM],
        )
        page.keyboard.press("End")
        page.keyboard.insert_text(" ")
        page.keyboard.press("Backspace")
    log.info("본문 입력(HTML %d자)", len(_cm_value(page)))


_EDITOR_STATE = """() => {
    const cms = [...document.querySelectorAll('.CodeMirror')].map(e => ({
        visible: e.offsetParent !== null, length: e.CodeMirror ? e.CodeMirror.getValue().length : -1}));
    const ed = window.tinymce && window.tinymce.activeEditor;
    return {url: location.href, codemirrors: cms,
        tinymce: ed ? {id: ed.id, length: ed.getContent().length} : null,
        iframes: [...document.querySelectorAll('iframe')].map(f => f.id || f.name || f.src).slice(0, 10),
        textareas: [...document.querySelectorAll('textarea')].map(t => ({id: t.id, name: t.name, length: t.value.length}))};
}"""


def editor_state(page: Page, out_dir: Path | None = None) -> dict:
    """발행 직전 편집기 상태(문제가 생기면 editor_state.json으로 원인을 본다)."""
    try:
        state = page.evaluate(_EDITOR_STATE)
    except Exception as e:  # noqa: BLE001
        state = {"error": str(e)}
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "editor_state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


def body_length(page: Page) -> dict:
    """지금 화면 편집기에 들어 있는 본문 길이(발행 전 확인용)."""
    return page.evaluate(_BODY_LENGTH)


def _category_label(text: str) -> str:
    """'- 숫자로 보는 한국 (3)' → '숫자로 보는 한국'(하위 카테고리 표시·글 수 제거)."""
    text = re.sub(r"\s+", " ", text or "").strip()
    text = re.sub(r"^[-·ㄴ└\s]+", "", text)
    return re.sub(r"\s*\(\d+\)$", "", text).strip()


_CATEGORY_DEBUG = """(want) => [...document.querySelectorAll('body *')]
    .filter(e => e.children.length <= 3 && (e.innerText || '').trim().replace(/\\s+/g, ' ').includes(want))
    .slice(0, 15).map(e => ({tag: e.tagName, id: e.id, cls: String(e.className).slice(0, 80), role: e.getAttribute('role'),
        visible: e.offsetParent !== null, html: e.outerHTML.slice(0, 400)}))"""


def _pick_category(page: Page, want: str, seen: list[str]) -> bool:
    """열린 화면에서 카테고리 항목을 찾아 누른다. 화면 구조가 달라도 되도록 세 가지 방법을 차례로 쓴다."""
    # 1) 일반 <select> 목록
    selects = page.locator("select")
    for i in range(selects.count()):
        sel = selects.nth(i)
        try:
            if not sel.is_visible():
                continue
            for label in sel.locator("option").all_inner_texts():
                if _category_label(label) == want:
                    sel.select_option(label=label)
                    return True
        except Exception:  # noqa: BLE001
            continue
    # 2) 알려진 목록 구조
    for css in SELECTORS["category_item"]:
        items = page.locator(css)
        for i in range(min(items.count(), 200)):
            item = items.nth(i)
            try:
                if not item.is_visible():
                    continue
                label = _category_label(item.inner_text())
            except Exception:  # noqa: BLE001
                continue
            if label and label not in seen:
                seen.append(label)
            if label == want:
                item.click()
                return True
    # 3) 구조와 상관없이 화면에 보이는 글자로(가장 안쪽 요소를 누른다)
    pattern = re.compile(r"^[-·ㄴ└\s]*" + re.escape(want) + r"(\s*\(\d+\))?\s*$")
    matches = page.get_by_text(pattern)
    for i in reversed(range(min(matches.count(), 20))):
        m = matches.nth(i)
        try:
            if m.is_visible() and m.evaluate("e => !e.closest('#category-btn') && e.tagName !== 'BUTTON'"):
                m.click()
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _select_category(page: Page, name: str, post: dict | None = None, out_dir: Path | None = None) -> bool:
    """카테고리를 고른다. 못 찾으면 화면에 보인 카테고리 이름을 post['_category_seen']에 남기고,
    그 이름이 들어 있는 화면 요소를 category_debug.json에 저장한다(화면 구조 확인용)."""
    if not name:
        return True
    want = _category_label(name)
    opener = _maybe(page, "category_open")
    if opener:
        opener.click()
    seen: list[str] = []
    deadline = time.time() + 5
    while time.time() < deadline:           # 목록이 늦게 뜨는 경우를 기다린다
        page.wait_for_timeout(400)
        if _pick_category(page, want, seen):
            page.wait_for_timeout(500)
            shown = ""
            try:
                shown = _category_label(opener.inner_text()) if opener and opener.is_visible() else ""
            except Exception:  # noqa: BLE001
                pass
            log.info("카테고리 선택: %s%s", name, f" (버튼 표시: {shown})" if shown else "")
            return True
    if out_dir is not None:
        _shot(page, out_dir, "category_not_found")
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "category_debug.json").write_text(
                json.dumps(page.evaluate(_CATEGORY_DEBUG, want), ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            log.warning("카테고리 화면 구조 저장 실패: %s", e)
    page.keyboard.press("Escape")
    log.warning("카테고리 '%s'를 찾지 못했습니다. 화면에 보인 카테고리: %s",
                name, ", ".join(seen[:30]) or "(목록을 읽지 못함)")
    if post is not None:
        post["_category_seen"] = seen[:30]
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


def rss_item(cfg: TistoryConfig, title: str) -> dict | None:
    """블로그 RSS에서 같은 제목의 글을 찾는다. {"url", "text_length"}(발행 확인·중복 발행 방지)."""
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
            desc = re.search(r"<description>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</description>", item, flags=re.S)
            text = re.sub(r"<[^>]+>", "", html.unescape(desc.group(1))) if desc else ""
            return {"url": link.group(1).strip(), "text_length": len(text.strip()) if desc else None}
    return None


def find_post_url(cfg: TistoryConfig, title: str) -> str | None:
    item = rss_item(cfg, title)
    return item["url"] if item else None


IMAGE_CODE = re.compile(r"\[##_Image(?:Grid)?\|.*?_##\]", re.S)
_IMG_COUNT = """() => { const ed = window.tinymce && window.tinymce.activeEditor;
    return ed ? (ed.getContent().match(/<img\\b|\\[##_Image/g) || []).length : -1; }"""


def _choose_file(page: Page, path: Path) -> None:
    """첨부 > 사진으로 파일 고르는 창을 열어 그림을 넣는다. 창이 안 뜨면 화면의 파일 입력칸에 바로 넣는다."""
    try:
        with page.expect_file_chooser(timeout=8_000) as chooser:
            _find(page, "attach_open", timeout=5_000).click()
            page.wait_for_timeout(500)
            item = _maybe(page, "attach_photo", timeout=3_000)
            if item:
                item.click()
        chooser.value.set_files(str(path))
        return
    except Exception as e:  # noqa: BLE001 - 아래 방법으로 다시 시도
        log.info("파일 선택 창을 열지 못해 입력칸에 바로 넣습니다: %s", e)
        page.keyboard.press("Escape")
    inputs = page.locator("input[type='file']")
    if not inputs.count():
        raise PublishError("그림을 올릴 파일 입력칸을 찾지 못했습니다")
    target = next((inputs.nth(i) for i in range(inputs.count())
                   if "image" in (inputs.nth(i).get_attribute("accept") or "")), inputs.first)
    target.set_input_files(str(path))


def _upload_images(page: Page, images: list[tuple[str, Path]], out_dir: Path) -> dict[str, str]:
    """기본 모드에서 그림을 차례로 올리고 HTML 모드로 바꿔, 티스토리가 만든 이미지 코드([##_Image|..._##])를
    올린 순서대로 그림 이름에 짝지어 돌려준다. 실패한 그림은 빼고 계속한다."""
    if not images:
        return {}
    uploaded: list[str] = []
    for name, path in images:
        before = page.evaluate(_IMG_COUNT)
        try:
            _choose_file(page, path)
        except Exception as e:  # noqa: BLE001
            log.warning("그림 %s 올리기 실패: %s", name, e)
            continue
        deadline = time.time() + 60
        while time.time() < deadline:
            page.wait_for_timeout(1000)
            now = page.evaluate(_IMG_COUNT)
            if now == -1 or now > before:
                break
        if now == -1:
            page.wait_for_timeout(6000)       # 편집기 내용을 읽을 수 없으면 넉넉히 기다린다
        uploaded.append(name)
        log.info("그림 올림: %s", name)
    _shot(page, out_dir, "images_uploaded")
    _switch_to_html(page)
    codes = IMAGE_CODE.findall(_cm_value(page))
    if not codes:
        codes = re.findall(r"<figure\b.*?</figure>|<img\b[^>]*>", _cm_value(page), flags=re.S | re.I)
    if len(codes) != len(uploaded):
        log.warning("올린 그림 %d장, 편집기에서 찾은 이미지 코드 %d개", len(uploaded), len(codes))
    return dict(zip(uploaded, codes))


def _host(path: Path, name: str) -> str:
    """그림을 구글 드라이브(구글 블로거와 같은 계정·폴더)에 올리고 바로 보이는 주소를 돌려준다."""
    from blogger_autopost import hosting
    from blogger_autopost.config import BloggerConfig
    return hosting.upload(BloggerConfig.load(), path, name)


def _host_images(images: list[tuple[str, Path]], post: dict, out_dir: Path) -> dict[str, str]:
    """그림을 편집기에 첨부하지 않고 드라이브 주소의 <img>로 만든다.
    (기본 모드에서 첨부한 뒤 HTML 모드로 바꿔 본문을 넣으면 티스토리가 그림만 저장하고 글은 버린다)"""
    alts = {i.get("name", ""): i.get("alt") or i.get("caption") or post.get("title", "")
            for i in post.get("illustrations") or []}
    codes: dict[str, str] = {}
    for name, path in images:
        try:
            url = _host(path, f"tistory-{out_dir.name}-{name}.jpg")
        except Exception as e:  # noqa: BLE001 - 그림 하나 때문에 글을 버리지 않는다
            log.warning("그림 %s 올리기 실패(빼고 발행): %s", name, e)
            continue
        codes[name] = (f'<p style="text-align:center"><img src="{html.escape(url)}" '
                       f'alt="{html.escape(alts.get(name, ""))}" style="max-width:100%;height:auto"></p>')
        log.info("그림 올림(드라이브): %s", name)
    return codes


def _fill_editor(cfg: TistoryConfig, page: Page, post: dict, out_dir: Path,
                 images: list[tuple[str, Path]] | None = None) -> Locator:
    """제목·본문·카테고리·태그를 넣고 발행 창에서 '공개'를 고른 뒤, 마지막 발행 버튼을 돌려준다."""
    try:
        if not _ensure_logged_in(page, cfg):
            raise SessionExpired("티스토리 로그인이 풀려 있습니다. `python -m tistory_autopost login`으로 다시 로그인하세요.")
        page.wait_for_timeout(1500)
        _find(page, "title", timeout=20_000)
        if getattr(cfg, "image_mode", "drive") == "upload":
            codes = _upload_images(page, images or [], out_dir)
        else:
            codes = _host_images(images or [], post, out_dir)
        post["_images_ok"] = len(codes)
        _switch_to_html(page)
        captions = {i.get("name", ""): i.get("caption") or "" for i in post.get("illustrations") or []}
        body = style.stylize(post["body_html"], codes, captions)
        post["_final_html"] = body
        _set_body(page, body)
        title_box = _find(page, "title")
        title_box.click()
        title_box.fill(post["title"])
        post["_category_ok"] = _select_category(page, cfg.category, post, out_dir)
        _add_tags(page, post.get("tags", []))
        _shot(page, out_dir, "editor_filled")

        log.info("편집기 상태: %s", json.dumps(editor_state(page, out_dir), ensure_ascii=False)[:500])
        filled = body_length(page)
        if filled["length"] < min(200, len(body) // 2):
            raise PublishError(f"본문이 편집기에 들어가지 않아 발행하지 않습니다({filled})")
        log.info("발행 전 본문 확인: %s 모드, %d자", filled["mode"], filled["length"])
        _find(page, "publish_open").click()
        page.wait_for_timeout(1200)
        if cfg.category and not post.get("_category_ok"):
            # 일부 화면은 카테고리를 발행 창에서 고른다
            post["_category_ok"] = _select_category(page, cfg.category, post, out_dir)
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


def _probe(body_html: str) -> str:
    """발행된 글 페이지에서 본문이 보이는지 확인할 문장 조각(공백 제거)."""
    for line in html_to_text(body_html).splitlines():
        line = _squash(line)
        if len(line) >= 20:
            return line[:20]
    return _squash(html_to_text(body_html))[:20]


def _verify_published(page: Page, cfg: TistoryConfig, post: dict, out_dir: Path) -> str:
    """RSS로 글 주소를 찾고, 그 글을 열어 본문 문장이 실제로 보이는지 확인한다."""
    url = ""
    for _ in range(6):                      # RSS 반영까지 잠깐 걸릴 수 있다
        item = rss_item(cfg, post["title"])
        if item:
            url = item["url"]
            break
        page.wait_for_timeout(10_000)
    if not url:
        log.warning("발행은 했지만 RSS에서 글 주소를 찾지 못했습니다")
        return f"{cfg.blog_url}/manage/posts/"
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    probe = _probe(post["body_html"])
    if probe and probe not in _squash(page.inner_text("body")):
        _shot(page, out_dir, "published_page")
        raise PublishUncertain(f"글은 올라갔지만 본문이 비어 있습니다(발행된 글에서 본문 문장을 찾지 못함). "
                               f"티스토리에서 이 글을 지우고 editor_state.json을 Claude에게 보여 주세요: {url}")
    log.info("발행된 글에서 본문 확인: %s", url)
    return url


def publish(cfg: TistoryConfig, post: dict, out_dir: Path, dry_run: bool = False,
            images: list[tuple[str, Path]] | None = None) -> str:
    """글을 발행하고 주소를 돌려준다. images는 [(그림 이름, 파일)] 순서. dry_run이면 마지막 '공개 발행' 직전에 멈춘다."""
    if not dry_run:
        same = find_post_url(cfg, post["title"])
        if same:
            log.warning("같은 제목의 글이 이미 블로그에 있어 새로 올리지 않습니다: %s", same)
            return same
    with sync_playwright() as p:
        ctx = _open(p, cfg, headless=cfg.headless)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.on("dialog", _on_dialog)
            confirm = _fill_editor(cfg, page, post, out_dir, images)
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
            return _verify_published(page, cfg, post, out_dir)
        finally:
            ctx.close()


def diagnose(cfg: TistoryConfig, out_dir: Path) -> Path:
    """글쓰기 화면의 버튼·입력칸 목록과 스크린샷을 저장한다(화면이 바뀌어 발행이 실패할 때)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = _open(p, cfg, headless=cfg.headless)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("dialog", _on_dialog)
        try:
            _ensure_logged_in(page, cfg)
            page.wait_for_timeout(3000)
            _shot(page, out_dir, "newpost")
            opener = _maybe(page, "category_open")   # 카테고리 목록도 펼쳐서 함께 저장한다
            if opener:
                opener.click()
                page.wait_for_timeout(1500)
                _shot(page, out_dir, "category_open")
            controls = page.evaluate(
                """() => [...document.querySelectorAll('button, input, textarea, select, [role=option], li, .CodeMirror')]
                    .slice(0, 600).map(e => ({tag: e.tagName, id: e.id, cls: String(e.className).slice(0, 80),
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
