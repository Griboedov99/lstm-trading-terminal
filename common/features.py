"""Масштабно-инвариантные признаки и цели.

Один и тот же модуль используется при обучении (ml/) и на сервере (server/),
поэтому признаки в онлайне считаются ровно так же, как в офлайне.

Ключевая идея: ни один признак не зависит от абсолютного уровня цены.
Все ценовые величины — это логарифмы отношений (log-returns) либо величины,
нормированные на текущую цену / скользящую волатильность. Поэтому свеча
EUR/USD на уровне 1.05 и та же по форме свеча на уровне 1.20 дают
идентичный вектор признаков.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# минимальная история, нужная для «прогрева» индикаторов (EMA26+сигнал9, окна 20/50)
WARMUP = 60

FEATURES = [
    "ret_1",      # log(C_t / C_{t-1})            — приращение close
    "gap",        # log(O_t / C_{t-1})            — гэп открытия
    "body",       # log(C_t / O_t)                — тело свечи
    "upper",      # log(H_t / max(O_t, C_t))      — верхняя тень
    "lower",      # log(min(O_t, C_t) / L_t)      — нижняя тень
    "vol_20",     # std(ret_1, 20)                — скользящая волатильность
    "roc_10",     # log(C_t / C_{t-10})           — скорость изменения цены
    "z_20",       # (C - SMA20) / STD20           — rolling z-score цены
    "rsi_14",     # (RSI14 - 50) / 50
    "macd_h",     # (MACD - signal) / C_t         — гистограмма MACD, нормированная на цену
    "vol_z",      # rolling z-score log-объёма (50)
    "hour_sin",   # сезонность внутри суток (для дневок = 0)
    "hour_cos",
]

TARGETS = ["t_open", "t_high", "t_low", "t_close"]  # log(X_{t+1} / C_t)


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def compute_features(df: pd.DataFrame, intraday: bool) -> pd.DataFrame:
    """df: timestamp, open, high, low, close, volume  →  DataFrame признаков (та же длина)."""
    o, h, l, c = (df[k].astype(float) for k in ("open", "high", "low", "close"))
    v = df["volume"].astype(float).clip(lower=0)
    out = pd.DataFrame(index=df.index)

    prev_c = c.shift(1)
    out["ret_1"] = np.log(c / prev_c)
    out["gap"] = np.log(o / prev_c)
    out["body"] = np.log(c / o)
    out["upper"] = np.log(h / np.maximum(o, c))
    out["lower"] = np.log(np.minimum(o, c) / l)
    out["vol_20"] = out["ret_1"].rolling(20).std()
    out["roc_10"] = np.log(c / c.shift(10))
    sma, sd = c.rolling(20).mean(), c.rolling(20).std()
    out["z_20"] = ((c - sma) / sd.replace(0, np.nan)).fillna(0.0)
    out["rsi_14"] = (_rsi(c) - 50.0) / 50.0
    ema12, ema26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    out["macd_h"] = (macd - macd.ewm(span=9, adjust=False).mean()) / c
    lv = np.log1p(v)
    out["vol_z"] = ((lv - lv.rolling(50).mean()) / lv.rolling(50).std().replace(0, np.nan)).fillna(0.0)

    if intraday:
        hour = pd.to_datetime(df["timestamp"]).dt.hour
        out["hour_sin"] = np.sin(2 * np.pi * hour / 24)
        out["hour_cos"] = np.cos(2 * np.pi * hour / 24)
    else:
        out["hour_sin"] = 0.0
        out["hour_cos"] = 0.0
    return out[FEATURES]


def compute_targets(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"].astype(float)
    out = pd.DataFrame(index=df.index)
    out["t_open"] = np.log(df["open"].shift(-1) / c)
    out["t_high"] = np.log(df["high"].shift(-1) / c)
    out["t_low"] = np.log(df["low"].shift(-1) / c)
    out["t_close"] = np.log(df["close"].shift(-1) / c)
    return out[TARGETS]


def standardize(x: np.ndarray, mean: np.ndarray, std: np.ndarray, clip: float = 5.0) -> np.ndarray:
    z = (x - mean) / std
    return np.clip(np.nan_to_num(z, nan=0.0, posinf=clip, neginf=-clip), -clip, clip).astype(np.float32)


def reconstruct_candle(last_close: float, pred_logrets: np.ndarray) -> dict:
    """Предсказанные лог-приращения → абсолютная свеча (с исправлением геометрии)."""
    t_o, t_h, t_l, t_c = (float(x) for x in pred_logrets)
    o, c = last_close * np.exp(t_o), last_close * np.exp(t_c)
    h = max(last_close * np.exp(t_h), o, c)
    l = min(last_close * np.exp(t_l), o, c)
    return {"open": o, "high": h, "low": l, "close": c}
