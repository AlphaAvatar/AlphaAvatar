# `alphaavatar doctor` — System Diagnostics

> **Design specification — planned for AlphaAvatar v0.6.9.** The commands and options on this page are proposed interfaces, **not implemented CLI features**. The current native Host CLI supports `alphaavatar dev`, `alphaavatar start`, `--help`, and `--version`. See the [Host README](../../avatar-host/README.md) for commands available today.

`alphaavatar doctor` is the **system-level, active diagnostic command** for AlphaAvatar. It discovers
the capabilities supported by the current installation, configuration, and device; runs bounded,
representative checks; and explains which part of the system is working, degraded, unavailable, or
untested.

AlphaAvatar is an **omni-modal assistant**, not a voice-only pipeline. Doctor must cover configured
text, audio, video, screen, perception, memory, persona, tools, agent execution, transport, and device
capabilities where meaningful tests are available.

Doctor is **not a log parser**. Health snapshots and historical traces may supplement a diagnosis, but
a passing result must come from an executed check and its assertions, not from matching log strings.

## Doctor, Test, and Check

| Command | Primary question | Behavior |
| --- | --- | --- |
| `alphaavatar doctor` | **Can this configured AlphaAvatar system operate correctly, and what is wrong if it cannot?** | Automatically discovers, selects, and runs representative checks across the enabled system. Reports dependencies, failures, and corrective actions. |
| [`alphaavatar test`](test.md) | **How correct, fast, scalable, and reliable is a specific capability or scenario?** | Runs explicitly selected scenarios and benchmarks with configurable sample counts, load, budgets, and assertions. |
| `alphaavatar check` | **Are configuration, code, dependencies, and contracts valid?** | Performs targeted static/contract checks; optional Claude/Codex analysis is separate from deterministic validation. **Planned**, not documented as an implemented command. |

Doctor and Test must use the **same Probe execution and result contracts**. They differ in selection,
depth, and presentation, not in test implementations.

## Proposed commands

The following examples illustrate the intended user experience. **Do not expect them to work until the
corresponding v0.6.9 features are implemented.**

```bash
# Automatically diagnose the currently selected installation and configuration.
alphaavatar doctor

# List discoverable checks, requirements, and supported execution modes.
alphaavatar doctor --list

# Include bounded local runtime/model checks when their prerequisites are available.
alphaavatar doctor --runtime

# Explicitly opt in to checks requiring real services, networks, or device access.
# The implementation must show the applicable costs, permissions, and data scope.
alphaavatar doctor --live

# Produce a machine-readable report using the same result schema as Test.
alphaavatar doctor --runtime --format json
```

In non-interactive mode, Doctor must never silently prompt, open a browser, request device permission,
download a model, or initiate a paid call. Missing authorization is reported as a skipped or
unavailable check rather than silently bypassed.

## What Doctor examines

Doctor follows the **capability dependency graph**, not a hard-coded audio pipeline. Only installed
and configured capabilities are eligible for relevant runtime checks.

| Area | Example active checks | What the result should establish |
| --- | --- | --- |
| Installation and environment | Python/runtime artifacts, architecture, CPU/GPU visibility, model assets, disk and permissions | The selected deployment can load its declared prerequisites. |
| Configuration and plugins | Strict configuration validation, discovered providers/processors, capability registration | Resolved configuration and plugin contracts are consistent without unintended side effects. |
| Host and Runner | Bounded startup, model initialization, request/response through IPC, cancellation, cleanup | Local execution is reachable, responsive, and correctly owned. |
| Text and Agent Loop | Fixed prompt, stream termination, tool feedback, cancellation | A Turn can complete or cancel with valid canonical output. |
| Audio input | Fixed PCM, VAD, segment boundaries, STT final, source cancellation | Speech events remain ordered and a failed segment cannot block later input. |
| Audio output | Fixed text, TTS PCM generation, source consumption, playout cancellation | First PCM, continuity, and termination are measurable; captions do not gate sound. |
| Image, video, and screen | Fixed image/frame, timestamped frame sequence, missing-frame scenario | Perception preserves modality, source identity, sequence, and cutoff. |
| Multimodal routing | Aligned audio/video evidence, directed/passive examples, interruption | Turn decisions and consumed evidence follow the expected causal order. |
| Memory | Isolated write/recall, passive recall visibility, owner/scope enforcement | Retrieved context is available to the intended Turn and private to the correct scope. |
| Persona | Test-only face/speaker inputs and profile operations | Enabled identity processors satisfy their contracts without changing production profiles. |
| Tools, RAG, and MCP | Declared mock/read-only operations, timeout, refusal, cancellation | Capability policy and tool-result accounting are enforced. |
| RTC and device | Connection, transport framing, audio/video delivery, supported client feedback | Transport stages are measurable; remote device latency is reported only if measured. |
| Cleanup | Cancel pending work; release test-owned resources | A check leaves no leaked test processes, tasks, media streams, or temporary data. |

A missing camera must not fail an audio-only installation. A disabled Memory plugin must not cause
Doctor to create a Memory database or download an embedding model.

## Execution levels and authorization

| Level | Intended coverage | Authorization and side effects |
| --- | --- | --- |
| **Local (default)** | Offline environment checks, validation, deterministic in-memory or temporary-resource probes | No paid APIs; no mutation of real user data; no implicit downloads or hardware permissions. |
| **Runtime (`--runtime`)** | Selected actual local models, Runner IPC, bounded pipeline scenarios | May require installed model assets and local compute; report unavailable prerequisites and resource budgets. |
| **Live (`--live`)** | Actual external providers, remote RTC, hardware/device paths | Explicit opt-in, service/credential requirements, privacy disclosure, time/cost bounds; never assume a real service is free. |

