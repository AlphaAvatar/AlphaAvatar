# AlphaAvatar MCP Plugin

MCP provides discovery and invocation across configured remote servers through
AlphaAvatar's native capability system. Transport and ClientSession ownership use
the MCP Python client directly; no LiveKit AgentSession or Agents SDK MCP base class
is involved.

## Architecture

```text
AvatarEngine -> Loop -> CapabilityRegistry -> MCPHost
    -> shared inference client -> isolated MCP runner
    -> native MCP clients -> configured remote servers
```

The foreground facade never blocks on database calls or a thread future. The
existing serial inference runner owns synchronous embeddings and LanceDB work;
its separate owned event loop performs asynchronous MCP networking. This does
not make a single runner process handle independent inference requests in parallel.
Within one admitted tool batch, remote calls may run concurrently.

The plugin presents an aggregate capability rather than exposing every remote
schema as a separate foreground tool. Discovery annotations do not grant permission.

## Configuration

MCP is configured under `tools.mcp` in a complete Avatar configuration:

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
        transport: streamable_http
        client_session_timeout_seconds: 60.0
        close_timeout: 10.0
        max_in_flight: 32
        max_tools: 4096
        max_pages: 64
        instruction: >
          Search the configured LiveKit documentation server.
```

Server settings are strictly validated. `streamable_http` is the default;
select `transport: sse` explicitly for an SSE endpoint. There is no automatic
transport fallback, reconnect-and-replay, or hidden SDK compatibility path.
Remote endpoints require HTTPS; loopback HTTP is supported for local development.
Embedded URL credentials and fragments are rejected. Endpoints and returned tool
content remain deployment-specific external services.

Credentials can use the existing environment-placeholder mechanism, for example:

```yaml
headers:
  Authorization: "Bearer <GITHUB_PAT>"
```

Provide `GITHUB_PAT` through the environment, never as a committed token. The
configuration above is a fragment; see [complete examples](../../../examples/README.md).
Restart Host after changing configured servers, transport settings or credentials.

## Discovery and refresh

`op="tool_search"` accepts a query, `top_k` (1–50, default 8), optional exact
`server_keys`, and categories `read`, `write` or `unknown`. Categories use the
server's `readOnlyHint`; they do not authorize invocation.

Tool listing handles pagination with configured page/tool limits. Duplicate names,
repeated cursors and excessive results fail the listing instead of publishing a
partial catalog as complete. Tool identities remain `<server_key>.<tool_name>`.

`op="refresh_tools"` explicitly refreshes selected catalogs and reports added,
removed and updated identities. A failed listing preserves the previous catalog,
but old entries are not evidence that the disconnected service remains callable.
A later explicit refresh can open a new client only after the previous client was
cleanly released. Invocation itself never reconnects and retries a tool call.

LanceDB replacements are embedded before they are upserted. An embedding failure
must not delete existing entries. Stale rows are pruned only for servers whose full
catalog was listed successfully, not for servers that were temporarily unavailable.
The index is discovery data, not an execution log or authorization database.

## Calls, results and cancellation

`op="tool_call"` accepts between one and 64 named operations. Per-server
`max_in_flight` bounds admitted requests; excess requests fail without dispatch.
Each dispatched request owns its timeout and cleanup. A timeout or caller
cancellation is not proof that a remote write did not commit.

`output_mode: raw` preserves complete result content and echoed arguments.
`compact` omits echoed arguments and truncates individual result text to 2000
characters with a note. Structured MCP result content is preserved. A successful
empty result is represented as an empty list, not misclassified as a tool failure.
Server-reported errors remain errors. Peer successes are not discarded merely
because another operation in the same batch failed.

Only one task enters and exits each native MCP transport and ClientSession.
Shutdown rejects new work, permits admitted work to settle within its grace period,
then cancels remaining local requests and waits for their cleanup before releasing
the connection. The isolated runner closes its clients and joins its loop thread.
A close failure remains a failure; it does not imply successful remote rollback.

## Authorization and privacy

Registration, discovery and remote annotations do not approve a call. Foreground
Loop enforces exact-capability policies and its authorizer. `tool_policies: {}`
does not bypass approval, and the native Host does not supply an approval UI.
Do not mark the whole MCP capability read-only because one configured tool is read-only.

Tool implementations return outcomes; they receive neither StatusEmitter nor
`monologue`. Loop owns canonical tool records. Memory and Status consume their
respective streams independently. Returned server content is data, not permission
to change application policy.

Connection errors expose safe stage/type information rather than raw headers,
credentials or response bodies. Existing log redaction remains defense in depth,
not permission to log arbitrary secrets or proof that third-party logs are safe.

## Installation and startup

Install the workspace's Host, MCP, embedding and database dependencies together,
then use a complete configuration:

```bash
ENV_FILE=.env.dev alphaavatar dev examples/agent_configs/voice/pipeline_openai_tools_minimal.yaml
```

Use the Host's `dev` / `start` commands, not `alphaavatar serve`. Model and remote
service credentials are still required. Native transport/lifecycle implementation
does not substitute for an integration check against your configured MCP servers.
