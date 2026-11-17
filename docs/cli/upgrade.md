# `alphaavatar upgrade`

Upgrade a Linux x86_64 installation to another build: its base package and, when
[`alphaavatar setup`](setup.md) made the environment `current` runs, the default bundle's
environment, both prepared and checked beside the current ones, then switched to at once. Part
of the Linux package; in a source checkout, `git pull` and `uv sync --all-packages --locked`
update it.

```bash
alphaavatar upgrade --check                 # the current build, the latest release's, and whether it upgrades
alphaavatar upgrade                         # to the latest release
alphaavatar upgrade --version 0.6.9         # to that release
alphaavatar upgrade --file ./alphaavatar-0.6.9-<commit>-linux-x86_64.tar.gz   # a CI build
```

| Option | Meaning |
| --- | --- |
| `--check` | Show the current build, the target's and whether it is an upgrade; nothing changes, and of a release only its manifest is downloaded |
| `--version X.Y.Z` | That release, instead of the latest |
| `--file PACKAGE` | A package already downloaded, such as a CI build of a commit; its SHA-256 from `--sha256` or `PACKAGE.sha256` beside it |
| `--sha256 HEX` | The package's SHA-256, instead of the `.sha256` file beside it |
| `--artifacts DIR\|URL` | Where the target build's own wheels are; by default beside `--file` for a CI build, and a release's in that release |

Stop `alphaavatar start` before upgrading, and start it again afterwards.

## Builds

A build is told by its ID, `<version>-<commit>` (a build of a checkout with changes adds
`-dirty.<time>`), as its package's manifest records it. Two builds of one version, such as two
CI builds of 0.6.9, are two builds, and either upgrades to the other:

```text
AlphaAvatar / Upgrade

OK    Upgradable to AlphaAvatar 0.6.9-3ade593c77ca
      Current      0.6.9-0600b13e01d0
      Target       0.6.9-3ade593c77ca
      From         /srv/ci/alphaavatar-0.6.9-3ade593c77ca-linux-x86_64.tar.gz

Next
  alphaavatar upgrade --file /srv/ci/alphaavatar-0.6.9-3ade593c77ca-linux-x86_64.tar.gz
```

A target that is the build current runs is current already: `--check` says so, and `upgrade`
ends at once, changing nothing. An older version is not an upgrade: `--check` says so and
`upgrade` refuses it.

A release publishes `alphaavatar-linux-x86_64.manifest.json` beside its package, so its build is
known before the package is downloaded: `--check` reads that file alone, and so does an upgrade
to the build already current. The release's package is
`alphaavatar-<version>-linux-x86_64.tar.gz` with its `.sha256`, as `install.sh --version` takes
it, and its own wheels are among its files.

To reproduce an upgrade between two CI builds, download each build's files (the
`alphaavatar-linux-x86_64-<commit>` artifact of the Linux package workflow) into a directory of
its own, install the first with `install.sh --file` and set it up, then upgrade with
`--file` to the second: its wheels are taken from beside it.

## What it does

```text
AlphaAvatar / Upgrade

01  Package        AlphaAvatar 0.6.9-3ade593c77ca · SHA-256 checked
02  Plan           Bundle my-avatar · 105 packages · 514 MB
03  Install        105 packages · 514 MB
04  Validate       PASS · 8 runners

OK    Upgraded to AlphaAvatar 0.6.9-3ade593c77ca
      Previous     0.6.9-0600b13e01d0
      Current      ~/.local/lib/alphaavatar/envs/73bcf97c85db5e92
      Bundle       my-avatar
      The previous version and its environment stay; nothing removes them.

Next
  alphaavatar doctor my-avatar
```

1. **Package**: the package, downloaded from its release or copied, matches its SHA-256, as
   for `install.sh`. It is unpacked into `<prefix>/versions/<build>/` and checked as
   `install.sh` checks one: its command reports its version, its help runs and the native
   libraries of the base load. `current` is not touched.
2. **Plan**: the target plans the environment for the default bundle with its own
   `alphaavatar setup <bundle> --plan`, so its configuration parser reads the bundle's settings
   and its catalog gives the packages. The plan also keeps what the current environment holds,
   so bundles set up earlier keep working. When `current` runs a base that has no setup
   environment, the target's base is switched to alone.
3. **Install**: each package of the plan, matching the size and SHA-256 the target's catalog
   records, into `<prefix>/envs/<plan>/` beside the current environment.
4. **Validate**: the new environment's command reports the target's version, its native
   libraries load, and its `config check` accepts the default bundle, with the credentials of
   the environment, `.env` and those stored.

Only then does `<prefix>/current` switch, once, and the command is run through it; if it does
not report the target, `current` goes back. Upgrading takes `<prefix>/.install.lock`, the lock
`install.sh` and `setup` take: another installation into the prefix is refused while one runs.

A failure or a signal before the switch leaves `current`, the command and the previous version
and environment as they were, and removes what this run made. The reason goes to stderr:

```text
FAIL  Upgrade failed; AlphaAvatar 0.6.9-0600b13e01d0 stays current
      The new environment fails check my-avatar:
        error: RuntimeError
          at alphaavatar.agents.runtime.plugin.resolution:189 in plan
        caused by: ValidationError
          fields: acceptance_marker
          at pydantic.main:705 in model_validate
      Fix what it names, then run `alphaavatar upgrade` again
```

A bundle the target does not accept fails at its plan or at the check; fix the bundle (or the
credentials it reads), then upgrade again. A package that does not match its SHA-256, a wheel
that cannot be fetched or does not match, a machine without the glibc or CPU the target needs,
and too little free space fail the same way.

Nothing in the application home is written: the default bundle and its profiles, the Avatar
ID, settings, stored credentials, workspaces and the model cache stay as they are. The
previous version and its environment stay in the prefix; nothing removes them, and there is no
command to go back to them.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Upgraded, the target current already, or `--check` printed |
| 1 | Nothing changed: a download, the SHA-256, the package, the plan, an install or the check failed; an older version; another installation running; not run from a Linux package |
| 2 | Nothing changed: another error |
| 130 | Interrupted with Ctrl+C; 143 for SIGTERM, 129 for SIGHUP |
