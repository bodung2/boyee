"""성장 실험실: 통계 매칭·점수·판정·오늘의 방향·화풍 실험·주간 리뷰 적용·텔레그램 답장을 확인한다."""
import json
import urllib.parse
from datetime import date, timedelta

import pytest

from growth_lab import brief, demand, diagnose, features, metrics, rank, review, scoring, stats, store, styles
from growth_lab.config import LabConfig
from naver_autopost import history
from tistory_autopost import inbox


@pytest.fixture
def cfg(tmp_path):
    return LabConfig(
        blogs=["invest", "tistory"], data_dir=tmp_path / "data" / "lab", history_dir=tmp_path / "data",
        output_dir=tmp_path / "output" / "lab", diagnostics_dir=tmp_path / "diag", log_dir=tmp_path / "logs",
        probe_posts=3, explore_share=0.3, promising_ratio=1.5, dead_ratio=0.5, min_baseline_posts=3,
        health_min_views=20, rank_max_queries=10, push_report=False)


def day(n: int) -> str:
    return (date(2026, 10, 1) + timedelta(days=n)).isoformat()


def url(i: int) -> str:
    return f"https://blog.naver.com/myblog/22400000{i:04d}"


# ---------------------------------------------------------------- 꼬리표

def test_title_type_and_features():
    assert features.title_type("연봉 5천, 실수령액 얼마일까?") == "실수령형"
    assert features.title_type("순자산 3억, 상위 몇 %일까?") == "위치형"
    assert features.title_type("PowerShell '-File' 오류 해결") == "오류형"
    assert features.title_type("그냥 제목") == "기타"
    f = features.post_features({"title": "청약 가점, 몇 점이면 될까?", "lane": "B", "image_style_id": "watercolor",
                                "body_html": "<p>첫 문단입니다.</p><h2>a</h2><table></table><p>[[IMAGE:illust_a]]</p>"
                                             "<h2>자주 묻는 질문</h2>", "tags": ["a", "b"]})
    assert f["title_type"] == "기준형" and f["tables"] == 1 and f["h2"] == 2 and f["faq"] and f["images"] == 1
    assert f["image_style"] == "watercolor" and f["title_question"]
    assert features.history_fields({"lab_topic": " 청약 ", "lab_mode": "탐색", "title": "x"})["lab_topic"] == "청약"


# ---------------------------------------------------------------- 통계 화면 매칭

def test_match_posts_from_json_and_text():
    posts = [{"url": url(1), "title": "연봉 5천, 실수령액 얼마일까?"},
             {"url": url(2), "title": "청약 가점, 몇 점이면 될까?"},
             {"url": url(3), "title": "국민연금 수령액, 평균은 얼마일까?"}]
    cap = stats.Capture(
        responses=[{"url": "https://x/api/rank", "json": {"result": {"list": [
            {"logNo": 224000000001, "title": "연봉 5천, 실수령액 얼마일까?", "cv": 120, "commentCount": 3, "rank": 1},
            {"logNo": "224000000002", "title": "청약 가점", "viewCount": "1,050"}]}}},
                   {"url": "https://x/api/daily", "json": [{"title": "연봉 5천, 실수령액 얼마일까?", "pv": 15}]}],
        pages=[{"url": "https://x/stat", "text": "1\n국민연금 수령액, 평균은 얼마일까?\n2026.10.02\n87\n"}])
    got = stats.match_posts(cap, posts)
    assert got[stats.post_key(url(1))]["views"] == 120            # 기간(15)보다 큰 누적 값을 쓴다
    assert got[stats.post_key(url(2))]["views"] == 1050           # 글 번호로 찾고, 문자열 숫자도 읽는다
    assert got[stats.post_key(url(3))]["views"] == 87             # 화면 글자: 순위·날짜를 건너뛴다


def test_loose_json_and_id_tokens():
    assert stats._loose_json('cb({"a": 1});') == {"a": 1}
    assert stats._loose_json(")]}',\n[1, 2]") == [1, 2]
    assert stats._loose_json("<html>") is None
    assert "224000000001" in stats.id_tokens("https://blog.naver.com/a/224000000001")
    assert "123" in stats.id_tokens("https://eskimo.tistory.com/123")


# ---------------------------------------------------------------- 점수·판정

