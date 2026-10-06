# Образ для переобучения модели «с нуля» (CPU). Запуск: docker compose --profile train run --rm trainer
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app
WORKDIR /app
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
COPY ml/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY . .
CMD ["sh", "-c", "python data/prepare.py && python ml/train.py --config eurusd_h1 && python ml/train.py --config stocks_d1"]
