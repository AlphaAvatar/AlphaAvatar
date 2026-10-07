# AlphaAvatar Context Plugin

The default Context manager is created by Host after AvatarRuntime is assembled
and is owned by FoundationRuntime. Engine lends Memory/Persona read sources; it
neither constructs the manager nor assembles native Loop context.

## Interface

Use `runtime.foundation.context` through the public ContextManager contract.
`prepare(ContextPrepareRequest)` returns a captured ModelInput. `build(prefix,
continuation=...)` appends canonical execution records without refreshing State.
No query object, parallel context service or provider-specific message API is exposed.

Preparation waits for the explicitly identified committed Turn. It then reads
State and source properties once, captures time and modality information, and
renders the query prefix off the event loop. Pending work is bounded and retained
until it finishes, even when its requesting execution is cancelled.

Captured State and static loop_budget use the existing synthetic
alphaavatar_runtime_context function call/output pair. They do not use a middle
system/developer message. The pair's identity, content and position remain stable
inside one execution. This supports prefix reuse but does not guarantee server
cache hits.

Application-owned behavior rules may be supplied in configuration:

```yaml
context:
  implementation: default
  options:
    behavior_rules: "Follow the application's execution and authorization policies."
    max_pending_preparations: 16
```

StateRuntime.global_behavior_rules may originate from client metadata. They are
included as captured reference/preferences, not promoted into application system
instructions. Binding state sources does not transfer their ownership.

## Lifecycle

Host creates the runtime, resolves the installed alphaavatar.context entry point,
and binds the resulting manager once. Engine then binds its existing processor
sources. Standalone native callers may populate State directly instead.

Stop Loop consumers before closing Foundation. Context waits for its remaining
preparation workers, and Foundation then closes Provider and Voice. There is no
process-global query cache and no per-step mutation of State.

Temporal alignment and visual renderers remain the existing implementations;
this change moves them rather than adding a second rendering pipeline.

The temporary LiveKit SDK generation bridge remains in Host until the native
Engine/Turn/Output cutover. It uses this same ContextManager API. Native Loop
submission does not go through that bridge.