def _entries(specs):
    """specs: [(topic, published_day, mode)]"""
    return [{"date": day(d), "title": f"글{i}", "url": url(i), "source": "autopost", "lab_topic": t, "lab_mode": m,
             "lab": {"image_style": "base"}}
            for i, (t, d, m) in enumerate(specs)]


def _rows(entries, views_by_index, measured_on):
    """measured_on 날짜에 각 글의 누적 조회수를 기록한 지표 한 줄."""
    return {"date": measured_on, "posts": {stats.post_key(e["url"]): {"views": views_by_index[i]}
                                           for i, e in enumerate(entries) if i in views_by_index}}


def test_judge_statuses(cfg):
    entries = _entries([("A", 0, "탐색"), ("A", 1, "시험 계속"), ("A", 2, "시험 계속"),
                        ("B", 0, "탐색"), ("B", 1, "시험 계속"), ("B", 2, "시험 계속"),
                        ("C", 0, "기본"), ("C", 1, "기본"), ("C", 2, "기본")])
    # 각 글이 7일째 되는 날 기록이 있게 만든다
    rows = [_rows(entries, {i: v for i, v in enumerate([300, 280, 320, 20, 10, 15, 100, 90, 110]) if entries[i]["date"] == day(d)},
                  day(d + 7)) for d in range(3)]
    table = scoring.post_table("invest", entries, rows, day(20), {})
    verdicts, channel = scoring.judge(table, cfg, gain=500)
    by = {v["topic"]: v for v in verdicts}
    assert channel == "정상"
    assert by["A"]["status"] == "promising" and by["B"]["status"] == "dead" and by["C"]["status"] == "neutral"
    # 채널 점검(조회 증가가 거의 없음)이면 무덤 대신 보류
    verdicts, channel = scoring.judge(table, cfg, gain=3)
    assert {v["topic"]: v for v in verdicts}["B"]["status"] == "hold" and "채널 점검" in channel
    # 검색 상위 10위 입질이 있으면 무덤에 넣지 않는다
    for p in table:
        if p["topic"] == "B":
            p["best_rank"] = 4
    verdicts, _ = scoring.judge(table, cfg, gain=500)
    assert {v["topic"]: v for v in verdicts}["B"]["status"] == "neutral"


def test_judge_needs_data(cfg):
    verdicts, channel = scoring.judge([], cfg, gain=None)
    assert verdicts == [] and "데이터 부족" in channel


def test_views_at_age_and_health():
    s = [(date(2026, 10, 3), 10), (date(2026, 10, 8), 50), (date(2026, 10, 9), 55)]
    assert scoring.views_at_age(s, date(2026, 10, 1), 7) == 50
    assert scoring.views_at_age(s, date(2026, 10, 1), 30) is None
    rows = [{"date": "2026-10-01", "posts": {"a": {"views": 10}}}, {"date": "2026-10-20", "posts": {"a": {"views": 40}, "b": {"views": 5}}}]
    assert scoring.health(rows, "2026-10-20") == 35


def test_tistory_topic_mapping(tmp_path):
    (tmp_path / "tistory_fix_topics.json").write_text(json.dumps({"topics": [{"id": "ps-x", "tool": "PowerShell"}]}), encoding="utf-8")
    (tmp_path / "tistory_topics.json").write_text(json.dumps({"topics": [{"id": "asset"}]}), encoding="utf-8")
    maps = scoring.topic_maps(tmp_path)
    assert scoring.topic_of("tistory", {"source": "autopost", "topic_id": "ps-x"}, maps) == "PowerShell 오류"
    assert scoring.topic_of("tistory", {"source": "autopost", "topic_id": "asset"}, maps) == scoring.STATS_BUCKET
    assert scoring.topic_of("tistory", {"source": "rss"}, maps) == scoring.OWN


# ---------------------------------------------------------------- 오늘의 방향

