# `alphaavatar doctor`

Diagnose the installation and a configuration: static checks first, then the runtime
diagnosis. Doctor starts the bundle's runtime as `start` does, feeds it a fixed spoken sample
at a real input's pace, measures what comes out, and runs its one scenario several times, each
time in a session of its own, to report each figure over the rounds. The runtime does its own work as it
would for a person; Doctor only provides the input, observes, judges and cleans up. One
command does both; nothing else to start.

```bash
alphaavatar doctor                                      # the default bundle, if there is one
alphaavatar doctor [<bundle> | <file>] [KEY=VALUE ...]  # as config check selects them
alphaavatar doctor --rounds 10                          # the scenario 10 times (default 5)
alphaavatar doctor --no-metrics                         # the static checks alone
alphaavatar doctor --json                               # the same report as JSON
alphaavatar doctor --list                               # the checks, without running any
```

The optional argument and the overrides follow [`config check`](config.md#choosing-a-configuration):
the same `.env` and stored [credentials](config.md#credentials), home, bundle or file selection,
profiles, overrides, validation and read-only
workspace checks. With no argument and no default bundle, Doctor says how to create one and
still checks everything that needs no configuration. `--no-metrics` leaves the runtime
diagnosis out: no runner starts and nothing is contacted. Otherwise what it runs follows from
what the configuration enables, once the person at the terminal or the configuration
[authorizes](#authorization) it. `--rounds N` (1 to 50) is the one setting of how much it
runs. To diagnose another configuration, such as another STT plugin, name it: an override or
another bundle, each run reported on its own.

## Checks

| ID | Checks | Needs a configuration |
| --- | --- | --- |
| `system.platform` | Operating system; the POSIX local socket API (AF_UNIX) the Host needs — present, not opened | |
| `python.version` | The interpreter against the Python versions AlphaAvatar supports | |
| `packages.alphaavatar` | Installed AlphaAvatar packages come from one release; the Host's requirements are installed | |
| `config.load` | Selection, profiles, overrides and validation, with `config check`'s result | |
| `config.runners` | The inference runners and workers the configuration selects | yes |
| `packages.capabilities` | Packages the enabled capabilities need: RTC backend, loop, context, model provider backends, voice, router, status, character, memory, persona and tools, with their extras and versions | yes |
| `paths.home` | Application home: where it came from, state, owner and mode, write access, settings, bundles, free space; a link without a target fails | |
| `paths.cache` | Cache root: state, write access, downloaded models, free space | |
| `paths.workspace` | The Avatar's workspace: state, write access, free space | yes |
| `session.start` | A temporary session of the configuration: assembled as `start` would, and ready | yes, session |
| `models.runners` | The planned runners started as `start` starts them, missing model files downloaded: the runtime's [start](#runtime-start) sample, each runner's start, calls, queue and execution figures | yes, session |
| `services.external` | Model, speech, vector store, tool and MCP services: reached by the session only when authorized; the RTC server is never contacted | yes |
| `session.scenarios` | Fixed samples through each enabled modality chain, with figures and evidence | yes, session |
| `session.cleanup` | Sessions, executor, runtime, runner processes, sockets and the temporary workspace reclaimed | yes, session |
| `devices.media` | Microphones, cameras and players: client devices, never opened — not verified | |

The static checks create, download, load, start and contact nothing, and open no socket; a
`.env` Doctor cannot read is a `config.load` failure in the same report. The first
configuration import in a process loads the plugins, as `config check` and `start` do, and
some of their libraries probe the machine while importing: `urllib3` opens and binds one IPv6
socket to test IPv6 support.

## The diagnostic session

It is the runtime `start` would run: the planned runners start in one inference runtime, as
`start` starts them, with the same runner plan, model resolution and cache: cached model files
load, missing ones download. The Engine, plugins and output runtime of each session come from
the Host's own `create_execution`. VAD, STT, turn taking, Context, the loop, the model and TTS
all work as the configuration says. What differs:

- **Process.** The diagnosis runs in a process of Doctor's own, which leads its own process
  group. Its inference endpoint and log capture stay there, and the caller's environment and
  loggers are left as they were. Run from inside a Host, it does not inherit that Host's
  inference endpoint, runner plan or log receiver (`ALPHAAVATAR_INFERENCE_ENDPOINT`,
  `ALPHAAVATAR_INFERENCE_PLAN`, `ALPHAAVATAR_LOG_ENDPOINT`). What it or its runners print goes
  to a file in Doctor's temporary directory, not to the terminal: a runner that fails is named
  in `models.runners`, and a process that dies without a report is named with the last line it
  printed. stdout carries the report alone, so `--json` output is parseable as it is. Ctrl+C
  reaches only the `doctor`
  command, which asks that process to stop; one that does not exit in time is ended with its
  whole group, runners included.
- **Snapshot.** Authorization is decided on the configuration Doctor loaded and validated, and
  that same snapshot is what the diagnostic process starts: nothing is read again in between.
- **Storage.** What the diagnosis writes is kept apart: the snapshot is moved onto a
  temporary directory, the Avatar's workspace and any explicit local LanceDB path of the
  default memory, persona or MCP store, which moves to where the default would be inside it.
  A remote vector store (Qdrant) holds real Avatar data Doctor cannot keep apart: the
  diagnosis does not run, unless the configuration says its remote stores hold test data
  (`host.doctor.test_stores: true`); then it writes them, and `session.start` names each as
  a test store. The directory is also the process's temporary root, so its runtime's socket
  goes there too, and it is removed afterwards. The model cache is the configuration's own,
  as `start` uses it.
- **Transport.** Doctor plays the RTC backend's part: it publishes the samples where the RTC
  input adapters publish media, at their cadence (20 ms microphone frames, screen frames at
  `runtime.perception.video_publish_interval_sec`), and reads
  the output boundary as the RTC transport does, acting as the local audio queue. No RTC
  server, client or device is involved.

A configuration that plans no runner is valid: `models.runners` is skipped as having nothing
to start, and `session.start` reports the session's own start. A configuration without voice
(VAD, STT and TTS) has no scenario Doctor can run: nothing is asked or started, and
`session.start` says what is missing.

### Authorization

The runtime diagnosis starts the runtime, may download model files the cache lacks, and calls
the services the configuration names, often billed per call. It runs only once authorized,
all of it at once. In a terminal, Doctor says what it would do after the static checks, and
asks once:

```text
Runtime diagnosis
  It starts this bundle's runtime as start does, then runs this scenario 5 times, each time
  in a session of its own:
    voice_vision  Speech and screen frames in one model request
  Model files the cache lacks are downloaded first, as start would.
  It calls the services this configuration names:
    model providers (langchain, openai)
    speech recognition (openai_segment)
    speech synthesis (openai)
    embeddings as alphaavatar.memory.vdb.lancedb starts
    embeddings as alphaavatar.persona.vdb.lancedb starts
  Calls to these services may be billed.
    Run the diagnosis? [y/N]:
```

A yes authorizes this run alone, of the configuration Doctor loaded and checked: the run uses
that same snapshot, and the same plan: the scenario and rounds listed are the ones its budget
is made for and the ones that run. A no, Enter, the input ending, or `--no-metrics` gives the static checks
alone: `session.start`, `models.runners` and `session.scenarios` are `SKIP`, `Not run: the
diagnosis was declined` (or `left out with --no-metrics`), and `session.cleanup` says nothing
was started. Nothing starts before that, not even a runner, whatever package it comes from.
With `--json`, the question goes to stderr and stdout stays the JSON alone.

Without a terminal, as in CI, nothing is asked: only the configuration authorizes.

```yaml
# host profile (configs/profiles/<bundle>/host/host.yaml)
doctor:
  external_services: true   # default false: the runtime diagnosis, downloads and calls included
  test_stores: false        # true: the remote vector stores named hold test data Doctor may write
```

or for one run: `alphaavatar doctor my-avatar host.doctor.external_services=true`. A
configuration that authorizes it is not asked about. Without a terminal or that setting, the
runtime diagnosis does not run: `session.start` names the services it would call and how to
allow it.

`services.external` lists each service the configuration names: configured, authorized,
reached (it answered a stage of the session) and passed (it served that stage, and no turn
stopped there), or which of those nothing Doctor ran could show. A model provider no turn used
is judged by the probe the vector stores send it as their runners start: passed when they all
started, failed only when the probe itself failed (`EmbeddingProbeError`), not observed when the
store failed before sending it, such as LanceDB not opening its local store, or when an earlier
runner kept them from starting; the runner's own failure is in `models.runners`.

### Runtime start

The runtime starts once, its runners one after another, each within its
`runtime.inference.initialize_timeout`, downloads included, as at `start`; a runner that fails
fails the start with its own error and where it was raised, and nothing else runs. That one
start is one sample, `runtime_start` in `models.runners`: its time, from the start's beginning
to its own end (every runner ready, or the first failure), and how the model cache changed
meanwhile, a net change only (`the model cache grew by 8.4 MB (net)`, or `did not grow`): a
cache scan cannot tell a download from a file replaced, so it never claims either, and a first
start's growth is never taken for a cached start. A runner that cannot load its model while
this machine switches downloads off (`ALPHAAVATAR_MODEL_OFFLINE` or `HF_HUB_OFFLINE`) fails as
at `start`, and the action says so. Each runner's own start time, the calls it served, and its
peak queue wait and execution follow.

### Scenarios

| Scenario | When | Input | The whole answer must be |
| --- | --- | --- | --- |
| `voice_vision` | VAD, STT and TTS configured, vision on (`vlm` or `realtime`) | "What color is the card on my screen?" spoken, one sentence, with a picture of a green card shared as a screen | `green`, or a short sentence stating it: `The card is green.` |
| `voice` | VAD, STT and TTS configured, vision off or text only | "What is two plus three? Answer with just the number." spoken: two sentences, each to be in the transcript | `5` or `five` |
| `image_input` | — | no input transport delivers images to a session yet | |
| `visual_output` | a Character is configured | its frames render in a browser participant and carry no Turn | |

One scenario runs: `voice_vision` when vision is on, `voice` when it is off; the other is
`not_enabled`. To diagnose both, run Doctor twice, once with `vision.enabled=false`. It runs
`--rounds` times, 5 by default, each time in a session of its own: no turn has another's
history. The runtime starts once for all of them; round 1 is the first after it started, and
is shown apart from the later rounds. The text figures (first text, text complete) are the
spoken scenario's own; no typed scenario runs.

The color is checked over one sentence, so that it checks the picture; whether a sentence is
lost is checked over two. For `voice`, each sentence must be in the committed transcript. For
each sentence, `sentences` in JSON keeps what each layer recorded of its sound, apart:

- `coverage`: how much of its sound closed speech segments hold (`full`, `partial` with
  `covered_ms`, or `none`), and the `segments`; `null` when its sound cannot be placed, as
  when the recording's voiced stretches do not match its sentences;
- `stt`: whether STT returned a final for a segment holding it in time (`final`), none
  (`no_final`, or how its segments ended), or only after the Turn committed (`late`);
- `adopted`: whether the Turn took that final, as its first request names it;
- `content`: whether the final the Turn took holds its words; `null` when no final was taken,
  since its text is not seen.

A sentence that is not heard is placed in the first layer that lost it: `vad` when no segment,
or only part of one, holds its sound; `stt` when no final came for it, or the final the Turn
took leaves its words out (one segment holding both sentences, its final the first alone, is
this case); `turn` when its final came, after the Turn committed or in time but not taken; and
`unknown` when the evidence cannot place it. The round stops at `vad.closed`, `stt.final`,
`turn.committed`, or `transcript` for `unknown`. KD-17, a turn cancelled while waiting for a
slow final, stays open; these show where a round loses a sentence, not why turn taking did.

The spoken samples are recordings shipped in the Host package (`alphaavatar/host/doctor/
samples/`, 16 kHz mono PCM16, about 2.4 s and 3.3 s), made offline with FFmpeg's flite voice
by `scripts/quality/doctor_samples.py make`; `scripts/quality/doctor_samples.py check` reads
them back through Doctor, and CI does so from the built wheel alone. Doctor needs nothing else: small
samples only tests use live in their package's `tests/fixtures/`, and large ones (long,
multi-stream or load runs) in a Hugging Face Dataset that only the tests asking for them
fetch. The microphone keeps sending silence after
them, as a real one does, until the turn ends. The transcript must contain the question's
words. An answer passes when, case, surrounding space and punctuation aside, it is one of the
expected answers; for the card, also when a short sentence states the color and nothing else
(`The card is green.`, `It's green.`). A wrong color, another color beside it, a negation, a
hedge (`maybe`, `I think`, `looks`), a question (`Green?`), or another number that contains the
digit does not. The picture comes as screen-share frames because it
has no face: a camera would put the turn in audio-visual mode, which waits for visual
addressing a card cannot give.

Each scenario ends with one outcome: `passed` or `failed` (measured), `not_enabled` (the
configuration does not select it), `conditions_unmet` (selected, but authorization, a model,
a sample or the session is missing), `no_coverage` (selected, but Doctor cannot drive or
observe it yet) or `interrupted`. A failed scenario names its `blocked_stage`, the first of
`input`, `vad.closed`, `stt.final`, `turn.committed`, `frames.selected`, `model.request`,
`request.input`, `request.content`, `request.frames`, `model.first_event`, `text.first`,
`text.complete`, `audio.first`, `outputs.complete`, `run.completed` it did not reach, `answer`
when everything was reached but the answer is not the task's, or `turn.timeout`,
`turn.interrupted`, `turn.session_failed` when the turn itself ended that way; and its `cause`
as the producer classified it, with the provider's code when it gave one, such as
`ModelCapabilityError: image_input`, `ModelRequestError: http_401` or
`speech_synthesis_failed`.

The spoken and the selected frames must meet in one model request. The Loop records what each
request actually carries: the input the Turn committed, whether each of the Turn's input
observations is in it (as its words, or as an audio part), and its frames. `request.input`
passes when the Turn's first request carries the Turn's committed input, `request.content`
when it carries the observation of the sample's STT final, and `request.frames` when it carries frames Doctor published. Each output of the
Turn's run is judged on its own (`outputs`): `completed`, `failed`, `interrupted`, `timed_out`
or `not_ended`, with its reason; `outputs.complete` passes only when all of them completed. A
turn that ended by timeout, interruption or a failed session keeps that end even if its
outputs complete afterwards: what arrives late stays as evidence, and completion times are
given only for a turn that completed.

A scenario that failed in any round fails `session.scenarios`: one round in five is a failure
worth knowing; one that did not run warns as partial coverage.

### Failures are reported as they are

Doctor runs the configuration it was given and nothing else: no fallback configuration, no
second runtime, no typed turn. A model that refuses the pictures
(`ModelCapabilityError: image_input`; the OpenAI adapter does when it cannot encode or inline
them) fails `voice_vision` at the model, and the next step says to choose a model that takes
images or to turn vision off; a runner that cannot start fails the start; a speech output that
fails fails the round, its outputs judged one by one. Rejected credentials, a generic HTTP 400
(`ModelRequestError: http_400`), a failing service: each keeps its own cause.

### Figures

Every time is on one clock, the session's monotonic clock, and every figure runs from the
**final speech**: the moment the frame carrying the sample's last voiced sample is published;
the trailing silence follows as usual. Figures are server side, from diagnostic input to the
output boundary: every measurement ends at the Host's output. LiveKit's transport, what a
client shows or plays, and the physical devices are not measured, since no RTC server, client
or device takes part; `devices.media` says so, and they are measured separately.

End to end, in this order: `first_text` (Runtime first text, the first answer text chunk out),
`first_audio_frame` (the runtime's first answer audio frame out), `response_final` (every
output complete), `text_complete` and `audio_last_frame`; the last three only when every output
completed.

From the final speech to the first audio frame, a round passes a chain of nodes, all for the
Turn's first model request and the outputs whose text it streamed. Its stages, `input`,
`context` and `output`, each run from the node that ends the one before, so for a round with
every boundary the three add up to `first_audio_frame` exactly; each row runs from the node
before it:

| Stage | Row (`<stage>.<node>`) | From | To |
| --- | --- | --- | --- |
| `input` | `input.vad_close` | Final speech | VAD close: the segment of the final below closed |
| | `input.final_transcript` | VAD close | Final transcript: the last STT final the request carries |
| `context` | `context.turn_commit` | Final transcript | Turn commit |
| | `context.context_ready` | Turn commit | Context readiness check complete |
| | `context.context_built` | Context readiness check complete | Context built: the request's input assembled |
| | `context.request_sent` | Context built | Model request sent: encoded and handed to the transport, the first attempt |
| `output` | `output.first_text_delta` | Model request sent | First text delta of that request |
| | `output.tts_request` | First text delta | TTS request for its answer |
| | `output.first_pcm` | TTS request | First PCM (HTTP PCM providers log it) |
| | `output.first_audio_frame` | First PCM | First audio frame |

A node inside a stage that is missing, or came out of order, is merged into the next row: that
row runs from the last node observed in order (its `start` names it, `merged` the nodes left
out), and is no sample of either row. A stage missing a boundary is not measured, and says
which node and why (`Model request sent not observed: its provider logs no request sent`);
rows that do not touch it still are. A retry of the request is an attempt of its own:
`model_request_attempts` counts them, the evidence lists each, and the first is the node. When
the first request streams no text and a later one answers, the output stage is not measured:
its first audio frame answers a later request.

| Figure | From | To |
| --- | --- | --- |
| `first_visual_output_frame` | — | none: no visual output reaches the output boundary |
| `last_required_input` | final speech | the last selected frame or voiced sample in (`voice_vision`) |
| `audio_duration`, `audio_frame_interval`, `audio_max_gap` | answer audio frames out | |
| `audio_underruns` | first answer frame | last: where a real-time queue started at the first frame would starve |
| `audio_rtf` | first answer frame | last: producing time over audio duration, both given |
| `stt_request_to_final` | segment committed to STT | the request's last final |
| `context_ready_wait` | Context asks for the Turn's context | ready (the Context manager's own figure) |
| `model_request_encode`, `model_request_frames`, `model_request_bytes`, `model_request_attempts` | first attempt sent | encoded here (ms), pictures it carries, body sent (bytes), attempts: the provider's own record |
| `model_first_event` | model request sent | first stream event, which may only say the response began |
| `frame_input_to_available`, `selected_frame_age` | frame arrival | published to perception, model request |
| `last_selected_frame_to_cutoff` | newest selected frame in | Turn committed (negative: it arrived after the cutoff) |
| `vision_wait` | Turn committed | frames available: only when a wait is observed, so far never |
| `session_ready` (`session.start`) | session assembly | Engine ready: the median over every session, each in `values` |
| `runtime_start` (`models.runners`) | runtime start began | every runner ready, or the first failure: its note the model cache's net change |
| `queue_wait_max`, `execution_max` (`models.runners`) | each runner's own summary | |

Each figure gives its value, unit, start and end events, sample count and boundary; an event
not observed leaves the value `null` with 0 samples, and a `note` says why where the figure
knows (`not recorded: the turn ended by timeout`). A measured figure's `note` describes it
instead.

`session.scenarios` sums the rounds up in `summaries`, one per scenario, with the
`configuration` its rounds ran with (model, STT and TTS backends and models, vision) and the
`sample` they heard, by name and content digest: the rounds run and passed, where the others
stopped (`stopped_at`), and for each figure, over the passed rounds, the first round's value
apart (`first`), then the later rounds that passed and observed it: their count, median and
range (`samples`, `median`, `low`, `high`), and their 95th percentile (`p95`) from 20 samples
on. The `all_` fields give the same over every round that observed it, failed ones included,
round 1 apart (`all_first`, `all_samples`, `all_median`, `all_low`, `all_high`); `merged`
counts the rounds whose value ran from an earlier node. The text shows the passed rounds'
table, and every round's when any did not pass; `n` is the later rounds counted. Each round's
own figures stay with it, in `scenarios`, with its `round`. A few rounds on one machine
describe this machine and these services today, not the pipeline's behavior in general.

`scripts/quality/doctor_compare.py NAME=REPORT.json ...` puts saved reports side by side,
recomputing each figure from the rounds the same way, checking it against the report's own
summary (a difference is named, exit code 1), and counting holds, cancels, finals for a
retired segment, retried requests and sentences lost by layer.

### Evidence

Each measured scenario lists what was observed, in order, with times relative to the response
start: Doctor's input (`input.voiced_end`, `input.screen_first`), the input trace's stages
(`perception.speech_closed`, `stt.terminal`, `candidate.decision`, `turn.committed`,
`context.frame_selected`, `model.request`, `model.request_frame`, …), the loop and speech logs
(`model.started`, `model.first_event`, `speech.request`, …) and the output events
(`output.text_chunk`, `output.audio_frame`, `output.control`, `output.playback`). The trace
keeps identities salted per session; the evidence shows their shortened tokens (`turn`,
`decision`, `candidate`, `segment`, `input`, `run`, `request`, `observation`), and equal tokens
are one identity: a segment joins its candidate, decision and Turn; the Turn joins its input,
its model request with that request's frames, and its run's outputs. `request` sums that up,
and `frames` tells the frames Context selected from those the request carried, each matched
to one Doctor published. The Turn is the one committed in this session whose perception range
holds this input, so a late event of another turn or session is never counted. When no Turn
commits, the evidence follows the spoken input from its own sound on (its segment, STT and
turn-taking decisions), so the report names the stage it stopped at, such as a candidate
cancelled for want of a transcript before the STT final arrived. Evidence is
bounded, keeping where the chain began, turned and ended, and passes the same output boundary
as the rest of the report.

### Bounds

The runtime's start is bounded as `start` bounds it: each runner by its own
`runtime.inference.initialize_timeout` (300 s by default), downloads included, so its own
timeout is the error reported; Doctor's bound, the runners' timeouts together and 30 s more,
only catches a start that keeps to none. Assembling a session and its readiness take at most
180 s, one turn at most 60 s, and everything at most 480 s more than the start's bound, a
turn's more for each turn past three; closing has its own bounds. Nothing starts once a stop
was asked or the budget is spent, and a step keeps the state its wait ended in: one that
returns after its deadline is still a timeout, and what it returned is closed. A turn that does
not end on its own ends its sample playback and its outputs with it. Ctrl+C stops the
diagnosis: what runs is closed, the rounds not run are reported as such, and the exit code is
130; cancelling `Diagnosis.run()` closes the same way before it raises. After
success, failure, timeout or interruption, sessions and their executors close before the
runtime, then the temporary directory goes; `session.cleanup` fails if any of it, a runner
process, or the diagnostic process itself had to be killed or left something behind.

## Results

| Status | Meaning |
| --- | --- |
| `PASS` | Checked and fine |
| `WARN` | Works, but needs attention: no configuration yet, mixed package releases, less than 1 GiB free, a model `start` would download |
| `FAIL` | `start` or `dev` would fail, or cannot work as configured; a measured scenario failed |
| `SKIP` | Not run or not verifiable here: needs a configuration, authorization, or a client |

| Exit code | Meaning |
| --- | --- |
| `0` | No check failed; warnings and skipped checks allowed |
| `1` | At least one check failed |
| `2` | Invalid arguments |
| `130` | Interrupted; the report still shows what ran |

Three rounds of `voice`, vision off, on the offline test doubles of Doctor's tests (their
figures are theirs, not a service's; their TTS logs no first PCM), in which the second round's
STT gives the sum question's first sentence alone; from the sessions on. [cli.html](cli.html)
shows earlier runs with the others, colors and all; its Doctor panels predate this layout:

```text
Session
  Ready                  2.5 ms at the median of 3, 2.2–18 ms

Runners
  Runtime start          648 ms · the model cache did not grow (net)
  PASS  alphaavatar.voice.vad.silero
        started in 0.32 s · 183 calls, queue ≤ 0.0 ms, run ≤ 0.2 ms
  PASS  alphaavatar.router.turn_taking.smart_turn_v3
        started in 0.32 s · 3 calls, queue ≤ 0.0 ms, run ≤ 0.2 ms

Scenarios · 3 rounds, a session each
  FAIL  voice                  2/3 passed · stopped: 1 at stt.final
        Round 2: The transcript does not hold every sentence of the sample
        Round 2: Sentence 2: the final the Turn took (23 characters) holds another sentence too, and
        leaves this one out
        → See the transcript and each sentence in --json; another STT model or plugin compares
  SKIP  voice_vision           Vision is off or text only: voice runs instead
  SKIP  image_input            No input transport delivers images to a session yet
  SKIP  visual_output          No Character is configured
  With model m · stt openai_segment m · tts openai m · vision off
  Sample sum_question sha256:0f72883c4ad4

Latency · voice · 2 of 3 rounds passed
  Metric                                               Round 1   n   Median    Range
  End to end
    Runtime first text                                  706 ms   1   706 ms   706 ms
    First audio frame                                   727 ms   1   727 ms   727 ms
    Response complete                                   958 ms   1   957 ms   957 ms
    Text complete                                       706 ms   1   706 ms   706 ms
    Last audio frame                                    958 ms   1   956 ms   956 ms
  Input                                                 652 ms   1   652 ms   652 ms
    Final speech → VAD close                            601 ms   1   601 ms   601 ms
    VAD close → Final transcript                         51 ms   1    51 ms    51 ms
  Context                                               3.4 ms   1   2.8 ms   2.8 ms
    Final transcript → Turn commit                      1.0 ms   1   0.9 ms   0.9 ms
    Turn commit → Context readiness check complete      0.7 ms   1   0.5 ms   0.5 ms
    Context readiness check complete → Context built    1.2 ms   1   1.1 ms   1.1 ms
    Context built → Model request sent                  0.5 ms   1   0.4 ms   0.4 ms
  Output                                                 72 ms   1    72 ms    72 ms
    Model request sent → First text delta                51 ms   1    51 ms    51 ms
    First text delta → TTS request                      0.9 ms   1   0.6 ms   0.6 ms
    TTS request → First PCM                                  —   0        —        —
    First PCM → First audio frame                            —   0        —        —
  n: later rounds that passed and observed it; the stages add up to First audio frame
  — First PCM → First audio frame: from an earlier node in 3 rounds, so no sample of it
  — TTS request → First PCM: merged into the next row: First PCM not observed: this TTS plugin logs
  no first PCM

Latency · voice · every round, the 1 not passed included
  Metric                                               Round 1   n   Median        Range
  End to end
    Runtime first text                                  706 ms   2   705 ms   705–706 ms
    First audio frame                                   727 ms   2   727 ms   726–727 ms
    Response complete                                   958 ms   2   957 ms       957 ms
    Text complete                                       706 ms   2   706 ms   705–706 ms
    Last audio frame                                    958 ms   2   957 ms   956–957 ms
  Input                                                 652 ms   2   652 ms   651–652 ms
    Final speech → VAD close                            601 ms   2   601 ms       601 ms
    VAD close → Final transcript                         51 ms   2    51 ms     50–51 ms
  Context                                               3.4 ms   2   2.9 ms   2.8–3.0 ms
    Final transcript → Turn commit                      1.0 ms   2   1.0 ms   0.9–1.0 ms
    Turn commit → Context readiness check complete      0.7 ms   2   0.5 ms   0.5–0.6 ms
    Context readiness check complete → Context built    1.2 ms   2   1.1 ms       1.1 ms
    Context built → Model request sent                  0.5 ms   2   0.4 ms       0.4 ms
  Output                                                 72 ms   2    72 ms        72 ms
    Model request sent → First text delta                51 ms   2    51 ms        51 ms
    First text delta → TTS request                      0.9 ms   2   0.6 ms       0.6 ms
    TTS request → First PCM                                  —   0        —            —
    First PCM → First audio frame                            —   0        —            —
  n: later rounds that observed it; the stages add up to First audio frame
  — First PCM → First audio frame: from an earlier node in 3 rounds, so no sample of it
  — TTS request → First PCM: merged into the next row: First PCM not observed: this TTS plugin logs
  no first PCM

Failed rounds · voice
  Round 2 · stopped at stt.final · measured: Runtime first text 705 ms; First audio frame 726 ms;
  Response complete 957 ms; Text complete 705 ms; Last audio frame 957 ms; Input 651 ms; Context 3.0
  ms; Output 72 ms

Run again as JSON
  alphaavatar doctor avatar.json --rounds 3 --json
```

The text is grouped, through the [commands' shared layout](README.md#output). The headline gives
the report's status and its tally; `Diagnostics completed` once the session ran. `Checks` has a
row per group, environment, configuration, directories, and session and services: a group that
only passed is its row, and any check that did not pass is a row under it with its details and
next step. A group that ran nothing is under `Not verified`, with why and what would allow it.
Once the diagnosis ran, the report follows the order a turn depends on: `Session`, each
session's readiness at the median over all of them; `Runners`, the runtime's one start and how
the model cache changed meanwhile, then each runner's start, the calls it served, and its peak
queue wait and execution; `Scenarios`, the scenario with its rounds passed of run and where the
others stopped, a failed round's reasons below it, each once with the rounds that share it, and
the next step; then what its rounds ran with and the sample they heard. Then the `Latency`
table over its passed rounds: end to end (Runtime first text, First audio frame, Response
complete, Text complete, Last audio frame), then `Input`, `Context` and `Output`, each stage's
total on its own line and its rows under it, each from the node before it (see
[Figures](#figures)). When a round did not pass, a second table follows over every round that
observed each figure, failed ones included, said so in its heading. Each row gives round 1,
then the later rounds' count (`n`, said under the table), median and range, and P95 once there
are 20 samples; where the terminal is too narrow, each figure takes lines of its own. A figure
no round observed is `—`, never `0 ms`, and a line under its table says why; a row merged in
some rounds says in how many. `Failed rounds` lists each failed round with the stage it stopped
at and what it did measure: end to end and each stage. Times under 10 ms keep one decimal.
When the diagnosis did not run, `Latency` says so, `Not measured`, with why. `Run again as
JSON` is the command that prints the same diagnosis as JSON, with the same `--rounds`: every
round, event boundary, sample count, service and piece of evidence. Run with `KEY=VALUE`
overrides, it says to give the same ones, and does not repeat them.
`--list` lists the checks in the same groups.

JSON keeps the flat list of checks, each with `id`, `status`,
`summary`, `details`, `action`, `runners`, `scenarios`, `metrics`, `services` and `summaries`; a
scenario, one per round, has `name`, `outcome`, `summary`, `configuration`, `round`,
`blocked_stage`, `cause`, `details`, `task`, `transcript`, `answer` (both bounded), `reached`,
`request`, `outputs`, `metrics`, `segments`, `frames`, `sentences`, `evidence` and `sample`; a
figure has `merged` besides its value and boundaries; a runner has `method`, `status`,
`summary`, `details`, `startup_seconds`, `calls`, `queue_wait_max_ms` and `execution_max_ms`; a
summary has `name`, `configuration`, `rounds`, `passed`, `stopped_at`, `figures` and `sample`;
a service has `name`, `authorized`, `reached`, `passed` and `note`.
Text, JSON and details pass the same output boundary as `config check`: credentials from the
configuration and the environment are replaced and control characters removed. `--list --json` prints each check's `id`, `title`,
`needs_configuration` and `in_session`.

Model provider backends come from the provider tasks start would create: the built-in plugins'
settings are validated as `config check` does (`validate_plugin_settings`), so omitted fields
take their defaults; a processor switched off (`enabled: false`) and a disabled plugin create
nothing and are skipped. The vector store embeddings of the default memory, persona and MCP
always use the default backend. For another loop, memory, persona or MCP plugin,
`packages.capabilities` warns that its backends are not verified. Settings a built-in plugin's
schema rejects, such as a realtime loop without `model`, fail `config.load` as they fail
`config check`; settings only a plugin's construction checks, such as STT without `model`,
fail `session.start`.

Unreadable settings do not stop a named bundle or a file: `paths.home` warns and names the file
to fix, since `config init` and runs without a configuration argument read it. Without an
argument, the default bundle comes from the same read of the settings as the stored
credentials, and settings or stored credentials that cannot be read fail `config.load`.

An App or TUI can call `alphaavatar.host.doctor.diagnose(target, overrides)` (async), or
`prepare(...)` for the static checks and `Diagnosis.run()` for the session; the CLI reads
`.env`, parses arguments, handles Ctrl+C and prints. The session's process is started with
`spawn`, as inference runners are, so a script that calls these needs the usual
`if __name__ == "__main__":` guard.

## Not covered

- Client devices, LiveKit's transport and what a client shows or plays: Doctor uses no RTC
  server or client, and every figure ends at the Host's output; `devices.media` names them as
  not measured, and they are measured separately.
- Image input and visual output: no transport delivers images to a session, and the Character's
  frames carry no Turn.
- Camera addressing: the picture is shared as a screen, so visual addressing is not exercised.
- A remote vector store holding real data: Doctor never writes it, so the diagnosis does not
  run; a configuration that names its remote stores test stores lets it, and the report says so.
- What a custom plugin writes: it gets the temporary workspace, and anything it writes elsewhere
  is outside what Doctor can isolate.
- Parallel runner workers and long or loaded runs: their own tests, and `alphaavatar test`.
