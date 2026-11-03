# `alphaavatar doctor`

Diagnose the installation and a configuration with static checks: read-only and offline.

```bash
alphaavatar doctor                                      # the default bundle, if there is one
alphaavatar doctor [<bundle> | <file>] [KEY=VALUE ...]  # as config check selects them
alphaavatar doctor --json                               # the same report as JSON
alphaavatar doctor --list                               # the checks, without running any
```

The optional argument and the overrides follow [`config check`](config.md#choosing-a-configuration):
the same `.env`, home, bundle or file selection, profiles, overrides, validation and read-only
workspace checks. With no argument and no default bundle, Doctor says how to create one and
still checks everything that needs no configuration.

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
| `models.runners` | Runner models — not verified | yes |
| `services.external` | RTC server, model providers, speech, vector store, tool and MCP services — not verified | yes |
| `devices.media` | Microphones and cameras — not verified | |

Static checks cannot tell whether a model loads, a service accepts the credentials or a device
works. Those checks are always `SKIP` with "Not verified", never `PASS`; their next step names
the command that does exercise them.

Doctor's checks never create files, directories or settings, download or load a model, start a
Host or runner, contact a service, open a microphone or camera, or construct a service client.
Like `config check`, it reads `.env` for `<ENV_VAR>` placeholders; a `.env` it cannot read is a
`config.load` failure in the same report, and checks that depend on it are skipped.

The first configuration import in a process loads the plugins, as `config check` and `start` do,
and some of their libraries probe the machine while importing: `urllib3` opens and binds one IPv6
socket to test IPv6 support, and `weasyprint` looks up native libraries through
`ctypes.util.find_library`, which runs `ldconfig`, `gcc` and `ld` and creates and removes
temporary files. These probes come from the libraries, not from Doctor's checks.

## Results

Each check has a stable ID, a status, a summary, optional details and, unless it passed, a next
step.

| Status | Meaning |
| --- | --- |
| `PASS` | Checked and fine |
| `WARN` | Works, but needs attention: no configuration yet, mixed package releases, less than 1 GiB free |
| `FAIL` | `start` or `dev` would fail, or cannot work as configured |
| `SKIP` | Not run: needs a configuration, or not verifiable by static checks |

| Exit code | Meaning |
| --- | --- |
| `0` | No check failed; warnings and skipped checks allowed |
| `1` | At least one check failed |
| `2` | Invalid arguments |

```text
OK  doctor: 9 passed, 0 warned, 0 failed, 3 not verified or skipped (static checks)
    environment
      PASS  system.platform        Linux 6.8.0 x86_64; AF_UNIX socket API present, not opened
      PASS  python.version         Python 3.13.13 (CPython) at /home/me/.venv/bin/python3; supported (<3.14,>=3.13)
      PASS  packages.alphaavatar   16 AlphaAvatar packages, release 0.6.9; Host requirements installed
    configuration
      PASS  config.load            bundle my-avatar (default) loaded and validated
      PASS  config.runners         8 runners (1 worker each); plan is valid
      PASS  packages.capabilities  Requirements installed for rtc, loop, context, providers, voice, router, status, memory, persona
    directories
      PASS  paths.home             /home/me/.local/share/alphaavatar  (drwx------, owned by this user)
      PASS  paths.cache            /home/me/.local/share/alphaavatar/cache  (drwx------, owned by this user)
      PASS  paths.workspace        /home/me/.local/share/alphaavatar/avatars/my-avatar  (not created yet; created when first needed)
    not verified
      SKIP  models.runners         Not verified: static checks load and download no model for the 8 runners
                                   -> `alphaavatar dev` initializes every runner, fetching missing models, before it accepts a session
      ...
```

The text groups the checks as environment, configuration, directories and not verified. A
passing check is one line; any other shows its details and next step. `--list` uses the same
groups. Grouping is presentation only: JSON keeps the flat list, the check IDs and the exit codes.

`--json` prints the same report: `status` (`PASS`, `WARN` or `FAIL`), `counts` per status, and
`checks` with `id`, `status`, `summary`, `details` and `action`. Text, JSON and details pass the
same output boundary as `config check`: credentials from the configuration and the environment
are replaced and control characters removed. `--list --json` prints each check's `id`, `title`
and `needs_configuration`.

Model provider backends come from the provider tasks start would create: the built-in plugins'
settings are validated as `config check` does (`validate_plugin_settings`), so omitted fields
take their defaults; a processor switched off (`enabled: false`) and a disabled plugin create
nothing and are skipped. The vector store embeddings of the default memory, persona and MCP
always use the default backend. For another loop, memory, persona or MCP plugin,
`packages.capabilities` warns that its backends are not verified. Settings a built-in plugin's
schema rejects, such as a realtime loop without `model`, fail `config.load` as they fail
`config check`.

Unreadable settings do not stop a named bundle or a file: `paths.home` warns and names the file
to fix, since `config init` and runs without a configuration argument read it.

The report is built by `alphaavatar.host.doctor.diagnose(target, overrides)`, which an App or TUI
can call; the CLI reads `.env`, parses arguments and prints.

## Planned — not available yet

```bash
alphaavatar doctor --runtime    # Bounded local checks: load runner models, start runners
alphaavatar doctor --live       # Opt in to real services and devices
```

Explicit probes will measure what static checks cannot, in batches: model loading, service
access and devices, and first-token, first-audio-frame and end-to-end latency. Doctor will never
prompt, download models or make paid calls without explicit permission.
