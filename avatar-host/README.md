# AlphaAvatar Host

`alpha-avatar-host` owns application assembly and execution lifecycle coordination.

It connects Agent execution and native-client transport adapters without moving
model execution or media processing into the application layer.

## Entrypoint and CLI

The current LiveKit entrypoint is:

```text
alphaavatar.host.livekit.entrypoint:main
```

The `alphaavatar` command is registered by this package. Item 13 will organize
command handling under `alphaavatar.host.cli`, not a separate distribution package.

Applications may use Host interfaces directly without going through CLI parsing.

## Lifecycle ownership

`HostSessionLifecycle` coordinates:

```text
RTC outputs -> AvatarEngine -> RTC inputs
```

`AvatarEngine` starts its own consumers before the Router. Shutdown reverses the
stage order, stopping RTC inputs before Agent consumers and outputs.

Concurrent start and close requests share their respective tasks. A lifecycle
instance is not restarted after closure. Startup failures roll back completed
stages, and cancellation does not interrupt owned rollback or shutdown cleanup.

The entrypoint waits for Host startup before sending native-client READY status.

Components remain responsible for cleaning up resources acquired by their own
failed or cancelled startup.

## Boundaries

- Host may depend on Agent and RTC interfaces and implementations.
- Agent and RTC libraries must not import Host.
- AvatarEngine does not receive RTC adapters or manage their lifecycle.
- Package roots do not eagerly import execution components or transport backends.
- Shared Foundation services remain owned through `AvatarRuntime.foundation`.

## Migration status

`LiveKitHostedAgent` temporarily connects SDK lifecycle hooks to Host. It does not
implement model execution and will be removed with the LiveKit Agents path.

Audio/video input adapters now live in `avatar-rtc` and receive the shared
PerceptionRuntime through constructor injection. Host retains application
assembly and lifecycle coordination.

External messaging bridges and their application dispatch path have been removed.
LiveKit Agents execution ownership is still being migrated.

Native session modes are configured in `alphaavatar.host.livekit.session`.
The existing `chat`, `agent`, `audio`, and `video` values remain supported.
Room names and external-channel metadata do not select execution paths.

`close_session_execution()` closes the SDK session, ensures Host components are
closed, then closes the session-owned AvatarRuntime. It is not transport-only
detach.

Execution remains session-scoped. Connection-independent Episodes, persistent
Context recovery, run tracking, sleep/wake, and Dream scheduling are not
implemented by this migration.
