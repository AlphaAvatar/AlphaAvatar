# AlphaAvatar Host

`alpha-avatar-host` owns application startup, shared inference and hosted execution.
`sessions/` owns interaction attachments; `sessions/livekit/` implements the LiveKit backend.
Core, Agents and RTC do not depend on Host. App is not required to run the command.

## 📦 Package structure

<p align="center">
  <img src="../.github/assets/avatar-host/relationships.png" alt="Package relationships overview" width="100%" />
</p>

```text
alphaavatar/host/
├── main.py                         # Public command entrypoint.
├── version.py                      # Package version.
├── cli/
│   ├── app.py                      # Arguments, help, version and command routing.
│   └── commands/run.py             # Native dev/start commands.
├── log/
│   ├── config.py                   # Levels, color, banner and rotating file settings.
│   ├── runtime.py                  # One Host-owned collector and writer.
│   ├── format.py                   # Timestamp, level, source and message formatting.
│   └── banner.py                   # Terminal adaptation of the AlphaAvatar wordmark.
├── configs/
│   ├── application.py              # Combined Host/Avatar configuration.
│   └── loader.py                   # Strict loading and resolved child snapshots.
├── application/
│   ├── application.py              # AvatarHost and shared-service ownership.
│   ├── bootstrap.py                # Child-side Runtime/Engine/session assembly.
│   ├── config.py                   # Host settings and health configuration.
│   ├── health.py                   # Liveness, readiness and bounded status.
│   └── signals.py                  # Process signals to an owned stop request.
├── execution/
│   ├── execution.py                # Child-local HostExecution: Engine + Runtime.
│   ├── manager.py                  # Parent-side admission and execution handles.
│   ├── policy.py                   # Session-end and control-loss policies.
│   ├── schemas.py                  # Reservations, states and execution views.
│   └── stop.py                     # Stop notification with a first-request reason.
├── processes/
│   ├── supervisor.py               # Execution subprocess supervision.
│   ├── process.py                  # Execution ownership, authenticated IPC and reaping.
│   ├── group.py                    # Dedicated POSIX process-group boundary.
│   ├── entrypoint.py               # Internal child entrypoint; not a public CLI.
│   ├── channel.py                  # Bounded IPC framing.
│   ├── config.py                   # Capacity and process timeouts.
│   └── schemas.py                  # Versioned launch, control and result messages.
└── sessions/
    ├── base.py                     # Backend and connection contracts.
    ├── factory.py                  # Configuration validation and lazy selection.
    ├── manager.py                  # Child-local execution/attachment binding.
    ├── attachment.py               # Transport, adapters and presentation ownership.
    ├── mode.py                     # Text, audio and video interaction modes.
    ├── config.py                   # Backend selection settings.
    ├── schemas.py                  # Requests, participant context and end events.
    └── livekit/
        ├── backend.py              # Dispatch/direct access and adapter assembly.
        ├── config.py               # LiveKit settings and credential validation.
        ├── dispatch.py             # Native control protocol; no SDK worker pool.
        ├── connection.py           # One RTC connection and its events.
        └── character.py            # Scoped renderer credentials and readiness.
```

Ordinary package initializers are omitted. The three `schemas.py` entries are files,
not directories. The PNGs are conceptual overviews; process placement and lifecycle
ownership are defined by the descriptions below, not by every arrow in those sketches.

## Run

The sole public entrypoint is `alphaavatar.host.main:main`:

```bash
alphaavatar --help
alphaavatar --version
ENV_FILE=.env.dev alphaavatar dev examples/agent_configs/mm/pipeline_openai_tools.yaml
alphaavatar start examples/agent_configs/mm/pipeline_openai_tools.yaml
```

`dev` enables DEBUG logging and an ephemeral health port by default; it does not
watch files or restart executions. `start` defaults to INFO and health port 8081.
Help and version do not initialize models, inference, RTC or credentials. Overrides
remain `key=value` arguments after the filename. Installer, TUI and Doctor are not
implemented by these commands.

Both LiveKit modes require `LIVEKIT_URL`, `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET`
in the environment or the selected environment file. Remote LiveKit URLs require
TLS; loopback development can use an unencrypted local endpoint. Model, embedding
and tool providers require their own configured credentials. Do not commit secrets.

For files stored on your machine, see [Avatar workspace](../docs/avatar-workspace-layout.md)
and [Model cache](../docs/models-cache-layout.md). These are user-facing storage,
backup and cleanup guides, not implementation reports.

