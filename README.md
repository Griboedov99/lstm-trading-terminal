# LSTM Trading Terminal

Домашнее задание №2 по курсу «Разработка интеллектуальных приложений»: клиент‑серверный торговый терминал
с LSTM‑прогнозом следующей свечи.

* **Модель** — PyTorch LSTM, прогноз всего OHLC следующей свечи + вероятность роста; признаки не зависят от уровня цены.
* **Сервер** — FastAPI: воспроизводит отложенную историю / генерирует GBM‑поток / (опц.) берёт живые котировки Binance,
  собирает свечи из тиков, в реальном времени выдаёт BUY / SELL / HOLD, ведёт демо‑счёт и автоторгового бота.
* **Клиент** — нативное iOS‑приложение на **Swift + UIKit** (без сторонних зависимостей): график японских свечей,
  рекомендации с уверенностью, ручная торговля и автоторговля, баланс, позиции, история, P&L.

Результаты обучения и бэктеста — в [`reports/REPORT.md`](reports/REPORT.md).

```
 data/raw ──prepare.py──▶ data/processed (OHLCV)
                              │
                 ml/train.py  ▼                       models/*.onnx + *.json
   признаки (common/features.py) → LSTM → бэктест ──────────────┐
                                                                ▼
 ┌──────────── server (FastAPI, Docker) ─────────────────────────────────┐
 │ ReplayFeed / GBMFeed / BinanceFeed → тики → свечи → Predictor (ONNX)  │
 │                    → сигнал BUY/SELL/HOLD → бот → PaperBroker (счёт)  │
 └───────────── WebSocket /ws/{symbol}  ·  REST /api/... ────────────────┘
                                  ▲
             iOS UIKit «LSTM Terminal» (ios/TradingTerminal.xcodeproj)
```

## Структура репозитория

| Путь | Что внутри |
|---|---|
| `data/raw/`, `data/processed/` | исходные котировки и OHLCV (`timestamp,open,high,low,close,volume`) |
| `data/prepare.py`, `scripts/download_data.sh` | скачивание и приведение данных к OHLCV |
| `common/features.py` | масштабно‑инвариантные признаки и цели (общие для обучения и сервера) |
| `ml/` | конфиги, датасеты, модели (LSTM/GRU/raw‑price), обучение, бэктест, генерация отчёта |
| `models/` | **предобученные веса**: `*.pt` (PyTorch), `*.onnx` (для сервера), `*.json` (скейлер, окно, пороги) |
| `reports/` | `REPORT.md`, метрики `*_metrics.json`, графики, логи обучения |
| `server/` | FastAPI‑сервер, Dockerfile |
| `ios/` | Xcode‑проект клиента на Swift/UIKit |
| `docker-compose.yml` | сервер (+ профиль `train` для переобучения) |

## Быстрый старт (≈ 5 минут, без обучения)

Нужны: Docker Desktop, Mac с Xcode 16+ (для клиента).

```bash
git clone https://github.com/Griboedov99/lstm-trading-terminal.git
cd lstm-trading-terminal

# 1. сервер
docker compose up --build -d
curl http://localhost:8000/api/health        # {"status":"ok","sessions":{"EURUSD":"running",...}}
open http://localhost:8000/docs              # Swagger со всеми эндпоинтами

# 2. клиент
open ios/TradingTerminal.xcodeproj           # выбрать симулятор iPhone → ⌘R
```

В симуляторе приложение само подключится к `http://localhost:8000`. На реальном iPhone: вкладка **Настройки** →
адрес `http://<IP вашего Mac в Wi‑Fi>:8000` → «Подключиться» (в Xcode выберите свою Team в Signing & Capabilities).

> Нет Xcode ≥ 16? `brew install xcodegen && cd ios && xcodegen generate` — проект пересоберётся из `ios/project.yml`.

### Без Docker

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r server/requirements.txt
uvicorn server.app.main:app --host 0.0.0.0 --port 8000
```

## Обучение модели

Предобученные веса уже лежат в `models/`. Переобучить «с нуля»:

```bash
pip install -r ml/requirements.txt
./scripts/download_data.sh                    # данные (уже в репозитории; скрипт — для воспроизводимости)
python data/prepare.py                        # → data/processed/*.csv
python ml/train.py --config eurusd_h1         # ~3 мин на CPU
python ml/train.py --config stocks_d1         # ~7 мин на CPU
python ml/make_report.py                      # → reports/REPORT.md
```

или в контейнере: `docker compose --profile train run --rm trainer` (веса и отчёты пишутся в `./models`, `./reports`).
После переобучения перезапустите сервер: `docker compose up --build -d`.

`train.py` делает: подбор окна и размера сети по валидации → обучение LSTM (early stopping) → калибровку
уверенности → базовые модели (наивная, ARIMA, GRU, LSTM на сырых ценах) → подбор порогов стратегии на валидации →
бэктест на тесте → экспорт в ONNX с проверкой паритета → графики. Флаг `--quick` — быстрый прогон (1 конфигурация),
`--reuse` — пересчитать метрики/бэктест для уже обученной модели.

## Тестовый поток данных

| Поток | Источник | Модель |
|---|---|---|
| `EURUSD` | воспроизведение **тестового** участка EUR/USD H1 (модель его не видела) | `eurusd_h1` |
| `NVDA`, `GOOG` | воспроизведение тестового участка D1 (2012+) | `stocks_d1` |
| `SYNTH` | синтетика: GBM с переключением режимов волатильности | `eurusd_h1` |
| `BTCUSDT` | живые свечи Binance M1 (если `ENABLE_BINANCE=1`) | `eurusd_h1` |

Скорость эмуляции — `CANDLE_SECONDS` в `docker-compose.yml` (по умолчанию 1 свеча = 2 с) или слайдер в настройках
приложения. Внутри свечи сервер генерирует 8 тиков по траектории open → low/high → close, поэтому свеча «растёт»
на глазах, а после закрытия совпадает с исторической.

Подключиться к потоку без клиента:

```bash
python - <<'EOF'
import asyncio, json, websockets
async def main():
    async with websockets.connect("ws://localhost:8000/ws/EURUSD") as ws:
        while True:
            m = json.loads(await ws.recv())
            if m["type"] == "candle":
                c, s = m["candle"], m["signal"]
                print(c["t"], c["o"], c["h"], c["l"], c["c"], "→", s["action"], f"{s['confidence']:.0%}")
