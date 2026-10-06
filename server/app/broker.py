"""Бумажный (демо) брокер: баланс, открытые позиции, история сделок, P&L.

* Рыночные ордера исполняются по текущей цене ± половина спреда.
* Можно держать несколько позиций (hedging-режим как у MT5) — для ручной торговли.
* Учёт в валюте котировки (для EUR/USD — доллары), без свопов.
"""
from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, asdict, field


@dataclass
class Position:
    id: int
    side: str            # "long" | "short"
    qty: float
    entry_price: float
    entry_time: int
    opened_by: str       # "manual" | "bot"

    def pnl(self, price: float) -> float:
        d = price - self.entry_price
        return self.qty * (d if self.side == "long" else -d)


@dataclass
class Trade:
    id: int
    side: str
    qty: float
    entry_price: float
    exit_price: float
    entry_time: int
    exit_time: int
    pnl: float
    opened_by: str
    closed_by: str


@dataclass
class PaperBroker:
    initial_balance: float = 10_000.0
    half_spread: float = 0.000035          # доля цены
    leverage: float = 30.0
    balance: float = field(init=False)
    positions: list = field(default_factory=list)
    history: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)   # [(t, equity)] на закрытиях свечей
    price: float = 0.0
    time: int = 0

    def __post_init__(self):
        self._ids = itertools.count(1)
        self.balance = self.initial_balance

    # ---------- рыночные данные
    def mark(self, price: float, t: int):
        self.price, self.time = price, t

    def on_candle_close(self, t: int):
        self.equity_curve.append((t, round(self.equity, 2)))
        self.equity_curve = self.equity_curve[-500:]

    # ---------- торговля
    @property
    def unrealized(self) -> float:
        return sum(p.pnl(self.price) for p in self.positions)

    @property
    def equity(self) -> float:
        return self.balance + self.unrealized

    @property
    def margin_used(self) -> float:
        return sum(p.qty * p.entry_price for p in self.positions) / self.leverage

    def open(self, side: str, qty: float, by: str = "manual") -> Position:
        if side not in ("long", "short"):
            raise ValueError("side должен быть long или short")
        if qty <= 0:
            raise ValueError("объём должен быть > 0")
        if self.price <= 0:
            raise ValueError("нет котировки")
        fill = self.price * (1 + self.half_spread if side == "long" else 1 - self.half_spread)
        need = qty * fill / self.leverage
        if self.margin_used + need > self.equity:
            raise ValueError(f"недостаточно маржи: нужно {need:.2f}, свободно {self.equity - self.margin_used:.2f}")
        p = Position(next(self._ids), side, qty, fill, self.time or int(time.time()), by)
        self.positions.append(p)
        return p

    def close(self, pos_id: int, by: str = "manual") -> Trade:
        p = next((x for x in self.positions if x.id == pos_id), None)
        if p is None:
            raise KeyError(f"позиция {pos_id} не найдена")
        fill = self.price * (1 - self.half_spread if p.side == "long" else 1 + self.half_spread)
        pnl = p.pnl(fill)
        self.balance += pnl
        self.positions.remove(p)
        tr = Trade(p.id, p.side, p.qty, p.entry_price, fill, p.entry_time, self.time, pnl, p.opened_by, by)
        self.history.append(tr)
        self.history = self.history[-300:]
        return tr

    def close_all(self, by: str = "manual", side: str | None = None) -> list[Trade]:
        return [self.close(p.id, by) for p in list(self.positions) if side is None or p.side == side]

    def net_side(self) -> str | None:
        net = sum(p.qty if p.side == "long" else -p.qty for p in self.positions)
        return None if abs(net) < 1e-12 else ("long" if net > 0 else "short")

    # ---------- отчёт
    def stats(self) -> dict:
        pnls = [t.pnl for t in self.history]
        wins = [x for x in pnls if x > 0]
        eq = [e for _, e in self.equity_curve] or [self.equity]
        peak, mdd = eq[0], 0.0
        for e in eq:
            peak = max(peak, e)
            mdd = min(mdd, e / peak - 1)
        return {
            "trades": len(pnls),
            "winrate": len(wins) / len(pnls) if pnls else 0.0,
            "realized_pnl": sum(pnls),
            "total_pnl": self.equity - self.initial_balance,
            "return_pct": (self.equity / self.initial_balance - 1) * 100,
            "max_drawdown_pct": mdd * 100,
        }

    def snapshot(self) -> dict:
        return {
            "initial_balance": self.initial_balance,
            "balance": self.balance,
            "equity": self.equity,
            "unrealized_pnl": self.unrealized,
            "margin_used": self.margin_used,
            "price": self.price,
            "positions": [{**asdict(p), "current_price": self.price, "pnl": p.pnl(self.price)} for p in self.positions],
            "history": [asdict(t) for t in reversed(self.history[-100:])],
            "equity_curve": [{"t": t, "equity": e} for t, e in self.equity_curve[-200:]],
            "stats": self.stats(),
        }
