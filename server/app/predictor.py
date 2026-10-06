"""Онлайн-инференс LSTM (ONNX Runtime) поверх тех же признаков, что и при обучении."""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import onnxruntime as ort
import pandas as pd

from common.features import WARMUP, compute_features, reconstruct_candle, standardize


@dataclass
class Signal:
    action: str               # BUY / SELL / HOLD
    confidence: float         # уверенность в направлении = max(P(up), 1 − P(up))
    p_up: float               # калиброванная вероятность роста следующего close
    expected_return: float    # прогноз log(C_{t+1}/C_t)
    predicted: dict           # прогноз следующей свечи (open/high/low/close)
    based_on: int             # timestamp свечи, по которой сделан прогноз
    model: str

    def to_dict(self):
        d = asdict(self)
        d["expected_return_pct"] = self.expected_return * 100
        return d


class Predictor:
    def __init__(self, models_dir: Path, name: str):
        self.name = name
        self.meta = json.loads((models_dir / f"{name}.json").read_text())
        self.session = ort.InferenceSession(str(models_dir / f"{name}.onnx"), providers=["CPUExecutionProvider"])
        self.lookback = int(self.meta["lookback"])
        self.mean = np.asarray(self.meta["mean"], dtype=np.float64)
        self.std = np.asarray(self.meta["std"], dtype=np.float64)
        self.scale = float(self.meta["target_scale"])
        self.T = float(self.meta["temperature"])
        self.p_thr = float(self.meta["p_thr"])
        self.r_thr = float(self.meta["r_thr"])
        self.intraday = bool(self.meta["intraday"])

    @property
    def min_history(self) -> int:
        return self.lookback + WARMUP

    def predict(self, candles: list[dict]) -> Signal | None:
        """candles — закрытые свечи (dict t,o,h,l,c,v), последняя — самая свежая."""
        if len(candles) < self.min_history:
            return None
        tail = candles[-(self.min_history + 20):]
        df = pd.DataFrame({
            "timestamp": pd.to_datetime([c["t"] for c in tail], unit="s"),
            "open": [c["o"] for c in tail], "high": [c["h"] for c in tail],
            "low": [c["l"] for c in tail], "close": [c["c"] for c in tail],
            "volume": [c.get("v", 0.0) for c in tail],
        })
        feats = compute_features(df, self.intraday).to_numpy(np.float64)
        x = standardize(feats[-self.lookback:], self.mean, self.std)[None]
        reg, logit = self.session.run(None, {"x": x})
        reg = reg[0].astype(np.float64) * self.scale
        p_up = float(1.0 / (1.0 + np.exp(-float(logit[0]) / self.T)))
        exp_ret = float(reg[3])
        if p_up >= self.p_thr and exp_ret > self.r_thr:
            action = "BUY"
        elif p_up <= 1 - self.p_thr and exp_ret < -self.r_thr:
            action = "SELL"
        else:
            action = "HOLD"
        last = candles[-1]
        pred = reconstruct_candle(float(last["c"]), reg)
        return Signal(action=action, confidence=max(p_up, 1 - p_up), p_up=p_up, expected_return=exp_ret,
                      predicted=pred, based_on=int(last["t"]), model=self.name)
