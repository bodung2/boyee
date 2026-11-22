"""퀘스트 보드: 예약 표 읽기, 기록·로그로 오늘 상태 판단, 화면·요약 만들기."""
import json
import os
from datetime import datetime

from quest_board import board, html, schedule
from quest_board.checks import Paths

TABLE = '''$Schedule = @(
    @{ Name = "NaverAutoPost-edu"; Bat = "run_daily.bat"; Arg = "--profile edu"; Times = @("06:00", "11:00"); Hours = 9; Wake = $true; Desc = "네이버 교육 블로그(11:00은 막힌 날 재시도)" }
    @{ Name = "TistoryAutoPost2"; Bat = "run_tistory_daily.bat"; Arg = "--slot 2"; Times = @("17:00"); Hours = 8; Wake = $true; Desc = "티스토리 2편째" }
    @{ Name = "NaverAutoPost-market"; Bat = "run_daily.bat"; Arg = "--profile market"; Times = @("13:30"); Hours = 6; Wake = $true; Days = @("Tuesday", "Saturday"); Desc = "시황" }
    @{ Name = "Social-edu"; Bat = "run_social.bat"; Arg = "--profile edu"; Times = @("20:00"); Hours = 2; Wake = $true; Desc = "교육 인스타·쓰레드" }
    @{ Name = "PerpBotPaper"; Bat = "run_perp_paper.bat"; Arg = ""; Times = @("01:05"); Hours = 0.5; Wake = $false; Every = 4; Desc = "선물 봇" }
    @{ Name = "NewQuest"; Bat = "run_new_thing.bat"; Arg = ""; Times = @("09:00"); Hours = 1; Wake = $false; Desc = "새 퀘스트" }
    @{ Name = "QuestBoard"; Bat = "run_quest_board.bat"; Arg = "--notify"; Times = @("23:40"); Hours = 0.5; Wake = $false; Desc = "보드" }
    @{ Name = "QuestBoardRefresh"; Bat = "run_quest_board_refresh.bat"; Arg = ""; Times = @("00:05"); Hours = 0.25; Wake = $false; Every = 1; Hidden = $true; Desc = "갱신" }
)
'''
MON = datetime(2026, 11, 2, 19, 0, tzinfo=board.KST)      # 월요일


def paths(tmp_path):
    p = Paths(tmp_path / "data", tmp_path / "output", tmp_path / "logs")
    for d in (p.data, p.output, p.logs):
        d.mkdir(parents=True)
    return p


def old(path, ts=MON.timestamp() - 5 * 3600):
    os.utime(path, (ts, ts))


def statuses(p, live=None, now=MON):
    quests, has_live, missing = schedule.load(live=live, table_text=TABLE)
    b = board.build(quests, has_live, missing, now=now, days=3, paths=p)
    return b, {r.quest.name: r.today for r in b.rows}


def test_parse_table_reads_every_field_and_skips_board_itself():
    qs = {q.name: q for q in schedule.parse_table(TABLE)}
    assert "QuestBoard" not in qs and "QuestBoardRefresh" not in qs
    edu = qs["NaverAutoPost-edu"]
    assert (edu.bat, edu.arg, edu.times, edu.label) == ("run_daily.bat", "--profile edu", ["06:00", "11:00"], "네이버 교육 블로그")
    assert qs["NaverAutoPost-market"].days == ["Tuesday", "Saturday"]
    assert qs["PerpBotPaper"].every == 4


def test_real_schedule_table_parses():
    qs = schedule.parse_table((schedule.ROOT / "scripts" / "setup_all_schedules.ps1").read_text(encoding="utf-8-sig"))
    names = {q.name for q in qs}
    assert {"NaverAutoPost-edu", "TistoryAutoPost", "BloggerAutoPost", "NaverAutoPost-Social-childhood"} <= names
    assert all(q.times for q in qs)
    assert not names & {"QuestBoard", "QuestBoardRefresh"}
    text = (schedule.ROOT / "scripts" / "setup_all_schedules.ps1").read_text(encoding="utf-8-sig")
    assert 'Name = "QuestBoardRefresh"' in text and "Every = 1; Hidden = $true" in text


