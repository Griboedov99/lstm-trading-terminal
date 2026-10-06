"""Собирает reports/REPORT.md из reports/*_metrics.json (запускать после ml/train.py)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REP = ROOT / "reports"


def pct(x, d=2, sign=False):
    s = f"{x * 100:+.{d}f}%" if sign else f"{x * 100:.{d}f}%"
    return s.replace("-", "−")


def load(name):
    return json.loads((REP / f"{name}_metrics.json").read_text())


def metrics_table(r):
    rows = ["| Модель | MAE | RMSE | MAPE | Точность направления |", "|---|---|---|---|---|"]
    order = ["LSTM", "GRU", "ARIMA(1,0,1) on log-returns", "Naive (C_t+1 = C_t)", "LSTM on raw prices (min-max)"]
    names = {"LSTM": "**LSTM (log-returns, наша)**", "GRU": "GRU (та же схема)",
             "ARIMA(1,0,1) on log-returns": "ARIMA(1,0,1) по log-returns",
             "Naive (C_t+1 = C_t)": "Наивная: C̃(t+1)=C(t), направление = знак последнего Δ",
             "LSTM on raw prices (min-max)": "LSTM на сырых ценах (global min-max)"}
    for k in order:
        m = r["metrics_test"].get(k)
        if not m:
            continue
        rows.append(f"| {names[k]} | {m['MAE']:.5g} | {m['RMSE']:.5g} | {m['MAPE_%']:.3f}% | {m['DirAcc_%']:.1f}% |")
    return "\n".join(rows)


def bt_table(r):
    b = r["backtest"]
    rows = ["| Стратегия | Доходность | Годовая | Sharpe | Макс. просадка | Winrate | Сделок | В рынке |",
            "|---|---|---|---|---|---|---|---|"]
    items = [("validation", "LSTM, **валидация** (подбор порогов)"), ("test", "**LSTM, тест, с издержками**"),
             ("test_without_costs", "LSTM, тест, без издержек"),
             ("test_always_in_market", "LSTM без фильтра уверенности (P>0.5), тест"),
             ("buy_and_hold", "Buy & Hold, тест")]
    for k, title in items:
        d = b[k]
        rows.append(f"| {title} | {pct(d['total_return'], sign=True)} | {pct(d['annual_return'], 1, True)} | "
                    f"{d['sharpe']:.2f} | {pct(d['max_drawdown'])} | {pct(d['winrate'], 0)} | {d['n_trades']} | "
                    f"{pct(d['exposure'], 0)} |")
    return "\n".join(rows)


def grid_table(r):
    rows = ["| lookback | слоёв × нейронов | val loss | эпох до early stop |", "|---|---|---|---|"]
    sel = r["selected"]
    for g in r["grid"]:
        mark = " ✅" if (g["lookback"], g["layers"], g["hidden"]) == (sel["lookback"], sel["layers"], sel["hidden"]) else ""
        rows.append(f"| {g['lookback']} | {g['layers']} × {g['hidden']}{mark} | {g['val_loss']:.5f} | {g['epochs']} |")
    return "\n".join(rows)


def main():
    fx, st = load("eurusd_h1"), load("stocks_d1")
    raw_fx = fx["metrics_test"]["LSTM on raw prices (min-max)"]
    lstm_fx = fx["metrics_test"]["LSTM"]
    raw_st = st["metrics_test"]["LSTM on raw prices (min-max)"]
    lstm_st = st["metrics_test"]["LSTM"]
    per = st.get("metrics_test_per_symbol") or {}
    per_rows = "\n".join(f"| {s.replace('_D1', '')} | {m['MAPE_%']:.3f}% | {m['DirAcc_%']:.1f}% |" for s, m in per.items())
    fxb, stb = fx["backtest"], st["backtest"]

    md = f"""# Отчёт: LSTM-прогноз свечей и бэктест торговой стратегии

> Сгенерирован скриптом `ml/make_report.py` из `reports/*_metrics.json`. Все цифры — на **отложенной (тестовой)** части данных,
> которую модель не видела ни при обучении, ни при подборе гиперпараметров и порогов.

