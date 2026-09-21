#!/bin/bash
set -e

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV_PYTHON="$PROJECT_ROOT/venv/bin/python"

FRONTEND_PORT=58001
BACKEND_PORT=58002

start() {
    echo "=== 启动 chunk Web 服务 ==="

    if fuser $FRONTEND_PORT/tcp >/dev/null 2>&1 || fuser $BACKEND_PORT/tcp >/dev/null 2>&1; then
        echo "服务已在运行中"
        exit 1
    fi

    cd "$PROJECT_ROOT"
    export PATH="$PROJECT_ROOT/venv/bin:$PATH"

    nohup "$VENV_PYTHON" web/app.py >> /tmp/chunk_app.log 2>&1 &
    echo "后端已启动 (PID $!)"

    nohup "$VENV_PYTHON" web/frontend.py >> /tmp/chunk_frontend.log 2>&1 &
    echo "前端已启动 (PID $!)"

    sleep 2
    if curl -sf http://localhost:$BACKEND_PORT/api/health >/dev/null 2>&1; then
        echo "后端 :$BACKEND_PORT - 正常"
    else
        echo "后端 :$BACKEND_PORT - 启动失败"
        exit 1
    fi
    if curl -sf http://localhost:$FRONTEND_PORT/api/health >/dev/null 2>&1; then
        echo "前端 :$FRONTEND_PORT - 正常"
    else
        echo "前端 :$FRONTEND_PORT - 启动失败"
        exit 1
    fi
    echo "=== 启动完成 ==="
}

stop() {
    echo "=== 停止 chunk Web 服务 ==="
    fuser -k $FRONTEND_PORT/tcp 2>/dev/null || true
    fuser -k $BACKEND_PORT/tcp 2>/dev/null || true
    echo "=== 已停止 ==="
}

restart() {
    stop
    sleep 1
    start
}

status() {
    echo "=== chunk Web 服务状态 ==="
    if fuser $BACKEND_PORT/tcp >/dev/null 2>&1; then
        echo "后端 :$BACKEND_PORT - PID $(fuser $BACKEND_PORT/tcp 2>/dev/null)"
    else
        echo "后端 :$BACKEND_PORT - 未运行"
    fi
    if fuser $FRONTEND_PORT/tcp >/dev/null 2>&1; then
        echo "前端 :$FRONTEND_PORT - PID $(fuser $FRONTEND_PORT/tcp 2>/dev/null)"
    else
        echo "前端 :$FRONTEND_PORT - 未运行"
    fi
}

case "${1:-}" in
    start)   start ;;
    stop)    stop ;;
    restart) restart ;;
    status)  status ;;
    *)
        echo "用法: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
