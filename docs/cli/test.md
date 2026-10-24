# `alphaavatar test` — Targeted Tests and Benchmarks

> **Design specification — planned for AlphaAvatar v0.6.9.** The commands and options below describe a proposed interface, **not commands already implemented**. The existing Host CLI currently provides `dev`, `start`, `--help`, and `--version`. See the [Host README](../../avatar-host/README.md).

`alphaavatar test` runs **specific, repeatable experiments** against AlphaAvatar capabilities. It
validates behavior, measures performance, and reproduces failures under controlled input, concurrency,
load, cancellation, and fault conditions.

Unlike [`alphaavatar doctor`](doctor.md), which automatically selects a system-wide health suite, Test
lets the developer or operator **select the subject, workload, sample count, execution mode, and
acceptance criteria**. Both commands use the same versioned Diagnostic Probe Framework and result
schemas.

## Proposed commands and examples

All examples are **planned v0.6.9 syntax** and may be refined during implementation.

```bash
# Discover the available test suites/probes and their requirements.
alphaavatar test list

# Run a bounded end-to-end scenario using deterministic multimodal inputs.
alphaavatar test run multimodal-smoke

# Measure the local Semantic Addressing Runner using fixed requests.
alphaavatar test runner semantic --samples 100

# Validate passive memory recall correctness, visibility and latency.
alphaavatar test memory passive --samples 100

# Measure synthetic/fixture-based TTS streaming and output behavior.
alphaavatar test voice tts --samples 50

# Measure a timestamped image/video-frame sequence.
alphaavatar test vision realtime --duration 60

# Run bounded concurrent multimodal input/output and cancellation pressure.
alphaavatar test stress multimodal --concurrency 8 --duration 120

# Reproduce exact cancellation and cleanup ordering conditions.
alphaavatar test scenario cancellation

# Machine-readable output for CI, Doctor, App, and later Agent analysis.
alphaavatar test runner semantic --samples 100 --format json
```

A command targeting a real paid TTS/STT/LLM/embedding service must require **separate explicit
live-mode authorization**, not quietly substitute that service for a deterministic fixture. No example
above implies that an external API is called by default.

## What Test covers

Tests are **capability-focused**, not voice-specific. Every enabled module should be able to
contribute probes without requiring Host to import its internal business logic.

| Test domain | Example scenarios | Key properties |
| --- | --- | --- |
| Text and models | Fixed prompts, streamed delta ordering, structured responses, tool outputs | Correctness, first text, throughput, error/finish semantics. |
| Audio input | Silence/noise/speech fixture, VAD and STT final, source loss and late final | Endpoints, segment lineage, cancellation, transcript correctness. |
| Audio output | TTS fixed phrase, paced/irregular PCM chunks, cancellation | First PCM, duration, underruns, audio-versus-caption independence. |
| Vision | Known still images, timestamped frames, optional local detection | First processed frame, detection correctness, frame loss, throughput. |
| Video and screen | Multi-source input, reordering, format/source changes | Source generations, sequence gaps, timestamps and pressure handling. |
| Audio + video | Synchronized source streams, directed speech and interruption | Temporal alignment, evidence ordering, Turn cutoff, cross-modal decisions. |
| Memory | Fixture write/recall, passive/active retrieval, owner/scope separation | Expected hits, misses, freshness, isolation, embedding/search/resolve latency. |
| Persona | Known test speaker/face samples, profile changes, unknown identity | Recognition boundaries, false matches, test-data isolation, latency. |
| Agent Loop / Context | Turn acceptance, required consumer readiness, model/tool continuation | Context consistency, deterministic execution and cancellation. |
| Tools, RAG, MCP | Simulated tools, denied writes, timeout, result reconciliation | Policy correctness, permission gates, error paths, no replay after dispatch. |
| Runner and IPC | Initialization, single request, shared Runner, multiple replicas | Queue latency, execution time, memory/CPU, throughput and fairness. |
| RTC and devices | Connect/disconnect, synthetic transport frames, playback feedback | Transport latency, reattachment constraints, duplex behavior, client receipt. |
| Long-running reliability | Repeated requests, rate pressure, slow consumers, interruption storms | Bounded buffers, no leaks, predictable errors, cleanup. |

