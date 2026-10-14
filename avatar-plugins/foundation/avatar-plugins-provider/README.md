# AlphaAvatar Provider Plugin

Public model, prompt, tool-result, request and stream contracts live in `alphaavatar.agents.avatar.provider`. SDK construction, message conversion, structured parsing and usage normalization remain in this plugin.

## Shared ownership

Every FoundationRuntime owns one ProviderService, exposed as `runtime.foundation.provider`. It belongs to the current runtime, not a process-global registry, and is not another ProviderRuntime.

Memory Conversation, Environment, Tool and Persona Profiler borrow gateways from the service. Gateways retain immutable task snapshots, business task names, trace policy and prompts. Complete equal model configurations can reuse a binding inside one service; different services/configurations stay isolated.

Provider stores neither conversation history nor tool authorization. The resource pool is not a result cache. Credentials are read during client initialization; changing them requires a new runtime instead of mutation of an active gateway. Pool keys do not contain plaintext credentials.

## Backend selection

`backend` selects an installed implementation; `provider` selects its vendor/endpoint family. Factory discovery uses AvatarModulePlugin and does not itself make a model request.

| Backend | Current role |
| --- | --- |
| `openai` | Native Responses streaming used by the foreground realtime Loop. |
| `langchain` | Structured-task model bindings used by plugin-owned extraction gateways. |

Streaming contracts being public does not make every backend stream-capable. The current LangChain task backend does not advertise StreamingLLMBase. Loop initialization checks the selected model binding; use `backend: openai` explicitly for the native main model.

```yaml
loop:
  plugin: realtime
  init_config:
    model:
      backend: openai
      provider: openai
      model: YOUR_MODEL_ID
      temperature: null
```

Memory and Persona keep their own processor-level provider settings. Their structured tasks need not be converted to the foreground backend merely to share client ownership.

## Construction and invocation

LangChain LLM construction is lazy, single-flight and off the event loop. Cancelling the first waiter does not abandon initialization. Subsequent calls reuse the initialized client and schema-bound structured runnables; a lock is not held over remote requests.

Model invocations use asynchronous SDK paths. The configured structured-invocation timeout includes retries, while consumer deadlines bound whole workflows. Unsupported media and invalid structured output remain explicit errors. Initialization failure remains failed for that binding; there is no implicit credential refresh.

## Client resources

OpenAI/OpenRouter LangChain bindings receive owned sync and async HTTP transports. The Anthropic adapter avoids process-cached HTTP transports, and the Google wrapper's async/sync clients are explicitly closed. Blocking construction and synchronous close operations run in worker threads, not on the realtime loop.

The LangChain resource adapter follows the repository's constrained integration versions. Recheck Anthropic cached-client and Google ownership details when upgrading dependencies. External client handles in task `extra` and stateful Anthropic container reuse are not supported by shared task bindings.

## Shutdown

Consumers finish their finalization before Foundation releases Provider. Shutdown rejects new calls, settles residual owned requests and initialization, closes bindings, and drains tracers. An ordinary peer-close failure does not skip the remaining cleanup.

Concurrent callers share a close task; cancellation propagates after owned cleanup. LLMBase.aclose is part of the contract, and owners must stop producers before closing their model resources.

## Tracing

Each trace policy has a service-owned bounded writer queue (`max_pending`, default 256). There is no synchronous fallback or untracked per-write task. File work stays off the event loop. Cancellation produces a terminal trace when it reaches the tracing stage.

Tracing is best-effort diagnostics, not a lossless audit log. Saturation increments dropped-write counters, failures are logged/reported, and shutdown waits for accepted writes. Missing `provider_dir` destinations are skipped rather than creating a writer.

## Current boundary

Native Engine/Loop generation, typed Output publication and Router/RTC delivery are implemented. Obsolete SDK model/tool/record bridges are removed. Voice owns native OpenAI and Voice.ai HTTP/PCM synthesis; it does not borrow ProviderService LLM bindings. SDK worker hosting and SDK-dependent Character integrations remain elsewhere in the workspace.

VDB worker processes still own their Embedding instances; no SDK client is passed across process boundaries. Execution remains Host-scoped, without new persistent recovery or Dream scheduling.
