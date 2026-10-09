# AlphaAvatar Loop Plugin

Loop is a required Foundation component initialized after Foundation is bound to
AvatarRuntime. Construction stores configuration; initialize() resolves shared
Provider services and validates streaming support without making model requests.
Engine and submission require an initialized, non-closed Loop.

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
```

The model identifier is supplied by the deployment, never inferred from the old
SDK llm configuration. AvatarConfig retains its default LoopConfig; absent model
settings fail when the selected Loop plugin validates its configuration.

```python
loop = runtime.foundation.loop
handle = await loop.submit(request, authorize=authorize)
result = await handle.wait()
```

There are no on_event/on_commit parameters or LoopDependencies container. Shared
Provider, ContextManager, capabilities and output are obtained from AvatarRuntime.
Tool authorization is a separate decision and remains explicit. Without an
authorizer, only capabilities explicitly configured read-only with no approval
requirement may run. A model-generated tool call does not grant permission.

## Submission and static query context

submit() validates a committed input and schedules an owned execution. The owned
task prepares Context through the single ContextManager interface. Engine does
not prebuild it or wait for the model/tool loop. Retiring executions retain their
cleanup ownership; their text lease is revoked before the replacement begins.

State and static loop_budget are captured once via synthetic runtime tool context.
Subsequent requests append canonical model/tool items, preserving that prefix,
tool definitions/order and the selected reasoning profile. No middle developer
policy or per-step State rewrite is introduced. Counters still enforce execution
limits and appear only in the observation stream, not changing prompt content.

## Output and records

Visible text goes directly to runtime.output with stable run/message-derived
output_id. Completed messages finish the text source; audio-enabled outputs are
not marked completely finished before TTS produces its remaining audio.

Complete assistant/tool batches go to runtime.output.records. They carry immutable
context/turn/run provenance and are admitted atomically before new tools execute.
Memory independently consumes that stream; Loop never calls a Memory plugin.
Admission is local memory acceptance, not durable persistence or proof of playback.
Private reasoning/continuation remains in the Loop's own working history and is
excluded from the record projection, just like synthetic State/budget context.

Runtime.output.execution receives request, tool and run observations. Commentary
references describe nonempty text actually admitted for this model request, not
whether a vendor advertises commentary support. References reset each request.
Status consumers may derive presentation and narration without recursive Loop use.
Loop has no waiting/narration timer; remove a previously explicit feedback_delay
setting. feedback_timeout still limits asynchronous user-content publication.

If a required record consumer fails or retained capacity is full, the execution
fails explicitly rather than dispatching further tools as though admission
succeeded. Tool results that cannot be admitted still remain in the returned
LoopResult tools collection; no persistence guarantee is made for failed admission.
Cancelled executions settle already accepted calls, never replay writes implicitly,
and publish observed results even when their user-facing output is no longer active.

## Lifecycle and migration status

Stop new execution, close Loop and finish call settlement before draining Memory's
record consumer and final extraction. Foundation then closes Context and shared
Provider/Voice; the Output runtime and other low-level resources close last.

The current Host SDK bridge also publishes native records to the same journal;
it no longer calls Memory. Its old model-generation route is not switched by this
change. The StatusRuntime processor refactor, tool monologue/status cleanup and
Engine/Turn/final TTS/RTC cutover are separate subsequent functional blocks.
