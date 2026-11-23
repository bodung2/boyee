"""자바스크립트로 본문을 그리는 공식 페이지(국가법령정보센터 law.go.kr, 교육청 누리집)와 PDF의 글자를 읽는다.

글쓰기 Claude의 WebFetch는 페이지 틀만 받아 와서 법령 조문을 못 읽는다(2026-11-23 저경력 교사 시리즈 실패 원인).
Claude가 Bash로 이 모듈을 불러 원문을 확인한다:

  python -m naver_autopost.pagetext "https://www.law.go.kr/법령/교육공무원법/제41조"
  python -m naver_autopost.pagetext "https://www.goe.go.kr/....pdf" --out OUTPUT_DIR/src_goe.txt
  python -m naver_autopost.pagetext --law 교육공무원법 --article 41

- 웹페이지: 머리 없는 크롬으로 열어 모든 프레임의 보이는 글자를 모은다(로그인 정보는 쓰지 않는 새 브라우저).
- PDF(주소가 .pdf이거나 응답이 PDF): 내려받아 pypdf로 글자를 뽑는다.
- --out을 주면 전체를 파일로 저장하고, 화면에는 앞부분만 보여 준다.
"""
from __future__ import annotations

import argparse
import io
import re
import sys
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
PRINT_MAX = 12000
PREVIEW_MAX = 1500      # --out으로 저장할 때 화면에 보여 줄 앞부분


def law_url(law: str, article: str | None = None) -> str:
    """국가법령정보센터 현행 법령(조문) 주소. 예: 교육공무원법 41 → /법령/교육공무원법/제41조"""
    path = f"/법령/{law.strip()}"
    if article:
        art = str(article).strip()
        art = art if art.startswith("제") else f"제{art}조"
        path += f"/{art}"
    return "https://www.law.go.kr" + urllib.parse.quote(path)


def pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return "\n\n".join(f"[{i} 쪽]\n{(p.extract_text() or '').strip()}" for i, p in enumerate(reader.pages, 1))


def _fetch_bytes(url: str) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read(), r.headers.get("Content-Type", "")


def page_text(url: str, wait_ms: int = 2500, timeout_ms: int = 45_000) -> str:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True, channel="chrome")
        except Exception:  # noqa: BLE001 - 크롬이 없으면 Playwright 기본 크로미움
            browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(locale="ko-KR", user_agent=UA)
            pdf_holder: dict = {}

            def on_response(resp):                  # 주소가 PDF로 바로 내려오는 경우
                if "application/pdf" in (resp.headers.get("content-type") or "") and not pdf_holder:
                    try:
                        pdf_holder["data"] = resp.body()
                    except Exception:  # noqa: BLE001
                        pass
            page.on("response", on_response)
            try:
                page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            except Exception:  # noqa: BLE001 - 늦게 끝나는 페이지도 받은 만큼 읽는다
                pass
            if pdf_holder.get("data"):
                return pdf_text(pdf_holder["data"])
            page.wait_for_timeout(wait_ms)
            parts = []
            for frame in page.frames:
                try:
                    t = frame.inner_text("body", timeout=5_000)
                except Exception:  # noqa: BLE001
                    continue
                t = re.sub(r"\n{3,}", "\n\n", t).strip()
                if t and t not in parts:
                    parts.append(t)
            return f"[페이지 제목] {page.title()}\n[주소] {page.url}\n\n" + "\n\n---- (프레임) ----\n\n".join(parts)
        finally:
            browser.close()


def read(url: str) -> str:
    if re.search(r"\.pdf($|\?)", url, re.I):
        data, _ = _fetch_bytes(url)
        return pdf_text(data)
    return page_text(url)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m naver_autopost.pagetext")
    ap.add_argument("url", nargs="?")
    ap.add_argument("--law", help="법령 이름(국가법령정보센터 현행)")
    ap.add_argument("--article", help="조 번호(예: 41 또는 제41조의2)")
    ap.add_argument("--out", help="전체 글자를 저장할 파일")
    a = ap.parse_args(argv)
    url = a.url or (law_url(a.law, a.article) if a.law else None)
    if not url:
        ap.error("주소나 --law를 주세요")
    try:
        text = read(url)
    except Exception as e:  # noqa: BLE001
        print(f"읽기 실패: {url}\n{type(e).__name__}: {e}")
        return 1
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if a.out:                                        # 토큰 아끼기: 파일로 저장하면 화면에는 짧게만
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(f"[출처] {url}\n\n{text}")
        print(f"저장: {a.out} ({len(text)}자). 필요한 조·단어는 Grep으로 찾아 읽으세요.\n")
        print(text[:PREVIEW_MAX] + ("\n…" if len(text) > PREVIEW_MAX else ""))
        return 0
    print(text[:PRINT_MAX] + ("\n…(앞부분만 표시, 전체는 --out 파일)" if len(text) > PRINT_MAX else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
