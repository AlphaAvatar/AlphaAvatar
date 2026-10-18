# AlphaAvatar Core

## 🧩 Introduction

`avatar-core` provides transport-agnostic runtime primitives shared by Agents, plugins and RTC adapters. Core does not depend on Agents, concrete plugins, Provider SDKs or LiveKit.

```text
PerceptionRuntime    normalized observations, annotations and input history
TurnRuntime          committed input snapshots and independent Turn consumers
OutputRuntime        output content, canonical records and execution observations
```

## 📦 Package structure

```text
alphaavatar/core/
├── cleanup.py           # Cancellation-safe waiting for owned cleanup.
├── lifecycle.py         # LifecycleComponent, LifecyclePhase, LifecycleGroup, LifecycleError.
├── log/                 # Explicit diagnostic clients, records and bounded error formatting.
├── env/
│   ├── observation.py   # EnvObservation: input evidence.
│   ├── annotation.py    # Typed input annotations.
│   └── output.py        # EnvOutput: producer-side output contract.
├── media/               # Audio/video frames, text and representation containers.
├── perception/          # Streams, annotations, timelines and captured windows.
├── turn/                # Committed Turn snapshots and consumer cursors.
└── output/
    ├── enums/           # Output kinds, lanes and delivery/control semantics.
    ├── schemas/         # Typed payloads, scope, source and publication envelopes.
    ├── runtime.py       # Ownership, admission, state transitions and publication.
    ├── journal.py       # Independent retained records and execution observations.
    ├── stream.py        # Realtime output distribution.
    └── timeline.py      # Lightweight history without retained PCM frame bodies.
```

## 🔄 Perception and Turns

External RTC/device adapters normalize media into AlphaAvatar payloads. `EnvObservation` supplies identity, source and time before publication to PerceptionRuntime. Annotations and derived views do not replace the original observation's evidence.

TurnRuntime captures committed inputs against a perception cutoff. Consumers have independent cursors; a committed Turn is not a completed model request or persisted Memory entry. Time alignment is configured at `runtime.perception.temporal_alignment`.

```text
RTC / device -> media payload -> EnvObservation -> PerceptionRuntime
                                             -> committed Turn -> consumers
```

## 📤 Output content and publication

A producer constructs a validated `EnvOutput`, then submits normal content with `OutputRuntime.publish(output)`. The published `OutputEvent` contains that object and Runtime-assigned publication information, rather than a second copy of kind, scope, payload and metadata.

```text
Loop / Status / output processor
    -> EnvOutput
    -> OutputRuntime.publish(...)
    -> OutputEvent.output
    -> Router / RTC consumers
```

`EnvOutput` is not an observation and never becomes user input merely because it is published. Content includes typed text, AudioFrame, alignment, transcript, playback and status payloads. Control and status payloads do not need to pretend to be media containers.

Formal identity belongs to `OutputScope`, `OutputSource`, output identity and the relevant payload. Run, request, item, call, content-phase, completion-barrier and interrupt-target information must not be hidden in free metadata.

Metadata is a bounded immutable JSON-style snapshot with reserved-key checks. SDK clients, tensors, coroutine objects, non-finite numbers and media bytes are not extension metadata. A schema validates structure; it cannot infer the business meaning of an arbitrary custom key.

Output text preserves whitespace, line breaks and indentation. Input-side `TextPayload.create()` normalization is a separate contract. Audio publication reuses the validated AudioFrame and immutable bytes without re-encoding them. A frozen envelope does not make a mutable media representation cache deeply immutable; consumers must not replace published canonical content.

## Three separate output flows

| Flow | Purpose | Reliability boundary |
| --- | --- | --- |
| `stream` | Realtime text, media, control, playback and presentation | Delivery subscriptions and managed lifecycle transitions |
| `records` | Canonical batches for independent consumers such as Memory | Synchronous atomic admission, bounded retention and consumer acknowledgement |
| `execution` | Bounded execution observations for Status and diagnostics | Consumers can detect gaps; observations are not canonical persistence |

Record admission does not prove database persistence or client delivery. Internal records are not sent to RTC as presentation content. A late tool outcome may still need to be recorded after its Run loses user-facing output permission.

## Identity, interruption and completion

`context_id`, `turn_id`, `run_id` and `output_id` have different scopes; a chunk or content index is not a substitute for an owning output identity. Closed outputs cannot be reopened by late producer data.

Runtime control operations such as `activate_run`, `revoke_run`, `start_turn` and `interrupt` remain explicit. Constructing a CONTROL EnvOutput does not grant permission to bypass state transitions or fabricate a completion barrier.

Interrupt targets are fixed when the operation is accepted. Consumers use the resulting exact output/lane/scope identities and do not rematch a later output by a broad lane or Turn. Accepted in-flight media and its completion barrier remain accounted for even when interruption overlaps subscriber backpressure.

| Signal | Meaning |
| --- | --- |
| `TEXT_COMPLETE` | The text source is sealed; synthesis may still have work. |
| `AUDIO_COMPLETE` | Audio/alignment production is sealed against Runtime-owned sequence barriers. |
| `COMPLETE` | The logical output has reached its Runtime terminal state. |
| `PLAYBACK` | The transport reports what was actually played; this is not inferred from generation. |

Accepted terminal publication belongs to managed tasks. Caller cancellation must not silently discard it. Closing OutputRuntime releases subscription backpressure and settles owned work rather than leaving publication tasks orphaned.

## ⏱️ Text and transcript delivery

`IMMEDIATE` text can be delivered without audio. `AUDIO_SYNCED` text is released through transcript synchronization using alignment and transport playback. `MIRROR` is observational text for a separately owned delivery path, not a second user-visible answer.

Generated source text and playback-derived transcript remain separate. After interruption, already delivered text remains visible and unplayed text is not reported as heard. Alignment may be an estimate; transport playback feedback is the evidence of delivered audio.

## Lifecycle primitives

`LifecycleComponent` defines `on_start()` and `on_stop()`. `LifecycleGroup` orders phases, starts independent components within a phase concurrently, and closes phases in reverse order. It owns components even before startup completes; cleanup must tolerate partial or unstarted initialization.

Start/stop operations have shared task ownership, failed startup is rolled back, and cleanup failures are surfaced after ordinary peer cleanup. A stopped group is not restarted. Business operations such as Memory final extraction remain outside Core.

## 🔌 Transport independence

RTC owns codecs, rooms, tracks and frontend projection. Router owns synthesis and transcript coordination. Model/tool execution belongs to Agents and Foundation plugins. Core owns the data and lifecycle contracts that connect them, not a second generic event bus or plugin schema registry.

## Diagnostic logging

`log/` provides explicitly configured, nonblocking local diagnostic producers, a bounded
JSON record contract, exception metadata formatting and scoped Python-stream capture.
`log/events.py` adds bounded conversation observations using existing session/Turn/Run
identities. Producers submit immutable text fragments only at committed-input and
recorded-output boundaries; Host policy decides whether previews can be serialized.
No provisional input, opaque reasoning, tool arguments or media data is collected by
these events.
It does not install handlers at import time, depend on Host, configure a model, or
write the application's log files. Host owns console branding, collection, rotation
and final diagnostic draining. Normal application loggers continue using `logging`.

Diagnostic records may be dropped under load and are not canonical output records,
Memory persistence or a replacement for execution outcome tracking. See
[Conversation diagnostics](../avatar-host/README.md#conversation-diagnostics) for capture
settings and [Avatar workspace](../docs/avatar-workspace-layout.md) for finding saved logs.
Preview capture is not a delivery acknowledgement. Console-only previews may still be
saved by a terminal, service manager or output redirection.
