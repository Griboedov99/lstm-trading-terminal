# Сервер-эмулятор торгов: FastAPI + ONNX Runtime (без PyTorch → образ ~350 МБ, сборка ~1–2 мин)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app \
    MODELS_DIR=/app/models DATA_DIR=/app/data/processed REPORTS_DIR=/app/reports
WORKDIR /app

COPY server/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY common/ ./common/
COPY server/ ./server/
COPY models/*.onnx models/*.json ./models/
COPY data/processed/ ./data/processed/
COPY reports/*_metrics.json ./reports/

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')" || exit 1
CMD ["uvicorn", "server.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
