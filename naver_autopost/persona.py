"""작가 페르소나(persona/persona.md): 자동 글에 실제 경험·생각을 녹일 때 쓰는 유일한 근거.

파일은 집 PC에만 둔다(.gitignore). 없으면 페르소나 없이 예전처럼 쓴다.
에피소드는 "[E01]" 같은 번호로 구분하고, 글마다 쓴 번호를 post.json의 persona_used에 남겨
최근에 쓴 에피소드가 반복되지 않게 한다.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .config import ROOT

EPISODE_ID = re.compile(r"\[(E\d{2,3})\]")


def path() -> Path:
    return Path(os.environ.get("PERSONA_FILE") or ROOT / "persona" / "persona.md")


def load() -> str:
    p = path()
    return p.read_text(encoding="utf-8-sig") if p.exists() else ""


def episode_ids(text: str) -> list[str]:
    return list(dict.fromkeys(EPISODE_ID.findall(text)))


def recent_used(history_files: list[Path], posts: int = 10) -> list[str]:
    """여러 블로그의 최근 자동 글(posts편씩)에서 쓴 에피소드 번호."""
    used: list[str] = []
    for f in history_files:
        try:
            entries = json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
        except (OSError, json.JSONDecodeError):
            continue
        auto = [e for e in entries if e.get("source") == "autopost"][-posts:]
        for e in auto:
            used += [i for i in e.get("persona_used") or [] if isinstance(i, str)]
    return list(dict.fromkeys(used))


def clean_used(value, text: str) -> list[str]:
    """글쓴이가 적은 persona_used 중 실제 페르소나에 있는 번호만 남긴다."""
    known = set(episode_ids(text))
    items = value if isinstance(value, list) else []
    return [i for i in dict.fromkeys(str(x).strip() for x in items) if i in known]
