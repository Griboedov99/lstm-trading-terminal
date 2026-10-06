"""FastAPI-сервер торгового эмулятора.

REST:
  GET  /api/health
  GET  /api/symbols                       — доступные потоки
  GET  /api/{symbol}/state                — полный снимок (свечи, сигнал, счёт)
  POST /api/{symbol}/order                {"side": "long"|"short", "qty": 10000}
  POST /api/{symbol}/close/{position_id}
  POST /api/{symbol}/close_all
  POST /api/{symbol}/mode                 {"mode": "manual"|"auto", "qty": 10000}
  POST /api/{symbol}/speed                {"candle_seconds": 2.0}
  POST /api/{symbol}/reset                — сбросить демо-счёт
  GET  /api/report                        — метрики модели и бэктеста
WebSocket:
  /ws/{symbol} — snapshot при подключении, далее события tick / candle / account
"""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .broker import PaperBroker
from .feeds import BinanceFeed, GBMFeed, ReplayFeed
from .predictor import Predictor
from .session import TradingSession

ROOT = Path(__file__).resolve().parents[2]
MODELS_DIR = Path(os.getenv("MODELS_DIR", ROOT / "models"))
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data" / "processed"))
REPORTS_DIR = Path(os.getenv("REPORTS_DIR", ROOT / "reports"))
CANDLE_SECONDS = float(os.getenv("CANDLE_SECONDS", "2.0"))
INITIAL_BALANCE = float(os.getenv("INITIAL_BALANCE", "10000"))
ENABLE_BINANCE = os.getenv("ENABLE_BINANCE", "0") == "1"

SESSIONS: dict[str, TradingSession] = {}


def _first_index(csv: Path, frac: float | None = None, date: str | None = None) -> int:
    df = pd.read_csv(csv, usecols=["timestamp"], parse_dates=["timestamp"])
    if frac is not None:
        return int(len(df) * frac)
    return int((df["timestamp"] < pd.Timestamp(date)).sum())


def build_sessions() -> dict[str, TradingSession]:
    fx = Predictor(MODELS_DIR, "eurusd_h1")
    st = Predictor(MODELS_DIR, "stocks_d1")
    kw = dict(candle_seconds=CANDLE_SECONDS, ticks_per_candle=8)
    s: dict[str, TradingSession] = {}

    eur = DATA_DIR / "EURUSD_H1.csv"
    s["EURUSD"] = TradingSession(
        "EURUSD", "EUR/USD · replay теста", "H1",
        ReplayFeed(eur, _first_index(eur, frac=0.85), **kw), fx,
        PaperBroker(INITIAL_BALANCE, half_spread=0.000035, leverage=30), default_qty=10_000, price_digits=5)

    for sym in ("NVDA", "GOOG"):
        p = DATA_DIR / f"{sym}_D1.csv"
        s[sym] = TradingSession(
            sym, f"{sym} · replay теста", "D1",
            ReplayFeed(p, _first_index(p, date="2012-01-01"), **kw), st,
            PaperBroker(INITIAL_BALANCE, half_spread=0.00025, leverage=1), default_qty=20 if sym == "NVDA" else 5,
            price_digits=2)

    s["SYNTH"] = TradingSession(
        "SYNTH", "Синтетика · GBM", "H1",
        GBMFeed(s0=1.10, sigma_per_candle=0.0012, timeframe="H1", **kw), fx,
        PaperBroker(INITIAL_BALANCE, half_spread=0.000035, leverage=30), default_qty=10_000, price_digits=5)

    if ENABLE_BINANCE:
        s["BTCUSDT"] = TradingSession(
            "BTCUSDT", "BTC/USDT · Binance live", "M1",
            BinanceFeed("BTCUSDT", "1m", poll_seconds=2.0), fx,
            PaperBroker(INITIAL_BALANCE, half_spread=0.0001, leverage=1), default_qty=0.01, price_digits=2)
    return s


@asynccontextmanager
async def lifespan(app: FastAPI):
    SESSIONS.update(build_sessions())
    for sess in SESSIONS.values():
        await sess.start()
    print(f"sessions: {list(SESSIONS)}  candle_seconds={CANDLE_SECONDS}")
    yield
    for sess in SESSIONS.values():
        await sess.stop()