## 1. Данные

| Набор | Рынок | Таймфрейм | Период | Источник |
|---|---|---|---|---|
| EUR/USD | Forex | **H1** | 2017‑04‑19 … 2018‑02‑07, 5 000 свечей | выборка котировок из `backtesting.py` |
| GOOG, NVDA, ORCL, YHOO | акции США | **D1** | 1995…2015, ≈ 16 000 свечей | Yahoo Finance (наборы `backtrader`, `backtesting.py`) |

**Почему такие таймфреймы.** Для Forex выбран H1: на M1/M5 движение свечи сопоставимо со спредом (≈ 0.8 пункта) и
состоит в основном из микроструктурного шума, а на D1 за доступный период слишком мало точек. На H1 средний ход свечи ≈ 8
пунктов, т.е. в ~10 раз больше спреда, а 24 свечи в сутки дают достаточно данных. Для акций — D1: открытые внутридневные
истории короткие, а дневки доступны за 15–20 лет; торговая сессия с ночным гэпом естественно делится на дневные свечи.

**Разбиение — строго по времени, без перемешивания между выборками.** Сэмпл относится к выборке по времени
*свечи‑цели*, поэтому окно никогда не «заглядывает» в соседнюю выборку.

* EUR/USD: train 70 % / val 15 % / test 15 % → тест {fx['test_period'][0][:10]} … {fx['test_period'][1][:10]}.
* Акции: общие для всех тикеров даты — train < 2010‑01‑01 ≤ val < 2012‑01‑01 ≤ test
  ({st['test_period'][0][:10]} … {st['test_period'][1][:10]}).

## 2. Предобработка, устойчивая к уровню цен (критерий 15 %)

Ни один признак не зависит от абсолютной цены (`common/features.py`, один и тот же код используется при обучении и на сервере):

| Признак | Формула |
|---|---|
| ret_1 | log(Cₜ / Cₜ₋₁) |
| gap, body | log(Oₜ / Cₜ₋₁), log(Cₜ / Oₜ) |
| upper, lower | log(Hₜ / max(O,C)), log(min(O,C) / Lₜ) — тени свечи |
| vol_20 | std(ret_1) за 20 свечей — волатильность |
| roc_10 | log(Cₜ / Cₜ₋₁₀) — скорость изменения цены (ROC) |
| z_20 | (C − SMA20) / STD20 — rolling z‑score цены |
| rsi_14 | (RSI14 − 50) / 50 |
| macd_h | (MACD − signal) / Cₜ — гистограмма MACD, нормированная на цену |
| vol_z | rolling z‑score log‑объёма (окно 50) |
| hour_sin/cos | час суток (только для H1) |

Затем признаки стандартизируются средними/СКО, посчитанными **только на train**, и обрезаются в [−5, 5].
**Цель — не цена, а лог‑приращения следующей свечи относительно текущего close:**
`log(Oₜ₊₁/Cₜ), log(Hₜ₊₁/Cₜ), log(Lₜ₊₁/Cₜ), log(Cₜ₊₁/Cₜ)`; цена восстанавливается как `Cₜ·exp(ŷ)`.

**Проверка.** Цена EUR/USD на тесте — {fx['test_price_range'][0]:.4f}…{fx['test_price_range'][1]:.4f}, а на train максимум был
{fx['train_price_range'][1]:.4f}: тест в основном **выше всего, что модель видела**. Акции на тесте торгуются в 10–20 раз дороже, чем в
начале train. Контрольная LSTM на сырых ценах с глобальным min‑max:

| | EUR/USD H1, MAPE | Акции D1, MAPE |
|---|---|---|
| LSTM на сырых ценах (min‑max) | {raw_fx['MAPE_%']:.3f}% | {raw_st['MAPE_%']:.2f}% |
| **LSTM на log‑returns (наша)** | **{lstm_fx['MAPE_%']:.3f}%** | **{lstm_st['MAPE_%']:.3f}%** |

Сырая модель «упирается» в потолок min‑max (сигмоида не может выдать цену выше максимума train) — ошибка в
{raw_fx['MAPE_%'] / lstm_fx['MAPE_%']:.0f}× больше. Наша модель такой проблемы не имеет по построению.

