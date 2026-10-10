# AlphaAvatar Status Plugin

Status is a lifecycle-managed observer, not an execution controller or tool dependency.
Its processors consume Core data streams and derive presentation decisions. They do
not register tools, call AvatarLoop, or generate model records for Memory.

## Data flow

```text
TurnRuntime events ─┐
Output.execution ───┼── Activity ── Presentation ── Output STATUS decisions ── RTC
Assistant text ─────┘                              └── Narration ── TRANSIENT text
```

`StatusRuntime` owns three processors and their tasks. Each processor has its own
configuration and lifecycle under `processors/<name>/`.

Activity maintains bounded, Run-scoped observations. It drains pending Turn and
execution facts before interpreting independently scheduled delivery notifications.
Replacing an individual assistant output is not a Run interruption. Execution-journal
gaps are diagnostic losses, not permission to invent missing execution facts.

Presentation publishes typed `OutputStatusDecision` objects with source identity,
execution scope, revision, expiry and audience. Internal decisions remain local.
Only user decisions are projected by the RTC adapter, using an explicit field allow-list.
No tool arguments, private reasoning or canonical record payloads are sent as status.

Narration consumes user decisions with a narration key. Current English and Chinese
rules are deterministic and non-recursive. A future model renderer can replace this
processor's renderer without calling the foreground Loop. Narration is transient:
it is not an assistant-history commit and never re-enters the execution journal.

## Commentary and interruption

Suppression depends on actual text and same-request commentary references, not a
provider-name flag. Missing commentary permits a delayed fallback. Tool failure and
unknown-outcome decisions are separate from routine waiting narration. A pending
notice is discarded when its observed revision is no longer current.

Generated text is not proof of completed playout. Status observes accepted source
text and execution facts; transport playback remains authoritative for delivery.
Narration may be skipped when the response completes quickly or its decision expires.
It never claims that a cancelled operation was rolled back or should be blindly retried.

The natural-language output uses the TRANSIENT lane. Audio-enabled sessions use
AUDIO_SYNCED source text; Router owns speech synthesis, alignment and audio completion.
Text-only sessions publish IMMEDIATE text. User interruption and newer output preempt
transient speech. The narration worker cancels its own pending work on supersession.

## Configuration

The existing `status: {plugin: default, enabled: true, init_config: {}}` remains valid.

```yaml
status:
  plugin: default
  enabled: true
  action_topic: agent.status.action
  init_config:
    activity:
      max_pending: 128
      max_runs: 128
    presentation:
      waiting_delay: 1.5
      min_narration_interval: 4.0
      max_narrations_per_turn: 3
      decision_ttl: 5.0
      publish_timeout: 0.5
      system_decisions: true
    narration:
      enabled: true
      language: en
      publish_timeout: 1.0
```

Use `language: zh` for Chinese rule narration. Language is configuration, not a
hidden classification-model request. `text_topic` is removed: source text and
synchronized transcripts use the existing Output/RTC text delivery path.

Narration limits count published narration decisions, not proof of heard speech.
All status paths are bounded, best-effort diagnostics/presentation. Their backpressure
or failures do not modify actual tool outcomes or block synchronous record admission.
The canonical record journal and its required consumers are unchanged.

## Ownership and migration state

Engine creates the Status plugin and starts/stops it with the other consumers.
Engine and Loop publish execution facts; neither injects a StatusEmitter. ToolBase
and tool plugins accept no Status dependency. Tool request schemas contain no
`monologue`; the tool performs the operation and returns its outcome.

The current application still uses the temporary SDK response path. Host's
LiveKitExecutionBridge observes its model/tool operations using the owning
SpeechHandle, and the raw-schema tool projection still invokes the native registry.
It owns no presentation policy and does not choose models or execute an extra Loop.
This bridge is removed with the subsequent native Engine/main-output cutover.

`context_status.py` is removed. `turn_controller.py` remains until that cutover.
Static query State, synthetic runtime context, loop budgets, model configuration,
Memory consumption, Provider ownership and tool authorization policy are unchanged.
