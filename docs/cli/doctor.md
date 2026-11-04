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

It is the session `start` would run: the configuration is loaded by the same services, the
planned runners start in one inference runtime from the configured model cache, and the
Engine, plugins and output runtime come from the Host's own `create_execution`. Only two
things differ:

- **Transport.** Doctor plays the RTC backend's part: it publishes the samples where the RTC
  input adapters publish media, at their cadence (20 ms microphone frames, screen frames at
  `runtime.perception.video_publish_interval_sec`, typed text through the Engine), and reads
  the output boundary as the RTC transport does, acting as the local audio queue. No RTC
  server, client or device is involved.
- **Workspace.** A temporary directory, removed afterwards: the Avatar's workspace, memory,
  persona and vector stores are never touched. Model downloads are switched off for Doctor's
  process and its runners while the session runs; a missing model is reported, never fetched.
  Resolving cached models refreshes their lock files and integrity manifests, as `start` does.

### Authorization

External services, often billed per call, are reached only when the configuration allows it:

```yaml
# host profile (configs/profiles/<bundle>/host/host.yaml)
doctor:
  external_services: true   # default false
```

or for one run: `alphaavatar doctor my-avatar host.doctor.external_services=true`.

Without it the session does not run: `session.start` names the services it would reach and
the scenarios are reported as not run for want of authorization. The runners still start, as
an independent local check, when starting them reaches no service; the default memory,
persona and MCP vector stores embed a probe text with their embedding provider when they
start, so with those enabled the runners wait for authorization too.

### Scenarios

| Scenario | When | Input | The answer must contain |
| --- | --- | --- | --- |
| `voice_vision` | VAD, STT and TTS configured, vision on (`vlm` or `realtime`) | "What color is the card on my screen?" spoken, with a picture of a green card shared as a screen | `green` |
| `voice` | VAD, STT and TTS configured, vision off | "What is two plus three?" spoken | `5` or `five` |
| `text` | always, after the spoken turn | "What is two plus three? Answer in one short sentence." typed | `5` or `five` |
| `image_input` | — | no input transport delivers images to a session yet | |
| `visual_output` | a Character is configured | its frames render in a browser participant and carry no Turn | |

The spoken samples are recordings at 16 kHz; the microphone keeps sending silence after them,
as a real one does, until the turn completes. The transcript must contain the question's
words. The picture comes as screen-share frames because it has no face: a camera would put
the turn in audio-visual mode, which waits for visual addressing a card cannot give.

Each scenario ends with one outcome: `passed` or `failed` (measured), `not_enabled` (the
configuration does not select it), `conditions_unmet` (selected, but authorization, a model,
a sample or the session is missing), `no_coverage` (selected, but Doctor cannot drive or
observe it yet) or `interrupted`. A failed scenario names its `blocked_stage`: the first of
`input`, `vad.closed`, `stt.final`, `turn.committed`, `frames.selected`, `model.request`,
`model.first_event`, `text.first`, `text.complete`, `audio.first`, `response.complete` it
did not reach, or `answer` when everything was reached but the answer misses the task.

### Fallbacks

When the original configuration fails where an existing fallback applies, Doctor runs that
fallback in a session of its own and reports both:

- **Vision unavailable** — `voice_vision` was heard but stopped at frame selection, the model
  or the answer: the `voice` scenario runs with `vision.enabled=false` as an audio session.
- **Speech output unavailable** — a spoken or typed turn stopped before its first audio frame:
  the `text` scenario runs as a chat session, without audio output.

A degraded result carries its `configuration` (`degraded: vision off`, `degraded: text
output`); the original keeps its own outcome and blocked stage, and decides the status.

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
| `text_complete`, `audio_last_frame`, `response_final` | response start | text complete, last answer audio frame, response complete |
| `last_required_input` | response start | the last selected frame or voiced sample in (`voice_vision`) |
| `audio_duration`, `audio_frame_interval`, `audio_max_gap` | answer audio frames out | |
| `audio_underruns` | first answer frame | last: where a real-time queue started at the first frame would starve |
| `audio_rtf` | first answer frame | last: producing time over audio duration, both given |
| `vad_close`, `stt_final`, `turn_cutoff` | response start | segment closed, STT final, Turn committed |
| `stt_request_to_final` | segment committed to STT | STT final |
| `cutoff_to_model_request` | Turn committed | model request |
| `model_first_token`, `model_first_text` | model request | first model event, first answer text out |
| `tts_text_ready_to_request` | first speakable segment ready | TTS request |
| `tts_request_to_first_pcm`, `first_pcm_to_first_audio_frame` | TTS request, first PCM | first PCM, first answer audio frame out (HTTP PCM providers log the first PCM) |
| `tts_request_to_first_audio_frame` | TTS request | first answer audio frame out |
| `frame_input_to_available`, `selected_frame_age`, `vision_wait` | frame arrival, frame arrival, Turn committed | published to perception, model request, last selected frame in |
| `session_ready` (`session.start`) | session assembly | Engine ready |
| `queue_wait_max`, `execution_max` (`models.runners`) | each runner's own summary | |

