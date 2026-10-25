"""그림 화풍 목록과 실험(한 번에 변수 하나, 두 갈래를 번갈아).

'base'는 지금 스킬에 적힌 화풍 그대로다. 실험은 채택된 화풍(처음엔 base)과 아직 안 해 본 화풍 하나를 하루씩 번갈아 쓰고,
같은 나이 조회수 점수로 비교해 확실히 나은 쪽만 채택한다. 어떤 화풍이든 '글자·숫자·로고 없음, 실존 인물 아님'은 그대로다
(스킬과 그림 검수가 지킨다)."""
from __future__ import annotations

from datetime import date, timedelta

STYLES: dict[str, dict[str, str]] = {
    "invest": {
        "base": "clean modern editorial illustration, flat vector with soft grain, deep navy and warm yellow accents, "
                "slightly humorous mood, Korean everyday setting, wide 16:9 composition",
        "watercolor": "soft watercolor illustration with gentle paper texture, warm natural palette with navy accents, "
                      "calm everyday Korean setting, wide 16:9 composition",
        "isometric": "clean isometric 3D illustration with soft shadows, navy and warm yellow palette, "
                     "miniature everyday Korean scene, wide 16:9 composition",
        "bold_flat": "bold high-contrast flat illustration with thick outlines, saturated yellow and deep navy, "
                     "playful mood, Korean everyday setting, wide 16:9 composition",
        "photo": "photorealistic editorial photo style, natural light, everyday Korean setting, people seen from behind "
                 "or out of focus with faces not visible, shallow depth of field, wide 16:9 composition",
    },
    "tistory": {
        "base": "clean modern editorial illustration, flat vector with soft grain, muted navy and warm orange accents, calm mood",
        "isometric": "clean isometric 3D illustration of a desk with a laptop and abstract interface shapes, "
                     "soft shadows, navy and warm orange palette, calm mood",
        "line": "minimal line-art illustration with one accent color (warm orange) on off-white background, "
                "simple shapes, calm mood",
        "photo": "photorealistic photo style of a tidy desk with a laptop seen at an angle, screen content blurred and "
                 "unreadable, natural window light, calm mood",
    },
}

EXPERIMENT_POSTING_DAYS = 14        # 두 갈래를 번갈아 쓰는 기간(그 뒤 판정 나이만큼 더 기다렸다 비교)
MIN_POSTS_PER_ARM = 4
WIN_MARGIN = 1.2                    # 상대보다 20% 이상 나아야 채택


def style_text(blog: str, style_id: str) -> str:
    table = STYLES.get(blog, {})
    return table.get(style_id) or table.get("base", "")


def next_challenger(blog: str, ledger: dict) -> str | None:
    tried = {a for e in ledger.get("experiments_done", []) if e.get("var") == "image_style" for a in e.get("arms", [])}
    current = (ledger.get("adopted") or {}).get("image_style", "base")
    for sid in STYLES.get(blog, {}):
        if sid != current and sid not in tried:
            return sid
    return None


def start(blog: str, ledger: dict, today: str) -> dict | None:
    challenger = next_challenger(blog, ledger)
    if not challenger:
        return None
    current = (ledger.get("adopted") or {}).get("image_style", "base")
    until = (date.fromisoformat(today) + timedelta(days=EXPERIMENT_POSTING_DAYS - 1)).isoformat()
    ledger["experiment"] = {"var": "image_style", "arms": [current, challenger], "start": today,
                            "post_until": until, "status": "running"}
    return ledger["experiment"]


def arm_for(ledger: dict, today: str, slot: int = 1) -> str:
    """오늘 글이 쓸 화풍 id. 실험 중이면 날짜(와 하루 몇 번째 글인지)로 두 갈래를 번갈아 고른다."""
    exp = ledger.get("experiment") or {}
    current = (ledger.get("adopted") or {}).get("image_style", "base")
    if exp.get("var") != "image_style" or exp.get("status") != "running":
        return current
    if not (exp["start"] <= today <= exp["post_until"]):
        return current
    # 하루 한 편이면 날마다 번갈아, 두 편이면 그날 두 편이 서로 다르게(날짜 + 몇 번째 글)
    return exp["arms"][(date.fromisoformat(today).toordinal() + slot - 1) % 2]


def decide(scores: dict[str, dict], arms: list[str]) -> tuple[str | None, str]:
    """(채택할 갈래 또는 None, 이유). 두 갈래 모두 충분히 모였을 때만 판정한다."""
    a, b = arms
    sa, sb = scores.get(a, {}), scores.get(b, {})
    if min(sa.get("n", 0), sb.get("n", 0)) < MIN_POSTS_PER_ARM or not (sa.get("ratio") and sb.get("ratio")):
        return None, f"글이 모자람({a} {sa.get('n', 0)}편 / {b} {sb.get('n', 0)}편, 갈래당 {MIN_POSTS_PER_ARM}편 필요)"
    if sb["ratio"] >= sa["ratio"] * WIN_MARGIN:
        return b, f"{b} {sb['ratio']} vs {a} {sa['ratio']} → {b} 채택"
    if sa["ratio"] >= sb["ratio"] * WIN_MARGIN:
        return a, f"{a} {sa['ratio']} vs {b} {sb['ratio']} → {a} 유지"
    return a, f"{a} {sa['ratio']} vs {b} {sb['ratio']} → 차이가 작아 구분 불가, {a} 유지"
