# `alphaavatar config`

Create or check application configuration. Neither subcommand starts anything.

## Bundles and profiles

A **bundle** is a complete, startable configuration. A **profile** is one section that bundles
reference and may share. Both live in the application home:

| File | Holds |
| --- | --- |
| `<home>/configs/bundles/<name>.yaml` | `avatar` (and any section set inline), plus `profiles` |
| `<home>/configs/profiles/<name>.yaml` | One section's body, for example `voice`; `<name>` may have `/` parts |
| `<home>/settings/settings.yaml` | `default_bundle`, the stored credentials' file (`credentials`) and other user settings |
| `<home>/settings/credentials-<id>.env` | Credentials [`alphaavatar setup`](setup.md) stored, readable only by you |

```yaml
# configs/bundles/my-avatar.yaml
avatar:
  id: my-avatar
profiles:
  host: my-avatar/host/host                     # configs/profiles/my-avatar/host/host.yaml
  runtime: my-avatar/agent/runtime
  voice: my-avatar/plugins/foundation/voice
  memory: my-avatar/plugins/perception/memory
```

- `profiles` maps a section to a profile name: `host`, `runtime`, or a plugin section
  (`context`, `loop`, `voice`, `vision`, `status`, `router`, `character`, `memory`, `persona`,
  `tools`). `avatar`, the Avatar's identity, stays in the bundle.
- Profiles are grouped in layers: `host`, `agent` (`runtime`), and `plugins/foundation`,
  `plugins/perception` and `plugins/tools`. `config init` writes them this way and
  `config check` reports in the same layers; any other name works too.
- A profile file is that section's body. It references nothing, so references never form a
  cycle; a profile with its own `profiles` is rejected.
- A section comes from the bundle or from one profile, never both.
- Names use 1-64 lowercase letters, digits, `-` or `_`; profile names add `/` between parts.
  They are never paths and resolve inside the home, whatever the working directory.
- With symbolic links resolved, a named bundle must stay in `configs/bundles` and a profile in
  `configs/profiles`, both inside the real home; a link out of the home is an error. A home
  reached through an alias, and links that stay inside the home, are fine.
- YAML anchors do not cross files. `${...}` interpolation resolves after composition, as in a
  single file.
- The home is chosen as before: `application.home` override, then `ALPHAAVATAR_HOME`, then the
  platform default. Settings never choose it, and a named bundle cannot move it.
- A single YAML or JSON file still loads as before, and may use `profiles` too.

## Choosing a configuration

`config check`, [`doctor`](doctor.md), `start` and `dev` take the same optional argument:

| Argument | Loads |
| --- | --- |
| Contains `/` or has an extension, e.g. `./avatar.yaml` | That file, relative to the working directory |
| Any other word, e.g. `my-avatar` | `<home>/configs/bundles/my-avatar.yaml` |
| Omitted | The bundle named by `default_bundle` in settings |

- The spelling decides. A missing bundle is an error and never falls back to a file of a
  similar name, nor the reverse.
- With no argument and no default bundle, the command fails and says how to create one.
- `KEY=VALUE` arguments are always overrides, so `alphaavatar config check voice.tts.speed=1.2`
  checks the default bundle.
- `profiles.<section>=<name>` chooses another profile. Every other override applies to the
  composed configuration, after profiles are placed.
- After loading, the Host and its sessions use the accepted snapshot; later edits to profiles
  take effect at the next start.

## Credentials

`start`, `dev`, `config check` and [`doctor`](doctor.md) take each variable from the first of:

1. the environment;
2. the `.env` file `ENV_FILE` names (default `.env`);
3. the credentials [`alphaavatar setup`](setup.md) stored, in the file the settings name.

- The default bundle comes from the same read of the settings as the stored credentials: a
  setup committing meanwhile changes neither.
- Settings or stored credentials that cannot be read (invalid YAML or UTF-8, a stored file
  missing, anything but a regular file) give no stored credentials: a named bundle or a file
  still loads, and a run without a configuration argument fails, naming the file to fix.
