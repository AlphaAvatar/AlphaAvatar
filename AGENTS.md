# AlphaAvatar agent guide

[中文](AGENTS-zh.md) · [Project overview](README.md) · [Development](CONTRIBUTING.md)

This is the repository navigation guide for coding agents.
Use it to find the owner, contract, implementation and relevant checks for a change.
Detailed behavior belongs in the linked source and documentation rather than duplicated here.
Paths are relative to the repository root; shell commands below run from that root.

## 1. Start here

Read only the parts needed for the task, then follow the implementation and its consumers.

| Question | First stop |
| --- | --- |
| What is the project building? | [Goals](#2-development-goals) and [Roadmap](docs/ROADMAP.md). |
| Which package owns the change? | [Workspace map](#3-workspace-map) and [dependency boundaries](#4-dependency-boundaries). |
| How does an interaction run? | [Runtime ownership](#5-runtime-ownership), then the relevant input/output section. |
| What does an identifier mean? | [Identifier reference](docs/identifiers-zh.md). |
| How should the code read? | [Coding rules](#18-coding-rules) and [coding conventions](docs/coding-conventions.md). |
| How do I run or validate it? | [Development checks](#19-development-and-validation) and [CLI documentation](docs/cli/README.md). |
| Where are known defects? | [Bug register](docs/bugs-zh.md); verify each entry against current source. |
| Why was something changed? | [Agent work records](docs/agent-logs/), scoped to the relevant date/task. |

For a code change, locate both its public contract and all affected consumers.
For a review, establish the requested commit/ref and distinguish source review from runtime validation.
Existing working-tree changes belong to their authors; preserve unrelated work.
Keep the requested scope explicit and proceed with work already authorized by the user.

## 2. Development goals

AlphaAvatar is a self-hostable, configurable, pluggable realtime multimodal personal assistant.
Its longer-term direction is a continuous assistant that remembers, understands and acts.

- Design for mobile and other personal devices, alongside desktop and server execution.
- Keep one composable runtime architecture that can evolve toward device/cloud cooperation.
- Prefer modular capabilities over a separate reduced mobile architecture.
- Keep the interaction path asynchronous, responsive and full duplex.
- Allow input reception, interpretation, generation and playback to progress independently.
- Make loss, cancellation, stale work and partial completion observable.
- Keep personal data ownership and private-context access explicit.
- Let models supply individual capabilities without turning the framework into an opaque model wrapper.
- Reuse typed contracts and runtime services rather than duplicating plugin state in Core.

These are design goals, not claims that every platform or topology already works.
The current Host uses Python 3.13 and POSIX execution supervision.
The implemented RTC backend is LiveKit; generic backend contracts do not imply other implementations.
The App directory currently reserves future client work; Host runs without an App.
Mobile runtime delivery, additional transports and persistent execution recovery remain separate work.

Use [docs/ROADMAP.md](docs/ROADMAP.md) for planned milestones and their stated status.
Use current code and tests to establish actual behavior before changing it.
Release notes and dated experiment records describe their own versions and conditions.

## 3. Workspace map

The Python workspace contains four base packages and twelve plugin packages.
The root `pyproject.toml` defines shared development tooling and workspace membership.
Each distribution owns its runtime dependency metadata and resources.

| Location | Responsibility | Read first |
| --- | --- | --- |
| `avatar-core/` | Transport-independent media, events, clocks, lifecycle and runtime contracts. | [Core README](avatar-core/README.md). |
| `avatar-agents/` | Engine, Agent contracts, runtime composition, capabilities and inference. | [Agents README](avatar-agents/README.md). |
| `avatar-rtc/` | Transport adapters that consume Core contracts. | [RTC README](avatar-rtc/README.md). |
| `avatar-host/` | CLI, application startup, configuration, processes, sessions, setup and Doctor. | [Host README](avatar-host/README.md). |
| `avatar-plugins/foundation/` | Context, Loop, Provider and Voice implementations. | [Plugin boundaries](avatar-plugins/README.md). |
| `avatar-plugins/perception/` | Router, Memory, Persona, Character and Status. | [Plugin catalog](README.md#alphaavatar-plugins). |
| `avatar-plugins/tools/` | DeepResearch, MCP and RAG. | [Plugin boundaries](avatar-plugins/README.md). |
| `avatar-app/` | Reserved client/App scope; no installable App is supplied yet. | [App README](avatar-app/README.md). |
| `examples/` | Complete configuration examples and supporting examples. | [Examples README](examples/README.md). |
| `tests/fixtures/` | Shared small samples and opt-in large-sample manifest. | `conftest.py` and the sample manifest. |
| `packaging/linux/` | Linux package construction, installation and capability wheels. | [Setup guide](docs/cli/setup.md). |
| `scripts/` | Quality, documentation, maintenance and release utilities. | [Task routing](#21-common-change-routes). |
| `docs/` | Guides, CLI reference, roadmap, deployment, release history and agent records. | [Documentation index](#22-documentation-index). |

`avatar-app` is not a Python uv workspace member.
Plugin layer directories organize the repository; they do not add Python namespace segments.
Keep the shared `alphaavatar` namespace package; do not add a namespace-root `__init__.py`.

## 4. Dependency boundaries

Preserve the direction of dependencies when moving code or sharing behavior.

| Consumer | Allowed architectural dependency |
| --- | --- |
| Core | Standard/declared low-level dependencies; no Agents, Host, plugins or RTC. |
| Agents | Core and its declared execution abstractions; no Host ownership. |
| RTC | Core; backend libraries through the relevant optional extra. |
| Host | Agents, Core and selected RTC/application integrations. |
| Plugins | Agents/Core contracts and explicitly borrowed shared services. |

The essential directions are **RTC → Core**, **Agents → Core**, **Host → Agents**.
RTC receives injected callbacks where Agent behavior is required.
Core must not import model SDKs, concrete plugins or LiveKit ownership.
Keep SDK types at adapter boundaries rather than in public media/output schemas.
The native path does not use `livekit.agents` or its worker/AgentSession lifecycle.
Ruff explicitly bans imports of that removed SDK API.
Do not recreate an obsolete bridge as a parallel execution path.

## 5. Runtime ownership

Find the owner before adding state, a background task or a close operation.

| Owner | What it owns | Implementation entry |
| --- | --- | --- |
| Host application | Shared services, execution supervision, health and signals. | [application/](avatar-host/alphaavatar/host/application/). |
| Host execution | A child execution's Engine and AvatarRuntime lifecycle. | [execution/](avatar-host/alphaavatar/host/execution/). |
| Session attachment | Input/output adapters, subscriptions and connection attachment. | [sessions/](avatar-host/alphaavatar/host/sessions/). |
| SessionRuntime | Participants, accepted identity bindings and session events. | [session/](avatar-core/alphaavatar/core/session/). |
| AvatarRuntime | Composition of state, Core runtimes, Foundation, participants and capabilities. | [runtime.py](avatar-agents/alphaavatar/agents/runtime/runtime.py). |
| PerceptionRuntime | Observation/annotation publication, source lineage and temporal evidence. | [perception/](avatar-core/alphaavatar/core/perception/). |
| TurnRuntime | Committed input snapshots and their independent consumers. | [turn/](avatar-core/alphaavatar/core/turn/). |
| OutputRuntime | Output admission, delivery, execution observations and canonical records. | [output/](avatar-core/alphaavatar/core/output/). |
| AvatarEngine | Turn admission, duplicate/stale-input isolation and foreground interruption. | [engine.py](avatar-agents/alphaavatar/agents/avatar/engine.py). |
| FoundationRuntime | Shared Context, Loop, Provider and Voice services. | [foundation/](avatar-agents/alphaavatar/agents/runtime/modules/foundation/). |

A consumer owns its tasks, subscriptions and request state.
Borrowing a shared service does not transfer the right to close it.
Detaching transport, stopping an execution and persisting records are distinct boundaries.
Session shutdown is not the only point at which durable data may be written.

## 6. Configuration and plugin selection

Start with the selected bundle/file and its effective configuration, not a guessed default.

| Concern | Entry |
| --- | --- |
| Host configuration loading | [host/configs/](avatar-host/alphaavatar/host/configs/). |
| Strict Avatar configuration | [agents/configs/](avatar-agents/alphaavatar/agents/configs/). |
| Plugin discovery and setting validation | [runtime/plugin/](avatar-agents/alphaavatar/agents/runtime/plugin/). |
| Runtime limits and retention | [runtime_config.py](avatar-agents/alphaavatar/agents/configs/runtime_config.py). |
| Example selections | [examples/agent_configs/](examples/agent_configs/). |
| Bundle/profile authoring | [CLI config guide](docs/cli/config.md). |

- Host reads the top-level `host` section before strict AvatarConfig validation.
- The main model is selected under `loop.init_config.model`.
- Foundation selections include `context`, `loop` and `voice`.
- Processor-specific settings, prompts and model specifications stay with their owner.
- Installed implementations are discovered through `alphaavatar.<type>` entry points.
- `AvatarModulePlugin` validates settings and declares selected inference runners.
- Registration and configuration inspection must not load or download models.
- Factories create configured instances and carry no session-specific mutable state.
- Optional STT `language` and `prompt` require explicit support from the selected implementation.
- Automatic language selection and a fixed language hint have different semantics.
- Changing selected components currently requires application restart.
- Execution children restore validated snapshots without resolving the Avatar workspace twice.

Keep validation errors attached to the actual setting that selects or configures a plugin.

## 7. Startup and shutdown

Use the owning lifecycle instead of adding a second manager for the same resource.

1. Host resolves configuration, application/workspace paths and selected services.
2. Shared inference initializes its selected worker plan.
3. An execution assembles Session, AvatarRuntime, Foundation and Engine.
4. Attachment outputs start before Engine; Engine consumers start before Router decisions.
5. Attachment inputs start once the execution can accept their work.
6. Shutdown releases ingress and settles accepted work through the owning components.

Exact assembly lives in Host; use the source when changing ordering.

- `LifecycleComponent` exposes async `on_start()` and `on_stop()`.
- `LifecycleGroup` orders phases, runs independent components within a phase concurrently and reverses phases on stop.
- Partial initialization also owns cleanup.
- Concurrent close callers should share the same owned close operation.
- A caller's cancellation must not abandon admitted cleanup.
- Keep canonical record consumers alive while their producers settle.
- Release borrowed subscriptions without closing the shared runtime or room.
- Preserve useful cleanup failures rather than silently reporting success.

Read [core/lifecycle.py](avatar-core/alphaavatar/core/lifecycle.py) and
[core/cleanup.py](avatar-core/alphaavatar/core/cleanup.py) before changing these rules.
Host session/execution policy decides termination; an RTC disconnection does not itself own Engine destruction.

## 8. Perception and temporal evidence

Inputs are typed `EnvObservation` values; interpretation arrives as annotations.
Core owns their lineage, event order, retention and temporal lookup.

| Contract | Meaning |
| --- | --- |
| `PerceptionSourceRef` | Source identity together with its generation. |
| `PerceptionSegmentRef` | A speech segment qualified by its complete source reference. |
| `PerceptionEntityRef` | A perception entity label qualified by its source. |
| Observation ID | One observation, including its payload/reference and media time. |
| Annotation ID | One interpretation record targeting evidence. |
| Event sequence | Publication order inside its own event stream. |
| Consumer ID/cursor | A reader and its acknowledged progress in that stream. |
| Perception cutoff | The retained evidence boundary captured for a committed Turn. |

Do not compare sequence numbers from different streams as a global clock.
Publication order and media timestamps answer different questions.
A consumer cursor does not identify a speaker or define a Turn's owned segments.
Use complete typed source/segment/entity references across generations.
Expose gaps, missed counts and retention boundaries when evidence has been lost.
Do not substitute newer evidence merely because the original observation expired.

Start at [PerceptionRuntime](avatar-core/alphaavatar/core/perception/runtime.py), then
[perception schemas](avatar-core/alphaavatar/core/perception/schemas/) and
[identifier rules](docs/identifiers-zh.md).

## 9. Voice models and speech streams

Reusable voice components belong to Foundation Voice.
Router owns the streams and jobs that borrow those components.

| Concern | Implementation |
| --- | --- |
| VAD model/factory and runner | [voice/vad/](avatar-plugins/foundation/avatar-plugins-voice/alphaavatar/plugins/voice/vad/). |
| Segment/realtime STT implementations | [voice/stt/](avatar-plugins/foundation/avatar-plugins-voice/alphaavatar/plugins/voice/stt/). |
| TTS provider implementations | [voice/tts/](avatar-plugins/foundation/avatar-plugins-voice/alphaavatar/plugins/voice/tts/). |
| Audio activity and segment publication | [router/audio_activity/](avatar-plugins/perception/avatar-plugins-router/alphaavatar/plugins/router/processors/audio_activity/). |
| Transcription consumption | [router/speech/](avatar-plugins/perception/avatar-plugins-router/alphaavatar/plugins/router/processors/speech/). |
| Speech completion assessment | [router/turn_taking/](avatar-plugins/perception/avatar-plugins-router/alphaavatar/plugins/router/processors/turn_taking/). |

- Publish normalized audio once and let independent consumers derive results.
- A VAD segment boundary is not automatically a conversational Turn boundary.
- Segment IDs are allocated by the speech path, not by speaker recognition.
- STT results retain the originating segment and source generation.
- Terminal transcript state must agree with what consumers actually receive.
- Keep upload, response-header wait, first event and final event timing distinct.
- Connection reuse requires the owning HTTP response/body lifecycle to settle correctly.
- Keep provider framing/decoding details inside its adapter.
- A fixed language hint must not silently become a universal hardcoded language policy.
- Prompt/language experiments do not establish behavior for every language or noisy input.
- VAD latency comparisons also need correct cross-segment turn-taking behavior.
- Preserve sample identity and strict pass criteria when comparing measurements.

See [Voice README](avatar-plugins/foundation/avatar-plugins-voice/README.md) for supported settings.

## 10. Turn-taking and admission

Turn-taking evaluates a temporal input flow assembled from observations and annotations.
Persona supplies speaker/identity evidence; turn-taking does not identify people.

| Component | Responsibility |
| --- | --- |
| `TurnTakingProcessor` | Consume perception/annotation/Turn streams and own processor lifecycle. |
| `TurnTakingCoordinator` | Maintain the input window and coordinate assessment, waiting and publication. |
| `InputWindow` | Input membership, active/closed segments, transcripts and revision. |
| `TurnEvidenceBuilder` | Build model evidence from the input and retained temporal context. |
| `TurnAddressing` / `AddressingFusion` | Match and combine addressing evidence. |
| Turn-taking model | Estimate speech completion/interaction evidence through its declared capabilities. |
| `TurnTakingPolicy` | Produce actions from evidence and assessment. |
| `AssessmentWork` | Replace, cancel, trace and reap asynchronous assessment workers. |
| `AvatarEngine` | Validate the proposed action/input and admit an actual Turn. |

Implementation: [turn_taking/](avatar-plugins/perception/avatar-plugins-router/alphaavatar/plugins/router/processors/turn_taking/).
Public contracts: [agents/router/](avatar-agents/alphaavatar/agents/router/).

- `input_id` identifies the proposed temporal input; `revision` detects stale assessment.
- Speaker/entity labels do not split the audio assessed for speech completion into independent person candidates.
- A HOLD for incomplete or uncertain speech keeps the current input open for subsequent speech and reassessment.
- Once speech completion is decided, an input may be sealed while its STT results are pending.
- Sealed input membership stays fixed while the next input can continue arriving.
- Pending records serve transcript/admission lifecycle; they are not a speaker registry.
- Transcript wait has an observation point and a fixed hard deadline; reassessment must not extend it.
- Newly arriving speech must retain its own applicable transcript budget.
- A proposed `COMMIT` annotation is not proof that Engine committed a Turn.
- `TurnRuntime` publishes the accepted `TurnSnapshot`; `_consume_turns()` observes that acknowledgement.
- Advance using the actual committed evidence boundary, not the wall-clock time of acknowledgement.
- Preserve newer/unowned input while retiring the acknowledged input.
- Expired, cancelled-generation and unavailable-evidence proposals may be rejected.
- Engine's `_inputs` tracks processed actions per input for duplicate isolation.
- That action bookkeeping is separate from the authoritative committed Turn stream.

When altering this path, check transcript-first/audio-first ordering, cancellation and delayed acknowledgement.
Also check natural pauses, mixed speakers, anonymous segments and overlapping media times.

## 11. Participants, identity and private context

Keep transport identity, perceived entities, session participants and durable users distinct.

| Concept | Owner / entry |
| --- | --- |
| Device/transport connection | RTC/Host adaptation into Core session contracts. |
| Speaker/face evidence | [Persona processors](avatar-plugins/perception/avatar-plugins-persona/alphaavatar/plugins/persona/processors/). |
| Segment association and readiness | [ParticipantRuntime](avatar-agents/alphaavatar/agents/runtime/modules/participants/). |
| Accepted participant/user binding | [SessionRuntime](avatar-core/alphaavatar/core/session/). |
| Actor resolution at Turn admission | `AvatarEngine._decision_actors()`; current-identity projection uses `ParticipantRuntime.project_turn()`. |
| Snapshot-scoped Persona access | [persona/runtime.py](avatar-plugins/perception/avatar-plugins-persona/alphaavatar/plugins/persona/runtime.py). |

- A microphone, device or primary participant alone does not prove who spoke a segment.
- A local entity label does not independently establish a durable user identity.
- One temporal Turn can contain multiple actors or unattributed segments.
- Conflicting evidence must not grant a private user identity.
- Association readiness, identity inference and attribute extraction have separate completion times.
- Start independent annotation work early; await only dependencies required by the consuming operation.
- An async wait can suspend a task while other input tasks continue.
- Keep unrelated attribute extraction off the dependency path required for Turn admission.
- Preserve committed historical ownership when a later identity binding changes.
- Do not replace missing authorization with primary-user or device-based fallback.

For identifier lifetimes and initialization entry points, read [identifiers-zh.md](docs/identifiers-zh.md).

## 12. Context, history and model input

Context owns query preparation and canonical history.
Engine does not assemble prompts; Provider does not own conversational history.

| Concern | Entry |
| --- | --- |
| Query preparation and captured state | [context/manager.py](avatar-plugins/foundation/avatar-plugins-context/alphaavatar/plugins/context/manager.py). |
| Input construction | [context/builder/](avatar-plugins/foundation/avatar-plugins-context/alphaavatar/plugins/context/builder/). |
| Canonical user/assistant/tool history | [context/history/](avatar-plugins/foundation/avatar-plugins-context/alphaavatar/plugins/context/history/). |
| Request-local history projection | [context/compressor/](avatar-plugins/foundation/avatar-plugins-context/alphaavatar/plugins/context/compressor/). |
| Public Context contracts | [agents/avatar/context/](avatar-agents/alphaavatar/agents/avatar/context/). |

- Save the Builder-produced user message as the canonical historical message.
- Preserve its captured media and input structure across later annotations.
- Do not rewrite stored history to reflect a later identity or interpretation.
- Request-local compression/projection must not mutate canonical history.
- Runtime context describes the current query and is not canonical historical tool activity.
- Capture state and capabilities consistently for a query; avoid per-step prefix rewriting.
- Keep typed text and speech transcript rendering distinguishable.
- A transcript failure notice remains associated with the affected input segments.
- Historical notices must not be treated as new current user instructions.
- Private Memory/Persona reads use the applicable accepted identity and ownership checks.
- Tool results settling late keep their original execution and historical ownership.

When context changes, inspect both the first model request and the next Turn's reused history.
Do not infer the current contract from older README phrases such as “bounded history”.

## 13. Loop, Provider and tools

The foreground path is Engine → Loop → Context/Provider/capabilities → OutputRuntime.

| Concern | Owner / implementation |
| --- | --- |
| Model/tool execution | [Loop plugin](avatar-plugins/foundation/avatar-plugins-loop/alphaavatar/plugins/loop/). |
| Shared clients and structured tasks | [Provider plugin](avatar-plugins/foundation/avatar-plugins-provider/alphaavatar/plugins/provider/). |
| Streaming backend contracts | [agents/avatar/provider/](avatar-agents/alphaavatar/agents/avatar/provider/). |
| Native capability registration/invocation | [runtime/capability/](avatar-agents/alphaavatar/agents/runtime/capability/). |
| External tool implementations | [tools plugins](avatar-plugins/tools/). |

- A Run can contain multiple model requests and tool calls.
- Keep `input_id`, `turn_id`, `run_id`, request IDs and tool `call_id` distinct.
- Pair tool results with the original call; do not use a tool name as the correlation key.
- Capability discovery/registration does not itself authorize execution.
- Use the active operation's policy and authorizer; do not assume all operations are read-only.
- Structured-task and native streaming backends have different capabilities.
- Provider sharing does not make every backend suitable for the realtime Loop.
- Keep SDK response mapping and errors in the appropriate provider adapter.
- Publish canonical records through the owning Loop/output contracts.
- Do not replay state-changing model/tool work automatically after connection or worker failure.

Follow the selected implementation instead of adding model-specific inference inside MCP.

## 14. Output, synthesis and playback

Core `EnvOutput` is producer content; `OutputEvent` adds publication identity and timing.
Router synthesizes/synchronizes speech; RTC delivers media and reports playback progress.

| Surface | Purpose |
| --- | --- |
| `OutputRuntime.stream` | Realtime delivery and presentation. |
| `OutputRuntime.records` | Canonical batches consumed independently by History/Memory. |
| `OutputRuntime.execution` | Execution facts for Status and diagnostics. |
| Output scope | Owning context, Turn and optional Run. |
| Output identity | Content identity qualified by lane/scope. |
| Text/audio alignment | Correlation and revision of synthesis/playback timing. |

- Record admission, database persistence and remote playback are separate facts.
- Text completion, audio completion and source completion are separate stages.
- Generation completion does not revoke still-playing audio.
- Explicit interruption targets the identities resolved when the interrupt is admitted.
- Late callbacks must not retarget an interruption to a newer Run.
- Keep synthesis at its native production pace; caption delivery must not slow PCM production.
- Distinguish estimated alignment from measured audio/playback timing.
- Preserve already emitted caption prefixes during final timing correction.
- Keep terminal publication and shutdown ownership explicit.
- One subscriber seeing a final event does not prove all publication/cleanup is finished.

See [Core output](avatar-core/alphaavatar/core/output/),
[Router speech](avatar-plugins/perception/avatar-plugins-router/alphaavatar/plugins/router/processors/speech/),
and [RTC audio](avatar-rtc/alphaavatar/rtc/livekit/audio/).

## 15. Memory and Persona persistence

Memory and Persona consume shared runtime facts and retain their own business/storage ownership.
Their persistence rules do not belong in Core or Engine.

| Concern | Implementation |
| --- | --- |
| Memory orchestration | [memory/runtime.py](avatar-plugins/perception/avatar-plugins-memory/alphaavatar/plugins/memory/runtime.py). |
| Conversation/environment/retrieval processors | [memory/processors/](avatar-plugins/perception/avatar-plugins-memory/alphaavatar/plugins/memory/processors/). |
| SQLite authority and projections | [memory/storage/](avatar-plugins/perception/avatar-plugins-memory/alphaavatar/plugins/memory/storage/). |
| Public Memory schemas | [agents/memory/](avatar-agents/alphaavatar/agents/memory/). |
| Identity/profile orchestration | [Persona plugin](avatar-plugins/perception/avatar-plugins-persona/alphaavatar/plugins/persona/). |

- Consume committed Turns and canonical output records using independent consumer progress.
- Preserve original owners, participants, context and source references.
- Distinguish authoritative records from vector, graph and Markdown projections.
- Keep graph/source namespaces explicit when integrating multiple producers.
- Persist through the existing commit/outbox/storage contracts.
- A failed batch restored after newer arrivals must not overwrite those newer arrivals.
- Passive retrieval supplies contextual clues; active retrieval can request more precise evidence.
- User rebinding does not authorize moving or exposing another user's stored data.
- Historical context stays frozen while current identity-dependent state can change.
- Session end is one finalization boundary, not a universal persistence trigger.
- Keep processor-specific lifecycle, configuration, prompts and providers together.

Read the [Memory README](avatar-plugins/perception/avatar-plugins-memory/README.md)
and [Persona README](avatar-plugins/perception/avatar-plugins-persona/README.md), then verify current source.

## 16. Inference runners and model assets

InferenceRuntime owns worker processes and the shared inference socket.
InferenceExecutor owns client connections, while Host supervises the service.

| Concern | Entry |
| --- | --- |
| Runner interface | [inference/runner.py](avatar-agents/alphaavatar/agents/runtime/inference/runner.py). |
| Worker selection, service and pools | [runtime/inference/](avatar-agents/alphaavatar/agents/runtime/inference/). |
| Plugin-specific runner plan | The selected plugin's factory and `inference.py`. |
| Model resolution and offline policy | [Model cache guide](docs/models-cache-layout.md). |

- Select runners from validated active configuration.
- Resolve/download model files in the appropriate initialization path, not module import.
- Initialize selected models before accepting their realtime requests.
- Keep model implementation in its owning plugin; streams remain with consuming processors.
- Separate client availability, queue waiting and request execution deadlines.
- Respect configured concurrency and worker limits rather than adding unbounded tasks.
- Runner initialization/failure must not reject unrelated healthy methods globally.
- Cancellation must settle the owned request and its resources.
- Caller cancellation and worker-process termination are different operations.
- Avoid creating a second process owner while adding supervision or diagnostics.
- Offline mode must report missing required assets accurately.

`ALPHAAVATAR_MODEL_OFFLINE=1` disables model-asset downloads; remote provider calls still follow their own configuration.
Do not describe fake-runner success as real model or remote-service validation.

## 17. Application paths and stored data

There are two roots: the application home and each Avatar's resolved workspace.
Path construction and filesystem mutation have separate owners.

| Concern | Entry |
| --- | --- |
| Application home, settings, configuration and shared cache | [Host ApplicationPaths](avatar-host/alphaavatar/host/workspace/application.py). |
| Avatar workspace, users and session paths | [Agents WorkspacePaths](avatar-agents/alphaavatar/agents/workspace/paths.py). |
| Explicit application directory preparation | [Host workspace operations](avatar-host/alphaavatar/host/workspace/operations.py). |
| Explicit Avatar directory preparation | [Agents workspace operations](avatar-agents/alphaavatar/agents/workspace/operations.py). |
| User-facing layout and backup guidance | [Workspace guide](docs/avatar-workspace-layout.md). |

- Host selects the platform data directory by default; `ALPHAAVATAR_HOME` or YAML `application.home` can select another absolute root.
- Preserve the documented configuration/settings/cache/Avatar organization.
- An Avatar workspace separates environment, users, graph, data, logs and caches.
- Session paths retain the SessionRuntime creation date used by the path/context contracts.
- Avoid resolving the Avatar ID into an already resolved workspace a second time.
- Preserve logical IDs separately from filesystem-safe path keys.
- Validate paths without implicitly creating directories or changing global environment state.
- Keep caches, credentials and generated runtime data out of source changes.

Use the linked path APIs instead of duplicating directory construction in a plugin.

## 18. Coding rules

The authoritative ordering reference is [docs/coding-conventions.md](docs/coding-conventions.md).
Use `core/perception/runtime.py` and the named Memory modules there as style examples.

- Target the repository's Python version and Ruff configuration, currently Python 3.13 and Ruff 0.12.9.
- Prefer direct, concise code that matches neighboring modules.
- Keep a reasonable expression on one line; the formatter targets 100 columns.
- Split when width, nesting or readability justifies it.
- Keep useful comments focused on ownership, invariants and non-obvious ordering.
- Put processor-specific business logic with its owner.
- Extract a helper/class when it has a coherent responsibility, not just to shorten a file.
- Use current contracts directly during rapid iteration unless the task requires compatibility.
- Migrate consumers, tests, examples and diagnostics when a public contract changes.
- Do not maintain old aliases or a parallel legacy path by default.

Module/class organization:

1. Existing license header, future import, then standard/third-party/absolute/relative imports.
2. Type-only dependencies under `TYPE_CHECKING` where appropriate.
3. Private module helpers/classes before their public consumers.
4. Class docstring, grouped constants, constructor, properties and static methods.
5. Private methods before their callers; mutually recursive methods are the exception.
6. Functional areas may use standalone strings such as `"""Input event operations"""`.
7. Within each area, keep private helpers before public entry points.
8. Lifecycle implementations before lifecycle entry points, with lifecycle at the end.

Naming and async ownership:

- Methods requiring an already-held lock end with `_locked`.
- Background consumer loops use `_consume_*`.
- Task completion callbacks use `_*_done` or `_observe`.
- Track created tasks and observe their terminal exceptions.
- Avoid blocking I/O or heavy model work on the event loop.
- Use existing runners or an appropriate asynchronous/off-thread boundary.
- Bound queues, pending records and retained context according to their contracts.
- Release owned resources on success, failure, cancellation and partial startup.

Do not reorder untouched modules solely to satisfy an unrelated style cleanup.

## 19. Development and validation

Use [CONTRIBUTING.md](CONTRIBUTING.md) for the complete workflow.
Use `.python-version`, `pyproject.toml` and `uv.lock` rather than inventing dependency versions.

Set up the Python workspace:

```bash
uv sync --all-packages --locked
uv pip check --python .venv/bin/python
```

Check structure, lock and code style:

```bash
uv lock --check
uv run --no-sync python scripts/quality/check_workspace.py
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
git diff --check
```

Run the relevant deterministic offline tests first:

```bash
PYTHONDONTWRITEBYTECODE=1 ALPHAAVATAR_MODEL_OFFLINE=1 \
  uv run --no-sync pytest -p no:cacheprovider path/to/affected/tests
```

Use the same environment for the full suite when the change crosses contracts:

```bash
PYTHONDONTWRITEBYTECODE=1 ALPHAAVATAR_MODEL_OFFLINE=1 \
  uv run --no-sync pytest -p no:cacheprovider
```

Replace the example test path with the actual owning package's tests.
Large samples are opt-in through the existing `large_samples` marker/fixtures.
`alphaavatar test` is a planned CLI command, not a substitute for pytest today.
Run pre-commit checks where appropriate; hooks may modify files, so inspect their output.
The whole-workspace CI also checks formatting and installation beyond changed files.
Check that validation did not leave bytecode, caches or other unexpected checkout changes.
An isolated interpreter may ignore environment-based bytecode controls; pass flags at its owning boundary.
If a check is blocked by the environment, report the exact command/stage and remaining coverage.
Do not weaken assertions or strict validation merely to make a renamed API pass old tests.

## 20. Packaging, releases and real-service validation

Read [CONTRIBUTING.md](CONTRIBUTING.md) before changing package or release automation.

- Package layout changes affect workspace membership, sources, dependencies and release package lists.
- Keep `uv.lock` consistent and inspect dependency changes.
- Each distribution owns its README, version, resources and Apache license copy.
- Build with the lock-constrained workflow; check produced metadata with Twine.
- `--no-sources` checks build independence from editable workspace overrides.
- A built wheel does not prove complete installation or service operation.
- A GitHub Release does not prove that every workspace package exists on PyPI.
- Tag-triggered GitHub Release creation and manual package-index publishing are separate workflows.
- Linux package building/installing is separate from an editable source checkout.
- Keep installed-package validation separate from source-tree tests.

Real-service checks use the effective configuration and existing external-service controls.
Doctor may download models or call remote providers when authorized/configured.
Do not run paid experiments as an incidental consequence of import or documentation checks.
Separate offline stubs, actual model inference, remote services, RTC and renderer validation.
Record sample/configuration identity, failures and warm/first-run conditions when reporting timings.
Do not claim speech completion correctness from a small latency-only sample.

Workflow entry points: [.github/workflows/](.github/workflows/),
[packaging/linux/](packaging/linux/) and [scripts/maintenance/](scripts/maintenance/).

## 21. Common change routes

Use this table to avoid starting in a convenient but non-owning module.

| Task | Follow this route |
| --- | --- |
| CLI argument/help/default | Host `cli/` → command implementation → `docs/cli/` → CLI tests. |
| Bundle/profile option | Host `configs/` → Agents config → plugin validation → example/CLI docs. |
| Startup or subprocess cleanup | Host application/execution/processes → lifecycle owner → lifecycle tests. |
| RTC input/output | RTC adapter → injected Core contract → Host assembly → adapter tests. |
| VAD or segment timing | Voice VAD → Router audio activity → source/segment evidence → timing tests. |
| STT request/terminal state | Voice STT → Router transcription → turn-taking deadline/admission → Doctor. |
| Natural pause or premature Turn | Turn-taking window/evidence/model/policy → Engine admission → multi-segment tests. |
| Speaker readiness/private identity | Persona processor → ParticipantRuntime → Session binding → Turn actor/context checks. |
| Prompt/history/media replay | Context manager/builder/history → Provider model input → next-query history tests. |
| Tool authorization/result ownership | Capability registry → Loop tools/execution → provider records → identity checks. |
| TTS/caption interruption | Router speech → OutputRuntime exact scope → RTC playback feedback → close/cancel tests. |
| Memory durability/retrieval | Memory processor → storage commit/outbox → projection → ownership filters. |
| Runner concurrency/timeout | Plugin selection → InferenceRuntime/pool/executor → runner ownership tests. |
| Model download/offline behavior | Plugin model spec → existing cache resolver → offline tests and cache guide. |
| Doctor metric | Producer trace boundary → Core trace schema → Host measurement → compare script/tests/docs. |
| New plugin/package | Plugin boundary guide → entry points/factory → metadata/workspace/lock → catalog/tests. |
| Future App presentation | App design/implementation → Core/RTC delivery contract → frontend checks. |
| Deployment or install | Host/setup or packaging → `docs/DEPLOY.md` / setup guide → installation validation. |

Search with `rg` for a contract's constructors, serializers and consumers before renaming it.
When changing trace fields, inspect both producers and offline report reconstruction.
When changing identities, check scopes, persistence and cancellation as well as display labels.

## 22. Documentation index

Every non-log file currently under `docs/` is listed below.
`agent-logs/` is one historical-work category rather than a per-artifact API index.
Keep this table and its Chinese counterpart synchronized when documents are added or moved.

| Document | Purpose / when to read |
| --- | --- |
| [ROADMAP.md](docs/ROADMAP.md) | Development direction and milestone status across runtime, capabilities and clients. |
| [DEPLOY.md](docs/DEPLOY.md) | Linux/source deployment, service configuration, credentials and operating procedures. |
| [coding-conventions.md](docs/coding-conventions.md) | Module/class ordering, functional section strings and method naming. |
| [identifiers-zh.md](docs/identifiers-zh.md) | Identifier meanings, owners, uniqueness/lifetimes, initialization and correlation rules. |
| [avatar-workspace-layout.md](docs/avatar-workspace-layout.md) | Application/Avatar data layout, personal data, logs and backup boundaries. |
| [models-cache-layout.md](docs/models-cache-layout.md) | Model cache ownership, resolution, downloads, offline behavior and cleanup. |
| [bugs-zh.md](docs/bugs-zh.md) | Known defects, fixes and deferred observations; verify status against the current revision. |
| [cli/README.md](docs/cli/README.md) | CLI navigation, available/planned commands, configuration and exit behavior. |
| [cli/config.md](docs/cli/config.md) | Bundle/profile creation and effective configuration inspection/validation. |
| [cli/setup.md](docs/cli/setup.md) | Linux installation environment and selectable capability/dependency setup. |
| [cli/doctor.md](docs/cli/doctor.md) | Static/runtime diagnosis, external-service controls, reports, evidence and timing metrics. |
| [cli/dev.md](docs/cli/dev.md) | Development-mode startup, defaults, logging and supported options. |
| [cli/start.md](docs/cli/start.md) | Service-mode startup, configuration overrides and operating behavior. |
| [cli/test.md](docs/cli/test.md) | Planned Agent capability-test command; not an implemented CLI entry today. |
| [cli/cli.html](docs/cli/cli.html) | Recorded CLI display gallery; illustrative output, not live service or benchmark evidence. |
| [releases/v0.6.1.md](docs/releases/v0.6.1.md) | Review v0.6.1 face recognition, visual identity, speaker-face fusion, and Persona persistence changes. Historical version context. |
| [releases/v0.6.2.md](docs/releases/v0.6.2.md) | Review v0.6.2 unified providers and embeddings, tracing, runtime and multiparticipant foundations, and nested configuration migration. Historical version context. |
| [releases/v0.6.3.md](docs/releases/v0.6.3.md) | Review v0.6.3 graph-aware Memory, node mentions and aliases, session-local entity keys, and LanceDB retrieval. Historical version context. |
| [releases/v0.6.4.md](docs/releases/v0.6.4.md) | Review v0.6.4 Core perception streams, shared payloads and annotations, AvatarRuntime, visual consumers, and online environment memory. Historical version context. |
| [releases/v0.6.5.md](docs/releases/v0.6.5.md) | Review v0.6.5 shared audio, Router VAD/STT, persistent isolated inference processes, and consumer ownership/cursor patterns. Historical version context. |
| [releases/v0.6.6.md](docs/releases/v0.6.6.md) | Review v0.6.6 unified timing and multimodal alignment, immutable Turns, provider-neutral input, Output, and playout-paced transcripts. Historical version context. |
| [releases/v0.6.7.md](docs/releases/v0.6.7.md) | Review v0.6.7 native semantic addressing, conversation focus, Smart Turn, addressing fusion, full-duplex interruption, and exact Turn snapshots. Historical version context. |
| [releases/v0.6.8.md](docs/releases/v0.6.8.md) | Review v0.6.8 native Host/RTC ownership, Foundation and processor plugins, streaming model/tool/voice execution, CPython 3.13, and migration. Historical version context. |
| [agent-logs/](docs/agent-logs/) | Dated records of Claude and other agents' project changes, validation and unresolved work. |

Additional repository entry points:

- [README.md](README.md): product overview, architecture summary, installation and plugin catalog.
- [CONTRIBUTING.md](CONTRIBUTING.md): development environments, checks, packaging and release workflows.
- Package READMEs: local responsibilities, settings and supported integrations.
- [Examples README](examples/README.md): configuration examples; check commands against the current Host CLI.
- Workflow YAML and scripts: executable source of CI/build behavior.

Older docs may retain terminology from an earlier implementation.
Resolve disagreements through the active source/contracts and actual validation, and fix relevant docs with the change.

## 23. Agent work records

`docs/agent-logs/` exists to explain work done on AlphaAvatar by Claude and other coding agents.
Read the relevant task/date rather than loading the complete history into context.

Useful record content:

- Task objective and the source revision reviewed or changed.
- Architecture/implementation decisions and their reasons.
- Changed modules and important contract migrations.
- Validation commands, outcomes and material environment limitations.
- Real-service conditions and concise conclusions when applicable.
- Remaining defects, unresolved questions and the next concrete step.

Link to the owning guide or bug entry rather than duplicating large specifications.
Keep the index at directory level so new dated entries do not require this guide to grow.
Existing experiment dumps are supporting evidence for their recorded runs, not current runtime contracts.
Avoid adding generated scripts, model caches, install trees or bulk raw reports as routine work logs.
Never include credentials, private environment files or unnecessary personal/media content.
Do not silently rewrite old records to make historical results match newer code.
Editing or removing an existing evidence collection is a separate scoped maintenance task.

## 24. Completing a change

Before handing work back, check the actual behavior and the navigation affected by it.

- Keep the implementation within its owning layer and lifecycle.
- Migrate all affected contracts and consumers together.
- Validate cancellation, stale work and cleanup when the change touches asynchronous execution.
- Use meaningful regression checks for behavior; a documentation-only change needs link/path validation.
- Report what ran, what passed and what remains unverified.
- Distinguish installed builds, source tests, remote services and CI for a particular SHA.
- Update relevant examples, documentation and both navigation files after path/contract moves.
- Keep generated runtime files and unrelated edits out of the deliverable.
- Follow the user's requested output format and commit/push scope.

Keep this guide navigational: add durable entry points and ownership rules, not an expanding incident diary.
