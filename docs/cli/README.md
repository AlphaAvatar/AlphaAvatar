# `alphaavatar` commands

`alphaavatar` runs and configures an AlphaAvatar Host. On Linux x86_64, `install.sh` installs it
with its own Python; see [DEPLOY.md](../../DEPLOY.md#or-install-the-linux-package-then-choose-capabilities).
In a source checkout it is the command of the `alpha-avatar-host` package.

| Command | Does |
| --- | --- |
| [`alphaavatar setup`](setup.md) | Choose capabilities, install what they need, then enable a bundle; in the Linux package |
| [`alphaavatar config init`](config.md#config-init) | Create a minimal bundle and its profiles |
| [`alphaavatar config check`](config.md#config-check) | Validate a configuration without starting anything |
| [`alphaavatar doctor`](doctor.md) | Diagnose the installation and a configuration |
| [`alphaavatar start`](start.md) | Run the Host as a long-running service |
| [`alphaavatar dev`](dev.md) | Run the Host for development |
| [`alphaavatar test`](test.md) | Planned: scenarios and benchmarks |

`config check`, `doctor`, `start` and `dev` choose a configuration and read credentials the same
way: see [choosing a configuration](config.md#choosing-a-configuration) and
[credentials](config.md#credentials). `alphaavatar <command> --help` lists the options, and
`alphaavatar --version` prints the version.

## Output

`config init`, `config check`, `setup` and `doctor` print their text reports the same way:

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
| Group headings: `Configuration`, `Scenarios`, `Next`, … | Bold, the terminal's own color |
| `OK`, `PASS` | Green |
| `WARN` | Yellow |
| `FAIL`, `ERROR` | Red |
| `SKIP` | Gray |
| Everything else: labels, values, paths, figures | The terminal's own color |

- Values share a column. On a narrow terminal, a value too long for its line goes below its
  label, indented and wrapped at spaces; a path stays whole. Diagnostics and commands print
  whole too, so they can be searched for and copied.
- The width is `COLUMNS`, else the terminal's, else 100 for a pipe or a file.
- Colors appear only on a terminal: a pipe, `NO_COLOR` and `TERM=dumb` get the same lines,
  plain. A stream that cannot encode `·`, `→` or `—` gets `-`, `->` and `-`.
- `--json` and `setup --plan` print JSON alone on stdout; setup's questions then go to stderr.