- YAML reads a variable as `${oc.env:NAME}`; credentials never go in bundle or profile files.
- A key variable setup names after a server of your own, `ALPHAAVATAR_SERVER_KEY_<hash>`, is
  checked against the `base_url` in effect: a bundle whose `base_url` was moved to another
  server, or removed, fails at the setting that holds them, such as `loop.init_config.model`.
  See [setup's credentials](setup.md#credentials).

## `config init`

Create a minimal bundle, its profiles and, if none is set, the default bundle.

```bash
alphaavatar config init <name> --avatar-id <id>
```

```text
Created bundle my-avatar
  bundle    /home/me/.local/share/alphaavatar/configs/bundles/my-avatar.yaml
  profiles  /home/me/.local/share/alphaavatar/configs/profiles/my-avatar  (host, agent, plugins/foundation, plugins/perception, plugins/tools)
  default   my-avatar (set as the default bundle)
```

- Writes the given Avatar ID with OpenAI model, voice, Memory and Persona profiles; tools are
  disabled. Host, runtime, context, status, router and character profiles write out their
  defaults to be edited, as does memory's `environment` (ENV memory) switch, off. The composed
  result behaves as the former single-file template.

```text
configs/bundles/my-avatar.yaml                 avatar, plus the profiles below
configs/profiles/my-avatar/
  host/host.yaml                               RTC transport, health, logs, doctor
  agent/runtime.yaml                           inference runners
  plugins/foundation/{context,loop,voice,vision}.yaml
  plugins/perception/{status,router,character,memory,persona}.yaml
  plugins/tools/tools.yaml                     deepresearch, rag, mcp
```
- Writes no credentials and no machine paths.
- In the Linux package before `alphaavatar setup` has run, it names setup as the next step:
  the bundle stays as written, and `config check` names what it needs installed.
- Never overwrites an existing bundle or profile file; existing directories are reused.
  Checks each target as loading would: a bundle must stay in `configs/bundles`, a profile in
  `configs/profiles`, and the settings in `settings`, inside the real home.
- Sets `default_bundle` only when none is set. Reading, deciding and replacing the settings
  happen under one lock (`settings/.write.lock`, kept by the lock library), so concurrent
  `init` runs never both become the default. A lock file that is a symbolic link is refused,
  since opening it would empty what it points to.
- Appends `default_bundle` when the file is a plain block mapping, keeping other settings and
  comments. Otherwise — `default_bundle: null`, a flow mapping, an explicit document end — it
  writes the same values again, without comments. Settings are replaced atomically.
- Replacing the settings commits the bundle. Before that, a failure or Ctrl+C removes only the
  files and empty directories it created; existing files, shared profiles and settings stay
  unchanged, and the settings lock file may remain. After it, the complete bundle stays and
  the interruption is still reported.

Set these in the environment or `.env`, never in the files:

| Variable | Used for |
| --- | --- |
| `OPENAI_API_KEY` | Models, speech, embeddings, Memory and Persona |
| `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | Session transport |

Then start it with [`alphaavatar dev my-avatar`](dev.md), or check it first.

## `config check`

Validate a configuration without starting anything. Optional: `start` and `dev` run the same
validation before they start.

```bash
alphaavatar config check [<bundle> | <file>] [KEY=VALUE ...] [--json]
```

It runs the same loading steps as `start` — `.env` and the stored [credentials](#credentials),
selection, profiles, overrides, defaults,
path resolution, schema validation, read-only workspace checks, and the built-in plugins' own
settings schemas (realtime loop, context, router, memory, persona; for example a loop without
`model` fails at `loop.init_config.model`) — but starts no Host,
runner or model, contacts no service, creates no directories or settings and needs no local
log socket.

```text
OK  configuration and read-only path checks passed
    config          bundle my-avatar  (default)
    avatar_id       my-avatar
    home            /home/me/.local/share/alphaavatar
    workspace       /home/me/.local/share/alphaavatar/avatars/my-avatar
    host
      rtc           livekit
      health        127.0.0.1:8081 (dev: free port)
    agent
      inference     8 runners  (workers: alphaavatar.voice.vad.silero x2)
    plugins/foundation
      context       default
      loop          realtime
      voice         vad=silero  stt=openai_segment  tts=openai
      vision        on  (input: vlm)
    plugins/perception
      status        default
      router        default  (audio activity on, semantic addressing on, visual addressing on, turn taking on, interruption on)
      character     none
      memory        default  (vdb: lancedb; retrieval on, conversation on, tool on, environment off)
      persona       default  (vdb: lancedb; profiler on, speaker on, face off)
    plugins/tools
      deepresearch  none
      rag           default
      mcp           default  (1 server)
```

The summary lists the checked file or bundle, then facts in the profile layers: plugin
selections, vision and its input, the
on/off switches of the built-in router, status, memory (including `environment`, the ENV memory)
and persona processors, vector store kinds, enabled tools, the inference runners the Host would
start with their worker counts, and the health address — never endpoints, collection names or
other plugin-defined settings. Switches are read with each plugin's own schema, so an omitted
switch shows its default; `--json` gives the same values under `plugins`: `vision`, `router`
and `status` are objects (`plugin` and their switches; `router` and `status` were plugin-name
strings before v0.6.9), and `memory` and `persona` carry their processor switches. A misspelled,
unselected or non-replicable `runtime.inference.methods` entry fails with its field location.

```text
ERROR  configuration and read-only path checks failed
  error: ValidationError
    fields: avatar.timezone
```

```text
ERROR  configuration and read-only path checks failed
  error: ConfigReferenceError
    Bundle 'my-avatar': profiles.voice references missing profile 'my-avatar/voice': /home/me/.local/share/alphaavatar/configs/profiles/my-avatar/voice.yaml
```

- Errors go to stderr and name the failing fields, bundle or profile, never the rejected
  values or file contents.
- `--json` prints `{"valid": true, "config", "avatar_id", "home", "workspace", "plugins",
  "inference", "health"}` (`config` is `{"bundle", "default", "file"}`; `inference` maps each
  runner method to its workers) or `{"valid": false, "error": {"type", "fields",
  "diagnostic"}}`, with credentials and control characters removed.
- Colors appear only on a terminal; pipes, `NO_COLOR` and `TERM=dumb` get plain text.

## Exit codes

| Code | `init` | `check` |
| --- | --- | --- |
| 0 | Created | Valid |
| 2 | File exists, invalid name or ID, unreadable settings or write failure | Invalid configuration, selection or reference, failed path check, or unreadable settings or stored credentials with no configuration argument |
