# Quick start

[中文](quickstart-zh.md)

From nothing to a running AlphaAvatar Host on a Linux server, with the latest release's Linux
package. Other versions, mirrors and unattended installs are in
[DEPLOY.md](DEPLOY.md#or-install-the-linux-package-then-choose-capabilities).

## What you need

- Linux x86_64 with glibc 2.28 or newer, and `tar`, `gzip`, coreutils and `curl`. The package
  brings its own Python: no Python, Node or compiler is needed.
- About 515 MB to download for the reference bundle (about 210 MB with only voice activity
  detection on this machine), and about four times that free; semantic addressing needs an
  x86-64-v3 CPU.
- A LiveKit server, the implemented session transport: `LIVEKIT_URL` (`wss://` unless the
  server is on this machine), `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET`.
- Keys for the model providers you choose: the reference uses OpenAI (`OPENAI_API_KEY`), and
  Google (`GOOGLE_API_KEY`) for ENV memory; setup also offers others and servers of your own.
- A client that joins the LiveKit room; this repository supplies none (`avatar-app/` is reserved).

## Install the latest release

```bash
curl -fsSL https://github.com/AlphaAvatar/AlphaAvatar/releases/latest/download/install.sh | bash
```

Program files go to `~/.local/lib/alphaavatar` and the command to `~/.local/bin`, which the
installer adds to PATH for new terminals; in this one, run the `source` line it prints under
`Next`. In a terminal, a first install then offers to run `alphaavatar setup`; declined, failed
or cancelled, the installation stays.

## Run setup

```bash
alphaavatar setup
```

Setup starts from the reference configuration and asks step by step: capabilities, each part's
provider and model, the credentials the choice reads, then the install plan; Enter keeps the
reference's answer. Typed credentials are stored only on a yes, in
`<home>/settings/credentials-<id>.env`, readable only by you, never in bundle or profile files.
Setup installs and checks the plan, and only then makes the bundle the default; a failure
leaves everything as it was. No tool is on: switch on DeepResearch or MCP in the bundle's tools
profile, then run `alphaavatar setup <bundle>`.

To edit the bundle first, or without a terminal (as in CI), create it, then set it up by name,
its credentials from the environment, `.env` or those stored:

```bash
alphaavatar config init my-avatar --avatar-id my-avatar   # edit its profiles as needed
alphaavatar setup my-avatar
```

`config init` writes the bundle in the application home (on Linux `~/.local/share/alphaavatar`
unless `XDG_DATA_HOME` or `ALPHAAVATAR_HOME` says otherwise) and makes it the default when none
is set. See [setup](cli/setup.md) and [config init](cli/config.md#config-init).

## Check with Doctor

```bash
alphaavatar doctor
```

Doctor's static checks of the installation and the default bundle download and contact
nothing. Then it asks once: a yes starts the bundle's runtime as `start` does, downloads model
files the cache lacks, and runs a fixed spoken scenario 5 times (`--rounds N`), calling the
services the bundle names, which may be billed. Without a terminal, only the configuration
[authorizes](cli/doctor.md#authorization) that; `--no-metrics` gives the static checks alone.
Doctor uses no RTC server or client.

## Start the Host

```bash
alphaavatar start
curl --fail http://127.0.0.1:8081/ready   # in another terminal
```

`start` loads and validates the default bundle (or the bundle or file named), creates the
application home and Avatar workspace on first run, and serves `/live`, `/ready` and `/status`
on `127.0.0.1:8081`; runners download model files the cache lacks as they start. Ctrl+C or
SIGTERM stops it once every owned resource is released. Readiness does not prove that speech,
tools or playback work ([start](cli/start.md), [service](DEPLOY.md#install-a-systemd-service)).

## Connect a client

The bundle `config init` and setup write uses LiveKit in `dispatch` mode: the Host registers
under `avatar.name` (`AlphaAvatar` there) and waits for dispatches of that name, each supplying
its room. Point a LiveKit frontend and its trusted backend at the same LiveKit deployment and
dispatch that name; keep `LIVEKIT_API_SECRET` and API keys on the server, and give browser
participants scoped access tokens from the backend. The participant's `session_type` metadata
selects `chat`, `agent`, `audio` or `video` (default `video`). Starting the Host does not by
itself join a room: test a real dispatch, room join, text interaction and audio playback. See
[DEPLOY.md](DEPLOY.md#connect-the-browser-frontend) and the
[Host configuration](../avatar-host/README.md#configuration).

## From source, for development

The default branch holds changes not yet released. It targets CPython 3.13 with uv 0.10.0 or
newer; `uv sync` installs every package, so the Linux package's `setup`, `upgrade` and
`cleanup` are not needed:

```bash
git clone --recurse-submodules https://github.com/AlphaAvatar/AlphaAvatar.git
cd AlphaAvatar && uv sync --all-packages --locked && source .venv/bin/activate
cp .env.template .env.dev    # then fill in the credentials
ENV_FILE=.env.dev alphaavatar config init my-avatar --avatar-id my-avatar
ENV_FILE=.env.dev alphaavatar doctor
ENV_FILE=.env.dev alphaavatar dev
```

`ENV_FILE` names the `.env` file credentials are read from (default `.env`). `dev` is `start`
with DEBUG logging and a health server on any free port; it does not reload code. To deploy
from source, use a release's tag ([DEPLOY.md](DEPLOY.md)); for environments and checks, see
[CONTRIBUTING.md](../CONTRIBUTING.md#python-313-development-environment).

## Where to go next

- [DEPLOY.md](DEPLOY.md): credentials, health checks, a systemd service, logs, storage, updates.
- [Commands](cli/README.md), [config](cli/config.md#credentials), [upgrade](cli/upgrade.md) and
  [cleanup](cli/cleanup.md); [examples](../examples/README.md) of complete configurations.
- [Avatar workspace](avatar-workspace-layout.md) and [Models and cache](models-cache-layout.md):
  where data and models are kept; [README](../README.md); [CONTRIBUTING.md](../CONTRIBUTING.md).
