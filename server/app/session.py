"""Торговая сессия по одному инструменту: поток свечей + модель + брокер + автобот + подписчики WebSocket."""
from __future__ import annotations

import asyncio
import time
from collections import deque

from fastapi import WebSocket

from .broker import PaperBroker
from .feeds import Feed
from .predictor import Predictor


class TradingSession:
    def __init__(self, symbol: str, title: str, timeframe: str, feed: Feed, predictor: Predictor,
                 broker: PaperBroker, default_qty: float, price_digits: int):
        self.symbol, self.title, self.timeframe = symbol, title, timeframe
        self.feed, self.predictor, self.broker = feed, predictor, broker
        self.default_qty = default_qty
        self.price_digits = price_digits
        self.candles: deque = deque(maxlen=600)
        self.forming: dict | None = None
        self.signal = None
        self.signals: deque = deque(maxlen=200)       # журнал рекомендаций
        self.bot_log: deque = deque(maxlen=100)
        self.mode = "manual"                          # manual | auto
        self.auto_qty = default_qty
        self.subscribers: set[WebSocket] = set()
        self.task: asyncio.Task | None = None
        self.started_at = time.time()
        self.status = "starting"
        self.error: str | None = None

    # ------------------------------------------------------------ жизненный цикл
    async def start(self):
        if hasattr(self.feed, "load_history"):
            try:
                await self.feed.load_history()
            except Exception as e:
                self.status, self.error = "error", f"не удалось загрузить историю: {e}"
        for c in self.feed.history():
            self.candles.append(c)
        if self.candles:
            last = self.candles[-1]
            self.broker.mark(last["c"], last["t"])
            self._update_signal()
        self.task = asyncio.create_task(self._run())

    async def stop(self):
        if self.task:
            self.task.cancel()

    async def _run(self):
        self.status = "running"
        try:
            async for kind, candle in self.feed.stream():
                if kind == "tick":
                    self.forming = candle
                    self.broker.mark(candle["c"], candle["t"])
                    await self.broadcast({"type": "tick", "symbol": self.symbol, "forming": candle,
                                          "account": self._account_brief()})
                else:
                    await self._on_close(candle)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # pragma: no cover
            self.status, self.error = "error", str(e)
            print(f"[{self.symbol}] feed error: {e}")

    async def _on_close(self, candle: dict):
        self.forming = None
        if self.candles and candle["t"] <= self.candles[-1]["t"]:
            return
        self.candles.append(candle)
        self.broker.mark(candle["c"], candle["t"])
        self._score_previous_signal(candle)
        self._update_signal()
        if self.mode == "auto":
            self._bot_step()
        self.broker.on_candle_close(candle["t"])
        await self.broadcast({"type": "candle", "symbol": self.symbol, "candle": candle,
                              "signal": self.signal_dict(), "account": self.broker.snapshot(),
                              "bot_log": list(self.bot_log)[-20:]})

    # ------------------------------------------------------------ модель
    def _update_signal(self):
        s = self.predictor.predict(list(self.candles))
        if s is not None:
            self.signal = s
            self.signals.append({"t": s.based_on, "action": s.action, "p_up": s.p_up,
                                 "expected_return": s.expected_return, "close": self.candles[-1]["c"],
                                 "hit": None})

    def _score_previous_signal(self, candle: dict):
        """Онлайн-проверка: совпало ли направление прошлой рекомендации с фактом."""
        if len(self.signals) == 0:
            return
        last = self.signals[-1]
        if last["hit"] is None and last["t"] < candle["t"]:
            real_up = candle["c"] > last["close"]
            last["hit"] = (last["p_up"] > 0.5) == real_up

    def signal_dict(self) -> dict | None:
        if not self.signal:
            return None
        d = self.signal.to_dict()
        scored = [s for s in self.signals if s["hit"] is not None]
        d["online_hit_rate"] = sum(s["hit"] for s in scored) / len(scored) if scored else None
        d["online_scored"] = len(scored)
        return d

    # ------------------------------------------------------------ автоторговля
    def _bot_step(self):
        """Та же логика, что и в бэктесте: BUY → быть в лонге, SELL → в шорте, HOLD → вне рынка."""
        if not self.signal:
            return
        target = {"BUY": "long", "SELL": "short", "HOLD": None}[self.signal.action]
        current = self.broker.net_side()
        if target == current and (target is None or len(self.broker.positions) == 1):
            return
        closed = self.broker.close_all(by="bot")
        for tr in closed:
            self._log(f"закрыл {tr.side} #{tr.id} по {tr.exit_price:.{self.price_digits}f}, P&L {tr.pnl:+.2f}")
        if target:
            try:
                p = self.broker.open(target, self.auto_qty, by="bot")
                self._log(f"{self.signal.action}: открыл {target} {p.qty:g} по "
                          f"{p.entry_price:.{self.price_digits}f} (уверенность {self.signal.confidence:.0%})")
            except ValueError as e:
                self._log(f"не смог открыть {target}: {e}")

    def _log(self, msg: str):
        self.bot_log.append({"t": self.broker.time, "message": msg})

    def set_mode(self, mode: str, qty: float | None = None):
        if mode not in ("manual", "auto"):
            raise ValueError("mode: manual | auto")
        self.mode = mode
        if qty:
            self.auto_qty = qty
        self._log(f"режим: {'автоторговля' if mode == 'auto' else 'ручная торговля'}")
        if mode == "auto":
            self._bot_step()

    # ------------------------------------------------------------ рассылка
    def _account_brief(self) -> dict:
        b = self.broker
        return {"equity": b.equity, "balance": b.balance, "unrealized_pnl": b.unrealized, "price": b.price,
                "positions": [{"id": p.id, "pnl": p.pnl(b.price)} for p in b.positions]}

    def info(self) -> dict:
        m = self.predictor.meta
        return {"symbol": self.symbol, "title": self.title, "timeframe": self.timeframe,
                "source": self.feed.source, "candle_seconds": self.feed.candle_seconds,
                "price_digits": self.price_digits, "default_qty": self.default_qty,
                "status": self.status, "error": self.error,
                "model": {"name": self.predictor.name, "lookback": m["lookback"], "layers": m["layers"],
                          "hidden": m["hidden"], "p_thr": m["p_thr"], "timeframe": m["timeframe"]}}

    def snapshot(self, limit: int = 300) -> dict:
        return {"type": "snapshot", **self.info(), "mode": self.mode, "auto_qty": self.auto_qty,
                "candles": list(self.candles)[-limit:], "forming": self.forming,
                "signal": self.signal_dict(), "account": self.broker.snapshot(),
                "bot_log": list(self.bot_log)[-20:]}

    async def broadcast(self, msg: dict):
        dead = []
        for ws in list(self.subscribers):
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.subscribers.discard(ws)

    async def push_state(self):
        await self.broadcast({"type": "account", "symbol": self.symbol, "account": self.broker.snapshot(),
                              "mode": self.mode, "auto_qty": self.auto_qty, "bot_log": list(self.bot_log)[-20:],
                              "candle_seconds": self.feed.candle_seconds})
