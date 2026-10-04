# AlphaAvatar Loop Plugin

The `realtime` implementation owns an Agent's foreground interaction loop. Public
contracts are in `alphaavatar.agents.avatar.loop`. It does not import a vendor SDK,
LiveKit, a concrete Provider plugin, or Host.

## Ownership

`runtime.foundation.loop.create(config=..., dependencies=...)` discovers the
selected implementation through `alphaavatar.loop` metadata and the existing
AvatarModulePlugin registry. LoopService is only a factory: it has no current
turn, context, request, or message history. Engines own and close returned loops
before closing Foundation.

The caller supplies ProviderService, an AvatarCapabilityRegistry, a per-run
capability allowlist, and optional async feedback, history, and authorization
callbacks. Shared services are borrowed and never closed by the Loop plugin.

## Execution

`await loop.submit(request)` returns a LoopHandle without waiting for a model or
tool. Each handle has a generated run ID and preserves the submitted turn/context
IDs. `await handle.wait()` returns the outcome; cancelling a waiter does not cancel
the execution. Use `handle.cancel()` or `loop.interrupt()` to stop it, and close the
loop at the owning Engine's shutdown boundary.

A new foreground run invalidates the old run's feedback immediately. The old run
retains ownership of model/tool cancellation and history cleanup. A bounded number
of retiring executions is allowed; new work is rejected when that bound is full.

Caller-provided sinks must also use the event's immutable run/turn identity when
publishing to external output. Cancelling a Python task does not retract an event
already delivered to a device. Slow feedback applies async backpressure only to
its execution, not the Turn submission/control path.

Loop results contain only new history items. Model responses are committed before
any associated tool is dispatched. Tool batches commit their results in call order
before the next model request. A commit callback receives an idempotency key; it is
responsible for its storage transaction. Without a callback, history is in-memory
in LoopResult. This is not durable recovery or cross-process exactly-once execution.

## Budget and model behavior

LoopLimits belong to the request. The current budget is rendered as a request-local
developer message, never added permanently to StateRuntime or stored as Persona.
Model steps, tool rounds, total calls, parallelism, arguments and result sizes are
bounded. The exploration deadline reserves time for exactly one answer-only model
request. That request has no tools and uses `tool_choice="none"`; returned tool
calls are rejected rather than dispatched.

No-progress and repeated-call detection prevent commentary-only or repeated-tool
loops. Budget convergence returns a partial answer/outcome, not an iteration-limit
exception. Cancellation never triggers an extra summary. Actual request/protocol
failures remain explicit failed outcomes; they are not relabeled as successful
answers. Callers render a suitable failure message when no answer could be produced.

Reasoning defaults to the selected model's own behavior when the caller has not
provided a verified supported-effort profile. With a profile, quick/auto/careful
intent and no-progress state select a supported level. No per-turn classifier
request, model-name heuristic, or user-facing effort control is introduced.

Deadlines rely on cooperative async SDK/tool cancellation. They cannot forcibly
terminate a blocking or cancellation-suppressing third-party Python handler.

## Tool safety and results

The existing capability registry remains the only handler registry. Tools are a
model-facing projection of the explicitly allowed callable capabilities. The
executor rejects duplicate JSON keys, non-finite JSON values, invalid schemas,
unknown capabilities and reused call IDs. It does not execute partial tool deltas.

Policies are trusted host configuration, not model arguments. Unknown tools require
explicit authorization and run serially. Read-only tools may run concurrently only
when explicitly marked parallel-safe. Without an authorizer, only read-only tools
with `approval_required=False` run. A supplied authorizer decides every call.

Side effects use an instance-wide execution lock, also covering retiring runs.
Cancellation/timeout of a dispatched write records an unknown outcome; it does not
claim rollback and is never silently retried. This version does not retry tool calls.

Handlers return JSON-serializable values, Pydantic objects, text, or an explicit
`CapabilityResult(parts=...)` containing text/media. Result call IDs are supplied
by the executor. Media is retained; unsupported content is rejected, not stringified.
History retains uncertain executed actions even after foreground cancellation.

## Feedback and integration boundary

Feedback contains state transitions, delayed waiting notices, model text/messages,
and tool started/finished facts. Reasoning deltas and opaque continuation items do
not enter user feedback. Model commentary is distinct from final answers. The
request stream completing does not by itself complete the interaction.

This functional block is usable without RTC. It does not yet switch AvatarEngine,
replace the legacy LiveKit ToolBase/plugins, map events to StatusEmitter/TTS, or
provide a durable Context history store. The following main-path integration must
connect these interfaces together and remove the legacy model/tool execution path.
The existing Engine and RTC entrypoint remain unchanged in this block.
