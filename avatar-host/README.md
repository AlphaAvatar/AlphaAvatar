# AlphaAvatar Host

`alpha-avatar-host` owns application assembly and execution hosting.

It constructs the configured runtime and connects Agent execution, transport
adapters, and channel integrations. It is separate from command-line interaction,
model provider implementations, and transport-level media processing.

## Current entrypoint

Install the `livekit` extra to use the current LiveKit application entrypoint:

```text
alphaavatar.host.livekit.entrypoint:main
```

The `alphaavatar` command is temporarily registered by this package. Command
registration and argument handling will move to `avatar-cli` in item 13.
Application assembly remains here.

## Boundaries

- Host may depend on Agent, RTC, and channel interfaces and implementations.
- Agent and RTC libraries must not import Host.
- Package roots do not eagerly import runtime components or transport backends.
- Shared Foundation services remain owned through `AvatarRuntime.foundation`.

## Migration status

The system entrypoint and runtime construction have moved out of `avatar-agents`.
The existing session-owned execution behavior is unchanged.

Engine-managed RTC lifecycle phases, input adapters, channel bridges, and
LiveKit Agents execution ownership are still being migrated.

`close_session_execution()` closes the current AgentSession and its associated
AvatarRuntime. It is not a transport-only detach operation.

This package does not yet implement connection-independent Episodes, persistent
Context recovery, run tracking, automatic sleep/wake, or Dream scheduling.
