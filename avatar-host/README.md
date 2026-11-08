# AlphaAvatar Host

`alpha-avatar-host` starts AlphaAvatar, owns shared inference, and supervises Avatar
executions. Interaction connections belong to session backends; Agents, Core and RTC
do not depend on Host. The App is not required to run the service.

## 📦 Package structure

```text
alphaavatar/host/
├── main.py             # Public alphaavatar command.
├── version.py
├── cli/                # dev/start, arguments, help and version.
├── configs/            # Strict Host/Avatar configuration loading.
├── workspace/          # Application, config and cache paths; Workspace continuity.
├── application/        # Bootstrap, shared services, health and signals.
├── execution/          # Hosted execution ownership and end policies.
├── processes/          # Execution subprocesses, IPC and bounded cleanup.
├── sessions/           # Attachments, modes and backend selection.
│   └── livekit/        # Native dispatch, connections and Character transport.
└── log/                # Console, JSONL, previews and optional event diagnostics.
```

[Startup overview](../.github/assets/avatar-host/start-up-flow.png) ·
[Package overview](../.github/assets/avatar-host/relationships.png)

The diagrams are conceptual. Host holds execution handles in the parent process;
Engine, Runtime and their session adapters are assembled inside execution children.

## Run

Use the repository's Python 3.13 environment and your configured provider credentials:

```bash
alphaavatar --help
alphaavatar --version
ENV_FILE=.env.dev alphaavatar dev examples/agent_configs/mm/pipeline_openai_tools.yaml
alphaavatar start examples/agent_configs/mm/pipeline_openai_tools.yaml
```

`dev` defaults to DEBUG and an available health port; it does not watch or reload code.
`start` defaults to INFO and port 8081. Help/version do not start models or require RTC
credentials. Each command takes a bundle name, a YAML/JSON file, or nothing for the default
bundle; configuration overrides use `key=value` after it.

Create a bundle (with its profiles, and as the default if none is set), and optionally check
it without starting anything:

```bash
alphaavatar config init my-avatar --avatar-id my-avatar
alphaavatar config check my-avatar voice.tts.speed=1.2
alphaavatar doctor my-avatar          # installation, configuration, a diagnostic session
alphaavatar dev                       # the default bundle
```

`start` and `dev` run the same validation before starting. See [docs/cli](../docs/cli/) for
every command and the bundle layout. The Python entry points live in
`alphaavatar.host.configs` (`select_configuration`, `load_application`,
`check_application_paths`, `validate_plugin_settings`, `create_bundle`, `read_settings`,
`describe_summary`, `describe_application`, `describe_error`, `format_failure`,
`output_scrubber`); Doctor's report comes from `alphaavatar.host.doctor.diagnose` (async),
or `prepare` and `Diagnosis.run` to run the static checks first.

## Configuration

Keep the existing Avatar settings at the top level and add Host settings beside them:

```yaml
host:
  rtc:
    backend: livekit
    init_config:
      connection_mode: dispatch
  log:
    events: false
    conversation:
      content: dev
      file_content: false
```

LiveKit requires `LIVEKIT_URL`, `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET`. Model and
tool providers need their own credentials. Remote endpoints require TLS.

| Connection mode | Behavior |
| --- | --- |
| `dispatch` | Registers using `avatar.name` and waits for matching explicit dispatches. The assignment supplies the room. Host remains available after a session ends. |
| `direct` | Requires `room_name`, optionally selects `device_id`, and exits after its single execution ends. It still requires LiveKit. |

The remote participant's `session_type` metadata selects `chat`, `agent`, `audio` or
`video`; the default is `video`. This is independent of connection mode and `dev/start`.

Logs show time, severity, source location, PID and content. `dev` previews committed user
input and recorded assistant text; `content: off` hides those previews and `content: all`
enables them in both commands. JSONL files are saved under the resolved Avatar workspace's
`.logs/host/`; conversation text is excluded unless `file_content: true`. Console capture
and provider traces have separate retention. Review all logs for personal data before sharing.

`host.log.events=true` with DEBUG enables sampled Core event metadata and gap diagnostics.
These logs preserve source stream identities and sequence numbers; they are not lossless
records or a globally ordered replay log. Do not log raw media or credentials.

## Runtime boundaries

Host starts outputs before Engine and inputs. Detaching a session releases its adapters;
Host policy decides when its execution ends. Shared inference closes only after execution
children settle, and InferenceRuntime remains the sole owner of its runner processes.
Ctrl+C/SIGTERM request orderly shutdown; repeated Ctrl+C does not abandon cleanup.

Audio sessions use playback-driven captions through `TranscriptSynchronizationProcessor`.
PCM streams at the provider's native pace; caption publication and network sending do not
pace audio capture. PCM-only providers use estimated word timing, corrected by measured
audio duration. LiveKit playback feedback measures the local audio queue, not remote speakers.

The health endpoints are `/live`, `/ready` and `/status`. They are unauthenticated and bind
to `127.0.0.1` by default; set `host.health.bind` explicitly only behind network controls.
`/status` reports readiness, runner startup states and recent execution ids and codes; it
returns no configuration or credentials.
Execution supervision requires POSIX. Process groups are not complete descendant sandboxes;
deployments that need containment of detached browsers require an external cgroup/container.
One attachment per execution is supported. Reattachment, persistent execution recovery and
sleep/wake are not implemented. Control loss finishes affected jobs before re-registration;
it does not replay model or tool work. Disconnecting does not delete the room.

## More information

[Deployment](../docs/DEPLOY.md) · [Development](../CONTRIBUTING.md) ·
[Avatar workspace](../docs/avatar-workspace-layout.md) ·
[Model cache](../docs/models-cache-layout.md) ·
[Character setup](../avatar-plugins/perception/avatar-plugins-character/README.md)
