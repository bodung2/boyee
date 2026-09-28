"""그날 발행한 블로그 글 → 쓰레드·인스타그램 (Meta 공식 API).

- 아침(블로그 발행 직후): Claude가 social-auto-post 스킬로 social.json 초안을 만든다.
- 저녁(예약 작업 `social-publish`): social.json을 다시 검사한 뒤 쓰레드(글 + 인포그래픽)와
  인스타그램(인포그래픽 + 캡션)에 올린다. 채널마다 한 번만 올리고 결과를 social_state.json에 남긴다.

인스타그램·쓰레드 API는 이미지를 '공개 주소'로만 받으므로, 인포그래픽을 JPEG로 바꿔
imgbb(무료, IMGBB_API_KEY)에 하루짜리로 올린 뒤 그 주소를 넘긴다.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image

from . import content, generate, history, notify
from .config import Config

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")

THREADS_API = "https://graph.threads.net"
INSTAGRAM_API = "https://graph.instagram.com"
THREADS_MAX = 500
INSTAGRAM_MAX = 2200
INSTAGRAM_MAX_TAGS = 30
TOKEN_REFRESH_DAYS = 7          # 60일짜리 토큰을 일주일마다 새로 받아 만료를 막는다

_URL = re.compile(r"https?://\S+")
_HASHTAG = re.compile(r"#\S+")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


class SocialError(RuntimeError):
    pass


# ---------------------------------------------------------------- 초안 검사

def _numbers(text: str) -> set[str]:
    text = re.sub(r"(?<=\d),(?=\d{3})", "", text)          # 1,545,000 → 1545000
    return set(_NUMBER.findall(text))


def source_text(post: dict) -> str:
    return "\n".join([
        post.get("title", ""), content.html_to_text(content.IMAGE_MARKER.sub("", post.get("body_html", ""))),
        json.dumps(post.get("card", {}), ensure_ascii=False), json.dumps(post.get("thumbnail", {}), ensure_ascii=False),
    ])


def instagram_caption(social: dict) -> str:
    ig = social.get("instagram") or {}
    tags = " ".join(ig.get("hashtags") or [])
    return (ig.get("caption", "").strip() + ("\n\n" + tags if tags else "")).strip()


def validate(social: dict, post: dict, blog_url: str, profile=None) -> list[str]:
    """발행을 막아야 하는 문제 목록. 비어 있으면 통과."""
    errors: list[str] = []
    th = (social.get("threads") or {}).get("text", "").strip()
    ig = (social.get("instagram") or {}).get("caption", "").strip()
    tags = (social.get("instagram") or {}).get("hashtags") or []
    if not th:
        errors.append("쓰레드 글이 없습니다")
    if not ig:
        errors.append("인스타 캡션이 없습니다")
    if errors:
        return errors
    if len(th) > THREADS_MAX:
        errors.append(f"쓰레드 글이 {THREADS_MAX}자를 넘습니다({len(th)}자)")
    if len(instagram_caption(social)) > INSTAGRAM_MAX:
        errors.append(f"인스타 캡션이 {INSTAGRAM_MAX}자를 넘습니다({len(instagram_caption(social))}자)")
    if len(tags) > INSTAGRAM_MAX_TAGS:
        errors.append(f"해시태그가 {INSTAGRAM_MAX_TAGS}개를 넘습니다({len(tags)}개)")
    bad_tags = [t for t in tags if not str(t).startswith("#") or " " in str(t)]
    if bad_tags:
        errors.append(f"해시태그 형식이 틀렸습니다: {bad_tags[:5]}")
    for name, text in (("쓰레드", th), ("인스타", ig)):
        if blog_url not in text:
            errors.append(f"{name} 글에 블로그 주소({blog_url})가 없습니다")
        for phrase in content.FORBIDDEN_PHRASES:
            if phrase in text:
                errors.append(f"{name} 글에 자리표시자/초안 문구가 있습니다: '{phrase}'")
        for phrase in profile.extra_forbidden if profile else ():
            if content._affirmative_use(text, phrase):
                errors.append(f"{name} 글에 금지 표현이 있습니다: '{phrase}'")
        # 원문이 사실의 상한선: 블로그 글에 없는 숫자는 쓰지 않는다(주소·해시태그 속 숫자는 제외).
        body = _HASHTAG.sub("", _URL.sub("", text))
        unknown = sorted(_numbers(body) - _numbers(source_text(post)))
        if unknown:
            errors.append(f"{name} 글에 블로그에 없는 숫자가 있습니다: {unknown[:8]}")
    return errors


def draft(cfg: Config, out_dir: Path, blog_url: str) -> dict:
    """블로그 글(post.json)로 social.json 초안을 만든다. 검사에서 떨어지면 이유를 알려 주고 한 번 더 쓰게 한다."""
    post = json.loads((out_dir / "post.json").read_text(encoding="utf-8"))
    path = out_dir / "social.json"
    feedback = ""
    for attempt in (1, 2):
        path.unlink(missing_ok=True)
        prompt = (
            "/social-auto-post\n\n"
            f"OUTPUT_DIR={generate._rel(out_dir)}\nBLOG_URL={blog_url}\nPROFILE={cfg.profile.name}\n"
            f"ACCOUNT={cfg.social_account or '(미지정)'}\n\n"
            "스킬 지침대로 post.json을 인스타그램 캡션·쓰레드 글로 재가공해 OUTPUT_DIR/social.json에 저장하라. "
            "질문하지 말고 끝까지 진행하라."
        )
        if feedback:
            prompt += f"\n\n직전 초안은 아래 이유로 거부되었다. 고쳐서 다시 저장하라:\n{feedback}"
        generate._run_claude(cfg, prompt, out_dir / f"claude_social_{attempt}.log")
        if not path.exists():
            feedback = "social.json이 만들어지지 않았습니다"
            continue
        social = json.loads(path.read_text(encoding="utf-8"))
        social["blog_url"] = blog_url
        errors = validate(social, post, blog_url, cfg.profile)
        if not errors:
            path.write_text(json.dumps(social, ensure_ascii=False, indent=2), encoding="utf-8")
            (out_dir / "social_preview.md").write_text(preview_md(social), encoding="utf-8")
            return social
        feedback = "\n- ".join([""] + errors)
        log.warning("소셜 초안 검사 실패(%d/2):%s", attempt, feedback)
    raise SocialError(f"소셜 초안을 만들지 못했습니다:{feedback}")


def preview_md(social: dict) -> str:
    return (f"# 소셜 초안\n\n블로그: {social.get('blog_url', '')}\n\n## 쓰레드\n\n"
            f"{(social.get('threads') or {}).get('text', '')}\n\n## 인스타그램\n\n{instagram_caption(social)}\n")


# ---------------------------------------------------------------- HTTP·토큰

def _request(method: str, url: str, params: dict, timeout: int = 60) -> dict:
    data = urllib.parse.urlencode({k: v for k, v in params.items() if v not in (None, "")}).encode()
    if method == "GET":
        req = urllib.request.Request(f"{url}?{data.decode()}")
    else:
        req = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            msg = json.loads(body).get("error", {}).get("message") or body
        except (json.JSONDecodeError, AttributeError):
            msg = body
        raise SocialError(f"{url.split('?')[0]} → HTTP {e.code}: {msg[:300]}") from e


def _tokens_file(cfg: Config) -> Path:
    return cfg.data_dir / f"social_tokens_{cfg.profile.name}.json"


def _fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:12]


def token(cfg: Config, channel: str) -> str:
    """.env의 토큰(또는 전에 갱신해 둔 토큰)을 돌려준다. 일주일이 지났으면 새로 받아 저장한다."""
    env_token = cfg.threads_token if channel == "threads" else cfg.instagram_token
    if not env_token:
        return ""
    path = _tokens_file(cfg)
    state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    saved = state.get(channel) or {}
    if saved.get("env") == _fingerprint(env_token):        # .env 토큰을 새로 넣었으면 그것부터 쓴다
        current, last = saved["token"], saved.get("refreshed")
    else:
        current, last = env_token, None
    today = datetime.now(KST).date()
    if last and (today - datetime.fromisoformat(last).date()).days < TOKEN_REFRESH_DAYS:
        return current
    url, grant = ((f"{THREADS_API}/refresh_access_token", "th_refresh_token") if channel == "threads"
                  else (f"{INSTAGRAM_API}/refresh_access_token", "ig_refresh_token"))
    try:
        new = _request("GET", url, {"grant_type": grant, "access_token": current}).get("access_token")
    except SocialError as e:
        log.warning("%s 토큰 갱신 실패(기존 토큰 사용): %s", channel, e)
        return current
    if new:
        state[channel] = {"token": new, "refreshed": today.isoformat(), "env": _fingerprint(env_token)}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        log.info("%s 토큰을 갱신했습니다(60일 연장)", channel)
        return new
    return current


def account(cfg: Config, channel: str) -> dict:
    """토큰 주인 계정(id·username). 발행에 쓸 사용자 ID도 여기서 얻는다."""
    tok = token(cfg, channel)
    if not tok:
        raise SocialError(f"{channel} 토큰이 .env에 없습니다")
    if channel == "threads":
        me = _request("GET", f"{THREADS_API}/v1.0/me", {"fields": "id,username", "access_token": tok})
        return {"id": cfg.threads_user_id or me["id"], "username": me.get("username", ""), "token": tok}
    me = _request("GET", f"{INSTAGRAM_API}/{cfg.instagram_api_version}/me",
                  {"fields": "user_id,username", "access_token": tok})
    return {"id": cfg.instagram_user_id or me.get("user_id") or me["id"], "username": me.get("username", ""),
            "token": tok}


# ---------------------------------------------------------------- 이미지

def to_instagram_jpeg(src: Path, out: Path, width: int = 1080) -> Path:
    """인스타는 JPEG, 가로:세로 4:5~1.91:1만 받는다. 세로로 긴 인포그래픽은 흰 여백을 붙여 4:5로 맞춘다."""
    img = Image.open(src).convert("RGB")
    ratio = img.width / img.height
    if ratio < 0.8:
        canvas = Image.new("RGB", (round(img.height * 0.8), img.height), "white")
        canvas.paste(img, ((canvas.width - img.width) // 2, 0))
        img = canvas
    elif ratio > 1.91:
        canvas = Image.new("RGB", (img.width, round(img.width / 1.91)), "white")
        canvas.paste(img, (0, (canvas.height - img.height) // 2))
        img = canvas
    if img.width != width:
        img = img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "JPEG", quality=92, optimize=True)
    return out


def host_image(cfg: Config, path: Path) -> str:
    """Meta가 가져갈 수 있게 이미지를 하루짜리 공개 주소로 올린다(imgbb)."""
    if not cfg.imgbb_api_key:
        raise SocialError(".env에 IMGBB_API_KEY가 없어 이미지를 올릴 수 없습니다")
    res = _request("POST", "https://api.imgbb.com/1/upload", {
        "key": cfg.imgbb_api_key, "expiration": 86400,
        "image": base64.b64encode(path.read_bytes()).decode(), "name": path.stem,
    }, timeout=120)
    url = (res.get("data") or {}).get("url")
    if not url:
        raise SocialError(f"이미지 업로드 응답에 주소가 없습니다: {str(res)[:200]}")
    return url


# ---------------------------------------------------------------- 발행

def _wait(url: str, params: dict, field: str, done: str = "FINISHED", tries: int = 20, pause: float = 6) -> None:
    for _ in range(tries):
        status = str(_request("GET", url, {**params, "fields": field}).get(field, "")).upper()
        if status in (done, "PUBLISHED"):
            return
        if status in ("ERROR", "EXPIRED"):
            raise SocialError(f"미디어 준비 실패: {status}")
        _sleep(pause)
    raise SocialError("미디어 준비가 끝나지 않았습니다(시간 초과)")


_sleep = time.sleep


def publish_threads(cfg: Config, social: dict, image_url: str | None) -> str:
    acc = account(cfg, "threads")
    base = f"{THREADS_API}/v1.0"
    th = social["threads"]
    params = {"text": th["text"].strip(), "access_token": acc["token"], "topic_tag": th.get("topic_tag", "")}
    params.update({"media_type": "IMAGE", "image_url": image_url} if image_url else {"media_type": "TEXT"})
    try:
        cid = _request("POST", f"{base}/{acc['id']}/threads", params)["id"]
    except SocialError as e:
        if "topic_tag" not in str(e):
            raise
        params.pop("topic_tag")
        cid = _request("POST", f"{base}/{acc['id']}/threads", params)["id"]
    if image_url:
        _wait(f"{base}/{cid}", {"access_token": acc["token"]}, "status")
    mid = _request("POST", f"{base}/{acc['id']}/threads_publish", {"creation_id": cid, "access_token": acc["token"]})["id"]
    try:
        return _request("GET", f"{base}/{mid}", {"fields": "permalink", "access_token": acc["token"]}).get("permalink", mid)
    except SocialError:
        return mid


def publish_instagram(cfg: Config, social: dict, image_url: str) -> str:
    acc = account(cfg, "instagram")
    base = f"{INSTAGRAM_API}/{cfg.instagram_api_version}"
    cid = _request("POST", f"{base}/{acc['id']}/media", {
        "image_url": image_url, "caption": instagram_caption(social), "access_token": acc["token"],
    })["id"]
    _wait(f"{base}/{cid}", {"access_token": acc["token"]}, "status_code")
    mid = _request("POST", f"{base}/{acc['id']}/media_publish", {"creation_id": cid, "access_token": acc["token"]})["id"]
    try:
        return _request("GET", f"{base}/{mid}", {"fields": "permalink", "access_token": acc["token"]}).get("permalink", mid)
    except SocialError:
        return mid


def _load_state(out_dir: Path) -> dict:
    path = out_dir / "social_state.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def publish(cfg: Config, date: str, dry_run: bool = False) -> int:
    """저녁 예약 작업: 그날 블로그 글의 소셜 초안을 쓰레드·인스타에 올린다."""
    label = cfg.profile.label
    out_dir = cfg.output_dir / date
    entry = history.published_on(cfg.history_file, date)
    if not entry:
        log.info("[%s] %s에 발행한 블로그 글이 없어 소셜 발행을 건너뜁니다", label, date)
        return 0
    blog_url = entry["url"]
    post = json.loads((out_dir / "post.json").read_text(encoding="utf-8"))
    if not (out_dir / "social.json").exists():
        log.info("아침에 만든 소셜 초안이 없어 지금 만듭니다")
        draft(cfg, out_dir, blog_url)
    social = json.loads((out_dir / "social.json").read_text(encoding="utf-8"))
    errors = validate(social, post, blog_url, cfg.profile)        # 사람이 고친 뒤에도 한도·주소를 다시 확인
    if errors:
        msg = f"[{label} 소셜 발행 중단] social.json 문제:\n- " + "\n- ".join(errors)
        notify.send(cfg, msg)
        return 1

    channels = [c for c, tok in (("threads", cfg.threads_token), ("instagram", cfg.instagram_token)) if tok]
    if not channels:
        notify.send(cfg, f"[{label}] 소셜 토큰이 .env에 없어 발행하지 않았습니다. 초안: {out_dir / 'social_preview.md'}")
        return 0
    state = _load_state(out_dir)
    todo = [c for c in channels if not (state.get(c) or {}).get("url")]
    if not todo:
        log.info("[%s] 오늘 소셜 발행은 이미 끝났습니다", label)
        return 0

    image = out_dir / "infographic.png"
    image_url = None
    if image.exists() and (cfg.imgbb_api_key or dry_run):
        jpeg = to_instagram_jpeg(image, out_dir / "social_image.jpg")
        image_url = "(dry-run)" if dry_run else host_image(cfg, jpeg)
    if dry_run:
        print(preview_md(social))
        print(f"채널: {todo}, 이미지: {'인포그래픽' if image_url else '없음'}")
        return 0

    results, failed = [], []
    for ch in todo:
        try:
            if ch == "threads":
                url = publish_threads(cfg, social, image_url if cfg.threads_with_image else None)
            elif image_url:
                url = publish_instagram(cfg, social, image_url)
            else:
                raise SocialError("인스타그램은 이미지가 필요합니다(인포그래픽 또는 IMGBB_API_KEY 없음)")
            state[ch] = {"url": url, "at": datetime.now(KST).isoformat()}
            (out_dir / "social_state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            results.append(f"{ch}: {url}")
        except Exception as e:  # noqa: BLE001 - 한 채널이 실패해도 다른 채널은 올린다
            log.exception("%s 발행 실패", ch)
            failed.append(f"{ch}: {e}")
    lines = [f"[{label} 소셜 발행] {post.get('title', '')}"] + results + [f"⚠️ {f}" for f in failed]
    notify.send(cfg, "\n".join(lines))
    return 1 if failed else 0


def check(cfg: Config) -> int:
    """토큰·계정·이미지 업로드 설정을 확인한다(발행하지 않음)."""
    ok = True
    for ch in ("threads", "instagram"):
        try:
            acc = account(cfg, ch)
            print(f"  ✅ {ch}: @{acc['username']} (id {acc['id']})")
        except SocialError as e:
            ok = False
            print(f"  ❌ {ch}: {e}")
    print(f"  {'✅' if cfg.imgbb_api_key else '❌'} 이미지 업로드(IMGBB_API_KEY)")
    return 0 if ok and cfg.imgbb_api_key else 1