asyncio.run(main())
EOF
```

### API

| Метод | Путь | Описание |
|---|---|---|
| WS | `/ws/{symbol}` | `snapshot` при подключении, затем `tick` (формирующаяся свеча + P&L), `candle` (закрытая свеча + сигнал + счёт), `account` |
| GET | `/api/symbols` | список потоков и моделей |
| GET | `/api/{symbol}/state` | полный снимок |
| POST | `/api/{symbol}/order` | `{"side":"buy"\|"sell","qty":10000}` — рыночный ордер |
| POST | `/api/{symbol}/close/{id}`, `/close_all` | закрыть позицию / все |
| POST | `/api/{symbol}/mode` | `{"mode":"manual"\|"auto","qty":10000}` |
| POST | `/api/{symbol}/speed` | `{"candle_seconds":1.0}` |
| POST | `/api/{symbol}/reset` | сбросить демо‑счёт |
| GET | `/api/report` | метрики модели и бэктеста (вкладка «Модель» в приложении) |

Пример сигнала:
```json
{"action":"BUY","confidence":0.561,"p_up":0.561,"expected_return":0.00012,
 "predicted":{"open":1.23101,"high":1.23188,"low":1.23032,"close":1.23116},
 "online_hit_rate":0.53,"online_scored":120}
```

## Клиент (iOS, Swift/UIKit)

* **Терминал** — график свечей (CoreGraphics): зелёная — close > open, красная — close < open, тени high/low,
  объём, линия текущей цены, линии входа открытых позиций, **пунктирная прогнозная свеча LSTM**;
  pinch — масштаб, свайп — история, удержание — перекрестие с O/H/L/C. Ниже — карточка рекомендации
  (BUY/SELL/HOLD, уверенность, P(рост), прогноз close/high/low, онлайн‑точность), переключатель
  **Ручная торговля / Автоторговля**, объём, кнопки BUY/SELL, журнал бота, баланс/эквити/P&L.
* **Портфель** — кривая капитала, статистика (сделки, winrate, макс. просадка), открытые позиции (свайп — закрыть),
  история сделок, журнал бота.
* **Модель** — метрики LSTM против базовых моделей и результаты бэктеста с сервера.
* **Настройки** — адрес сервера, скорость эмуляции, сброс счёта.

Код: `Core/` (модели JSON, REST, WebSocket с автопереподключением, единое состояние), `UI/` (график, компоненты),
`Screens/` (экраны). Минимальная версия iOS — 15.

**Скриншоты/видео для сдачи:** в симуляторе ⌘S — скриншот; видео — `xcrun simctl io booted recordVideo demo.mov`
(Ctrl+C для остановки). Покажите: график + прогнозную свечу, смену рекомендаций, ручную сделку, включение автоторговли
и вкладку «Портфель».

## Соответствие критериям

| Критерий | Где |
|---|---|
| Предобработка, устойчивая к масштабу цен (15) | `common/features.py`, раздел 2 отчёта (сравнение с LSTM на сырых ценах) |
| Качество и обоснованность LSTM (20) | `ml/`, разделы 3–4 отчёта (подбор окна/слоёв, лосс, оптимизатор, early stopping, MAE/RMSE/MAPE/направление) |
| Сервер‑эмулятор с потоком свечей (15) | `server/app/feeds.py`, `session.py`, `main.py` |
| Клиент с графиком японских свечей (15) | `ios/TradingTerminal/UI/CandleChartView.swift` |
| Рекомендации в реальном времени (10) | `server/app/predictor.py` → WebSocket → `SignalCardView` |
| Ручной + авто режимы (10) | `server/app/broker.py`, `session.py::_bot_step`, вкладка «Терминал» |
| Docker, README (10) | `server/Dockerfile`, `docker-compose.yml`, этот файл |
| Бэктест и прибыльность (5) | `ml/backtest.py`, раздел 5–6 отчёта |
| Бонусы | доп. признаки (RSI, MACD, ROC, волатильность, объём); сравнение с GRU/ARIMA; живой API Binance (опц.); тёмный UI |
