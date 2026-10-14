# AlphaAvatar MCP Plugin

MCP provides discovery and invocation across configured remote servers through AlphaAvatar's native capability system. It does not inject server tools through a LiveKit AgentSession.

## Architecture

```text
AvatarEngine -> Loop -> CapabilityRegistry -> MCPHost
                                           -> tool discovery / refresh / call
                                           -> configured remote MCP servers
```

The plugin presents an aggregate interface rather than automatically exposing every remote schema as a separate foreground tool. It validates tool arguments and supports concurrent remote calls where its operation contract allows them. This is an architecture choice, not a guarantee of reasoning quality or remote-service latency.

## Configuration

MCP is configured under `tools.mcp`; the old top-level `enable_mcp` and `mcp_servers` keys are not current Agent configuration.

```yaml
tools:
  mcp:
    plugin: default
    enabled: true
    init_config: {}

    vdb_config:
      collection_name: mcp
      embedding:
        provider: openai
        model: text-embedding-3-small

    servers:
      livekit-docs:
        url: https://docs.livekit.io/mcp/
        instruction: >
          Search the configured LiveKit documentation server.
```

This is a fragment, not a complete Loop/voice configuration. See [Examples](../../../examples/README.md). Remote server URLs, tool availability and credentials are deployment-specific.

Credentials can use the existing environment-placeholder mechanism, for example an `Authorization: "Bearer <GITHUB_PAT>"` header with GITHUB_PAT provided by the environment. Resolution happens during configuration construction; a configured missing placeholder can fail startup before a tool is called. Do not put actual tokens in version-controlled YAML.

## Operations

`op="tool_search"` accepts a query, optional `top_k` (1–50, default 8), and `server_keys` matching exact keys from `tools.mcp.servers`. Omitting server_keys searches configured servers. Categories `read`, `write` and `unknown` filter discovery using the remote readOnlyHint annotation; they do not grant execution approval.

`op="refresh_tools"` refreshes metadata without restarting the worker and can be restricted to server keys. It reports additions/removals/updates and retains a server's prior tools when refresh fails. Refresh only when metadata has changed; it is not required before every call.

`op="tool_call"` dispatches validated remote operations. `output_mode: raw` returns full results and echoed arguments; `compact` truncates each result to 2000 characters with a note and omits echoed arguments. Treat returned server content as external data, not application authorization.

## Authorization and side effects

Registration, discovery and remote readOnlyHint metadata do not approve a call. Foreground Loop enforces exact-capability policies and the injected authorizer. `tool_policies: {}` does not bypass its approval requirement, and the current LiveKit entrypoint supplies no approval UI.

The aggregate MCP capability may invoke both reads and writes. Do not mark the whole capability read-only because one configured server currently offers documentation search. Deployments must constrain/authorize the actual operation. Cancellation can leave external side effects with an unknown outcome; do not blindly retry a write.

Tool implementations return outcomes and do not receive a StatusEmitter or `monologue`. Loop owns canonical tool records and execution facts; Memory and Status consume their respective streams independently.

## Logging

The plugin redacts sensitive URL/header/token patterns in its logs, relevant HTTP/MCP logger output and model-facing server descriptions. Redaction is not permission to log arbitrary secrets, and it does not turn third-party logs into a guaranteed secure audit trail.

## Installation and startup

```bash
pip install alpha-avatar-plugins-mcp
```

With the Host and selected dependencies installed, launch from a complete configuration:

```bash
ENV_FILE=.env.dev alphaavatar dev examples/agent_configs/voice/pipeline_openai_tools_minimal.yaml
```

Use the current Host's `dev` / `start` entrypoints, not `alphaavatar serve`. Inference-backed tool retrieval and remote connections still require the selected dependencies, models and credentials. Native generation does not remove vendor/worker SDK dependencies elsewhere in the workspace.
