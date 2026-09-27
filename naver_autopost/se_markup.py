"""post.json 본문(단순 HTML)을 네이버 스마트에디터 ONE 문서 데이터로 바꾼다.

에디터는 복사할 때 내용을 localStorage["se3#SE_COPIED_DATA"]에 문서 데이터(JSON)로 저장하고,
클립보드에는 '내부 복사' 표식(data-input-buffer)만 둔다. 붙여넣을 때 표식이 있으면 저장된 JSON으로
인용구·표·글자 크기까지 그대로 만든다(style-lab2·3과 preview-editor로 확인).
그래서 SR의 기존 글(https://blog.naver.com/kkus_i/224403935438)과 같은 서식의 JSON을 만들어 넣는다.

- 본문: 16pt(fs16), 줄간격 1.8
- 챕터(h2): 인용구 quotation_line, 굵게(인용구 기본 글꼴 19)
- 3줄 핵심 요약(맨 앞 ol): 1칸 표(배경 #f7f7f7, 테두리 #e2e2e2) + 굵은 제목 + 글머리표 목록
- 비교 표: 가운데 정렬, 첫 줄 굵게 + 배경 #fafafa, 테두리 #ccc
- 한 줄 요약(<div data-block="oneline">): 구분선 + 인용구 quotation_postit
- 함께 보면 좋은 글(<div data-block="related">): 구분선 + 🔗 제목 + 글 소개 + 링크 카드(주소 입력 후 Enter)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import quote

from .content import IMAGE_MARKER

URL_ONLY = re.compile(r"^\s*(https?://\S+)\s*$")
STORAGE_KEY = "se3#SE_COPIED_DATA"
_JS_URI_SAFE = "()!'*"
RELATED_HEAD = re.compile(r"함께\s*보면\s*좋은\s*글")
ONELINE_HEAD = re.compile(r"^\s*[📌✅🔑⭐]?\s*\[?\s*한\s*줄\s*(요약|정리)\s*\]?\s*[:：]?\s*")


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


# ---------------------------------------------------------------- 문서 데이터(JSON) 조각

def _node(text: str, bold: bool, size: str | None = "fs16", bg: str | None = None) -> dict:
    style: dict = {"ctype": "nodeStyle"}
    if size:
        style.update({"fontColor": "#000000", "fontSizeCode": size})
    if bg:
        style["backgroundColor"] = bg
    if bold:
        style["bold"] = True
    return {"id": "", "ctype": "textNode", "value": text, "style": style}


def _para(runs: list[Run], align: str | None = None, size: str | None = "fs16", bg: str | None = None,
          bullet: bool = False, line_height: float | None = 1.8) -> dict:
    nodes = [_node(t, b, size, bg) for t, b in runs] or [_node("", False, size, bg)]
    para: dict = {"id": "", "ctype": "paragraph", "nodes": nodes}
    style: dict = {"ctype": "paragraphStyle"}
    if line_height:
        style["lineHeight"] = line_height
    if align:
        style["align"] = align
    if bullet:
        style["list"] = {"type": "bullet", "level": 0, "ctype": "paragraphListStyle"}
    if len(style) > 1:
        para["style"] = style
    return para


def text_component(paragraphs: list[dict]) -> dict:
    return {"id": "", "ctype": "text", "layout": "default", "value": paragraphs}


def chapter_quote(runs: list[Run]) -> dict:
    return {"id": "", "ctype": "quotation", "layout": "quotation_line",
            "value": [_para([(t, True) for t, _ in runs], size=None, line_height=None)], "source": None}


def oneline_quote(lines: list[list[Run]]) -> dict:
    paras = [_para([("[한 줄 요약]", False)], size=None, line_height=None)]
    paras += [_para(r, size=None, line_height=None) for r in lines if r]
    return {"id": "", "ctype": "quotation", "layout": "quotation_postit", "value": paras, "source": None}


def _cell(paragraphs: list[dict], width: float, bg: str | None, border: str) -> dict:
    cell = {"id": "", "ctype": "tableCell", "borderInlineStyle": f"border:1px solid {border};",
            "colSpan": 1, "rowSpan": 1, "width": width, "height": 40, "value": paragraphs}
    if bg:
        cell["backgroundColor"] = bg
    return cell


def _table(rows: list[list[dict]], ncol: int) -> dict:
    return {"id": "", "ctype": "table", "layout": "default", "width": 100,
            "rows": [{"ctype": "tableRow", "cells": r} for r in rows],
            "columnCount": ncol, "borderInlineStyle": "border:none;"}


def summary_table(items: list[list[Run]], title: str = "⚡ 3줄 핵심 요약") -> dict:
    bg = "#f7f7f7"
    paras = [_para([(title, True)], bg=bg)] + [_para(r, bg=bg, bullet=True) for r in items]
    return _table([[_cell(paras, 100, bg, "rgb(226, 226, 226)")]], 1)


def compare_table(rows: list[list[list[list[Run]]]]) -> dict | None:
    """rows[행][열] = 셀 안 문단들(각 문단은 글자 조각 목록). 첫 행은 머리글."""
    if not rows:
        return None
    ncol = max(len(r) for r in rows)
    width = round(100 / ncol, 2)
    head_bg, border = "#fafafa", "rgb(204, 204, 204)"
    out = []
    for i, row in enumerate(rows):
        cells = []
        for c in range(ncol):
            paras = row[c] if c < len(row) else [[("", False)]]
            if i == 0:
                cells.append(_cell([_para([(t, True) for t, _ in p], align="center", bg=head_bg) for p in paras],
                                   width, head_bg, border))
            else:
                cells.append(_cell([_para(p, align="center") for p in paras], width, None, border))
        out.append(cells)
    return _table(out, ncol)


def horizontal_line() -> dict:
    return {"id": "", "ctype": "horizontalLine", "layout": "line1"}


def copied_data(components: list[dict]) -> str:
    """localStorage['se3#SE_COPIED_DATA']에 넣을 값."""
    return json.dumps({"docId": "0", "copyData": components}, ensure_ascii=False)


def clipboard_html(user_agent: str, plain: str = "") -> str:
    """에디터가 '내부 복사'로 알아보는 클립보드 표식(내용은 저장소에서 읽는다)."""
    encoded = quote(user_agent, safe=_JS_URI_SAFE)      # 브라우저 encodeURIComponent와 같게
    marker = f'<span data-input-buffer="INPUT_BUFFER_DATA;{encoded};blog.naver.com"></span>'
    return f"<html><body><!--StartFragment-->\ufeff{marker}\ufeff<!--EndFragment--></body></html>"


def plain_text(components: list[dict]) -> str:
    out = []

    def walk(v):
        if isinstance(v, dict):
            if v.get("ctype") == "textNode":
                out.append(v.get("value", ""))
            for x in v.values():
                if isinstance(x, (list, dict)):
                    walk(x)
            if v.get("ctype") == "paragraph":
                out.append("\n")
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(components)
    return "".join(out).strip()


# ---------------------------------------------------------------- 본문 → 조각 순서

Segment = tuple[str, object]  # ("se", [컴포넌트 dict]) | ("image", 이름) | ("oglink", 주소)


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
    pending: list[dict] = []         # 붙여넣기 한 번으로 넣을 컴포넌트들
    paragraphs: list[dict] = []      # 이어지는 본문 문단(한 텍스트 컴포넌트로 묶음)
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
            segments.append(("se", pending.copy()))
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
        elif tag == "h2" and RELATED_HEAD.search(text_of(node)):
            # 예전 형식: '🔗 함께 보면 좋은 글'을 챕터 제목으로 쓴 경우 → 구분선 + 굵은 머리말
            flush_text()
            pending.append(horizontal_line())
            add_paragraph([("🔗 함께 보면 좋은 글", True)])
        elif tag == "h2":
            seen_chapter = True
            flush_text()
            runs = [r for line in runs_of(node) for r in line]
            pending.append(chapter_quote(runs))
        elif tag == "p" and ONELINE_HEAD.match(text_of(node)):
            # 예전 형식: '한 줄 요약: …' 문단 → 구분선 + 포스트잇
            flush_text()
            rest = ONELINE_HEAD.sub("", text_of(node)).strip()
            pending.append(horizontal_line())
            pending.append(oneline_quote([[(rest, False)]]))
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
                paragraphs.extend(_para(r, bullet=True) for r in items)
        elif tag == "table":
            flush_text()
            table = compare_table(_table_rows(node))
            if table:
                pending.append(table)
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
