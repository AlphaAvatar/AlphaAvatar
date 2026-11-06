# AlphaAvatar Deployment Guide

Run the native AlphaAvatar Host on a Linux server and connect a browser client through
LiveKit. Install a tested source revision using the [README](README.md) before following
this guide. This development line targets standard CPython 3.13 on Linux. Complete the
[Python migration checks](CONTRIBUTING.md#python-313-development-environment), including
a newly resolved and reviewed Python 3.13 lockfile, before deploying. Changing package
metadata alone is not an installation or model-compatibility result.

## Prepare the deployment

Use one service account with access to the checkout, its virtual environment, the Avatar
workspace and the model cache. Complete installation or upgrades while the service is
stopped, not inside an automatically restarting service:

```bash
cd /path/to/AlphaAvatar
uv python install 3.13
uv venv .venv --python 3.13
uv sync --locked --all-packages
test -f .env.demo || cp .env.template .env.demo
chmod 600 .env.demo
```

The copy step preserves an existing `.env.demo`. Configure LiveKit, model, embedding
and tool credentials required by the selected YAML. Keep secrets out of version control.
The launch environment can override settings from the environment file.

```env
LIVEKIT_URL=wss://your-livekit-host
LIVEKIT_API_KEY=your-key
LIVEKIT_API_SECRET=your-secret
OPENAI_API_KEY=your-openai-key
ALPHAAVATAR_HOME=/var/lib/alphaavatar
```

Create the application home and make it writable by the service account. Do not run the
assistant as root merely to access `/var/lib`. With `avatar.id: my_avatar` and no explicit
workspace setting, the workspace is `/var/lib/alphaavatar/avatars/my_avatar/` and models
are cached under `/var/lib/alphaavatar/cache/models/`.

To keep a separate cache, merge this top-level section into the selected YAML and create
the writable cache directory:

```yaml
application:
  cache_root: /var/cache/alphaavatar
```

This places models under `/var/cache/alphaavatar/models/`. `application.home`, if set,
overrides the environment-selected application home. For an existing workspace, set
`avatar.workspace_root` to its complete absolute directory; no Avatar ID is appended.
Remove legacy `AVATAR_WORK_DIR` and `ALPHAAVATAR_MODEL_CACHE` values from the service
environment and `.env` file: Host rejects both rather than relocating existing data.
See [Avatar workspace](docs/avatar-workspace-layout.md) and
[Model cache](docs/models-cache-layout.md) for locating, backing up and moving data.

### Or install the Linux package, then choose capabilities

On Linux x86_64, CI builds a small base package per release, and on `main` and `dev/**` for
each push that changes what goes into it: its own Python with the CLI, `config init|check` and
`alphaavatar setup`. Setup
installs exactly what a bundle needs, from a catalog in the package with each artifact's
version and SHA-256, checks it, then enables it. Neither needs Python, Node or a compiler:

```bash
curl -fsSLO https://github.com/AlphaAvatar/AlphaAvatar/releases/download/v<version>/install.sh
bash install.sh --version <version>     # or --file <package> for a downloaded CI build
alphaavatar setup                       # a new bundle, asked part by part
alphaavatar doctor
```

Asked, setup starts from `config init`'s reference configuration: voice, vision, memory and
persona, with turn taking, addressing, face and speaker models on this machine (about 515 MB
to download; the semantic addressing model needs an x86-64-v3 CPU). Each part can be switched
off; with no model on the machine but the voice activity detection speech input needs, about
210 MB. The vectors go to LanceDB in the Avatar workspace or to your Qdrant, and models and
speech come from OpenAI or from servers of your own with OpenAI's API (Responses for the
conversation model). For CI and unattended installs, create or edit a bundle, then set up
that bundle, credentials from the environment, with no question asked:

```bash
alphaavatar config init my-avatar --avatar-id my-avatar   # edit its profiles as needed
alphaavatar setup my-avatar
alphaavatar config check my-avatar
```

