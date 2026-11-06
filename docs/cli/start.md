# `alphaavatar start`

Run the AlphaAvatar Host as a long-running service.

```bash
alphaavatar start [<bundle> | <file>] [KEY=VALUE ...]
```

- Loads a bundle by name, a YAML/JSON file, or the default bundle when omitted; see
  [choosing a configuration](config.md#choosing-a-configuration).
- Reads each variable from the environment, then `.env` (`ENV_FILE`), then the credentials
  [`alphaavatar setup`](setup.md) stored; see [credentials](config.md#credentials).
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
