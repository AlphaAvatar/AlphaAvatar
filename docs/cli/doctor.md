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
| `system.platform` | Operating system; POSIX local sockets, which the Host needs | |
| `python.version` | The interpreter against the Python versions AlphaAvatar supports | |
| `packages.alphaavatar` | Installed AlphaAvatar packages come from one release; the Host's requirements are installed | |
| `config.load` | Selection, profiles, overrides and validation, with `config check`'s result | |
| `config.runners` | The inference runners and workers the configuration selects | yes |
| `packages.capabilities` | Packages the enabled capabilities need: RTC backend, loop, context, model provider backends, voice, router, status, character, memory, persona and tools, with their extras and versions | yes |
| `paths.home` | Application home: where it came from, state, owner and mode, write access, settings, bundles, free space | |
| `paths.cache` | Cache root: state, write access, downloaded models, free space | |
| `paths.workspace` | The Avatar's workspace: state, write access, free space | yes |
| `models.runners` | Runner models — not verified | yes |
| `services.external` | RTC server, model providers, speech, vector store, tool and MCP services — not verified | yes |
| `devices.media` | Microphones and cameras — not verified | |

Static checks cannot tell whether a model loads, a service accepts the credentials or a device
works. Those checks are always `SKIP` with "Not verified", never `PASS`; their next step names
the command that does exercise them.

Doctor never creates files, directories or settings, downloads or loads a model, starts a Host
or runner, contacts a service, opens a microphone or camera, or constructs a service client. Like
`config check`, it reads `.env` for `<ENV_VAR>` placeholders.

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
    PASS  system.platform        Linux 6.8.0 x86_64; POSIX local sockets available
    PASS  python.version         Python 3.13.13 (CPython) at /home/me/.venv/bin/python3; supported (<3.14,>=3.13)
    PASS  packages.alphaavatar   16 AlphaAvatar packages, release 0.6.9; Host requirements installed
    PASS  config.load            bundle my-avatar (default) loaded and validated
                                 avatar my-avatar
    PASS  config.runners         8 runners (1 worker each); plan is valid
    PASS  packages.capabilities  Requirements installed for rtc, loop, context, providers, voice, router, status, memory, persona
    PASS  paths.home             /home/me/.local/share/alphaavatar  (drwx------, owned by this user)
                                 chosen by the platform default; settings: default bundle my-avatar; 1 bundle; 120.4 GiB free
    ...
    SKIP  models.runners         Not verified: static checks load and download no model for the 8 runners
                                 -> `alphaavatar dev` initializes every runner, fetching missing models, before it accepts a session
```

`--json` prints the same report: `status` (`PASS`, `WARN` or `FAIL`), `counts` per status, and
`checks` with `id`, `status`, `summary`, `details` and `action`. Text, JSON and details pass the
same output boundary as `config check`: credentials from the configuration and the environment
are replaced and control characters removed. `--list --json` prints each check's `id`, `title`
and `needs_configuration`.

Model provider backends come from the provider tasks in the configuration (a `model` with a
`provider` or `backend`); a task without a `backend` uses the default backend. Defaults that a
plugin applies internally are not visible to Doctor.

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
