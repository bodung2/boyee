"""post.json 본문(단순 HTML)을 네이버 스마트에디터 ONE 고유 형식으로 바꾼다.

에디터는 자기 자신이 복사한 내용(맨 앞에 data-input-buffer 표식이 붙은 컴포넌트 HTML)을 붙여넣으면
인용구·표·글자 크기까지 그대로 되살린다(style-lab2로 확인). 그래서 SR의 기존 글
(https://blog.naver.com/kkus_i/224403935438)에서 뜬 서식을 그대로 재현하는 컴포넌트를 만든다.

- 본문: 나눔고딕 16, 줄간격 1.8
- 챕터(h2): 인용구 '세로선'(quotation_line), 나눔바른고딕 19, 굵게
- 3줄 핵심 요약(맨 앞 ol): 1칸 표(배경 #f7f7f7, 테두리 #e2e2e2) + 굵은 제목 + 글머리표 목록
- 비교 표: 가운데 정렬, 첫 줄 굵게 + 배경 #fafafa, 테두리 #ccc
- 한 줄 요약(<div data-block="oneline">): 구분선 + 인용구 '포스트잇', 가운데 19
- 함께 보면 좋은 글(<div data-block="related">): 구분선 + 🔗 제목 + 글 소개 + 링크 카드(주소 입력 후 Enter)
"""
from __future__ import annotations

import html
import re
import uuid
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import quote

from .content import IMAGE_MARKER

BLACK = "color: rgb(0, 0, 0);"
URL_ONLY = re.compile(r"^\s*(https?://\S+)\s*$")


def _id() -> str:
    return f"SE-{uuid.uuid4()}"


# ---------------------------------------------------------------- 간단한 DOM

@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)   # Node | str


