# `alphaavatar start`

Run the AlphaAvatar Host as a long-running service.

```bash
alphaavatar start <config> [KEY=VALUE ...]
```

- INFO logging; health endpoints on `127.0.0.1:8081`.
- Creates the application home and Avatar workspace on first run.
- Ctrl+C or SIGTERM stops it after every owned resource is released.
- Validates the configuration before starting; [`alphaavatar config check`](config.md#config-check) runs the same validation without starting.

| Exit code | Meaning |
| --- | --- |
| 0 | Stopped normally |
| 1 | Failed while running |
| 2 | Configuration or startup error |
| 130 | Interrupted |

For development, use [`alphaavatar dev`](dev.md).
