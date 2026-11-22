#!/usr/bin/env bash
# 启动后端（同时托管已构建的前端）
set -e
cd "$(dirname "$0")"
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8000}"
