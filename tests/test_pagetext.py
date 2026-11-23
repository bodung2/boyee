"""자바스크립트로 그리는 공식 페이지·PDF 원문 읽기(저경력 교사 시리즈가 법령 조문을 못 읽어 멈춘 문제)."""
import urllib.parse

import pytest

from naver_autopost import pagetext


def test_law_url_points_to_current_article():
    url = pagetext.law_url("교육공무원법", "41")
    assert urllib.parse.unquote(url) == "https://www.law.go.kr/법령/교육공무원법/제41조"
    assert urllib.parse.unquote(pagetext.law_url("교육공무원법", "제41조의2")).endswith("/제41조의2")


def test_page_text_reads_script_rendered_body_and_frames(tmp_path):
    pytest.importorskip("playwright")
    page = tmp_path / "law.html"
    page.write_text(
        "<html><head><title>법령</title></head><body><div id='c'>로딩</div>"
        "<iframe srcdoc='<p>제41조(근무장소 외 연수) 교원은 수업에 지장을 주지 아니하는 범위에서</p>'></iframe>"
        "<script>setTimeout(()=>{document.getElementById('c').innerText='교육공무원법 본문'},200)</script></body></html>",
        encoding="utf-8")
    try:
        text = pagetext.page_text(page.as_uri(), wait_ms=800)
    except Exception as e:  # noqa: BLE001 - 브라우저가 없는 환경
        pytest.skip(f"브라우저 없음: {e}")
    assert "교육공무원법 본문" in text and "제41조(근무장소 외 연수)" in text


def test_pdf_text_extracts_pages(tmp_path):
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(100, 100)
    path = tmp_path / "a.pdf"
    with open(path, "wb") as f:
        w.write(f)
    assert pagetext.pdf_text(path.read_bytes()).startswith("[1 쪽]")