`setup <bundle>` installs what the bundle's settings select, edits included, and refuses a
selection this release does not install before anything is installed. Each server of your own
reads its own key from a variable named after its URL,
`ALPHAAVATAR_SERVER_KEY_<hash>`, which setup shows when it asks: a key serves only the server it
was given for, only the same server shares one, and a server of your own never receives
`OPENAI_API_KEY`. Loading checks it against the URL in effect, overrides applied: a bundle
whose `base_url` was moved to another server, or removed, is refused before any client is
made; a variable you name yourself may point anywhere. Speech sends its key over HTTPS unless the server is on this machine. Given a bundle, setup reads credentials from the environment, `.env` or those stored, and stores none; asked
for, they are stored in a file of the application home's settings, readable only by you, only
if you say so, and a value stored there already, which other bundles may read, is replaced
only on a second yes. The settings replacement that makes the new bundle the default names
the stored credentials too, so even a killed setup leaves both as they were or both new.
`start`, `config check` and `doctor` read stored values where the environment does not set
them, and the default bundle from the same read of the settings. Model weights are not part of the
plan: runners fetch them into the model cache, and `doctor` names what it lacks and downloads
it once you agree. `--plan` prints the plan and changes nothing; a
CI build's own wheels sit beside its package, so pass `--artifacts <directory>` for one.

A configuration names each plugin by capability type and implementation, and the installed
packages' entry points provide them; `config check` and `doctor` name a missing one at the
setting that selects it, and say whether this release's setup installs it. Loading a
configuration resolves the plugins with their settings and the model providers those name,
and plans the inference workers of all their runners: what `config check` reports is what
`start` launches.

Program files go to `~/.local/lib/alphaavatar` and the command to `~/.local/bin`
(`--prefix`, `--bin-dir`); the application home, workspaces and model caches stay where
`ALPHAAVATAR_HOME` puts them. A new base version, or setup's environment, is installed and
checked beside the current one, and the configuration is enabled only after the switch; if
anything fails, the current version, command, configuration and data stay as they were;
nothing is removed that the installer cannot tell it made. A second setup keeps what the
current environment holds, so earlier bundles keep working, even one that finished while
this setup waited for confirmation.
`packaging/linux/build.sh` builds the same files from a checkout.

## Check the configuration in the foreground

The supplied demo uses `examples/agent_configs/roles/demo.yaml`. Review its enabled
features and services before running it:

```bash
ENV_FILE=.env.demo .venv/bin/alphaavatar start examples/agent_configs/roles/demo.yaml
```

Named LiveKit dispatch uses **`avatar.name`**, not `avatar_name`. The browser/backend
must dispatch the same name to the same LiveKit deployment. The supplied examples use
`AlphaAvatar`. Starting Host does not by itself join a room or prove that an interaction
has completed.

For a long-running service, use `dispatch`, not the one-shot `direct` mode. These are
fragments to merge into the existing Host section, not a complete Avatar configuration:

```yaml
host:
  rtc:
    backend: livekit
    init_config:
      connection_mode: dispatch
  health:
    bind: 127.0.0.1
    port: 8081
  log:
    banner: false
    color: never
```

Use the startup logs and local health endpoints to check progress:

```bash
curl --fail http://127.0.0.1:8081/live
curl --fail http://127.0.0.1:8081/ready
curl --fail http://127.0.0.1:8081/status
```

`/live` checks the Host process, `/ready` checks service readiness, and `/status` explains
runner and execution state without configuration or credentials. Readiness is not proof of
successful speech, tool calls or playback. These endpoints are not authenticated: they bind to
`127.0.0.1` unless `host.health.bind` is set, so expose them only behind your deployment
network controls. Press Ctrl+C and wait for normal shutdown before
installing the service.

## Install a systemd service

Replace `/path/to/AlphaAvatar` and `your-linux-user` below. Use the actual virtualenv
executable so the service's main process is Host, not an installer or a shell wrapper.
Save the unit as `/etc/systemd/system/alphaavatar-demo.service`:

