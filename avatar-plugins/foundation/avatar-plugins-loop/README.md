# AlphaAvatar Loop Plugin

Loop is a required Foundation component. Host constructs it with AvatarRuntime, binds Foundation, then calls `initialize()`. Initialization resolves shared services and checks streaming support without making a foreground model request. Engine submission requires an initialized, non-closed Loop.

## Configuration and ownership

```yaml
loop:
  plugin: realtime
  init_config:
    model:
      backend: openai
      provider: openai
      model: YOUR_MODEL_ID
      temperature: null
    tool_policies: {}
```

The deployment supplies the model identifier. The old top-level `llm` section is rejected, not interpreted as Loop settings. Loop cannot be disabled with `null`; a missing required model is rejected when its concrete configuration is validated.

```python
loop = runtime.foundation.loop
handle = await loop.submit(request, authorize=authorize)
result = await handle.wait()
```

Provider, ContextManager, capabilities and Output are obtained from AvatarRuntime. There are no `LoopDependencies`, `on_event` or `on_commit` parameters. Engine owns admission and foreground interruption; Loop owns execution, accepted calls, records and terminal execution facts.

Tool registration is not permission. Without an authorizer, only capabilities explicitly configured read-only with no approval requirement may execute. Use exact capability policies; do not grant an aggregate MCP or RAG capability read-only status based on a single harmless operation.

## Submission and static query context

`submit()` validates committed input and schedules owned execution. The task prepares Context through ContextManager; Engine does not prebuild prompts or wait for the whole model/tool loop. Retiring executions retain cleanup ownership after their user-facing output lease is revoked.

State and static `loop_budget` are captured once via synthetic runtime tool context. Later requests append model/tool continuation while preserving the fixed prefix, tool definitions/order and selected reasoning profile. Counters enforce limits and feed execution observations without rewriting prompt content between steps.

## Output and records

Visible content is constructed as EnvOutput and submitted through `runtime.output.publish(...)`, with stable output identities and typed scope/source association. Text completion seals the source, not the remaining TTS or playback. Router synthesizes ASSISTANT/TRANSIENT text; RTC reports transport playback and delivers synchronized transcripts.

Complete assistant/tool batches use `runtime.output.records`. They carry context/Turn/Run provenance and are admitted atomically before further dependent execution proceeds. Memory and Context consume records independently; Loop calls neither a Memory persistence API nor a transport adapter.

Admission is local acceptance, not durable persistence or proof of playback. Private reasoning/provider continuation and synthetic State/budget material are excluded from the canonical record projection.

`runtime.output.execution` carries request, tool and Run observations. Same-request commentary references identify text actually admitted, not a vendor capability flag. Status derives presentation and non-recursive narration from facts; Loop has no waiting/narration timer. `feedback_timeout` still limits asynchronous user-content publication.

A required record-consumer failure or exhausted retained capacity fails execution explicitly. Tool outcomes that cannot be admitted remain available through the returned result where supported; failed admission is not claimed as persistence. Cancellation settles accepted calls, never blindly replays writes, and preserves observed results even after visible output permission is lost.

## Lifecycle and migration status

Engine stops admission and settles Loop while Memory, Status and Output consumers remain alive. It then closes Router and plugins; Host closes RTC outputs and releases AvatarRuntime. Foundation closes Loop idempotently as its resource owner before releasing Context, Provider and Voice.

The native Engine/Loop path is active in this source tree. The old TurnController and Host SDK model/tool/record bridges are removed. Voice now implements native async PCM synthesis. Character has a separate native presentation lifecycle and does not submit another Loop. SDK worker hosting remains a separate boundary; it does not own the main generation path.

Execution still belongs to the current Host execution. Connection-independent Episodes, recovery, sleep/wake and Dream scheduling are not provided by this plugin migration.
