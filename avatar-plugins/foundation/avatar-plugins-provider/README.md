# AlphaAvatar Provider Plugin

Public model, prompt, tool-result, request, and stream contracts live in
`alphaavatar.agents.avatar.provider`. SDK construction, message conversion,
structured parsing, and usage normalization remain in this plugin.

## Shared ownership

Every `FoundationRuntime` owns one `ProviderService`, available as
`runtime.foundation.provider`. A service belongs to the current runtime, not to
a process-global registry. This does not introduce another ProviderRuntime.

Memory Conversation, Environment, Tool, and Persona Profiler borrow gateways from
that service. Each gateway retains its own immutable task-configuration snapshot,
business task names, trace metadata, and prompt. Equal complete model configuration
snapshots reuse one model wrapper and its SDK clients inside the same service.
Different configurations and different service instances remain isolated.

No message history or tool registry is stored in the service. The resource pool
is not a result cache. Environment credentials are read on client initialization;
credential or configuration changes require a new runtime rather than mutation of
an active gateway. Pool keys do not contain plaintext credentials.

## Construction and invocation

`backend` selects the installed implementation; `provider` selects its vendor or
endpoint family. Entry-point discovery still registers factories through
AvatarModulePlugin. Loading a factory is not a network request.

LangChain LLM construction is lazy, single-flight, and runs off the event loop.
The first caller's cancellation does not abandon the initialization task. Later
requests reuse the same initialized client, and schema-bound structured runnables
are cached by output schema class. There is no lock held across model requests.

All model invocations use async SDK paths. `timeout` bounds the remote structured
invocation, including SDK retries. Consumer-level deadlines still cover their
whole workflow. Unsupported media and invalid structured output remain errors.

Model initialization failures remain failed for that model binding. Recreate the
runtime after correcting initialization configuration; there is no implicit
credential refresh or hot replacement in this implementation.

## Client resources

OpenAI and OpenRouter receive explicitly owned sync and async HTTP transports.
The narrow Anthropic subclass bypasses LangChain's process-cached HTTP transports.
The Google client is detached from its wrapper and both its async and sync halves
are explicitly closed. Blocking construction and sync close operations run in
worker threads; model requests are not replaced with blocking SDK calls.

The LangChain integration versions are constrained to the existing repository
lock versions for this resource adapter. They are not upgraded by this change.
The Anthropic `_client_params`/cached-property integration and Google client
ownership must be rechecked when those integrations are upgraded.

External client handles cannot be supplied in task `extra` fields. Stateful
Anthropic container reuse is not supported by shared task models.

## Shutdown

Consumers complete their own finalization before Foundation closes. Provider
shutdown rejects new calls, cancels and awaits residual owned requests, waits for
in-progress client/schema initialization, closes every model, and finally drains
tracers. A failure in one close does not skip ordinary peer cleanup.

Concurrent close callers share one close task. Caller cancellation is propagated
after owned cleanup finishes. `LLMBase.aclose()` is now part of the contract;
a model owner must stop requests before invoking it.

## Tracing

Each trace-policy configuration has one service-owned writer with a bounded
queue (`trace.max_pending`, default 256). There is no synchronous fallback and no
untracked task per write. File work stays off the event loop. Cancelled requests
produce a cancelled terminal trace when they reached the tracing stage.

Tracing is best-effort diagnostics, not a lossless audit log. Queue saturation
drops new diagnostic writes and increments `dropped_writes`; warnings report the
loss. Shutdown waits for accepted writes. Write failures are counted, logged, and
reported by close after subsequent accepted jobs have been processed. Calls with
no `provider_dir` destination increment `skipped_writes` and do not create a writer.

## Remaining execution work

The existing isolated VDB workers still own their Embedding instances. No SDK
client is moved across process boundaries by the Foundation service. This batch
does not redesign worker Embedding lifecycle.

Streaming contracts remain defined, but the LangChain task backend does not yet
advertise StreamingLLMBase. Native streaming model/tool execution, final Assistant
output and TTS, and LiveKit Agents removal remain separate functional work.
Execution remains session-scoped; Episodes and Dream scheduling are unchanged.
