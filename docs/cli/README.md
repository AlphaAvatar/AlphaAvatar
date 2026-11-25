# `alphaavatar` commands

`alphaavatar` runs and configures an AlphaAvatar Host. On Linux x86_64, `install.sh` installs it
with its own Python; see [DEPLOY.md](../DEPLOY.md#or-install-the-linux-package-then-choose-capabilities).
In a source checkout it is the command of the `alpha-avatar-host` package.

| Command | Does |
| --- | --- |
| [`alphaavatar setup`](setup.md) | Install what a bundle needs, check it, then enable it: an existing bundle, or a new one asked from the reference configuration; in the Linux package |
| [`alphaavatar upgrade`](upgrade.md) | Upgrade the installation to another build, the latest release by default: prepared and checked beside the current one, then switched to once; in the Linux package |
| [`alphaavatar cleanup`](cleanup.md) | Remove the environments and builds `current` does not use, as upgrades leave them, with the Host stopped; `--dry-run` lists them; in the Linux package |
| [`alphaavatar config init`](config.md#config-init) | Create the reference bundle and its profiles |
| [`alphaavatar config check`](config.md#config-check) | Validate a configuration without starting anything |
| [`alphaavatar doctor`](doctor.md) | Diagnose the installation and a configuration: static checks, then the runtime diagnosis, its spoken scenario in rounds |
| [`alphaavatar start`](start.md) | Run the Host as a long-running service |
| [`alphaavatar dev`](dev.md) | Run the Host for development |
| [`alphaavatar test`](test.md) | Planned: scenarios and benchmarks |

`config check`, `doctor`, `start` and `dev` choose a configuration and read credentials the same
way: see [choosing a configuration](config.md#choosing-a-configuration) and
[credentials](config.md#credentials). `alphaavatar <command> --help` lists the options, and
`alphaavatar --version` prints the version.

## Output

`config init`, `config check`, `setup`, `upgrade`, `cleanup` and `doctor` print their text
reports the same way. [cli.html](cli.html), a page that opens offline, shows those of all but
`upgrade` and `cleanup` as a terminal shows them, colors and all:

```text
AlphaAvatar / Doctor
OK    9 passed · 6 skipped

Checks
  PASS  Environment            3 checks passed
  PASS  Configuration          my-avatar · 8 runners
```

| Part | Style |
| --- | --- |
| `AlphaAvatar / …` title | Brand blue, `#60a5fa` |
| The current setup step, its questions, and commands to copy | Signal cyan, `#22d3ee` |
| Groups of rows: config check's `Configuration`, `host`, `agent`, `plugins/…`; setup's install summary | Bold signal cyan |
| Other headings: `Scenarios`, `Next`, … | Bold, the terminal's own color |
| A state worth noticing that is no fault: a tool not on (`none`, `None enabled (default)`) | Yellow, with the state in words |
| `OK`, `PASS` | Green |
| `WARN` | Yellow |
| `FAIL`, `ERROR` | Red |
| `SKIP` | Gray |
| Everything else: labels, values, paths, figures | The terminal's own color |

- Values share a column. On a narrow terminal, a value too long for its line wraps at spaces,
  going on under its own start; where there is too little room beside the label, or a word,
  such as a path or a model ID, would not fit there, it goes below the label. A path, a model
  ID and a command to copy stay whole. Diagnostics and commands print
  whole too, so they can be searched for and copied. A setting at fault that does not fit its
  line, such as a missing package or a variable holding no value, is split instead: the
  setting, what is wrong, the package and what installs it, a line each.
- The width is `COLUMNS`, else the terminal's, else 100 for a pipe or a file.
- Colors, and a line redrawn in place (setup's step in progress, Doctor's running tests), appear
  only on a terminal: a pipe, `NO_COLOR` and `TERM=dumb` get the same lines, plain, each
  progress line on a line of its own and nothing erased. A stream that cannot encode `·`, `→`
  or `—` gets `-`, `->` and `-`.
- `--json` and `setup --plan` print JSON alone on stdout; the steps and questions then go to
  stderr.
