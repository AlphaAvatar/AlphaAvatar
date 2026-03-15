# MCP Plugin for AlphaAvatar

A high-performance **Model Context Protocol (MCP) orchestration layer** for **AlphaAvatar**.

This plugin provides a **unified, parallel, and latency-optimized interface** for discovering and invoking tools exposed by one or more MCP servers — without relying on LiveKit’s native MCP tool injection chain.

> We intentionally disable LiveKit’s native “inject each MCP tool into Agent as separate tool” mechanism.
>
> Why?
>
> * Too many tools degrade Agent reasoning performance.
> * Serial tool calls increase latency.
> * Tool explosion harms LLM decision quality.
>
> Instead, we provide a **single unified MCP interface** that:
>
> * Supports tool discovery
> * Enables parallel execution
> * Coordinates multi-server workflows
> * Improves overall Agent tool-call performance

---

# Overview

The MCP Plugin acts as a **Tool Orchestrator Middleware** between AlphaAvatar Agents and external MCP servers.

It enables:

* 🔍 Tool discovery across heterogeneous MCP servers
* ⚡ Parallel tool execution (concurrent dispatch)
* 🧠 Workflow coordination across multiple servers
* 🔗 Unified abstraction for diverse capabilities (RAG, search, automation, data APIs, etc.)

Unlike traditional tool injection approaches, this design:

* Prevents exponential tool growth inside the Agent
* Reduces reasoning noise
* Avoids serial execution bottlenecks
* Improves scalability for multi-server MCP deployments

---

# Core Architecture

```text
AlphaAvatar Agent
        │
        ▼
    MCPHost (Unified Tool)
        │
        ├── search_tools()
        └── call_tools()
                │
                ├── MCP Server A
                ├── MCP Server B
                └── MCP Server C
```

The Agent only sees **one tool: `MCP`**.

Internally, MCPHost:

1. Discovers relevant tools
2. Validates schemas
3. Dispatches calls in parallel
4. Aggregates structured responses

---

# Performance Design Philosophy

## ❌ What We Avoid

* Injecting hundreds of tools into the Agent
* Serial tool invocation chains
* Tool schema explosion
* Repeated LLM tool selection loops

## ✅ What We Enable

* Single unified MCP interface
* Parallel tool dispatch
* Multi-server orchestration
* Scalable architecture

---

# Installation

```bash
pip install alpha-avatar-plugins-mcp
```

---

# Usage

## Step 1️⃣ Enable MCP in Configuration

Enable MCP and register remote MCP servers inside your `yaml` configuration file.

```yaml
enable_mcp: true

mcp_servers:
  livekit-docs:
    url: "https://docs.livekit.io/mcp"
    instruction: >
      LiveKit Docs MCP Server provides unified access to the LiveKit ecosystem,
      allowing you to search documentation, explore GitHub code across livekit
      and livekit-examples repositories, retrieve package changelogs, and browse
      Python Agents SDK examples—all in one place.

  github-copilot:
    url: "https://api.githubcopilot.com/mcp/"
    headers:
      Authorization: "Bearer <GITHUB_PAT>"
    instruction: >
      The GitHub MCP server (via GitHub Copilot) enables AI agents to interact
      with repositories, issues, pull requests, and code through a standardized
      MCP interface.
```

---

### 🔐 Environment Variables

Sensitive credentials such as `<GITHUB_PAT>` should be injected via environment variables:

```bash
export GITHUB_PAT=your_personal_access_token
```

At runtime:

* The system automatically resolves `<GITHUB_PAT>`
* Injects it into the request headers
* Keeps secrets out of version-controlled config files

---

## Step 2️⃣ Start AlphaAvatar

Once MCP is enabled and servers are configured:

```bash
alphaavatar serve <yarm-file-path>
```

During startup:

1. MCPHost initializes
2. All configured MCP servers are connected
3. Server metadata is injected into MCP tool description
4. MCP becomes available as a unified tool inside the Agent
