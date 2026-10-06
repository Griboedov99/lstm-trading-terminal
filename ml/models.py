"""Архитектуры: LSTM (основная), GRU (сравнение), LSTM на абсолютных ценах (анти-пример)."""
import torch
from torch import nn


class SeqForecaster(nn.Module):
    """Рекуррентная сеть с двумя головами.

    * reg  — 4 числа: лог-приращения следующей свечи (open/high/low/close) относительно текущего close,
             в единицах target_scale (std приращения close на train);
    * logit — логит вероятности того, что следующий close > текущего (для BUY/SELL и «уверенности»).
    """

    def __init__(self, n_features: int, hidden: int = 64, layers: int = 2, dropout: float = 0.2, cell: str = "lstm"):
        super().__init__()
        rnn_cls = nn.LSTM if cell == "lstm" else nn.GRU
        self.rnn = rnn_cls(n_features, hidden, num_layers=layers, batch_first=True,
                           dropout=dropout if layers > 1 else 0.0)
        self.norm = nn.LayerNorm(hidden)
        self.drop = nn.Dropout(dropout)
        self.reg = nn.Linear(hidden, 4)
        self.cls = nn.Linear(hidden, 1)

    def forward(self, x):
        out, _ = self.rnn(x)
        h = self.drop(self.norm(out[:, -1]))
        return self.reg(h), self.cls(h).squeeze(-1)


class RawPriceLSTM(nn.Module):
    """Наивный подход: окно абсолютных цен, глобальный min-max по train → следующая цена.
    Нужен только как контрпример: при выходе цены за диапазон train прогноз «упирается в потолок»."""

    def __init__(self, hidden: int = 64):
        super().__init__()
        self.rnn = nn.LSTM(1, hidden, num_layers=2, batch_first=True, dropout=0.2)
        self.out = nn.Sequential(nn.Linear(hidden, 1), nn.Sigmoid())  # min-max ⇒ выход в [0, 1]

    def forward(self, x):
        out, _ = self.rnn(x)
        return self.out(out[:, -1]).squeeze(-1)
