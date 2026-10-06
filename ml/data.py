"""Сборка оконных датасетов со строго временным разбиением train/val/test (без shuffle между выборками)."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from common.features import FEATURES, TARGETS, WARMUP, compute_features, compute_targets  # noqa: E402
from ml.config import DatasetConfig  # noqa: E402

PROCESSED = ROOT / "data" / "processed"


@dataclass
class SymbolData:
    symbol: str
    df: pd.DataFrame          # OHLCV
    feats: np.ndarray         # (n, F) — сырые (до стандартизации)
    targets: np.ndarray       # (n, 4)
    split: np.ndarray         # (n,) 0=train 1=val 2=test -1=не используется


def load_symbol(symbol: str, cfg: DatasetConfig) -> SymbolData:
    df = pd.read_csv(PROCESSED / f"{symbol}.csv", parse_dates=["timestamp"])
    feats = compute_features(df, cfg.intraday).to_numpy(np.float64)
    targets = compute_targets(df).to_numpy(np.float64)
    n = len(df)
    split = np.full(n, -1, dtype=np.int64)
    # Сэмпл i = окно, заканчивающееся на свече i, цель — свеча i+1.
    # Принадлежность к выборке определяется по свече-цели i+1 → никакой утечки будущего.
    tgt_time = df["timestamp"].shift(-1)
    if cfg.split_frac:
        a, b = int(n * cfg.split_frac[0]), int(n * cfg.split_frac[1])
        idx = np.arange(n) + 1
        split[idx < a] = 0
        split[(idx >= a) & (idx < b)] = 1
        split[idx >= b] = 2
    else:
        v, t = (pd.Timestamp(x) for x in cfg.split_dates)
        split[(tgt_time < v).to_numpy()] = 0
        split[((tgt_time >= v) & (tgt_time < t)).to_numpy()] = 1
        split[(tgt_time >= t).to_numpy()] = 2
    split[: WARMUP] = -1
    split[n - 1] = -1                      # у последней свечи нет цели
    return SymbolData(symbol, df, feats, targets, split)


def load_all(cfg: DatasetConfig) -> list[SymbolData]:
    return [load_symbol(s, cfg) for s in cfg.symbols]


def fit_scaler(data: list[SymbolData]):
    """Статистики стандартизации считаются ТОЛЬКО по train-части."""
    x = np.concatenate([d.feats[d.split == 0] for d in data])
    mean, std = np.nanmean(x, axis=0), np.nanstd(x, axis=0)
    std[std < 1e-12] = 1.0
    # признаки часа уже в [-1, 1] — не трогаем
    for k in ("hour_sin", "hour_cos"):
        j = FEATURES.index(k)
        mean[j], std[j] = 0.0, 1.0
    y = np.concatenate([d.targets[d.split == 0][:, TARGETS.index("t_close")] for d in data])
    target_scale = float(np.nanstd(y))
    return mean, std, target_scale


@dataclass
class Windows:
    x: np.ndarray        # (N, L, F) стандартизированные признаки
    y: np.ndarray        # (N, 4) лог-приращения следующей свечи (не масштабированы)
    close: np.ndarray    # (N,) close последней свечи окна
    next_ohlc: np.ndarray  # (N, 4) фактическая следующая свеча
    ts: np.ndarray       # (N,) время свечи-цели
    sym: np.ndarray      # (N,) индекс тикера
    raw_close: np.ndarray  # (N, L) сырые цены close окна (для baseline на абсолютных ценах)


def make_windows(data: list[SymbolData], split_id: int, lookback: int, mean, std) -> Windows:
    from common.features import standardize
    parts = []
    for si, d in enumerate(data):
        z = standardize(d.feats, mean, std)
        idx = np.where(d.split == split_id)[0]
        idx = idx[idx >= lookback - 1 + WARMUP]
        if len(idx) == 0:
            continue
        win = np.lib.stride_tricks.sliding_window_view(z, (lookback, z.shape[1]))[:, 0]  # (n-L+1, L, F)
        closes = d.df["close"].to_numpy(np.float64)
        cwin = np.lib.stride_tricks.sliding_window_view(closes, lookback)
        ohlc = d.df[["open", "high", "low", "close"]].to_numpy(np.float64)
        parts.append(dict(
            x=win[idx - lookback + 1],
            y=d.targets[idx].astype(np.float32),
            close=closes[idx],
            next_ohlc=ohlc[idx + 1],
            ts=d.df["timestamp"].to_numpy()[idx + 1],
            sym=np.full(len(idx), si),
            raw_close=cwin[idx - lookback + 1],
        ))
    cat = {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}
    return Windows(**cat)
