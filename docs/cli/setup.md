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
| `--artifacts DIR\|URL` | Where this build's own wheels are when it is not a release: a CI or local build's directory. Without it, such a build is refused before the first question |
| `--plan` | Print the plan as JSON: packages, sizes, SHA-256s; nothing is installed or written. A refusal prints `{"error": {"diagnostic": …}}` there too, the reason as the report gives it |

## Asked: a new bundle

`alphaavatar setup` starts from the reference configuration `config init` writes, and Enter
keeps each of its answers. In a terminal, it asks step by step:

1. **Capabilities**: voice (speech in and out, voice activity detected on this machine), vision
   (camera frames reach the model), models on this machine (turn taking, addressing, face and
   speaker recognition), ENV memory (memories drawn from the session's audio and video by
   Google's Gemini), and where memory and persona keep vectors (LanceDB in the Avatar
   workspace, or your Qdrant). A part switched off keeps its settings, to switch it on later,
   and asks nothing more: no model, no credential. No tool is on, the default, and it says how
   to switch one on: DeepResearch or MCP in the bundle's tools profile, then
   `alphaavatar setup <bundle>`; this release's setup does not install RAG. Then the bundle name,
   asked again if a bundle has it, and the Avatar ID.
2. **Models**: each running part's provider, then its model.

   | Part | Providers |
   | --- | --- |
   | The conversation | OpenAI, or a server of your own with OpenAI's Responses API |
   | Memory, tool memory, persona profiles | OpenAI, Anthropic, Google, OpenRouter, or a server of your own |
   | ENV memory | Google |
   | Embeddings | OpenAI, Google, or a server of your own |
   | Speech recognition | `openai_segment`, `openai_realtime`, or a server of your own with OpenAI's audio API |
   | Speech synthesis | `openai`, `voiceai`, or a server of your own with OpenAI's audio API |

   The reference's provider is the default, with its model offered; another provider's model is
   typed, none carried over. Memory, tool memory and persona profiles can take a model chosen for
   an earlier part (`As for memory: …`). A server of your own is asked for its URL, the one typed
   before offered; speech needs `https://` unless the server is on this machine, and a URL the
   backends would refuse is asked again. Speech synthesis asks for a voice (optional for
   Voice.ai) and a speed where the implementation takes one; a model that reads no instructions
   (`tts-1`, `tts-1-hd`, Voice.ai) is written with `instructions: null`.
3. **Credentials**: each variable the choice reads, once, with the parts that read it; then
   whether to store them.
4. **Install**: what the bundle runs with and the plan, in groups (the bundle, its
   capabilities, each part's model, speech, where vectors are kept and the tools, then the
   installation), then whether to install and enable it. An existing bundle's come from its
   settings: its tools on, its stores where they are, a server of its own by its address alone,
   without credential, query or fragment.

On a terminal, a provider is chosen from a list: the arrow keys move, typing narrows it to the
options holding what is typed, Escape clears that, Enter takes the marked one. With `TERM=dumb`
or `NO_COLOR`, the options are numbered: a number, or text only one option holds; Enter takes
the default. Ctrl+C or the input's end (Ctrl+D) leaves the terminal as it was and writes
nothing.

Without a terminal, setup refuses with exit code 1 and names `alphaavatar setup <bundle>`.

## Given: an existing bundle

`alphaavatar setup <bundle>` installs what the bundle's settings select, overrides and edits
included, as `start` would resolve them: the plugins of each part, the providers' backends,
the vector stores, and the local models the switches leave on. A model task that names its
model alone takes its kind and backend from the provider schema's defaults, as `start` does.
It imports no plugin to plan.
A LanceDB index the bundle's plugins open, made with another embedding model than the bundle
names for it, fails the same way, before anything is installed: give the store another name, or
configure the model it was made with. The index is looked for where `start` opens it, in the
directory its `client_path` names or else the Avatar's own for that plugin; a Qdrant index is
checked as `start` opens it. A selection this release's setup installs nothing for, such
as a plugin that is not in the catalog, fails before anything is installed and is named by its
setting:

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
| `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `OPENROUTER_API_KEY`, `VOICEAI_API_KEY` | The parts chosen from that provider; Google's for ENV memory too, while it is on |
| `ALPHAAVATAR_SERVER_KEY_<hash>` | Each server of your own, named after its URL; any text if it needs none |
| `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | Session transport |
| `QDRANT_URL`, `QDRANT_API_KEY` | Your Qdrant, when the vectors go there; the key only if it asks for one |