## Connection modes

| Mode | Room source | Host lifetime |
| --- | --- | --- |
| `dispatch` (default) | Named LiveKit dispatch assignment. | Continues accepting new jobs after individual executions end. |
| `direct` | Explicit `room_name` in Host configuration. | Runs one execution, then exits and releases shared services. |

Both modes use the same execution supervisor and child-side assembly. `direct`
still connects to LiveKit; it is neither peer-to-peer nor offline operation.
Connection mode is independent of `dev/start` and participant `session_type`.

Add this Host section alongside the existing Avatar configuration:

```yaml
host:
  rtc:
    backend: livekit
    init_config:
      connection_mode: dispatch

  execution:
    on_session_end: finish_execution
    on_control_loss: finish_execution
```

Dispatch registers using `avatar.name`; the sender must request that agent name.
The assignment supplies the room and token, so do not configure `room_name` in
this mode. Starting Host alone does not create a participant interaction.

For one fixed room, change the connection settings to:

```yaml
host:
  rtc:
    backend: livekit
    init_config:
      connection_mode: direct
      room_name: host-review-room
      # Optional remote user identity, not the Avatar name:
      # participant_identity: demo-user
```

The same setting can be overridden without copying a complete configuration:

```bash
ENV_FILE=.env.dev alphaavatar dev examples/agent_configs/mm/pipeline_openai_tools.yaml \
  host.rtc.init_config.connection_mode=direct \
  host.rtc.init_config.room_name=host-review-room
```

An explicit `participant_identity` selects the remote user. Without it, the
connection selects the first eligible standard/SIP participant. The selected
participant leaving ends that attachment; this is not a multi-user room service.
Participant readiness defaults to 60 seconds and also falls within the execution
process's total startup deadline.

Interaction mode comes from participant metadata, not dispatch-job metadata:
`chat` and `agent` are text modes, `audio` enables audio, and `video` also enables
configured visual input. The default is `video`. Direct mode does not disable TTS;
use participant metadata such as `{"session_type": "chat"}` for text-only testing.

## Ownership and startup

<p align="center">
  <img src="../.github/assets/avatar-host/start-up-flow.png" alt="Startup flow overview" width="100%" />
</p>

AvatarHost owns shared inference and parent-side ExecutionManager/ProcessSupervisor.
The parent starts a child process and holds its execution handle, not its Engine.
Only then does child-side bootstrap create HostExecution, SessionManager and the
single SessionAttachment. Bootstrap does not construct child Engine objects in
advance in the parent process.

SessionManager starts Character readiness, outputs, Engine and inputs in that order.
Detachment releases the attachment's adapters, subscriptions, presentation and
connection; it does not close HostExecution. The Host's `finish_execution` policy
then settles Engine and Runtime. Shared inference closes only when the entire Host
shuts down, after execution children are reaped—not after each dispatch session.
InferenceRuntime remains the sole owner of its own serial runner processes.
Core lifecycle and managed cleanup are reused.

## Control loss and result semantics

`host.execution.on_control_loss: finish_execution` is the supported control-loss
policy. Losing a registered LiveKit control connection makes the backend unready,
cancels its outstanding reservations and asks Host to stop and reap the exact
assigned executions. Only then may a fresh registration accept new jobs. Shared
inference remains alive unless the whole Host must stop.

A new worker registration does not restore old job ownership. Old jobs are not
replayed, resumed or reported as belonging to the new registration. There is no
unverified migration/resume switch. This deliberately ends affected conversations
even when their RTC media connection is still alive.

`stop_reason` retains the first accepted stop request independently of final
`outcome` and `reason`. A cleanup error or forced kill cannot turn an unknown tool
result into success. Process `success` means orderly lifecycle completion, not proof
that every tool succeeded or that the user heard every response.

## Process shutdown and diagnostics

Hosted execution subprocesses currently require POSIX process groups. Each child
starts a new OS session, separate from Host and shared inference. Platforms without
this implementation are rejected when constructing the supervisor; there is no unverified Windows
process-tree fallback.

Closing first requests orderly execution shutdown over IPC. When that deadline
expires, Host sends SIGTERM to the execution group, then SIGKILL if necessary.
Both escalation waits have finite deadlines. Even when the main child has already
exited, remaining processes in its original group must disappear before that scope
is considered reaped. Forced cleanup changes the execution outcome to `unknown`,
even if the child previously reported success. No model or tool work is replayed.