Test suites must select only supported capabilities. An unsupported GPU, camera, or Provider is
**UNSUPPORTED/SKIP**, unless the specific test explicitly requires it as an assertion.

## Test categories

### Correctness and regression

Use fixed, versioned fixtures and assertions to validate source identity, state transitions, media
timing, model/tool contracts, and expected outputs. A known-good deterministic test should fail if a
future refactor changes an externally observable contract.

For inherently probabilistic models, declare whether an assertion checks **protocol correctness**
(deterministic), **quality** (statistical), or **performance** (distributional). Do not interpret one
model response as a universal accuracy result.

### Latency and throughput

Distinguish cold-start from warmed-up measurements and include the precise measured boundaries:

| Metric family | Examples | Important distinction |
| --- | --- | --- |
| Input | Frame arrival → processed frame; speech end → STT final | Source timestamps and event time need separate definitions. |
| Routing | Segment final → Turn cutoff/commit | Addressing wait and STT wait must not be conflated. |
| Context | Turn commit → recall completion → context-ready | Report success, valid empty result, timeout, and overload separately. |
| Model | Request sent → first visible text; output token rate | A provider's response-start event is not the first text token. |
| TTS | TTS request → first PCM; PCM production/consumption ratio | Generated PCM length is not generation wall-clock latency. |
| Playback | First PCM → local capture; queue underruns/starvation | Local capture is not the user's remote speaker playback. |
| Video | Capture → first processed frame; end-to-end FPS | The origin of timestamps and clocks must be identified. |
| Runner | IPC queue, dispatch, execution, return, recovery | Queueing and model compute are separate measurement phases. |
| Resources | CPU, memory/RSS, GPU, model initialization, queue high-water mark | Snapshot/resource sampling overhead must be bounded. |

Always include **units**, fixture identity, warmup policy, per-request status, and sample count.
p50/p95/p99 should be reported only with enough independent valid samples; a handful of smoke tests
cannot establish p99.

### Concurrency, pressure, and full duplex

A stress suite must specify **both the offered load and the concurrency limit**. Compare
fixed-concurrency workloads with fixed arrival-rate/audio/video-cadence workloads; otherwise slow
processing may unintentionally throttle the input generator and hide queue overload.

Scenarios should include multiple independent sources, same-source ordering, overlapping audio/video,
simultaneous memory and model inference, runner replica selection, interrupt/cancel during output, and
slow/downstream-failing consumers.

Measure admitted/rejected/cancelled requests, queue high-water marks, end-to-end latency distribution,
resource use, missed frame/event counts, timeouts, and cleanup. Cancellation at the caller does not
prove work was cancelled in the Runner; distinguish queued, dispatched, executing, completed, and
reaped states.

### Fault injection and long-running tests

Use reproducible faults at owned interfaces: dropped/reordered media events, missing STT final, late
provider callback, slow TTS chunks, tool timeout, Runner termination, duplicate completion, context
consumer error, and simulated RTC disconnect.

Long-running tests should report duration, workload, event drops, queue growth, cumulative errors,
recovery *within the current execution*, and remaining resources. They do not require durable Episode
execution or resume across a stopped application.

## Execution modes and safety

| Mode | Input/service | Typical use |
| --- | --- | --- |
| **Deterministic / local** | Pinned fixtures, mock network boundary, test-only in-memory/temporary state | PR regression and reproducible performance-boundary testing without paid calls. |
| **Local runtime** | Actual installed models/Runner, isolated fixture state | Device-specific initialization and performance measurements. |
| **Live / end-to-end** | Real external Providers, RTC and authorized devices | Measure actual service/device behavior; disclose costs and permissions beforehand. |

Every test declares timeouts, maximum concurrency, fixture size, cleanup deadlines, side effects and
whether its cost is bounded. Use temporary workspaces and isolated owners/scopes for Memory/Persona
testing; do not mutate production identity, memory, external tools, or credentials. Test-specific data
persistence, if required, must go through the **existing plugin-owned storage abstraction**, not a
processor-private database.

