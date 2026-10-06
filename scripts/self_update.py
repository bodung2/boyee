"""예약 작업이 글을 쓰기 전에 집 PC의 코드를 최신으로 맞춘다(scripts/run_*.bat이 먼저 부른다).

- 작업 폴더가 다른 브랜치로 바뀌어 있으면 기준 브랜치(AUTOPOST_BRANCH, 기본 claude/optimistic-bell-2admac)로 되돌린다.
- 끝나지 않은 병합(충돌)이 남아 있으면 취소한다.
- 기준 브랜치를 GitHub에서 받아 온다(pull). 충돌이 나면 취소하고 지금 코드로 그대로 실행한다.
- requirements.txt가 바뀌었으면 패키지를 다시 설치한다.
문제가 있으면 텔레그램으로 알린다. 어떤 경우에도 0으로 끝나서 그날 발행은 멈추지 않는다.
패키지 코드가 낡거나 깨져 있어도 돌아가도록 표준 라이브러리만 쓴다.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BRANCH = "claude/optimistic-bell-2admac"
IDENTITY = ["-c", "user.name=naver-autopost", "-c", "user.email=naver-autopost@localhost"]


def _env() -> dict:
    values = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip().strip('"').strip("'")
    return {**values, **{k: v for k, v in os.environ.items() if k in values or k.startswith("AUTOPOST_")}}


def git(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    p = subprocess.run(["git", *IDENTITY, *args], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and p.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {(p.stderr or p.stdout).strip()[-300:]}")
    return p


def _out(*args: str) -> str:
    return git(*args).stdout.strip()


def notify(env: dict, text: str) -> None:
    print(text)
    token, chat = env.get("TELEGRAM_BOT_TOKEN", ""), env.get("TELEGRAM_CHAT_ID", "")
    if not (token and chat):
        return
    body = json.dumps({"chat_id": chat, "text": f"[코드 자동 업데이트] {text}"}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body,
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=15).read()
    except Exception as e:  # noqa: BLE001
        print(f"텔레그램 알림 실패: {e}")


def _dirty() -> list[str]:
    """커밋 안 된 '추적 중인' 파일 변경(무시 목록·새 파일은 빼고)."""
    return [l for l in _out("status", "--porcelain", "--untracked-files=no").splitlines() if l.strip()]


def update(env: dict | None = None) -> list[str]:
    """한 일·문제를 문장으로 돌려준다(문제는 '⚠️'로 시작)."""
    env = _env() if env is None else env
    branch = env.get("AUTOPOST_BRANCH") or DEFAULT_BRANCH
    done: list[str] = []
    if not (ROOT / ".git").exists():
        return ["⚠️ git 저장소가 아니어서 업데이트를 건너뜁니다"]
    if (ROOT / ".git" / "MERGE_HEAD").exists():
        git("merge", "--abort")
        done.append("⚠️ 끝나지 않은 병합(충돌)이 남아 있어 취소했습니다")

    fetched = git("fetch", "origin", branch)
    if fetched.returncode:
        return done + [f"⚠️ GitHub에서 받아 오지 못해 지금 코드로 실행합니다: {fetched.stderr.strip()[-200:]}"]

    current = _out("rev-parse", "--abbrev-ref", "HEAD")
    if current != branch:
        if _dirty():
            return done + [f"⚠️ 작업 폴더가 '{current}' 브랜치이고 고친 파일이 있어 '{branch}'(으)로 바꾸지 못했습니다 "
                           "→ 수정 파일을 정리한 뒤 git checkout으로 바꿔 주세요"]
        has_local = git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").returncode == 0
        switched = git("checkout", branch) if has_local else git("checkout", "-b", branch, "--track", f"origin/{branch}")
        if switched.returncode:
            return done + [f"⚠️ '{branch}'(으)로 바꾸지 못했습니다: {switched.stderr.strip()[-200:]}"]
        done.append(f"⚠️ 작업 폴더가 '{current}' 브랜치로 바뀌어 있어 '{branch}'(으)로 되돌렸습니다")
    git("branch", f"--set-upstream-to=origin/{branch}", branch)

    before = _out("rev-parse", "HEAD")
    pulled = git("merge", "--no-edit", f"origin/{branch}")
    if pulled.returncode:
        git("merge", "--abort")
        return done + [f"⚠️ 최신 코드를 합치다 충돌이 나서 취소하고 지금 코드로 실행합니다: "
                       f"{(pulled.stdout + pulled.stderr).strip()[-200:]}"]
    after = _out("rev-parse", "HEAD")
    if after != before:
        done.append(f"최신 코드로 업데이트: {_out('log', '-1', '--format=%h %s')}")
        if "requirements.txt" in _out("diff", "--name-only", before, after).splitlines():
            pip = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"],
                                 cwd=ROOT, capture_output=True, text=True)
            done.append("패키지 다시 설치" + ("" if pip.returncode == 0 else f" 실패 ⚠️ {pip.stderr.strip()[-200:]}"))
    return done


def main() -> int:
    env = _env()
    try:
        done = update(env)
    except Exception as e:  # noqa: BLE001 - 업데이트 문제로 발행을 멈추지 않는다
        done = [f"⚠️ 업데이트 중 오류(지금 코드로 실행): {e}"]
    for line in done:
        print(line)
    problems = [d for d in done if d.startswith("⚠️")]
    if problems:
        notify(env, "\n".join(problems))
    return 0


if __name__ == "__main__":
    sys.exit(main())
