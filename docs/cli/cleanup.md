# `alphaavatar cleanup`

[中文](cleanup-zh.md)

Remove what upgrades and setups leave in a Linux x86_64 installation: the environments
`current` does not run, then the base packages no kept environment is over. Part of the Linux
package, like [`alphaavatar upgrade`](upgrade.md), which keeps the previous version and
environment for it.

```bash
alphaavatar cleanup --dry-run    # what would go, the space it takes, and what stays and why
alphaavatar cleanup              # remove it
```

| Option | Meaning |
| --- | --- |
| `--dry-run` | List what would be removed, its size, and what stays and why; nothing is written |

**Stop the Host first.** Cleanup takes `<prefix>/.install.lock`, the lock `install.sh`,
`alphaavatar setup` and `alphaavatar upgrade` take, so it never runs beside an installation;
the lock covers installations only, not a running Host. A Host started before an upgrade still
runs from the previous environment and base, which cleanup removes: stop every
`alphaavatar start`, `dev` and `doctor` of this installation before removing, and start it
again afterwards. `--dry-run` can run at any time.

## What it removes and keeps

Only the prefix's `envs/` and `versions/` change, and only directories the installer made:

| Removed | When |
| --- | --- |
| `envs/<plan>/` | Setup's environment (its mark, and the `plan.json` of the plan it is named after) that `current` does not run |
| `versions/<build>/` | A base package `install.sh` or `upgrade` unpacked (its manifest names it) that no kept environment is over |
| `envs/.setup-*/`, `versions/.install-*/` | A stage a stopped run left, marked as the installer's |

The environments go first, then the bases. What stays is listed with why:

- `current`: the environment it points to and the base that environment is over, or the base
  it points to;
- every base a kept environment is over;
- the build and environment running this command;
- what cleanup cannot tell the installer made: a symbolic link, a file, a directory without
  setup's mark, a `plan.json` that is missing, unreadable, names a base outside `versions/` or
  another plan than the environment's name, a directory of `versions/` no manifest names. A
  `plan.json` that is not its environment's tells no base, whatever base it names. While the
  base of a kept environment cannot be told, no base is removed;
- a directory holding the application home or its cache, or inside one, a stage a stopped run
  left included. The home is the one `start` would use: `ALPHAAVATAR_HOME` from the
  environment, or from the `.env` file `ENV_FILE` names when the environment's is unset or
  empty, or the default.

The application home (bundles and profiles, settings, stored credentials, Avatar workspaces and
the model cache) is outside `envs/` and `versions/` and never changes; neither do `current`,
the `alphaavatar` command and the lock.

Removing surveys again under the lock: what `current` points to and what each environment is
over are read as they are then, whatever `--dry-run` showed before. Each directory is first
moved into a marked stage, then removed; an interrupted cleanup leaves no part of an
environment in place, only a stage the next cleanup or installation removes.

```text
AlphaAvatar / Cleanup

01  Survey         2 to remove · 2,034 MB · 2 kept

  Prefix       ~/.local/lib/alphaavatar
  Current      envs/e003187213a2f154 · AlphaAvatar 0.6.9-f3ffa11c18dd

Would remove
  envs/7c360b3f811392e7         1,816 MB · environment over AlphaAvatar 0.6.9-62c87e3d33de
  versions/0.6.9-62c87e3d33de     219 MB · AlphaAvatar 0.6.9-62c87e3d33de

Kept
  envs/e003187213a2f154         current
  versions/0.6.9-f3ffa11c18dd   kept environments are over it: envs/e003187213a2f154 (current)

OK    Would free 2,034 MB; nothing was removed

Next
  With every `alphaavatar start` of this installation stopped:
  alphaavatar cleanup
```

Run by the previous build's environment instead (`<prefix>/envs/<old>/bin/alphaavatar`), the
same survey keeps that environment, as it runs the command, and its base, as a kept
environment is over it:

```text
Kept
  envs/7c360b3f811392e7         runs this command
  envs/e003187213a2f154         current
  versions/0.6.9-62c87e3d33de
    kept environments are over it: envs/7c360b3f811392e7 (runs this command)
  versions/0.6.9-f3ffa11c18dd   kept environments are over it: envs/e003187213a2f154 (current)

OK    Nothing to remove
```

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Removed, nothing to remove, or `--dry-run` printed |
| 1 | Refused: another installation running, `current` missing or not the installer's, a directory that cannot be removed, not run from a Linux package; what was removed before it is said |
| 2 | Another error |
| 130 | Interrupted with Ctrl+C; 143 for SIGTERM, 129 for SIGHUP: what was being removed stays in a marked stage |
