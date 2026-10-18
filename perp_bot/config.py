"""봇 설정. 위험 한도는 코드에 고정하고, .env로는 더 보수적인 쪽으로만 바꿀 수 있다."""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace

# 사용자와 정한 한도(이보다 느슨하게는 못 바꾼다)
HARD_MAX_LEVERAGE = 10.0
HARD_STOP_EQUITY = 400.0     # 잔고가 이 아래로 내려가면 전부 정리하고 영구 정지
START_EQUITY = 600.0


@dataclass(frozen=True)
class BotConfig:
    coins: tuple[str, ...] = ("BTC", "ETH", "SOL")
    interval: str = "4h"
    bars_per_day: int = 6
    # 신호(4시간 봉 기준): 1·2·4주 수익률 ÷ 변동성의 평균 = 추세 강도
    horizons: tuple[int, ...] = (42, 84, 168)
    vol_window: int = 180
    ema_window: int = 200
    entry_x: float = 0.5          # 대시보드 경향 분석과 같은 기준: 확인된 추세만
    exit_x: float = 0.0           # 추세 강도가 0을 지나 반대로 가면 정리
    allow_short: bool = True
    atr_window: int = 14
    stop_atr: float = 2.5         # 처음 손절 = 진입가 ∓ 2.5×ATR(거래소에 미리 걸어 둘 주문)
    trail_atr: float = 3.0        # 추적 손절 = 진입 뒤 최고(최저) 종가 ∓ 3×ATR
    # 위험
    risk_per_trade: float = 0.02  # 손절에 걸리면 잃는 돈 = 잔고의 2%
    max_leverage: float = HARD_MAX_LEVERAGE   # 전체 포지션 합계 / 잔고 상한
    max_coin_leverage: float = 5.0            # 코인 하나당 상한
    daily_loss_limit: float = 0.06            # 하루 6% 넘게 잃으면 그날 새 진입 금지
    stop_equity: float = HARD_STOP_EQUITY
    start_equity: float = START_EQUITY
    # 비용(Hyperliquid 기본 등급 테이커 수수료 + 체결 미끄러짐 가정)
    fee: float = 0.00045
    slippage: float = 0.0003
    extra: dict = field(default_factory=dict, compare=False)

    @classmethod
    def load(cls) -> "BotConfig":
        env = os.environ.get
        c = cls()
        lev = min(float(env("PERP_MAX_LEVERAGE", c.max_leverage)), HARD_MAX_LEVERAGE)
        risk = min(float(env("PERP_RISK_PER_TRADE", c.risk_per_trade)), 0.02)
        stop_eq = max(float(env("PERP_STOP_EQUITY", c.stop_equity)), HARD_STOP_EQUITY)
        return replace(c, max_leverage=lev, risk_per_trade=risk, stop_equity=stop_eq,
                       max_coin_leverage=min(c.max_coin_leverage, lev))
