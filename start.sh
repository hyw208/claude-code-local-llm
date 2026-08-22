#!/usr/bin/env bash
set -e

# Path where start.sh and proxy.py live (resolves symlinks if invoked via symlink/PATH)
SOURCE="${BASH_SOURCE[0]}"
while [ -L "$SOURCE" ]; do
    DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
    SOURCE="$(readlink "$SOURCE")"
    [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"

# Ensure common Node/npm global bin paths are included in PATH for Headroom/Claude Code
export PATH="$PATH:$HOME/.npm-global/bin:$HOME/.nvm/versions/node/$(node -v 2>/dev/null || true)/bin:/usr/local/bin:/opt/homebrew/bin:$HOME/.local/bin"

WORK_DIR="$PWD"
CLAUDE_ARGS=()
SHOW_HELP=false

# Parse arguments to extract target directory and claude flags
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            SHOW_HELP=true
            shift
            ;;
        -C|--cd)
            if [ -n "$2" ] && [ -d "$2" ]; then
                WORK_DIR="$(cd "$2" && pwd)"
                shift 2
            else
                echo "Error: Directory '$2' does not exist." >&2
                exit 1
            fi
            ;;
        *)
            if [ -d "$1" ]; then
                WORK_DIR="$(cd "$1" && pwd)"
                shift
            else
                CLAUDE_ARGS+=("$1")
                shift
            fi
            ;;
    esac
done

if [ "$SHOW_HELP" = true ]; then
    echo "========================================================"
    echo "  🚀 Local SGLang Proxy Wrapper Script Usage"
    echo "========================================================"
    echo "Usage:"
    echo "  start.sh [DIRECTORY] [CLAUDE_FLAGS...]"
    echo "  start.sh -C | --cd <directory> [CLAUDE_FLAGS...]"
    echo ""
    echo "Directory Parameters:"
    echo "  DIRECTORY           Target workspace directory path (optional)."
    echo "  -C, --cd <dir>      Set working workspace directory for Claude Code."
    echo ""
    echo "Common Claude Code Flags:"
    echo "  --dangerously-skip-permissions   Bypass manual approval prompts."
    echo "  -p, --print                      Print response and exit."
    echo "  -c, --continue                   Continue most recent conversation."
    echo "  -r, --resume [id]                Resume conversation session."
    echo "========================================================"
    echo ""
    exit 0
fi

# 1. Load environment configuration (.env) if present
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

PROXY_PORT="${PROXY_PORT:-4000}"
HEADROOM_PORT="${HEADROOM_PORT:-8787}"
export SGLANG_URL="${SGLANG_URL:-http://127.0.0.1:8000/v1/chat/completions}"

# 2. Activate Virtual Environment if available
if [ -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
    source "$SCRIPT_DIR/.venv/bin/activate"
fi

# 3. Setup isolated Claude config dir to bypass OAuth & browser login
mkdir -p /tmp/claude_local
echo '{"hasCompletedOnboarding":true,"lastOnboardingVersion":"2.0.42","primaryApiKey":"dummy-key"}' > /tmp/claude_local/.claude.json

# 4. Kill any old proxy instance running on target port
pkill -f "headroom.*proxy" 2>/dev/null || true
pkill -f "proxy\.py" 2>/dev/null || true

# 5. Start Local Protocol Translation Bridge (proxy.py) in background
python "$SCRIPT_DIR/proxy.py" > /tmp/proxy.log 2>&1 &
PROXY_PID=$!

# Clean up background translator proxy when Claude Code exits
cleanup() {
    kill $PROXY_PID 2>/dev/null || true
    pkill -f "proxy\.py" 2>/dev/null || true
    pkill -f "headroom.*proxy" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

sleep 1

# 6. Export environment variables for isolated login bypass and Headroom routing
export CLAUDE_CONFIG_DIR="/tmp/claude_local"
export ANTHROPIC_API_KEY="dummy-key"
export ANTHROPIC_TARGET_API_URL="http://127.0.0.1:${PROXY_PORT}"

echo "========================================================"
echo "  🚀 Headroom Wrapped Claude Code Started"
echo "  📄 Translation Proxy Logs: /tmp/proxy.log"
echo "  📂 Workspace: $WORK_DIR"
echo "  🤖 Launching headroom wrap claude..."
echo "========================================================"

# 6. Launch Claude Code through Headroom's native wrapper (headroom wrap claude)
cd "$WORK_DIR"
if [ ${#CLAUDE_ARGS[@]} -gt 0 ]; then
    "$SCRIPT_DIR/.venv/bin/headroom" wrap claude \
        --learn \
        --memory \
        -- "${CLAUDE_ARGS[@]}"
else
    "$SCRIPT_DIR/.venv/bin/headroom" wrap claude \
        --learn \
        --memory
fi

