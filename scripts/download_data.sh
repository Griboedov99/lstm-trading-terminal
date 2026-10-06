#!/usr/bin/env bash
# Скачивает открытые исторические котировки в data/raw.
# Данные уже лежат в репозитории; скрипт нужен для воспроизводимости «с нуля».
set -euo pipefail
cd "$(dirname "$0")/../data/raw"

BT=https://raw.githubusercontent.com/kernc/backtesting.py/master/backtesting/test
BTR=https://raw.githubusercontent.com/mementum/backtrader/master/datas

curl -fsSL -o EURUSD.csv "$BT/EURUSD.csv"            # Forex EUR/USD, H1
curl -fsSL -o GOOG.csv "$BT/GOOG.csv"                # Google, D1
curl -fsSL -o nvda-1999-2014.csv "$BTR/nvda-1999-2014.txt"   # Yahoo Finance, D1
curl -fsSL -o orcl-1995-2014.csv "$BTR/orcl-1995-2014.txt"
curl -fsSL -o yhoo-1996-2015.csv "$BTR/yhoo-1996-2015.txt"
echo "OK: $(ls -1 | wc -l) файлов в data/raw"
