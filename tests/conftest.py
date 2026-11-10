import pytest


@pytest.fixture(autouse=True)
def _alerts_outbox(tmp_path, monkeypatch):
    """알림 기록(data/alerts.jsonl)이 테스트 중에 진짜 data/ 폴더에 쌓이지 않게 한다."""
    monkeypatch.setenv("AUTOPOST_ALERTS_FILE", str(tmp_path / "alerts.jsonl"))
