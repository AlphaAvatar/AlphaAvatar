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
