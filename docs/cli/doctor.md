# `alphaavatar doctor`

Diagnose the installation and a configuration: static checks first, then the runtime tests,
a temporary diagnostic session of the configuration on fixed samples. One command does both;
nothing else to start.

```bash
alphaavatar doctor                                      # the default bundle, if there is one
alphaavatar doctor [<bundle> | <file>] [KEY=VALUE ...]  # as config check selects them
alphaavatar doctor --no-metrics                         # the static checks alone
alphaavatar doctor --json                               # the same report as JSON
alphaavatar doctor --list                               # the checks, without running any
```

The optional argument and the overrides follow [`config check`](config.md#choosing-a-configuration):
the same `.env` and stored [credentials](config.md#credentials), home, bundle or file selection,
profiles, overrides, validation and read-only
workspace checks. With no argument and no default bundle, Doctor says how to create one and
still checks everything that needs no configuration. `--no-metrics` leaves the runtime tests
out: no runner starts and nothing is contacted. Otherwise what they run follows from what the
configuration enables, what is available here, and what the configuration or the person at
the terminal [authorizes](#authorization).

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
| `models.runners` | The planned runners started from the model cache, offline unless a [download](#model-files) was agreed: each one's start, queue and execution figures | yes, session |
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

It is the session `start` would run: the planned runners start in one inference runtime from
the configured model cache, and the Engine, plugins and output runtime come from the Host's own
`create_execution`. What differs:

- **Process.** The session runs in a process of Doctor's own, which leads its own process
  group. Model downloads are switched off there and in its runners unless a person agreed to
  them, its inference endpoint and log capture stay there, and the caller's environment and
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
- **Storage.** The snapshot is moved onto a temporary directory: the Avatar's workspace, and
  any explicit local LanceDB path of the default memory, persona or MCP store, which moves to
  where the default would be inside it. A remote vector store (Qdrant) holds real Avatar data
  Doctor cannot keep apart, so whatever needs it is skipped and named. The directory is also
  the process's temporary root, so its runtime's socket goes there too, and it is removed
  afterwards. A missing model is reported, and fetched only once a person agrees
  ([model files](#model-files)); resolving cached models refreshes their lock files and
  integrity manifests, as `start` does.
- **Transport.** Doctor plays the RTC backend's part: it publishes the samples where the RTC
  input adapters publish media, at their cadence (20 ms microphone frames, screen frames at
  `runtime.perception.video_publish_interval_sec`, typed text through the Engine), and reads
  the output boundary as the RTC transport does, acting as the local audio queue. No RTC
  server, client or device is involved.

A configuration that plans no runner, such as a text-only one, is valid: `models.runners` is
skipped as having nothing to start, and `session.start` reports the session's own start.

### Authorization

The runtime tests run a configuration that reaches nothing beyond this machine directly. One
that reaches external services, often billed per call, runs only once they are authorized. In
a terminal, Doctor lists them after the static checks and asks:

```text
Runtime tests
  They run this configuration on fixed samples, through the services it names:
    model providers (openai)
    speech recognition (openai_segment)
    speech synthesis (openai)
  Calls to these services may be billed.
    Run the runtime tests? [y/N]:
```

A yes authorizes this run alone, of the configuration Doctor loaded and listed the services
of: the run uses that same snapshot. A no or Enter gives the static checks alone, as
`--no-metrics` does: `session.start`, `models.runners` and `session.scenarios` are `SKIP`,
`Not run: the external services it reaches were declined` (or `left out with --no-metrics`),
and `session.cleanup` says nothing was started. With `--json`, the question goes to stderr
and stdout stays the JSON alone.

Without a terminal, as in CI, nothing is asked: only the configuration authorizes.

```yaml
# host profile (configs/profiles/<bundle>/host/host.yaml)
doctor:
  external_services: true   # default false
```

or for one run: `alphaavatar doctor my-avatar host.doctor.external_services=true`. A
configuration that authorizes them is not asked about either. Without a terminal or that
setting, the session does not run: `session.start` names the services it would reach and the scenarios are reported as not
run for want of authorization. A plugin, provider backend or
runner Doctor does not ship counts as one of those services: what it reaches cannot be
confirmed. The runners still start, as an independent local check, when starting them reaches
nothing beyond this machine; the default memory, persona and MCP vector stores embed a probe
text with their embedding provider when they start, so with those enabled the runners wait for
authorization too. Reaching external services and writing real Avatar data are separate
bounds: authorization never lets Doctor write to a remote vector store.

`services.external` lists each service the configuration names: configured, authorized,
reached (it answered a stage of the session) and passed (it served that stage, and no turn
stopped there), or which of those nothing Doctor ran could show. A model provider no turn used
is judged by the starts of the runners that embed with it as they start, a vector store's:
passed when they all started, failed when one failed, not observed when an earlier runner kept
them from starting.

### Model files

The runners start from the model cache alone first. When some lack their model files, as on a
first run after `setup`, Doctor names those runners and where their files go, and asks in a
terminal:

```text
Model files
  These runners did not start: their model files are not in the cache yet.
    alphaavatar.router.turn_taking.smart_turn_v3
  Doctor downloads what the runners need into ~/.local/share/alphaavatar/cache/models, as start
  would, then runs the runtime tests again.
    Download and continue? [y/N]:
```

On a yes the runtime tests run again with downloads allowed, and the report is that run's. On a
no, without a terminal, or with `ALPHAAVATAR_MODEL_OFFLINE` or `HF_HUB_OFFLINE` set, the report
is the first run's: each such runner failed, its model not in the cache. `alphaavatar start`
downloads the files too.

### Scenarios

| Scenario | When | Input | The whole answer must be |
| --- | --- | --- | --- |
| `voice_vision` | VAD, STT and TTS configured, vision on (`vlm` or `realtime`) | "What color is the card on my screen? Answer in one word." spoken, with a picture of a green card shared as a screen | `green` |
| `voice` | VAD, STT and TTS configured, vision off | "What is two plus three? Answer with just the number." spoken | `5` or `five` |
| `text` | always, after the spoken turn | the same sum, typed | `5` or `five` |
| `image_input` | — | no input transport delivers images to a session yet | |
| `visual_output` | a Character is configured | its frames render in a browser participant and carry no Turn | |

The spoken samples are recordings shipped in the Host package (`alphaavatar/host/doctor/
samples/`, 16 kHz mono PCM16, about 3.7 s and 3.3 s), made offline with FFmpeg's flite voice
by `scripts/quality/doctor_samples.py make`; `scripts/quality/doctor_samples.py check` reads
them back through Doctor, and CI does so from the built wheel alone. Doctor needs nothing else: small
samples only tests use live in their package's `tests/fixtures/`, and large ones (long,
multi-stream or load runs) in a Hugging Face Dataset that only the tests asking for them
fetch. The microphone keeps sending silence after
them, as a real one does, until the turn ends. The transcript must contain the question's
words. An answer passes only when, case, surrounding space and punctuation aside, it is one of
the expected answers: a wrong or negated answer, a guess ("Green?"), a sentence, or another
number that contains the digit does not. The picture comes as screen-share frames because it
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
when it carries the observation of the sample's STT final (for typed text, the typed
observation), and `request.frames` when it carries frames Doctor published. Each output of the
Turn's run is judged on its own (`outputs`): `completed`, `failed`, `interrupted`, `timed_out`
or `not_ended`, with its reason; `outputs.complete` passes only when all of them completed. A
turn that ended by timeout, interruption or a failed session keeps that end even if its
outputs complete afterwards: what arrives late stays as evidence, and completion times are
given only for a turn that completed.

When text passes and a selected scenario could not run, such as voice without TTS, the summary
says partial coverage and `session.scenarios` warns.

### Fallbacks

When the original configuration fails for a reason an existing fallback answers, Doctor tries
that fallback on its own configuration, with its own runners and sessions, and reports both:

- **Vision unavailable** — the provider refused the pictures as such
  (`ModelCapabilityError: image_input`; the OpenAI adapter does when it cannot encode or
  inline them), or a runner only vision needs could not start: the snapshot runs as a
  camera-less device, with vision off and the default persona's face analysis and the
  router's visual addressing off with it. Its runners are planned anew, and the
  `runtime.inference.methods` settings of runners only vision used go with them while the
  others stay; `voice` runs as an audio session, and `text` too when the original never ran.
- **Speech output unavailable** — a spoken or typed turn had no audio, or an output's audio
  failed after it began: `text` runs as a chat session, without audio output.

Any other cause is reported as it is, without a fallback: rejected credentials, a generic HTTP
400 (`ModelRequestError: http_400`; nothing in it shows it is about vision), a failing
service, or a capability the backend lacks that is not about images. A degraded result carries its `configuration` (`degraded: vision off`,
`degraded: text output`); the original keeps its own outcome, blocked stage and cause, and
decides the status.

### Figures

Every time is on one clock, the session's monotonic clock. A spoken turn's **response start**
is the moment the frame carrying the sample's last voiced sample is published; the trailing
silence follows as usual. A typed turn starts when the Engine accepts the input. Figures are
server side, from diagnostic input to the output boundary: every measurement ends at the Host's
output. LiveKit's transport and what a client shows or plays are measured separately, since no
RTC server or client takes part.

| Figure | From | To |
| --- | --- | --- |
| `first_text` | response start | first answer text chunk out |
| `first_audio_frame` | response start | first answer audio frame out |
| `first_visual_output_frame` | — | none: no visual output reaches the output boundary |
| `text_complete`, `audio_last_frame`, `response_final` | response start | last text complete, last answer audio frame, every output complete: only when every output completed |
| `last_required_input` | response start | the last selected frame or voiced sample in (`voice_vision`) |
| `audio_duration`, `audio_frame_interval`, `audio_max_gap` | answer audio frames out | |
| `audio_underruns` | first answer frame | last: where a real-time queue started at the first frame would starve |
| `audio_rtf` | first answer frame | last: producing time over audio duration, both given |
| `vad_close`, `stt_final`, `turn_cutoff` | response start | segment closed, STT final, Turn committed |
| `stt_request_to_final` | segment committed to STT | STT final |
| `context_ready_wait` | Context asks for the Turn's context | ready (the Context manager's own figure) |
| `cutoff_to_model_request` | Turn committed | model request |
| `model_first_event`, `model_first_text_delta`, `first_displayable_text` | model request | first stream event, first nonempty text delta, first answer text out |
| `tts_text_ready_to_request` | first speakable segment ready | TTS request |
| `tts_request_to_first_pcm`, `first_pcm_to_first_audio_frame` | TTS request, first PCM | first PCM, first answer audio frame out (HTTP PCM providers log the first PCM) |
| `tts_request_to_first_audio_frame` | TTS request | first answer audio frame out |
| `frame_input_to_available`, `selected_frame_age` | frame arrival | published to perception, model request |
| `last_selected_frame_to_cutoff` | newest selected frame in | Turn committed (negative: it arrived after the cutoff) |
| `vision_wait` | Turn committed | frames available: only when a wait is observed, so far never |
| `session_ready` (`session.start`) | session assembly | Engine ready |
| `queue_wait_max`, `execution_max` (`models.runners`) | each runner's own summary | |

Each figure gives its value, unit, start and end events, sample count and boundary; an event
not observed leaves the value `null` with 0 samples, and a `note` says why where the figure
knows (`this TTS plugin logs no first PCM`, `not recorded: the turn ended by timeout`). A
measured figure's `note` describes it instead. Single samples on one machine describe
this run, not the voice pipeline's real-time behavior in general.

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

Starting the runners, assembling a session and its readiness take at most 180 s, one turn at
most 60 s, everything at most 480 s, the model cache check included since it is part of the
runners' start; closing has its own bounds. A run with downloads agreed gives the runners'
start as long as `start` gives it, `runtime.inference.initialize_timeout` (300 s by default),
and everything as much more. Nothing starts once a stop was asked or the
budget is spent, and a step keeps the state its wait ended in: one that returns after its
deadline is still a timeout, and what it returned is closed. A turn that does not end on its
own ends its sample playback and its outputs with it, and the scenarios after it get a fresh
session. Ctrl+C stops the session: what runs is closed, the rest is reported as not run, and
the exit code is 130; cancelling `Diagnosis.run()` closes the same way before it raises. After
success, failure, timeout or interruption, sessions and their executors close before each
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

A run with stand-in services whose model accepts no images (the offline test doubles of
Doctor's tests; the figures are theirs), from its checks on. [cli.html](cli.html) shows it with
the others, colors and all: the question and its answers, the download, vision off:

```text
Checks
  ...
  FAIL  Session and services   3 passed · 2 failed
        FAIL  services.external   2 passed, 1 failed, 3 not verified by the samples
              model providers (scripted): configured, authorized, reached, failed
              (ModelCapabilityError: image_input)
              speech recognition (openai_segment): configured, authorized, reached, passed
              speech synthesis (openai): configured, authorized, reached, passed
              custom memory 'doctor': configured, authorized, reached: not observed, passed: not
              observed (external access unknown)
              custom persona 'doctor': configured, authorized, reached: not observed, passed: not
              observed (external access unknown)
              custom provider backend 'scripted': configured, authorized, reached: not observed,
              passed: not observed (external access unknown)
              livekit RTC server: not contacted; `alphaavatar dev avatar.json` connects to it
              → See the failed scenarios' blocked stages and causes
        FAIL  session.scenarios
              1 passed, 2 failed, 1 not enabled, 1 no coverage; degraded: voice passed
              → See each failed scenario's blocked stage, cause and evidence

Not verified
  SKIP  Media devices
        Not verified: the diagnostic session uses its own samples and opens no microphone, camera or
        player
        → Join a dev session from a client to try its devices

Scenarios
  FAIL  voice_vision           Stopped at model.first_event
        The run ended failed: ModelCapabilityError: image_input
  FAIL  text                   Stopped at model.first_event
        The run ended failed: ModelCapabilityError: image_input
  PASS  voice [vision off]     Speech transcribed and answered
  SKIP  image_input            No input transport delivers images to a session yet
  SKIP  visual_output          No Character is configured

Runners
  PASS  alphaavatar.voice.vad.silero                   started in 0.39 s
  PASS  alphaavatar.router.turn_taking.smart_turn_v3   started in 0.39 s
  PASS  alphaavatar.voice.vad.silero                   started in 0.39 s · degraded: vision off
  PASS  alphaavatar.router.turn_taking.smart_turn_v3   started in 0.39 s · degraded: vision off

End-to-end latency
  Metric              voice_vision   text   voice [vision off]
  First text                     —      —               705 ms
  First audio frame              —      —               727 ms
  Response complete              —      —               957 ms
  Text complete                  —      —               705 ms
  Last audio frame               —      —               956 ms
  — First text · voice_vision, text: not reached: stopped at model.first_event
  — First audio frame · voice_vision, text: not reached: stopped at model.first_event
  — Response complete · voice_vision, text: not recorded: an output ended otherwise
  — Text complete · voice_vision, text: not recorded: an output ended otherwise
  — Last audio frame · voice_vision, text: not recorded: an output ended otherwise

Stage timing · voice_vision
  Speech end → VAD close                600 ms
  Speech end → STT final                650 ms
  Speech end → Turn commit              651 ms
  Speech end → Last required input      600 ms
  Context ready wait                    0.0 ms
  Turn commit → Model request           2.2 ms
  Model request → First event                —
  Model request → First text delta           —
  Model request → First text out             —
  TTS request → First PCM                    —
  TTS request → First audio frame            —
  Selected frame age at model request   654 ms
  Newest selected frame → Turn commit    51 ms
  — Model request → First event: not reached: stopped at model.first_event
  — Model request → First text delta: not reached: stopped at model.first_event
  — Model request → First text out: not reached: stopped at model.first_event
  — TTS request → First PCM: not reached: stopped at model.first_event
  — TTS request → First audio frame: not reached: stopped at model.first_event

Stage timing · text
  Context ready wait                    0.0 ms
  Turn commit → Model request           2.0 ms
  Model request → First event                —
  Model request → First text delta           —
  Model request → First text out             —
  TTS request → First PCM                    —
  TTS request → First audio frame            —
  — Model request → First event: not reached: stopped at model.first_event
  — Model request → First text delta: not reached: stopped at model.first_event
  — Model request → First text out: not reached: stopped at model.first_event
  — TTS request → First PCM: not reached: stopped at model.first_event
  — TTS request → First audio frame: not reached: stopped at model.first_event

Stage timing · voice [vision off]
  Speech end → VAD close                601 ms
  Speech end → STT final                651 ms
  Speech end → Turn commit              652 ms
  Context ready wait                    0.0 ms
  Turn commit → Model request           1.4 ms
  Model request → First event           0.4 ms
  Model request → First text delta       51 ms
  Model request → First text out         51 ms
  TTS request → First PCM                    —
  TTS request → First audio frame        21 ms
  — TTS request → First PCM: this TTS plugin logs no first PCM

Run again as JSON
  alphaavatar doctor avatar.json --json
```

The text is grouped, through the [commands' shared layout](README.md#output). The headline gives
the report's status and its tally; `Diagnostics completed` once the session ran. `Checks` has a
row per group, environment, configuration, directories, and session and services: a group that
only passed is its row, and any check that did not pass is a row under it with its details and
next step. A group that ran nothing is under `Not verified`, with why and what would allow it.
Once the session ran come the scenarios (a passed one says what it showed; a failed one, where
it stopped and why), the runners each configuration started, then the figures, in milliseconds
as the session times them: `End-to-end latency` first (first text, first answer audio frame,
response complete, then text complete and last audio frame), a column per measured scenario,
side by side where the terminal fits them and one after another where it does not; then each
scenario's `Stage timing`: speech (VAD close, STT final, the Turn's commit), Context's wait, the
model (request, first event, first text delta, first text out), TTS (first PCM, first audio
frame) and the frames vision selected (age at the model request, the newest one against the
commit). A failed scenario keeps what it measured. A figure not observed is `—`, never `0 ms`,
and a line under its table says why: the figure's own reason, else where its scenario stopped,
else that it was not observed. Times under 10 ms keep one decimal. When the session did not
run, `End-to-end latency` says so, `Not measured`, with why. `Run again as JSON` is the command
that prints the same diagnosis as JSON: every event boundary, sample count, service and piece
of evidence. Run with `KEY=VALUE` overrides, it says to give the same ones, and does not repeat
them. `--list` lists the checks in the same groups.

JSON keeps the flat list of checks, each with `id`, `status`,
`summary`, `details`, `action`, `runners`, `scenarios`, `metrics` and `services`; a scenario
has `name`, `outcome`, `summary`, `configuration`, `blocked_stage`, `cause`, `details`, `task`,
`transcript`, `answer` (both bounded), `reached`, `request`, `outputs`, `metrics`, `segments`,
`frames` and `evidence`; a service has `name`, `authorized`, `reached`, `passed` and `note`.
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
  server or client, and every figure ends at the Host's output; those are measured separately.
- Image input and visual output: no transport delivers images to a session, and the Character's
  frames carry no Turn.
- Camera addressing: the picture is shared as a screen, so visual addressing is not exercised.
- A remote vector store: Doctor never writes real Avatar data, so what needs it is skipped.
- What a custom plugin writes: it gets the temporary workspace, and anything it writes elsewhere
  is outside what Doctor can isolate.
- Parallel runner workers and long or loaded runs: their own tests, and `alphaavatar test`.
