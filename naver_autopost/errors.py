"""외부 서비스 공통 예외."""


class ExternalAccountError(RuntimeError):
    """키·잔액·로그인·사용 한도 문제. 다시 시도해도 소용없으므로 그날 실행을 멈추고 알린다.
    다음 실행은 멈춘 단계부터 이어서 한다."""
