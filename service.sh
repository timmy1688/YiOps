#!/usr/bin/env bash

set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$ROOT/.runtime/yiops.pid"
LOG_FILE="$ROOT/logs/yiops.log"
PYTHON="$ROOT/backend/.venv/bin/python"
PORT="${YIOPS_PORT:-8100}"

running() {
    [[ -f "$PID_FILE" ]] &&
        kill -0 "$(cat "$PID_FILE")" 2>/dev/null &&
        [[ "$(ps -p "$(cat "$PID_FILE")" -o stat= 2>/dev/null)" != *Z* ]]
}

start() {
    if running; then
        echo "YiOps already running, PID $(cat "$PID_FILE")"
        return
    fi
    if [[ ! -x "$PYTHON" ]]; then
        echo "Missing backend/.venv; install backend dependencies first."
        exit 1
    fi
    if [[ ! -f "$ROOT/frontend/dist/index.html" ]]; then
        echo "Missing frontend/dist; run: cd frontend && npm run build"
        exit 1
    fi

    mkdir -p "$ROOT/.runtime" "$ROOT/logs"
    cd "$ROOT/backend" || exit 1
    nohup "$PYTHON" -m uvicorn app.main:app \
        --host 0.0.0.0 --port "$PORT" > "$LOG_FILE" 2>&1 &
    echo "$!" > "$PID_FILE"
    sleep 1

    if running; then
        echo "YiOps started: http://127.0.0.1:${PORT}/"
    else
        echo "YiOps failed to start. See $LOG_FILE"
        exit 1
    fi
}

run_foreground() {
    if running; then
        echo "YiOps already running, PID $(cat "$PID_FILE")"
        return
    fi
    if [[ ! -x "$PYTHON" ]]; then
        echo "Missing backend/.venv; install backend dependencies first."
        exit 1
    fi
    if [[ ! -f "$ROOT/frontend/dist/index.html" ]]; then
        echo "Missing frontend/dist; run: cd frontend && npm run build"
        exit 1
    fi

    mkdir -p "$ROOT/.runtime" "$ROOT/logs"
    cd "$ROOT/backend" || exit 1
    echo "$$" > "$PID_FILE"
    exec "$PYTHON" -m uvicorn app.main:app \
        --host 0.0.0.0 --port "$PORT"
}

stop() {
    if ! running; then
        rm -f "$PID_FILE"
        echo "YiOps is not running."
        return
    fi

    local pid
    pid="$(cat "$PID_FILE")"
    kill "$pid"
    rm -f "$PID_FILE"
    echo "YiOps stopped."
}

status() {
    if running; then
        echo "YiOps running, PID $(cat "$PID_FILE"), port ${PORT}"
    else
        echo "YiOps stopped"
        return 1
    fi
}

case "${1:-}" in
    start) start ;;
    run) run_foreground ;;
    stop) stop ;;
    restart) stop; start ;;
    status) status ;;
    logs) tail -f "$LOG_FILE" ;;
    *) echo "Usage: $0 {start|run|stop|restart|status|logs}"; exit 1 ;;
esac
