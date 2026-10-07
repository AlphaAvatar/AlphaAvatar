# AlphaAvatar Loop Plugin

Loop implementations live here; public lifecycle and submission contracts live
in alphaavatar.agents.avatar.loop. Shared services are resolved from AvatarRuntime.
There is no LoopDependencies container.

```python
loop = runtime.foundation.loop.create(config=loop_config, runtime=runtime)
handle = await loop.submit(request, on_event=on_event, on_commit=on_commit, authorize=authorize)
result = await handle.wait()
await loop.aclose()
```

Loop creates its gateway through runtime.foundation.provider, obtains the single
ContextManager through runtime.foundation.context, and invokes tools through
runtime.capability_registry. Neither the Loop factory nor Foundation owns a global
current Turn; callers own and close the returned Loop instance.

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

Tool classifications and verified model reasoning profiles are configured on the
Loop implementation (tool_policies / supported_reasoning_efforts), not in model
arguments. Default profiles do not guess capabilities from model names.

The static query budget, tool definitions and selected reasoning profile remain
stable across model steps. Runtime counters enforce limits without changing the
captured context. Answer-only finalization retains tool schemas but disables new
calls. Accepted tool calls are settled even when cancellation occurs before batch
entry. Unknown write outcomes must not be retried blindly.

Advisory feedback failure does not terminate an otherwise healthy request. Visible
message delivery and history acknowledgement failures remain explicit errors.
Completed refusal messages and partial visible text survive interrupted execution.

Actual Status/Output/Memory/TTS routing and the replacement of the remaining
LiveKit Agent execution path are the following integration work. The Loop
package itself imports no RTC, LiveKit Agents or vendor SDK; backend implementations
own their SDK imports.
