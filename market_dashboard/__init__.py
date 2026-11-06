"""자산군 모멘텀 대시보드: 추세 강도 × 가속도 사분면, 오늘의 매수 후보, 원화 기준 백테스트."""

import os as _os
import sys as _sys


def _ascii_ca_bundle() -> None:
    """윈도우 사용자 폴더 이름이 한글이면(C:\\Users\\박보영) yfinance가 쓰는 curl_cffi가 인증서 파일을 못 읽어
    야후 접속이 모두 SSLError로 실패한다. 인증서 파일을 영문 경로에 복사해 그쪽을 쓰게 한다."""
    if _sys.platform != "win32" or _os.environ.get("CURL_CA_BUNDLE"):
        return
    try:
        import shutil

        import certifi

        src = certifi.where()
        if src.isascii():
            return
        for base in (_os.environ.get("PROGRAMDATA"), _os.environ.get("PUBLIC"), "C:\\boyee-certs"):
            if not base or not base.isascii():
                continue
            dst = _os.path.join(base, "boyee", "cacert.pem")
            try:
                _os.makedirs(_os.path.dirname(dst), exist_ok=True)
                if not _os.path.exists(dst) or _os.path.getmtime(dst) < _os.path.getmtime(src):
                    shutil.copyfile(src, dst)
            except OSError:
                continue
            _os.environ["CURL_CA_BUNDLE"] = dst
            return
    except Exception:  # noqa: BLE001 - 안 되면 원래대로
        pass


_ascii_ca_bundle()

