# `alphaavatar dev`

Run the AlphaAvatar Host for development.

```bash
ENV_FILE=.env.dev alphaavatar dev <config> [KEY=VALUE ...]
```

Same as [`alphaavatar start`](start.md), except:

- DEBUG logging.
- Health endpoints use any free port.

It does not watch files or reload code.
