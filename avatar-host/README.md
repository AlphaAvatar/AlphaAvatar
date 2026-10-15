# AlphaAvatar Host

`alpha-avatar-host` assembles Agent execution and transport adapters. It does not
implement model generation, prompt construction, media processing or Memory storage.

## Entrypoint

`alphaavatar.host.livekit.entrypoint:main` provides the current `alphaavatar` command.
Installer, configuration UI/TUI and doctor commands are planned for v0.6.9. Applications can assemble a
`HostExecution` directly without importing LiveKit.

## Lifecycle and ownership

`HostExecution(runtime=..., engine=..., inputs=..., outputs=..., presentations=...)` takes ownership
of the constructed components and the Runtime. Its startup order is:

```text
Optional Character readiness -> RTC outputs -> AvatarEngine -> RTC inputs
```

Shutdown stops inputs, settles Engine execution and plugin consumers, closes
outputs and Character presentation, then releases Runtime. Runtime is still closed when component cleanup
fails; failures are aggregated, not silently treated as successful cleanup.
`LifecycleGroup` owns concurrent startup within each phase and ordered shutdown
across phases. `LifecycleComponent.on_stop()` must tolerate partial and unstarted
initialization. Startup failure rolls back owned components, and repeated close
or caller cancellation cannot abandon accepted cleanup. Instances are single-use.

The entrypoint uses an `AsyncExitStack` before ownership transfers to HostExecution.
This covers construction failures and shutdown callback registration failure.
After transfer, only HostExecution releases its Runtime. `LiveKitConnection`
owns room events, monitors, disconnection and room cleanup; it delegates execution
shutdown to HostExecution. It also monitors the optional Character session.
There is no `livekit.lifecycle` cleanup bridge.

Host supplies a LiveKit Character transport for scoped credentials and authenticated
READY/video checks. The Character plugin owns the browser; the shared frontend is
served separately. Exact renderer identities are excluded from audio/video input.
See [Character setup](../avatar-plugins/perception/avatar-plugins-character/README.md).

## Worker supervision

`alphaavatar.host.livekit.worker.LiveKitWorker` is the SDK dispatch adapter. It uses
public SDK run/close APIs rather than copying AgentServer.run or importing SDK IPC
internals. The old Agents `avatar/patches` package is removed.

Host starts the selected InferenceRuntime before the SDK can create job processes.
The entrypoint uses `spawn` for both inference and job processes, so each child gets
this worker's final endpoint. Four warm job processes and the existing load/close
settings are retained. This does not create four copies of each inference model.

Host owns the exposed HTTP health endpoint. `/` returns 503 while warming, closing,
or when inference is unhealthy, and 200 after the SDK worker has started and the
inference service is alive. It is not a probe of cloud model providers or a guarantee
that dispatch is currently registered. `/worker` exposes readiness, active job count
and inference method identifiers only. Its JSON is no longer the private SDK copy's
schema. The SDK keeps an internal loopback/ephemeral health listener for now.

Inference failure is checked every 0.5 seconds by default. It makes readiness fail
immediately when probed, causes the load callback to refuse capacity, and initiates
worker shutdown on detection. SDK job cleanup precedes inference cleanup; the health
endpoint keeps returning 503 while jobs settle. Neither jobs nor state-changing
requests are replayed automatically.

See [Worker hosting](../docs/worker-hosting.md) for cancellation and validation limits.
This is a reduction of the SDK boundary, not completion of SDK removal: dispatch,
JobContext, the job pool and the existing dev/start command runner remain SDK-backed.

## Boundaries and remaining work

Engine uses the native Loop/Provider/Output contracts. The old SDK AgentSession
generation, tool and record bridges are removed. OpenAI/Voice.ai TTS uses native
async PCM providers. JobContext/worker hosting still uses LiveKit Agents APIs.
AIRI Character uses native lifecycle/transport contracts, with no AgentSession.
Renderer/RTC end-to-end validation remains required; examples keep Character disabled.

Agent and RTC libraries do not import Host. Shared Foundation services remain
owned through AvatarRuntime. Connection-independent Episodes, Context recovery,
sleep/wake and Dream scheduling are not implemented by this migration.
Session mode resolution stays in `alphaavatar.host.livekit.session`.