Each figure gives its value, unit, start and end events, sample count and boundary; a value
is `null` when an event was not observed. Single samples on one machine describe this run,
not the voice pipeline's real-time behavior in general.

### Evidence

Each measured scenario lists what was observed, in order, with times relative to the response
start: Doctor's input (`input.voiced_end`, `input.screen_first`), the input trace's stages
(`perception.speech_closed`, `stt.terminal`, `candidate.decision`, `turn.committed`,
`context.frame_selected`, …), the loop and speech logs (`model.started`, `model.first_event`,
`speech.request`, …) and the output events (`output.text_chunk`, `output.audio_frame`,
`output.control`, `output.playback`). The trace keeps identities salted per session; the
evidence shows their shortened tokens (`turn`, `decision`, `candidate`, `segment`), and equal
tokens are one identity, so a segment joins its candidate, decision and Turn, and the Turn
joins its selected frames (`frames`: perception sequence, offset from the speech end, age at
the model request), its model request and its outputs. Evidence is bounded and passes the
same output boundary as the rest of the report.

### Bounds

Starting the runners, assembling a session and its readiness take at most 180 s, one turn at
most 60 s, everything at most 480 s; closing has its own bounds. The model cache check is the
runners' start, inside those bounds. Ctrl+C stops the session: what runs is closed, the rest
is reported as not run, and the exit code is 130. After success, failure, timeout or
interruption, sessions and their executors close before the runtime, then the temporary
workspace goes; `session.cleanup` fails if any of it, or a runner process, remains.

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

A run with stand-in services whose model accepts no images (CI's doubles; figures are theirs):

```text
    session
      PASS  session.start          A temporary session with the configured plugins was ready in 33 ms
      PASS  models.runners         2 runners started from the cache, offline; slowest alphaavatar.voice.vad.silero in 0.28 s
      FAIL  services.external      Reached by the diagnostic session; see session.scenarios for each stage
      FAIL  session.scenarios      1 passed, 2 failed, 1 not enabled, 1 no coverage; degraded: voice passed
        failed       voice_vision   Stopped at model.first_event
                                    end to end: last input 601 ms
                                    segments: vad 601 ms; stt final 651 ms; cutoff 653 ms; to request 3 ms; frame age 757 ms
        failed       text           Stopped at model.first_event
                                    segments: to request 2 ms
        passed       voice          Answered as the task expects; first text 704 ms; first audio frame 711 ms; complete 734 ms  [degraded: vision off]
        no coverage  image_input    No input transport delivers images to a session yet
        not enabled  visual_output  No Character is configured
      PASS  session.cleanup        3 owned parts closed: sessions and executor before the runtime; runner processes, sockets and the temporary workspace reclaimed
```

The text groups the checks as environment, configuration, directories, session and not
verified; `--list` uses the same groups. A passing check is one line; any other shows its
details and next step. Each scenario has its own line; a failed one also shows the figures it
did reach. JSON keeps the flat list of checks, each with `id`, `status`, `summary`, `details`,
`action`, `runners`, `scenarios` and `metrics`; a scenario has `name`, `outcome`, `summary`,
`configuration`, `blocked_stage`, `details`, `task`, `transcript`, `answer` (both bounded),
`metrics`, `segments`, `frames` and `evidence`. Text, JSON and details pass the same output
boundary as `config check`: credentials from the configuration and the environment are
replaced and control characters removed. `--list --json` prints each check's `id`, `title`,
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
`.env`, parses arguments, handles Ctrl+C and prints.

## Not covered

- Client devices, the RTC server and what a client shows or plays: Doctor uses no client.
- Image input and visual output: no transport delivers images to a session, and the Character's
  frames carry no Turn.
- Camera addressing: the picture is shared as a screen, so visual addressing is not exercised.
- Parallel runner workers and long or loaded runs: their own tests, and `alphaavatar test`.