When a client cannot provide real playout feedback, `device_playback_latency` must be **not
measured**, rather than approximated using the Host's audio queue. When a network service or GPU is
absent, preserve a meaningful `SKIP`/`UNSUPPORTED` result rather than inventing one.

## Probe and measurement contract

Each executable probe should declare:

- Stable ID and version; capability, fixture, prerequisites, mode, resource/cost/permission
  requirements.
- An async execution contract, bounded cleanup, cancellation policy, and isolated input/output.
- Versioned assertions with expected values or statistical tolerances.
- Measurements with fixed identifiers, units, timing boundaries and sample validity rules.
- Results distinguishing **PASS**, **FAIL**, **WARN**, **SKIP**, **UNSUPPORTED**, **INCONCLUSIVE**,
  and **ERROR**.

The host orchestrates, limits, and aggregates tests; the owning plugin or platform adapter implements
its own probe. A test suite is a composition of these probes. The same registered probe may
participate in Doctor smoke coverage or a larger Test benchmark **without cloning its
implementation**.

These result fields are sourced from typed API boundaries and execution receipts, **never by parsing
logger text or by matching plugin-generated string messages**. Existing `InputTrace` remains useful
for bounded Turn/segment/cutoff evidence, but does not become the general test-result schema. A log
message changing wording must not break a test.

## Example results

These are **illustrative reports**, not measured AlphaAvatar benchmark claims.

### Semantic Runner benchmark

```text
Suite: runner.semantic   Mode: local-runtime
Fixture: semantic-addressing-fixed@v1   Warmup: 5   Samples: 100
Correctness: 100/100 valid responses
Queue latency: p50 0.3 ms, p95 0.7 ms
Execution:     p50 118 ms, p95 159 ms, p99 196 ms
Timeouts: 0   Cancellations: 0   Resource cleanup: PASS
Outcome: PASS (scenario-defined limits)
```

### Multimodal pressure test

```text
Suite: stress.multimodal   Mode: deterministic
Offered load: 8 concurrent sources, 120 s, fixed media cadence
Audio: 0 unexpected missing segment terminals
Video: event loss measured and within declared policy
Output: interruption convergence checked
Runner: queue/execution stages captured separately
Cleanup: 0 outstanding test-owned tasks/processes
Outcome: PASS (scenario-defined limits)
```

Sample results must retain every run's failures and skips, not only successful request timings. The
aggregate must not mask regressions in one modality with a good average from another.

## Integration with Doctor, CLI and Agent tooling

- **Doctor** chooses a short representative subset based on the installed system, then explains root
  causes and next steps.
- **Test** selects a specific suite and produces reproducible, comparable measurements and evidence.
- **Check** (planned) validates configuration and contracts; Claude/Codex may optionally analyze code
  and suggest new tests, but Agent output is not itself evidence of a passing test.
- **CLI/App/CI** consume one versioned, redacted report schema. Diagnostics export must avoid secrets,
  raw user media and personal memory by default.

Any Agent-created test proposal requires the same explicit permissions, resource budgets and
deterministic assertions as a hand-written scenario. An Agent must not silently modify production
code, enable a tool, or auto-approve its own changes while running diagnostics.

## v0.6.9 acceptance boundaries

The first implementation should demonstrate a repeatable cross-modal smoke scenario, one local
model/Runner benchmark, isolated Memory retrieval, media stream and cancellation tests, valid typed
reports, bounded cleanup, and CI-friendly exit behavior. Subsequent work extends the same framework to
configurable Runner parallelism, sustained stress, real-provider tests and mobile device receipts.

**Out of scope:** cross-session Episode persistence, post-shutdown work recovery, autonomous
Dream/Reflection cycles, and background sleep/wake — reserved for v0.7.4.

**Related:** [System Diagnostics / Doctor](doctor.md) · [Host CLI today](../../avatar-host/README.md)
· [Model cache](../models-cache-layout.md) · [Workspace](../avatar-workspace-layout.md)
