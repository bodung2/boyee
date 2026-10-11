"""4시간 봉 시뮬레이터. 백테스트와 모의 운용(paper)이 같은 Sim을 쓴다.

봉마다: ① 직전 봉 종가에 정한 주문을 이번 봉 시가에 체결 ② 봉 안에서 손절가를 건드렸는지(고가·저가) 확인
③ 펀딩비 정산 ④ 종가에서 추적 손절 갱신·청산 신호·새 진입 신호 → 다음 봉 시가에 체결
평가 잔고가 stop_equity 이하가 되면 다음 봉 시가에 전부 정리하고 영구 정지한다.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import pandas as pd

from . import strategy
from .config import BotConfig


@dataclass
class Position:
    coin: str
    side: int
    qty: float
    entry: float
    entry_time: str
    stop: float
    risk_usd: float
    best: float
    leverage: float


def _fill(price: float, side: int, c: BotConfig) -> float:
    """사는 쪽은 비싸게, 파는 쪽은 싸게 체결된다고 본다."""
    return price * (1 + side * c.slippage)


@dataclass
class Sim:
    c: BotConfig
    cash: float = 0.0
    pos: dict = field(default_factory=dict)          # coin -> Position
    pending: dict = field(default_factory=dict)      # coin -> ["enter", side, notional, lev, stop_dist] | ["exit", reason]
    trades: list = field(default_factory=list)
    events: list = field(default_factory=list)       # 이번 봉에 일어난 일(알림용)
    day: str | None = None
    day_start_eq: float = 0.0
    kill_pending: bool = False
    killed_at: str | None = None
    last_bar: str | None = None

    def __post_init__(self):
        if not self.cash:
            self.cash = self.c.start_equity
            self.day_start_eq = self.cash

    # ---- 상태 저장(모의 운용) ----
    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k not in ("c", "events")}
        d["pos"] = {k: asdict(p) for k, p in self.pos.items()}
        return d

    @classmethod
    def from_dict(cls, c: BotConfig, d: dict) -> "Sim":
        s = cls(c, cash=d["cash"])
        for k in ("pending", "trades", "day", "day_start_eq", "kill_pending", "killed_at", "last_bar"):
            setattr(s, k, d.get(k, getattr(s, k)))
        s.pos = {k: Position(**p) for k, p in d.get("pos", {}).items()}
        return s

    # ---- 계산 ----
    def _close(self, k: str, price: float, t, reason: str):
        p = self.pos.pop(k)
        px = _fill(price, -p.side, self.c)
        pnl = p.side * p.qty * (px - p.entry) - self.c.fee * p.qty * px
        self.cash += pnl
        tr = {"coin": k, "side": "롱" if p.side > 0 else "숏", "entry_time": p.entry_time, "exit_time": str(t),
              "entry": p.entry, "exit": px, "pnl": pnl, "r": pnl / p.risk_usd if p.risk_usd else 0.0,
              "lev": p.leverage, "reason": reason}
        self.trades.append(tr)
        self.events.append(f"{k} {tr['side']} 정리({reason}) {px:,.2f} 손익 {pnl:+.2f}$")

    def equity(self, prices: dict[str, float]) -> float:
        return self.cash + sum(p.side * p.qty * (prices[k] - p.entry) for k, p in self.pos.items() if k in prices)

    def on_bar(self, t: pd.Timestamp, bars: dict[str, pd.Series], rows: dict[str, pd.Series],
               fund: dict[str, float], ready: bool = True) -> float | None:
        """봉 하나 처리. 정지되면 None."""
        c = self.c
        self.events = []
        if self.killed_at:
            return None
        # ① 시가 체결
        if self.kill_pending:
            for k in list(self.pos):
                if k in bars:
                    self._close(k, bars[k]["open"], t, "잔고 하한 도달 — 전부 정리")
            self.killed_at = str(t)
            self.events.append(f"잔고 {self.cash:.2f}$ — 하한 {c.stop_equity:.0f}$ 도달, 운용 종료")
            self.last_bar = str(t)
            return None
        for k, order in list(self.pending.items()):
            if k not in bars:
                continue
            o = bars[k]["open"]
            if order[0] == "exit" and k in self.pos:
                self._close(k, o, t, order[1])
            elif order[0] == "enter" and k not in self.pos:
                _, side, notional, lev, stop_dist = order
                px = _fill(o, side, c)
                qty = notional / px
                self.cash -= c.fee * notional
                stop = px - side * stop_dist
                self.pos[k] = Position(k, side, qty, px, str(t), stop, qty * stop_dist, px, lev)
                self.events.append(f"{k} {'롱' if side > 0 else '숏'} 진입 {px:,.2f} 크기 {notional:,.0f}$({lev:.1f}배) 손절 {stop:,.2f}")
            self.pending.pop(k)
        # ② 봉 안 손절(거래소에 미리 걸어 둔 손절 주문과 같은 효과)
        for k in list(self.pos):
            if k not in bars:
                continue
            p, b = self.pos[k], bars[k]
            if (p.side > 0 and b["low"] <= p.stop) or (p.side < 0 and b["high"] >= p.stop):
                gap = (p.side > 0 and b["open"] < p.stop) or (p.side < 0 and b["open"] > p.stop)
                self._close(k, b["open"] if gap else p.stop, t, "손절" + ("(갭)" if gap else ""))
        # ③ 펀딩비(롱이 양수 펀딩을 낸다)
        for k, p in self.pos.items():
            if k in bars:
                self.cash -= p.side * p.qty * bars[k]["close"] * fund.get(k, 0.0)
        prices = {k: b["close"] for k, b in bars.items()}
        eq = self.equity(prices)
        d = str(t.date())
        if d != self.day:
            self.day, self.day_start_eq = d, eq
        self.last_bar = str(t)
        if eq <= c.stop_equity:
            self.kill_pending = True
            self.events.append(f"평가 잔고 {eq:.2f}$ ≤ {c.stop_equity:.0f}$ — 다음 봉에 전부 정리하고 종료")
            return eq
        if not ready:
            return eq
        # ④ 종가 판단
        open_notional = sum(p.qty * prices[k] for k, p in self.pos.items() if k in prices)
        no_new = eq < self.day_start_eq * (1 - c.daily_loss_limit)
        for k, row in rows.items():
            if k in self.pos:
                p = self.pos[k]
                p.best = max(p.best, row["close"]) if p.side > 0 else min(p.best, row["close"])
                if not math.isnan(row["atr"]):
                    trail = p.best - p.side * c.trail_atr * row["atr"]
                    p.stop = max(p.stop, trail) if p.side > 0 else min(p.stop, trail)
                if strategy.should_exit(p.side, row, c):
                    self.pending[k] = ["exit", "추세 반전"]
            elif not no_new and k not in self.pending:
                side = strategy.entry_side(row, c)
                if side:
                    sz = strategy.size(side, row["close"], row["atr"], eq, open_notional, c)
                    if sz.notional > 0:
                        self.pending[k] = ["enter", side, sz.notional, sz.leverage, abs(row["close"] - sz.stop)]
                        open_notional += sz.notional
        return eq


def prepare(data: dict[str, pd.DataFrame], fund: dict[str, pd.Series], c: BotConfig):
    ind = {k: strategy.indicators(df, c) for k, df in data.items()}
    idx = pd.DatetimeIndex(sorted(set().union(*[df.index for df in data.values()])))
    fsum = {}
    for k in data:
        f = fund.get(k)
        fsum[k] = (f.resample(c.interval).sum().reindex(idx).fillna(0.0) if f is not None and len(f)
                   else pd.Series(0.0, index=idx))
    return ind, idx, fsum


def run(data: dict[str, pd.DataFrame], fund: dict[str, pd.Series], c: BotConfig) -> Sim:
    ind, idx, fsum = prepare(data, fund, c)
    warm = max(max(c.horizons), c.vol_window, c.ema_window) + 2
    sim = Sim(c)
    sim.eq_hist = {}
    for i, t in enumerate(idx):
        bars = {k: data[k].loc[t] for k in data if t in data[k].index}
        rows = {k: ind[k].loc[t] for k in data if t in ind[k].index}
        eq = sim.on_bar(t, bars, rows, {k: fsum[k].loc[t] for k in data}, ready=i >= warm)
        if eq is None:
            sim.eq_hist[t] = sim.cash
            break
        sim.eq_hist[t] = eq
    return sim


def metrics(sim: Sim, c: BotConfig) -> dict:
    eq = pd.Series(sim.eq_hist).dropna()
    if eq.empty:
        return {}
    days = max((eq.index[-1] - eq.index[0]).days, 1)
    final = float(eq.iloc[-1])
    tr = pd.DataFrame(sim.trades)
    out = {
        "기간": f"{eq.index[0]:%Y-%m-%d} ~ {eq.index[-1]:%Y-%m-%d}",
        "최종 잔고": round(final, 2),
        "총수익": final / c.start_equity - 1,
        "연환산": (final / c.start_equity) ** (365 / days) - 1 if final > 0 else -1.0,
        "최대낙폭": float((eq / eq.cummax() - 1).min()),
        "거래 수": len(tr),
        "운용 종료(잔고 하한)": sim.killed_at or "없음",
    }
    if len(tr):
        wins, loss = tr[tr["pnl"] > 0], tr[tr["pnl"] <= 0]
        out.update({
            "승률": len(wins) / len(tr),
            "평균 R": float(tr["r"].mean()),
            "손익비(PF)": float(wins["pnl"].sum() / -loss["pnl"].sum()) if loss["pnl"].sum() < 0 else float("inf"),
            "평균 레버리지": float(tr["lev"].mean()),
            "최대 레버리지": float(tr["lev"].max()),
            "최장 연속 손실": _streak(tr["pnl"] <= 0),
            "코인별 손익$": {k: round(float(v), 1) for k, v in tr.groupby("coin")["pnl"].sum().items()},
            "롱/숏 손익$": {k: round(float(v), 1) for k, v in tr.groupby("side")["pnl"].sum().items()},
        })
        monthly = eq.resample("ME").last().pct_change().dropna()
        if len(monthly):
            out["최악의 달"] = float(monthly.min())
    return out


def _streak(flags) -> int:
    best = cur = 0
    for f in flags:
        cur = cur + 1 if f else 0
        best = max(best, cur)
    return best
