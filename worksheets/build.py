"""활동지 한 세트 만들기: 설계 → 원화(없는 것만 새로) → 그리기 → Claude 검수(떨어진 원화는 다시 그림) → 드라이브 공유.

결과는 OUTPUT_DIR/worksheet.json(나눔글이 읽는 요약)과 장 이미지·PDF·미리보기.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from . import library, render, share
from .spec import PAGE_TYPES, problems, used_assets

log = logging.getLogger(__name__)
QA_ROUNDS = 3


class WorksheetRejected(Exception):
    """이번 설계로는 발행할 만한 활동지를 만들지 못함(다른 주제로 다시)."""


def _claude(cfg, prompt: str, log_file: Path, run=None) -> None:
    from naver_autopost import generate
    (run or generate._run_claude)(cfg, prompt + generate.FILE_RULES, log_file)


def _rel(p: Path) -> Path:
    from naver_autopost.generate import _rel
    return _rel(p)


def design(cfg, out_dir: Path, today: str, lib: Path, feedback: str = "", run=None) -> dict:
    catalog = out_dir / "library.json"
    catalog.write_text(json.dumps(library.catalog(lib), ensure_ascii=False, indent=1), encoding="utf-8")
    related = [p for p in sorted(cfg.data_dir.glob("published_*.json")) if p != cfg.history_file]
    prompt = (
        "/worksheet-design\n\n"
        f"TODAY={today}\nOUTPUT_DIR={_rel(out_dir)}\nHISTORY_FILE={_rel(cfg.history_file)}\n"
        f"RELATED_HISTORY_FILES={','.join(str(_rel(p)) for p in related) or '(없음)'}\n"
        f"LIBRARY_FILE={_rel(catalog)}\nPAGE_TYPES={', '.join(f'{k}({v})' for k, v in PAGE_TYPES.items())}\n"
        "스킬 지침대로 오늘 나눌 유아 무료 활동지 한 세트(1~2장)를 설계해 OUTPUT_DIR/spec.json에 저장하라. "
        "질문하지 말고 끝까지 진행하라."
    )
    if feedback:
        prompt += f"\n\n직전 설계는 아래 이유로 쓰지 못했다. 다른 주제나 활동으로 바꿔라:\n{feedback[:1500]}"
    _claude(cfg, prompt, out_dir / "claude_design.log", run)
    path = out_dir / "spec.json"
    if not path.exists():
        raise WorksheetRejected("spec.json이 만들어지지 않았습니다(설계 없이 끝남)")
    spec = json.loads(path.read_text(encoding="utf-8"))
    errs = problems(spec, library.load(lib))
    if errs:
        _claude(cfg, "/worksheet-design\n\n"
                f"OUTPUT_DIR={_rel(out_dir)}\nLIBRARY_FILE={_rel(catalog)}\nMODE=repair\n"
                "OUTPUT_DIR/spec.json이 아래 문제로 그릴 수 없다. 주제는 그대로 두고 문제만 고쳐 같은 파일에 저장하라:\n- "
                + "\n- ".join(errs), out_dir / "claude_design_repair.log", run)
        spec = json.loads(path.read_text(encoding="utf-8"))
        errs = problems(spec, library.load(lib))
        if errs:
            raise WorksheetRejected("활동지 설계서 문제:\n- " + "\n- ".join(errs))
    return spec


def seed_masters(lib: Path, data_dir: Path) -> list[str]:
    """보관함에 워크북 원화(master)가 없고 data/worksheets에 명세서 docx가 있으면 거기서 원화를 잘라 넣는다."""
    if any(v.get("master") for v in library.load(lib).values()):
        return []
    for docx in sorted((data_dir / "worksheets").glob("*.docx")):
        try:
            added = library.seed(docx, lib)
            log.info("워크북 원화 %d개를 보관함에 넣었습니다(%s)", len(added), docx.name)
            return added
        except Exception as e:  # noqa: BLE001 - 다른 docx일 수 있다
            log.warning("%s에서 원화를 꺼내지 못했습니다: %s", docx.name, e)
    return []


def _asset_list(spec: dict, lib: Path) -> list[dict]:
    """페이지에 쓰는 그림. 설계서에 프롬프트가 없으면 보관함 기록을 쓴다."""
    index = library.load(lib)
    given = {a["key"]: a for a in spec.get("assets") or [] if a.get("key")}
    out = []
    for k in used_assets(spec):
        a = {**index.get(k, {}), **given.get(k, {}), "key": k}
        a["prompt"] = given.get(k, {}).get("prompt") or index.get(k, {}).get("prompt", "")
        out.append(a)
    return out


def qa(cfg, out_dir: Path, spec: dict, result: dict, lib: Path, run=None) -> dict:
    index = library.load(lib)
    keys = used_assets(spec)
    new = [k for k in keys if index.get(k, {}).get("status") == "new"]
    (out_dir / "qa.json").unlink(missing_ok=True)
    prompt = (
        "/worksheet-qa\n\n"
        f"OUTPUT_DIR={_rel(out_dir)}\nSPEC_FILE={_rel(out_dir / 'spec.json')}\n"
        f"PAGES={','.join(str(_rel(Path(p))) for p in result['pages'])}\n"
        f"NEW_ASSETS={','.join(f'{k}={_rel(library.path(lib, k))}' for k in new) or '(없음)'}\n"
        f"OLD_ASSETS={','.join(k for k in keys if k not in new) or '(없음)'}\n"
        f"ANSWERS={json.dumps(result.get('answers') or {}, ensure_ascii=False)}\n"
        "스킬 지침대로 완성한 활동지 장과 새 원화를 직접 보고 검수해 OUTPUT_DIR/qa.json에 저장하라. 질문하지 말고 끝까지 진행하라."
    )
    _claude(cfg, prompt, out_dir / "claude_qa.log", run)
    path = out_dir / "qa.json"
    if not path.exists():
        raise WorksheetRejected("qa.json이 만들어지지 않았습니다(검수 없이 끝남)")
    return json.loads(path.read_text(encoding="utf-8"))


def build(cfg, out_dir: Path, today: str, feedback: str = "", run=None, gen=None, upload=None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    lib = library.root(cfg.data_dir)
    seed_masters(lib, cfg.data_dir)
    spec_path = out_dir / "spec.json"
    spec = (json.loads(spec_path.read_text(encoding="utf-8")) if spec_path.exists()
            else design(cfg, out_dir, today, lib, feedback, run))
    blog_url = f"https://blog.naver.com/{cfg.blog_id}" if cfg.blog_id else ""
    verdict: dict = {}
    for round_no in range(1, QA_ROUNDS + 1):
        library.ensure(cfg, lib, _asset_list(spec, lib), gen)
        result = render.render(spec, lib, out_dir, blog_url)
        verdict = qa(cfg, out_dir, spec, result, lib, run)
        bad = {k: str(v) for k, v in (verdict.get("assets") or {}).items() if not str(v).startswith("ok")}
        index = library.load(lib)               # 워크북 원화(master)는 지우지 않는다
        bad = {k: v for k, v in bad.items() if library.path(lib, k).exists() and not index.get(k, {}).get("master")}
        if verdict.get("verdict") == "pass" and not bad:
            break
        if bad:
            log.warning("검수에서 떨어진 원화(다시 그림, %d/%d): %s", round_no, QA_ROUNDS, bad)
            assets = {a["key"]: a for a in _asset_list(spec, lib)}
            for k in bad:                         # 다시 그릴 때 프롬프트를 잃지 않게 설계서에 남긴다
                if k in assets:
                    spec.setdefault("assets", [])
                    spec["assets"] = [a for a in spec["assets"] if a.get("key") != k] + [
                        {**assets[k], "prompt": (verdict.get("fix_prompts") or {}).get(k) or assets[k]["prompt"]}]
            library.reject(lib, list(bad), bad)
            continue
        raise WorksheetRejected(f"활동지 검수 불합격: {verdict.get('summary', '')}\n"
                                + json.dumps(verdict.get("pages") or {}, ensure_ascii=False)[:800])
    else:
        raise WorksheetRejected(f"원화를 {QA_ROUNDS}번 그려도 검수를 통과하지 못했습니다: {verdict.get('summary', '')}")
    library.accept(lib, used_assets(spec), spec["set_id"])
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")

    pdf = Path(result["pdf"])
    link = (upload or share.publish_pdf)(pdf, f"꾸쓰쌤_무료활동지_{spec['set_id']}.pdf",
                                         cfg.data_dir / "worksheets" / "drive")
    info = {
        "set_id": spec["set_id"], "theme": spec["theme"], "title": spec["title"], "age": spec["age"],
        "domain": spec.get("domain", ""), "competency": spec.get("competency", ""), "nuri": spec.get("nuri", ""),
        "skills": spec.get("skills") or [],
        "pages": [{"no": i, "type": p["type"], "activity": PAGE_TYPES[p["type"]], "title": p["title"],
                   "instruction": p["instruction"], "image": f"worksheet_p{i}"}
                  for i, p in enumerate(spec["pages"], 1)],
        "cover": "worksheet_cover", "answers": result.get("answers") or {},
        "parent_tip": spec.get("parent_tip", ""), "pdf_url": link["url"], "pdf_pages": len(spec["pages"]),
        "qa_summary": verdict.get("summary", ""),
    }
    (out_dir / "worksheet.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("활동지 준비 완료: %s (%d장) → %s", spec["title"], len(spec["pages"]), link["url"])
    return info
