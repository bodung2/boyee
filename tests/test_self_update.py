"""scripts/self_update.py: 다른 브랜치·끝나지 않은 병합·충돌이 있어도 기준 브랜치의 최신 코드로 맞추는지 진짜 git으로 확인."""
import importlib.util
import subprocess
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("self_update", Path(__file__).parent.parent / "scripts" / "self_update.py")
su = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(su)
MAIN = "claude/main-line"
ENV = {"AUTOPOST_BRANCH": MAIN}


def sh(cwd, *args):
    return subprocess.run(["git", *su.IDENTITY, *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def commit(cwd, name, text, msg):
    (Path(cwd) / name).write_text(text, encoding="utf-8")
    sh(cwd, "add", name)
    sh(cwd, "commit", "-q", "-m", msg)


@pytest.fixture
def repos(tmp_path, monkeypatch):
    """GitHub 역할(origin), 다른 세션(dev), 집 PC(pc) 저장소."""
    origin, dev, pc = tmp_path / "origin.git", tmp_path / "dev", tmp_path / "pc"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(dev)], check=True)
    sh(dev, "checkout", "-q", "-b", MAIN)
    commit(dev, "app.txt", "v1", "v1")
    sh(dev, "push", "-q", "-u", "origin", MAIN)
    sh(dev, "checkout", "-q", "-b", "claude/tistory")
    commit(dev, "tistory.txt", "t", "tistory")
    sh(dev, "push", "-q", "-u", "origin", "claude/tistory")
    sh(dev, "checkout", "-q", MAIN)
    subprocess.run(["git", "clone", "-q", "-b", MAIN, str(origin), str(pc)], check=True)
    monkeypatch.setattr(su, "ROOT", pc)
    return dev, pc


def test_pulls_latest_code(repos):
    dev, pc = repos
    commit(dev, "app.txt", "v2", "v2")
    sh(dev, "push", "-q")
    done = su.update(ENV)
    assert (pc / "app.txt").read_text() == "v2" and "v2" in done[0]
    assert su.update(ENV) == []                     # 이미 최신이면 할 일 없음


def test_switches_back_from_other_branch_and_aborts_stuck_merge(repos):
    dev, pc = repos
    commit(dev, "app.txt", "v2", "v2")
    sh(dev, "push", "-q")
    sh(pc, "checkout", "-q", "-b", "claude/tistory", "--track", "origin/claude/tistory")
    commit(pc, "app.txt", "conflict", "local edit")   # 다른 브랜치에서 기준 브랜치를 끌어오다 충돌
    subprocess.run(["git", *su.IDENTITY, "merge", f"origin/{MAIN}"], cwd=pc, capture_output=True)
    sh(pc, "fetch", "-q", "origin")
    subprocess.run(["git", *su.IDENTITY, "merge", f"origin/{MAIN}"], cwd=pc, capture_output=True)
    assert (pc / ".git" / "MERGE_HEAD").exists()

    done = su.update(ENV)
    assert sh(pc, "rev-parse", "--abbrev-ref", "HEAD").strip() == MAIN
    assert (pc / "app.txt").read_text() == "v2" and not (pc / ".git" / "MERGE_HEAD").exists()
    assert any("취소" in d for d in done) and any("되돌렸습니다" in d for d in done)


def test_keeps_local_diagnostics_commits_and_merges(repos):
    dev, pc = repos
    commit(pc, "diag.txt", "d", "diagnostics")      # PC가 올리기 전 진단 결과 커밋
    commit(dev, "app.txt", "v2", "v2")
    sh(dev, "push", "-q")
    su.update(ENV)
    assert (pc / "app.txt").read_text() == "v2" and (pc / "diag.txt").exists()


def test_conflict_is_cancelled_and_current_code_kept(repos):
    dev, pc = repos
    commit(pc, "app.txt", "pc edit", "pc")
    commit(dev, "app.txt", "v2", "v2")
    sh(dev, "push", "-q")
    done = su.update(ENV)
    assert (pc / "app.txt").read_text() == "pc edit" and not (pc / ".git" / "MERGE_HEAD").exists()
    assert done[-1].startswith("⚠️") and "충돌" in done[-1]


def test_does_not_switch_branch_with_uncommitted_edits(repos):
    dev, pc = repos
    sh(pc, "checkout", "-q", "-b", "claude/tistory", "--track", "origin/claude/tistory")
    (pc / "app.txt").write_text("unsaved")
    done = su.update(ENV)
    assert sh(pc, "rev-parse", "--abbrev-ref", "HEAD").strip() == "claude/tistory"
    assert (pc / "app.txt").read_text() == "unsaved" and "바꾸지 못했습니다" in done[-1]


def test_main_never_fails(monkeypatch):
    monkeypatch.setattr(su, "update", lambda env: (_ for _ in ()).throw(OSError("git not found")))
    sent = []
    monkeypatch.setattr(su, "notify", lambda env, text: sent.append(text))
    assert su.main() == 0 and "git not found" in sent[0]