def test_plan_modes(cfg):
    led = store.empty_ledger()
    # 탐색으로 1편 쓴 주제는 시험 글 3편을 채울 때까지 이어 쓴다
    entries = _entries([("새 주제", 0, "탐색")])
    p = brief.plan("invest", cfg, led, entries)
    assert p["mode"] == "시험 계속" and p["topic"] == "새 주제" and p["done"] == 1
    # 이어 쓰지 못하고 다른 주제 글이 3편 나오면 시험을 접는다
    stale = _entries([("새 주제", 0, "탐색"), ("Y", 1, "기본"), ("Y", 2, "기본"), ("Y", 3, "기본")])
    assert brief.plan("invest", cfg, led, stale)["mode"] != "시험 계속"
    # 시험이 끝났고 유망 주제가 없으면: 10편 중 앞 3편은 탐색, 나머지는 기본
    entries = _entries([("X", i, "기본") for i in range(3)])
    assert brief.plan("invest", cfg, led, entries)["mode"] == "기본"
    entries = _entries([("X", i, "기본") for i in range(10)])
    assert brief.plan("invest", cfg, led, entries)["mode"] == "탐색"
    led["topics"]["X"] = {"status": "promising", "ratio": 1.8, "keywords": ["연봉 실수령액 표"]}
    entries = _entries([("X", i, "기본") for i in range(5)])
    assert brief.plan("invest", cfg, led, entries) == {"mode": "집중", "topic": "", "exploit": ["X"]}


def test_brief_text_and_graveyard_block(cfg):
    led = store.empty_ledger()
    led["graveyard"].append({"name": "코인 투자자 수", "reason": "시험 글 3편 점수 0.2"})
    led["explore_queue"].append({"name": "청약 가점", "keywords": ["청약 가점 계산"], "demand": 1.4, "why": "가을 청약"})
    store.save_ledger(cfg, "invest", led)
    history.save(cfg.history_file("invest"), _entries([("X", i, "기본") for i in range(10)]))
    store.save_learned(cfg, "invest", "# 플레이북\n- 표를 앞에 둔 글이 잘 됐다", "2026-10-20")
    assert "오늘 차례: 기본" in brief.for_blog("invest", "2026-10-20", cfg=cfg)     # 조회수를 아직 못 읽으면 탐색 보류
    store.append_metrics(cfg, "invest", {"date": "2026-10-19", "posts": {}, "matched": 4})
    text = brief.for_blog("invest", "2026-10-20", cfg=cfg)
    assert "오늘 차례: 탐색" in text and "청약 가점" in text and "코인 투자자 수" in text
    assert "IMAGE_STYLE_ID=base" in text and styles.STYLES["invest"]["base"] in text
    assert "표를 앞에 둔 글" in text and '"lab_topic"' in text
    assert "무덤" in brief.check_post("invest", {"lab_topic": "코인 투자자수 통계"}, cfg)
    assert brief.check_post("invest", {"lab_topic": "연봉 실수령액"}, cfg) == ""
    off = LabConfig(**{**cfg.__dict__, "blogs": []})
    assert brief.for_blog("invest", "2026-10-20", cfg=off) == ""


def test_queue_order_drops_graveyard_and_boosts_hot(cfg):
    from tistory_autopost.topics import Candidate
    (cfg.history_dir).mkdir(parents=True, exist_ok=True)
    (cfg.history_dir / "tistory_fix_topics.json").write_text(json.dumps({"topics": [
        {"id": "a", "tool": "Git"}, {"id": "b", "tool": "Python"}, {"id": "c", "tool": "Excel"}]}), encoding="utf-8")
    led = store.empty_ledger()
    led["graveyard"].append({"name": "Excel 오류", "reason": "x"})
    led["topics"]["Python 오류"] = {"status": "promising"}
    store.save_ledger(cfg, "tistory", led)
    ranked = [Candidate({"id": "a"}, 30, "p"), Candidate({"id": "b"}, 20, "p"), Candidate({"id": "c"}, 40, "p")]
    out = brief.queue_order("tistory", ranked, cfg)
    assert [c.topic["id"] for c in out] == ["b", "a"]


# ---------------------------------------------------------------- 화풍 실험

