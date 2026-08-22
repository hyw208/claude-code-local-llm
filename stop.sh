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
echo "  🛑 Stopping Local/Remote SGLang Proxy & Web Sessions..."
echo "========================================================"

# 1. Kill any running proxy processes
if pkill -f "headroom.*proxy" 2>/dev/null || pkill -f "proxy\.py" 2>/dev/null; then
    echo "  ✔ Stopped running Headroom proxy processes."
else
    echo "  ℹ No Headroom proxy processes currently running."
fi

# 2. Kill any running ttyd web terminal server
if pkill -u $USER ttyd 2>/dev/null || sudo pkill ttyd 2>/dev/null; then
    echo "  ✔ Stopped running ttyd web terminal server."
fi

# 3. Kill tmux claude session if active
if tmux kill-session -t claude 2>/dev/null; then
    echo "  ✔ Terminated active tmux 'claude' session."
fi

# 4. Clean up proxy log file if present
if [ -f "/tmp/proxy.log" ]; then
    rm -f /tmp/proxy.log
    echo "  ✔ Cleaned up /tmp/proxy.log"
fi

echo "========================================================"
echo "  All local & remote proxy processes stopped cleanly."
echo "========================================================"

