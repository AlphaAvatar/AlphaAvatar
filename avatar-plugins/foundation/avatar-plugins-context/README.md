# AlphaAvatar Context Plugin

The default Context manager is created by Host against a partial AvatarRuntime
and then owned by FoundationRuntime. Engine lends Memory/Persona read sources;
it neither constructs the manager nor assembles native Loop context.

## Interface

Use `runtime.foundation.context` through the public ContextManager contract.
`prepare(ContextPrepareRequest)` returns a captured ModelInput. `build(prefix,
continuation=...)` appends canonical execution records without refreshing State.
There is no PreparedModelContext or parallel query management interface.
ContextContribution and ContextPrepareRequest live in the public schemas/request.py.

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
  plugin: default
  init_config:
    behavior_rules: "Follow the application's execution and authorization policies."
    max_pending_preparations: 16
```

StateRuntime.global_behavior_rules may originate from client metadata. They are
included as captured reference/preferences, not promoted into application system
instructions. Binding state sources does not transfer their ownership.

## Lifecycle

Host resolves the installed alphaavatar.context entry point and creates the
manager before binding Foundation. It constructs an optional native Loop only
after that binding. Context does not request Foundation services during creation.

Foundation first stops its Loop, then closes Context and its remaining preparation
workers, and then closes Provider and Voice. Output and Inference remain available
until Foundation cleanup completes. Applications must stop their ingress and
other consumers before closing the runtime.

Temporal alignment and visual renderers remain the existing implementations.
There is no process-global query cache and no per-step mutation of State.

The temporary LiveKit SDK generation bridge remains in Host until the native
Engine/Turn/Output cutover. It uses this same ContextManager API. Native Loop
submission does not go through that bridge.
