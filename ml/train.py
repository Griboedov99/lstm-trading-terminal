"""Обучение LSTM + сравнение с базовыми моделями + бэктест + экспорт в ONNX.

Запуск:
    python ml/train.py --config eurusd_h1
    python ml/train.py --config stocks_d1
    python ml/train.py --config eurusd_h1 --quick     # быстрый прогон (1 конфигурация, 15 эпох)

Артефакты:
    models/<name>.pt, models/<name>.onnx, models/<name>.json   — веса, ONNX для сервера, метаданные
    reports/<name>_metrics.json, reports/figures/<name>_*.png
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import torch
from torch import nn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from common.features import FEATURES, TARGETS  # noqa: E402
from ml import backtest as bt  # noqa: E402
from ml.config import (BATCH, CLS_WEIGHT, CONFIGS, DROPOUT, LR, MAX_EPOCHS,  # noqa: E402
                       PATIENCE, SEED, WEIGHT_DECAY)
from ml.data import fit_scaler, load_all, make_windows  # noqa: E402
from ml.models import RawPriceLSTM, SeqForecaster  # noqa: E402

MODELS = ROOT / "models"
REPORTS = ROOT / "reports"
FIG = REPORTS / "figures"
torch.set_num_threads(max(1, torch.get_num_threads()))
CLOSE = TARGETS.index("t_close")


def set_seed(seed: int = SEED):
    np.random.seed(seed)
    torch.manual_seed(seed)


# ---------------------------------------------------------------- обучение
def fit(model: nn.Module, tr, va, target_scale: float, max_epochs: int, log_prefix: str = ""):
    opt = torch.optim.Adam(model.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)
    sched = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, factor=0.5, patience=4)
    huber, bce = nn.SmoothL1Loss(beta=1.0), nn.BCEWithLogitsLoss()

    def tensors(w):
        x = torch.from_numpy(np.ascontiguousarray(w.x, dtype=np.float32))
        y = torch.from_numpy((w.y / target_scale).astype(np.float32))
        up = torch.from_numpy((w.y[:, CLOSE] > 0).astype(np.float32))
        return x, y, up

    xt, yt, ut = tensors(tr)
    xv, yv, uv = tensors(va)

    def loss_on(x, y, up):
        reg, logit = model(x)
        return huber(reg, y) + CLS_WEIGHT * bce(logit, up)

    best, best_state, wait, hist = float("inf"), None, 0, []
    g = torch.Generator().manual_seed(SEED)
    for ep in range(1, max_epochs + 1):
        model.train()
        perm = torch.randperm(len(xt), generator=g)   # перемешивание окон ВНУТРИ train — допустимо
        tl = 0.0
        for i in range(0, len(xt), BATCH):
            b = perm[i:i + BATCH]
            opt.zero_grad()
            loss = loss_on(xt[b], yt[b], ut[b])
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            tl += loss.item() * len(b)
        tl /= len(xt)
        model.eval()
        with torch.no_grad():
            vl = sum(loss_on(xv[i:i + 2048], yv[i:i + 2048], uv[i:i + 2048]).item() * len(xv[i:i + 2048])
                     for i in range(0, len(xv), 2048)) / len(xv)
        sched.step(vl)
        hist.append((tl, vl))
        if vl < best - 1e-5:
            best, best_state, wait = vl, copy.deepcopy(model.state_dict()), 0
        else:
            wait += 1
        if ep % 5 == 0 or ep == 1:
            print(f"{log_prefix} ep {ep:3d}  train {tl:.4f}  val {vl:.4f}", flush=True)
        if wait >= PATIENCE:
            break
    model.load_state_dict(best_state)
    return model, best, hist


@torch.no_grad()
def predict(model, w, target_scale):
    model.eval()
    regs, logits = [], []
    for i in range(0, len(w.x), 2048):
        r, l = model(torch.from_numpy(np.ascontiguousarray(w.x[i:i + 2048], dtype=np.float32)))
        regs.append(r.numpy())
        logits.append(l.numpy())
    return np.concatenate(regs) * target_scale, np.concatenate(logits)


def fit_temperature(logits: np.ndarray, up: np.ndarray) -> float:
    """Temperature scaling на валидации — калибровка «уверенности» модели."""
    best_t, best_nll = 1.0, float("inf")
    for t in np.exp(np.linspace(np.log(0.25), np.log(8), 60)):
        p = 1 / (1 + np.exp(-logits / t))
        p = np.clip(p, 1e-6, 1 - 1e-6)
        nll = -np.mean(up * np.log(p) + (1 - up) * np.log(1 - p))
        if nll < best_nll:
            best_t, best_nll = float(t), nll
    return best_t


# ---------------------------------------------------------------- метрики
def price_metrics(pred_close, w, pred_dir=None, ohlc_pred=None):
    true = w.next_ohlc[:, 3]
    err = pred_close - true
    real_dir = np.sign(true - w.close)
    if pred_dir is None:
        pred_dir = np.sign(pred_close - w.close)
    m = real_dir != 0
    out = {
        "MAE": float(np.mean(np.abs(err))),
        "RMSE": float(np.sqrt(np.mean(err ** 2))),
        "MAPE_%": float(np.mean(np.abs(err) / true) * 100),
        "DirAcc_%": float(np.mean(pred_dir[m] == real_dir[m]) * 100),
    }
    if ohlc_pred is not None:
        for j, k in enumerate(["open", "high", "low"]):
            out[f"MAPE_{k}_%"] = float(np.mean(np.abs(ohlc_pred[:, j] - w.next_ohlc[:, j]) / w.next_ohlc[:, j]) * 100)
    return out


def ohlc_from_reg(reg, close):
    o = close * np.exp(reg[:, 0])
    c = close * np.exp(reg[:, 3])
    h = np.maximum.reduce([close * np.exp(reg[:, 1]), o, c])
    l = np.minimum.reduce([close * np.exp(reg[:, 2]), o, c])
    return np.stack([o, h, l, c], axis=1)


def per_symbol(fn, w, symbols, *arrays):
    res = {}
    for si, s in enumerate(symbols):
        m = w.sym == si
        if m.any():
            sub = copy.copy(w)
            for k in ("x", "y", "close", "next_ohlc", "ts", "sym", "raw_close"):
                setattr(sub, k, getattr(w, k)[m])
            res[s] = fn(sub, *(a[m] if a is not None else None for a in arrays))
    return res


# ---------------------------------------------------------------- базовые модели
def arima_baseline(data, lookback, mean, std, split_id):
    """ARIMA(1,0,1) по лог-доходностям close: обучение на train каждого тикера, далее фильтрация без переобучения."""
    from statsmodels.tsa.arima.model import ARIMA
    preds = []
    for d in data:
        r = d.feats[:, FEATURES.index("ret_1")]
        r = np.nan_to_num(r, nan=0.0)
        tr_mask = d.split == 0
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = ARIMA(r[tr_mask], order=(1, 0, 1), trend="c").fit()
            full = res.apply(r)
        # прогноз доходности свечи i+1, сделанный в момент i
        f = full.forecasts[0] if hasattr(full, "forecasts") else full.fittedvalues
        f = np.asarray(f).ravel()
        idx = np.where(d.split == split_id)[0]
        from common.features import WARMUP
        idx = idx[idx >= lookback - 1 + WARMUP]
        preds.append(f[idx + 1])
    return np.concatenate(preds)


def raw_price_baseline(tr, va, te, max_epochs):
    """LSTM на абсолютных ценах с min-max нормализацией по train (анти-пример)."""
    lo, hi = tr.raw_close.min(), tr.raw_close.max()
    sc = lambda a: ((a - lo) / (hi - lo)).astype(np.float32)  # noqa: E731
    set_seed()
    m = RawPriceLSTM()
    opt = torch.optim.Adam(m.parameters(), lr=LR)
    xt = torch.from_numpy(sc(tr.raw_close)[..., None]); yt = torch.from_numpy(sc(tr.next_ohlc[:, 3]))
    xv = torch.from_numpy(sc(va.raw_close)[..., None]); yv = torch.from_numpy(sc(va.next_ohlc[:, 3]))
    best, state, wait = 1e9, None, 0
    for ep in range(max_epochs):
        m.train()
        perm = torch.randperm(len(xt))
        for i in range(0, len(xt), BATCH):
            b = perm[i:i + BATCH]
            opt.zero_grad(); l = nn.functional.mse_loss(m(xt[b]), yt[b]); l.backward(); opt.step()
        m.eval()
        with torch.no_grad():
            vl = nn.functional.mse_loss(m(xv), yv).item()
        if vl < best:
            best, state, wait = vl, copy.deepcopy(m.state_dict()), 0
        else:
            wait += 1
            if wait >= PATIENCE:
                break
    m.load_state_dict(state); m.eval()
    with torch.no_grad():
        p = m(torch.from_numpy(sc(te.raw_close)[..., None])).numpy()
    return p * (hi - lo) + lo, (float(lo), float(hi))


# ---------------------------------------------------------------- экспорт
def export_onnx(model, lookback, path):
    model.eval()
    dummy = torch.zeros(1, lookback, len(FEATURES))
    torch.onnx.export(model, dummy, str(path), input_names=["x"], output_names=["reg", "logit"],
                      dynamic_axes={"x": {0: "batch"}, "reg": {0: "batch"}, "logit": {0: "batch"}},
                      opset_version=17, dynamo=False)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="eurusd_h1", choices=list(CONFIGS))
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--reuse", action="store_true", help="не переобучать LSTM: взять models/<name>.pt")
    args = ap.parse_args()
    cfg = CONFIGS[args.config]
    max_epochs = 15 if args.quick else MAX_EPOCHS
    MODELS.mkdir(exist_ok=True); FIG.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    data = load_all(cfg)
    mean, std, target_scale = fit_scaler(data)
    print(f"[{cfg.name}] признаков={len(FEATURES)} target_scale(std Δlog close)={target_scale:.6f}")

    # ---- 1. подбор lookback и архитектуры по валидации
    lookbacks = cfg.lookbacks[1:2] if args.quick else cfg.lookbacks
    archs = cfg.arch_grid[-1:] if args.quick else cfg.arch_grid
    grid, best = [], None
    if args.reuse and (MODELS / f"{cfg.name}.pt").exists():
        ck = torch.load(MODELS / f"{cfg.name}.pt", weights_only=False)
        prev = json.loads((REPORTS / f"{cfg.name}_metrics.json").read_text())
        model = SeqForecaster(len(FEATURES), ck["hidden"], ck["layers"], DROPOUT, "lstm")
        model.load_state_dict(ck["state_dict"])
        best = {**prev["selected"], "model": model, "hist": ck.get("hist", [])}
        grid = prev["grid"]
        lookbacks = []
        print(f"[{cfg.name}] reuse: {prev['selected']}")
    for L in lookbacks:
        tr, va = (make_windows(data, s, L, mean, std) for s in (0, 1))
        for layers, hidden in archs:
            set_seed()
            model = SeqForecaster(len(FEATURES), hidden, layers, DROPOUT, "lstm")
            model, vl, hist = fit(model, tr, va, target_scale, max_epochs, f"[LSTM L={L} {layers}x{hidden}]")
            grid.append({"lookback": L, "layers": layers, "hidden": hidden, "val_loss": vl, "epochs": len(hist)})
            print(f"  → L={L} layers={layers} hidden={hidden}: val_loss={vl:.4f}  epochs={len(hist)}", flush=True)
            if best is None or vl < best["val_loss"]:
                best = {"lookback": L, "layers": layers, "hidden": hidden, "val_loss": vl,
                        "model": model, "hist": hist}
    L = best["lookback"]
    model = best["model"]
    print(f"[{cfg.name}] выбрано: lookback={L}, layers={best['layers']}, hidden={best['hidden']}")
    tr, va, te = (make_windows(data, s, L, mean, std) for s in (0, 1, 2))
    print(f"  окон: train={len(tr.x)} val={len(va.x)} test={len(te.x)}")

    # ---- 2. прогнозы LSTM + калибровка
    reg_va, lg_va = predict(model, va, target_scale)
    reg_te, lg_te = predict(model, te, target_scale)
    T = fit_temperature(lg_va, (va.y[:, CLOSE] > 0).astype(float))
    p_va, p_te = 1 / (1 + np.exp(-lg_va / T)), 1 / (1 + np.exp(-lg_te / T))
    ohlc_te = ohlc_from_reg(reg_te, te.close)

    results = {}
    results["LSTM"] = price_metrics(ohlc_te[:, 3], te, ohlc_pred=ohlc_te)
    results["LSTM"]["DirAcc_cls_%"] = float(np.mean(((p_te > 0.5) * 2 - 1)[np.sign(te.y[:, CLOSE]) != 0]
                                                  == np.sign(te.y[:, CLOSE])[np.sign(te.y[:, CLOSE]) != 0]) * 100)

    # ---- 3. базовые модели
    results["Naive (C_t+1 = C_t)"] = price_metrics(te.close.copy(), te,
                                                   pred_dir=np.sign(te.x[:, -1, FEATURES.index("ret_1")]))
    results["Naive (C_t+1 = C_t)"]["note"] = "направление = знак последнего приращения (momentum)"

    set_seed()
    gru = SeqForecaster(len(FEATURES), best["hidden"], best["layers"], DROPOUT, "gru")
    gru, gru_vl, _ = fit(gru, tr, va, target_scale, max_epochs, "[GRU]")
    reg_g, lg_g = predict(gru, te, target_scale)
    results["GRU"] = price_metrics(te.close * np.exp(reg_g[:, 3]), te)
    results["GRU"]["val_loss"] = gru_vl

    try:
        ar = arima_baseline(data, L, mean, std, 2)
        results["ARIMA(1,0,1) on log-returns"] = price_metrics(te.close * np.exp(ar), te)
    except Exception as e:  # pragma: no cover
        print("ARIMA failed:", e)

    raw_pred, (lo, hi) = raw_price_baseline(tr, va, te, max_epochs)
    results["LSTM on raw prices (min-max)"] = price_metrics(raw_pred, te)
    results["LSTM on raw prices (min-max)"]["train_price_range"] = [lo, hi]

    per_sym = per_symbol(lambda w, oh: price_metrics(oh[:, 3], w), te, cfg.symbols, ohlc_te) \
        if len(cfg.symbols) > 1 else None

    # ---- 4. бэктест: пороги по валидации, оценка на тесте
    p_thr, r_thr, val_bt = bt.tune(p_va, reg_va[:, CLOSE], va.y[:, CLOSE], va.sym, cfg.cost,
                                   cfg.bars_per_year, target_scale, va.ts)
    pos_te = bt.signals(p_te, reg_te[:, CLOSE], p_thr, r_thr)
    test_bt = bt.run(pos_te, te.y[:, CLOSE], te.sym, cfg.cost, cfg.bars_per_year, te.ts)
    test_bt_nocost = bt.run(pos_te, te.y[:, CLOSE], te.sym, 0.0, cfg.bars_per_year, te.ts)
    bh = bt.run(np.ones(len(te.y)), te.y[:, CLOSE], te.sym, 0.0, cfg.bars_per_year, te.ts)
    # «всегда по знаку прогноза» — без фильтра уверенности
    always = bt.run(bt.signals(p_te, reg_te[:, CLOSE], 0.5, 0.0), te.y[:, CLOSE], te.sym, cfg.cost,
                    cfg.bars_per_year, te.ts)

    strip = lambda d: {k: v for k, v in d.items() if k != "equity"}  # noqa: E731
    backtest = {
        "thresholds": {"p_thr": p_thr, "r_thr": r_thr},
        "validation": strip(val_bt),
        "test": strip(test_bt),
        "test_without_costs": strip(test_bt_nocost),
        "test_always_in_market": strip(always),
        "buy_and_hold": strip(bh),
        "cost_per_turnover": cfg.cost,
        "test_signal_mix": {"long": int((pos_te > 0).sum()), "short": int((pos_te < 0).sum()),
                            "flat": int((pos_te == 0).sum())},
        "test_worst_bar": float((pos_te * te.y[:, CLOSE]).min()),
    }

    # ---- 5. сохранение
    torch.save({"state_dict": model.state_dict(), "lookback": L, "layers": best["layers"],
                "hidden": best["hidden"], "hist": best["hist"]}, MODELS / f"{cfg.name}.pt")
    export_onnx(model, L, MODELS / f"{cfg.name}.onnx")
    meta = {
        "name": cfg.name, "timeframe": cfg.timeframe, "intraday": cfg.intraday, "symbols": cfg.symbols,
        "features": FEATURES, "targets": TARGETS, "lookback": L,
        "layers": best["layers"], "hidden": best["hidden"],
        "mean": mean.tolist(), "std": std.tolist(), "target_scale": target_scale,
        "temperature": T, "p_thr": p_thr, "r_thr": r_thr, "cost": cfg.cost,
        "bars_per_year": cfg.bars_per_year,
    }
    (MODELS / f"{cfg.name}.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))

    # проверка паритета torch ↔ onnxruntime
    import onnxruntime as ort
    sess = ort.InferenceSession(str(MODELS / f"{cfg.name}.onnx"), providers=["CPUExecutionProvider"])
    o_reg, o_lg = sess.run(None, {"x": np.ascontiguousarray(te.x[:64], dtype=np.float32)})
    diff = float(np.abs(o_reg * target_scale - reg_te[:64]).max())
    print(f"ONNX parity max|Δ| = {diff:.2e}")

    report = {
        "config": cfg.name, "timeframe": cfg.timeframe, "symbols": cfg.symbols,
        "selected": {k: best[k] for k in ("lookback", "layers", "hidden", "val_loss")},
        "grid": grid, "temperature": T,
        "n_windows": {"train": len(tr.x), "val": len(va.x), "test": len(te.x)},
        "test_period": [str(te.ts.min())[:19], str(te.ts.max())[:19]],
        "train_price_range": [float(tr.close.min()), float(tr.close.max())],
        "test_price_range": [float(te.close.min()), float(te.close.max())],
        "metrics_test": results, "metrics_test_per_symbol": per_sym,
        "backtest": backtest, "onnx_parity": diff, "train_seconds": round(time.time() - t0, 1),
    }
    (REPORTS / f"{cfg.name}_metrics.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, default=float))

    # ---- 6. графики
    make_figures(cfg, best["hist"], te, ohlc_te, raw_pred, (lo, hi), test_bt, bh, p_te)
    print(json.dumps({k: {kk: (round(vv, 5) if isinstance(vv, float) else vv) for kk, vv in v.items()}
                      for k, v in results.items()}, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in backtest.items()}, indent=1, default=float))
    print(f"[{cfg.name}] done in {time.time() - t0:.0f}s")


def make_figures(cfg, hist, te, ohlc_te, raw_pred, rng, test_bt, bh, p_te):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if len(hist):   # при --reuse старой истории может не быть — тогда график не перерисовываем
        h = np.array(hist)
        fig, ax = plt.subplots(figsize=(7, 3.5))
        ax.plot(h[:, 0], label="train"); ax.plot(h[:, 1], label="val")
        ax.set_xlabel("эпоха"); ax.set_ylabel("Huber + 0.5·BCE"); ax.legend(); ax.set_title(f"{cfg.name}: кривые обучения")
        fig.tight_layout(); fig.savefig(FIG / f"{cfg.name}_loss.png", dpi=130); plt.close(fig)

    m = te.sym == 0
    n = min(300, int(m.sum()))
    t = np.arange(n)
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(t, te.next_ohlc[m][-n:, 3], label="факт close", color="black", lw=1.2)
    ax.plot(t, ohlc_te[m][-n:, 3], label="LSTM (log-returns)", color="tab:blue", lw=1)
    ax.plot(t, raw_pred[m][-n:], label="LSTM на сырых ценах", color="tab:red", lw=1, ls="--")
    ax.axhline(rng[1], color="tab:red", lw=0.8, ls=":", label="max цены в train")
    ax.set_title(f"{cfg.symbols[0]}: прогноз следующего close на тесте (последние {n} свечей)")
    ax.legend(fontsize=8); fig.tight_layout(); fig.savefig(FIG / f"{cfg.name}_forecast.png", dpi=130); plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 3.8))
    ax.plot(test_bt["equity"], label="LSTM-стратегия (с издержками)")
    ax.plot(bh["equity"], label="Buy & Hold", alpha=0.7)
    ax.set_title(f"{cfg.name}: кривая капитала на тесте"); ax.legend(); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(FIG / f"{cfg.name}_equity.png", dpi=130); plt.close(fig)

    fig, ax = plt.subplots(figsize=(6, 3.5))
    ax.hist(p_te, bins=40, color="tab:purple")
    ax.set_title("Распределение P(up) на тесте"); ax.set_xlabel("P(up)")
    fig.tight_layout(); fig.savefig(FIG / f"{cfg.name}_pup.png", dpi=130); plt.close(fig)


if __name__ == "__main__":
    main()
