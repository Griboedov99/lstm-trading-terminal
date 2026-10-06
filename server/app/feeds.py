"""Источники котировок. Каждый источник — асинхронный генератор событий:
    ("tick",  forming_candle)   — промежуточное обновление формирующейся свечи
    ("close", closed_candle)    — свеча закрыта
Свеча — dict: t (unix-время открытия, сек), o, h, l, c, v.
"""
from __future__ import annotations

import asyncio
import math
import random
from pathlib import Path
from typing import AsyncIterator

import pandas as pd

TF_SECONDS = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600, "D1": 86400}


def _candle(t, o, h, l, c, v=0.0) -> dict:
    return {"t": int(t), "o": float(o), "h": float(h), "l": float(l), "c": float(c), "v": float(v)}


class Feed:
    """Базовый класс; candle_seconds — сколько реальных секунд длится одна свеча (скорость эмуляции)."""
    source = "base"

    def __init__(self, candle_seconds: float = 2.0, ticks_per_candle: int = 8):
        self.candle_seconds = candle_seconds
        self.ticks_per_candle = ticks_per_candle

    def history(self) -> list[dict]:
        return []

    async def stream(self) -> AsyncIterator[tuple[str, dict]]:  # pragma: no cover
        yield "close", {}


class ReplayFeed(Feed):
    """Воспроизведение исторических свечей с заданной скоростью.

    Внутри свечи генерируются тики по правдоподобной траектории
    open → (low → high | high → low) → close, поэтому формирующаяся свеча «растёт»
    так же, как на реальном терминале, а закрытая свеча совпадает с исторической.
    По умолчанию воспроизводится отложенный (тестовый) участок — модель его не видела.
    """
    source = "replay"

    def __init__(self, csv_path: Path, start_index: int, history_len: int = 300, **kw):
        super().__init__(**kw)
        df = pd.read_csv(csv_path, parse_dates=["timestamp"])
        ts = (df["timestamp"].astype("int64") // 10**9).to_numpy()
        self.rows = [_candle(t, o, h, l, c, v) for t, o, h, l, c, v in
                     zip(ts, df.open, df.high, df.low, df.close, df.volume)]
        self.start = max(history_len, min(start_index, len(self.rows) - 50))
        self.history_len = history_len

    def history(self) -> list[dict]:
        return self.rows[self.start - self.history_len:self.start]

    def _path(self, c: dict) -> list[float]:
        o, h, l, cl = c["o"], c["h"], c["l"], c["c"]
        pts = [o, l, h, cl] if cl >= o else [o, h, l, cl]
        n = self.ticks_per_candle
        out = []
        for i in range(1, n + 1):
            x = i / n * 3
            k = min(int(x), 2)
            frac = x - k
            p = pts[k] + (pts[k + 1] - pts[k]) * frac
            out.append(min(h, max(l, p)))
        return out

    async def stream(self):
        i, offset = self.start, 0
        span = self.rows[-1]["t"] - self.rows[self.start]["t"] + (self.rows[-1]["t"] - self.rows[-2]["t"])
        while True:
            if i >= len(self.rows):           # данные закончились → начинаем заново, время продолжает идти
                i, offset = self.start, offset + span
            src = self.rows[i]
            path = self._path(src)
            forming = _candle(src["t"] + offset, src["o"], src["o"], src["o"], src["o"], 0)
            dt = self.candle_seconds / len(path)
            for j, p in enumerate(path):
                await asyncio.sleep(dt)
                forming["h"], forming["l"], forming["c"] = max(forming["h"], p), min(forming["l"], p), p
                forming["v"] = src["v"] * (j + 1) / len(path)
                if j < len(path) - 1:
                    yield "tick", dict(forming)
            yield "close", _candle(src["t"] + offset, src["o"], src["h"], src["l"], src["c"], src["v"])
            i += 1


class GBMFeed(Feed):
    """Синтетический поток: геометрическое броуновское движение dS = μS dt + σS dW
    с режимами волатильности (σ переключается марковской цепью) — так ряд похож на рынок."""
    source = "synthetic"

    def __init__(self, s0: float = 1.10, sigma_per_candle: float = 0.0012, mu_per_candle: float = 0.0,
                 timeframe: str = "H1", history_len: int = 300, seed: int | None = None, **kw):
        super().__init__(**kw)
        self.rng = random.Random(seed)
        self.s = s0
        self.base_sigma = sigma_per_candle
        self.sigma = sigma_per_candle
        self.mu = mu_per_candle
        self.tf = TF_SECONDS[timeframe]
        self.t = int(pd.Timestamp("2026-01-05").timestamp())
        self._hist = [self._gen_candle(instant=True) for _ in range(history_len)]

    def _step_regime(self):
        if self.rng.random() < 0.02:
            self.sigma = self.base_sigma * self.rng.choice([0.6, 1.0, 1.0, 1.8])

    def _gen_ticks(self) -> list[float]:
        n = self.ticks_per_candle * 3
        dt = 1.0 / n
        prices = []
        for _ in range(n):
            z = self.rng.gauss(0, 1)
            self.s *= math.exp((self.mu - 0.5 * self.sigma ** 2) * dt + self.sigma * math.sqrt(dt) * z)
            prices.append(self.s)
        return prices

    def _gen_candle(self, instant=False) -> dict:
        self._step_regime()
        o = self.s
        ps = self._gen_ticks()
        c = _candle(self.t, o, max(o, *ps), min(o, *ps), ps[-1], self.rng.uniform(500, 3000) * (self.sigma / self.base_sigma))
        self.t += self.tf
        return c

    def history(self):
        return self._hist

    async def stream(self):
        while True:
            self._step_regime()
            o, t0 = self.s, self.t
            ps = self._gen_ticks()
            forming = _candle(t0, o, o, o, o, 0)
            vol_total = self.rng.uniform(500, 3000) * (self.sigma / self.base_sigma)
            step = max(1, len(ps) // self.ticks_per_candle)
            dt = self.candle_seconds / self.ticks_per_candle
            for j in range(0, len(ps), step):
                await asyncio.sleep(dt)
                chunk = ps[j:j + step]
                forming["h"] = max(forming["h"], *chunk)
                forming["l"] = min(forming["l"], *chunk)
                forming["c"] = chunk[-1]
                forming["v"] = vol_total * min(1.0, (j + step) / len(ps))
                if j + step < len(ps):
                    yield "tick", dict(forming)
            self.t += self.tf
            forming["v"] = vol_total
            yield "close", dict(forming)


class BinanceFeed(Feed):
    """(Опционально) Реальные котировки Binance через публичный REST /api/v3/klines (без ключа).
    Последняя свеча — формирующаяся, остальные закрытые. Опрос каждые poll_seconds."""
    source = "binance"

    def __init__(self, symbol: str = "BTCUSDT", interval: str = "1m", poll_seconds: float = 2.0, **kw):
        super().__init__(**kw)
        self.symbol, self.interval, self.poll = symbol, interval, poll_seconds
        self.url = "https://api.binance.com/api/v3/klines"
        self._hist: list[dict] = []

    @staticmethod
    def _parse(k) -> dict:
        return _candle(int(k[0]) // 1000, k[1], k[2], k[3], k[4], k[5])

    async def _fetch(self, client, limit):
        r = await client.get(self.url, params={"symbol": self.symbol, "interval": self.interval, "limit": limit})
        r.raise_for_status()
        return [self._parse(k) for k in r.json()]

    async def load_history(self):
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            ks = await self._fetch(client, 300)
        self._hist = ks[:-1]

    def history(self):
        return self._hist

    async def stream(self):
        import httpx
        last_closed = self._hist[-1]["t"] if self._hist else 0
        async with httpx.AsyncClient(timeout=10) as client:
            while True:
                try:
                    ks = await self._fetch(client, 5)
                    for k in ks[:-1]:
                        if k["t"] > last_closed:
                            last_closed = k["t"]
                            yield "close", k
                    yield "tick", ks[-1]
                except Exception as e:  # сеть недоступна — ждём и пробуем снова
                    print(f"[binance] {e}")
                await asyncio.sleep(self.poll)
