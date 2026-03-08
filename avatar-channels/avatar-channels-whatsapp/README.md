# AlphaAvatar WhatsApp Channel

> WhatsApp channel integration module for **AlphaAvatar**
> Built with a **Driver Abstraction Architecture** for future API replacement.

---

# 🏗 Architecture

This module is divided into two independent layers:

```
WhatsApp Backend API
        │
        ▼
Driver Layer (replaceable)
        │  WebSocket
        ▼
Bridge Core (Python)
        │  LiveKit DataChannel
        ▼
AlphaAvatar Agent
```

## Layer Responsibilities

### 🔌 Driver Layer (Replaceable)

Located at:

```
drivers/
  baileys/
```

Responsible for:

* Connecting to WhatsApp backend
* Receiving inbound messages
* Sending outbound messages
* Converting raw events → unified schema
* Communicating with Bridge Core via WebSocket

This layer can be replaced without modifying the Agent or Bridge Core.

---

### 🧠 Bridge Core (Stable Layer)

Located at:

```
src/alphaavatar/channels/whatsapp/
```

Responsible for:

* WebSocket hub
* Message deduplication
* Session mapping
* LiveKit publish/subscribe
* Routing `whatsapp.in` / `whatsapp.out`

This layer **does not depend on a specific WhatsApp API provider**.

---

# 📦 Current Driver: Baileys (WhatsApp Web)

> Development & local testing only.

### When to Use

* Development
* Internal testing
* Personal bot

### Not Recommended For

* Production
* Public bots
* High-volume systems

---

# 🚀 Quick Start

## 1️⃣ Start Python Bridge Core

From repo root:

```bash
uv run alphaavatar-whatsapp-core
```

Expected output:

```
WhatsApp Core WS listening on ws://127.0.0.1:18789
```

Verify port:

```bash
ss -lntp | grep 18789
```

---

## 2️⃣ Start Baileys Driver

```bash
cd drivers/baileys
pnpm install
pnpm dev
```

Expected logs:

```
Connected to Core WS
```

Then a QR code will appear.

---

## 3️⃣ Link WhatsApp

On your phone:

1. WhatsApp → Settings
2. Linked Devices
3. Link a device
4. Scan terminal QR

Successful login:

```
WhatsApp connection opened
```

---

## 4️⃣ Test Message

Send a message to the linked account.

You should receive:

```
[echo] your message
```

If echo works, the channel pipeline is healthy.

---

# 🔄 Unified Event Schema

All drivers must emit events in the following format.

## Inbound Event

```json
{
  "v": 1,
  "channel": "whatsapp",
  "direction": "in",
  "from": "+9715xxxxxxx",
  "chat_id": "wa:xxx",
  "message_id": "xxx",
  "ts": 1700000000,
  "type": "text",
  "text": "hello",
  "meta": { "driver": "baileys" }
}
```

## Outbound Event

```json
{
  "v": 1,
  "channel": "whatsapp",
  "direction": "out",
  "to": "+9715xxxxxxx",
  "chat_id": "wa:xxx",
  "text": "hi!"
}
```

---

# 🔌 Driver Abstraction Model

Future drivers should implement:

* Inbound handler → send to Bridge Core
* Outbound handler → send via API
* Reconnect logic
* Auth lifecycle

Recommended structure:

```
drivers/
  baileys/
  meta/
  twilio/
```

Only the driver directory changes when switching backend API.

---

# 🔁 Switching to Official APIs

For production usage, replace Baileys with:

## Meta Cloud API

* Webhook-based inbound
* HTTPS outbound
* Business account required

## Twilio WhatsApp API

* Twilio webhook
* Twilio REST outbound

### What Does NOT Change

* Python Bridge Core
* LiveKit topics
* Agent routing logic
* Memory / RAG / MCP plugins

Only driver implementation changes.

---

# 🧠 LiveKit Integration

Bridge Core publishes:

* `whatsapp.in`
* `whatsapp.out`

Agent subscribes to `whatsapp.in`
Agent replies to `whatsapp.out`

This decouples channel transport from AI logic.

---

# 🛠 Production Hardening Checklist

When moving beyond development:

* Persistent deduplication (Redis / DB)
* Per-user message queue
* Rate limiting
* Allowlist / pairing
* Monitoring & health checks
* Containerization
* Replace Baileys with official API

---

# 📁 Project Structure

```
avatar-channels/
  avatar-channels-whatsapp/
    drivers/
      baileys/
        src/
    src/
      alphaavatar/channels/whatsapp/
    pyproject.toml
    README.md
```

---

# 📌 Design Philosophy

This module is designed with:

* Clean separation of concerns
* Replaceable transport layer
* Stable AI core
* Production upgrade path

It ensures that WhatsApp API provider changes **do not cascade into AlphaAvatar core logic**.

---

# 🗺 Roadmap

* [ ] LiveKit streaming integration
* [ ] Meta Cloud API driver
* [ ] Twilio driver
* [ ] Voice note support (ASR)
* [ ] Media support
* [ ] Multi-driver runtime selection
