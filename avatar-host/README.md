# AlphaAvatar Host

`alpha-avatar-host` assembles Agent execution and transport adapters. It does not
implement model generation, prompt construction, media processing or Memory storage.

## Entrypoint

`alphaavatar.host.livekit.entrypoint:main` provides the current `alphaavatar` command.
Installer, configuration UI/TUI and doctor commands are planned for v0.6.9. Applications can assemble a
`HostExecution` directly without importing LiveKit.

## Lifecycle and ownership

`HostExecution(runtime=..., engine=..., inputs=..., outputs=...)` takes ownership
of the constructed components and the Runtime. Its startup order is:

```text
RTC outputs -> AvatarEngine -> RTC inputs
```

Shutdown stops inputs, settles Engine execution and plugin consumers, closes
outputs, then releases Runtime. Runtime is still closed when component cleanup
fails; failures are aggregated, not silently treated as successful cleanup.
`LifecycleGroup` owns concurrent startup within each phase and ordered shutdown
across phases. `LifecycleComponent.on_stop()` must tolerate partial and unstarted
initialization. Startup failure rolls back owned components, and repeated close
or caller cancellation cannot abandon accepted cleanup. Instances are single-use.

The entrypoint uses an `AsyncExitStack` before ownership transfers to HostExecution.
This covers construction failures and shutdown callback registration failure.
After transfer, only HostExecution releases its Runtime. `LiveKitConnection`
owns room events, monitors, disconnection and room cleanup; it delegates execution
shutdown to HostExecution. There is no `livekit.lifecycle` cleanup bridge.

## Boundaries and remaining work

Engine uses the native Loop/Provider/Output contracts. The old SDK AgentSession
generation, tool and record bridges are removed. OpenAI/Voice.ai TTS now use native async PCM providers. JobContext/worker hosting
still uses LiveKit Agents APIs and remains part of the v0.6.8 SDK-removal work. Native Character transport is
not yet implemented; enabled SDK-dependent Character configurations are rejected.

Agent and RTC libraries do not import Host. Shared Foundation services remain
owned through AvatarRuntime. Connection-independent Episodes, Context recovery,
sleep/wake and Dream scheduling are not implemented by this migration.
Session mode resolution stays in `alphaavatar.host.livekit.session`.
