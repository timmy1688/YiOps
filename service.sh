#!/usr/bin/env bash

set -Eeuo pipefail

YIOPS_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
YIOPS_PID_FILE="$YIOPS_ROOT/.runtime/yiops.pid"
YIOPS_MCP_PID_FILE="$YIOPS_ROOT/.runtime/yiops-mcp.pid"
YIOPS_MODE_FILE="$YIOPS_ROOT/.runtime/service-mode"
YIOPS_LOG_FILE="$YIOPS_ROOT/logs/yiops.log"
YIOPS_MCP_LOG_FILE="$YIOPS_ROOT/logs/yiops-mcp.log"
YIOPS_PYTHON="$YIOPS_ROOT/backend/.venv/bin/python"
YIOPS_ACTION="${1:-status}"

source_env_value() {
    local key="$1" default_value="$2" file candidate value=""
    for file in "$YIOPS_ROOT/backend/.env" "$YIOPS_ROOT/.env"; do
        if [[ -f "$file" ]]; then
            candidate="$(awk -F= -v wanted="$key" '$1 == wanted {sub(/^[^=]*=/, ""); print; exit}' "$file")"
            [[ -n "$candidate" ]] && value="$candidate"
        fi
    done
    printf '%s' "${value:-$default_value}"
}

validate_port() {
    local name="$1" value="$2"
    if [[ ! "$value" =~ ^[0-9]+$ ]] || ((10#$value < 1 || 10#$value > 65535)); then
        echo "$name must be an integer between 1 and 65535." >&2
        exit 1
    fi
}

YIOPS_PORT="${YIOPS_PORT:-$(source_env_value YIOPS_PORT 8100)}"
YIOPS_MCP_PORT="${YIOPS_MCP_PORT:-$(source_env_value YIOPS_MCP_PORT 8110)}"
validate_port YIOPS_PORT "$YIOPS_PORT"
validate_port YIOPS_MCP_PORT "$YIOPS_MCP_PORT"

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

mcp_running() {
    local pid stat
    pid="$(cat "$YIOPS_MCP_PID_FILE" 2>/dev/null || true)"
    if [[ ! "$pid" =~ ^[0-9]+$ ]] || ! kill -0 "$pid" 2>/dev/null; then
        pid="$(pgrep -f -- "$YIOPS_PYTHON -m app.mcp.server" | head -n 1 || true)"
    fi
    [[ "$pid" =~ ^[0-9]+$ ]] || return 1
    kill -0 "$pid" 2>/dev/null || return 1
    stat="$(ps -p "$pid" -o stat= 2>/dev/null || true)"
    if [[ -n "$stat" && "$stat" != *Z* ]]; then
        printf '%s\n' "$pid" > "$YIOPS_MCP_PID_FILE"
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

wait_for_mcp() {
    local attempt
    for attempt in {1..20}; do
        if ! mcp_running; then
            echo "YiOps MCP failed to start. See $YIOPS_MCP_LOG_FILE" >&2
            return 1
        fi
        if "$YIOPS_PYTHON" -c \
            "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${YIOPS_MCP_PORT}/health', timeout=1)" \
            >/dev/null 2>&1; then
            return 0
        fi
        sleep 0.5
    done
    echo "YiOps MCP started but did not become ready. See $YIOPS_MCP_LOG_FILE" >&2
    return 1
}

start_mcp() {
    cd "$YIOPS_ROOT/backend"
    nohup "$YIOPS_PYTHON" -m app.mcp.server > "$YIOPS_MCP_LOG_FILE" 2>&1 &
    echo "$!" > "$YIOPS_MCP_PID_FILE"
    wait_for_mcp
}

source_start() {
    if source_running && mcp_running; then
        echo "YiOps already running, PID $(cat "$YIOPS_PID_FILE")"
        return
    fi
    if source_running || mcp_running; then
        source_stop
    fi
    rm -f "$YIOPS_PID_FILE" "$YIOPS_MCP_PID_FILE"
    prepare_source
    if ! start_mcp; then
        source_stop || true
        return 1
    fi
    cd "$YIOPS_ROOT/backend"
    nohup "$YIOPS_PYTHON" -m uvicorn app.main:app \
        --host 0.0.0.0 --port "$YIOPS_PORT" --no-access-log \
        > "$YIOPS_LOG_FILE" 2>&1 &
    echo "$!" > "$YIOPS_PID_FILE"
    if ! wait_for_source; then
        source_stop || true
        return 1
    fi
    echo "YiOps started: http://127.0.0.1:${YIOPS_PORT}/"
}

source_run() {
    if source_running && mcp_running; then
        echo "YiOps already running, PID $(cat "$YIOPS_PID_FILE")"
        return
    fi
    if source_running || mcp_running; then
        source_stop
    fi
    rm -f "$YIOPS_PID_FILE" "$YIOPS_MCP_PID_FILE"
    prepare_source
    cd "$YIOPS_ROOT/backend"
    "$YIOPS_PYTHON" -m app.mcp.server >> "$YIOPS_MCP_LOG_FILE" 2>&1 &
    echo "$!" > "$YIOPS_MCP_PID_FILE"
    if ! wait_for_mcp; then
        source_stop || true
        return 1
    fi
    "$YIOPS_PYTHON" -m uvicorn app.main:app \
        --host 0.0.0.0 --port "$YIOPS_PORT" --no-access-log &
    echo "$!" > "$YIOPS_PID_FILE"
    trap 'kill "$(cat "$YIOPS_PID_FILE" 2>/dev/null)" "$(cat "$YIOPS_MCP_PID_FILE" 2>/dev/null)" 2>/dev/null || true' EXIT INT TERM
    wait "$(cat "$YIOPS_PID_FILE")"
}

source_stop() {
    if ! source_running && ! mcp_running; then
        rm -f "$YIOPS_PID_FILE" "$YIOPS_MCP_PID_FILE"
        echo "YiOps is not running."
        return
    fi
    local pid mcp_pid attempt
    pid="$(cat "$YIOPS_PID_FILE" 2>/dev/null || true)"
    mcp_pid="$(cat "$YIOPS_MCP_PID_FILE" 2>/dev/null || true)"
    [[ "$pid" =~ ^[0-9]+$ ]] && kill "$pid" 2>/dev/null || true
    [[ "$mcp_pid" =~ ^[0-9]+$ ]] && kill "$mcp_pid" 2>/dev/null || true
    for attempt in {1..20}; do
        if ! source_running && ! mcp_running; then
            rm -f "$YIOPS_PID_FILE" "$YIOPS_MCP_PID_FILE"
            echo "YiOps stopped."
            return
        fi
        sleep 0.5
    done
    echo "YiOps processes are still stopping." >&2
    return 1
}

source_status() {
    if source_running && mcp_running; then
        echo "YiOps running, API PID $(cat "$YIOPS_PID_FILE"):${YIOPS_PORT}, MCP PID $(cat "$YIOPS_MCP_PID_FILE"):${YIOPS_MCP_PORT} (source mode)"
    else
        echo "YiOps incomplete: API=$(source_running && echo running || echo stopped), MCP=$(mcp_running && echo running || echo stopped) (source mode)"
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
    logs) mkdir -p "$YIOPS_ROOT/logs"; touch "$YIOPS_LOG_FILE" "$YIOPS_MCP_LOG_FILE"; tail -f "$YIOPS_LOG_FILE" "$YIOPS_MCP_LOG_FILE" ;;
    *) echo "Usage: $0 {install|start|run|stop|restart|status|logs|mode}" >&2; exit 1 ;;
esac
