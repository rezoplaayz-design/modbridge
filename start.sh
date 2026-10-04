#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-8765}"
exec python3 server.py