def test_scheduler_entries_find_bat_even_when_run_hidden():
    plain = schedule._with_bat({"Execute": r"C:\Users\홍길동\boyee\scripts\run_daily.bat", "Arguments": "--profile edu"})
    assert (plain["Bat"], plain["Arg"]) == ("run_daily.bat", "--profile edu")
    hidden = schedule._with_bat({"Execute": "wscript.exe", "Arguments":
                                 r'"C:\Users\홍 길동\boyee\scripts\run_hidden.vbs" "C:\Users\홍 길동\boyee\scripts\run_tistory_daily.bat" --slot 2'})
    assert (hidden["Bat"], hidden["Arg"]) == ("run_tistory_daily.bat", "--slot 2")
    quests, _, _ = schedule.load(live={"QuestBoardRefresh": schedule._with_bat({
        "Name": "QuestBoardRefresh", "Execute": "wscript.exe",
        "Arguments": r'"C:\b\scripts\run_hidden.vbs" "C:\b\scripts\run_quest_board_refresh.bat"'})}, table_text=TABLE)
    assert "QuestBoardRefresh" not in {q.name for q in quests}


def test_today_states_from_records_logs_and_locks(tmp_path):
    p = paths(tmp_path)
    (p.data / "published_edu.json").write_text(json.dumps([
        {"date": "2026-11-02", "title": "고교학점제 정리", "url": "https://blog.naver.com/a/1", "source": "autopost"},
        {"date": "2026-11-01", "title": "어제 글", "url": "https://blog.naver.com/a/0", "source": "autopost"}]), encoding="utf-8")
    (p.logs / ".run-tistory.lock").write_text("1")
    old(p.logs / ".run-tistory.lock", MON.timestamp() - 600)
    b, st = statuses(p)
    assert st["NaverAutoPost-edu"].state == "done" and st["NaverAutoPost-edu"].result.title == "고교학점제 정리"
    assert st["TistoryAutoPost2"].state == "running"
    assert st["NaverAutoPost-market"].state == "off"          # 월요일은 예약 없음
    assert st["Social-edu"].state == "waiting"                # 20:00 전
    assert st["NewQuest"].state == "unknown"                  # 기록 방식을 모르고 스케줄러 정보도 없음
    edu_row = next(r for r in b.rows if r.quest.name == "NaverAutoPost-edu")
    assert [c.state for c in edu_row.cells] == ["none", "done", "done"]


def test_failure_reason_and_retry_from_log(tmp_path):
    p = paths(tmp_path)
    log = p.logs / "edu-2026-11-02.log"
    log.write_text("2026-11-02 06:40:00,1 INFO x: 시작\n"
                   "2026-11-02 06:41:00,1 ERROR naver_autopost.pipeline: 자동 발행 실패\n"
                   "Traceback (most recent call last):\n  File \"x.py\", line 1\n"
                   "naver_autopost.publisher.SessionExpired: 네이버 로그인이 풀려 있습니다\n"
                   "2026-11-02 06:41:01,1 INFO naver_autopost.notify: 알림: [교육 자동발행 실패]\n", encoding="utf-8")
    old(log, MON.replace(hour=6, minute=42).timestamp())
    _, st = statuses(p, now=MON.replace(hour=9))
    assert st["NaverAutoPost-edu"].state == "retry"
    assert st["NaverAutoPost-edu"].detail == "네이버 로그인이 풀려 있습니다 → 11:00 재시도"
    _, st = statuses(p)
    assert st["NaverAutoPost-edu"].state == "fail"


def test_error_followed_by_success_is_not_failure(tmp_path):
    p = paths(tmp_path)
    log = p.logs / "edu-2026-11-02.log"
    log.write_text("2026-11-02 06:41:00,1 ERROR x: 자동 발행 실패\nRuntimeError: 일시 오류\n"
                   "2026-11-02 11:30:00,1 INFO naver_autopost.notify: 알림: [교육 자동발행 완료] 제목\n", encoding="utf-8")
    old(log)
    _, st = statuses(p)
    assert st["NaverAutoPost-edu"].state == "unknown"        # 실패 아님, 다만 이력 기록이 없음


def test_scheduler_info_marks_missed_failed_and_unregistered(tmp_path):
    p = paths(tmp_path)
    live = {
        "NaverAutoPost-edu": {"Name": "NaverAutoPost-edu", "LastRun": "2026-11-01T06:00:00", "LastResult": 0},
        "NewQuest": {"Name": "NewQuest", "LastRun": "2026-11-02T09:00:05", "LastResult": 1,
                     "NextRun": "2026-11-03T09:00:00"},
        "Handmade": {"Name": "Handmade", "Bat": "run_handmade.bat", "Arg": "", "Times": ["10:00"],
                     "LastRun": "2026-11-02T10:00:00", "LastResult": 0},
    }
    b, st = statuses(p, live=live)
    assert st["NaverAutoPost-edu"].state == "missed"          # 오늘 실행 흔적이 없음
    assert st["NewQuest"].state == "fail" and "종료 코드 1" in st["NewQuest"].detail
    assert st["Handmade"].state == "ran"                      # 표에 없이 직접 등록한 작업도 보인다
    assert "TistoryAutoPost2" in b.unregistered
    row = next(r for r in b.rows if r.quest.name == "NewQuest")
    assert row.next_run == "11/3(화) 09:00"


