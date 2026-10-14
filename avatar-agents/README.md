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

## Configuration

Agent configuration selects plugins and passes processor-owned settings through `init_config`. Complete configurations and the five-section layout are documented in [Examples](../examples/README.md).

The main model is `loop.init_config.model`; there is no SDK `llm` section. Loop cannot be disabled with `null`. Tool registration does not grant approval: execution requires a suitable exact-capability policy or an injected asynchronous Engine authorizer.

The `alphaavatar` command belongs to `alpha-avatar-host`. Agents is usable as a library without the Host CLI.

## Current boundary

The obsolete TurnController and SDK model/turn/response bridges have been removed. OpenAI and Voice.ai TTS now use native async PCM providers behind TTSBase/TTSStreamBase. SDK worker hosting and SDK-dependent Character integrations still remain in the workspace. The native Host rejects enabled Character plugins until their transport is migrated.

Execution is still scoped to the current Host execution. Connection-independent Episodes, persistent execution recovery, sleep/wake and Dream scheduling remain separate work.
