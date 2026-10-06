"""글쓴이가 만든 '의미 HTML'에 네이버 블로그 기본 서식을 인라인 스타일로 입힌다.

글쓴이(Claude)는 스타일을 쓰지 않고 구조만 적는다. 서식은 여기서 한 번에 입혀 글마다 똑같이 보이게 한다.
네이버 기준(naver_autopost/se_markup.py와 같은 값):
- 본문 16px·줄간격 1.8 / 챕터 제목: 세로선 인용구 굵게 / 3줄 요약: 회색 1칸 상자 + 굵은 제목 + 글머리표
- 표: 가운데 정렬, 머리줄 굵게 + 회색 배경, 칸마다 테두리 / 한 줄 요약: 구분선 + 포스트잇 인용구
- 함께 보면 좋은 글: 구분선 + 🔗 머리말

의미 HTML 약속(stats-auto-post 스킬):
  <div data-block="summary"><ul><li>..</li></ul></div>      3줄 요약
  <div data-block="highlight"><ul><li>..</li></ul></div>    핵심 숫자 박스
  <table data-chart="bar"><tr><td>이름</td><td>70.5%</td></tr></table>   막대그래프(두 번째 칸의 숫자로 길이 계산)
  <div data-block="oneline"><p>..</p></div>                 한 줄 요약
  <div data-block="related"><ul>..</ul></div>               함께 보면 좋은 글
  <div data-block="sources"><ul>..</ul></div>               출처
  <p>[[IMAGE:이름]]</p>                                      그림 자리
"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser

FONT = "font-family:'Noto Sans KR','Apple SD Gothic Neo','Malgun Gothic',sans-serif;"
BASE = {
    "p": "font-size:16px;line-height:1.8;color:#333;margin:0 0 18px;word-break:keep-all;",
    "h2": ("font-size:24px;font-weight:700;line-height:1.5;color:#111;border-left:4px solid #111;"
           "padding:2px 0 2px 14px;margin:56px 0 22px;"),
    "h3": "font-size:19px;font-weight:700;line-height:1.5;color:#222;margin:34px 0 12px;",
    "ul": "font-size:16px;line-height:1.8;color:#333;margin:0 0 18px;padding-left:22px;",
    "ol": "font-size:16px;line-height:1.8;color:#333;margin:0 0 18px;padding-left:22px;",
    "li": "margin:4px 0;",
    "strong": "font-weight:700;color:#111;",
    "a": "color:#1a73e8;text-decoration:underline;",
    "blockquote": ("border-left:3px solid #bbb;margin:22px 0;padding:6px 0 6px 18px;color:#555;"
                   "font-size:16px;line-height:1.8;"),
    "hr": "border:0;border-top:1px solid #ddd;margin:44px 0 26px;",
    "table": ("width:100%;border-collapse:collapse;margin:22px 0 30px;font-size:15px;line-height:1.6;"
              "border:1px solid #bdbdbd;"),
    "th": ("background:#f1f3f5;border:1px solid #bdbdbd;padding:12px 10px;font-weight:700;"
           "text-align:center;color:#111;"),
    "td": "border:1px solid #bdbdbd;padding:11px 10px;text-align:center;color:#333;",
}
BLOCK = {
    "summary": "background:#f7f7f7;border:1px solid #e2e2e2;padding:20px 24px 6px;margin:6px 0 34px;",
    "highlight": "border:2px solid #111;padding:20px 24px 6px;margin:26px 0 30px;",
    "oneline": ("background:#fff6cc;padding:22px 24px 6px;margin:0 0 30px;box-shadow:3px 3px 0 #ecd98a;"
                "font-weight:700;"),
    "related": "margin:0 0 26px;",
    "sources": "margin:0 0 10px;",
}
BLOCK_TITLE = {
    "summary": "📌 바쁜 사람용 3줄 요약",
    "highlight": "🔢 숫자로 박제",
    "oneline": "",
    "related": "🔗 함께 보면 좋은 글",
    "sources": "출처",
}
SOURCES_TEXT = "font-size:13px;line-height:1.7;color:#888;"
CAPTION = "text-align:center;font-size:13px;color:#999;margin:-8px 0 26px;"
BAR = "#2f6fed"
IMAGE_MARKER = re.compile(r"<p\b[^>]*>\s*\[\[IMAGE:(\w+)\]\]\s*</p>|\[\[IMAGE:(\w+)\]\]")
VOID = {"br", "hr", "img"}


def _num(text: str) -> float | None:
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", text or "")
    return float(m.group(0).replace(",", "")) if m else None


def bar_chart(rows: list[tuple[str, str]]) -> str:
    """[(이름, 값 글자)] → 막대그래프. 가장 큰 값이 70%, 나머지는 비례."""
    values = [_num(v) for _, v in rows]
    top = max((v for v in values if v is not None and v > 0), default=0)
    out = ['<div style="margin:18px 0 26px;">']
    for (label, value), n in zip(rows, values):
        width = round((n or 0) / top * 70) if top else 0
        out.append(
            '<div style="display:flex;align-items:center;gap:10px;margin:8px 0;font-size:15px;color:#333;">'
            f'<span style="flex:0 0 110px;">{label}</span>'
            f'<span style="display:inline-block;height:20px;width:{max(width, 1)}%;background:{BAR};border-radius:3px;"></span>'
            f'<span style="font-weight:700;color:#111;">{value}</span></div>')
    out.append("</div>")
    return "".join(out)


class _Styler(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.out: list[str] = []
        self.blocks: list[str | None] = []      # 열린 div의 data-block(없으면 None)
        self.chart: list[list[str]] | None = None
        self.cell: list[str] | None = None

    # 막대그래프 표는 칸 글자만 모았다가 끝에서 그래프로 바꾼다
    def _chart_tag(self, tag: str, start: bool) -> None:
        if tag == "tr" and start:
            self.chart.append([])
        elif tag in ("td", "th"):
            if start:
                self.cell = []
            elif self.cell is not None:
                self.chart[-1].append("".join(self.cell).strip())
                self.cell = None

    def _block(self) -> str | None:
        return next((b for b in reversed(self.blocks) if b), None)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.chart is not None:
            self._chart_tag(tag, True)
            return
        if tag == "table" and a.get("data-chart") == "bar":
            self.chart = []
            return
        if tag == "div" and a.get("data-block") in BLOCK:
            name = a["data-block"]
            self.blocks.append(name)
            if name in ("oneline", "related"):
                self.out.append(f'<hr style="{BASE["hr"]}">')
            self.out.append(f'<div style="{BLOCK[name]}">')
            if BLOCK_TITLE[name]:
                size = "13px;color:#888" if name == "sources" else "17px;color:#111"
                self.out.append(f'<p style="font-size:{size};font-weight:700;margin:0 0 10px;">{BLOCK_TITLE[name]}</p>')
            return
        if tag == "div":
            self.blocks.append(None)
            self.out.append("<div>")
            return
        style = BASE.get(tag, "")
        block = self._block()
        if block == "sources" and tag in ("ul", "li", "p", "a"):
            style = SOURCES_TEXT + ("color:#888;text-decoration:underline;" if tag == "a" else "")
            if tag == "ul":
                style += "padding-left:18px;margin:0;"
        elif block == "oneline" and tag == "p":
            style = "font-size:17px;line-height:1.7;color:#222;margin:0 0 16px;"
        elif block in ("highlight", "summary") and tag == "ul":
            style = BASE["ul"] + "margin:0 0 14px;"
        keep = [(k, v) for k, v in attrs if k in ("href", "colspan", "rowspan")]
        if tag == "a" and a.get("href", "").startswith("http"):
            keep += [("target", "_blank"), ("rel", "noopener")]
        attr = "".join(f' {k}="{html.escape(v or "", quote=True)}"' for k, v in keep)
        self.out.append(f"<{tag}{attr}" + (f' style="{style}"' if style else "") + (" />" if tag in VOID else ">"))

    def handle_endtag(self, tag):
        if self.chart is not None:
            if tag == "table":
                rows = [(r[0], r[1]) for r in self.chart if len(r) >= 2 and _num(r[1]) is not None]
                self.out.append(bar_chart(rows))
                self.chart = None
            else:
                self._chart_tag(tag, False)
            return
        if tag == "div":
            if self.blocks:
                self.blocks.pop()
            self.out.append("</div>")
            return
        if tag in VOID:
            return
        self.out.append(f"</{tag}>")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_data(self, data):
        (self.cell if self.cell is not None else self.out).append(data)

    def handle_entityref(self, name):
        self.handle_data(f"&{name};")

    def handle_charref(self, name):
        self.handle_data(f"&#{name};")


def _wrap_tables(body: str) -> str:
    """머리줄(thead/th)이 없는 표는 첫 줄의 td를 th로 바꿔 '표 느낌'을 확실히 낸다."""
    def fix(m: re.Match) -> str:
        table = m.group(0)
        if "data-chart" in table or re.search(r"<th\b", table, re.I):
            return table
        return re.sub(r"<tr\b[^>]*>(.*?)</tr>",
                      lambda r: r.group(0).replace("<td", "<th").replace("</td>", "</th>"), table, count=1,
                      flags=re.I | re.S)
    return re.sub(r"<table\b.*?</table>", fix, body, flags=re.I | re.S)


def stylize(body_html: str, images: dict[str, str] | None = None, captions: dict[str, str] | None = None) -> str:
    """의미 HTML → 네이버 블로그 서식이 입혀진 HTML. images는 그림 이름 → 티스토리 이미지 코드.
    올리지 못한 그림 자리는 지운다."""
    images, captions = images or {}, captions or {}
    styler = _Styler()
    styler.feed(_wrap_tables(body_html))
    styler.close()
    out = "".join(styler.out)

    def image(m: re.Match) -> str:
        name = m.group(1) or m.group(2)
        code = images.get(name)
        if not code:
            return ""
        cap = captions.get(name, "")
        return code + (f'<p style="{CAPTION}">{html.escape(cap)}</p>' if cap else "")
    out = IMAGE_MARKER.sub(image, out)
    out = re.sub(r'<p style="[^"]*">\s*</p>', "", out)
    return f'<div style="{FONT}">{out}</div>'