These optional settings belong in the existing top-level Host section:

```yaml
host:
  processes:
    startup_timeout: 120.0
    shutdown_timeout: 180.0
    terminate_timeout: 5.0
    kill_timeout: 5.0
    ipc_timeout: 5.0
```

`kill_timeout` bounds the final exit-confirmation wait after SIGKILL. If exit cannot
be confirmed, cleanup raises, the supervisor retains the unresolved handle and
admission becomes unhealthy rather than treating that execution as safely reclaimed.
Shared inference is not explicitly closed while owned execution scopes remain.
These are phase deadlines, not a total wall-clock shutdown guarantee: OS process
creation is shielded and joined before releasing ownership, so a late acquisition
cannot be abandoned merely because its caller was cancelled. Abruptly killing Host
itself is outside this in-process cleanup guarantee.

**A process group is not a complete descendant container or a security sandbox.**
A child can create another session/group and leave this boundary. Playwright's
browser launcher does this on POSIX; therefore group reclamation is not proof that
every AIRI browser process has ended after a crash. Normal Character shutdown still
owns browser/driver cleanup. Deployments requiring forced cleanup across detached
browser processes need an independently managed containment boundary, such as an
execution-scoped cgroup/container; this package does not create one. Do not kill the
Host's inherited process group or use global browser-process name matching.
Containers must also provide an init/reaper for orphaned processes. Unreaped zombie
members are treated conservatively as an unconfirmed group, not silently ignored.

CLI, execution-child and inference failures share `alphaavatar.core.log.diagnostics.format_error`.
Child diagnostics identify import, configuration restoration, assembly and execution
stages. `dev` includes bounded module/function/line traces and exception-group causes;
normal mode retains the nearest location. Diagnostics do not render exception message
bodies, source lines, locals or configuration input values. This is not a guarantee
that every third-party library log is redacted.

## Inference startup progress

Host reports the health port before inference warmup begins. Each configured runner
then produces lifecycle logs with its method name, startup progress and elapsed time.
Initialization and request execution remain serial within the existing runner design;
these logs do not enable additional runner replicas or replay failed work.

`/status` includes an `inference_runners` array in configuration order:

| Field | Meaning |
| --- | --- |
| `method` | The configured inference method, not a model Run ID. |
| `startup_state` | `pending`, `initializing`, `ready`, `failed` or `cancelled`. |
| `ready` | Whether the runner is currently ready and the inference service is not closing. |
| `startup_elapsed_seconds` | Monotonic elapsed time; live during startup, fixed afterward, and null before an attempt. |
| `error_type` | The parent-observed exception class for failed or cancelled startup; no exception message. |

Startup history and current readiness are separate. A runner which initialized and
later exited retains `startup_state: ready` but has `ready: false`. A runner which was
never attempted remains `pending`, including when an earlier runner failed. Elapsed
time covers process acquisition and initialization; a failed or cancelled start can
also include rollback before it returns. It is not model inference latency.

Snapshots are immutable values. Reading status does not issue inference requests,
load models, inspect request payloads, or change admission. Lifecycle logs are emitted
only at startup and shutdown transitions, not for each audio frame, token or inference
request. Host explicitly configures the diagnostic logger described below. Python
stdout/stderr emitted during isolated runner initialization, including InsightFace's
model-discovery prints, use the same formatter. This does not intercept native C/C++
writes directly to OS file descriptors or arbitrary output after initialization.

## Logging

`log/` owns console presentation and the single application log writer. Terminals show
an ALPHAAVATAR pixel banner in the existing brand blue/cyan palette, with the exact
`AlphaAvatar` name, current package version and mode beneath it. The seven-row wordmark
uses double-width pixels when space permits, single-width pixels on ordinary terminals,
and compact text on narrow terminals or redirected output. ASCII-only terminals use `#`
instead of block characters. No font, image library or additional dependency is loaded.
Only the main Host prints the banner, before its buffered startup records.

Console records show a millisecond timestamp with timezone, colored severity, source
file and line, PID, then content. Installed third-party files retain their package path,
for example `httpx/_client.py`, rather than an ambiguous basename. Multiline messages
receive a prefix on every line.
With `color: auto`, terminals use color and redirected output stays plain. `NO_COLOR`
and `TERM=dumb` disable color even when `color: always` is selected. File output is JSONL without color or banners. Third-party DEBUG is suppressed
by default, independently of the application's `dev` level.