def test_style_experiment_cycle():
    led = store.empty_ledger()
    exp = styles.start("invest", led, "2026-10-01")
    assert exp["arms"] == ["base", "watercolor"] and exp["post_until"] == "2026-10-14"
    seq = [styles.arm_for(led, day(i)) for i in range(4)]
    assert set(seq) == {"base", "watercolor"} and seq[0] != seq[1]
    assert styles.arm_for(led, day(2), slot=1) != styles.arm_for(led, day(2), slot=2)   # 하루 두 편이면 서로 다르게
    assert styles.arm_for(led, "2026-10-30") == "base"       # 기간 밖은 채택된 화풍
    assert styles.decide({"base": {"n": 5, "ratio": 1.0}, "watercolor": {"n": 5, "ratio": 1.3}}, ["base", "watercolor"])[0] == "watercolor"
    assert styles.decide({"base": {"n": 5, "ratio": 1.0}, "watercolor": {"n": 5, "ratio": 1.1}}, ["base", "watercolor"])[0] == "base"
    assert styles.decide({"base": {"n": 2, "ratio": 1.0}, "watercolor": {"n": 5, "ratio": 3}}, ["base", "watercolor"])[0] is None
    led["experiments_done"].append({"var": "image_style", "arms": ["base", "watercolor"]})
    led["experiment"] = None
    assert styles.next_challenger("invest", led) == "isometric"


# ---------------------------------------------------------------- 주간 리뷰

def _seed_review(cfg):
    entries = _entries([("A", 0, "탐색"), ("A", 1, "시험 계속"), ("A", 2, "시험 계속"),
                        ("B", 0, "탐색"), ("B", 1, "시험 계속"), ("B", 2, "시험 계속")])
    history.save(cfg.history_file("invest"), entries)
    views = [300, 280, 320, 20, 10, 15]
    store.append_metrics(cfg, "invest", {"date": day(0), "posts": {}})
    for d in range(3):
        store.append_metrics(cfg, "invest", _rows(entries, {i: views[i] for i in range(6) if entries[i]["date"] == day(d)}, day(d + 7)))
    # 판정 날: 모든 글 누적 조회(채널 정상)
    store.append_metrics(cfg, "invest", _rows(entries, {i: v * 2 for i, v in enumerate(views)}, day(20)))
    return entries


def test_review_without_claude_updates_ledger(cfg):
    _seed_review(cfg)
    res = review.run("invest", cfg, day(20), use_claude=False, inbox_file=cfg.history_dir / "inbox.json")
    led = store.load_ledger(cfg, "invest")
    assert led["topics"]["A"]["status"] == "promising"
    assert [g["name"] for g in led["graveyard"]] == ["B"]
    assert led["experiment"]["arms"] == ["base", "watercolor"]       # 채널 정상 + 점수 있음 → 화풍 실험 시작
    assert "성장 실험실" in res["report"] and "무덤 1개" in res["report"]
    assert (cfg.output_dir / "invest" / f"review-{day(20)}" / "review_input.json").exists()
    pushed = LabConfig(**{**cfg.__dict__, "push_report": True})
    review.run("invest", pushed, day(21), use_claude=False, inbox_file=cfg.history_dir / "inbox.json", idents=["myblog"])
    weekly = (cfg.diagnostics_dir / "invest" / "weekly.md").read_text(encoding="utf-8")
    assert "주간 보고" in weekly and "myblog" not in weekly and "글0" not in weekly


