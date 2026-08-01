#!/usr/bin/env bash

set -Eeuo pipefail

YIOPS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
YIOPS_PID_FILE="$YIOPS_ROOT/.runtime/yiops.pid"
YIOPS_MODE_FILE="$YIOPS_ROOT/.runtime/service-mode"
YIOPS_LOG_FILE="$YIOPS_ROOT/logs/yiops.log"
YIOPS_PYTHON="$YIOPS_ROOT/backend/.venv/bin/python"
YIOPS_PORT="${YIOPS_PORT:-8100}"
YIOPS_ACTION="${1:-status}"

service_mode() {
    if [[ -n "${YIOPS_SERVICE_MODE:-}" ]]; then
        printf '%s' "$YIOPS_SERVICE_MODE"
    elif [[ -f "$YIOPS_MODE_FILE" ]]; then
        tr -d '[:space:]' < "$YIOPS_MODE_FILE"
    elif [[ -x "$YIOPS_PYTHON" ]]; then
        printf 'source'
    else
        printf 'compose'
    fi
}

source_running() {
    local pid stat
    pid="$(cat "$YIOPS_PID_FILE" 2>/dev/null || true)"
    if [[ ! "$pid" =~ ^[0-9]+$ ]] || ! kill -0 "$pid" 2>/dev/null; then
        pid="$(pgrep -f -- "$YIOPS_PYTHON -m uvicorn app.main:app --host 0.0.0.0 --port $YIOPS_PORT" | head -n 1 || true)"
    fi
    [[ "$pid" =~ ^[0-9]+$ ]] || return 1
    kill -0 "$pid" 2>/dev/null || return 1
    stat="$(ps -p "$pid" -o stat= 2>/dev/null || true)"
    if [[ -n "$stat" && "$stat" != *Z* ]]; then
        printf '%s\n' "$pid" > "$YIOPS_PID_FILE"
        return 0
    fi
    return 1
}

prepare_source() {
    if [[ ! -x "$YIOPS_PYTHON" ]]; then
        echo "Missing backend/.venv; install backend dependencies first." >&2
        exit 1
    fi
    if [[ ! -f "$YIOPS_ROOT/frontend/dist/index.html" ]]; then
        echo "Missing frontend/dist; run: cd frontend && npm run build" >&2
        exit 1
    fi
    mkdir -p "$YIOPS_ROOT/.runtime" "$YIOPS_ROOT/logs"
    (cd "$YIOPS_ROOT/backend" && "$YIOPS_ROOT/backend/.venv/bin/aerich" upgrade)
}

wait_for_source() {
    local attempt
    for attempt in {1..20}; do
        if ! source_running; then
            echo "YiOps failed to start. See $YIOPS_LOG_FILE" >&2
            return 1
        fi
        if "$YIOPS_PYTHON" -c \
            "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${YIOPS_PORT}/api/v1/health/ready', timeout=1)" \
            >/dev/null 2>&1; then
            return 0
        fi
        sleep 0.5
    done
    echo "YiOps started but did not become ready. See $YIOPS_LOG_FILE" >&2
    return 1
}

source_start() {
    if source_running; then
        echo "YiOps already running, PID $(cat "$YIOPS_PID_FILE")"
        return
    fi
    rm -f "$YIOPS_PID_FILE"
    prepare_source
    cd "$YIOPS_ROOT/backend"
    nohup "$YIOPS_PYTHON" -m uvicorn app.main:app \
        --host 0.0.0.0 --port "$YIOPS_PORT" --no-access-log \
        > "$YIOPS_LOG_FILE" 2>&1 &
    echo "$!" > "$YIOPS_PID_FILE"
    wait_for_source
    echo "YiOps started: http://127.0.0.1:${YIOPS_PORT}/"
}

source_run() {
    if source_running; then
        echo "YiOps already running, PID $(cat "$YIOPS_PID_FILE")"
        return
    fi
    rm -f "$YIOPS_PID_FILE"
    prepare_source
    cd "$YIOPS_ROOT/backend"
    echo "$BASHPID" > "$YIOPS_PID_FILE"
    exec "$YIOPS_PYTHON" -m uvicorn app.main:app \
        --host 0.0.0.0 --port "$YIOPS_PORT" --no-access-log
}

source_stop() {
    if ! source_running; then
        rm -f "$YIOPS_PID_FILE"
        echo "YiOps is not running."
        return
    fi
    local pid attempt
    pid="$(cat "$YIOPS_PID_FILE")"
    kill "$pid"
    for attempt in {1..20}; do
        if ! kill -0 "$pid" 2>/dev/null; then
            rm -f "$YIOPS_PID_FILE"
            echo "YiOps stopped."
            return
        fi
        sleep 0.5
    done
    echo "YiOps is still stopping, PID $pid" >&2
    return 1
}

source_status() {
    if source_running; then
        echo "YiOps running, PID $(cat "$YIOPS_PID_FILE"), port ${YIOPS_PORT} (source mode)"
    else
        rm -f "$YIOPS_PID_FILE"
        echo "YiOps stopped (source mode)"
        return 1
    fi
}

compose_action() {
    case "$YIOPS_ACTION" in
        install) exec "$YIOPS_ROOT/deploy.sh" up ;;
        start|run) exec "$YIOPS_ROOT/deploy.sh" up ;;
        stop) exec "$YIOPS_ROOT/deploy.sh" down ;;
        restart|status|logs) exec "$YIOPS_ROOT/deploy.sh" "$YIOPS_ACTION" ;;
        *) return 1 ;;
    esac
}

YIOPS_MODE="$(service_mode)"
if [[ "$YIOPS_ACTION" == "mode" ]]; then
    echo "$YIOPS_MODE"
    exit 0
fi
if [[ "$YIOPS_ACTION" == "install" ]]; then
    mkdir -p "$YIOPS_ROOT/.runtime"
    printf 'compose\n' > "$YIOPS_MODE_FILE"
    exec "$YIOPS_ROOT/deploy.sh" up
fi
if [[ "$YIOPS_MODE" == "compose" ]]; then
    compose_action || {
        echo "Usage: $0 {install|start|run|stop|restart|status|logs|mode}" >&2
        exit 1
    }
    exit 0
fi
if [[ "$YIOPS_MODE" != "source" ]]; then
    echo "Unknown YiOps service mode: $YIOPS_MODE" >&2
    exit 1
fi

case "$YIOPS_ACTION" in
    start) source_start ;;
    run) source_run ;;
    stop) source_stop ;;
    restart) source_stop || true; source_start ;;
    status) source_status ;;
    logs) mkdir -p "$YIOPS_ROOT/logs"; touch "$YIOPS_LOG_FILE"; tail -f "$YIOPS_LOG_FILE" ;;
    *) echo "Usage: $0 {install|start|run|stop|restart|status|logs|mode}" >&2; exit 1 ;;
esac
