# `alphaavatar setup`

Install what a bundle needs, check it, then make it the default bundle. Part of the Linux
x86_64 package: [install it](../DEPLOY.md#or-install-the-linux-package-then-choose-capabilities)
with `install.sh` first.

```bash
alphaavatar setup                    # a new bundle, asked part by part from the reference
alphaavatar setup my-avatar          # an existing bundle, as config init made it or as edited
alphaavatar setup my-avatar --plan   # print the install plan, change nothing
```

| Option | Meaning |
| --- | --- |
| `BUNDLE` | An existing bundle: no questions, the credentials from the environment, `.env` or those stored. Omitted, setup asks in a terminal |
| `--name`, `--avatar-id` | The new bundle's name (default `avatar`) and Avatar ID (default: the name); not with `BUNDLE` |
| `--artifacts DIR\|URL` | Where this build's own wheels are when it is not a release: a CI build's directory |
| `--plan` | Print the plan as JSON: packages, sizes, SHA-256s; nothing is installed or written |

## Asked: a new bundle

`alphaavatar setup` starts from the reference configuration `config init` writes: voice and
vision on, memory and persona. In a terminal, it asks:

1. Each part, kept with Enter or switched off: voice (speech in and out, voice activity
   detected on this machine), vision (camera frames reach the model), models on this machine
   (turn taking, addressing, face and speaker recognition), and the vector store for memory and
   persona (LanceDB in the Avatar workspace, or your Qdrant).
2. Where the models come from, and the speech if voice is on: OpenAI, or a server of your own
   with OpenAI's API. A server of your own is asked for its URL, then the models (conversation
   through the Responses API, memory and persona tasks, embeddings) or speech (transcription,
   synthesis, voice). Speech needs `https://` unless the server is on this machine; a URL the
   backends would refuse is asked again.
3. The bundle name and Avatar ID.
4. The credentials the choice needs, then whether to store them.
5. The plan, then whether to install and enable it.

Without a terminal, setup refuses with exit code 1 and names `alphaavatar setup <bundle>`.

## Given: an existing bundle

`alphaavatar setup <bundle>` installs what the bundle's settings select, overrides and edits
included, as `start` would resolve them: the plugins of each part, the providers' backends,
the vector stores, and the local models the switches leave on. A model task that names its
model alone takes its kind and backend from the provider schema's defaults, as `start` does.
It imports no plugin to plan.
A selection this release's setup installs nothing for, such as a plugin that is not in the
catalog, fails before anything is installed and is named by its setting:

```text
FAIL  Setup failed; nothing was enabled
      This release's setup installs nothing for: tools.rag.plugin: tools.rag 'default'
```

