# `alphaavatar setup`

Choose what the Avatar runs with, install what that needs, check it, then make it the default
bundle. Part of the Linux x86_64 package: [install it](../../DEPLOY.md#or-install-the-linux-package-then-choose-capabilities)
with `install.sh` first.

```bash
alphaavatar setup                                  # questions
alphaavatar setup --preset default|remote          # no questions, for scripts and CI
alphaavatar setup --plan                           # print the install plan, change nothing
```

| Option | Meaning |
| --- | --- |
| `--preset default` | `config init`'s reference bundle: voice, vision, memory and persona, with turn taking, addressing, face and speaker models on this machine (about 515 MB; semantic addressing needs an x86-64-v3 CPU) |
| `--preset remote` | The same with no model on this machine but voice activity detection (about 210 MB) |
| `--no-voice`, `--no-vision`, `--vector-store lancedb\|qdrant` | With `--preset`: no speech, no camera, where memory and persona vectors go |
| `--name`, `--avatar-id` | The bundle name (default `avatar`) and the Avatar ID (default: the name) |
| `--artifacts DIR\|URL` | Where this build's own wheels are when it is not a release: a CI build's directory |
| `--plan` | Print the plan as JSON: packages, sizes, SHA-256s; nothing is installed or written |

## Questions

Without `--preset`, setup asks, in a terminal:

1. The default bundle, remote inference, or each part: voice, vision, models on this machine,
   and the vector store (LanceDB in the Avatar workspace, or your Qdrant).
2. Choosing each part, the models and speech can come from OpenAI or from a server of your own
   with OpenAI's API: its URL, then the models (conversation through the Responses API, memory
   and persona tasks, embeddings) or speech (transcription, synthesis, voice). Speech needs
   `https://` unless the server is on this machine. A URL the backends would refuse is asked
   again.
3. The bundle name and Avatar ID.
4. The credentials the choice needs, then whether to store them.

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
- With `--preset`, every credential comes from the environment or `.env`, and none is stored.
  A missing one fails before anything is installed.

## What it does

- Plans from the catalog in the package: every artifact with its version and SHA-256. What the
  current environment holds stays in the plan, so earlier bundles keep working.
- Checks the machine (glibc, CPU) and the free space (about four times the download) first.
- Installs into `<prefix>/envs/<plan>/` beside the current version, or reuses the environment
  of the same plan, then checks it: its native libraries load and its `alphaavatar config check`
  accepts the new bundle.
- Only then switches `<prefix>/current` to it and writes the bundle. One replacement of
  `settings.yaml` makes the bundle the default and names the credentials stored with it, so even
  a killed setup leaves both as they were or both new.
- Failing or interrupted before that, the current version, command, bundles, settings and
  credentials stay as they were, and the environment this run made is removed. Model weights
  are not part of the plan: runners download them into the model cache when they start.
- Takes the lock `install.sh` takes, `<prefix>/.install.lock`: a second installation into the
  prefix is refused while one runs. A lock that is not a regular file, a link or a pipe, is
  refused and left as it is.

With `--preset remote`:

```text
AlphaAvatar 0.6.9 (linux-x86_64), plan 0d4c1f7a9b2e5c63:
  sessions through LiveKit
  model and embeddings from OpenAI
  speech from OpenAI
  voice: speech in and out, voice activity detected on this machine
  vision: camera frames reach the model
  no other models on this machine
  memory and persona: vectors in LanceDB in the Avatar workspace
  85 packages, 210 MB to download
  environment /home/me/.local/lib/alphaavatar/envs/ab714123b86b7b48; bundle avatar, made the default

Enabled bundle avatar (default) in /home/me/.local/lib/alphaavatar/envs/ab714123b86b7b48.
```

Then start it with [`alphaavatar start`](start.md), or [`alphaavatar dev`](dev.md).

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Enabled, or `--plan` printed |
| 1 | Nothing enabled: answered no, no terminal to ask in, missing credentials, the machine or free space, a download or the check failed, another installation running |
| 2 | Refused before installing: a bundle of that name exists, unreadable settings, another error |
| 130 | Interrupted with Ctrl+C; 143 for SIGTERM, 129 for SIGHUP |
