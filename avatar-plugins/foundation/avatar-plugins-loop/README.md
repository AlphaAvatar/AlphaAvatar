# AlphaAvatar Loop Plugin

Loop implementations live here; public lifecycle and submission contracts live
in alphaavatar.agents.avatar.loop. Shared services are resolved from AvatarRuntime.
There is no LoopDependencies container or LoopService wrapper.

## Configuration and ownership

The current Host still uses its SDK response path. Omitting `loop` does not build
an unused native Loop. An explicit native Loop configuration must specify its
model; the Host does not infer one from the legacy `llm` configuration:

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

`loop: {}` is invalid because the realtime plugin requires `init_config.model`.
Configuring a Loop initializes it but does not switch the current response path.
The model identifier above is a placeholder, not an automatically selected model.

Host binds Context, Provider and Voice through FoundationRuntime before calling
LoopConfig.get_plugin(runtime=runtime). It then binds the resulting Loop exactly
once with FoundationRuntime.bind_loop().

```python
loop = runtime.foundation.loop
handle = await loop.submit(request, on_event=on_event, on_commit=on_commit, authorize=authorize)
result = await handle.wait()
```

Foundation owns the configured Loop. On runtime shutdown it closes Loop before
Context, then Provider and Voice; Output and Inference are closed afterwards.
An application may stop its Loop earlier; repeated close requests are idempotent.
A consumer must never close its borrowed Provider, Context or whole runtime.

## Execution

Loop creates its gateway through runtime.foundation.provider, obtains the single
ContextManager through runtime.foundation.context, and invokes tools through
runtime.capability_registry. Active runs belong to the runtime's Loop instance,
not to a process-global registry.

submit() validates and accepts a committed input and schedules owned preparation.
The execution calls ContextManager.prepare before its first model request.
submit() never waits for context readiness, model generation, tools or TTS.
Every later model request calls ContextManager.build with the captured prefix and
new canonical records only. Engine does not preassemble native Loop context.

Event, commit and authorization callbacks are optional per-submission hooks for
application delivery, persistence and approval. They are not service dependencies
or shared singleton state. Without an authorizer, only explicitly classified
read-only tools with approval_required=false may execute. No durable persistence
is claimed when no commit hook is provided; results remain in LoopResult.items.

ToolPolicy is plugin configuration, imported from alphaavatar.plugins.loop.config.
Tool classifications and verified reasoning profiles are configured on the Loop,
not in model arguments. Default profiles do not guess capabilities from model names.

The static query budget, tool definitions and selected reasoning profile remain
stable across model steps. Runtime counters enforce limits without changing the
captured context. Answer-only finalization retains tool schemas but disables new
calls. Accepted tool calls are settled even when cancellation occurs before batch
entry. Unknown write outcomes must not be retried blindly.

Advisory feedback failure does not terminate an otherwise healthy request. Visible
message delivery and history acknowledgement failures remain explicit errors.
Completed refusal messages and partial visible text survive interrupted execution.

Actual Status/Output/Memory/TTS routing and replacement of the remaining LiveKit
Agent execution path remain integration work. Loop imports no RTC, LiveKit Agents
or vendor SDK; backend implementations own their SDK imports.