def test_review_with_claude_applies_result_and_limits_writes(cfg, monkeypatch):
    from naver_autopost import generate
    _seed_review(cfg)
    seen = {}

    def fake(c, prompt, log_file, light=False, tools=None, permission_mode="acceptEdits"):
        seen.update(prompt=prompt, tools=tools, mode=permission_mode)
        out = log_file.parent / "review.json"
        out.write_text(json.dumps({"funnel": {"stage": "수요", "evidence": "순위 3위인데 조회 적음"},
                                   "report": "다음 주는 A 주제 집중"}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(generate, "_run_claude", fake)
    res = review.run("invest", cfg, day(20), inbox_file=cfg.history_dir / "inbox.json")
    assert seen["mode"] == "default" and "/growth-lab-review" in seen["prompt"]
    assert not any(t.startswith("Bash") for t in seen["tools"]) and any(t.startswith("Write(") for t in seen["tools"])
    assert "막힌 곳: 수요" in res["report"] and "A 주제 집중" in res["report"]


def test_apply_review_result(cfg):
    led = store.empty_ledger()
    led["topics"]["A"] = {"status": "promising", "keywords": ["기존"]}
    led["graveyard"].append({"name": "코인 투자자 수", "reason": "x"})
    led["proposals"].append({"id": 1, "text": "제목에 숫자 조건을 넣는다", "status": "rejected"})
    led["next_proposal_id"] = 2
    result = {
        "topic_keywords": {"A": ["연봉 실수령액 표"], "없는 주제": ["x"]},
        "explore_candidates": [{"name": "청약 가점", "keywords": ["청약 가점 계산"], "why": "w"},
                               {"name": "코인 투자자수", "keywords": ["코인"]},
                               {"name": "아무도 안 찾는 주제", "keywords": ["zzz"]}],
        "learned_md": "# 투자 플레이북\n## 통한 것\n- 표를 첫 화면에 둔 글(3편)이 중간값의 1.8배\n## 안 통한 것\n- 뉴스형 제목(2편, 가설)",
        "proposals": [{"text": "제목에 숫자 조건을 넣는다", "evidence": "e"}, {"text": "발행을 저녁 8시로", "evidence": "e"}],
    }
    fake = lambda body, cid, sec: {"results": [  # noqa: E731
        {"title": "__anchor__", "data": [{"ratio": 50}] * 3},
        {"title": "청약 가점", "data": [{"ratio": 70}] * 3},
        {"title": "아무도 안 찾는 주제", "data": [{"ratio": 1}] * 3}]}
    cfg2 = LabConfig(**{**cfg.__dict__, "naver_search_id": "id", "naver_search_secret": "sec"})
    notes = review.apply_review("invest", cfg2, led, result, "2026-10-20", demand_post=fake)
    assert led["topics"]["A"]["keywords"][:2] == ["연봉 실수령액 표", "기존"]
    assert [c["name"] for c in led["explore_queue"]] == ["청약 가점"] and led["explore_queue"][0]["demand"] == 1.4
    assert any("수요가 거의 없는" in n for n in notes)
    assert [p["text"] for p in led["proposals"] if p["status"] == "pending"] == ["발행을 저녁 8시로"]
    assert "표를 첫 화면" in store.load_learned(cfg2, "invest")


def test_approved_rule_survives_learned_rewrite(cfg):
    store.save_learned(cfg, "invest", "# v1", "2026-10-01")
    store.add_approved_rule(cfg, "invest", "도입에서 결론 숫자를 먼저 쓴다", "2026-10-02")
    store.save_learned(cfg, "invest", "# v2\n- 새로 배운 것", "2026-10-09")
    text = store.load_learned(cfg, "invest")
    assert "# v2" in text and "도입에서 결론 숫자를 먼저 쓴다" in text and "# v1" not in text
    assert (cfg.data_dir / "backup" / "learned_invest_2026-10-09.md").exists()


def test_telegram_commands_flow(cfg):
    updates = [{"update_id": 5, "message": {"chat": {"id": 1}, "text": "승인 투1"}},
               {"update_id": 6, "message": {"chat": {"id": 1}, "text": "화제 연봉 논쟁"}},
               {"update_id": 7, "message": {"chat": {"id": 2}, "text": "승인 투2"}}]
    assert inbox.parse_updates(updates, "1", "화제")[0] == ["연봉 논쟁"]
    cmds = inbox.parse_commands(updates, "1")
    assert cmds == [{"verb": "승인", "prefix": "투", "id": 1, "update_id": 5}]
    box = cfg.history_dir / "inbox.json"
    box.parent.mkdir(parents=True, exist_ok=True)
    box.write_text(json.dumps({"offset": 8, "tips": [], "commands": [{**cmds[0], "done": ""}]}), encoding="utf-8")
    led = store.empty_ledger()
    led["proposals"].append({"id": 1, "text": "표를 첫 화면에 둔다", "status": "pending"})
    notes = review.handle_commands("invest", cfg, led, "2026-10-20", box)
    assert led["proposals"][0]["status"] == "approved" and notes
    assert "표를 첫 화면에 둔다" in store.approved_rules(store.load_learned(cfg, "invest"))
    assert inbox.pending_commands(box) == []


# ---------------------------------------------------------------- 수집·순위·수요

def test_search_rank_and_check():
    items = {"items": [{"link": "https://blog.naver.com/other/1"}, {"link": "https://blog.naver.com/myblog/224000000001?x"}]}
    fetch = lambda u, h: json.dumps(items)  # noqa: E731
    got = rank.search_rank("연봉 실수령액", url(1), "naver", "id", "sec", fetch)
    assert got == {"query": "연봉 실수령액", "blog": 2}
    entries = [{"date": "2026-10-10", "url": url(1), "tags": ["연봉실수령액"]},
               {"date": "2026-01-01", "url": url(2), "tags": ["오래된글"]}]
    out = rank.check(entries, "naver", "id", "sec", "2026-10-20", fetch=fetch)
    assert list(out) == [stats.post_key(url(1))]
    assert rank.check(entries, "naver", "", "", "2026-10-20") == {}


def test_demand_compare_errors():
    assert "_error" in demand.compare({"a": ["b"]}, "anchor", "", "")
    fake = lambda body, cid, sec: {"results": [{"title": "__anchor__", "data": [{"ratio": 20}]},  # noqa: E731
                                               {"title": "a", "data": [{"ratio": 40}]}]}
    assert demand.compare({"a": ["b"]}, "anchor", "id", "sec", date(2026, 10, 20), fake) == {"a": 2.0}


def test_collect_writes_one_row_per_day(cfg):
    history.save(cfg.history_file("invest"), [{"date": "2026-10-15", "title": "연봉 5천, 실수령액 얼마일까?",
                                               "url": url(1), "tags": ["연봉실수령액"], "source": "autopost"}])
    cap = stats.Capture(responses=[{"url": "u", "json": [{"logNo": "224000000001", "cv": 42}]}])
    fetch = lambda u, h: json.dumps({"items": [{"link": url(1)}]})  # noqa: E731
    cfg2 = LabConfig(**{**cfg.__dict__, "naver_search_id": "id", "naver_search_secret": "sec"})
    for _ in range(2):
        snap = metrics.collect("invest", cfg2, "2026-10-20", capture_fn=lambda: cap, rank_fetch=fetch)
    rows = store.load_metrics(cfg2, "invest")
    assert len(rows) == 1 and snap["matched"] == 1
    assert rows[0]["posts"][stats.post_key(url(1))] == {"views": 42, "src": "cv", "rank": {"blog": 1}, "query": "연봉실수령액"}


def test_diagnose_shape_hides_values():
    s = diagnose.shape({"result": {"list": [{"title": "비밀 제목", "cv": 3}], "2026-10-01": 5},
                        "byKeyword": {"연봉 실수령액": 12}})
    dumped = json.dumps(s, ensure_ascii=False)
    assert "비밀" not in dumped and "연봉" not in dumped and "2026" not in dumped
    assert s["result"]["__map__"] == 2
    assert diagnose._path_only("https://admin.blog.naver.com/myblog/stat/224000000001/%EC%97%B0", "myblog") \
        == "https://admin.blog.naver.com/<BLOG>/stat/<N>/<x>"


# ---------------------------------------------------------------- 글쓰기 연결

def test_writer_prompt_gets_lab_brief(monkeypatch, tmp_path):
    from naver_autopost import generate
    from naver_autopost.config import Config
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("LAB_BLOGS", "invest")
    seen = {}

    def fake(c, prompt, log_file, light=False, **kw):
        seen["p"] = prompt
        (tmp_path / "out" / "post.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(generate, "_run_claude", fake)
    generate.write_post(Config.load("invest"), tmp_path / "out", "2026-10-20")
    assert "[성장 실험실 안내]" in seen["p"] and "IMAGE_STYLE_ID=" in seen["p"]
    generate.write_post(Config.load("edu"), tmp_path / "out", "2026-10-20")
    assert "[성장 실험실 안내]" not in seen["p"]


# ---------------------------------------------------------------- 네이버 일별 글 조회수(열 모양 표)

def _rank_json(rows):
    """네이버 조회수 순위 응답 모양: rows가 열(column)별 목록."""
    cols = {"date": [], "cv": [], "rank": [], "title": [], "uri": [], "createDate": []}
    for i, (title, uri, cv) in enumerate(rows, 1):
        for k, v in zip(cols, ["2026-10-24", cv, i, title, uri, "2026-10-20"]):
            cols[k].append(v)
    return {"statusCode": 200, "message": "ok", "result": {"statDataList": [{"dataId": "x", "data": {
        "columnInfo": list(cols), "rows": cols}, "utime": "t"}]}}


def test_columnar_rows_are_matched():
    posts = [{"url": url(1), "title": "연봉 5천, 실수령액 얼마일까?"}, {"url": url(2), "title": "청약 가점, 몇 점이면 될까?"}]
    cap = stats.Capture(responses=[{"url": "https://blog.stat.naver.com/api/blog/rank/cvContentPc",
                                    "json": _rank_json([("연봉 5천, 실수령액 얼마일까?", "/myblog/224000000001", 37),
                                                        ("다른 글", "/myblog/224000000099", 5)])}])
    got = stats.match_posts(cap, posts)
    assert got[stats.post_key(url(1))]["views"] == 37 and stats.post_key(url(2)) not in got


class _Resp:
    def __init__(self, data):
        self.data = data

    def text(self):
        return json.dumps(self.data, ensure_ascii=False)


class _Ctx:
    """ctx.request.get만 흉내: startDate별로 다른 조회수를 돌려준다."""
    def __init__(self, by_day):
        self.by_day, self.urls = by_day, []
        self.request = self

    def get(self, u, headers=None):
        self.urls.append(u)
        day = dict(urllib.parse.parse_qsl(u.split("?", 1)[1]))["startDate"]
        return _Resp(_rank_json(self.by_day.get(day, [])))


def test_fetch_daily_replays_page_request_per_day():
    seen = {"url": "https://blog.stat.naver.com/api/blog/rank/cvContentPc",
            "query": "timeDimension=DATE&startDate=2026-10-25&exclude=&_=1", "json": {}}
    cap = stats.Capture(responses=[seen])
    ctx = _Ctx({"2026-10-23": [("연봉 5천, 실수령액 얼마일까?", "/myblog/224000000001", 10)],
                "2026-10-24": [("연봉 5천, 실수령액 얼마일까?", "/myblog/224000000001", 4)]})
    stats.fetch_daily(ctx, cap, ["2026-10-23", "2026-10-24"])
    assert sorted(cap.daily) == ["2026-10-23", "2026-10-24"]
    assert all("timeDimension=DATE" in u and "exclude=" in u for u in ctx.urls)
    views = stats.daily_views(cap, [{"url": url(1), "title": "연봉 5천, 실수령액 얼마일까?"}])
    assert views == {stats.post_key(url(1)): {"2026-10-23": 10, "2026-10-24": 4}}
    # 화면 요청이 없으면 이유를 남기고 아무것도 받지 않는다
    empty = stats.Capture()
    stats.fetch_daily(ctx, empty, ["2026-10-23"])
    assert not empty.daily and empty.errors


def test_daily_merge_and_scoring(cfg):
    k = stats.post_key(url(1))
    store.merge_daily(cfg, "invest", {k: {day(0): 5, day(1): 7}}, [day(0), day(1)])
    data = store.merge_daily(cfg, "invest", {}, [day(1)])          # 다시 받은 날 순위에 없으면 0으로 본다
    assert data["posts"][k] == {day(0): 5} and day(1) in data["fetched"]
    store.merge_daily(cfg, "invest", {k: {d: 10 for d in [day(i) for i in range(2, 9)]}}, [day(i) for i in range(2, 9)])
    daily = store.load_daily(cfg, "invest")
    entry = {"date": day(0), "title": "t", "url": url(1), "source": "autopost", "lab_topic": "A"}
    table = scoring.post_table("invest", [entry], [], day(20), {}, daily)
    assert table[0]["v1"] == 5 + 0 + 10 * 6 and table[0]["v2"] is None   # 14일째까지 받은 날이 모자라면 판정 안 함
    assert table[0]["views_now"] == 75
    assert scoring.health_daily(daily, day(9)) == 75 - 0 and scoring.health_daily({"fetched": [], "posts": {}}, day(9)) is None


def test_collect_uses_daily_sum_as_views(cfg):
    history.save(cfg.history_file("invest"), [{"date": "2026-10-20", "title": "연봉 5천, 실수령액 얼마일까?",
                                               "url": url(1), "source": "autopost"}])
    cap = stats.Capture(responses=[{"url": "https://blog.stat.naver.com/api/blog/rank/cvContentPc",
                                    "json": _rank_json([("연봉 5천, 실수령액 얼마일까?", "/myblog/224000000001", 3)])}],
                        daily={"2026-10-23": _rank_json([("연봉 5천, 실수령액 얼마일까?", "/myblog/224000000001", 8)]),
                               "2026-10-24": _rank_json([("연봉 5천, 실수령액 얼마일까?", "/myblog/224000000001", 6)])})
    snap = metrics.collect("invest", cfg, "2026-10-25", capture_fn=lambda: cap)
    assert snap["posts"][stats.post_key(url(1))]["views"] == 14 and snap["posts"][stats.post_key(url(1))]["src"] == "daily"
    assert metrics.days_to_fetch(cfg, "invest", "2026-10-25")[-2:] == ["2026-10-24", "2026-10-25"]
    assert "2026-10-23" not in metrics.days_to_fetch(cfg, "invest", "2026-10-25")
    assert len(metrics.days_to_fetch(cfg, "invest", "2026-10-25")) == metrics.DAILY_BACKFILL_DAYS - 1


def test_diagnose_query_shape():
    assert diagnose._query_shape("timeDimension=DATE&startDate=2026-10-25&exclude=&_=17") == {
        "timeDimension": "DATE", "startDate": "9999-99-99", "exclude": "", "_": "99"}


# ---------------------------------------------------------------- 텔레그램 없이 결정하기

def test_repo_decisions_apply_once_with_edited_text(cfg):
    led = store.empty_ledger()
    led["proposals"] += [{"id": 1, "text": "도입에 결론 숫자", "status": "pending"},
                         {"id": 2, "text": "발행 시각 20시", "status": "pending"}]
    cfg.history_dir.mkdir(parents=True, exist_ok=True)
    (cfg.history_dir / review.DECISIONS_FILE).write_text(json.dumps({"decisions": [
        {"blog": "invest", "id": 1, "verb": "승인", "text": "도입 첫 문장에 결론 숫자를 쓴다"},
        {"blog": "invest", "id": 2, "verb": "거절"},
        {"blog": "tistory", "id": 1, "verb": "승인"}]}, ensure_ascii=False), encoding="utf-8")
    notes = review.apply_repo_decisions("invest", cfg, led, "2026-10-26")
    assert len(notes) == 2 and [p["status"] for p in led["proposals"]] == ["approved", "rejected"]
    assert "도입 첫 문장에 결론 숫자를 쓴다" in store.approved_rules(store.load_learned(cfg, "invest"))
    assert review.apply_repo_decisions("invest", cfg, led, "2026-10-27") == []        # 같은 결정은 한 번만


def test_weekly_report_hides_titles_urls_and_ids(cfg):
    led = store.empty_ledger()
    led["proposals"].append({"id": 3, "text": "「연봉 5천, 실수령액 얼마일까?」처럼 조건을 앞에", "status": "pending",
                             "evidence": "https://blog.naver.com/secretid/224000000001 조회 3배"})
    led["graveyard"].append({"name": "코인 투자자 수", "reason": "점수 0.3"})
    verdicts = [{"topic": "연봉 실수령액", "status": "promising", "ratio": 1.8, "evaluated": 3, "posts": 3, "best_rank": 4}]
    out = review.write_weekly("invest", cfg, led, verdicts, "정상", {"report": "secretid 블로그 요약"}, "2026-10-25",
                              ["연봉 5천, 실수령액 얼마일까?"], ["secretid"])
    text = out.read_text(encoding="utf-8")
    assert "연봉 5천, 실수령액 얼마일까?" not in text and "secretid" not in text and "blog.naver.com" not in text
    assert "**투3**" in text and "연봉 실수령액 | 유망 | 1.8" in text and "코인 투자자 수" in text


def test_cli_approve(cfg, monkeypatch, capsys):
    from growth_lab import __main__ as cli
    led = store.empty_ledger()
    led["proposals"].append({"id": 5, "text": "표를 첫 화면에", "status": "pending"})
    store.save_ledger(cfg, "tistory", led)
    assert cli._decide(cfg, "티5", "승인", "", "2026-10-26") == 0
    assert store.load_ledger(cfg, "tistory")["proposals"][0]["status"] == "approved"
    assert cli._decide(cfg, "티5", "승인", "", "2026-10-26") == 1          # 이미 정한 제안
    assert cli._decide(cfg, "5", "승인", "", "2026-10-26") == 1            # 블로그 글자 없음
