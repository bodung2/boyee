"""모의 운용: 4시간마다 새로 확정된 봉을 받아 Sim에 넣고, 상태를 data/perp/paper_state.json에 저장한다.

실제 주문은 하지 않는다. 체결은 다음 봉 시가 + 미끄러짐으로 가정(백테스트와 같은 규칙).
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from . import hl
from .backtest import Sim, prepare
from .config import BotConfig


def load(path: Path, c: BotConfig) -> Sim:
    if path.exists():
        return Sim.from_dict(c, json.loads(path.read_text(encoding="utf-8")))
    return Sim(c)


def save(path: Path, sim: Sim) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(sim.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def tick(path: Path, c: BotConfig, data: dict[str, pd.DataFrame] | None = None,
         fund: dict[str, pd.Series] | None = None) -> tuple[Sim, list[str]]:
    """아직 처리하지 않은 확정 봉을 모두 처리한다. 반환: (상태, 알림 문장들)."""
    sim = load(path, c)
    if sim.killed_at:
        return sim, [f"운용 종료 상태({sim.killed_at}). 다시 시작하려면 상태 파일을 직접 지워야 한다."]
    if data is None:
        data = {k: hl.candles(k, c.interval, days=90) for k in c.coins}
        fund = {k: hl.funding(k, days=10) for k in c.coins}
    ind, idx, fsum = prepare(data, fund or {}, c)
    last = pd.Timestamp(sim.last_bar) if sim.last_bar else None
    new = [t for t in idx if last is None or t > last]
    if last is None:
        new = new[-1:]  # 처음 시작: 가장 최근 봉 하나만으로 판단(과거를 소급해 매매하지 않음)
    msgs = []
    for t in new:
        bars = {k: data[k].loc[t] for k in data if t in data[k].index}
        rows = {k: ind[k].loc[t] for k in data if t in ind[k].index}
        sim.on_bar(t, bars, rows, {k: fsum[k].loc[t] for k in data})
        msgs += [f"[{t:%m-%d %H:%M}] {e}" for e in sim.events]
        if sim.killed_at:
            break
    save(path, sim)
    return sim, msgs


def status_text(sim: Sim, prices: dict[str, float] | None, c: BotConfig) -> str:
    lines = [f"[코인 선물 모의 운용] 마지막 봉 {sim.last_bar}"]
    eq = sim.equity(prices) if prices else sim.cash
    lines.append(f"평가 잔고 {eq:.2f}$ (시작 {c.start_equity:.0f}$, 하한 {c.stop_equity:.0f}$)")
    for k, p in sim.pos.items():
        side = "롱" if p.side > 0 else "숏"
        now = f" 현재 {prices[k]:,.2f}" if prices and k in prices else ""
        lines.append(f"  {k} {side} {p.qty:.4f}개 진입 {p.entry:,.2f}{now} 손절 {p.stop:,.2f} ({p.leverage:.1f}배)")
    if not sim.pos:
        lines.append("  보유 포지션 없음")
    for k, o in sim.pending.items():
        lines.append(f"  다음 봉 예정: {k} {'진입' if o[0] == 'enter' else '정리'}")
    if sim.killed_at:
        lines.append(f"운용 종료: {sim.killed_at}")
    return "\n".join(lines)
