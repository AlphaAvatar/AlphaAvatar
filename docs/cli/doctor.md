# `alphaavatar doctor`

Diagnose the installation and a configuration: static checks, then a temporary diagnostic
session of the configuration on fixed samples. One command does both; nothing else to start.

```bash
alphaavatar doctor                                      # the default bundle, if there is one
alphaavatar doctor [<bundle> | <file>] [KEY=VALUE ...]  # as config check selects them
alphaavatar doctor --json                               # the same report as JSON
alphaavatar doctor --list                               # the checks, without running any
```

The optional argument and the overrides follow [`config check`](config.md#choosing-a-configuration):
the same `.env`, home, bundle or file selection, profiles, overrides, validation and read-only
workspace checks. With no argument and no default bundle, Doctor says how to create one and
still checks everything that needs no configuration. There are no other options: what the
session runs follows from what the configuration enables, what is available here and what
the configuration authorizes.

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
| `models.runners` | The planned runners started from the model cache, offline: each one's start, queue and execution figures | yes, session |
| `services.external` | Model, speech, vector store, tool and MCP services: reached by the session only when authorized; the RTC server is never contacted | yes |
| `session.scenarios` | Fixed samples through each enabled modality chain, with figures and evidence | yes, session |
| `session.cleanup` | Sessions, executor, runtime, runner processes, sockets and the temporary workspace reclaimed | yes, session |
| `devices.media` | Microphones, cameras and players: client devices, never opened — not verified | |

The static checks create, download, load, start and contact nothing, and open no socket; a
`.env` Doctor cannot read is a `config.load` failure in the same report. The first
configuration import in a process loads the plugins, as `config check` and `start` do, and
some of their libraries probe the machine while importing: `urllib3` opens and binds one IPv6
socket to test IPv6 support, and `weasyprint` looks up native libraries through
`ctypes.util.find_library`, which runs `ldconfig`, `gcc` and `ld` and creates and removes
temporary files.

## The diagnostic session

It is the session `start` would run: the planned runners start in one inference runtime from
the configured model cache, and the Engine, plugins and output runtime come from the Host's own
`create_execution`. What differs:

- **Process.** The session runs in a process of Doctor's own, which leads its own process
  group. Model downloads are switched off there and in its runners, its inference endpoint
  and log capture stay there, and the caller's environment and loggers are left as they were.
  Ctrl+C reaches only the `doctor` command, which asks that process to stop; one that does not
  exit in time is ended with its whole group, runners included.
- **Snapshot.** Authorization is decided on the configuration Doctor loaded and validated, and
  that same snapshot is what the diagnostic process starts: nothing is read again in between.
- **Storage.** The snapshot is moved onto a temporary directory: the Avatar's workspace, and
  any explicit local LanceDB path of the default memory, persona or MCP store, which moves to
  where the default would be inside it. A remote vector store (Qdrant) holds real Avatar data
  Doctor cannot keep apart, so whatever needs it is skipped and named. The directory is also
  the process's temporary root, so its runtime's socket goes there too, and it is removed
  afterwards. A missing model is reported, never fetched; resolving cached models refreshes
  their lock files and integrity manifests, as `start` does.
- **Transport.** Doctor plays the RTC backend's part: it publishes the samples where the RTC
  input adapters publish media, at their cadence (20 ms microphone frames, screen frames at
  `runtime.perception.video_publish_interval_sec`, typed text through the Engine), and reads
  the output boundary as the RTC transport does, acting as the local audio queue. No RTC
  server, client or device is involved.

### Authorization

External services, often billed per call, are reached only when the configuration allows it:

```yaml
# host profile (configs/profiles/<bundle>/host/host.yaml)
doctor:
  external_services: true   # default false
```

or for one run: `alphaavatar doctor my-avatar host.doctor.external_services=true`.

Without it the session does not run: `session.start` names the services it would reach and
the scenarios are reported as not run for want of authorization. A plugin, provider backend or
runner Doctor does not ship counts as one of those services: what it reaches cannot be
confirmed. The runners still start, as an independent local check, when starting them reaches
nothing beyond this machine; the default memory, persona and MCP vector stores embed a probe
text with their embedding provider when they start, so with those enabled the runners wait for
authorization too. Reaching external services and writing real Avatar data are separate
bounds: authorization never lets Doctor write to a remote vector store.

`services.external` lists each service the configuration names: configured, authorized,
reached (it answered a stage of the session) and passed (it served that stage, and no turn
stopped there), or which of those nothing Doctor ran could show.

### Scenarios

| Scenario | When | Input | The whole answer must be |
| --- | --- | --- | --- |
| `voice_vision` | VAD, STT and TTS configured, vision on (`vlm` or `realtime`) | "What color is the card on my screen? Answer in one word." spoken, with a picture of a green card shared as a screen | `green` |
| `voice` | VAD, STT and TTS configured, vision off | "What is two plus three? Answer with just the number." spoken | `5` or `five` |
| `text` | always, after the spoken turn | the same sum, typed | `5` or `five` |
| `image_input` | — | no input transport delivers images to a session yet | |
| `visual_output` | a Character is configured | its frames render in a browser participant and carry no Turn | |

The spoken samples are recordings shipped in the Host package (`alphaavatar/host/doctor/
samples/`, 16 kHz mono PCM16), made offline with FFmpeg's flite voice by
`scripts/doctor_samples.py make`; `scripts/doctor_samples.py check` reads them back through
Doctor, and CI does so from the built wheel alone. The microphone keeps sending silence after
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
`request.input`, `request.frames`, `model.first_event`, `text.first`, `text.complete`,
`audio.first`, `outputs.complete`, `run.completed` it did not reach, or `answer` when
everything was reached but the answer is not the task's; and its `cause` as the producer
names it, such as `ModelCapabilityError` or `speech_synthesis_failed`.

The spoken and the selected frames must meet in one model request: `request.input` passes when
the Turn's first model request carries the input the Turn committed, and `request.frames` when
it carries frames Doctor published. Each output of the Turn's run is judged on its own
(`outputs`): `completed`, `failed`, `interrupted`, `timed_out` or `not_ended`, with its reason;
`outputs.complete` passes only when all of them completed.

When text passes and a selected scenario could not run, such as voice without TTS, the summary
says partial coverage and `session.scenarios` warns.

### Fallbacks

When the original configuration fails for a reason an existing fallback answers, Doctor tries
that fallback on its own configuration, with its own runners and sessions, and reports both:

- **Vision unavailable** — the model refused the pictures (`ModelCapabilityError`), or a
  runner only vision needs could not start: the snapshot runs as a camera-less device, with
  vision off and the default persona's face analysis and the router's visual addressing off
  with it, so its runners are planned anew; `voice` runs as an audio session, and `text` too
  when the original never ran.
- **Speech output unavailable** — a spoken or typed turn had no audio, or an output's audio
  failed after it began: `text` runs as a chat session, without audio output.

Any other cause, such as rejected credentials (`ModelRequestError`), is reported as it is,
without a fallback. A degraded result carries its `configuration` (`degraded: vision off`,
`degraded: text output`); the original keeps its own outcome, blocked stage and cause, and
decides the status.

### Figures

Every time is on one clock, the session's monotonic clock. A spoken turn's **response start**
is the moment the frame carrying the sample's last voiced sample is published; the trailing
silence follows as usual. A typed turn starts when the Engine accepts the input. Figures are
server side, from diagnostic input to the output boundary: what a client shows or plays is not
measured, since no client takes part.

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
not observed leaves the value `null` with 0 samples. Single samples on one machine describe
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
holds this input, so a late event of another turn or session is never counted. Evidence is
bounded, keeping where the chain began, turned and ended, and passes the same output boundary
as the rest of the report.

### Bounds

Starting the runners, assembling a session and its readiness take at most 180 s, one turn at
most 60 s, everything at most 480 s, the model cache check included since it is part of the
runners' start; closing has its own bounds. Nothing starts once a stop was asked or the
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

A run with stand-in services whose model accepts no images (CI's doubles; figures are theirs),
from its session rows on:

```text
    STATUS  CHECK                  SUMMARY
    ------  ---------------------  ------------------------------------------------------------
    ...
    session
    PASS    session.start          A temporary session with the configured plugins was ready in 41 ms
    PASS    models.runners         2 runners started from the cache, offline; slowest alphaavatar.router.turn_taking.smart_turn_v3 in 0.72 s
    FAIL    services.external      2 passed, 1 failed, 3 not verified by the samples
                                   livekit RTC server: not contacted; `alphaavatar dev avatar.json` connects to it
                                   -> See the failed scenarios' blocked stages and causes
    FAIL    session.scenarios      1 passed, 2 failed, 1 not enabled, 1 no coverage; degraded: voice passed
                                   -> See each failed scenario's blocked stage, cause and evidence
    PASS    session.cleanup        4 owned parts closed: sessions and executor before each runtime; runner processes, sockets and the temporary workspace reclaimed

    STATUS  RUNNER                                        CONFIGURATION         STARTUP  SUMMARY
    ------  --------------------------------------------  --------------------  -------  -------
    PASS    alphaavatar.voice.vad.silero                  original              0.35 s   started
    PASS    alphaavatar.router.turn_taking.smart_turn_v3  original              0.72 s   started
    PASS    alphaavatar.voice.vad.silero                  degraded: vision off  0.33 s   started
    PASS    alphaavatar.router.turn_taking.smart_turn_v3  degraded: vision off  0.67 s   started

    SERVICE                              AUTHORIZED  REACHED  PASSED  NOTE
    -----------------------------------  ----------  -------  ------  -----------------------
    model providers (scripted)           yes         yes      no      ModelCapabilityError
    speech recognition (openai_segment)  yes         yes      yes
    speech synthesis (openai)            yes         yes      yes
    custom memory 'doctor'               yes         -        -       external access unknown
    custom persona 'doctor'              yes         -        -       external access unknown
    custom provider backend 'scripted'   yes         -        -       external access unknown

    OUTCOME      SCENARIO       CONFIGURATION         SUMMARY
    -----------  -------------  --------------------  ------------------------------------------------------------
    failed       voice_vision   original              Stopped at model.first_event
                                                      The run ended failed: ModelCapabilityError
    failed       text           original              Stopped at model.first_event
                                                      The run ended failed: ModelCapabilityError
    passed       voice          degraded: vision off  Answered as the task expects; first text 725 ms; first audio frame 747 ms; complete 1001 ms
    no coverage  image_input    original              No input transport delivers images to a session yet
    not enabled  visual_output  original              No Character is configured

    FIGURE (ms)                       voice_vision  text  voice [vision off]
    --------------------------------  ------------  ----  ------------------
    first_text                        -             -     725
    first_audio_frame                 -             -     747
    text_complete                     -             -     725
    audio_last_frame                  -             -     1001
    response_final                    -             -     1001
    last_required_input               604           -     -
    vad_close                         603           -     600
    stt_final                         658           -     655
    turn_cutoff                       660           -     667
    context_ready_wait                0.0           0.0   0.0
    cutoff_to_model_request           3.5           7.9   1.4
    model_first_event                 -             -     0.4
    model_first_text_delta            -             -     56
    first_displayable_text            -             -     56
    tts_request_to_first_audio_frame  -             -     22
    selected_frame_age                663           -     -
    last_selected_frame_to_cutoff     56            -     -
```

The text is a set of tables. The checks come first, grouped as environment, configuration,
directories, session and not verified (`--list` is a table with the same groups): a passing
check is one row, any other adds its details and next step below it. Then, once something ran,
the runners of each configuration tried, the external services with what was shown of each,
the scenarios (a failed one adds what stopped it), and the figures side by side, a column per
measured scenario and a dash where a figure was not observed; times under 10 ms keep one
decimal. JSON keeps the flat list of checks, each with `id`, `status`,
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
to fix, since `config init` and runs without a configuration argument read it.

An App or TUI can call `alphaavatar.host.doctor.diagnose(target, overrides)` (async), or
`prepare(...)` for the static checks and `Diagnosis.run()` for the session; the CLI reads
`.env`, parses arguments, handles Ctrl+C and prints. The session's process is started with
`spawn`, as inference runners are, so a script that calls these needs the usual
`if __name__ == "__main__":` guard.

## Not covered

- Client devices, the RTC server and what a client shows or plays: Doctor uses no client.
- Image input and visual output: no transport delivers images to a session, and the Character's
  frames carry no Turn.
- Camera addressing: the picture is shared as a screen, so visual addressing is not exercised.
- A remote vector store: Doctor never writes real Avatar data, so what needs it is skipped.
- What a custom plugin writes: it gets the temporary workspace, and anything it writes elsewhere
  is outside what Doctor can isolate.
- Parallel runner workers and long or loaded runs: their own tests, and `alphaavatar test`.
