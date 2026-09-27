import json

from naver_autopost import se_markup as S


def kinds(segments):
    out = []
    for k, v in segments:
        if k == "se":
            out += [f"{c['ctype']}:{c.get('layout', '')}" for c in v]
        else:
            out.append(k)
    return out


BODY = (
    "<ol><li>요약 <b>12%</b>입니다.</li><li>둘째</li><li>셋째</li></ol><p>도입</p><p>[[IMAGE:illust_a]]</p>"
    "<h2>1. 무엇이 다른가요?</h2><p>결론 <strong>굵게</strong></p><p>둘째 문단</p>"
    "<table><tr><th>구분</th><th>핵심</th></tr><tr><td>진입<br>(2세)</td><td>가</td></tr></table>"
    '<div data-block="oneline"><p>무대를 깔아 주는 것입니다.</p></div>'
    '<div data-block="related"><p>「관련」 — 이유</p><p>https://blog.naver.com/kkus_i/1</p></div>'
)


def test_design_structure_matches_reference_post():
    segs = S.to_segments(BODY)
    k = kinds(segs)
    assert k[0] == "table:default"                       # 3줄 요약 표가 맨 앞
    assert "image" in k and "quotation:quotation_line" in k
    assert k.index("quotation:quotation_line") < k.index("quotation:quotation_postit")
    assert k[k.index("quotation:quotation_postit") - 1] == "horizontalLine:line1"
    assert "oglink" in k
    summary = segs[0][1][0]
    cell = summary["rows"][0]["cells"][0]
    assert cell["backgroundColor"] == "#f7f7f7"
    assert cell["value"][0]["nodes"][0]["style"]["bold"] is True
    assert all(p["style"]["list"]["type"] == "bullet" for p in cell["value"][1:])


def test_body_text_is_16pt_180_and_keeps_bold():
    segs = S.to_segments(BODY)
    texts = [c for k, v in segs if k == "se" for c in v if c["ctype"] == "text"]
    nodes = [n for c in texts for p in c["value"] for n in p["nodes"] if n["value"]]
    assert all(n["style"]["fontSizeCode"] == "fs16" for n in nodes)
    assert any(n["style"].get("bold") and n["value"] == "굵게" for n in nodes)
    assert all(p["style"]["lineHeight"] == 1.8 for c in texts for p in c["value"])


def test_compare_table_centered_with_grey_bold_header():
    segs = S.to_segments(BODY)
    tables = [c for k, v in segs if k == "se" for c in v if c["ctype"] == "table"]
    compare = tables[1]
    head = compare["rows"][0]["cells"]
    assert all(c["backgroundColor"] == "#fafafa" for c in head)
    assert all(p["style"]["align"] == "center" for c in head for p in c["value"])
    assert head[0]["value"][0]["nodes"][0]["style"]["bold"] is True
    body_cell = compare["rows"][1]["cells"][0]
    assert len(body_cell["value"]) == 2                   # <br> → 두 문단


def test_legacy_related_h2_and_oneline_paragraph():
    body = ("<h2>1. 본문</h2><p>내용</p><p>한 줄 요약: 핵심 문장입니다.</p>"
            "<h2>🔗 함께 보면 좋은 글</h2><p>「글」 — 이유</p><p>https://blog.naver.com/a/1</p>")
    k = kinds(S.to_segments(body))
    assert k.count("quotation:quotation_line") == 1       # '함께 보면 좋은 글'은 인용구가 아님
    assert "quotation:quotation_postit" in k and "oglink" in k


def test_clipboard_marker_and_storage_payload():
    html = S.clipboard_html("Mozilla/5.0 (Windows NT 10.0)")
    assert 'data-input-buffer="INPUT_BUFFER_DATA;Mozilla%2F5.0%20(Windows%20NT%2010.0);blog.naver.com"' in html
    data = json.loads(S.copied_data([S.horizontal_line()]))
    assert data["copyData"][0]["ctype"] == "horizontalLine"
