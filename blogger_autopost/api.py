"""구글 블로거 공식 API(v3)와 OAuth 로그인. 추가 패키지 없이 표준 라이브러리만 쓴다.

최초 1회 `python -m blogger_autopost auth`로 브라우저에서 구글 계정을 승인하면 refresh token을 저장하고,
이후 매일 실행은 그 토큰으로 사람 손 없이 발행한다.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import logging
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

from naver_autopost.errors import ExternalAccountError

from .config import BloggerConfig

log = logging.getLogger(__name__)

BLOGGER_SCOPE = "https://www.googleapis.com/auth/blogger"
# 생성 그림을 올릴 드라이브 권한(이 프로그램이 만든 파일만 다룰 수 있는 가장 좁은 권한)
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"
# 검색 유입 진단(diagnose)용 서치 콘솔 읽기 권한
SEARCH_CONSOLE_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
SCOPE = f"{BLOGGER_SCOPE} {DRIVE_SCOPE} {SEARCH_CONSOLE_SCOPE}"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/blogger/v3"


class BloggerError(RuntimeError):
    pass


class BloggerAuthError(BloggerError, ExternalAccountError):
    """로그인(토큰)이 없거나 만료·취소됨. `python -m blogger_autopost auth`를 다시 해야 한다."""


# ---------------------------------------------------------------- OAuth

def _client(cfg: BloggerConfig) -> dict:
    if not cfg.client_secret_file.exists():
        raise BloggerAuthError(
            f"OAuth 클라이언트 파일이 없습니다: {cfg.client_secret_file}\n"
            "구글 클라우드 콘솔에서 '데스크톱 앱' OAuth 클라이언트를 만들고 JSON을 이 위치에 저장하세요(README 참고).")
    data = json.loads(cfg.client_secret_file.read_text(encoding="utf-8"))
    info = data.get("installed") or data.get("web") or data
    if not info.get("client_id") or not info.get("client_secret"):
        raise BloggerAuthError(f"{cfg.client_secret_file}에 client_id/client_secret이 없습니다")
    return info


def _post_form(url: str, fields: dict) -> dict:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:500]
        if "invalid_grant" in body or e.code in (400, 401):
            raise BloggerAuthError(
                f"구글 로그인이 만료되었거나 취소되었습니다(HTTP {e.code}): {body}\n"
                "→ python -m blogger_autopost auth 를 다시 실행하세요.") from e
        raise BloggerError(f"토큰 요청 실패(HTTP {e.code}): {body}") from e


def _save_token(cfg: BloggerConfig, token: dict) -> None:
    cfg.token_file.parent.mkdir(parents=True, exist_ok=True)
    cfg.token_file.write_text(json.dumps(token, indent=2), encoding="utf-8")


def authorize(cfg: BloggerConfig, open_browser: bool = True, timeout: int = 300) -> dict:
    """로컬 루프백(127.0.0.1) 방식으로 구글 계정 승인을 받고 refresh token을 저장한다."""
    client = _client(cfg)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    result: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            if "code" not in q and "error" not in q:
                self.send_response(404)
                self.end_headers()
                return
            result.update(q)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            msg = "승인되었습니다. 이 창을 닫아도 됩니다." if "code" in q else f"승인 실패: {q.get('error')}"
            self.wfile.write(f"<meta charset='utf-8'><h2>{msg}</h2>".encode("utf-8"))

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    redirect_uri = f"http://127.0.0.1:{server.server_port}"
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client["client_id"], "redirect_uri": redirect_uri, "response_type": "code",
        "scope": SCOPE, "access_type": "offline", "prompt": "consent", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256",
    })
    print("브라우저에서 블로그 주인 구글 계정으로 로그인하고 '허용'을 누르세요.\n"
          "(창이 안 열리면 아래 주소를 복사해 크롬에 붙여넣기)\n" + url)
    if open_browser:
        webbrowser.open(url)
    thread = threading.Thread(target=lambda: _serve_until(server, result, timeout), daemon=True)
    thread.start()
    thread.join(timeout + 5)
    server.server_close()
    if result.get("state") != state or "code" not in result:
        raise BloggerAuthError(f"구글 승인을 받지 못했습니다: {result.get('error') or '시간 초과'}")
    token = _post_form(client.get("token_uri", TOKEN_URL), {
        "code": result["code"], "client_id": client["client_id"], "client_secret": client["client_secret"],
        "redirect_uri": redirect_uri, "grant_type": "authorization_code", "code_verifier": verifier,
    })
    if not token.get("refresh_token"):
        raise BloggerAuthError("refresh token을 받지 못했습니다. 구글 계정 설정 > 보안 > 타사 앱 접근에서 "
                               "이 앱을 삭제한 뒤 다시 auth를 실행하세요.")
    token["expires_at"] = time.time() + int(token.get("expires_in", 3600)) - 60
    _save_token(cfg, token)
    return token


def _serve_until(server: http.server.HTTPServer, result: dict, timeout: int) -> None:
    deadline = time.time() + timeout
    server.timeout = 1
    while not result and time.time() < deadline:
        server.handle_request()


def has_scope(cfg: BloggerConfig, scope: str) -> bool:
    """저장된 로그인 토큰에 그 권한이 들어 있는지(예전에 블로거 권한만으로 로그인했으면 드라이브 권한이 없다)."""
    if not cfg.token_file.exists():
        return False
    granted = json.loads(cfg.token_file.read_text(encoding="utf-8")).get("scope", "")
    return scope in granted.split()


def access_token(cfg: BloggerConfig) -> str:
    if not cfg.token_file.exists():
        raise BloggerAuthError("구글 블로거 로그인이 안 되어 있습니다 → python -m blogger_autopost auth")
    token = json.loads(cfg.token_file.read_text(encoding="utf-8"))
    if token.get("access_token") and token.get("expires_at", 0) > time.time():
        return token["access_token"]
    client = _client(cfg)
    fresh = _post_form(client.get("token_uri", TOKEN_URL), {
        "client_id": client["client_id"], "client_secret": client["client_secret"],
        "refresh_token": token["refresh_token"], "grant_type": "refresh_token",
    })
    token.update(fresh)
    token["expires_at"] = time.time() + int(fresh.get("expires_in", 3600)) - 60
    _save_token(cfg, token)
    return token["access_token"]


# ---------------------------------------------------------------- Blogger API

def request(cfg: BloggerConfig, method: str, path: str, params: dict | None = None,
            body: dict | None = None) -> dict:
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(body).encode("utf-8") if body is not None else (b"" if method == "POST" else None)
    last: Exception | None = None
    for attempt in range(3):
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {access_token(cfg)}", "Content-Type": "application/json; charset=utf-8"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            if e.code == 401:
                raise BloggerAuthError(f"구글 블로거 인증 실패 → python -m blogger_autopost auth 다시 실행: {detail}") from e
            if e.code == 403:
                raise BloggerAuthError(f"이 계정에 블로그 글쓰기 권한이 없거나 API가 꺼져 있습니다(HTTP 403): {detail}") from e
            if e.code in (429, 500, 502, 503) and attempt < 2:
                last = BloggerError(f"HTTP {e.code}: {detail}")
                time.sleep(10 * (attempt + 1))
                continue
            raise BloggerError(f"Blogger API {method} {path} 실패(HTTP {e.code}): {detail}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
            time.sleep(10 * (attempt + 1))
    raise BloggerError(f"Blogger API 요청 실패: {last}")


def my_blogs(cfg: BloggerConfig) -> list[dict]:
    return request(cfg, "GET", "/users/self/blogs").get("items", [])


def resolve_blog_id(cfg: BloggerConfig) -> str:
    """BLOGGER_BLOG_ID가 없으면 BLOGGER_BLOG_URL로, 그것도 없고 블로그가 하나뿐이면 그 블로그로 정한다."""
    if cfg.blog_id:
        return cfg.blog_id
    if cfg.blog_url:
        cfg.blog_id = request(cfg, "GET", "/blogs/byurl", {"url": cfg.blog_url})["id"]
        return cfg.blog_id
    blogs = my_blogs(cfg)
    if len(blogs) == 1:
        cfg.blog_id = blogs[0]["id"]
        return cfg.blog_id
    raise BloggerError(".env에 BLOGGER_BLOG_URL(또는 BLOGGER_BLOG_ID)을 적어 주세요. "
                       f"이 계정의 블로그: {[b.get('url') for b in blogs]}")


def list_posts(cfg: BloggerConfig, status: str = "live", limit: int = 2000) -> list[dict]:
    blog = resolve_blog_id(cfg)
    posts: list[dict] = []
    token = None
    while len(posts) < limit:
        params = {"maxResults": 500, "fetchBodies": "false", "status": status,
                  "fields": "nextPageToken,items(id,title,url,published,labels,status)"}
        if token:
            params["pageToken"] = token
        data = request(cfg, "GET", f"/blogs/{blog}/posts", params)
        posts += data.get("items", [])
        token = data.get("nextPageToken")
        if not token:
            break
    return posts


def create_draft(cfg: BloggerConfig, title: str, content: str, labels: list[str]) -> dict:
    blog = resolve_blog_id(cfg)
    return request(cfg, "POST", f"/blogs/{blog}/posts", {"isDraft": "true"},
                   {"kind": "blogger#post", "title": title, "content": content, "labels": labels})


def update_content(cfg: BloggerConfig, post_id: str, content: str) -> dict:
    """이미 발행·예약한 글의 본문만 바꾼다(제목·라벨·발행일은 그대로)."""
    blog = resolve_blog_id(cfg)
    return request(cfg, "PATCH", f"/blogs/{blog}/posts/{post_id}", None, {"content": content})


def publish(cfg: BloggerConfig, post_id: str, publish_at: str | None = None) -> dict:
    """초안을 발행한다. publish_at(RFC3339 미래 시각)을 주면 그 시각에 올라가도록 예약한다."""
    blog = resolve_blog_id(cfg)
    params = {"publishDate": publish_at} if publish_at else None
    return request(cfg, "POST", f"/blogs/{blog}/posts/{post_id}/publish", params)
