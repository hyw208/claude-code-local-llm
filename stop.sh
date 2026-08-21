#!/usr/bin/env bash

# Resolve symlinks so stop.sh works from anywhere or via symlinks
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
    DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"

echo "========================================================"
echo "  🛑 Stopping Local SGLang Proxy..."
echo "========================================================"

# 1. Kill any running proxy processes
if pkill -f "headroom.*proxy" 2>/dev/null || pkill -f "proxy\.py" 2>/dev/null; then
    echo "  ✔ Stopped running Headroom proxy process."
else
    echo "  ℹ No Headroom proxy process currently running."
fi

# 2. Clean up proxy log file if present
if [ -f "/tmp/proxy.log" ]; then
    rm -f /tmp/proxy.log
    echo "  ✔ Cleaned up /tmp/proxy.log"
fi

echo "========================================================"
echo "  All local proxy processes stopped."
echo "========================================================"