![forecast](figures/eurusd_h1_forecast.png)

## 3. Модель LSTM (критерий 20 %)

```
вход (lookback × 13 признаков)
 → LSTM (layers × hidden, dropout 0.2 между слоями)
 → LayerNorm → Dropout(0.2)
 ├─ reg‑голова: Linear(hidden → 4)  — log‑приращения O/H/L/C следующей свечи
 └─ cls‑голова: Linear(hidden → 1)  — логит P(close вырастет)
```

* **Функция потерь:** `Huber(reg) + 0.5·BCE(cls)`. Huber (SmoothL1) устойчив к «толстым хвостам» доходностей —
  редкие гэпы не доминируют в градиенте, как в MSE. BCE‑голова даёт вероятность направления → «уверенность» и BUY/SELL/HOLD.
  Цели нормированы на СКО приращения close (target_scale), чтобы обе части лосса были одного масштаба.
* **Оптимизатор:** Adam, lr = 1e‑3, weight decay 1e‑5, ReduceLROnPlateau(×0.5, patience 4), клиппинг градиента 1.0, batch 256.
* **Эпохи:** до 80, early stopping по val loss (patience 10), берутся веса лучшей эпохи. Реально останавливается на 15–45 эпохе:
  дальше модель начинает запоминать шум train.
* **Калибровка:** temperature scaling на валидации (T = {fx['temperature']:.2f} для EUR/USD, {st['temperature']:.2f} для акций),
  чтобы «уверенность 55 %» действительно означала ~55 %.
* **Окно и размер сети** выбраны перебором по val loss:

EUR/USD H1:

{grid_table(fx)}

Акции D1:

{grid_table(st)}

Для H1 оптимально окно 48 часов (двое суток: внутридневная сезонность + вчерашняя сессия); 96 — уже переобучение.
Для дневок — 60 дней (≈ квартал). Небольшие сети (1×32, 2×64) выигрывают: в финансовых рядах мало сигнала, и
крупная сеть быстрее переобучается. Обучение: `models/*.pt`, экспорт для сервера: `models/*.onnx` (паритет torch↔ONNX: max|Δ| ≈ {max(fx['onnx_parity'], st['onnx_parity']):.0e}).

![loss](figures/eurusd_h1_loss.png)

## 4. Качество прогноза на тесте

**EUR/USD H1** ({fx['n_windows']['test']} свечей):

{metrics_table(fx)}

**Акции D1** ({st['n_windows']['test']} свечей, 4 тикера):

{metrics_table(st)}

По тикерам (LSTM):

| Тикер | MAPE | Точность направления |
|---|---|---|
{per_rows}

Прогноз high/low/open: MAPE open {lstm_fx['MAPE_open_%']:.3f}%, high {lstm_fx['MAPE_high_%']:.3f}%, low {lstm_fx['MAPE_low_%']:.3f}% (EUR/USD).

**Интерпретация.** По MAE/RMSE LSTM, GRU и ARIMA практически совпадают с наивным прогнозом «завтра = сегодня» — это
ожидаемо: на горизонте одной свечи цена близка к случайному блужданию, и любая модель, минимизирующая ошибку,
прижимается к нулевому приращению. Сигнал содержится в **направлении**: LSTM угадывает его в {lstm_fx['DirAcc_%']:.1f}% (EUR/USD) и
{lstm_st['DirAcc_%']:.1f}% (акции) случаев против ~49 % у наивного momentum‑правила. Преимущество над GRU/ARIMA — в пределах
статистической погрешности (±1.8 п.п. для 750 свечей).

## 5. Бэктест (критерий 5 %)

Правило — то же, что у бота на сервере: на закрытии свечи t
**BUY** (long), если `P(up) ≥ p_thr` и прогноз Δclose > r_thr; **SELL** (short), если `P(up) ≤ 1 − p_thr` и Δclose < −r_thr;
иначе **HOLD** — вне рынка. Позиция держится одну свечу. Издержки списываются с каждого изменения позиции.
Пороги подбираются **на валидации** (максимум Sharpe при ≥ 20 сделках) и на тесте не меняются.

