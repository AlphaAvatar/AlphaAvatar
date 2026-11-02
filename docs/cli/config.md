# `alphaavatar config`

Create or check application configuration. Neither subcommand starts anything.

## `config init`

Create a minimal configuration file.

```bash
alphaavatar config init <path> --avatar-id <id>
```

- Writes the given Avatar ID with OpenAI model, voice, Memory and Persona settings; tools
  are disabled.
- Writes no credentials and no machine paths; the Host chooses the application home.
- Never overwrites an existing file; removes what it created if writing fails.

Set these in the environment or `.env`, never in the file:

| Variable | Used for |
| --- | --- |
| `OPENAI_API_KEY` | Models, speech, embeddings, Memory and Persona |
| `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | Session transport |

Then start it with [`alphaavatar dev`](dev.md), or check it first.

## `config check`

Validate a configuration without starting anything. Optional: `start` and `dev` run the same
validation before they start.

```bash
alphaavatar config check <file> [KEY=VALUE ...] [--json]
```

It runs the same loading steps as `start` — `.env`, overrides, defaults, path resolution,
schema validation and read-only workspace checks — but starts no Host, runner or model,
contacts no service, creates no directories and needs no local log socket.

```text
OK  configuration and read-only path checks passed
    avatar_id  my-avatar
    home       /home/me/.local/share/alphaavatar
    workspace  /home/me/.local/share/alphaavatar/avatars/my-avatar
    rtc        livekit
    loop       realtime
    voice      vad=silero  stt=openai_segment  tts=openai
    router     default
    character  none
    memory     default  (vdb: lancedb)
    persona    default  (vdb: lancedb; speaker on, face off)
    tools      rag, mcp (1 server)
    inference  8 runners  (workers: alphaavatar.voice.vad.silero x2)
    health     127.0.0.1:8081 (dev: free port)
```

The summary lists plugin selections, vector store kinds, enabled tools, the inference
runners the Host would start with their worker counts, and the health address — never
endpoints, collection names or plugin-defined settings. A misspelled, unselected or
non-replicable `runtime.inference.methods` entry fails with its field location.

```text
ERROR  configuration and read-only path checks failed
  error: ValidationError
    fields: avatar.timezone
```

- Errors go to stderr and name the failing fields, never the rejected values.
- `--json` prints `{"valid": true, "avatar_id", "home", "workspace", "plugins", "inference",
  "health"}` (`inference` maps each runner method to its workers) or
  `{"valid": false, "error": {"type", "fields", "diagnostic"}}`, with credentials and control
  characters removed.
- Colors appear only on a terminal; pipes, `NO_COLOR` and `TERM=dumb` get plain text.

## Exit codes

| Code | `init` | `check` |
| --- | --- | --- |
| 0 | Created | Valid |
| 2 | File exists, invalid ID or write failure | Invalid configuration or failed path check |
