# AlphaAvatar Roadmap

[中文](ROADMAP-zh.md)

This file is the single maintained source of the AlphaAvatar Roadmap: what has been delivered,
what is in development and what is planned, by version. [ROADMAP-zh.md](ROADMAP-zh.md) is its
Chinese version and is kept in step with it. The docs site renders its Roadmap page from these
files; agents read them directly. What a version actually shipped is in its
[release notes](releases/), and how the system works today is in the technical documents, such as
the [identifier reference](identifiers-zh.md); this Roadmap links to them and does not replace them.

## Goal

> **Build a universal multimodal personal assistant** capable of recognizing users through streaming voice, text, image, and video input.

> It should possess **self-memory**, **persona awareness**, **autonomous reflection**, **planning ability**, **iterative self-evolution**, and **real-time interaction feedback**.

> The assistant will **seamlessly integrate** with mainstream external tools and personal workspaces to solve practical problems efficiently.

## Reading this Roadmap

- A **milestone** is a version, or one of two groups: `earlier` (delivered through v0.6.5) and
  `backlog` (not scheduled).
- An **item** has a stable ID, `<AREA>-<NN>`. Moving an item to another milestone moves its row;
  its ID stays. IDs are never reused. [Areas](#areas) lists the area codes.
- Three things are recorded separately: an item's **status**, the **milestone** it targets, and
  the milestone's **release** state. Completed items in a version do not mean the version is
  released.
- Dates keep the precision they were recorded with: months for completed items, the GitHub
  Release publication day (UTC) for releases. `—` means none.
- [Planning notes](#planning-notes) describe proposals, not current behavior.

| Item status | Meaning |
| --- | --- |
| `proposed` | Listed, but whether or how it is done is undecided. |
| `planned` | Accepted for its milestone; not started. |
| `in-progress` | Work has started; the notes say where, or that the status is carried over from the earlier Roadmap without re-checking. |
| `implemented` | In the source, with validation still incomplete. |
| `done` | Implemented and validated; for a released milestone, shipped in that release. |

| Release state | Meaning |
| --- | --- |
| `released` | Tagged and published as a GitHub Release, with release notes. |
| `in-development` | A development branch exists; not released. |
| `planned` | Not started. |
| `unscheduled` | Not assigned to a version. |

**Priority** keeps the marks the earlier Roadmap gave its TODO items, `🔸` and `🔹`, as they were
recorded, including for items since moved to a version. That Roadmap did not define them, so they
are not translated into levels. `—` means the item had no mark.

## Timeline

| Milestone | Version | Theme | Release | Released | Release notes |
| --- | --- | --- | --- | --- | --- |
| [`earlier`](#earlier) | v0.1.0–v0.6.5 | Foundations through v0.6.5 | released | 2025-11-13 – 2026-07-25 | Per-item versions not verified |
| [`v0.6.6`](#v0.6.6) | v0.6.6 | Unified timing, multimodal alignment and capability awareness | released | 2026-08-17 | [v0.6.6](releases/v0.6.6.md) |
| [`v0.6.7`](#v0.6.7) | v0.6.7 | Native turn taking, Semantic Addressing and full-duplex interruption | released | 2026-09-05 | [v0.6.7](releases/v0.6.7.md) |
| [`v0.6.8`](#v0.6.8) | v0.6.8 | Native Host, runtime capabilities and realtime voice | released | 2026-10-22 | [v0.6.8](releases/v0.6.8.md) |
| [`v0.6.9`](#v0.6.9) | v0.6.9 | Voice reliability, participant ownership and standalone installation | released | 2026-11-25 | [v0.6.9](releases/v0.6.9.md) |
| [`v0.7.0`](#v0.7.0) | v0.7.0 | Configuration and versions, new Web/App UI, guided setup, docs and Roadmap, Demo stability | in-development | — | Branch `dev/v0.7.0` |
| [`v0.7.1`](#v0.7.1) | v0.7.1 | Tool-layer plugins | planned | — | — |
| [`v0.7.2`](#v0.7.2) | v0.7.2 | Perception plugins and multi-person recognition | planned | — | — |
| [`v0.7.3`](#v0.7.3) | v0.7.3 | WebRTC backend | planned | — | — |
| [`v0.8.0`](#v0.8.0) | v0.8.0 | Avatar execution independent of interaction connections | planned | — | — |
| [`v0.8.1`](#v0.8.1) | v0.8.1 | Configuration initialization; remaining scope open | planned | — | — |
| [`backlog`](#backlog) | — | Long-term, unscheduled | unscheduled | — | — |

## Upcoming

<a id="v0.7.0"></a>
### v0.7.0 · Configuration and versions, new Web/App UI, guided setup, docs and Roadmap, Demo stability

- **Release:** in-development · Branch `dev/v0.7.0`
- **Summary:** One configuration and version source across CLI, Web and App; the new UI in Web and App, with guided install, configuration and start; organized documentation and this Roadmap on the docs site; a stable, repeatable Demo.
- **Order:** configuration and versions → Figma, Web and App UI → guided install, configuration and start → documentation and Roadmap → Demo stability and acceptance.
- **Acceptance path:** open Web or App → guided Host install or connection → configure graphically and save → Doctor → start and interact → see status, locate problems and complete updates.
- **Open:** which platforms the App delivers first, and their local or remote Host connections (APP-01); whether a TUI or agent-driven configuration is offered (APP-02).

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `CFG-01` | **One configuration experience** — Build on bundles, profiles and the Host configuration service so CLI, Web and App configure the same way, with one set of docs. Graphical entry points reuse the existing configuration, validation and credential logic; editing configuration files by hand remains supported. | planned | — | — | Tracks O-37 (`consolidation.item_ops` has no runtime effect); its fix is not decided |
| `CFG-02` | **Version management** — One version source, a build identity, and component versions shown to users, so Python packages, the CLI, Web/App and release artifacts stop repeating version upkeep. | planned | — | — | Related: RUN-22 |
| `UI-01` | **Product UI from the new Figma design** — Unify Web and App visual rules and interaction flows from the new Figma design: first use, configuration, connection, runtime status and troubleshooting. | planned | — | — | Design status is not recorded here |
| `WEB-09` | **New UI in AlphaAvatar-web** — Bring the new UI to AlphaAvatar-web; improve the Demo's connection, voice and video interaction, status display and error feedback. | planned | — | — | Separate repository. Related: WEB-07 |
| `APP-01` | **New UI in avatar-app and first platforms** — Bring the new UI to `avatar-app`; decide the first delivery scope across Web, desktop and iOS, and which local or remote Host connections each platform supports. | planned | — | — | `avatar-app` holds only a README today; platform scope is open |
| `APP-02` | **Guided install, configuration and start** — Guide users from the App through installing or connecting a Host, first configuration, credentials, Doctor, start and stop, and upgrades. The graphical flow comes first. | planned | — | — | A TUI and agent-driven configuration are to be evaluated as optional entry points |
| `DOC-01` | **Documentation organization** — Organize documentation across AlphaAvatar, AlphaAvatar-web and AlphaAvatar-docs with one navigation for installation, configuration, architecture, development and deployment; update README, screenshots and examples from the UI as actually delivered. | in-progress | — | — | This repository: [docs manifest](manifest.yaml) and this Roadmap. The other repositories and the UI-based updates are not started |
| `DOC-02` | **Roadmap page** — A Roadmap page on the docs site, with the repository Roadmap (English and Chinese) as its only source and a clear entry in the repository, showing planned, in-progress and completed work the same way. | in-progress | — | — | The repository Roadmap is restructured for that; the site page is not implemented |
| `OPS-01` | **Demo deployment** — Repeatable Demo deployment with configuration, health checks, logs, updates and failure recovery, stable enough for daily demos. | planned | — | — | — |
| `QA-02` | **Agent-assisted testing for v0.7.0** — Extend agent-based (Claude, Codex and others) defect finding and testing to the new UI, configuration generation, Host connection, guided installation and Demo deployment, throughout development and acceptance. | planned | — | — | — |

<a id="v0.7.1"></a>
### v0.7.1 · Tool-layer plugins

- **Release:** planned
- **Summary:** Improve the tool-layer plugins: DeepResearch, MCP and other agents as sub-agents. Whether RAG, a Files plugin and a streaming voice survey are included is still open.
- **Focus:** the tool-layer plugins.
- **Open:** whether RAG work is included (RAG-13), whether RAG and Files are one plugin (FIL-01), and whether the streaming voice and embedding survey is included (VOI-02).

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `DRS-07` | **Improve DeepResearch** — Improve the DeepResearch plugin. | planned | — | — | Scope not defined; candidates DRS-03 to DRS-06 |
| `RAG-13` | **Improve RAG** — Improve the RAG plugin. | proposed | — | — | Inclusion undecided; candidates RAG-07 to RAG-12 |
| `FIL-01` | **Files plugin** — Introduce a Files plugin. | proposed | — | — | Whether RAG and Files become one plugin is open |
| `MCP-15` | **Improve MCP** — Improve the MCP plugin. | planned | — | — | Scope not defined; candidates MCP-11 to MCP-14 |
| `AGX-01` | **Other agents as sub-agents** — Let AlphaAvatar attach other agents, such as Claude Code, Codex or a DeepSeek harness, as sub-agents. | planned | — | — | — |
| `VOI-02` | **Streaming STT, TTS and embeddings survey** — Survey streaming STT and TTS from more providers and improve embeddings. | proposed | — | — | Inclusion undecided. See [rolling-commit STT](#pn-rolling-stt). Related: RUN-23 |
| `QA-03` | **Agent-assisted testing for v0.7.1** — Agent-based defect finding and testing. | planned | — | — | — |

<a id="v0.7.2"></a>
### v0.7.2 · Perception plugins and multi-person recognition

- **Release:** planned
- **Summary:** Perception plugins for several people: multimodal Memory and Persona updates, finer memory ownership, multi-person recall and addressing, and identity from face and voice together.
- **Focus:** perception plugins and recognizing several people.
- **Depends on:** multi-person recall (MEM-36) and addressing input (RTR-22) use the identity results of the Persona items.

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `MEM-31` | **Multimodal Memory and Persona updates** — Memory and Persona updates take multimodal input. | planned | — | — | Related: MEM-28 |
| `MEM-32` | **Fine-grained memory ownership** — Link each Memory update to its message, Turn and `user_id`, so a memory item's owner is decided item by item. | planned | — | — | Related: O-29 (mixed batches), MEM-26, MEM-30 |
| `MEM-33` | **Avatar memory for the environment** — Add an Avatar memory type for ENV memory. | planned | — | — | Today ENV memory is owned by the primary participant and the Avatar and read through its user owners |
| `MEM-34` | **Experience memory for tools** — Add a second, experience level to tool memory. | planned | — | — | — |
| `MEM-35` | **Richer memory source references** — Extend memory items' `source_ref`, which today records messages, tool calls and results, and runtime events. | planned | — | — | The schema also defines perception source, segment and entity kinds, which nothing writes yet. Related: MEM-22, MEM-31 |
| `MEM-36` | **Passive recall with several people** — Passive Memory recall that accounts for several people in the conversation. | planned | — | — | See [multi-person passive recall](#pn-memory-recall) |
| `PER-29` | **Configurable profile detail** — Make Persona profile detail configurable, for example in YAML; without configuration the current detail is used. | planned | — | — | Earlier planned for v0.6.10 |
| `PER-30` | **Multi-angle face vectors** — Keep independent face vectors for different angles. | planned | — | — | — |
| `PER-31` | **Tracking thresholds with a buffer band** — Add buffer thresholds (three bands) and a policy to Persona tracking to prevent false matches. | planned | — | — | Related: O-24, KD-41 |
| `PER-32` | **Uncertain speakers and several people in one segment** — Add an uncertainty notice that asks when speaker matching falls between thresholds, and handle several people speaking within one segment. | planned | — | — | Related: O-25 |
| `CTX-19` | **XML input with user IDs** — Messages given to the Avatar, Persona and Memory providers use XML and carry `user_id`. | planned | — | — | — |
| `PER-33` | **Profiler by current user** — The Persona profiler extracts by the `user_id` of the current cache. | planned | — | — | — |
| `RTR-22` | **Multi-person addressing input** — Format Semantic Addressing input by the multi-person recognition result, in XML. | planned | — | — | Related: O-25 (addressing evidence in multi-person scenes) |
| `PER-34` | **Audio-visual binding** — Recognize which visible person is speaking by binding voice and face. | planned | — | — | Related: PER-28, VIS-11 |
| `PER-35` | **Identity recognition policy** — Update the identity recognition policy. | planned | — | — | Related: AGT-12, PER-25 |
| `PER-36` | **Persona in Markdown** — Show Persona information as Markdown. | planned | — | — | Related: PER-21 |
| `QA-04` | **Agent-assisted testing for v0.7.2** — Agent-based defect finding and testing. | planned | — | — | — |

<a id="v0.7.3"></a>
### v0.7.3 · WebRTC backend

- **Release:** planned
- **Summary:** A WebRTC backend beside the existing LiveKit backend. Whether it needs a LiveKit server, which library it uses and how signalling works are still open.
- **Open:** the WebRTC backend's boundary; see RTC-10.

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `RTC-10` | **WebRTC backend** — Implement a WebRTC backend beside the existing LiveKit backend. | planned | — | — | LiveKit, the implemented backend, is itself WebRTC-based. The new backend's boundary is not decided: whether it needs a LiveKit server, which library (aiortc was named earlier), and how signalling works. Related: RTC-08 |

<a id="v0.8.0"></a>
### v0.8.0 · Avatar execution independent of interaction connections

- **Release:** planned
- **Summary:** Avatar execution separate from interaction connections: episodes, persistent Context, pause and resume, wake and sleep, recovery after shutdown, and a Reflection plugin.
- **Focus:** separate the lifecycle of an interaction connection from the Avatar's execution lifecycle.
- **Background:** see [execution lifecycle](#pn-execution-lifecycle) for what exists today and the proposed semantics.

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `EXE-01` | **Execution lifecycle separate from connections** — Give the Avatar an execution lifecycle independent of interaction connections. | planned | — | — | See [execution lifecycle](#pn-execution-lifecycle). Related: RUN-19, RUN-28 |
| `EXE-02` | **Episode management** — Manage Episodes as the Avatar's active running periods. | planned | — | — | `episode_id` exists today without this lifecycle |
| `EXE-03` | **Persistent Context** — Contexts that persist across sessions and Episodes. | planned | — | — | `context_id` exists today; it does not persist work |
| `EXE-04` | **Execution correlation and execution-level run_id** — Correlate executions across Contexts and Episodes; extend `run_id` to execution state, trace, retry and recovery. | planned | — | — | `run_id` already identifies one Loop run; an earlier discussion placed this in 0.7.1 |
| `EXE-05` | **Pause and resume** — Pause and resume tasks. | planned | — | — | — |
| `EXE-06` | **Basic wake and sleep** — Basic automatic wake and sleep. | planned | — | — | Host: sleep/wake is not implemented |
| `EXE-07` | **Dream** — Dream scheduling, background reflection and consolidation across cycles, and preemption on wake-up. | planned | — | — | Related: RFL-02 |
| `RFL-01` | **Reflection plugin** — Introduce the Reflection plugin. | planned | 🔸 | — | Earlier backlog wording: Build Reflection Plugin Alpha for summarizing recent memories, tool results, failures, repeated user needs, and behavioral improvements |
| `EXE-08` | **Session start wait** — A new session should not keep the user waiting while it is created. | planned | — | — | Each dispatch now starts an execution process that assembles the session; Doctor reports it as `session_ready`. The LiveKit Agents room path in the original note was removed in v0.6.8 |
| `EXE-09` | **Recovery after shutdown** — Recover data after the Host stops. | planned | — | — | Persistent execution recovery is not implemented |
| `QA-05` | **Agent-assisted testing for v0.8.0** — Agent-based defect finding and testing. | planned | — | — | — |

<a id="v0.8.1"></a>
### v0.8.1 · Configuration initialization; remaining scope open

- **Release:** planned
- **Summary:** Configuration initialization: init_config validated the way STT settings are. The rest of the version is not decided.
- **Open:** the rest of this version's scope is not decided.

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `CFG-03` | **init_config validation like STT** — Improve how `avatar-agents` validates `init_config`, as the STT configuration does. | planned | — | — | Related: O-10 (STT model checked at its field), O-27 |

## Released

<a id="v0.6.9"></a>
### v0.6.9 · Voice reliability, participant ownership and standalone installation

- **Release:** released · 2026-11-25 · [v0.6.9](releases/v0.6.9.md)
- **Summary:** Reliable speech timing and turn taking, participants and their data owned per person, and a standalone Linux package with setup, upgrade, cleanup and Doctor.
- **Order:** speech timing and association evidence → configuration service and CLI → runner parallelism and stress validation → installation, upgrade, cleanup and Doctor.
- **Acceptance path:** clean Linux install → interactive CLI configuration → Doctor run and exported report → start, a real LiveKit call and a normal stop (accepted by the maintainer) → upgrade between two v0.6.9 builds → the current environment stays usable when preparation fails → safe cleanup of old environments.
- **Setup flow:** capabilities → provider and model → credentials → summary and install confirmation → install dependencies, check, enable the bundle → result and next steps.
- **Version plan, as recorded, and its items:**
  - Speech terminal states, cancellation and late results; speech timing and association evidence; TTS speech rate → RTR-14, VOI-01
  - Memory: a failed batch no longer overwrites newer batches; passive recall supplies clues for later active recall → MEM-18
  - User resolution and data ownership for one or several people; `ParticipantRuntime`; `SessionRuntime` in Core; workspace paths in Agents, application paths in Host; unified IDs and docs → AGT-11, AGT-16, AGT-17
  - Persona recognizes several faces and speakers; perceived entities, session participants and durable users associated one way → PER-20
  - Runner inputs configured explicitly, without globals → RUN-15
  - Configurable runner parallelism with multi-voice, queue-pressure and cancellation tests and metrics → RUN-15, RUN-29
  - Voice capability hints for the Agent; Context plugin structure and prompt rendering → CTX-18
  - Turn taking and addressing accumulate uncommitted input up to the committed Turn, not per segment or speaker; three labels; explicit HOLD, uncertainty timeouts and notices → RTR-13
  - Memory identity binding and retrieval fixes → MEM-18
  - New speaker-vector model, short-segment handling, speaker and face vector updates and storage, per-model voiceprints, matching, tracking and cache de-duplication → PER-20
  - Simpler logic; identity strings and ID contracts unified; architecture and identifier docs → AGT-17
  - Standalone `alphaavatar` CLI and Linux package → RUN-17
  - Host configuration service, profiles and bundles, interactive Setup and credential storage → RUN-16
  - Transactional upgrade and separate cleanup → RUN-17
  - Doctor checks and reports → RUN-18
  - Agent-based development review and regression, with the deterministic tests needed → QA-01
  - Stress tests extended to long runs, cancellation, queue backlog and varied voice input; whether to offer `alphaavatar test` decided separately → RUN-29, QA-06

#### Agent foundations

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `AGT-11` | Added `ParticipantRuntime`, which reads a Turn's participants from its input whenever they are needed and keeps settled speech and face associations for the whole session; private Memory and Persona reads use the accepted identity. | done | — | 2026-11 | Notes: Participants, Identity and Persona |
| `AGT-16` | **Session and path ownership** — `SessionRuntime` moved to Core; Avatar workspace paths owned by Agents, application and platform paths by Host. | done | — | — | Not itemized in the notes; present at the v0.6.9 tag and absent at v0.6.8 |
| `AGT-17` | **Identifier contracts** — Identity strings and ID contracts unified and documented in the identifier reference. | done | — | — | Not itemized in the notes; [identifiers-zh.md](identifiers-zh.md) first appears at the v0.6.9 tag |

#### Prompt and context

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `CTX-18` | **Voice hints and Context structure** — Voice hints for the Agent; Context plugin structure and prompt rendering. | done | — | — | Not itemized in the notes; between the v0.6.8 and v0.6.9 tags the Context plugin gained model guidance for `<speech>`, `<unavailable_speech>` and speech and uncertainty notices |

#### Runtime and Host

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `RUN-15` | **Configurable Runner Workers** — Runners take explicit launch inputs; replicable runners (Silero VAD, Smart Turn v3) run several worker processes, with bounded per-method queues, separate deadlines, bounded restarts without replay and per-method health metrics. | done | — | 2026-11 | Notes: Inference Runners, Parallelism and Metrics |
| `RUN-16` | **Bundles, Profiles and Credentials** — Commented profiles from complete templates, `config init` and `config check`, interactive and unattended Setup, and stored credentials kept apart from configuration. | done | — | 2026-11 | Notes: Configuration, Credentials and Interactive Setup |
| `RUN-17` | **Linux Package, Upgrade and Cleanup** — A Linux x86_64 package with its own CPython 3.13, an installer that sets PATH and offers Setup, transactional forward upgrade (no rollback or downgrade) and cleanup of unused builds. | done | — | 2026-11 | Notes: Standalone CLI, Linux Package, Upgrade and Cleanup |
| `RUN-18` | **Doctor Diagnosis and Metrics** — Static checks and an authorized runtime diagnosis on fixed speech and image samples, with lost-sentence attribution, stage latency, runner queue figures and credential-free text/JSON reports. | done | — | 2026-11 | Notes: Doctor and CLI Display |
| `RUN-29` | **Stress and soak validation** — Long-running, cancellation, queue backlog and multi-voice stress tests on model-free stand-in runners. | done | — | — | Notes: Validation (synthetic stress and soak tests) |

#### Interaction Router

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `RTR-13` | **Utterance Input Window** — One open input window across pauses, anonymous segments and speaker labels; explicit HOLD reasons, bounded uncertainty waits with notices, and progress only on committed Turns. | done | — | 2026-11 | Notes: Turn Taking and Addressing Across an Utterance |
| `RTR-14` | **Transcript Terminal States and Deadlines** — One terminal state per STT segment; a late final joins its Turn until a hard deadline, after which the Turn commits with a notice; a bounded segment-to-Turn correlation trace. | done | — | 2026-11 | Notes: Speech Transcription States, Late Results and Correlation |

#### Memory

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `MEM-18` | **Owner-based Retrieval and Batch Ownership** — Retrieval reads memories by type and owners; mixed batches keep their verified owners; a failed ENV batch retries only its own range; passive retrieval is time-bounded. | done | — | 2026-11 | Notes: Memory Ownership, Recovery, Retrieval and Embedding Spaces |
| `MEM-19` | **Embedding-space Records** — Each text-vector store records the embedding model that made it; another model is refused when the Host opens the store, before anything changes. Setup checks ahead only existing local LanceDB records; Qdrant and the actual vector size are checked as the store opens. | done | — | 2026-11 | Notes: Memory Ownership, Recovery, Retrieval and Embedding Spaces |

#### Persona

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `PER-20` | **CAM++ Speaker Vectors and Session Entities** — CAM++ zh-en ONNX speaker vectors, one voice or face entity per session across sources, nearest-first multi-face association, short-speech carry-over and weighted stored-vector updates. | done | — | 2026-11 | Notes: Participants, Identity and Persona |

#### Quality and process

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `QA-01` | **Agent-assisted review and regression** — Development review and regression with coding agents, with the deterministic tests they need. | done | — | — | Work records under `docs/agent-logs/` |

#### Voice providers

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `VOI-01` | **TTS speech rate** — Synthesized speech rate fixed. | done | — | — | Not itemized in the notes; between the v0.6.8 and v0.6.9 tags the OpenAI and Voice.ai TTS implementations gained a validated `speed` setting |

<a id="v0.6.8"></a>
### v0.6.8 · Native Host, runtime capabilities and realtime voice

- **Release:** released · 2026-10-22 · [v0.6.8](releases/v0.6.8.md)
- **Summary:** A native Host and Loop replace livekit.agents, capabilities become a runtime system, plugins form Foundation, Perception and Tools layers, and speech and captions stream in sync.
- **Version plan, as recorded, and its items:**
  - Persona split into processors with their own lifecycles; business logic moved from Agents into the plugin, Agents keeps the abstractions → PER-18
  - Memory split into processors with their own lifecycles; memory notes, object IDs and storage refactored → MEM-16, MEM-17
  - Unified workspace → RUN-24
  - Capabilities upgraded from prompt metadata to a runtime capability system → RUN-12
  - Turn runtime stream drives Turn-level consumers → CORE-12
  - Persona configuration and providers placed per processor, as in Memory → PER-18
  - Router `addressing` and `turn_taking` moved under processors, with per-processor configuration → RTR-11
  - Plugin registration (module and runtime plugins) and model download at runner initialization → RUN-25, PER-19
  - Model download code and folders standardized → RUN-25
  - `avatar-plugins` in three layers; Foundation provides shared components; README and release notes updated → RUN-26, RUN-13
  - LiveKit RTC moved to `avatar-rtc`; Context became its own plugin → RTC-05, RUN-13
  - `livekit.agents` removed: unified tool and capability registration, Provider as a plugin, one model input/output structure for structured and streaming output → RUN-11, RUN-12, CTX-10
  - Logging improved → RUN-27
  - `pyproject.toml` structure, Python 3.13 and Ruff checks → RUN-14

#### Core runtime contracts

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `CORE-12` | **Committed Turn Event Stream** — Added authoritative committed-turn publication with consumer-specific cursors, distinct from transient perception observations and model Run identity. | done | — | 2026-10 | Notes: Runtime Capabilities and Committed Turns |
| `CORE-13` | **Canonical Output and Delivery Boundaries** — Distinguished execution signals, canonical model/tool records, and user-facing output delivery, with exact interruptions and bounded delivery state. | done | — | 2026-10 | Notes: Runtime Capabilities and Committed Turns |

#### RTC

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `RTC-05` | **Standalone RTC Package** — Moved LiveKit media adapters to `avatar-rtc`, leaving application ownership with the Host and Core media contracts transport-independent. | done | — | 2026-10 | Notes: Native Host and RTC Ownership |
| `RTC-06` | **Native Media and Transcript Delivery** — Added native text, audio, status and transcript adapters with async lifecycle, playback-paced subtitles, interrupt isolation and exact output identity. | done | — | 2026-10 | Notes: Realtime Speech, Commentary, and Transcript Delivery |

#### Prompt and context

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `CTX-10` | **Query-scoped Context and Native Continuations** — Captures the turn's State and immutable generation prefix once; subsequent model/tool steps continue without silently changing the original perception boundary. | done | — | 2026-10 | Notes: Native Model, Provider, Context, and Tool Execution |
| `CTX-11` | **Spoken-first Answer and Commentary Guidance** — Selects natural conversational replies when audio output is active and supports optional, user-visible, task-specific pre-tool commentary without exposing private reasoning. | done | — | 2026-10 | Notes: Realtime Speech, Commentary, and Transcript Delivery |

#### Runtime and Host

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `RUN-11` | **Native Application Host** — `avatar-host` owns the unified CLI, application services, process supervision, managed executions, admission/settlement, and RTC session attachment lifecycle. | done | — | 2026-10 | Notes: Native Host and RTC Ownership |
| `RUN-12` | **Native Loop and Runtime Capabilities** — Removed SDK foreground execution, introduced callable capability bindings, validated native provider streaming, tool policies, and authoritative model/tool records. | done | — | 2026-10 | Notes: Runtime Capabilities and Committed Turns; Native Model, Provider, Context, and Tool Execution |
| `RUN-13` | **Processor-owned Foundation Services** — Context, Loop, Provider and Voice provide shared runtime services while consuming plugins retain their own business logic and lifecycle. | done | — | 2026-10 | Notes: Three-layer Plugin Workspace and Model Initialization |
| `RUN-14` | **Python 3.13 Toolchain** — Standardized Python 3.13 package metadata, workspace lock, Ruff/pre-commit and CI build/install/adapter gates. | done | — | 2026-10 | Notes: Python 3.13, Packaging, and Quality |
| `RUN-24` | **Unified workspace layout** — One workspace layout for environment data, users, graphs, Memory records, sessions, indexes, logs and caches. | done | — | — | Notes: Workspace, Logging, and Diagnostics |
| `RUN-25` | **Plugin registration and runner-time model resolution** — `AvatarModulePlugin` registration separated from runtime plugin instances; the pre-download step removed, enabled runners resolve their models during initialization; model code and cache folders standardized. | done | — | — | Notes: Runtime Capabilities and Committed Turns; Three-layer Plugin Workspace and Model Initialization |
| `RUN-26` | **Three-layer plugin workspace** — `avatar-plugins` organized into Foundation, Perception and Tools. | done | — | — | Notes: Three-layer Plugin Workspace and Model Initialization |
| `RUN-27` | **Structured Host logs** — Compact Host banner and consistent time, level, source, process and message formatting. | done | — | — | Notes: Workspace, Logging, and Diagnostics |
| `RUN-28` | **AvatarRuntime create and close** — `AvatarRuntime.create()` composes a runtime from activated resources; `aclose()` closes it. | done | — | — | Not itemized in the notes; introduced in `a92ff4e1` (2026-09-27), before the v0.6.8 tag. Related: EXE-01 |

#### Status

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `STS-06` | **Native Execution and Delivery Status** — Distinguishes model/tool progress, local output delivery failure, interruption and readiness; generic thinking narration is optional rather than always spoken. | done | — | 2026-10 | Notes: Realtime Speech, Commentary, and Transcript Delivery |

#### Interaction Router

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `RTR-11` | **Processor-owned Router Configuration** — Addressing and Turn Taking moved under processor-owned directories and configuration, alongside independently managed speech processors. | done | — | 2026-10 | Notes: Highlights (processor-owned Router) |
| `RTR-12` | **Streaming Speech and Caption Synchronization** — Added bounded PCM synthesis and prefetch, improved speech segmentation, playback-paced transcript release, and independent async audio/caption transport. | done | — | 2026-10 | Notes: Realtime Speech, Commentary, and Transcript Delivery |

#### Memory

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `MEM-16` | **Processor-owned Memory Runtime** — Independently manages Conversation, Tool, Environment and Retrieval capabilities while consuming authoritative committed turns and canonical model/tool records. | done | — | 2026-10 | Notes: Processor-owned Persona and Memory |
| `MEM-17` | **Unified Memory Storage and Exports** — Separates the global primary Memory records from owner/episode/context Markdown projections, derived indexes and graph namespaces under one workspace layout. | done | — | 2026-10 | Notes: Workspace, Logging, and Diagnostics |

#### Persona

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `PER-18` | **Processor-owned Persona Runtime** — Moved concrete Profiler, Speaker and Face business logic, configuration, providers and lifecycle to the Persona plugin; Agents retains abstract contracts. | done | — | 2026-10 | Notes: Processor-owned Persona and Memory |
| `PER-19` | **On-demand Model Initialization** — Standardized processor model cache/resolution and initializes only enabled runners, without a separate model-download command. | done | — | 2026-10 | Notes: Three-layer Plugin Workspace and Model Initialization |

#### MCP

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `MCP-07` | **MCP Tool Search Filters** — `tool_search` supports dynamic `top_k`, server filters, and tool category filters (`read` / `write` / `unknown` from MCP `readOnlyHint`), applied as LanceDB prefilters. | done | — | 2026-10 | Not itemized in the notes; merged before the v0.6.8 tag (#11) |
| `MCP-08` | **MCP Compact/Raw Output Modes** — `tool_call` supports `output_mode="compact"` (truncated results, no echoed args) and `"raw"` (default) to control long tool results. | done | — | 2026-10 | Not itemized in the notes; merged before the v0.6.8 tag (#11) |
| `MCP-09` | **MCP `refresh_tools`** — Adds a `refresh_tools` operation that reloads MCP tools and re-syncs the LanceDB index without restarting the worker. | done | — | 2026-10 | Not itemized in the notes; merged before the v0.6.8 tag (#12) |
| `MCP-10` | **MCP Log Redaction** — Redacts tokens, API keys, passwords, authorization headers, and URL credentials from MCP logs, including `httpx` / `mcp.client.*` loggers. | done | — | 2026-10 | Not itemized in the notes; merged before the v0.6.8 tag (#13) |

<a id="v0.6.7"></a>
### v0.6.7 · Native turn taking, Semantic Addressing and full-duplex interruption

- **Release:** released · 2026-09-05 · [v0.6.7](releases/v0.6.7.md)
- **Summary:** Native turn taking: multimodal reply decisions replace LiveKit's turn detection, with Semantic Addressing, conversation focus and full-duplex interruption.
- **Version plan, as recorded, and its items:**
  - Multimodal reply decisions; LiveKit turn detection removed → RTR-05, RTR-10, RUN-09
  - VAD processor in its own module → RTR-21
  - `interaction` renamed to `router` → RUN-10

#### Core runtime contracts

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `CORE-10` | **Typed Perception Identity & Annotation Events** — Promoted annotations into ordered Perception Events and added typed source, source-generation, segment, entity, and transport-participant references for exact multimodal lineage. | done | — | 2026-09 | Notes: Perception Events and Typed Lineage |
| `CORE-11` | **Exact Decision-bound Perception Snapshots** — Added historical perception capture at an exact Perception Event sequence so committed turns cannot include observations arriving after the turn decision. | done | — | 2026-09 | Notes: Exact Turn Snapshots |

#### Runtime and Host

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `RUN-09` | **Native User-turn Authority** — Added annotation-driven AvatarTurnController, explicit Router COMMIT / INTERRUPT decisions, and exact immutable turn snapshots independent of LiveKit text turn detection. | done | — | 2026-09 | Notes: Multimodal Turn Taking |
| `RUN-10` | **Router Contract Separation** — Moved reusable interaction-routing contracts under alphaavatar.agents.router, separating public Router schemas and model interfaces from concrete plugin implementations. | done | — | 2026-09 | Notes: Router Architecture (`alphaavatar.agents.router`) |

#### Interaction Router

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `RTR-05` | **Multimodal Turn-Taking Runtime** — Added revisioned speaker-scoped turn candidates, immutable evidence snapshots, Smart Turn speech completion assessment, deterministic turn policy, and explicit HOLD, COMMIT, PASSIVE, INTERRUPT, and CANCEL decisions. | done | — | 2026-09 | Notes: Multimodal Turn Taking |
| `RTR-06` | **Semantic Addressing** — Replaced acoustic invocation with transcript-based Semantic Addressing using Avatar identities, recent conversation context, and model-independent local inference contracts. | done | — | 2026-09 | Notes: Semantic Addressing |
| `RTR-07` | **Conversation Focus** — Added per-speaker conversation focus where explicit AVATAR / NON_AVATAR evidence updates focus and UNKNOWN preserves the existing state. | done | — | 2026-09 | Notes: Conversation Focus |
| `RTR-08` | **Addressing Fusion** — Added typed Semantic, Conversation Focus, Visual, and future explicit addressing evidence with conservative conflict resolution and evidence provenance. | done | — | 2026-09 | Notes: Addressing Fusion (What's New) |
| `RTR-09` | **Full-Duplex Turn Interruption** — Separated speech-start interruption from speech completion so Avatar output can stop immediately while addressing and final turn decisions continue asynchronously. | done | — | 2026-09 | Notes: Full-Duplex Interruption |
| `RTR-10` | **LiveKit Turn Detection Removal** — Removed LiveKit text turn detection and the legacy acoustic invocation path from AlphaAvatar-owned user-turn decisions. | done | — | 2026-09 | Notes: Removed |
| `RTR-21` | **Audio activity processor module** — VAD processing moved to its own Router processor module. | done | — | — | Notes: Router Architecture (`AudioActivityProcessor`) |

#### Persona

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `PER-17` | **Speaker Model Packaging & Validation** — Migrated speaker-vector and speaker-attribute ONNX models into dedicated versioned Hugging Face repositories, corrected speaker-attribute preprocessing and gender-label ordering, and separated model caches by purpose. | done | — | 2026-09 | Notes: Persona Model Packaging |

<a id="v0.6.6"></a>
### v0.6.6 · Unified timing, multimodal alignment and capability awareness

- **Release:** released · 2026-08-17 · [v0.6.6](releases/v0.6.6.md)
- **Summary:** Unified timing aligns input across modalities, the Avatar's prompt says what it can do, ENV Memory takes audio, and the Qdrant and LanceDB stores behave the same.
- **Version plan, as recorded, and its items:**
  - Fix related bugs → GEN-01
  - Temporal alignment and prompt improvements → CORE-06, CTX-06, CTX-07
  - ENV Memory takes audio and adapts its update boundaries → MEM-12, MEM-13
  - Memory Qdrant and LanceDB behave the same → MEM-14
  - Internal capability descriptions in the Avatar prompt, so it knows what it can do → CTX-08, RUN-08, PER-15
  - Core stream buffers were too short and forgot early input → CORE-07
  - Session storage grouped by creation date → AGT-10
  - Stream and observation kinds as enums and schemas in `avatar-core` → CORE-08

#### Core runtime contracts

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `CORE-06` | **Unified Temporal Runtime** — Added `RuntimeClock`, `RuntimeTime`, `RuntimeTimeRange`, ordered perception events, source-state tracking, immutable perception cutoffs, and shared multimodal temporal alignment. | done | — | 2026-08 | Notes: time-aligned multimodal runtime |
| `CORE-07` | **Time-based Perception Retention** — Replaced modality-owned fixed stream sizes with configurable retention derived from producer cadence, retention horizon, and safety headroom. | done | — | 2026-08 | Notes: reworked perception stream retention |
| `CORE-08` | **Typed Perception Contracts v2** — Stream, observation, event, and media-source kinds now use explicit enums and schemas across the perception runtime. | done | — | 2026-08 | Notes: schema-ized and enum-ized perception contracts |
| `CORE-09` | **Transport-independent Output Runtime** — Added AlphaAvatar-owned output streams, output timelines, delivery state, interruption semantics, and playback-aware output tracking. | done | — | 2026-08 | Notes: transport-independent `OutputRuntime` |

#### Agent foundations

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `AGT-08` | Added explicit separation between participant transport identity, session-scoped participant ID, temporary user identity, and Persona-resolved user identity. | done | — | 2026-08 | Notes: participant transport identity separated from logical user identity |
| `AGT-09` | Added application-, participant-, and runtime-time separation so persistence, user timezone context, and realtime temporal alignment use independent time semantics. | done | — | 2026-08 | Notes: runtime, application and participant time separated |
| `AGT-10` | Added creation-date session storage using `sessions/YYYY-MM-DD/<session_id>/` while keeping the session creation date immutable across long-running sessions. | done | — | 2026-08 | Notes: sessions grouped by creation date |

#### Prompt and context

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `CTX-06` | **Provider-neutral Model Input** — Added AlphaAvatar-owned text, image, audio, temporal, function-call, and function-output model input structures with input-type-specific renderers and provider-boundary conversion. | done | — | 2026-08 | Notes: provider-neutral model input and prompt pipeline |
| `CTX-07` | **Structured Temporal Input Context** — Current multimodal input is rendered as a time-aligned structured timeline containing speech, visual evidence, source-state transitions, pauses, perception gaps, and direct inputs. | done | — | 2026-08 | Notes: structured `alphaavatar_input` timeline |
| `CTX-08` | **Runtime Capability Awareness** — Added typed internal capability metadata for Memory and Persona and injects currently enabled capabilities into the stable Avatar system prompt. | done | — | 2026-08 | Notes: internal runtime capability descriptions |
| `CTX-09` | **Participant-scoped Time Context** — Runtime context can represent independent current-time and timezone views for multiple participants without coupling persistence timestamps to user-facing time. | done | — | 2026-08 | Notes: participant-scoped current-time snapshots |

#### Runtime and Host

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `RUN-06` | **Immutable Turn Snapshots** — Added turn-scoped immutable perception snapshots so retries and tool follow-ups reuse the original input boundary instead of observing later realtime state. | done | — | 2026-08 | Notes: immutable turn snapshots |
| `RUN-07` | **Staged Concurrent Lifecycle** — Runtime plugins now start and stop in dependency-safe stages, execute independent lifecycle work concurrently, roll back failed startup, and stop producers before consumers. | done | — | 2026-08 | Notes: staged concurrent runtime lifecycle |
| `RUN-08` | **Runtime Capability Metadata** — Added reusable capability contracts that allow internal runtime components to expose model-facing semantic capabilities independently of concrete plugin implementations. | done | — | 2026-08 | Notes: `AvatarCapability` metadata |

#### Vision

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `VIS-06` | **Stateless Visual Selection** — Removed the stateful Sampled Frame Vision runtime and replaced it with pure `VisualFrameSelector` selection over immutable aligned perception. | done | — | 2026-08 | Notes: `VisualFrameSelector` |
| `VIS-07` | **Temporal Visual Grounding** — Visual evidence now preserves temporal slices and authoritative start/end source state so historical frames cannot be mistaken for a currently active camera or screen. | done | — | 2026-08 | Notes: start and end source states retained |

#### Interaction Router

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `RTR-04` | **Output Processing Runtime** — Extended the Router into speech synthesis and playback-aware transcript synchronization while preserving transport-independent cancellation and output ordering. | done | — | 2026-08 | Notes: speech synthesis and transcript synchronization in output routing |

#### Memory

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `MEM-12` | **Audiovisual ENV Memory** — ENV Memory now combines sampled visual observations with continuous raw environmental audio while excluding speech-derived and direct-user input streams from environment evidence. | done | — | 2026-08 | Notes: audiovisual ENV Memory |
| `MEM-13` | **Adaptive ENV Memory Scheduling** — Periodic ENV updates defer boundaries during active speech, commit at complete speech boundaries when possible, and enforce a bounded maximum defer duration. | done | — | 2026-08 | Notes: speech-aware ENV boundaries with a maximum defer |
| `MEM-14` | **Memory VDB Backend Parity** — Unified LanceDB and Qdrant Memory runner behavior and persistence contracts. | done | — | 2026-08 | Not itemized in the notes. The version plan lists it under v0.6.6; the Qdrant runner changed between the v0.6.5 and v0.6.6 tags |
| `MEM-15` | **Structured Memory Timestamps** — Memory items now persist structured `created_at` timestamps instead of user-facing session-time strings, enabling reliable ordering across sessions and timezones. | done | — | 2026-08 | Notes: structured timestamps |

#### Persona

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `PER-14` | **Structured Persona Time Semantics** — Persona runtime state and profile fields now keep structured login/update datetimes while user-facing rendering converts them into each participant's current timezone. | done | — | 2026-08 | Notes: structured login and update datetimes |
| `PER-15` | **Persona Capability Metadata** — Profile, speaker-recognition, and face-recognition capabilities are declared at the abstract component level and automatically exposed to the Avatar system prompt. | done | — | 2026-08 | Notes: Persona capabilities |
| `PER-16` | **Participant-aware Identity Foundation** — Persona identity resolution updates resolved user identity while preserving stable participant identity and shared runtime references. | done | — | 2026-08 | Notes: participant identity separated from user identity |

#### General

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `GEN-01` | **v0.6.6 bug fixes** — Fixes delivered with v0.6.6, not itemized. | done | — | — | From the version plan; not itemized in the notes |

## Earlier history

<a id="earlier"></a>
### Through v0.6.5

- **Release:** released · 2025-11-13 – 2026-07-25
- **Summary:** Foundations delivered from v0.1.0 to v0.6.5, by area and month; which release shipped each item was not verified.
- Items delivered before v0.6.6, by area and month. Their release versions were not verified; see the [release notes](releases/) and the README's release history.

#### Core runtime contracts

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `CORE-01` | **Environment Observation Model** — Added transport-agnostic `EnvObservation` and `EnvAnnotation` models for video, audio, screen, event, and future multimodal inputs. | done | — | 2026-07 | — |
| `CORE-02` | **Multi-representation Media Payload** — Added `MediaPayload`, `PayloadFormat`, `PayloadView`, and AlphaAvatar-owned video-frame representations without RTC-specific types. | done | — | 2026-07 | — |
| `CORE-03` | **Typed Perception Runtime** — Added independent video, audio, screen, event, and annotation streams with consumer-specific cursors. | done | — | 2026-07 | — |
| `CORE-04` | **Shared Timeline and Window Builder** — Added observation–annotation alignment and ordered consumer windows for Persona, Memory, Vision, and future routers. | done | — | 2026-07 | — |
| `CORE-05` | **Shared Audio and Speech Perception** — Added normalized audio observations and a derived speech stream, allowing Router, transcription, speaker recognition, and future audio processors to consume the same source independently. | done | — | 2026-07 | — |

#### RTC

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `RTC-01` | **RTC Adapter Boundary** — RTC-specific media conversion is isolated from `avatar-core`; core observations no longer store LiveKit frame types directly. | done | — | 2026-07 | — |
| `RTC-02` | **LiveKit Video Input Runtime** — LiveKit video frames are normalized into AlphaAvatar media payloads and published once into `PerceptionRuntime`. | done | — | 2026-07 | — |
| `RTC-03` | **Model-bound Frame Conversion** — Generic AlphaAvatar frames are converted back to LiveKit frames only at the LiveKit model adapter boundary. | done | — | 2026-07 | — |
| `RTC-04` | **LiveKit Audio Input Runtime** — LiveKit microphone frames are normalized into AlphaAvatar audio payloads and published once into `PerceptionRuntime.audio`. | done | — | 2026-07 | — |

#### Agent foundations

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `AGT-01` | Developed a context manager to route real-time updated interaction information to plugin models such as memory and persona. | done | — | 2025-10 | — |
| `AGT-02` | Added mutable user-scoped working directory support through `UserPath`, enabling plugins to follow identity changes dynamically. | done | — | 2026-05 | — |
| `AGT-03` | Added temporary-user to real-user identity resolution flow, including deferred temporary directory migration and cleanup at session exit. | done | — | 2026-05 | — |
| `AGT-04` | Added runtime-aware session context construction based on room type, session mode, modality availability, user metadata, and time context. | done | — | 2026-05 | — |
| `AGT-05` | Added LiveKit room binding support for runtime components that need direct room-level access, such as status sinks and data channel publishers. | done | — | 2026-05 | — |
| `AGT-06` | Introduced a unified provider layer for task-based LLM and embedding calls, including structured output, usage normalization, provider tracing, and provider-based Memory / Persona extraction. | done | — | 2026-06 | — |
| `AGT-07` | Refactored runtime and configuration foundations with `SessionRuntime`, `StateRuntime`, participant-aware sessions, nested YAML config, and initial plugin lifecycle boundaries. | done | — | 2026-06 | — |

#### Prompt and context

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `CTX-01` | **System Prompt / Runtime Prompt Split** — Static content such as avatar introduction, interaction method, persona, and global behavior rules is kept in the system prompt for better prefix-cache reuse. | done | — | 2026-05 | — |
| `CTX-02` | **Runtime Context Injection** — Dynamic per-turn information such as memory, current time, plan, reflection, and turn-level behavior rules is injected after the user query. | done | — | 2026-05 | — |
| `CTX-03` | **Synthetic Tool Runtime Context Mode** — Added a model-compatible way to inject runtime context using synthetic tool-call / tool-output frames. | done | — | 2026-05 | — |
| `CTX-04` | **Interaction Method Awareness** — Runtime prompt understands whether the current room supports text, voice, audio output, video input, and video output. | done | — | 2026-05 | — |
| `CTX-05` | **Browser Timezone Integration** — Web demo passes browser timezone, locale, and UTC offset through LiveKit participant metadata so AlphaAvatar can build natural login time context. | done | — | 2026-05 | — |

#### Runtime and Host

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `RUN-01` | **AvatarRuntime Composition** — Added `AvatarRuntime` as the session-scoped composition root for `SessionRuntime`, `StateRuntime`, `PerceptionRuntime`, and `InferenceExecutor`. | done | — | 2026-07 | — |
| `RUN-02` | **Simplified Plugin Lifecycle** — Runtime dependencies are injected during plugin construction, while `on_start()` and `on_stop()` only manage lifecycle work. | done | — | 2026-07 | — |
| `RUN-03` | **Producer / Consumer Orchestration** — Perception consumers start before RTC producers, while producers stop before consumers to preserve clean full-duplex lifecycle boundaries. | done | — | 2026-07 | — |
| `RUN-04` | **AlphaAvatar Inference Runtime** — Added Worker-owned `InferenceRuntime`, session-scoped `InferenceExecutor`, Unix domain socket IPC, and persistent runner processes independent of LiveKit Agent inference internals. | done | — | 2026-07 | — |
| `RUN-05` | **Isolated Inference Runners** — VAD, speaker vector, speaker attributes, face analysis, and all Persona, Memory, and MCP VDB workloads now run in independent persistent processes. | done | — | 2026-07 | — |

#### Vision

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `VIS-01` | **Vision Input Module** — Added a dedicated `avatar/vision` module for real-time visual context handling, session-aware activation, and vision plugin integration. | done | — | 2026-05 | — |
| `VIS-02` | **Sampled Video Frame Support** — Supports sampled-frame visual input from real-time video streams instead of continuously sending every frame to the model. | done | — | 2026-05 | — |
| `VIS-03` | **Runtime Visual Context Injection** — Injects current sampled frames into the temporary model-facing context, strips stale historical visuals, and adds placeholders when needed. | done | — | 2026-05 | — |
| `VIS-04` | **Shared Perception Consumption** — Sampled Frame Vision consumes asynchronous observation windows from `PerceptionRuntime` instead of subscribing to RTC tracks directly. | done | — | 2026-07 | — |
| `VIS-05` | **Late-bound Annotated Frames** — Vision snapshots retain shared observations and resolve annotated frame views when visual context is injected into the model. | done | — | 2026-07 | — |

#### Status

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `STS-01` | **Status Plugin Architecture** — Added a replaceable status plugin with policy, renderer, and sink implementations while keeping the core protocol in `alphaavatar.agents.status`. | done | — | 2026-05 | — |
| `STS-02` | **Intermediate Status Lifecycle** — Added status events such as `READY`, `THINKING`, `TOOL_START`, `TOOL_PROGRESS`, `TOOL_END`, `TOOL_ERROR`, and `FINALIZING` for real-time interaction feedback. | done | — | 2026-05 | — |
| `STS-03` | **LLM + Tool Status Feedback** — Introduced delayed thinking and tool feedback; v0.6.8 preserves status events but defaults generic waiting narration to off in favor of optional model-generated commentary. | done | — | 2026-05 | — |
| `STS-04` | **Template-based Status Renderer** — Moved status response templates out of Python code into language-specific template files selected by `type + source + stage`, with multiple randomized templates. | done | — | 2026-05 | — |
| `STS-05` | **Multi-sink Status Delivery** — Supports logger sink, LiveKit action event sink, and room-type-aware text/voice delivery with interruptible status speech that does not enter chat context. | done | — | 2026-05 | — |

#### Interaction Router

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `RTR-01` | **Interaction Router Runtime** — Added a plugin-based processing runtime between raw perception streams and derived interaction streams. | done | — | 2026-07 | — |
| `RTR-02` | **Audio Activity Processing** — Added AlphaAvatar-native Silero VAD processing with pre-roll, bounded queues, speech boundaries, and publication into `PerceptionRuntime.speech`. | done | — | 2026-07 | — |
| `RTR-03` | **Speech Transcription Processing** — Added `openai_segment` and `openai_realtime` STT paths with normalized transcription events and a temporary LiveKit turn-pipeline bridge. | done | — | 2026-07 | — |

#### Character

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `CHR-01` | Integrated AIRI Live2D into AlphaAvatar. | done | — | 2025-12 | — |

#### Memory

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `MEM-01` | **Automatic Memory Extraction v1** — Built on Memory Client, enabling memory capture and retrieval across Assistant–User, Assistant–Tools, and Assistant self-memory. | done | — | 2025-09 | — |
| `MEM-02` | **Automatic Assistant–Tools Extraction v1** — Added Assistant–Tools memory in user sessions for DeepResearch and RAG plugins. | done | — | 2026-01 | — |
| `MEM-03` | **Automatic Assistant–Tools Extraction v2** — Designed differentiated prompts for self-memory, shared Assistant–User memory, and shared Assistant–Tools memory. | done | — | 2026-04 | — |
| `MEM-04` | **Local Memory Storage and Retrieval** — Supports local memory storage and retrieval through LanceDB. | done | — | 2026-04 | — |
| `MEM-05` | **Runtime Memory Injection** — Memory is treated as dynamic per-turn context instead of static system prompt content to improve prefix-cache hit rate. | done | — | 2026-05 | — |
| `MEM-06` | **Graph-aware Memory Foundation** — Added graph-based memory association across sessions, users, entities, tools, and future multimodal observations. Includes multi-object MemoryItem, session-scoped graph nodes, alias-ready lookup, and LanceDB graph-node retrieval. | done | — | 2026-06 | — |
| `MEM-07` | **Online ENV Memory Extraction** — Added periodic ENV memory extraction from ordered live visual observation windows through configurable multimodal provider tasks. | done | — | 2026-07 | — |
| `MEM-08` | **Annotated Visual Evidence** — ENV extraction prefers annotated JPEG views and falls back to raw visual evidence without persisting runtime frame payloads. | done | — | 2026-07 | — |
| `MEM-09` | **ENV Memory Consolidation** — Added `MemoryType.ENV` updates and final fusion with conversation and tool memory during the session lifecycle. | done | — | 2026-07 | — |
| `MEM-10` | **Asynchronous ENV Scheduler** — Separated fast perception capture and cursor commits from serialized multimodal extraction, with pending-batch merging, bounded retries, and session-stop draining. | done | — | 2026-07 | — |
| `MEM-11` | **Memory VDB Runtime Migration** — Migrated Memory LanceDB and Qdrant workloads from LiveKit’s shared inference executor to dedicated AlphaAvatar runner processes. | done | — | 2026-07 | — |

#### Persona

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `PER-01` | **Automatic User Profile Extraction v1** — Generates personalized, context-aware responses based on conversation history. | done | — | 2025-10 | — |
| `PER-02` | **Speaker Verification** — Added speech-based profiling through speaker vector extraction and identification. | done | — | 2025-11 | — |
| `PER-03` | **Runtime State Tracking** — Added deterministic user runtime state, including current timezone, login time, session ID, room type, last timezone, last login time, and login count. | done | — | 2026-05 | — |
| `PER-04` | **Runtime State Markdown Storage** — Runtime state is stored locally as markdown instead of being mixed into LLM-extracted profile vectors. | done | — | 2026-05 | — |
| `PER-05` | **Temporary Persona Replacement** — Runtime-only temporary persona can be replaced by the resolved real user profile while preserving current session runtime state. | done | — | 2026-05 | — |
| `PER-06` | **Identity-aware UserPath Binding** — Persona local storage follows user identity changes through mutable `UserPath`. | done | — | 2026-05 | — |
| `PER-07` | **Realtime Face Detection** — Added realtime face detection from camera input through the Persona visual identity pipeline. | done | — | 2026-06 | — |
| `PER-08` | **Face-based Identity Support** — Integrated face vectors with Persona identity resolution, local cache matching, and VDB-backed persistence. | done | — | 2026-06 | — |
| `PER-09` | **Perception-based FaceStream** — FaceStream consumes shared visual observations instead of subscribing directly to LiveKit tracks. | done | — | 2026-07 | — |
| `PER-10` | **Face Annotation Rendering** — Face detections are published as `EnvAnnotation` records and rendered into alternate annotated payload views. | done | — | 2026-07 | — |
| `PER-11` | **Perception-based SpeakerStream** — Speaker recognition now consumes routed speech observations from `PerceptionRuntime.speech` instead of depending on LiveKit VAD segmentation. | done | — | 2026-07 | — |
| `PER-12` | **Rolling Speaker Inference** — Added rolling speech windows, configurable inference cadence, reduced speaker-attribute frequency, and latest-window queue behavior. | done | — | 2026-07 | — |
| `PER-13` | **Isolated Persona Inference** — Speaker vector, speaker attributes, face analysis, and Persona VDB operations now run through independent AlphaAvatar inference processes. | done | — | 2026-07 | — |

#### DeepResearch

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `DRS-01` | **Tavily API Integration v1** — Supports fast online retrieval, deep search, scraping, and webpage-to-PDF conversion. | done | — | 2025-12 | — |
| `DRS-02` | **Status-aware DeepResearch Tool** — Emits `TOOL_START` status with optional model-generated monologue and supports `TOOL_ERROR` fallback through ToolBase. | done | — | 2026-05 | — |

#### RAG

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `RAG-01` | **RAG Anything Integration** — Supports query and indexing based on documents and pages from DeepResearch plugin. | done | — | 2026-01 | — |
| `RAG-02` | **UserPath-aware RAG Workspace** — RAG local workspace dynamically follows user identity changes through mutable `UserPath`. | done | — | 2026-05 | — |
| `RAG-03` | **RAG Initialization Waiting** — Added `_ensure_loaded()` so query and indexing wait for RAGAnything initialization. | done | — | 2026-05 | — |
| `RAG-04` | **Temporary + Current RAG Query Support** — Keeps previous temporary RAG instances as fallback after user identity resolution, while new indexing writes to the resolved user workspace. | done | — | 2026-05 | — |
| `RAG-05` | **LLM-friendly RAG Query Output** — RAG query returns structured markdown sections instead of raw JSON for easier LLM consumption. | done | — | 2026-05 | — |
| `RAG-06` | **Status-aware RAG Tool** — Emits `TOOL_START` status with optional model-generated monologue and supports `TOOL_ERROR` fallback through ToolBase. | done | — | 2026-05 | — |

#### MCP

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `MCP-01` | **MCP Host Integration** — Integrated MCP Host as an MCP plugin for AlphaAvatar, supporting MCP registration, tool search, and parallel invocation. | done | — | 2026-02 | — |
| `MCP-02` | **Runner-level MCP Initialization** — Moved costly MCP and retrieval initialization out of per-session work; v0.6.8 runs the selected MCP VDB service through AlphaAvatar-owned inference processes rather than the LiveKit Agents worker. | done | — | 2026-05 | — |
| `MCP-03` | **LanceDB-backed MCP Tool Retrieval** — Stores MCP tool metadata in LanceDB and supports top-k semantic tool search from agent queries. | done | — | 2026-05 | — |
| `MCP-04` | **MCP Tool Runtime Robustness** — Adds stable tool IDs, agent-friendly tool usage hints, argument validation, hybrid reranking, and server reconnect. | done | — | 2026-05 | — |
| `MCP-05` | **Status-aware MCP Tool** — Emits `TOOL_START` status with optional model-generated monologue and supports `TOOL_ERROR` fallback through ToolBase. | done | — | 2026-05 | — |
| `MCP-06` | **MCP VDB Runtime Migration** — Migrated MCP LanceDB and Qdrant retrieval workloads to dedicated AlphaAvatar inference runner processes. | done | — | 2026-07 | — |

#### Web client

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `WEB-01` | **LiveKit Web Demo v1** — Built realtime browser demo with voice, text chat, camera preview, agent audio/video stage, and session controls. | done | — | 2026-04 | — |
| `WEB-02` | **Browser Timezone Metadata** — Sends browser timezone, locale, and UTC offset to AlphaAvatar through participant metadata. | done | — | 2026-05 | — |
| `WEB-03` | **Room / Session Modality Awareness** — Web session metadata helps AlphaAvatar infer available text, voice, and video interaction modes. | done | — | 2026-05 | — |

## Long-term

<a id="backlog"></a>
### Unscheduled

- **Release:** unscheduled
- **Summary:** Directions and work not assigned to a version; the active client direction is AlphaAvatar Web, App and OS.
- Directions and work not assigned to a version. The active client direction is AlphaAvatar Web, App, and OS; third-party messaging bridges are outside the current implementation scope, while external tools and personal-workspace integrations remain part of the project.

#### Core runtime contracts

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `CORE-14` | Add source-aware retention, payload pruning, backpressure, and consumer-lag observability for long-running and multi-source sessions. | in-progress | 🔸 | — | Status carried over from the earlier Roadmap; actual progress not re-checked this round |
| `CORE-15` | Extend temporal alignment to richer multi-source, multi-speaker, annotation-fusion, and long-running event scenarios. | planned | 🔹 | — | — |
| `CORE-16` | Add annotation fusion for face, speaker, object, action, scene, and screen understanding. | planned | 🔹 | — | — |
| `CORE-17` | Add reusable core policies for observation selection, temporal windows, and payload lifecycle management. | planned | 🔹 | — | — |

#### RTC

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `RTC-07` | Extend RTC screen-share and data-channel coverage, frontend compatibility checks, and end-to-end transport recovery tests beyond the current LiveKit adapter set. | in-progress | 🔸 | — | Status carried over from the earlier Roadmap; actual progress not re-checked this round |
| `RTC-08` | Add alternative RTC backends such as native WebRTC, `aiortc`, and custom RTC providers. | planned | 🔹 | — | WebRTC is scheduled as RTC-10 (v0.7.3); other backends stay here |
| `RTC-09` | Add RTC-level reconnect, transport recovery, flow control, and health monitoring. | planned | 🔹 | — | — |

#### Agent foundations

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `AGT-12` | Complete multi-user streaming identity management with participant-level speaker tracking, face tracking, concurrent Persona resolution, conflict handling, and per-user routing. | in-progress | 🔸 | — | Status carried over from the earlier Roadmap; actual progress not re-checked this round. Related: v0.7.2 identity items PER-31, PER-32, PER-34, PER-35 |
| `AGT-13` | Improve provider runtime capabilities with fallback chains, retry policies, cost estimation, provider health checks, and model compatibility validation. | planned | 🔹 | — | — |
| `AGT-14` | Solve the cocktail-party problem for multi-speaker scenarios, including speaker separation, speaker tracking, overlapping speech handling, and per-user context routing. | planned | 🔹 | — | Related: PER-32 (several people in one segment, v0.7.2) |
| `AGT-15` | Add user upload lifecycle management, including temporary session storage, identity-aware persistence, artifact indexing, and cleanup policies. | planned | 🔹 | — | Related: FIL-01 (v0.7.1) |

#### Prompt and context

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `CTX-12` | Add adaptive prompt budgeting and context selection based on modality, model capability, context size, latency target, and active participant. | in-progress | 🔸 | — | Status carried over from the earlier Roadmap; actual progress not re-checked this round |
| `CTX-13` | Evaluate and extend spoken-first style and pre-tool commentary across providers, languages, client modes, and long-running tool workflows. | in-progress | 🔸 | — | Status carried over from the earlier Roadmap; actual progress not re-checked this round |
| `CTX-14` | Add country / location hint support based on browser timezone, locale, and optional IP-based geo hints, while treating them as soft signals. | planned | 🔹 | — | — |
| `CTX-15` | Add runtime context compression to avoid long dynamic prompts when memory, RAG, reflection, and plans become large. | planned | 🔹 | — | — |
| `CTX-16` | Add prompt versioning and prompt evaluation for system prompt, runtime prompt, memory extraction prompt, and persona extraction prompt. | planned | 🔹 | — | — |
| `CTX-17` | Add model-specific prompt adapters for OpenAI, Gemini, Claude, local models, and small edge models. | planned | 🔹 | — | — |

#### Runtime and Host

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `RUN-19` | Complete runtime lifecycle contracts with consistent `aclose`, health checks, explicit resource ownership, worker recovery, and runtime health observability. | planned | 🔹 | — | Related: EXE-01, EXE-09 (v0.8.0) |
| `RUN-20` | Add session replay and audit tooling based on turns, provider traces, memory events, and runtime status events. | planned | 🔹 | — | — |
| `RUN-21` | Add richer error handling and recovery policies across model calls, tool invocation, plugin initialization, native-client adapters, and realtime media streams. | planned | 🔹 | — | — |
| `RUN-22` | Add version control and compatibility checks for each plugin package, provider integration, config schema, and runtime protocol. | planned | 🔹 | — | Related: CFG-02 (v0.7.0) |
| `RUN-23` | Optimize latency across the voice pipeline, provider calls, tool invocation, memory retrieval, RAG, MCP, status feedback, and native-client adapters, starting with streaming transcription, synthesis from the first short sentence, pre-established provider connections and early recall embedding; Doctor measures the current voice stages (v0.6.9). | planned | 🔹 | — | Related: VOI-02 (v0.7.1) |

#### Vision

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `VIS-08` | Improve visual frame sampling policy based on interaction state, user speech, motion, camera activity, and model demand. | in-progress | 🔸 | — | Status carried over from the earlier Roadmap; actual progress not re-checked this round |
| `VIS-09` | Add user-facing visual grounding behavior, such as explicitly stating when the assistant can or cannot see the current camera frame. | in-progress | 🔸 | — | Status carried over from the earlier Roadmap; actual progress not re-checked this round |
| `VIS-10` | Add screen sharing visual input support for debugging, document reading, and workflow assistance. | planned | 🔹 | — | — |
| `VIS-11` | Add multi-user visual scene understanding, including face tracking, active speaker alignment, and per-user context routing. | planned | 🔹 | — | Related: PER-34 (v0.7.2) |
| `VIS-12` | Expand visual-history retrieval with object, event, identity, time-range, screenshot, and whiteboard search. | planned | 🔹 | — | — |
| `VIS-13` | Add visual privacy controls, allowing users to enable, disable, inspect, or discard visual context per session. | planned | 🔹 | — | — |
| `VIS-14` | Add multimodal evaluation for visual grounding accuracy, latency, and hallucination resistance. | planned | 🔹 | — | — |

#### Status

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `STS-07` | Add structured status trace logs showing whether an event was emitted, blocked by policy, rendered, delivered, skipped by sink, or interrupted. | in-progress | 🔸 | — | Status carried over from the earlier Roadmap; actual progress not re-checked this round |
| `STS-08` | Make `TOOL_END` useful for UI action timelines while keeping it silent for text/voice by default. | in-progress | 🔸 | — | Status carried over from the earlier Roadmap; actual progress not re-checked this round |
| `STS-09` | Add weighted status templates so common phrases appear more often while preserving variation. | planned | 🔹 | — | — |
| `STS-10` | Add template variables for safe metadata such as `url_count`, `tool_count`, `document_count`, and `data_source`. | planned | 🔹 | — | — |
| `STS-11` | Add per-user status verbosity preferences, such as quiet, normal, and verbose modes. | planned | 🔹 | — | — |
| `STS-12` | Add status timeline support for frontend UI, including thinking, searching, reading, tool execution, and result organization. | planned | 🔹 | — | — |
| `STS-13` | Add tool progress events for long-running DeepResearch, RAG indexing, and MCP parallel tool execution. | planned | 🔹 | — | — |
| `STS-14` | Add turn-level status metrics such as first-status latency, first-answer latency, tool count, status count, and interruption count. | planned | 🔹 | — | — |

#### Interaction Router

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `RTR-15` | Improve Semantic Addressing accuracy, latency, quantization efficiency, and multi-speaker robustness with stronger local models and task-specific training. | in-progress | 🔸 | — | Status carried over from the earlier Roadmap; actual progress not re-checked this round |
| `RTR-16` | Add concrete visual addressing signals such as gaze, face orientation, gesture, and visual attention on top of the existing visual evidence interface. | in-progress | 🔸 | — | Status carried over from the earlier Roadmap; actual progress not re-checked this round |
| `RTR-17` | Add visual-only proactive turn producers for help requests, unusual events, and environment-driven interaction. | in-progress | 🔸 | — | Status carried over from the earlier Roadmap; actual progress not re-checked this round |
| `RTR-18` | Extend multimodal routing to richer multi-user, shared-microphone, overlapping-speech, and group-conversation scenarios. | planned | 🔹 | — | Related: RTR-22 (v0.7.2) |
| `RTR-19` | Route committed interaction into answer, clarify, tool workflow, status-only, or other behavior paths using higher-level intention and Behavior policy. | planned | 🔹 | — | — |
| `RTR-20` | Select early status feedback based on user intention, task type, interaction mode, and expected latency. | planned | 🔹 | — | — |

#### Character

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `CHR-02` | Improve avatar synchronization between voice output, Live2D motion, facial expression, and conversation state. | planned | 🔹 | — | — |
| `CHR-03` | Connect status events to avatar animation states, such as thinking, searching, listening, speaking, and error recovery. | planned | 🔹 | — | — |
| `CHR-04` | Add persona-aware avatar expression control based on emotion, conversation topic, and user relationship. | planned | 🔹 | — | — |

#### Memory

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `MEM-20` | Improve ENV memory retrieval with object-, event-, identity-, location-, and time-aware visual-history queries. | in-progress | 🔸 | — | Status carried over from the earlier Roadmap; actual progress not re-checked this round |
| `MEM-21` | Refine ENV graph-node extraction so only concrete observed entities become graph anchors. | in-progress | 🔸 | — | Status carried over from the earlier Roadmap; actual progress not re-checked this round |
| `MEM-22` | Expand processor-owned Memory with independently usable graph/temporal retrieval capabilities and richer media/source references. | planned | 🔹 | — | Related: MEM-35 (v0.7.2); also carries the media-history part of the earlier v0.7.2 plan |
| `MEM-23` | Add `node_merge` for graph node canonicalization, including alias conflict handling, duplicate node merging, scoped-local-to-canonical mapping, and optional VDB reindexing. | planned | 🔹 | — | — |
| `MEM-24` | Add cross-window event consolidation and duplicate suppression for long-running sessions. | planned | 🔹 | — | — |
| `MEM-25` | Allow users to actively query, recall, correct, or delete specific memories on demand. | planned | 🔹 | — | — |
| `MEM-26` | Add multi-user memory isolation when multiple users are interacting in the same session. | planned | 🔹 | — | Related: MEM-32, MEM-36 (v0.7.2) |
| `MEM-27` | Extend event-driven memory triggers beyond current periodic/user-turn ENV updates to reflection, planning, behavior adaptation, and status-aware interaction events. | planned | 🔹 | — | — |
| `MEM-28` | Add omni-memory updates from text, voice, images, video, tools, files, and external workspaces. | planned | 🔹 | — | Related: MEM-31 (v0.7.2) |
| `MEM-29` | Expand graph-aware retrieval to richer relationships, temporal events, aliases, and long-term user goals. | planned | 🔹 | — | — |
| `MEM-30` | Add memory confidence, source attribution, and conflict resolution. | planned | 🔹 | — | Related: MEM-32, MEM-35 (v0.7.2) |

#### Persona

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `PER-21` | Support persona visualization interface for profile inspection and correction. | in-progress | 🔸 | — | Status carried over from the earlier Roadmap; actual progress not re-checked this round. Related: PER-36 (v0.7.2) |
| `PER-22` | Add multi-user profile management for concurrent interactions. | in-progress | 🔸 | — | Status carried over from the earlier Roadmap; actual progress not re-checked this round |
| `PER-23` | Add real-time profile retrieval and profile switching during active conversation. | in-progress | 🔸 | — | Status carried over from the earlier Roadmap; actual progress not re-checked this round |
| `PER-24` | Add shared user identity and explicit identity linking across AlphaAvatar Web, App, and OS clients. | planned | 🔹 | — | — |
| `PER-25` | Add user-confirmed identity merge and identity conflict resolution. | planned | 🔹 | — | Related: PER-35 (v0.7.2) |
| `PER-26` | Add persona privacy controls, allowing users to inspect, edit, export, or delete profile fields. | planned | 🔹 | — | — |
| `PER-27` | Add event triggers for profile updates, reflection cycles, and planning refresh. | planned | 🔹 | — | — |
| `PER-28` | Add multi-user face tracking, active speaker alignment, and per-user visual context routing. | planned | 🔹 | — | Related: PER-34 (v0.7.2) |

#### Reflection

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `RFL-02` | Add offline reflection cycles after session exit. | planned | 🔹 | — | Related: EXE-07 (background reflection, v0.8.0) |
| `RFL-03` | Add online lightweight reflection during long sessions. | planned | 🔹 | — | — |
| `RFL-04` | Feed reflection results into memory, behavior, and planning plugins. | planned | 🔹 | — | — |

#### Planning

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `PLN-01` | Build Planning Plugin Alpha based on memory, persona, reflection, reminders, and external tool results. | planned | 🔸 | — | — |
| `PLN-02` | Add short-term task tracking for ongoing user requests. | planned | 🔹 | — | — |
| `PLN-03` | Add long-term goal tracking based on user memory and profile. | planned | 🔹 | — | — |
| `PLN-04` | Integrate planning outputs with Notion, Calendar, Todoist, or other task systems. | planned | 🔹 | — | — |

#### Behavior

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `BHV-01` | Build Behavior Plugin Alpha for response style, workflow selection, tool-use policy, and proactive assistance rules. | planned | 🔸 | — | — |
| `BHV-02` | Add global behavior rules and turn-level behavior rules. | planned | 🔹 | — | — |
| `BHV-03` | Add user-configurable behavior preferences. | planned | 🔹 | — | — |
| `BHV-04` | Add safe fallback behavior when tools fail or runtime context is incomplete. | planned | 🔹 | — | — |

#### World Sandbox

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `SBX-01` | **World Sandbox** — Interact with external virtual environments, code sandboxes, simulated worlds, or apps. | planned | — | — | Earlier a Plan Overview row |

#### DeepResearch

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `DRS-03` | Add richer `TOOL_PROGRESS` updates during long research workflows, such as searching, extracting, reading, and synthesizing. | planned | 🔹 | — | Candidate scope for DRS-07 (v0.7.1) |
| `DRS-04` | Retrieve all accessible webpage links under a specified webpage and store them in a specific folder for RAG indexing. | planned | 🔹 | — | Candidate scope for DRS-07 (v0.7.1) |
| `DRS-05` | Add automatic summary metadata for downloaded pages, PDFs, and search results so memory and RAG can reference them later. | planned | 🔹 | — | Candidate scope for DRS-07 (v0.7.1) |
| `DRS-06` | Make DeepResearch outputs identity-aware through `UserPath`, so downloaded artifacts are stored in the correct user workspace. | planned | 🔹 | — | Candidate scope for DRS-07 (v0.7.1) |

#### RAG

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `RAG-07` | Add robust temp-to-real RAG migration policy after identity resolution. | in-progress | 🔸 | — | Status carried over from the earlier Roadmap; actual progress not re-checked this round. Identity rebinding no longer moves stored data (KD-10); revisit with PER-35. Candidate scope for RAG-13 |
| `RAG-08` | Add richer `TOOL_PROGRESS` updates during indexing, such as parsing, chunking, embedding, saving, and indexing completion. | in-progress | 🔸 | — | Status carried over from the earlier Roadmap; actual progress not re-checked this round. Candidate scope for RAG-13 (v0.7.1) |
| `RAG-09` | Allow folder indexing and workspace-scoped retrieval across different data sources. | planned | 🔹 | — | Candidate scope for RAG-13 or FIL-01 (v0.7.1) |
| `RAG-10` | Add structured metadata for different data sources, including directories, source type, creation time, and user ownership. | planned | 🔹 | — | Candidate scope for RAG-13 or FIL-01 (v0.7.1) |
| `RAG-11` | Add RAG result reranking and answer synthesis across current user RAG, temporary session RAG, and global knowledge. | planned | 🔹 | — | Candidate scope for RAG-13 (v0.7.1) |
| `RAG-12` | Allow AlphaAvatar to index and retrieve pre-written Skills for more efficient command execution. | planned | 🔹 | — | Candidate scope for RAG-13 (v0.7.1) |

#### MCP

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `MCP-11` | Integrate Notion MCP. | in-progress | 🔸 | — | Status carried over from the earlier Roadmap; actual progress not re-checked this round. Candidate scope for MCP-15 (v0.7.1) |
| `MCP-12` | Add richer `TOOL_PROGRESS` updates during parallel MCP execution, including tool count, completed count, failed count, and slow tool detection. | in-progress | 🔸 | — | Status carried over from the earlier Roadmap; actual progress not re-checked this round. Candidate scope for MCP-15 (v0.7.1) |
| `MCP-13` | Support global MCP + user-level MCP routing for OAuth-based tools such as Gmail, Calendar, Todoist, and Notion. | planned | 🔹 | — | Candidate scope for MCP-15 (v0.7.1) |
| `MCP-14` | Add MCP permission model for user-scoped tools and external account authorization. | planned | 🔹 | — | Candidate scope for MCP-15 (v0.7.1) |

#### Web client

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `WEB-04` | Add user-facing persona and memory inspection panels. | in-progress | 🔸 | — | Status carried over from the earlier Roadmap; actual progress not re-checked this round |
| `WEB-05` | Add upload UI for documents, folders, images, and URLs. | planned | 🔹 | — | — |
| `WEB-06` | Add screen sharing and visual grounding support. | planned | 🔹 | — | — |
| `WEB-07` | Add demo session debugging panel for room metadata, participant metadata, agent status, and tool status. | planned | 🔹 | — | Related: WEB-09 (v0.7.0) |
| `WEB-08` | Add user login and persistent identity binding. | planned | 🔹 | — | — |

#### Documentation

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `DOC-03` | **Agents for docs and assets** — Use an agent to manage documentation and draw assets for AlphaAvatar-docs. | in-progress | — | — | A design agent is finishing the docs site design (2026-11) |

#### Quality and process

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `QA-06` | **`alphaavatar test` entry point** — Whether to offer `alphaavatar test` for scenarios and benchmarks. | proposed | — | — | v0.6.9 left this undecided; [cli/test.md](cli/test.md) describes a proposal |
| `QA-07` | **Working with coding agents** — A way of working with agents that keeps construction visible and fast: rigorous, reproducible and explainable work; detailed logs, decisions, states and experiments; conclusions with evidence, no unfounded inference; failures analysed; validation gates; reflection summaries. | proposed | — | — | — |

#### Architecture direction

| ID | Item | Status | Priority | Date | Notes |
| --- | --- | --- | --- | --- | --- |
| `ARCH-01` | **One runtime across devices** — Not a server edition plus a reduced phone edition: one AlphaAvatar runtime negotiates its capabilities from device resources, network and available accelerators. It can run on the device alone, connect to a server for stronger models, and connect several devices that share capabilities. | proposed | — | — | Includes multi-device self-hosting |
| `ARCH-02` | **Runtime state visible to the model** — Runtime state that users can see should in principle be visible to the model as well. | proposed | — | — | — |

## Planning notes

These are proposals recorded with the plan. They are not current behavior and not public
contracts; the current contracts are in the technical documents they link to.

<a id="pn-memory-recall"></a>
### Multi-person passive recall (MEM-36, v0.7.2)

**Today.** Passive recall, for each committed Turn
([Memory README](../avatar-plugins/perception/avatar-plugins-memory/README.md),
[identifier reference §9](identifiers-zh.md)):

1. keeps the Turn's committed transcript text (`snapshot.text`) for its Context;
2. joins the most recent `search_context` user Turns of the same Context, the current one
   included, into one query, keeping at most its last `max_query_chars` characters. These are
   `memory.retrieval` settings whose defaults are 3 Turns and 8192 characters;
3. when the readers can read anything stored, embeds the query once with `embed_query()` and uses
   it for memory and graph candidate search; otherwise skips the embedding (the LanceDB runner
   checks this first);
4. searches the Avatar's memory and the user's memory for a Turn attributed to one user, and the
   Avatar's memory only for a Turn that is unattributed or mixes users;
5. checks the identity again when results return, and keeps only what the readers may read.

**Proposal.** Recall that accounts for several people. The design is open. The plan keeps
these constraints:

- Semantic cues in the query never grant access. When recent Turns hold A's and B's words and
  the current Turn is B's, A's words can shape the query, but A's private memories stay
  unreadable.
- Owner filtering is part of the query, and returned records and identities are checked again.
- "Identity" is the runtime's currently accepted `user_id` and identity revision. It can be a
  temporary identity of a new user, not yet recognized by voice or face.

**Open.** The plan's diagram also filters by scope (owner, current Episode or Context). The
current contract reads by memory type and owners and does not filter by scope
([identifier reference §9](identifiers-zh.md)); whether multi-person recall adds a scope filter
is to be decided. The window figures above are today's defaults, not fixed values of the
proposal.

<a id="pn-execution-lifecycle"></a>
### Execution lifecycle (EXE-01 to EXE-09, v0.8.0)

**Today** ([identifier reference](identifiers-zh.md), [Host README](../avatar-host/README.md)):

- `PerceptionRuntime` is session-scoped and its events carry `session_id`, so today's session
  covers both the interaction connection and the domain where perception and inference run.
  Separating them is the core of EXE-01.
- `avatar_id`, `session_id`, `episode_id`, `context_id` and `parent_context_id` exist. A
  `StateRuntime` gives each execution new `episode_id` and `context_id` values by default; Memory
  scopes reuse them. They do not make work durable or recoverable.
- `run_id` exists and identifies one Loop model/tool run. Host's `execution_id` identifies one
  hosted execution process. An earlier discussion proposed introducing an execution-level
  `run_id` in "0.7.1"; in this plan that is EXE-04, extending the existing field.
- No `dream_id` exists. `MemoryScopeKind.DREAM` is defined; nothing produces it.
- Host supports one attachment per execution; reattachment, persistent execution recovery and
  sleep/wake are not implemented.
- Each dispatch starts an execution process that assembles the session before it is ready
  (EXE-08). The LiveKit Agents room path the original note refers to was removed in v0.6.8.

**Proposed meanings** (not implemented):

| Identifier | Proposed meaning | Lifecycle boundary |
| --- | --- | --- |
| `avatar_id` | The persistent Avatar identity; owner of Avatar-owned memory. | Stable across Episodes, sessions and Contexts. |
| `episode_id` | One active, awake running period of the Avatar. | Not ended directly by one user disconnecting. |
| `session_id` | One interaction connection, such as a realtime room or terminal connection. | Ending the connection does not stop the Avatar. |
| `context_id` | The context of one ongoing piece of work: interaction, task, monitoring, planning. | Can span sessions and Episodes. |
| `run_id` | One actual execution, for execution state, trace, retry and recovery. | Separate from the logical task; one Context can have several runs. |
| `dream_id` | One background reflection or consolidation activity. | Can process several Episodes' material; can be interrupted by wake-up. |

**Rules discussed:**

- Continuing an unfinished task keeps its `context_id` and adds an execution link to the next
  Episode. Deriving a new task from an existing one creates a new `context_id`, linked by
  `parent_context_id` or another explicit source relation. The two are not both "inheriting a
  Context"; otherwise recovery, permissions and history tracking mix.
- An Episode can end when effective interaction has timed out, no accepted input is pending,
  and no work that must continue is short of a safe pause point.
- A monitoring Context waiting for its next scheduled trigger can persist without keeping the
  Episode open. A Context existing does not mean it is running.
- Dream is not bound one-to-one to an Episode ("an Episode ends → a Dream must start → the
  Dream must finish before waking"). It is a configurable background activity that can gather
  material from several Episodes; new effective input takes priority, and Dream pauses or is
  cancelled at a safe boundary.
- Dream writes memories through the normal Memory commit path, keeping original evidence and
  source relations. There is no separate Dream memory source of truth.

<a id="pn-rolling-stt"></a>
### Rolling-commit streaming STT (VOI-02, v0.7.1)

**Today.** The default STT, `openai_segment`, transcribes each complete speech segment after VAD
ends it; `openai_realtime` also exists. Transcription events include `INTERIM_TRANSCRIPT` and
one final per segment ([Voice README](../avatar-plugins/foundation/avatar-plugins-voice/README.md)).

**Proposal** (an older note, kept for VOI-02): while the user keeps speaking, submit
non-overlapping audio chunks on a fixed time window to produce interim transcripts in real
time, ordered, merged and failed per `segment_id` and `chunk_index` (a new field). When the
segment ends, transcribe the whole segment once more to produce its single final transcript,
correcting words lost, repeated or split at chunk boundaries. It would need to cover chunks
returning out of order, a failed chunk, timeout fallback, segment cancellation, duplicate
submission, the final replacing interim results, and latency and accuracy measurements.
Whether to adopt it is undecided.

## Areas

| Code | Area | Scope |
| --- | --- | --- |
| `CORE` | Core runtime contracts | Transport-independent media, perception, time, Turn and output contracts in `avatar-core`. |
| `RTC` | RTC | Transport adapters that consume Core contracts; LiveKit is the implemented backend. |
| `AGT` | Agent foundations | Sessions, participants, identity and time foundations of the Agent runtime. |
| `CTX` | Prompt and context | Query preparation, model input, history and prompt rendering. |
| `RUN` | Runtime and Host | Runtime composition, inference runners, the native Host, packaging and diagnostics. |
| `VIS` | Vision | Visual input selection, grounding and visual history. |
| `STS` | Status | Readiness, model/tool activity and delivery feedback. |
| `RTR` | Interaction Router | Owns realtime speech routing, Semantic Addressing, conversation focus, multimodal turn taking, interruption, speech synthesis, transcript synchronization, and transport-independent interaction decisions. |
| `CHR` | Character | Virtual character presentation. |
| `MEM` | Memory | Conversation, tool and environment memory, storage and retrieval. |
| `PER` | Persona | User profiles, speaker and face recognition, identity continuity. |
| `RFL` | Reflection | Generates metacognitive insights from memory, persona, tool usage, failures, and interaction history. |
| `PLN` | Planning | Generates short-term tasks, long-term plans, reminders, and follow-up actions from memory, reflection, and tool results. |
| `BHV` | Behavior | Controls response style, workflow selection, tool-use policy, and proactive assistance rules. |
| `SBX` | World Sandbox | Enables AlphaAvatar to interact with external virtual environments, code sandboxes, simulated worlds, or apps. |
| `DRS` | DeepResearch | Web research tool plugin. |
| `RAG` | RAG | Document indexing and retrieval tool plugin. |
| `FIL` | Files | A planned files capability; its relation to RAG is open. |
| `MCP` | MCP | MCP server tools: discovery, retrieval and invocation. |
| `AGX` | External agents | Other agents attached to AlphaAvatar as sub-agents. |
| `WEB` | Web client | AlphaAvatar-web and the browser demo. |
| `APP` | App | The `avatar-app` client. |
| `UI` | Product UI | Visual and interaction design shared by Web and App. |
| `CFG` | Configuration and versions | Configuration experience, validation and version management. |
| `DOC` | Documentation | Repository documentation, the docs site and this Roadmap. |
| `OPS` | Deployment and operations | Demo deployment, health, updates and recovery. |
| `QA` | Quality and process | Agent-assisted review and testing, and development principles. |
| `VOI` | Voice providers | Speech recognition, synthesis and embedding providers. |
| `EXE` | Execution lifecycle | Avatar execution independent of interaction connections. |
| `ARCH` | Architecture direction | Cross-cutting principles not yet scheduled. |
| `GEN` | General | Work not tied to one area. |

## Format

For tools that read these files, such as the docs site.

- The [Timeline](#timeline) table, header
  `| Milestone | Version | Theme | Release | Released | Release notes |` (Chinese:
  `| 里程碑 | 版本 | 主题 | 发布 | 发布日期 | Release 文档 |`), lists the milestones in order.
- Milestone sections start with `<a id="<milestone>"></a>` and a `###` heading. Milestones are
  versions (`vX.Y.Z`), `earlier` and `backlog`. Bullets before the first table are details:
  release, order, acceptance path, open questions.
- A milestone's `**Summary:**` bullet (Chinese: `**摘要**：`), right after its release bullet,
  says in at most 240 characters (Chinese: 120) what the milestone is about; the docs site
  shows it on the milestone's card. Both languages give one for the same milestones.
- Item tables have the header `| ID | Item | Status | Priority | Date | Notes |` (Chinese:
  `| ID | 事项 | 状态 | 优先级 | 日期 | 说明 |`). A row belongs to the milestone whose anchor last
  precedes it; `####` area headings only group rows.
- Priority is `🔸`, `🔹` or `—`.
- Status and release values are those in [Reading this Roadmap](#reading-this-roadmap), in
  English in both languages. Dates are `YYYY-MM`, `YYYY-MM-DD`, a range of two days, or `—`.
- Planning notes (`<a id="pn-…"></a>`) are proposals, not current behavior.
- Release notes are separate documents, one per version; the Roadmap links to them and the
  list of releases does not replace it.
- Both language versions hold the same milestones, item IDs, statuses, priorities and dates.
- For a released version, the Timeline's release notes link points to a release notes entry of
  that version in [manifest.yaml](manifest.yaml), whose `release.tag` and `release.published`
  match the Timeline's version and date. Translations of one version's release notes share the
  tag and date. A Roadmap links the release notes in its own language when they exist, otherwise
  those in an existing language. `earlier` summarizes several versions; unreleased milestones
  have no date or release notes.
- `scripts/docs/check_docs.py` checks these rules.