Settings are optional and go beside `rtc`, `processes` and `execution`:

```yaml
host:
  log:
    level: null                  # dev: DEBUG; start: INFO.
    third_party_level: INFO
    color: auto                  # auto, always, never; NO_COLOR still takes precedence.
    banner: true
    file: true
    directory: null              # Resolved Avatar workspace/.logs/host.
    rotate_bytes: 10485760
    backup_count: 3
    shutdown_timeout: 3.0
```

The file name is `alphaavatar-<UTC timestamp>-<pid>.jsonl`, unique to an invocation.
The current file and up to three rotated files are retained by default. Earlier
invocations are not automatically deleted; manage retention separately. Files are
created with mode 0600. Do not share logs without reviewing them for personal data.
See [Avatar workspace](../docs/avatar-workspace-layout.md#find-your-logs-and-temporary-files)
for finding logs, backups and cleanup.

Host is the only disk/terminal writer. Parent, execution children and inference workers
submit bounded JSON datagrams through a private local socket. Formatting and rotation
run on a dedicated writer thread, not on the media event loop. Producers never wait
for disk or terminal I/O: a full socket queue drops diagnostic records, and a later
accepted record reports their count. A final loss report is best effort. Logs are not
canonical tool records, a lossless audit journal, or proof of successful execution.

Core's `log/` contains the reusable producer, bounded record contract, safe exception
diagnostics and scoped Python-stream capture; it imports neither Host nor model SDKs.
Imports do not install handlers. The owning entrypoint installs and later restores
logging explicitly. Existing non-propagating third-party handlers and native fd output
are outside this collection path; no global monkey patch replaces `print()`.

Credential-key patterns, Cookie headers, explicit MCP session headers, known secret
environment values and terminal controls are filtered. MCP transport logger messages also
mask session identifiers, including `Received session ID`, without hiding AlphaAvatar's
own session/turn/run correlation fields. Producers filter before submission; the Host
filters again before terminal/file output. Importing the MCP plugin does not install
filters on HTTPX or other global loggers. The log formatter never calls arbitrary SDK
objects' `__str__`; such values remain type placeholders, for example `<URL>`. String URLs
retain only their public endpoint form, without credentials, query strings or fragments. Exception messages, source lines and locals are
not rendered by diagnostic exception formatting. This is best effort, not permission
to log raw audio, user text, credentials or arbitrary SDK objects. Record payloads,
partial captured lines and startup buffering are bounded. A blocked or failed sink can
cause loss and a failed diagnostic drain; it does not acquire execution ownership.

## Terminal interruption

Host handles SIGINT/SIGTERM as an idempotent shutdown request. Repeated Ctrl+C does
not cancel the owned resource-cleanup sequence. Execution subprocesses retain their
separate process groups and cooperative stop protocol.

Inference workers remain exclusively owned by InferenceRuntime. Their launching
thread masks SIGINT over spawn bootstrap and then restores its own prior mask. The
child installs SIGINT-ignore before loading its selected runner. Host remains
interruptible throughout. Workers stop through the existing CLOSE/CLOSED protocol;
SIGTERM remains available for forced reclamation. Model code is imported by its
registered module/class identity after the child signal and logging policy is installed.
No extra runner pool, concurrent inference replicas or second process owner is added.

Actual runner cleanup errors, dead workers and failed shutdown acknowledgements still
fail visibly. They are not downgraded to success because Ctrl+C was pressed. The
logger drains only after application cleanup has returned and the async loop has
settled; a diagnostic writer timeout is also reported rather than called a successful
flush. Abrupt Host termination, detached browser containment and uncooperative native
code remain subject to the process boundaries documented above.

## Health and current limits

The health service exposes `/live`, `/ready` and `/status`. Its listening port is
reported during startup; `dev` normally selects an available port. `/status`
contains bounded recent execution summaries, not an authenticated administration API.
Restrict access through deployment networking and do not expose it publicly.

One attachment per execution is supported; reattachment, persistent Episodes,
restart recovery, sleep/wake and Dream scheduling are not. Detachment never implies
room deletion. Dedupe is bounded and process-local, not durable exactly-once execution.

The `livekit` extra selects RTC/API/protocol libraries, not the Agents SDK.
Real LiveKit/server/client/provider validation remains a separate deployment gate.
Optional presentation follows [Character setup](../avatar-plugins/perception/avatar-plugins-character/README.md).