This is the way for CI and unattended installs, after [`config init`](config.md#config-init)
or a bundle of your own:

```bash
alphaavatar config init my-avatar --avatar-id my-avatar
alphaavatar setup my-avatar           # credentials from the environment
alphaavatar config check my-avatar
```

The credentials come from the environment, `.env` or those stored, and none is stored. Before
anything is installed, the selected session transport's are checked offline, as `start` reads
them, nothing contacted: LiveKit's three variables present, and its URL `wss://` unless the
server is on this machine. One missing or malformed fails at once, named, never shown:

```text
FAIL  Setup failed; nothing was enabled
      The session transport (livekit) cannot start: LIVEKIT_API_KEY and LIVEKIT_API_SECRET are
      required, in the environment, .env or the stored credentials
```

Without a terminal, the plan's confirmation is not asked. The check after installing is
`config check` of the bundle in the new environment, so a credential it needs and lacks fails
there too, and nothing is enabled.

## Credentials

| Variable | Asked for |
| --- | --- |
| `OPENAI_API_KEY` | What comes from OpenAI: models, embeddings, tasks, speech |
| `ALPHAAVATAR_SERVER_KEY_<hash>` | Each server of your own, named after its URL; any text if it needs none |
| `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | Session transport |
| `QDRANT_URL`, `QDRANT_API_KEY` | Your Qdrant, when the vectors go there; the key only if it asks for one |

- A server's variable is named after its endpoint: scheme, host, port and path. A default port
  and a trailing `/` are the same endpoint; another path is another server. Its key is sent to
  that server alone, and a server of your own never receives `OPENAI_API_KEY`. Loading checks
  the variable against the `base_url` in effect, overrides applied: a bundle whose `base_url`
  was moved to another server, or removed, fails [`config check`](config.md#config-check) and
  `start`. A variable you name yourself may point anywhere.
- A value already set, in the environment, `.env` or the stored credentials, is kept with Enter.
- Typed values are stored only on a yes, in `<home>/settings/credentials-<id>.env`, readable only
  by you; a stored value, which other bundles may read, is replaced only on a second yes. Values
  are never printed or written elsewhere.

## What it does

- Plans from the catalog in the package: every artifact with its version and SHA-256. What the
  current environment holds stays in the plan, so earlier bundles keep working. The reference
  bundle downloads about 515 MB (semantic addressing needs an x86-64-v3 CPU); with no model on
  this machine but voice activity detection, about 210 MB.
- Checks the machine (glibc, CPU) and the free space (about four times the download) first.
- Installs into `<prefix>/envs/<plan>/` beside the current version, or reuses the environment
  of the same plan, then checks it: its native libraries load and its `alphaavatar config check`
  accepts the bundle.
- Only then switches `<prefix>/current` to it and enables the bundle. One replacement of
  `settings.yaml` makes the bundle the default and names the credentials stored with it, so even
  a killed setup leaves both as they were or both new.
- Failing or interrupted before that, the current version, command, bundles, settings and
  credentials stay as they were, and the environment this run made is removed. Model weights
  are not part of the plan: runners download them into the model cache when they start, at
  `start` and in [`doctor`](doctor.md#runtime-start)'s runtime diagnosis alike.
- Takes the lock `install.sh` takes, `<prefix>/.install.lock`: a second installation into the
  prefix is refused while one runs. A lock that is not a regular file, a link or a pipe, is
  refused and left as it is.

It reports in four steps, each on one line once done. On a terminal, the current step is in
signal cyan, and its line shows the download in progress; a pipe, a log or `NO_COLOR` gets each
artifact on a line of its own. Asked, each step's questions go under it, and the plan comes
before the confirmation:

```text
AlphaAvatar / Setup

01  Capabilities
    From the reference configuration: voice and vision on, memory and persona, each model from the
    backend chosen below.
    Voice: speech in and out, voice activity detected on this machine? [Y/n]:
    Vision: camera frames reach the model? [Y/n]:
    Models on this machine: turn taking, addressing, face and speaker recognition? [Y/n]: n
    …
01  Capabilities   Voice on · Vision on · Local models off
02  Credentials    Ready
03  Install
    AlphaAvatar 0.6.9 (linux-x86_64), plan 97138f31be7bfc50
    sessions through LiveKit
    model and embeddings from OpenAI
    …
    85 packages · 212 MB to download
    Environment ~/.local/lib/alphaavatar/envs/97138f31be7bfc50; bundle first, made the default
    Install and enable? [Y/n]: y
03  Install        85 packages · 212 MB
04  Validate       PASS · 3 runners

OK    Bundle enabled
      Default       first
      Environment   ~/.local/lib/alphaavatar/envs/97138f31be7bfc50
      Start reads OPENAI_API_KEY, LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET from the
      environment or .env.

Next
  alphaavatar doctor first
```

An existing bundle reports the same steps from its settings:

```text
01  Capabilities   Bundle reference · Voice on · Vision on · Local models on
02  Credentials    From the environment, .env or those stored
03  Install        105 packages · 514 MB
04  Validate       PASS · 8 runners
```

`Validate` counts the inference runners the new environment's `config check` plans. A failure,
a declined plan or Ctrl+C is reported on stderr, `FAIL  Setup failed; nothing was enabled`,
`WARN  Cancelled; nothing was enabled` or `WARN  Interrupted; nothing was enabled`, with the
reason below; with `--plan`, the steps go to stderr too, leaving stdout to the plan's JSON.
Then diagnose the bundle with [`alphaavatar doctor`](doctor.md), and start it with
[`alphaavatar start`](start.md) or [`alphaavatar dev`](dev.md). Each screen, colors and all, is
in [cli.html](cli.html).

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Enabled, or `--plan` printed |
| 1 | Nothing enabled: answered no, no terminal to ask in and no bundle given, a selection setup does not install, missing credentials, the machine or free space, a download or the check failed, another installation running |
| 2 | Refused before installing: a bundle of that name exists, unreadable settings, another error |
| 130 | Interrupted with Ctrl+C; 143 for SIGTERM, 129 for SIGHUP |
