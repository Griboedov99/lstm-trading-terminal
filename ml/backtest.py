"""Бэктест сигнальной стратегии.

Правило (то же, что у бота на сервере):
    BUY  если P(up) ≥ p_thr  и прогноз Δclose >  r_thr
    SELL если P(up) ≤ 1-p_thr и прогноз Δclose < -r_thr
    HOLD иначе (позиция закрывается)
Позиция открывается по close свечи t и держится одну свечу; PnL = pos · log(C_{t+1}/C_t).
Издержки: cost · |pos_t − pos_{t−1}| (смена long→short стоит двойной спред).
Пороги подбираются по VALIDATION, на test применяются без изменений.
"""
from __future__ import annotations

import itertools

import numpy as np


def signals(p_up: np.ndarray, pred_ret: np.ndarray, p_thr: float, r_thr: float) -> np.ndarray:
    pos = np.zeros(len(p_up))
    pos[(p_up >= p_thr) & (pred_ret > r_thr)] = 1
    pos[(p_up <= 1 - p_thr) & (pred_ret < -r_thr)] = -1
    return pos


def run(pos: np.ndarray, ret: np.ndarray, sym: np.ndarray, cost: float, bars_per_year: int,
        ts: np.ndarray | None = None) -> dict:
    """pos/ret/sym/ts выровнены по времени внутри каждого тикера.
    Портфель — равные доли капитала на каждый тикер (1/N), без ребалансировки между долями."""
    import pandas as pd
    if ts is None:
        ts = np.zeros(len(pos), dtype=np.int64)
        for s in np.unique(sym):
            ts[sym == s] = np.arange((sym == s).sum())
    pnl_all, trade_pnls, n_trades = [], [], 0
    for s in np.unique(sym):
        m = sym == s
        p, r = pos[m], ret[m]
        turnover = np.abs(np.diff(np.concatenate([[0.0], p])))
        pnl = p * r - cost * turnover
        pnl_all.append(pd.Series(pnl, index=ts[m]))
        # сделка = непрерывный отрезок с одинаковой ненулевой позицией
        cur, acc = 0.0, 0.0
        for pi, x, tv in zip(p, pnl, turnover):
            if pi != cur:
                if cur != 0:
                    trade_pnls.append(acc)
                acc, cur = 0.0, pi
                if pi != 0:
                    n_trades += 1
            if pi != 0:
                acc += x
        if cur != 0:
            trade_pnls.append(acc)
    # капитал делится на равные части по тикерам; если тикер в этот день не торгуется, его доля лежит в кэше
    pnl = (pd.concat(pnl_all, axis=1).sort_index().fillna(0.0).sum(axis=1) / len(pnl_all)).to_numpy()
    equity = np.exp(np.cumsum(pnl))
    peak = np.maximum.accumulate(np.concatenate([[1.0], equity]))[1:]
    dd = equity / peak - 1
    sd = pnl.std()
    tp = np.array(trade_pnls) if trade_pnls else np.array([0.0])
    return {
        "total_return": float(equity[-1] - 1),
        "annual_return": float(np.exp(pnl.mean() * bars_per_year) - 1),
        "sharpe": float(pnl.mean() / sd * np.sqrt(bars_per_year)) if sd > 0 else 0.0,
        "max_drawdown": float(dd.min()),
        "winrate": float((tp > 0).mean()) if trade_pnls else 0.0,
        "n_trades": int(n_trades),
        "exposure": float((pos != 0).mean()),
        "equity": equity,
    }


def tune(p_up, pred_ret, ret, sym, cost, bars_per_year, ret_scale, ts=None):
    """Перебор порогов на валидации, критерий — Sharpe при ≥ 20 сделках."""
    best = None
    for p_thr, k in itertools.product([0.50, 0.52, 0.54, 0.56, 0.58, 0.60], [0.0, 0.1, 0.25, 0.5]):
        r_thr = k * ret_scale
        res = run(signals(p_up, pred_ret, p_thr, r_thr), ret, sym, cost, bars_per_year, ts)
        if res["n_trades"] < 20:
            continue
        if best is None or res["sharpe"] > best[2]["sharpe"]:
            best = (p_thr, r_thr, res)
    if best is None:
        best = (0.5, 0.0, run(signals(p_up, pred_ret, 0.5, 0.0), ret, sym, cost, bars_per_year, ts))
    return best