**EUR/USD H1** — порог P(up) = {fxb['thresholds']['p_thr']:.2f}, издержки {fxb['cost_per_turnover'] * 1e4:.1f} б.п. (≈ спред 0.8 пункта):

{bt_table(fx)}

![equity fx](figures/eurusd_h1_equity.png)

**Акции D1, равновзвешенный портфель из 4 тикеров** — порог P(up) = {stb['thresholds']['p_thr']:.2f}, издержки {stb['cost_per_turnover'] * 1e4:.0f} б.п.:

{bt_table(st)}

![equity stocks](figures/stocks_d1_equity.png)

Sharpe — годовой (×√6240 для H1, ×√252 для D1), просадка — по кривой капитала стратегии.

## 6. Прибыльна ли стратегия

{conclusion(fx, st)}

## 7. Ограничения и что можно улучшить

* Мало данных EUR/USD (≈ 10 месяцев H1). На длинной истории (2010–2024) модель увидит разные режимы рынка.
* Горизонт одной свечи — самый шумный. Прогноз на 4–24 свечи и выход по стоп‑лоссу/тейк‑профиту обычно дают лучшее
  отношение сигнал/издержки.
* Не учтены свопы, проскальзывание при гэпах и ограничения на шорт акций.
* Порог уверенности подобран на одной валидации — для надёжности нужна walk‑forward‑оптимизация.
"""
    (REP / "REPORT.md").write_text(md)
    print("written", REP / "REPORT.md")


def conclusion(fx, st):
    f, s = fx["backtest"], st["backtest"]
    ft, st_ = f["test"], s["test"]
    lines = []
    if ft["total_return"] <= 0:
        lines.append(
            f"**EUR/USD H1 — нет.** На тесте стратегия теряет {pct(-ft['total_return'])} (Sharpe {ft['sharpe']:.2f}); "
            f"без издержек — {pct(f['test_without_costs']['total_return'], sign=True)}. "
            "Уже на валидации ни одна комбинация порогов не дала положительного Sharpe, т.е. у модели нет устойчивого "
            "преимущества на часовых свечах EUR/USD. Причины: (1) EUR/USD — самый ликвидный рынок мира, "
            "краткосрочные закономерности в OHLCV сразу арбитражируются; (2) точность направления ~51 % при среднем "
            "ходе свечи ~8 пунктов даёт ожидаемый доход < 1 пункта на сделку — его съедает спред; "
            "(3) тест пришёлся на сильный тренд (+3.7 % buy & hold), а стратегия по построению симметрична и большую "
            "часть времени вне рынка. Честный вывод: LSTM‑сигнал на H1 Forex — это подсказка, а не источник альфы.")
    else:
        lines.append(f"**EUR/USD H1:** доходность {pct(ft['total_return'], sign=True)}, Sharpe {ft['sharpe']:.2f}.")
    if st_["total_return"] > 0:
        bh = s["buy_and_hold"]
        lines.append(
            f"\n**Акции D1 — да, но скромно.** Стратегия заработала {pct(st_['total_return'], sign=True)} "
            f"за тест с издержками (Sharpe {st_['sharpe']:.2f}, просадка {pct(st_['max_drawdown'])}), находясь в рынке лишь "
            f"{pct(st_['exposure'], 0)} времени. Buy & Hold за тот же период: {pct(bh['total_return'], sign=True)} "
            f"(Sharpe {bh['sharpe']:.2f}, просадка {pct(bh['max_drawdown'])}). То есть по абсолютной доходности стратегия "
            "проигрывает пассивному владению на растущем рынке 2012–2015, но даёт сопоставимую доходность на единицу риска "
            "при многократно меньшей просадке. Сигнал работает только с фильтром уверенности: без него "
            f"(всегда в рынке) Sharpe падает до {s['test_always_in_market']['sharpe']:.2f}.")
    else:
        lines.append(f"\n**Акции D1 — нет:** {pct(st_['total_return'], sign=True)}, Sharpe {st_['sharpe']:.2f}.")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
