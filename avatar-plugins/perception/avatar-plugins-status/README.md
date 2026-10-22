# AlphaAvatar Status Plugin

Status is a lifecycle-managed observer, not an execution controller or tool dependency. Its processors consume Core streams and derive presentation; they do not register tools, call the foreground Loop or publish canonical Memory records.

## Data flow

```text
TurnRuntime events + Output.execution + assistant text
    -> Activity -> Presentation -> typed STATUS decisions -> RTC
                               -> Narration -> TRANSIENT text -> Router / RTC
```

StatusRuntime owns activity, presentation and narration processors. Each owns its configuration and lifecycle under `processors/<name>/`.

Activity retains bounded Run-scoped observations and interprets independently scheduled notifications against pending Turn/execution facts. Replacing one output is not a Run interruption. Journal gaps are diagnostic losses, not permission to invent missing facts.

Presentation publishes OutputStatusDecision with identity, scope, revision, expiry and audience, carried through EnvOutput. Internal decisions remain local. RTC projects only allowed user-facing fields, not tool arguments, private reasoning or canonical records.

Narration consumes eligible user decisions and uses deterministic English/Chinese rules. A future model renderer must remain independent of the foreground Loop. Narration is transient, not an assistant-history commit, and does not re-enter the execution journal.

## Commentary, interruption and terminal status

Suppression depends on actual admitted text and same-request commentary references, not provider-name flags. Missing commentary can allow delayed fallback; failures and unknown tool outcomes have distinct decisions. Superseded revisions and expired decisions cannot narrate later as though still current.

Generated text is not proof of playback. Audio-enabled narration uses AUDIO_SYNCED text, and Router owns TTS/alignment; text-only sessions use IMMEDIATE output. User interruption and newer output can preempt transient speech.

Terminal presentation permission is distinct from model-generation permission. A terminal decision can remain displayable without reactivating a retired Run. Narration is bound to its decision and still checks scope, revision and validity. It must never claim that cancellation rolled back an external side effect.

## Configuration

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

`init_config: {}` remains valid. Use `language: zh` for Chinese rule narration. `text_topic` is removed; text and synchronized transcripts use the shared Output/RTC path. Limits count published narration decisions, not proof of heard speech.

Status is bounded, best-effort observation/presentation. Its failure cannot change a real tool outcome or imply canonical record persistence.

## Ownership and migration state

Engine creates/starts Status as a consumer and settles Loop before closing consumers. Engine and Loop publish facts; tools take no StatusEmitter dependency and no `monologue` request field.

The SDK execution bridge, raw-schema SDK tool projection and TurnController are removed. Status observes the native main path, not a temporary SDK response path. Context capture, model selection, budgets, canonical records and tool authorization remain owned by their corresponding components.
