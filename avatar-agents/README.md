# AlphaAvatar Agents

`alpha-avatar-agents` defines Agent execution contracts and runtime composition. Concrete model backends and feature implementations live in plugin packages; application/transport assembly lives in Host and RTC.

## Native execution

```text
Router turn decision / direct input
    -> AvatarEngine
    -> Foundation Loop
    -> ContextManager + ProviderService + CapabilityRegistry
    -> OutputRuntime
```

AvatarEngine owns bounded Turn admission, duplicate/stale-input isolation, submission and precise interruption. It does not inherit the LiveKit Agent, hold an SDK ChatContext, construct model prompts, register SDK tools, or write directly to Memory.

Loop owns model/tool execution and canonical record publication. ContextManager owns bounded native history and captured query preparation. Provider owns model clients and tracing. Static State and loop budgets are captured once per query, not rewritten between model steps.

Generation completion is not playback completion. Successful generation does not revoke remaining audio delivery; interruption and output completion retain their separate Runtime semantics.

## Contracts and ownership

Public provider schemas, enums and abstractions are in `alphaavatar.agents.avatar.provider`. Plugin implementations must not introduce SDK types into Core or the public output data contract.

`AvatarModulePlugin` registers factories. Runtime components implement Core's `LifecycleComponent` (`on_start` / `on_stop`), and use `LifecycleGroup` where phase orchestration is appropriate. AvatarRuntime remains the shared composition of Session, State, Core runtimes, Foundation, capabilities and inference resources; it is not the plugin lifecycle manager.

Engine starts its consumers before Router enables decisions. During shutdown it stops admission and settles Loop execution while Memory, Status and Output consumers still exist. Plugin-specific finalization remains in each plugin. Host then closes RTC outputs and the AvatarRuntime it owns.

## Inference process ownership

`InferenceRuntime` owns a bounded local endpoint and independent serial runner processes;
`InferenceExecutor` only owns its client connections. Dispatched request readers remain
owned after caller cancellation, preventing an old response from being attributed to the
next request. Shutdown closes partial initialization, reports cleanup failures and reaps
processes without blocking the event loop on process joins.

See [Inference process ownership](../docs/inference-runtime.md) for cancellation/outcome
semantics, limits and shutdown behavior. Host now owns inference startup and supervision
through its LiveKitWorker adapter; Agents no longer carries a copied SDK worker.run.
SDK dispatch and JobContext remain behind that Host boundary.

## Configuration

Agent configuration selects plugins and passes processor-owned settings through `init_config`. Complete configurations and the five-section layout are documented in [Examples](../examples/README.md).

The main model is `loop.init_config.model`; there is no SDK `llm` section. Loop cannot be disabled with `null`. Tool registration does not grant approval: execution requires a suitable exact-capability policy or an injected asynchronous Engine authorizer.

The `alphaavatar` command belongs to `alpha-avatar-host`. Agents is usable as a library without the Host CLI.

## Current boundary

The obsolete TurnController and SDK model/turn/response bridges have been removed. OpenAI and Voice.ai TTS now use native async PCM providers behind TTSBase/TTSStreamBase. Agents Character contracts are transport-neutral; Host supplies the scoped RTC connection and the Character plugin owns browser presentation. No AgentSession is passed to Character. SDK worker hosting remains in the workspace; renderer/RTC integration still requires end-to-end validation.

Execution is still scoped to the current Host execution. Connection-independent Episodes, persistent execution recovery, sleep/wake and Dream scheduling remain separate work.