A test requiring microphones, cameras, credentials, write-capable tools, or a remote account must
declare that requirement before it runs. Diagnostic authorization must never grant tool-execution
privileges implicitly.

## System workflow

A Doctor invocation should:

1. **Resolve** the requested configuration and supported deployment target without initializing
   unrelated plugins.
2. **Discover** the diagnostic probes declared by installed capabilities and platform adapters.
3. **Plan** an ordered, bounded suite from prerequisites, permissions, and dependency relationships;
   explain skips.
4. **Execute** isolated tests under explicit time, concurrency, memory, and external-cost budgets.
5. **Assert** observable behavior using typed results from the operation boundaries.
6. **Correlate** failures across relevant stages, including exact Turn, segment, output, and Runner
   identities when available.
7. **Clean up** all test-owned resources and record cleanup failures independently.
8. **Report** actionable findings, unsupported features, coverage gaps, and remediation guidance.

The diagnosis may identify a failing upstream dependency rather than reporting every downstream
capability as independently broken.

## What is measured

Doctor reports a small, useful health/latency summary; it does not attempt to replace a sustained
benchmark. Depending on the selected probes, measurements may include:

- **Startup:** installation verification, model load, Runner readiness, Host readiness, transport
  attachment.
- **Perception:** frame ingestion, dropped frames, audio processing, VAD/end-of-speech, STT final,
  multimodal alignment.
- **Turn and context:** Turn admission/cutoff, passive recall completion and status, context
  readiness.
- **Execution:** model request-to-first-text, total execution, tool latency, timeout and cancellation
  convergence.
- **Output:** TTS request-to-first-PCM, generated PCM duration, local queue underruns, capture time,
  client playout only when feedback exists.
- **Reliability and resources:** task/process leaks, queue occupancy, rejected work, CPU/memory,
  cleanup and timeout outcomes.

Each measurement must specify its **unit and exact start/end boundaries**. A local PCM queue timestamp
is *not* proof of playback on a remote device. A result marked `ready` must not hide whether a
required recall succeeded, returned no matches, timed out, or failed.

A brief Doctor smoke test cannot justify a p99 performance claim. For distributions and comparable
performance targets, use [`alphaavatar test`](test.md).

## Probe and report contract

The eventual implementation should use **versioned, strongly typed schemas**, not runtime log
messages. A Probe declares at minimum:

- Stable probe ID and version, capability domain, prerequisites, platform, supported mode.
- Side-effect classification, expected permissions, network/paid-service use, and isolation
  requirements.
- Input fixture(s), expected assertions, time and resource budgets, cancellation/cleanup contract.
- Stable measurement identifiers, units, observation points, and result semantics.

The report distinguishes **PASS**, **WARN**, **FAIL**, **SKIP**, **UNSUPPORTED**, **INCONCLUSIVE**,
and **ERROR**. `FAIL` means a tested requirement failed; `ERROR` means the diagnostic itself could not
complete reliably. `SKIP` and `UNSUPPORTED` are not successful checks.

### Illustrative terminal report

This is **sample output for the planned interface**, not a result collected from a real installation:

```text
AlphaAvatar Doctor  [local + runtime]
Configuration                 PASS    Valid; 7 processors enabled
Runner / semantic addressing  PASS    6/6 requests completed
Memory / passive recall      PASS    5/5 completed; 1 empty result
Audio / TTS continuity       WARN    1 underrun in 5 synthetic streams
Video / device capture       SKIP    No camera permission requested
RTC / remote playback        SKIP    Live checks not authorized
Test-owned resource cleanup  PASS    No outstanding resources

Summary: 4 PASS, 1 WARN, 2 SKIP
Recommendation: Run `alphaavatar test voice tts --samples 50`
Note: Device playback latency was not measured.
```

Human-readable summaries and optional logs are **views of the typed result**, never the reverse.
Reports must record effective config identity, capability versions, fixture versions, environment
summary, sample counts, failure reasons, skipped coverage, and cleanup results, with secrets and
sensitive user content removed.

## Architectural boundaries

- **Core:** portable Probe/measurement/result contracts where cross-package reuse is necessary.
- **Plugins and platform adapters:** own the checks for their own capabilities, including controlled
  fixtures and assertions.
- **Host:** selects and orchestrates probes, applies budgets/authorization, aggregates and exports
  reports, and owns the CLI entry point.
- **App and future device clients:** display results and provide device-side measurements without
  duplicating Host diagnostic semantics.
- **InputTrace:** remains bounded evidence for input and Turn lineage; it is not repurposed as a
  system-wide log parser or database.

Do not add processor-private stores or create a second persistence system for diagnostics. No
diagnostic operation may block a real-time audio/video frame loop with synchronous I/O.

## v0.6.9 acceptance boundaries

Doctor's first implementation should demonstrate automatic capability discovery, **real active
execution** of representative deterministic checks across multiple modalities, typed assertions and
metrics, explicit unsupported/skipped statuses, safe cancellation/cleanup, and the same
machine-readable report consumed by Test.

The longer-term cross-session Episode lifecycle, durable task recovery, Dream, Reflection, background
wake/sleep, and connection-independent Avatar execution are **v0.7.4 work**, not Doctor requirements
for v0.6.9.

**Related:** [Targeted Testing and Benchmarking](test.md) · [Host CLI
today](../../avatar-host/README.md) · [Model cache](../models-cache-layout.md) ·
[Workspace](../avatar-workspace-layout.md)
