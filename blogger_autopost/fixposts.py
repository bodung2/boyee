"""이미 발행·예약한 글에 새 글과 같은 다듬기(A: 그림을 첫 문단 뒤로, B: 끝에 관련 글 링크)를 적용한다.

기본은 미리보기만 하고, --apply를 주면 바꾸기 전 본문을 output/blogger/backup/에 저장한 뒤 블로그 글을 고친다.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from naver_autopost.content import html_to_text
from naver_autopost.pipeline import KST

from . import api, seo
from .config import BloggerConfig

log = logging.getLogger(__name__)


def _posts(cfg: BloggerConfig, status: str) -> list[dict]:
    blog = api.resolve_blog_id(cfg)
    posts, token = [], None
    while True:
        params = {"maxResults": 100, "fetchBodies": "true", "status": status,
                  "fields": "nextPageToken,items(id,title,url,published,labels,content)"}
        if token:
            params["pageToken"] = token
        data = api.request(cfg, "GET", f"/blogs/{blog}/posts", params)
        posts += data.get("items", [])
        token = data.get("nextPageToken")
        if not token:
            return posts


def run(cfg: BloggerConfig, apply: bool = False) -> list[dict]:
    live = _posts(cfg, "live")
    targets = live + _posts(cfg, "scheduled")
    candidates = [{"url": p.get("url"), "title": p.get("title"), "labels": p.get("labels", []),
                   "published": p.get("published")} for p in live]
    backup = cfg.output_dir / "backup" / datetime.now(KST).strftime("%Y%m%d-%H%M%S")
    report = []
    for post in targets:
        body = post.get("content") or ""
        new, changes = seo.improve(body, post.get("url", ""), post.get("title", ""), post.get("labels", []),
                                   candidates)
        if new == body:
            continue
        item = {"id": post["id"], "title": post.get("title"), "url": post.get("url", ""), **changes,
                "opening_before": html_to_text(body)[:120], "opening_after": html_to_text(new)[:120]}
        if apply:
            backup.mkdir(parents=True, exist_ok=True)
            (backup / f"{post['id']}.html").write_text(body, encoding="utf-8")
            api.update_content(cfg, post["id"], new)
            item["saved"] = True
            log.info("고침: %s", post.get("title"))
        report.append(item)
    if apply and report:
        (backup / "changes.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def restore(cfg: BloggerConfig, backup_dir: Path) -> int:
    """fix-posts로 바꾼 글을 백업해 둔 본문으로 되돌린다."""
    n = 0
    for f in sorted(backup_dir.glob("*.html")):
        api.update_content(cfg, f.stem, f.read_text(encoding="utf-8"))
        n += 1
    return n
