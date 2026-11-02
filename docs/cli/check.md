# `alphaavatar check`

Validate a configuration and its read-only path checks without starting anything.

```bash
alphaavatar check <config> [KEY=VALUE ...] [--json]
```

Runs the same loading steps as `start`: `.env`, overrides, defaults, path resolution, schema
validation and read-only workspace checks. It starts no Host, runner or model, contacts no
service, creates no directories and needs no local log socket.

```text
OK  configuration and read-only path checks passed
    avatar_id  my-avatar
    home       /home/me/.local/share/alphaavatar
    workspace  /home/me/.local/share/alphaavatar/avatars/my-avatar
```

```text
ERROR  configuration and read-only path checks failed
  error: ValidationError
    fields: avatar.timezone
```

- Errors go to stderr and name the failing fields, never the rejected values.
- `--json` prints `{"valid": true, ...}` or `{"valid": false, "error": {...}}`.

| Exit code | Meaning |
| --- | --- |
| 0 | Valid |
| 2 | Invalid configuration or failed path check |
