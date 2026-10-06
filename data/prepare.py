"""Приведение сырых датасетов к единому формату OHLCV.

Выход: data/processed/<SYMBOL>_<TF>.csv с колонками
    timestamp, open, high, low, close, volume

Источники (лежат в data/raw, скачиваются scripts/download_data.sh):
  * EURUSD H1 (2017-04 … 2018-02) — выборка из набора backtesting.py (котировки Forex, 5000 часовых свечей).
    Цена за период выросла с 1.07 до 1.25 — тот самый сценарий «EUR/USD ушёл с 1.05 на 1.20».
  * NVDA, ORCL, YHOO D1 — дневные котировки Yahoo Finance (из набора backtrader),
    GOOG D1 — из набора backtesting.py. Цены за выборку меняются в 10–20 раз.

Для акций используется Adj Close: high/low/open масштабируются тем же коэффициентом
(Adj Close / Close), чтобы сплиты не создавали ложных «гэпов».
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"
OUT = ROOT / "processed"


def _finalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df[["timestamp", "open", "high", "low", "close", "volume"]].copy()
    df = df.dropna()
    df = df[(df[["open", "high", "low", "close"]] > 0).all(axis=1)]
    # гарантируем корректную геометрию свечи
    df["high"] = df[["open", "high", "low", "close"]].max(axis=1)
    df["low"] = df[["open", "high", "low", "close"]].min(axis=1)
    df = df.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
    return df


def load_backtesting_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df = df.rename(columns={df.columns[0]: "timestamp", "Open": "open", "High": "high",
                            "Low": "low", "Close": "close", "Volume": "volume"})
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return _finalize(df)


def load_yahoo_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    k = df["Adj Close"] / df["Close"]
    out = pd.DataFrame({
        "timestamp": pd.to_datetime(df["Date"]),
        "open": df["Open"] * k,
        "high": df["High"] * k,
        "low": df["Low"] * k,
        "close": df["Adj Close"],
        "volume": df["Volume"] / k,  # объём в «скорректированных» акциях
    })
    return _finalize(out)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = {
        "EURUSD_H1": (load_backtesting_csv, "EURUSD.csv"),
        "GOOG_D1": (load_backtesting_csv, "GOOG.csv"),
        "NVDA_D1": (load_yahoo_csv, "nvda-1999-2014.csv"),
        "ORCL_D1": (load_yahoo_csv, "orcl-1995-2014.csv"),
        "YHOO_D1": (load_yahoo_csv, "yhoo-1996-2015.csv"),
    }
    for name, (loader, fname) in jobs.items():
        src = RAW / fname
        if not src.exists():
            print(f"[skip] {src} не найден — запустите scripts/download_data.sh")
            continue
        df = loader(src)
        df.to_csv(OUT / f"{name}.csv", index=False)
        lo, hi = df["close"].min(), df["close"].max()
        print(f"{name:10s} rows={len(df):5d}  {df.timestamp.iloc[0]} → {df.timestamp.iloc[-1]}  "
              f"close∈[{lo:.4f}, {hi:.4f}] (×{hi / lo:.1f})")


if __name__ == "__main__":
    main()
