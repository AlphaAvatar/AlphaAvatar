# `alphaavatar dev`

Run the AlphaAvatar Host for development.

```bash
ENV_FILE=.env.dev alphaavatar dev [<bundle> | <file>] [KEY=VALUE ...]
```

Same as [`alphaavatar start`](start.md), except:

- DEBUG logging.
- The health server uses any free port.

It does not watch files or reload code.
