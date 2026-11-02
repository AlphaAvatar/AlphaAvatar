# `alphaavatar doctor`

**Planned — not available yet.**

Diagnose a configured AlphaAvatar system: run bounded, representative checks across the
enabled capabilities and explain what works, what is degraded and why.

```bash
alphaavatar doctor                            # Diagnose the current installation and configuration
alphaavatar doctor --list                     # List checks and their requirements
alphaavatar doctor --runtime                  # Include bounded local runtime and model checks
alphaavatar doctor --live                     # Opt in to checks that use real services or devices
alphaavatar doctor --runtime --format json    # Machine-readable report
```

Doctor never prompts, downloads models or makes paid calls without explicit permission.

Today, use [`alphaavatar check`](check.md) for configuration and the Host health endpoints for
runtime readiness.
