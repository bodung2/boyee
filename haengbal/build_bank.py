"""행발 엑셀(한셀 저장본 포함)에서 문장 은행을 뽑아 index.html의 BANK 블록을 다시 쓴다.

    python haengbal/build_bank.py 행발.xlsx                # 문장 은행만 갱신(학생 이름은 넣지 않음)
    python haengbal/build_bank.py 행발.xlsx --year 2024 --backup out.json
                                                            # 그 해 학생별 배치를 웹페이지 '백업 불러오기'용 파일로

openpyxl은 한셀 파일의 스타일 표를 못 읽어 실패하므로 XML을 직접 읽는다.
학생 이름·배치는 개인정보라 저장소(index.html)에는 절대 넣지 않고 --backup 파일로만 내보낸다.
"""
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
HERE = Path(__file__).resolve().parent
START, END = "/*BANK-START*/", "/*BANK-END*/"


def read_book(path):
    z = zipfile.ZipFile(path)
    ss = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(NS + "si"):
            ss.append("".join(t.text or "" for t in si.iter(NS + "t")))
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    sheets = {}
    for s in ET.fromstring(z.read("xl/workbook.xml")).iter(NS + "sheet"):
        target = rels[s.get(RNS + "id")].lstrip("/")
        target = target if target.startswith("xl/") else "xl/" + target
        grid = {}
        for c in ET.fromstring(z.read(target)).iter(NS + "c"):
            m = re.match(r"([A-Z]+)(\d+)", c.get("r"))
            v = c.find(NS + "v")
            val = v.text if v is not None else None
            if c.get("t") == "s" and val is not None:
                val = ss[int(val)]
            elif c.get("t") == "inlineStr":
                val = "".join(t.text or "" for t in c.iter(NS + "t"))
            if val is None or not str(val).strip():
                continue
            grid.setdefault(int(m.group(2)), {})[m.group(1)] = str(val).strip()
        sheets[s.get("name")] = grid
    return sheets


def is_sentence(t):
    return len(t) >= 20 or t.endswith((".", ",", "함", "음", "임", "됨"))


def clean(t):
    return re.sub(r"\s+", " ", t.lstrip("‣").strip())


def column_bank(grid, col, header_col=None, skip_numbers=True):
    """한 열에 '머리글 → 문장들'이 이어지는 시트. header_col이 있으면 그 열 값이 머리글."""
    cats, cur = [], None
    for r in sorted(grid):
        row = grid[r]
        if header_col and row.get(header_col) and not re.fullmatch(r"-?\d+", row[header_col]):
            if cur is not None and not cur["items"] and row.get(col) is None:
                cur["cat"] += " " + row[header_col]  # 병합 셀이 여러 줄로 쪼개진 머리글
            elif cur is not None and len(cur["items"]) == 1 and len(row[header_col]) <= 4:
                cur["cat"] += " " + row[header_col]
            else:
                cur = {"cat": row[header_col], "items": []}
                cats.append(cur)
        t = row.get(col)
        if not t:
            continue
        if not header_col and not is_sentence(t):
            cur = {"cat": t, "items": []}
            cats.append(cur)
            continue
        t = re.sub(r"^\d+\.\s*", "", clean(t))
        if cur is None:
            cur = {"cat": "기타", "items": []}
            cats.append(cur)
        if t not in cur["items"]:
            cur["items"].append(t)
    return [c for c in cats if c["items"]]


def subject_bank(grid):
    """교과발달: [과목, 단원, 개수, 문장] 4열 묶음이 옆으로 반복된다(B~D, L~N, Y~AA, AM~AO)."""
    def col_idx(c):
        n = 0
        for ch in c:
            n = n * 26 + ord(ch) - 64
        return n

    def col_name(n):
        s = ""
        while n:
            n, r = divmod(n - 1, 26)
            s = chr(65 + r) + s
        return s

    cats = []
    for r in sorted(grid):
        for c, v in grid[r].items():
            if v in ("국어", "도덕", "음악", "실과", "사회", "수학", "과학", "영어", "미술", "체육"):
                i = col_idx(c)
                unit_col, text_col = col_name(i + 1), col_name(i + 2)
                cur = None
                for rr in sorted(grid):
                    if rr < r:
                        continue
                    row = grid[rr]
                    u = row.get(unit_col)
                    if u and not re.fullmatch(r"\d+", u):
                        cur = {"cat": f"{v} {u}", "items": []}
                        cats.append(cur)
                    t = row.get(text_col)
                    if t and cur and is_sentence(t) and not re.fullmatch(r"\d+", t):
                        cur["items"].append(clean(t))
    return [c for c in cats if c["items"]]