- A server's variable is named after its URL: scheme, host, port and path. A default port
  and a trailing `/` are the same URL; another path is another server. Its key is sent to
  that server alone, and a server of your own never receives `OPENAI_API_KEY`. Loading checks
  the variable against the `base_url` in effect, overrides applied: a bundle whose `base_url`
  was moved to another server, or removed, fails [`config check`](config.md#config-check) and
  `start`. A variable you name yourself may point anywhere.
- A value already set, in the environment, `.env` or the stored credentials, is kept with Enter;
  an empty or blank one is not set, and is asked for. See
  [config's credentials](config.md#credentials) for which source wins.
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
  credentials stay as they were, and the environment this run made is removed: whole into a
  marked stage first, and a stage, its own or one a stopped run left, loses its mark last, so a
  run stopped even then leaves only marked stages, which the next installation removes. Model
  weights are not part of the plan: runners download them into the model cache when they
  start, at `start` and in [`doctor`](doctor.md#runtime-start)'s runtime diagnosis alike.
- Takes the lock `install.sh` takes, `<prefix>/.install.lock`: a second installation into the
  prefix is refused while one runs. A lock that is not a regular file, a link or a pipe, is
  refused and left as it is.

It reports in five steps, each on one line once done. On a terminal, the current step is in
signal cyan, and its line shows the download in progress; a pipe, a log or `NO_COLOR` gets each
artifact on a line of its own. Asked, each step's questions go under it, and the plan comes
before the confirmation:

```text
AlphaAvatar / Setup

01  Capabilities
    Each question starts from the reference configuration: Enter keeps its answer.
    Voice: speech in and out, voice activity detected on this machine? [Y/n]:
    Models on this machine: turn taking, addressing, face and speaker recognition? [Y/n]: n
    …
    Tools  None enabled (default)
           Enable DeepResearch or MCP in the tools profile,
           then run: alphaavatar setup <bundle>
           RAG is not available through setup in this release.
    …
01  Capabilities   Bundle first · Voice on · Vision on · Local models off · ENV memory on
02  Models
    Provider for the conversation: OpenAI
      Model for the conversation [gpt-5.6-luna]:
    Provider for memory: ↑↓ to move, type to narrow, Enter to choose
      As for the conversation: OpenAI gpt-5.6-luna
    › OpenAI  (default)
      Anthropic
      …
02  Models         OpenAI · Google
03  Credentials    Ready
04  Install

    Configuration
      Bundle          first · will become the default
      Avatar ID       first
      Version         0.6.9 · linux-x86_64

    Capabilities
      Voice           On
      Vision          On
      Local models    Off
      ENV memory      On

    Models
      Conversation    OpenAI       gpt-5.6-luna
      …

    Storage & Tools
      Vectors         LanceDB · Avatar workspace
      Tools           None enabled (default)
                      Enable DeepResearch or MCP in the tools profile,
                      then run: alphaavatar setup first
                      RAG is not available through setup in this release.

    Installation
      Packages        85
      Download        212 MB
      Plan            97138f31be7bfc50
      Environment     ~/.local/lib/alphaavatar/envs/97138f31be7bfc50

    Install and enable? [Y/n]: y
04  Install        85 packages · 212 MB
05  Validate       PASS · 3 runners

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
01  Capabilities   Bundle reference · Voice on · Vision on · Local models on · ENV memory on
02  Models         As the bundle's settings choose them
03  Credentials    From the environment, .env or those stored
04  Install        105 packages · 514 MB
05  Validate       PASS · 8 runners
```

`Validate` counts the inference runners the new environment's `config check` plans. A failure,
a declined plan or Ctrl+C is reported on stderr, `FAIL  Setup failed; nothing was enabled`,
`WARN  Cancelled; nothing was enabled`, `WARN  Interrupted; nothing was enabled` or
`WARN  The input ended; nothing was enabled`, with the reason below; with `--plan`, the steps go to stderr too, leaving stdout to the plan's JSON.
Then diagnose the bundle with [`alphaavatar doctor`](doctor.md), and start it with
[`alphaavatar start`](start.md) or [`alphaavatar dev`](dev.md). Each screen, colors and all, is
in [cli.html](cli.html).

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Enabled, or `--plan` printed |
| 1 | Nothing enabled: answered no, the input ended, no terminal to ask in and no bundle given, a selection setup does not install, missing credentials, the machine or free space, a download or the check failed, another installation running |
| 2 | Refused before installing: `--name` names a bundle that exists, unreadable settings, another error |
| 130 | Interrupted with Ctrl+C; 143 for SIGTERM, 129 for SIGHUP |
