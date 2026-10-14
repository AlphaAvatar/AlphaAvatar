# AlphaAvatar Context Plugin

The default Context manager is created by Host against a partial AvatarRuntime and then owned by FoundationRuntime. Engine lends Memory/Persona read sources; it does not assemble native Loop prompts or own an SDK ChatContext.

## Interface

Use `runtime.foundation.context` through the public ContextManager contract:

- `accept_turn(snapshot)` accepts a committed Turn and supplies its current input seed.
- `prepare(ContextPrepareRequest)` captures the native history, perception and query prefix.
- `build(prefix, continuation=...)` appends execution continuation without refreshing State.

There is no parallel query-manager API. ContextContribution and ContextPrepareRequest live in the public `alphaavatar.agents.avatar.context.schemas` namespace.

Preparation waits for the explicitly identified committed Turn, captures State, source properties, time and modality information once, and renders the prefix off the event loop. Pending preparations are bounded and remain owned until settled, even when their requesting execution is cancelled.

State and static `loop_budget` use the synthetic `alphaavatar_runtime_context` function-call/output pair. Its identity, content and position remain stable inside one query. No middle system/developer update or per-model-step budget rewrite is introduced. Stable prefixes permit reuse but do not guarantee provider cache hits.

## Native history

The manager retains bounded history by context and Turn and independently consumes canonical model records from Output. User input comes from committed Turns; Engine does not reconstruct assistant/tool records from a LoopResult or inject Memory writes.

Incomplete tool-call/output pairs are excluded from the next model input. Retiring Run results remain associated with their original identity and do not resurrect evicted Turns. Context acknowledgement is independent of Memory acknowledgement and is not a database-persistence guarantee.

```yaml
context:
  plugin: default
  init_config:
    behavior_rules: "Follow the application's execution and authorization policies."
    max_pending_preparations: 16
    history_max_turns: 32
    history_max_items: 4096
    history_max_bytes: 8388608
```

The history byte limit bounds serialized retained content, not total process memory or shared media caches. Eviction respects whole-Turn history ownership.

StateRuntime.global_behavior_rules may originate from client metadata. It is captured as reference/preferences, not promoted into application system instructions. Binding Memory/Persona sources does not transfer their ownership.

## Lifecycle

Host constructs Context, Voice and the required Loop before binding Foundation. It initializes Loop only after binding. Context creation must not request an unavailable Foundation service. Loop is not optional and `loop: null` is invalid.

Ingress and execution producers stop before record consumers are drained. Foundation closes Loop, Context/preparation work, and shared Provider/Voice before Output and Inference are released. Context does not close borrowed Memory or Persona components.

The SDK generation bridge is removed. Native history and ContextManager are the main path, not a fallback beside SDK ChatContext. Temporal alignment and visual rendering remain separate components; there is no process-global query cache or per-step mutation of State.