app = FastAPI(title="LSTM Trading Terminal", version="1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def get(symbol: str) -> TradingSession:
    sess = SESSIONS.get(symbol.upper())
    if not sess:
        raise HTTPException(404, f"нет потока {symbol}; доступны: {list(SESSIONS)}")
    return sess


class OrderIn(BaseModel):
    side: str
    qty: float | None = None


class ModeIn(BaseModel):
    mode: str
    qty: float | None = None


class SpeedIn(BaseModel):
    candle_seconds: float


@app.get("/api/health")
def health():
    return {"status": "ok", "sessions": {k: v.status for k, v in SESSIONS.items()}}


@app.get("/api/symbols")
def symbols():
    return [s.info() for s in SESSIONS.values()]


@app.get("/api/{symbol}/state")
def state(symbol: str, limit: int = 300):
    return get(symbol).snapshot(limit)


@app.post("/api/{symbol}/order")
async def order(symbol: str, body: OrderIn):
    s = get(symbol)
    side = {"buy": "long", "sell": "short"}.get(body.side.lower(), body.side.lower())
    try:
        p = s.broker.open(side, body.qty or s.default_qty, by="manual")
    except ValueError as e:
        raise HTTPException(400, str(e))
    await s.push_state()
    return {"ok": True, "position_id": p.id, "account": s.broker.snapshot()}


@app.post("/api/{symbol}/close/{position_id}")
async def close(symbol: str, position_id: int):
    s = get(symbol)
    try:
        tr = s.broker.close(position_id, by="manual")
    except KeyError as e:
        raise HTTPException(404, str(e))
    await s.push_state()
    return {"ok": True, "pnl": tr.pnl, "account": s.broker.snapshot()}


@app.post("/api/{symbol}/close_all")
async def close_all(symbol: str):
    s = get(symbol)
    trades = s.broker.close_all(by="manual")
    await s.push_state()
    return {"ok": True, "closed": len(trades), "account": s.broker.snapshot()}


@app.post("/api/{symbol}/mode")
async def mode(symbol: str, body: ModeIn):
    s = get(symbol)
    try:
        s.set_mode(body.mode, body.qty)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await s.push_state()
    return {"ok": True, "mode": s.mode, "auto_qty": s.auto_qty}


@app.post("/api/{symbol}/speed")
async def speed(symbol: str, body: SpeedIn):
    s = get(symbol)
    s.feed.candle_seconds = max(0.2, min(60.0, body.candle_seconds))
    await s.push_state()
    return {"ok": True, "candle_seconds": s.feed.candle_seconds}


@app.post("/api/{symbol}/reset")
async def reset(symbol: str):
    s = get(symbol)
    b = s.broker
    s.broker = PaperBroker(b.initial_balance, half_spread=b.half_spread, leverage=b.leverage)
    s.broker.mark(b.price, b.time)
    s.mode = "manual"
    s.bot_log.clear()
    await s.push_state()
    return {"ok": True}


@app.get("/api/report")
def report():
    out = {}
    for name in ("eurusd_h1", "stocks_d1"):
        f = REPORTS_DIR / f"{name}_metrics.json"
        if f.exists():
            r = json.loads(f.read_text())
            out[name] = {k: r[k] for k in ("timeframe", "symbols", "selected", "test_period",
                                           "metrics_test", "backtest") if k in r}
    return out


@app.get("/")
def index():
    page = Path(__file__).parent / "static" / "index.html"
    if page.exists():
        return FileResponse(page)
    return {"service": "LSTM Trading Terminal", "docs": "/docs", "symbols": list(SESSIONS)}


@app.websocket("/ws/{symbol}")
async def ws(websocket: WebSocket, symbol: str):
    sess = SESSIONS.get(symbol.upper())
    await websocket.accept()
    if not sess:
        await websocket.send_json({"type": "error", "message": f"нет потока {symbol}"})
        await websocket.close()
        return
    await websocket.send_json(sess.snapshot())
    sess.subscribers.add(websocket)
    try:
        while True:
            msg = await websocket.receive_text()     # клиент может слать ping
            if msg == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        sess.subscribers.discard(websocket)
