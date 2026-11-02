# `alphaavatar config`

Show or create application configuration. Neither subcommand starts anything.

## `config show`

Print the effective configuration, with credentials removed.

```bash
alphaavatar config show <config> [KEY=VALUE ...] [--json]
```

- Shows plugin selections, runtime parameters and resolved paths after `.env`, overrides and
  defaults.
- `[redacted]`: credential-like fields and known credential values.
- `[hidden]`: text inside plugin-defined settings such as `init_config`, `vdb_config` and MCP
  `servers`. Numbers and booleans stay visible.
- Terminal output is highlighted YAML; pipes, `NO_COLOR` and `TERM=dumb` get plain YAML.
  `--json` prints plain JSON.
- Errors and exit codes match [`check`](check.md).

## `config init`

Create a minimal configuration file.

```bash
alphaavatar config init <path> --avatar-id <id>
```

- Writes the given Avatar ID with OpenAI model, voice, Memory and Persona settings; tools
  are disabled.
- Writes no credentials and no machine paths.
- Never overwrites an existing file; removes what it created if writing fails.

Then set these in the environment or `.env` and validate:

| Variable | Used for |
| --- | --- |
| `OPENAI_API_KEY` | Models, speech, embeddings, Memory and Persona |
| `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | Session transport |

```bash
alphaavatar check <path>
```

| Exit code | Meaning |
| --- | --- |
| 0 | Created |
| 2 | File exists, invalid ID or write failure |
