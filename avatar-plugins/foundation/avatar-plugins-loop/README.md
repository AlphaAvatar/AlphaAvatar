# AlphaAvatar Loop Plugin

Loop is a required Foundation component. `FoundationRuntime` receives a real Loop
instance; it does not accept `None`, an optional Loop factory, or a silent fallback.

## Construction and initialization

Host constructs Context, awaits Voice, and constructs the configured Loop using
AvatarRuntime. The Loop constructor stores configuration and runtime references;
it does not read the Foundation that has not yet been attached.

Host then constructs Foundation with Context, Loop, Provider and Voice, binds it
to AvatarRuntime, and awaits `loop.initialize()`. Initialization obtains the shared
Provider gateway and validates native streaming support. It does not issue model
requests, capture Context, or start an execution. Repeated initialization succeeds
without creating another gateway. Initialization after closure is rejected.

Host returns only after `loop.ready` is true. Engine also checks readiness before
constructing processors and before starting them. `submit()` rejects uninitialized
or closed instances rather than selecting another execution path.

Configuration is explicit:

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

Use the model ID available in your deployment. Missing or null top-level Loop
configuration is a validation error. Model configuration is never inferred from
the temporary SDK `llm` configuration.

## Submission and ownership

```python
# Host has already initialized the required component.
loop = runtime.foundation.loop
handle = await loop.submit(request, on_event=on_event, on_commit=on_commit, authorize=authorize)
result = await handle.wait()
```

Loop resolves Context and Provider through AvatarRuntime and tools through the
existing capability registry. There is no LoopDependencies container. Each
submission owns its preparation, execution state, tool records, feedback and
cancellation. Context preparation runs in the owned execution task, not in Engine.

State and static loop_budget are captured once through synthetic runtime tool
context. Tool schemas and the selected reasoning profile stay stable across model
steps. No middle developer policy messages or per-step State rewrites are added.

Engine stops Loop before flushing history and stopping Memory/Persona consumers.
Foundation provides the idempotent final close: Loop, Context, Provider/Voice.
AvatarRuntime closes Output and Inference afterwards. Individual loops never
close shared Provider or Voice resources themselves.

## Migration status

A required and initialized Loop is a startup invariant, not a claim that the
native Engine cutover is finished. Host's temporary LiveKit generation path still
owns the current default response. Engine/Turn, Memory, Status, final TTS and
playback integration remain the next functional cutover; this change does not
silently switch models or leave two simultaneous answering paths active.