def test_social_neighbors_and_mtime_quests(tmp_path):
    p = paths(tmp_path)
    (p.output / "edu" / "2026-11-01").mkdir(parents=True)
    (p.output / "edu" / "2026-11-01" / "social_state.json").write_text(json.dumps(
        {"threads": {"url": "https://threads.net/p/1"}, "instagram": {"url": "https://instagram.com/p/2"}}))
    (p.data / "perp").mkdir()
    (p.data / "perp" / "paper_state.json").write_text("{}")
    old(p.data / "perp" / "paper_state.json", MON.replace(hour=17, minute=5).timestamp())
    b, st = statuses(p, now=MON.replace(hour=21))
    social = next(r for r in b.rows if r.quest.name == "Social-edu")
    assert social.cells[1].state == "done" and [c for c, _ in social.cells[1].result.links] == ["threads", "instagram"]
    assert st["Social-edu"].state == "skip"                   # 오늘 블로그 글이 없어 올릴 것이 없음
    assert st["PerpBotPaper"].state == "done" and "17:05" in st["PerpBotPaper"].result.title


def test_render_and_summary(tmp_path):
    p = paths(tmp_path)
    (p.data / "published_edu.json").write_text(json.dumps([
        {"date": "2026-11-02", "title": "<제목>", "url": "https://blog.naver.com/a/1", "source": "autopost"}]))
    b, _ = statuses(p)
    page = html.render(b)
    assert '<meta http-equiv="refresh" content="300">' in page
    assert "오늘의 퀘스트 · 11/2(월)" in page and "&lt;제목&gt;" in page and "https://blog.naver.com/a/1" in page
    text = board.summary_text(b)
    assert text.startswith("[퀘스트 보드] 11/2(월)")
    assert "✅ 06:00 네이버 교육 블로그 — <제목>" in text
    assert "시황" not in text                                  # 쉬는 날은 요약에서 뺀다


def test_blog_panel_shows_lab_status_and_survives_missing_files(tmp_path, monkeypatch):
    import json as _json
    from datetime import datetime as _dt

    from quest_board import blogs
    from quest_board.checks import Paths
    data, out = tmp_path / "data", tmp_path / "output"
    (data / "lab").mkdir(parents=True)
    now = _dt(2026, 11, 21, 10)
    posts = [{"title": f"글{i}", "url": f"https://blog.naver.com/x/{i}", "date": f"2026-11-{21 - i:02d}", "source": "autopost"}
             for i in range(5)]
    for f in ("published_invest.json", "published_edu.json", "published_market.json"):
        (data / f).write_text(_json.dumps(posts), encoding="utf-8")
    (data / "lab" / "daily_invest.json").write_text(_json.dumps({
        "fetched": [f"2026-11-{d:02d}" for d in range(1, 21)],
        "posts": {"https://blog.naver.com/x/1": {f"2026-11-{d:02d}": 3 for d in range(1, 21)}}}), encoding="utf-8")
    (data / "lab" / "ledger_invest.json").write_text(_json.dumps({
        "topics": {"사교육비": {"status": "promising", "ratio": 2.9}}, "graveyard": [{"name": "등록금"}],
        "proposals": [{"id": 3, "text": "연도를 제목 끝에", "status": "pending"}]}, ensure_ascii=False), encoding="utf-8")
    (data / "lab" / "learned_invest.md").write_text(
        "## 확정 규칙 (블로그 주인 승인)\n- (2026-11-10) 조건형 검색어를 제목 앞에\n", encoding="utf-8")
    monkeypatch.setattr(blogs, "_lab_modes", lambda: (["invest", "tistory"], ["edu", "childhood"], ["invest"]))
    cards = blogs.collect(Paths(data=data, output=out, logs=tmp_path), now)
    by = {c.key: c for c in cards}
    assert set(by) == {"invest", "edu", "market"}
    assert by["invest"].mode == "lab-auto" and by["invest"].views == 42 and by["invest"].today == 1
    assert by["invest"].rules == [("2026-11-10", "조건형 검색어를 제목 앞에")]
    assert by["edu"].mode == "watch" and by["edu"].views is None and by["market"].mode == "off"
    page = blogs.render(cards, now)
    assert "실험실 · 자동 개선" in page and "조건형 검색어를 제목 앞에" in page and "투3 연도를 제목 끝에" in page
    assert "조회수 수집 중" in page and "등록금" in page and "<script" not in page