```ini
[Unit]
Description=AlphaAvatar native Host
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=your-linux-user
WorkingDirectory=/path/to/AlphaAvatar
Environment=ENV_FILE=/path/to/AlphaAvatar/.env.demo
Environment=PYTHONUNBUFFERED=1
Environment=NO_COLOR=1
ExecStart=/path/to/AlphaAvatar/.venv/bin/alphaavatar start /path/to/AlphaAvatar/examples/agent_configs/roles/demo.yaml
Restart=on-failure
RestartSec=5
KillSignal=SIGTERM
KillMode=mixed
TimeoutStopSec=300
SendSIGKILL=yes
UMask=0077
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**Keep `KillMode=mixed`.** The first stop signal goes to Host, allowing it to settle
executions and close inference runners through their own shutdown protocols. The
systemd default, `control-group`, sends that first signal to all service processes and
can terminate runners before Host finishes cleanup. Do not replace it with `process`
or `none`, which can leave descendants unmanaged.

systemd's final kill still covers remaining processes in the service control group,
including detached browser processes that remain in that group. It can run when Host
exits or the stop deadline expires. This is a service-wide boundary, not per-execution
browser containment and not proof that external tools were undone.

The 300-second stop allowance is an example. Set it above your intended Host cleanup
budget when changing process or tool settings. A forced kill is not successful cleanup.
Do not disable final reclamation to conceal shutdown problems. systemd reporting
`active` for a `Type=simple` service is also not equivalent to `/ready` returning 200.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now alphaavatar-demo
sudo systemctl status alphaavatar-demo
journalctl -u alphaavatar-demo -f
```

Stop, restart or disable the service with:

```bash
sudo systemctl stop alphaavatar-demo
sudo systemctl restart alphaavatar-demo
sudo systemctl disable alphaavatar-demo
```

The optional `examples/scripts/start_alphaavatar_demo.sh` is a foreground setup helper; it
can create an environment and synchronize dependencies. It is intentionally not the service
`ExecStart` above. Service restarts must not perform an implicit dependency update.

## Connect the browser frontend

Configure the frontend/backend to use the same LiveKit deployment and the selected
`avatar.name`. A frontend using `NEXT_PUBLIC_AVATAR_NAME` should set it to that name.
Keep `LIVEKIT_API_SECRET` and API keys on the server side; never give them a
`NEXT_PUBLIC_` prefix or embed them in a browser bundle. Browser participants receive
scoped access tokens from a trusted backend.

Test a real dispatch, room join, text interaction and audio playback separately from
Host registration. Test cancellation during a response and during a tool operation.
A client disconnect does not prove that an external operation did not execute.

## Logs, storage and updates

The service journal receives formatted text. Host's own rotating files are JSONL and
are normally under `<workspace>/.logs/host/`; the startup record reports their actual
path. Do not feed journal text or old SDK log-field examples into a JSON parser.
Inspect JSONL files with a text editor, or explicitly select the current `created`,
`level`, `source`, `line`, `pid` and `text` fields. Review logs before sharing them.

Keep a stable Avatar ID across updates. The current layout is:

```text
/var/lib/alphaavatar/avatars/<avatar_key>/
├── env/
├── users/
├── graph/
├── data/
│   ├── memory/
│   ├── sessions/
│   ├── indexes/
│   └── artifacts/
├── .logs/host/
└── .cache/

/var/cache/alphaavatar/models/      # Separate downloaded model cache.
```

Stop the service and back up its workspace before an update. Check out the tested
revision, update any required submodules, then synchronize using the committed lockfile:

```bash
sudo systemctl stop alphaavatar-demo
cd /path/to/AlphaAvatar
# Check out your tested revision here; retain a known-good rollback revision.
git submodule update --init --recursive
uv sync --locked --all-packages
sudo systemctl start alphaavatar-demo
journalctl -u alphaavatar-demo -n 100 --no-pager
```

Verify `/ready` and an actual interaction before retiring the backup. Do not run old
and new deployments against the same local workspace as an informal migration test.
A source rollback is not a database restore; preserve the stopped workspace backup as
well as the tested source revision and environment settings.
