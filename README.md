# Local SGLang Integration for Claude Code with Headroom AI

A high-performance local integration for **Claude Code CLI** powered by the **Headroom AI** context optimization proxy (`headroom-ai`) and connected to a local/remote **SGLang** (or OpenAI-compatible) LLM server.

---
## Architecture Overview

```mermaid
graph LR
    CLI["Claude Code CLI"]
    HR["Headroom Proxy<br/>(port 8787)"]
    PY["Protocol Translation Bridge<br/>(proxy.py:4000)"]
    SGL["SGLang Inference Server<br/>(port 8000)"]

    CLI -->|"Anthropic Messages API"| HR
    HR -->|"Compressed Anthropic API"| PY
    PY -->|"OpenAI Chat Completions"| SGL
    SGL -->|"Reasoning & Content Chunks"| PY
    PY -->|"Anthropic SSE Events"| HR
    HR -->|"Optimized SSE Stream"| CLI
```

### Component Roles

1. **Claude Code CLI**: The local developer CLI agent executing tools, reading code, and managing git tasks.
2. **Headroom Optimization Proxy (`headroom proxy`)**: Runs natively on port `8787`. Compresses prompt context (AST code structures, verbose JSON, repeated tool outputs), tracks cross-session memory, and handles live traffic learning (`--learn`).
3. **Protocol Translation Bridge (`proxy.py`)**: Runs on port `4000`. Translates Anthropic messages and tool calls into OpenAI Chat Completions format, extracts both standard text content and reasoning content (`reasoning_content` thinking tokens), and streams Anthropic SSE events back to Headroom.
4. **SGLang Inference Server**: Runs `Qwen/Qwen3.6-27B-FP8` (or any OpenAI-compatible LLM endpoint) on port `8000`.

---

## Key Capabilities & Features

- **Headroom Context Compression**: Intelligently compresses large tool outputs, code blocks, and conversation history using structural AST parsing (`ast-grep`) and `SmartCrusher`, cutting input prompt sizes by **20%–60%+** to accelerate GPU prefill speed.
- **Live Traffic Learning (`--learn`)**: Automatically learns error-recovery patterns, environment facts, and user preferences from proxy traffic and persists them to agent memory (`MEMORY.md`).
- **Vector & SQLite Cross-Session Memory (`--memory`)**: Maintains a persistent local context database, injecting relevant past memories into prompt context.
- **Reasoning Content Support (`reasoning_content`)**: Full support for streaming reasoning tokens emitted by reasoning models (Qwen 3.6, DeepSeek R1).
- **Mobile & Thin-Client Access**: Full support for remote mobile access via browser web terminals (`ttyd`) or mobile SSH apps (Termius, Blink Shell) over Tailscale.
- **Complete Protocol Support**: Native support for Anthropic streaming SSE, tool calls (`tool_use` and `tool_result`), multimodal base64 images, and non-streaming requests.
- **Config Isolation**: Uses an isolated configuration directory (`/tmp/claude_local`), bypassing Anthropic OAuth browser logins while preserving your real `~/.claude.json` untouched.

## Quick Start (Single Command)

Start the wrapper script from anywhere. It automatically launches the Headroom proxy in the background, configures environment isolation, and launches Claude Code CLI:

```bash
./start.sh
```

### Specifying a Target Workspace Folder

You can run `start.sh` from any location or pass a target directory path:

```bash
# Option 1: Pass target directory path directly
/Users/dutch/Projects/claudecode/start.sh /path/to/my-project

# Option 2: Run start.sh from inside your target directory
cd /path/to/my-project
/Users/dutch/Projects/claudecode/start.sh

# Option 3: Use explicit -C / --cd flag
/Users/dutch/Projects/claudecode/start.sh -C /path/to/my-project
```

### Automated Execution Flag (`--dangerously-skip-permissions`)

```bash
/Users/dutch/Projects/claudecode/start.sh /path/to/my-project --dangerously-skip-permissions
```
* **Without flag (`./start.sh`)**: Claude Code prompts for manual `[y/n]` approval before every file edit or shell command.
* **With flag (`./start.sh --dangerously-skip-permissions`)**: Bypasses interactive prompts for automated execution.

---

## Usage Reference

### Command Syntax

```bash
./start.sh [DIRECTORY] [OPTIONS...]
./start.sh -C <directory> [OPTIONS...]
```

### Script Arguments & Options

| Option / Argument | Description |
| :--- | :--- |
| `DIRECTORY` | Path to target workspace directory for Claude Code to open in |
| `-C, --cd <dir>` | Set target workspace directory |
| `--dangerously-skip-permissions` | Bypass manual approval prompts for edits and shell commands |
| `-p, --print [prompt]` | Run in non-interactive print mode |
| `-c, --continue` | Continue the most recent conversation session |
| `-r, --resume [id]` | Resume a specific session |
| `-h, --help` | Show script usage summary and Claude Code options |

### Stopping the Proxy

To stop the background Headroom proxy process at any time:
```bash
/Users/dutch/Projects/claudecode/stop.sh
```

### Monitoring Logs & Savings

View live incoming prompts, Headroom compression stats, and model responses:
```bash
tail -f /tmp/proxy.log
```

---

## Headroom CLI Utilities

Because Headroom is installed in your `.venv`, you can use Headroom's native CLI suite to inspect savings and memory:

```bash
# View durable token savings & compression metrics over time
.venv/bin/headroom savings

# Inspect original vs. compressed content for recent proxy requests
.venv/bin/headroom inspect

# Open the Headroom savings dashboard in your browser
.venv/bin/headroom dashboard

# Check proxy routing and dependencies health
.venv/bin/headroom doctor

# Manage stored cross-session memories
.venv/bin/headroom memory list
```

---

## Remote Worker & Thin Client Architecture (Mobile & Mac)

You can run Claude Code, Headroom, and SGLang on a powerful **Worker PC** (heavy compute) and interact with it from your **Mac or Mobile phone** as a lightweight thin client.

### Remote Architecture Flow

```mermaid
graph TD
    subgraph ThinClient ["📱 Mobile Phone / 💻 Mac (Thin Client)"]
        CLIENT["Web Browser (ttyd:7681) / SSH Client (Termius / iTerm)"]
    end

    subgraph WorkerPC ["🖥️ Worker PC (Heavy Compute)"]
        SERVER["ttyd / tmux Session"]
        CLI["Claude Code CLI"]
        HR["Headroom Proxy (port 8787)"]
        PY["Protocol Translation Bridge (proxy.py:4000)"]
        CODE["Workspace Codebase"]
        SGL["SGLang Inference Server (port 8000)"]
    end

    CLIENT -->|"Tailscale / WebSockets / SSH"| SERVER
    SERVER <--> CLI
    CLI <--> CODE
    CLI --> HR --> PY --> SGL
```

### Step-by-Step Remote Setup & Run Guide

#### Step 1: Install Prerequisites on Worker PC
Ensure `ttyd` and `tmux` are installed on your Worker PC:
```bash
# macOS
brew install ttyd tmux

# Ubuntu / Debian
sudo apt update && sudo apt install -y ttyd tmux
```

#### Step 2: Set Up Workspace on Worker PC
Clone/copy this repo to your Worker PC and initialize the virtual environment:
```bash
cd /path/to/claudecode
python3 -m venv .venv
source .venv/bin/activate
pip install headroom-ai fastapi uvicorn httpx
```

#### Step 3: Launch Headroom Proxy & Session on Worker PC
Run `ttyd` wrapping a persistent `tmux` session so your session stays alive 24/7 even when disconnected:
```bash
# On Worker PC: Start web terminal server on port 7681
ttyd -p 7681 tmux new-session -A -s claude "./start.sh /path/to/my-project --dangerously-skip-permissions"
```

#### Step 4: Connect from Mac or Mobile Phone

##### 💻 Mac Access Options
* **Mac Browser (Web UI)**: Open `http://<worker-pc-ip>:7681` in Chrome or Safari.
* **Mac Terminal (SSH)**: Run `ssh user@<worker-pc-ip> -t "tmux a -t claude"` for native terminal keybindings.

##### 📱 Mobile Access Options (iOS & Android)
Your mobile phone acts as a lightweight remote control UI displaying real-time streaming tokens and accepting user prompts, while your Worker PC executes all code and SGLang GPU inference.

* **Option A: Web App (No SSH App Needed)**:
  Open `http://<worker-pc-ip>:7681` in Safari or Chrome on your phone. Tap **"Add to Home Screen"** to turn it into a full-screen mobile app!
* **Option B: Mobile SSH App**:
  Use [Termius](https://termius.com/) (iOS/Android) or [Blink Shell](https://blink.sh/) (iOS) over Tailscale:
  ```bash
  ssh user@<worker-pc-ip> -t "tmux a -t claude"
  ```

### Key Advantages
* 🔋 **Zero Mac/Mobile Battery Drain**: All file processing and LLM inference happens on the Worker PC.
* ⚡ **Ultra-Low Latency**: `proxy.py` and `SGLang` communicate over local `127.0.0.1` inside the Worker PC.
* 🔄 **100% Session Persistence**: Closing your laptop lid or phone browser tab never kills Claude Code—reconnect anytime to pick up right where it left off.

---

## Configuration & Isolation Details

### 1. Environment Configuration (`.env`)
Copy `.env.example` to `.env` to customize your target server and port settings:

```bash
cp .env.example .env
```

| Environment Variable | Description | Default |
| :--- | :--- | :--- |
| `SGLANG_URL` | Target SGLang / OpenAI-compatible endpoint URL | `http://127.0.0.1:8000/v1/chat/completions` |
| `MODEL_NAME` | Model ID string sent in completions request | `Qwen/Qwen3.6-27B-FP8` |
| `PROXY_PORT` | Local FastAPI translation proxy port | `4000` |
| `HEADROOM_PORT` | Headroom optimization proxy port | `8787` |

### 2. Dual Config Setup (`~/.claude.json`)
* **When running `./start.sh`**: Uses `CLAUDE_CONFIG_DIR="/tmp/claude_local"`. Claude Code completely **ignores** your home `~/.claude.json` and uses `/tmp/claude_local/.claude.json`.
* **When running standard `claude`**: Uses your real `~/.claude.json` so you can switch back to Anthropic cloud anytime.

---

## Switching Back to Anthropic Cloud

To return to standard Claude Code with Anthropic's cloud:
```bash
# Run standard claude in a clean terminal (uses your real ~/.claude.json)
claude
```