def test_board_has_today_and_blog_analysis_sections():
    from datetime import datetime as _dt

    from quest_board import board as qb, html as qh
    b = qb.Board(_dt(2026, 11, 21, 10, tzinfo=qb.KST), ["2026-11-20", "2026-11-21"], [], True, [])
    page = qh.render(b, remote=True, blogs_html="<p>BLOG-PANEL</p>")
    assert 'id="sec-today"' in page and 'id="sec-blogs"' in page and "BLOG-PANEL" in page
    assert "자동화 블로그 분석" in page and "frameElement" in page


def test_blog_panel_blogger_index_card(tmp_path, monkeypatch):
    import json as _json
    from datetime import datetime as _dt

    from quest_board import blogs
    from quest_board.checks import Paths
    data = tmp_path / "data"
    data.mkdir()
    (data / "published_blogger.json").write_text(_json.dumps(
        [{"title": "a", "url": "https://x.blogspot.com/a", "date": "2026-11-21", "source": "autopost"}]), encoding="utf-8")
    (data / "blogger_index.json").write_text(_json.dumps({"days": [
        {"date": "2026-11-20", "posts": 20, "checked": 20, "indexed": 2, "states": {}, "impressions": 3, "clicks": 0, "by_day": {}},
        {"date": "2026-11-21", "posts": 21, "checked": 21, "indexed": 6, "states": {"발견됨·색인 안 됨": 15},
         "impressions": 40, "clicks": 2, "by_day": {"2026-11-20": {"impressions": 9, "clicks": 1}}, "days_to_index": 9}]},
        ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(blogs, "_lab_modes", lambda: ([], [], []))
    cards = blogs.collect(Paths(data=data, output=tmp_path / "out", logs=tmp_path), _dt(2026, 11, 21, 23))
    assert cards[0].mode == "index"
    page = blogs.render(cards)
    assert "색인 감시 중" in page and "<b>6</b>/21편" in page and "28%" in page
    assert "발견됨·색인 안 됨 15편" in page and "11-20에는 2편" in page and "보통 9일" in page


def test_blog_panel_shows_claude_notes_and_escapes(tmp_path):
    from quest_board import blogs
    (tmp_path / "invest.md").write_text("updated: 2026-11-21\n### 결론\n- **수요**가 막힘 <b>x</b>\n\n| 항목 | 값 |\n|---|---|\n| 조회 | 421 |\n",
                                        encoding="utf-8")
    day, html_ = blogs.note("invest", tmp_path)
    assert day == "2026-11-21" and "<b>수요</b>" in html_ and "&lt;b&gt;x" in html_ and "<td>421</td>" in html_
    assert blogs.note("none", tmp_path) == ("", "")
    c = blogs.Card("invest", "네이버 투자", "", mode="lab", note_date=day, note_html=html_)
    assert "🧠 Claude 분석 · 2026-11-21" in blogs.render([c])


def test_repo_notes_have_no_urls_or_post_titles():
    """diagnostics/notes는 공개 저장소에 올라간다: 주소·블로그 주소가 들어가면 안 된다."""
    from quest_board import blogs
    for f in blogs.NOTES_DIR.glob("*.md"):
        text = f.read_text(encoding="utf-8")
        assert "http" not in text and "blogspot" not in text and "tistory.com" not in text, f.name
        assert text.startswith("updated: "), f.name


def test_blogger_trend_slot_checked_separately(tmp_path):
    import json as _json

    from quest_board import checks
    from quest_board.checks import Paths
    from quest_board.schedule import Quest
    data = tmp_path / "data"
    data.mkdir()
    (data / "published_blogger.json").write_text(_json.dumps([
        {"date": "2026-11-21", "title": "main", "url": "https://x/1", "source": "autopost"},
        {"date": "2026-11-21", "title": "trend", "url": "https://x/2", "source": "autopost", "slot": "trend"}]),
        encoding="utf-8")
    p = Paths(data=data, output=tmp_path, logs=tmp_path)
    main = Quest("BloggerAutoPost", "run_blogger_daily.bat", "")
    two = Quest("BloggerAutoPost2", "run_blogger_daily.bat", "--slot trend")
    assert checks.check(p, main, "2026-11-21").title == "main"
    assert checks.check(p, two, "2026-11-21").title == "trend"


def test_auto_register_missing_tasks_once_a_day(tmp_path, monkeypatch):
    from quest_board import register
    calls = []

    def fake(names):
        calls.append(list(names))
        return True, "등록: " + ",".join(names)
    monkeypatch.delenv("AUTOPOST_AUTO_REGISTER", raising=False)
    assert register.auto_register(["A", "B"], tmp_path, "2026-11-22", fake, "win32") is True
    assert register.auto_register(["A", "B"], tmp_path, "2026-11-22", fake, "win32") is False   # 같은 날 다시 안 함
    assert register.auto_register(["A", "C"], tmp_path, "2026-11-22", fake, "win32") is True     # 새 작업만
    assert calls == [["A", "B"], ["C"]]
    assert register.auto_register(["A"], tmp_path, "2026-11-23", fake, "win32") is True          # 다음 날 다시 시도
    assert register.auto_register(["X"], tmp_path, "2026-11-23", fake, "linux") is False         # 윈도우에서만
    monkeypatch.setenv("AUTOPOST_AUTO_REGISTER", "false")
    assert register.auto_register(["Y"], tmp_path, "2026-11-23", fake, "win32") is False


def test_childhood_card_shows_activity_sheet_posts_and_queries(tmp_path, monkeypatch):
    import json as _json
    from datetime import datetime as _dt

    from quest_board import blogs
    from quest_board.checks import Paths
    data, out = tmp_path / "data", tmp_path / "output"
    (data / "lab").mkdir(parents=True)
    posts = [{"title": "한글 활동지", "url": "https://blog.naver.com/k/1", "source": "blog"},       # 날짜 없는 직접 쓴 글
             {"title": "[유아 워크북 제작기 ①] 7영역", "url": "https://blog.naver.com/k/2", "source": "blog"},
             {"title": "누리과정 인간상", "url": "https://blog.naver.com/k/3", "date": "2026-11-11", "source": "autopost"}]
    (data / "published_childhood.json").write_text(_json.dumps(posts, ensure_ascii=False), encoding="utf-8")
    (data / "lab" / "daily_childhood.json").write_text(_json.dumps({
        "fetched": ["2026-11-19", "2026-11-20"],
        "posts": {"https://blog.naver.com/k/1": {"2026-11-19": 2, "2026-11-20": 3, "2026-09-01": 10}}}), encoding="utf-8")
    cap = out / "lab" / "childhood" / "2026-11-21"
    cap.mkdir(parents=True)
    (cap / "capture.json").write_text(_json.dumps({"responses": [{"url": "https://x/api/blog/user/referer/total", "json": {
        "result": {"statDataList": [{"data": {"rows": {"searchQuery": ["유아 한글 활동지", "누리과정 인간상"],
                                                       "cv": [2, 5]}}}]}}}]}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(blogs, "_lab_modes", lambda: ([], ["childhood"], []))
    card = blogs.collect(Paths(data=data, output=out, logs=tmp_path), _dt(2026, 11, 21, 10))[0]
    assert [r[0] for r in card.freebie] == ["한글 활동지", "[유아 워크북 제작기 ①] 7영역"]
    assert card.freebie[0][2:] == (5, 15) and card.freebie_queries == [("유아 한글 활동지", 2)]
    page = blogs.render([card])
    assert "🎨 활동지 글 (최근 14일 조회 5회)" in page and "유아 한글 활동지(2)" in page


def test_remote_requests_run_once_and_only_allowed(tmp_path):
    import json as _json

    from quest_board import requests
    repo, local = tmp_path / "repo", tmp_path / "local"
    repo.mkdir()
    (repo / requests.REQUESTS).write_text(_json.dumps({"requests": [
        {"id": "a", "action": "export", "blog": "invest"},
        {"id": "b", "action": "shell", "cmd": "del *"},
        {"id": "c", "action": "export", "blog": "nope"}]}), encoding="utf-8")
    ran = []
    spawn = lambda cmd, log: ran.append(cmd[-3:])  # noqa: E731
    assert requests.run_pending(repo, local, tmp_path / "logs", spawn) == ["a"]
    assert ran == [["export", "--blog", "invest"]]
    assert requests.run_pending(repo, local, tmp_path / "logs", spawn) == []          # 한 번만