class _TreeBuilder(HTMLParser):
    VOID = {"br", "hr", "img", "meta", "link", "input"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def parse(fragment: str) -> Node:
    builder = _TreeBuilder()
    builder.feed(fragment)
    builder.close()
    return builder.root


def text_of(node) -> str:
    if isinstance(node, str):
        return node
    if node.tag == "br":
        return "\n"
    return "".join(text_of(c) for c in node.children)


# ---------------------------------------------------------------- 인라인 → 글자 조각

Run = tuple[str, bool]   # (글자, 굵게)


def runs_of(node, bold: bool = False) -> list[list[Run]]:
    """노드를 문단(줄) 단위의 글자 조각 목록으로. <br>은 문단을 나눈다."""
    lines: list[list[Run]] = [[]]

    def walk(n, b):
        if isinstance(n, str):
            text = re.sub(r"\s+", " ", n)
            if text:
                lines[-1].append((text, b))
            return
        if n.tag == "br":
            lines.append([])
            return
        nb = b or n.tag in ("b", "strong")
        if n.tag == "a" and n.attrs.get("href") and not text_of(n).strip():
            lines[-1].append((n.attrs["href"], nb))
            return
        for c in n.children:
            walk(c, nb)

    walk(node, bold)
    cleaned = []
    for line in lines:
        merged: list[Run] = []
        for text, b in line:
            if merged and merged[-1][1] == b:
                merged[-1] = (merged[-1][0] + text, b)
            else:
                merged.append((text, b))
        if merged:
            merged[0] = (merged[0][0].lstrip(), merged[0][1])
            merged[-1] = (merged[-1][0].rstrip(), merged[-1][1])
        cleaned.append([r for r in merged if r[0]])
    return cleaned


# ---------------------------------------------------------------- 컴포넌트 조각

def _span(text: str, bold: bool, font: str = "nanumgothic", size: int = 16,
          highlight: str | None = None, color: str = BLACK) -> str:
    inner = html.escape(text, quote=False)
    if bold:
        inner = f"<b>{inner}</b>"
    cls = f"se-ff-{font} se-fs{size}"
    style = color
    if highlight:
        cls += " se-highlight"
        style += f" background-color: {highlight};"
        inner = f"<mark>{inner}</mark>"
    return f'<span id="{_id()}" class="{cls} __se-node" style="{style}">{inner}</span>'


def _para(runs: list[Run], align: str = "left", lh: str = "1.8", **span_kw) -> str:
    if not runs:
        runs = [("", False)]
    spans = "".join(_span(t, b, **span_kw) for t, b in runs)
    return (f'<p id="{_id()}" class="se-text-paragraph se-text-paragraph-align-{align}" '
            f'style="line-height: {lh};">{spans}</p>')


def _component(kind: str, layout: str, title: str, section: str) -> str:
    cid = _id()
    return (f'<div class="se-component se-{kind} se-l-{layout}" id="{cid}" data-compid="{cid}" '
            f'data-a11y-title="{title}"><div class="se-component-content">'
            f'<div class="se-drop-indicator" data-unitid="" data-compid="{cid}" data-direction="top">'
            f'{section}</div></div></div>')


def text_component(paragraphs: list[str]) -> str:
    section = (f'<div class="se-section se-section-text se-l-default">'
               f'<div id="{_id()}" class="se-module se-module-text __se-unit">{"".join(paragraphs)}</div></div>')
    return _component("text", "default", "본문", section)


def bullet_list(items: list[list[Run]], **para_kw) -> str:
    lis = "".join(f'<li class="se-text-list-item">{_para(runs, **para_kw)}</li>' for runs in items)
    return f'<ul class="se-text-list se-text-list-type-bullet-disc">{lis}</ul>'


def quote_component(style: str, paragraphs: list[str], align: str = "left") -> str:
    cite = (f'<div id="{_id()}" class="se-module se-module-text __se-unit se-is-empty se-cite">'
            f'<p id="{_id()}" class="se-text-paragraph se-text-paragraph-align-{align}" style="line-height: 1.5;">'
            f'<span id="{_id()}" class="se-ff-nanumgothic se-fs13 __se-node" style="color: rgb(119, 119, 119);">'
            f'</span></p></div>')
    section = (f'<div class="se-section se-section-quotation se-l-{style} se-section-align-left __se-unit">'
               f'<div class="se-quotation-container">'
               f'<div id="{_id()}" class="se-module se-module-text __se-unit se-quote">{"".join(paragraphs)}</div>'
               f'{cite}</div></div>')
    return _component("quotation", style, "인용구", section)


def chapter_quote(runs: list[Run]) -> str:
    runs = [(t, True) for t, _ in runs]
    return quote_component("quotation_line", [_para(runs, font="nanumbarungothic", size=19)])


def oneline_quote(lines: list[list[Run]]) -> str:
    paras = [_para([("[한 줄 요약]", False)], align="center", font="nanumbarungothic", size=19)]
    paras += [_para(r, align="center", font="nanumbarungothic", size=19) for r in lines if r]
    return quote_component("quotation_postit", paras, align="center")


def _table(rows_html: str) -> str:
    section = (f'<div class="se-section se-section-table se-l-default se-section-align-left" style="width: 100%;">'
               f'<div class="se-table-container"><table class="se-table-content" style="border-width: medium; '
               f'border-style: none; border-color: currentcolor; border-image: none;"><tbody>{rows_html}'
               f'</tbody></table></div></div>')
    return _component("table", "default", "표", section)


def _cell(content: str, width: str, bg: str | None, border: str) -> str:
    style = f"width: {width}; height: 40px; "
    if bg:
        style += f"background-color: {bg}; "
    style += f"border: 1px solid {border};"
    return (f'<td id="{_id()}" colspan="1" rowspan="1" class="__se-unit se-cell" style="{style}">'
            f'<div id="{_id()}" class="se-module se-module-text">{content}</div></td>')


def summary_table(items: list[list[Run]], title: str = "⚡ 3줄 핵심 요약") -> str:
    bg = "rgb(247, 247, 247)"
    content = _para([(title, True)], highlight=bg) + bullet_list(items, highlight=bg)
    return _table(f'<tr class="se-tr" id="{_id()}">{_cell(content, "100%", bg, "rgb(226, 226, 226)")}</tr>')


def compare_table(rows: list[list[list[list[Run]]]]) -> str:
    """rows[행][열] = 셀 안 문단들(각 문단은 글자 조각 목록). 첫 행은 머리글."""
    if not rows:
        return ""
    ncol = max(len(r) for r in rows)
    width = f"{100 / ncol:.2f}%"
    head_bg, border = "rgb(250, 250, 250)", "rgb(204, 204, 204)"
    out = []
    for i, row in enumerate(rows):
        cells = []
        for c in range(ncol):
            paras = row[c] if c < len(row) else [[("", False)]]
            if i == 0:
                content = "".join(_para([(t, True) for t, _ in p], align="center", highlight=head_bg) for p in paras)
                cells.append(_cell(content, width, head_bg, border))
            else:
                content = "".join(_para(p, align="center") for p in paras)
                cells.append(_cell(content, width, None, border))
        out.append(f'<tr class="se-tr" id="{_id()}">{"".join(cells)}</tr>')
    return _table("".join(out))


def horizontal_line() -> str:
    section = ('<div draggable="true" class="se-section se-section-horizontalLine se-l-line1 '
               'se-section-align-left"><div class="se-module se-module-horizontalLine __se-unit">'
               '<span class="se-hr-invisible"></span><hr class="se-hr"></div></div>')
    return _component("horizontalLine", "line1", "구분선", section)


def clipboard_html(components: str, user_agent: str) -> str:
    """에디터가 '자기 복사본'으로 알아보도록 복사할 때와 같은 표식을 앞에 붙인다."""
    marker = f'<span data-input-buffer="INPUT_BUFFER_DATA;{quote(user_agent, safe="()")};blog.naver.com"></span>'
    return f"<html><body><!--StartFragment-->﻿{marker}{components}﻿<!--EndFragment--></body></html>"


# ---------------------------------------------------------------- 본문 → 조각 순서

Segment = tuple[str, str]     # ("se", 컴포넌트 HTML) | ("image", 이름) | ("oglink", 주소)


def _cell_paragraphs(td: Node) -> list[list[Run]]:
    lines = runs_of(td)
    return [l for l in lines if l] or [[("", False)]]


def _table_rows(table: Node) -> list[list[list[list[Run]]]]:
    rows = []

    def walk(n):
        for c in n.children:
            if isinstance(c, Node):
                if c.tag == "tr":
                    rows.append([_cell_paragraphs(td) for td in c.children
                                 if isinstance(td, Node) and td.tag in ("td", "th")])
                else:
                    walk(c)
    walk(table)
    return rows


def _list_items(node: Node) -> list[list[Run]]:
    items = []
    for li in node.children:
        if isinstance(li, Node) and li.tag == "li":
            runs = [r for line in runs_of(li) for r in line]
            if runs:
                items.append(runs)
    return items


def to_segments(body_html: str) -> list[Segment]:
    """본문 HTML을 에디터에 넣을 순서대로: 서식 컴포넌트 묶음, 이미지, 링크 카드."""
    body = IMAGE_MARKER.sub(lambda m: f'<img data-marker="{m.group(1)}">', body_html)
    root = parse(body)
    segments: list[Segment] = []
    pending: list[str] = []          # 붙여넣기 한 번으로 넣을 컴포넌트들
    paragraphs: list[str] = []       # 이어지는 본문 문단(한 텍스트 컴포넌트로 묶음)
    seen_chapter = False
    summary_done = False

    def flush_text():
        if paragraphs:
            pending.append(text_component(paragraphs.copy()))
            paragraphs.clear()

    def flush_all():
        flush_text()
        if pending:
            # 끝에 빈 문단을 하나 둬서, 다음 이미지·링크 카드를 넣을 때 커서가 인용구·표 안에 갇히지 않게 한다.
            pending.append(text_component([_para([])]))
            segments.append(("se", "".join(pending)))
            pending.clear()

    def add_paragraph(runs: list[Run], bold: bool = False):
        if paragraphs:
            paragraphs.append(_para([]))           # 문단 사이 한 줄 띄움(기존 글과 같은 호흡)
        paragraphs.append(_para([(t, b or bold) for t, b in runs]))

    def handle(node):
        nonlocal seen_chapter, summary_done
        if isinstance(node, str):
            if node.strip():
                add_paragraph([(node.strip(), False)])
            return
        tag = node.tag
        if tag == "img" and node.attrs.get("data-marker"):
            flush_all()
            segments.append(("image", node.attrs["data-marker"]))
        elif tag == "p" and any(isinstance(c, Node) and c.tag == "img" and c.attrs.get("data-marker")
                                for c in node.children):
            for c in node.children:
                handle(c)
        elif tag == "h2":
            seen_chapter = True
            flush_text()
            runs = [r for line in runs_of(node) for r in line]
            pending.append(chapter_quote(runs))
        elif tag == "h3":
            add_paragraph([r for line in runs_of(node) for r in line], bold=True)
        elif tag in ("ol", "ul") and not seen_chapter and not summary_done:
            summary_done = True
            flush_text()
            pending.append(summary_table(_list_items(node)))
        elif tag in ("ol", "ul"):
            items = _list_items(node)
            if tag == "ol":
                items = [[(f"{i}. ", False)] + runs for i, runs in enumerate(items, 1)]
                for runs in items:
                    add_paragraph(runs)
            else:
                if paragraphs:
                    paragraphs.append(_para([]))
                paragraphs.append(bullet_list(items))
        elif tag == "table":
            flush_text()
            pending.append(compare_table(_table_rows(node)))
        elif tag == "div" and node.attrs.get("data-block") == "oneline":
            flush_text()
            pending.append(horizontal_line())
            pending.append(oneline_quote([l for l in runs_of(node) if l]))
        elif tag == "div" and node.attrs.get("data-block") == "related":
            flush_text()
            pending.append(horizontal_line())
            add_paragraph([("🔗 함께 보면 좋은 글", True)])
            for child in node.children:
                if isinstance(child, Node) and child.tag not in ("p", "div"):
                    continue
                for line in (runs_of(child) if isinstance(child, Node) else [[(child, False)]]):
                    text = "".join(t for t, _ in line).strip()
                    if not text:
                        continue
                    m = URL_ONLY.match(text)
                    if m:
                        flush_all()
                        segments.append(("oglink", m.group(1)))
                    else:
                        add_paragraph(line)
        elif tag in ("p", "div", "section", "blockquote"):
            lines = runs_of(node)
            for line in lines:
                text = "".join(t for t, _ in line).strip()
                if not text:
                    continue
                m = URL_ONLY.match(text)
                if m:
                    flush_all()
                    segments.append(("oglink", m.group(1)))
                else:
                    add_paragraph(line)
        else:
            for c in node.children:
                handle(c)

    for child in root.children:
        handle(child)
    flush_all()
    return segments
