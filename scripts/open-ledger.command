#!/bin/bash

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LEDGER_URL="http://127.0.0.1:8766"
SERVICE="gui/$(id -u)/local.traffic-ledger"
SERVICE_PLIST="$HOME/Library/LaunchAgents/local.traffic-ledger.plist"

ready() {
    curl --noproxy '*' -fsS --max-time 2 "$LEDGER_URL/" >/dev/null 2>&1
}

finish() {
    echo
    read -r -p "按回车键关闭窗口..." || true
}

echo "流量账本"
echo

if ! ready; then
    echo "正在启动后台记录服务..."
    if launchctl print "$SERVICE" >/dev/null 2>&1; then
        launchctl kickstart "$SERVICE"
    elif [ -f "$SERVICE_PLIST" ]; then
        launchctl bootstrap "gui/$(id -u)" "$SERVICE_PLIST"
    else
        LEDGER_PYTHON="$PROJECT_DIR/.venv/bin/python"
        if [ ! -x "$LEDGER_PYTHON" ]; then
            LEDGER_PYTHON="$(command -v python3)"
        fi
        "$LEDGER_PYTHON" "$PROJECT_DIR/scripts/manage.py" install
    fi

    for attempt in {1..20}; do
        if ready; then
            break
        fi
        sleep 0.5
    done
fi

if ready; then
    open "$LEDGER_URL"
    echo "已打开：$LEDGER_URL"
    echo "关闭网页或本窗口后，后台仍会继续记录流量。"
else
    echo "账本启动失败，请查看日志："
    echo "$HOME/Library/Application Support/LocalTrafficLedger/error.log"
    finish
    exit 1
fi

finish
