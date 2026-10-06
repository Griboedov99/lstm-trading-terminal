"""Конфигурации экспериментов.

Таймфреймы:
  * EUR/USD — H1. M1/M5 на Forex почти полностью состоят из микроструктурного шума
    (bid/ask bounce), а спред съедает ожидаемое движение свечи; D1 даёт слишком мало
    точек (≈260 в год). H1: 24 свечи в сутки, тренды внутри сессий, движение свечи
    (~8 пунктов) кратно превышает спред (~0.8 пункта) — прогноз имеет смысл торговать.
  * Акции — D1: торговая сессия ~6.5 ч и большой ночной гэп, внутридневная история
    в открытых источниках короткая; дневки доступны за 15–20 лет.
"""
from dataclasses import dataclass, field


@dataclass
class DatasetConfig:
    name: str
    symbols: list
    intraday: bool
    timeframe: str
    lookbacks: list                     # кандидаты на размер окна (выбор по val)
    bars_per_year: int                  # для годового Sharpe
    cost: float                         # издержки на единицу оборота (доля цены)
    split_frac: tuple | None = None     # (train_end, val_end) как доля длины ряда
    split_dates: tuple | None = None    # (val_start, test_start) — общие для всех тикеров
    arch_grid: list = field(default_factory=lambda: [(1, 32), (2, 64)])  # (layers, hidden)


CONFIGS = {
    "eurusd_h1": DatasetConfig(
        name="eurusd_h1",
        symbols=["EURUSD_H1"],
        intraday=True,
        timeframe="H1",
        lookbacks=[24, 48, 96],
        bars_per_year=24 * 5 * 52,      # ≈ 6240 часовых свечей в торговом году Forex
        cost=0.00007,                   # спред ≈ 0.8 пункта на 1.15 ≈ 0.7 б.п.
        split_frac=(0.70, 0.85),
    ),
    "stocks_d1": DatasetConfig(
        name="stocks_d1",
        symbols=["GOOG_D1", "NVDA_D1", "ORCL_D1", "YHOO_D1"],
        intraday=False,
        timeframe="D1",
        lookbacks=[20, 40, 60],
        bars_per_year=252,
        cost=0.0005,                    # 5 б.п.: комиссия + проскальзывание
        split_dates=("2010-01-01", "2012-01-01"),
    ),
}

# Общие гиперпараметры обучения
BATCH = 256
LR = 1e-3
WEIGHT_DECAY = 1e-5
MAX_EPOCHS = 80
PATIENCE = 10
DROPOUT = 0.2
CLS_WEIGHT = 0.5      # вес BCE-головы направления в суммарной функции потерь
SEED = 42
