# AlphaAvatar Deployment Guide

This guide describes how to deploy the AlphaAvatar Agent on a server and connect it to the Vercel-hosted AlphaAvatar Web Demo through LiveKit.

---

## 1. Deployment Architecture

AlphaAvatar uses a separated deployment architecture:

```text
User Browser
    │
    ▼
Vercel alphaavatar-web
    │
    ▼
LiveKit Cloud / LiveKit Server
    │
    ▼
AlphaAvatar Agent Server
    │
    ├── Memory
    ├── Persona
    ├── RAG
    ├── MCP
    └── DeepResearch
```

The Vercel frontend creates LiveKit sessions and provides the browser UI.
The AlphaAvatar Agent runs as a long-running worker process on your server.

---

## 2. Repository Setup

Clone the repository:

```bash
git clone --recurse-submodules https://github.com/AlphaAvatar/AlphaAvatar.git
cd AlphaAvatar
```

Create Python environment:

```bash
uv venv .venv --python 3.11
source .venv/bin/activate
uv sync --all-packages
```

---

## 3. Environment File

AlphaAvatar uses `.env.demo` for demo deployment.

Create it from the template:

```bash
cp .env.template .env.demo
```

Edit:

```bash
nano .env.demo
```

Required variables usually include:

```env
# LiveKit
LIVEKIT_URL=
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=

# OpenAI
OPENAI_API_KEY=
OPENAI_BASE_URL=

# AlphaAvatar local workspace
AVATAR_WORK_DIR=/var/lib/alphaavatar

# GitHub MCP
GITHUB_PAT=
```

Recommended persistent workspace:

```bash
sudo mkdir -p /var/lib/alphaavatar
sudo chown -R $USER:$USER /var/lib/alphaavatar
```

The `AVATAR_WORK_DIR` stores user-scoped data such as:

```text
users/
memory markdown backups
persona runtime state
RAG indexes
RAG artifacts
LanceDB local data
tool artifacts
```

---

## 4. Demo Agent Config

The demo agent config is located at:

```bash
AlphaAvatar/examples/agent_configs/roles/demo.yaml
```

Default startup command:

```bash
ENV_FILE=.env.demo alphaavatar start examples/agent_configs/roles/demo.yaml
```

Make sure `avatar_name` in `demo.yaml` matches the frontend environment variable:

```env
NEXT_PUBLIC_AVATAR_NAME=AlphaAvatar
```

If these names do not match, the Web Demo may connect to LiveKit but keep waiting for the agent.

---

## 5. One-Command Start

Use the bundled startup script:

```bash
bash scripts/start_alphaavatar_demo.sh
```

First-time startup with required file download:

```bash
DOWNLOAD_FILES=true bash scripts/start_alphaavatar_demo.sh
```

Override config file:

```bash
ENV_FILE=.env.demo \
CONFIG_FILE=examples/agent_configs/roles/demo.yaml \
bash scripts/start_alphaavatar_demo.sh
```

Recommended script defaults:

```bash
ENV_FILE=.env.demo
CONFIG_FILE=examples/agent_configs/roles/demo.yaml
START_MODE=start
```

---

## 6. systemd Deployment

Create log directory:

```bash
sudo mkdir -p /var/log/alphaavatar
sudo chown -R $USER:$USER /var/log/alphaavatar
```

Create service:

```bash
sudo vi /etc/systemd/system/alphaavatar-demo.service
# or
sudo nano /etc/systemd/system/alphaavatar-demo.service
```

Example:

```ini
[Unit]
Description=AlphaAvatar Demo LiveKit Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=<your-linux-user>
WorkingDirectory=/path/to/AlphaAvatar

Environment=PATH=/home/<your-linux-user>/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=ENV_FILE=.env.demo
Environment=CONFIG_FILE=examples/agent_configs/roles/demo.yaml
Environment=START_MODE=start
Environment=PYTHONUNBUFFERED=1
Environment=DOWNLOAD_FILES=false

ExecStart=/path/to/AlphaAvatar/scripts/start_alphaavatar_demo.sh

Restart=always
RestartSec=5

StandardOutput=append:/var/log/alphaavatar/demo-agent.log
StandardError=append:/var/log/alphaavatar/demo-agent.err.log

[Install]
WantedBy=multi-user.target
```

> Replace `<your-linux-user>` and `/path/to/AlphaAvatar` with your actual server username and project path if needed.

Make sure the startup script is executable:

```bash
chmod +x /path/to/AlphaAvatar/scripts/start_alphaavatar_demo.sh
```

Reload and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable alphaavatar-demo
sudo systemctl start alphaavatar-demo
```

Check status:

```bash
sudo systemctl status alphaavatar-demo
```

View logs:

```bash
journalctl -u alphaavatar-demo -f
```

Or:

```bash
tail -f /var/log/alphaavatar/demo-agent.log
tail -f /var/log/alphaavatar/demo-agent.err.log
```

Or:

```bash
tail -f /var/log/alphaavatar/demo-agent.log | jq -r '
  if .message then
    "\(.timestamp // "") [\(.level // "INFO")] \(.name // "") room=\(.room_id // "-") job=\(.job_id // "-") \(.message)"
  else
    .
  end
'
```

---

## 7. Vercel Frontend Environment

The Vercel frontend should use the same LiveKit project as the AlphaAvatar Agent.

Required Vercel environment variables:

```env
NEXT_PUBLIC_AVATAR_NAME=AlphaAvatar

LIVEKIT_URL=
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=
```

The following variables must match the server `.env.demo`:

```env
LIVEKIT_URL
LIVEKIT_API_KEY
LIVEKIT_API_SECRET
```

The following value must match `avatar_name` in `examples/agent_configs/roles/demo.yaml`:

```env
NEXT_PUBLIC_AVATAR_NAME=AlphaAvatar
```

---

## 8. Update Deployment

Pull latest code:

```bash
cd /home/ecs-user/AlphaAvatar
git pull
git submodule update --init --recursive
```

Sync dependencies:

```bash
source .venv/bin/activate
uv sync --all-packages
```

Restart service:

```bash
sudo systemctl restart alphaavatar-demo
```

Check logs:

```bash
journalctl -u alphaavatar-demo -f
```

---

## 9. Recommended Production Layout

```text
/home/ecs-user/AlphaAvatar
  ├── .env.demo
  ├── .venv/
  ├── examples/
  │   └── agent_configs/
  │       └── roles/
  │           └── demo.yaml
  ├── scripts/
  │   └── start_alphaavatar_demo.sh
  └── DEPLOY.md

/var/lib/alphaavatar
  ├── users/
  ├── vdb/
  └── artifacts/

/var/log/alphaavatar
  ├── demo-agent.log
  └── demo-agent.err.log
```

---

## 10. Useful Commands

Reload (service file changed):
```bash
sudo systemctl daemon-reload
```

Start:

```bash
sudo systemctl start alphaavatar-demo
```

Stop:

```bash
sudo systemctl stop alphaavatar-demo
```

Restart:

```bash
sudo systemctl restart alphaavatar-demo
```

Status:

```bash
sudo systemctl status alphaavatar-demo
```

Logs:

```bash
journalctl -u alphaavatar-demo -f
```

Disable auto-start:

```bash
sudo systemctl disable alphaavatar-demo
```

Clear log:

```bash
sudo sh -c '> /var/log/alphaavatar/demo-agent.log'
sudo sh -c '> /var/log/alphaavatar/demo-agent.err.log'
```

---

## FAQ

