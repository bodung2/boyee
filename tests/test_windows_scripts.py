"""집 PC(Windows PowerShell 5.1·cmd)가 그대로 읽을 수 있는 스크립트 파일인지 확인한다."""
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


@pytest.mark.parametrize("path", sorted(SCRIPTS.glob("*.ps1")), ids=lambda p: p.name)
def test_powershell_scripts_with_korean_keep_utf8_bom(path):
    """PowerShell 5.1은 BOM이 없는 UTF-8을 ANSI(CP949)로 읽어 한글이 깨지고 문법 오류가 난다."""
    data = path.read_bytes()
    if any(b > 127 for b in data):
        assert data.startswith(b"\xef\xbb\xbf"), f"{path.name}: 파일 맨 앞에 UTF-8 BOM이 있어야 합니다"


@pytest.mark.parametrize("path", sorted([*SCRIPTS.glob("*.bat"), *SCRIPTS.glob("*.vbs")]), ids=lambda p: p.name)
def test_bat_and_vbs_are_plain_ascii(path):
    """cmd·wscript는 파일을 코드 페이지로 읽으므로 한글 없이 영문만 쓴다."""
    assert path.read_bytes().isascii(), f"{path.name}: 영문(ASCII)만 써야 합니다"