def build(sheets):
    hb = column_bank(sheets["행발기준"], "H")
    extra = [clean(row["C"]) for _, row in sorted(sheets.get("추가문장풀", {}).items()) if row.get("C")]
    if extra:
        hb.append({"cat": "추가문장풀(완성 예시)", "items": extra})
    areas = [
        {"id": "hb", "name": "행동특성 및 종합의견", "limit": 1500, "target": 6, "cats": hb},
        {"id": "ja", "name": "자율활동", "limit": 1500, "target": 3, "cats": column_bank(sheets["자율활동"], "H")},
        {"id": "dg", "name": "동아리활동", "limit": 1500, "target": 2, "cats": column_bank(sheets["동아리"], "B")},
        {"id": "jr", "name": "진로활동", "limit": 1500, "target": 3, "cats": column_bank(sheets["진로"], "C", header_col="B")},
        {"id": "gg", "name": "교과발달", "limit": 1500, "target": 3, "cats": subject_bank(sheets["교과발달"])},
    ]
    return areas


def backup(sheets, year):
    """그 해 학생 명단과 7항목 배치(행발기준 A~G열) + 행발최종 K열부터의 추가 문장."""
    base, final = sheets["행발기준"], sheets["행발최종"]
    students = []
    for r in sorted(base):
        row = base[r]
        if r > 1 and row.get("J") and row.get("K", "").isdigit():
            students.append({"no": int(row["K"]), "name": row["J"]})
    slots = {s["no"]: [None] * 7 for s in students}
    for r in sorted(base):
        row = base[r]
        t = row.get("H")
        if not t or not is_sentence(t):
            continue
        for k, col in enumerate("ABCDEFG"):
            v = row.get(col, "")
            if v.isdigit() and int(v) in slots:
                slots[int(v)][k] = clean(t)
    rec = {}
    for s in students:
        items = [t for t in slots[s["no"]] if t]
        for r, row in final.items():
            if row.get("B") == str(s["no"]):
                cols = sorted((c for c in row if len(c) == 1 and "K" <= c <= "Z"), key=lambda c: c)
                items += [clean(row[c]) for c in cols if is_sentence(row[c])]
        rec[str(s["no"])] = items
    target = 6
    for row in base.values():
        if row.get("U") == "요구개수" and row.get("V", "").isdigit():
            target = int(row["V"])
    return {"app": "haengbal", "version": 1, "years": {str(year): {
        "students": students, "recs": {"hb": rec}, "targets": {"hb": target}}}}


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    sheets = read_book(args[0])
    if "--backup" in args:
        year = args[args.index("--year") + 1] if "--year" in args else "2024"
        out = Path(args[args.index("--backup") + 1])
        out.write_text(json.dumps(backup(sheets, year), ensure_ascii=False, indent=1), encoding="utf-8")
        print("백업 파일:", out)
        return
    areas = build(sheets)
    html_path = HERE / "index.html"
    html = html_path.read_text(encoding="utf-8")
    a, b = html.index(START), html.index(END)
    blob = json.dumps(areas, ensure_ascii=False, separators=(",", ":"))
    html_path.write_text(html[: a + len(START)] + "\nconst BANK=" + blob + ";\n" + html[b:], encoding="utf-8")
    for ar in areas:
        print(ar["name"], len(ar["cats"]), "묶음", sum(len(c["items"]) for c in ar["cats"]), "문장")


if __name__ == "__main__":
    main()
