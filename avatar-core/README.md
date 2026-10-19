# AlphaAvatar Core

`avatar-core` provides transport-independent media, event and lifecycle contracts.
It does not depend on Agents, concrete plugins, model SDKs or LiveKit.

## 📦 Package structure

```text
alphaavatar/core/
├── cleanup.py          # Cancellation-safe waiting for owned cleanup.
├── lifecycle.py        # Components, phases and ordered lifecycle groups.
├── log/                # Diagnostic records, producers and error formatting.
├── env/                # Input observations, annotations and output envelopes.
├── media/              # AlphaAvatar-owned audio, image, video and text payloads.
├── perception/         # Source lineage, event streams, windows and timelines.
├── turn/               # Committed input snapshots and independent consumers.
└── output/             # Delivery, canonical records, control and playback facts.
    ├── enums/
    ├── schemas/
    ├── runtime.py
    ├── stream.py
    ├── journal.py
    └── timeline.py
```

## Runtime contracts

| Runtime | Responsibility |
| --- | --- |
| `PerceptionRuntime` | Normalized input evidence, source generations, annotations and time-aligned snapshots. |
| `TurnRuntime` | Committed input snapshots captured against a perception cutoff, with independent consumer cursors. |
| `OutputRuntime` | Validated output admission, exact interruption, completion and independent record/execution streams. |

Adapters normalize external data into `EnvObservation`. Producers submit `EnvOutput` to
OutputRuntime; the resulting `OutputEvent` adds runtime publication identity and timing.
Inputs and outputs are distinct contracts. Text output preserves whitespace; media reuses
validated frames rather than encoding them again for each consumer.

Identity belongs to typed scope/source fields. Context, Turn, Run, output and chunk IDs
are not interchangeable. Metadata is a bounded immutable extension, not a place for SDK
clients, tensors, media bytes or conflicting identity fields.

## Delivery and completion

Realtime `stream` subscriptions carry media and presentation. `records` admits canonical
batches for independent consumers such as Memory. `execution` carries bounded execution
observations for Status and diagnostics. Record admission is not database persistence,
client delivery or proof that a tool succeeded.

`TEXT_COMPLETE` seals source text; `AUDIO_COMPLETE` seals synthesis and alignment;
`COMPLETE` ends source production; `PLAYBACK` reports the transport's measured progress.
Interrupts resolve exact output identities when admitted and bypass ordinary queue
backpressure. Late callbacks cannot reinterpret an interrupt against a newer Run.

`IMMEDIATE` text does not require audio. `AUDIO_SYNCED` text is synthesized by Router and
released as captions according to playback progress. `MIRROR` is observational, not a
second user-visible response. Estimated timing is distinguished from measured duration;
finalization does not retract an already emitted caption prefix or change audio speed.

## Lifecycle and diagnostics

`LifecycleComponent` defines asynchronous `on_start()` / `on_stop()`. `LifecycleGroup`
starts phases in order and stops them in reverse; components within a phase run concurrently.
Cleanup owns partial initialization too. Cancellation does not silently abandon already
admitted work, and failed cleanup remains visible.

Core logging installs no handlers at import time. Modules use standard `logging`; Host
owns collection, formatting and file rotation. Optional Core event diagnostics are sampled,
may be dropped, and do not replace canonical records or execution outcomes. See
[Host settings](../avatar-host/README.md) and the user-facing
[workspace guide](../docs/avatar-workspace-layout.md) for saved logs and backups.
