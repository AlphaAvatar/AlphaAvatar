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

`start`, `dev`, `config check`, [`doctor`](doctor.md), [`setup`](setup.md) and
[`upgrade`](upgrade.md) take each credential from the first of these that holds a value,
neither empty nor only whitespace ([`cleanup`](cleanup.md) reads the first two so, for the home):

1. the environment;
2. the `.env` file `ENV_FILE` names (default `.env`);
3. the credentials [`alphaavatar setup`](setup.md) stored, in the file the settings name.

- The credentials are the variables the configuration names for them, under any name: each
  `api_key_env` as it is once interpolated, such as `${oc.env:TTS_KEY_NAME,MODEL_AUTH}` (a
  bundle's own, a server of your own's `ALPHAAVATAR_SERVER_KEY_<hash>`); in its MCP servers,
  each `<NAME>` placeholder and each `${oc.env:NAME}` of an `Authorization` header; those
  components read when it names none (`OPENAI_API_KEY`, `OPENROUTER_API_KEY`,
  `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `VOICEAI_API_KEY`, `TAVILY_API_KEY`, `QDRANT_URL`,
  `QDRANT_API_KEY` and the three `LIVEKIT_*`); and those setup stored.
- An empty or blank credential counts as unset: it gives way to the next source and never takes
  another's place, and a value is taken as it is set, spaces and all.
- `.env` itself loads as python-dotenv loads it: a variable the environment sets stays, empty
  too, so an empty `CUDA_VISIBLE_DEVICES` still hides every GPU and an empty
  `ALPHAAVATAR_MODEL_OFFLINE` still allows downloads; an empty line sets its variable empty.
  It is parsed once: `${NAME}` reads the environment's value first, then the file's earlier
  lines, never a later one; it reads a credential as the environment holds it, before the
  credentials are filled.
- In the configuration, `${oc.env:NAME}` reads a default or stored credential, and one an
  `Authorization` header names, once it is filled. Any other, such as an MCP server's
  `X-Region: ${oc.env:REGION}`, reads an ordinary variable as the environment holds it, empty
  too, and logs show its value. `\${oc.env:NAME}` is text, as OmegaConf escapes it, and reads
  nothing.
- `upgrade` reads `.env` once, and the target build's plan and check, which run from `/`, read
  those values instead of a file: the ones they read are the ones `upgrade` read.
- `ALPHAAVATAR_HOME`, which chooses the home that stores credentials, counts empty or blank as
  unset too: the file's value then chooses it.
- A credential unset, empty or blank everywhere is missing: what reads it refuses to start and
  names the variable, never its value. Logs hide the values of the credentials the
  configuration names and of servers' keys, as they hide those whose names say they are one.
- A variable the configuration itself reads that holds no value fails loading, in every
  command, at the setting that reads it, by name: where MCP is created (`enabled` with a
  `plugin`), a server's credential unset, empty or blank once filled, by `<NAME>` placeholder
  or by `${oc.env:NAME}` in `Authorization` (never sent as `Bearer `); and any other
  `${oc.env:NAME}` without a default whose variable is unset (one set empty interpolates as
  empty; write an empty default as `${oc.env:NAME,''}`: `${oc.env:NAME,}` means the same, but
  OmegaConf warns that this form is deprecated). In `Authorization`, each call is taken as
  OmegaConf evaluates it, nested defaults included: `${oc.env:NAME,default}` takes its default
  only while `NAME` is unset, so an empty or blank `NAME`, or a default that holds no value,
  is refused too. An MCP not created sends nothing and requires none, though its settings
  still interpolate.
  [`config check`](#config-check) shows how it is reported.

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

Create the reference bundle, its profiles and, if none is set, the default bundle: the
reference configuration (`examples/agent_configs/roles/demo.yaml`) with no tool on. Voice and
vision are on, memory with ENV memory and persona, the models from OpenAI and ENV memory's from
Google.

```bash
alphaavatar config init <name> --avatar-id <id>
```

```text
AlphaAvatar / Config init
OK    Bundle created

Configuration
  Bundle       my-avatar
  Profiles     ~/.local/share/alphaavatar/configs/profiles/my-avatar
  Default      my-avatar

Required credentials
  OPENAI_API_KEY
  GOOGLE_API_KEY
  LIVEKIT_URL · LIVEKIT_API_KEY · LIVEKIT_API_SECRET

Next
  alphaavatar config check my-avatar
  alphaavatar doctor my-avatar
```

- `Default` names another bundle, `(unchanged)`, when one is set already. The credentials are
  named only, never shown. In the Linux package before [`alphaavatar setup`](setup.md) has run,
  `Next` is `alphaavatar setup my-avatar`, which installs what the bundle needs, checks it and
  enables it.

- Writes the given Avatar ID with every public setting written out: the reference's value,
  or its schema's default where the reference names none, with comments, to be edited. The
  profiles ship in the package; the reference file is not needed. Tools are off. Switched on
  in `tools.yaml`, DeepResearch and MCP are installed by `alphaavatar setup <bundle>`, as this
  release's catalog offers them; it does not offer RAG, which `config check` and `setup` name
  at `tools.rag.plugin`.

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
- In the Linux package before `alphaavatar setup` has run, it names `alphaavatar setup <name>`
  as the next step: the bundle stays as written, edits included, and `config check` names
  what it needs installed until setup has installed it.
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

Check it, then diagnose it with [`alphaavatar doctor my-avatar`](doctor.md), before starting it
with [`alphaavatar dev my-avatar`](dev.md).

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
AlphaAvatar / Config check
OK    Configuration and read-only path checks passed

Configuration
  config         bundle my-avatar  (default)
  avatar_id      my-avatar
  home           /home/me/.local/share/alphaavatar
  workspace      /home/me/.local/share/alphaavatar/avatars/my-avatar

host
  rtc            livekit
  health         127.0.0.1:8081 (dev: free port)

agent
  inference      8 runners  (workers: alphaavatar.voice.vad.silero x2)

plugins/foundation
  context        default
  loop           realtime
  voice          vad=silero  stt=openai_segment  tts=openai
  vision         on  (input: vlm)

plugins/perception
  status         default
  router         default  (audio activity on, semantic addressing on, visual addressing on, turn
                 taking on, interruption on)
  character      none
  memory         default  (vdb: lancedb; retrieval on, conversation on, tool on, environment off)
  persona        default  (vdb: lancedb; profiler on, speaker on, face off)

plugins/tools
  deepresearch   none
  rag            default
  mcp            default  (1 server)
```

The summary lists the checked file or bundle, then facts in the profile layers: plugin
selections, vision and its input, the
on/off switches of the built-in router, status, memory (including `environment`, the ENV memory)
and persona processors, vector store kinds, enabled tools, the inference runners the Host would
start with their worker counts, and the health address — never service URLs, collection names or
other plugin-defined settings. Switches are read with each plugin's own schema, so an omitted
switch shows its default; `--json` gives the same values under `plugins`: `vision`, `router`
and `status` are objects (`plugin` and their switches; `router` and `status` were plugin-name
strings before v0.6.9), and `memory` and `persona` carry their processor switches. A misspelled,
unselected or non-replicable `runtime.inference.methods` entry fails with its field location.

```text
AlphaAvatar / Config check
ERROR Configuration and read-only path checks failed

  error: ValidationError
    fields: avatar.timezone
```

```text
AlphaAvatar / Config check
ERROR Configuration and read-only path checks failed

  error: ConfigReferenceError
    Bundle 'my-avatar': profiles.voice references missing profile 'my-avatar/voice': /home/me/.local/share/alphaavatar/configs/profiles/my-avatar/voice.yaml
```

A variable that holds no value is named at the setting that reads it, the MCP server and the
header included; a credential (a `<NAME>` placeholder, or `${oc.env:NAME}` in `Authorization`)
was looked for in the environment, the `.env` file and the stored credentials:

```text
AlphaAvatar / Config check
ERROR Configuration and read-only path checks failed

  error: MissingVariables
    Variables the configuration reads hold no value; set them in the environment or in the .env
    file ENV_FILE names (default .env):
      tools.mcp.servers.code.headers.Authorization reads the credential GITHUB_PAT, which is not set
      tools.mcp.servers.code.headers.X-Region reads REGION, which is not set, and ${oc.env:REGION} has no default
```

Interpolation comes first, so a `<NAME>` placeholder is reported once those are set
(`tools.mcp.servers.docs.headers.Authorization reads the credential MCP_PAT, which is empty`);
other fields validation refused with it are named by their path alone (`avatar.timezone is not
valid`). An interpolation that fails otherwise, such as one referencing no setting, is named
at its setting, with any such variables (`avatar.timezone holds an interpolation that cannot be
resolved`). In an installed package, an implementation no installed package provides says
whether this release's setup installs it, with the command for the bundle checked:
`` loop.plugin: no installed package provides loop 'realtime'; `alphaavatar setup my-avatar`
installs it (alpha-avatar-plugins-loop) ``. For a configuration file, which setup does not take,
it says `setup installs it for a bundle, not a file`, and gives no command.

- Errors go to stderr, stdout stays empty, and name the failing fields, bundle, profile or
  variable, never the rejected values, file contents, validation messages or an exception's own
  text. Their lines print whole where the terminal holds them; a narrower one shows each
  setting at fault with its problem, package and what installs it on lines of their own.
- `--json` prints `{"valid": true, "config", "avatar_id", "home", "workspace", "plugins",
  "inference", "health"}` (`config` is `{"bundle", "default", "file"}`; `inference` maps each
  runner method to its workers) or `{"valid": false, "error": {"type", "fields",
  "diagnostic", "problems", "action"}}`: `fields` are the settings at fault, `problems` each
  one with its `line`, `location`, `problem`, `package`, `action` and `variable`, and `action`
  the next step, as [`doctor`](doctor.md)'s `config.load` gives it; credentials and control
  characters removed.
- The text follows the [commands' shared layout](README.md#output): a value too long for the
  terminal goes on under its own start, as `router` does above at 100 columns. On a terminal,
  the groups are bold signal cyan and a tool not on, `none`, is yellow; pipes, `NO_COLOR` and
  `TERM=dumb` get the same text, plain.

## Exit codes

| Code | `init` | `check` |
| --- | --- | --- |
| 0 | Created | Valid |
| 2 | File exists, invalid name or ID, unreadable settings or write failure | Invalid configuration, selection or reference, failed path check, or unreadable settings or stored credentials with no configuration argument |
