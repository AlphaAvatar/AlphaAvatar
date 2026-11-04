# AlphaAvatar Context Plugin

The default Context manager is created by Host against a partial AvatarRuntime and then owned by FoundationRuntime. Engine lends Memory/Persona read sources; it does not assemble native Loop prompts or own an SDK ChatContext.

## Interface

Use `runtime.foundation.context` through the public ContextManager contract:

- `prepare(ContextPrepareRequest)` accepts the committed Turn from Loop and prepares its history, perception and query prefix.
- `build(prefix, continuation=...)` appends execution continuation without refreshing State.

There is no parallel query-manager API. ContextContribution and ContextPrepareRequest live in the public `alphaavatar.agents.avatar.context.schemas` namespace.

Preparation waits for the explicitly identified committed Turn, captures State, source properties, time and modality information once, and renders the prefix off the event loop. Pending preparations are bounded and remain owned until settled, even when their requesting execution is cancelled.

State and static `loop_budget` use the synthetic `alphaavatar_runtime_context` function-call/output pair. Its identity, content and position remain stable inside one query. No middle system/developer update or per-model-step budget rewrite is introduced. Stable prefixes permit reuse but do not guarantee provider cache hits.

## Native history

The manager retains the whole history by context and Turn and independently consumes canonical model records from Output. User input comes from committed Turns, including turns superseded before preparation. A system notice enters the current user message as a typed text part at the corresponding speech segment. History preserves the notice facts and their order when the snapshot retains the timing evidence.

Incomplete tool-call/output pairs are excluded from the next model input. Retiring Run results remain associated with their original identity. Context acknowledgement is independent of Memory acknowledgement and is not a database-persistence guarantee.

```yaml
context:
  plugin: default
  init_config:
    behavior_rules: "Follow the application's execution and authorization policies."
    max_pending_preparations: 16
```

History keeps the complete user message throughout the session, as ContextBuilder first built it, including the order and captured content of its media. After capture, the manager uses ContextCompressor to replace historical image payloads with `<image_not_replayed />` at their original position in the outgoing request. The current Turn carries its complete user message and its own runtime context.

Profiles that still set `history_max_turns`, `history_max_items` or `history_max_bytes` load, and those values are ignored.

StateRuntime.global_behavior_rules may originate from client metadata. It is captured as reference/preferences, not promoted into application system instructions. Binding Memory/Persona sources does not transfer their ownership.

## Lifecycle

Host constructs Context, Voice and the required Loop before binding Foundation. It initializes Loop only after binding. Context creation must not request an unavailable Foundation service. Loop is not optional and `loop: null` is invalid.

Ingress and execution producers stop before record consumers are drained. Foundation closes Loop, Context/preparation work, and shared Provider/Voice before Output and Inference are released. Context does not close borrowed Memory or Persona components.

The SDK generation bridge is removed. Native history and ContextManager are the main path, not a fallback beside SDK ChatContext. Temporal alignment and visual rendering remain separate components; there is no process-global query cache or per-step mutation of State.
