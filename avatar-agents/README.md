# AlphaAvatar Agents

`alpha-avatar-agents` defines Agent execution contracts and runtime composition.
Concrete model backends and feature implementations live in plugin packages;
application hosting and transport assembly belong to Host and RTC.

## 📦 Package structure


## Native execution

```text
Router turn decision / direct input
    -> AvatarEngine
    -> Foundation Loop
    -> ContextManager + ProviderService + CapabilityRegistry
    -> OutputRuntime
```

AvatarEngine owns bounded Turn admission, duplicate/stale-input isolation, submission
and precise interruption. It does not inherit a LiveKit Agent, construct model prompts,
register SDK tools or write directly to Memory.

Loop owns model/tool execution and canonical record publication. ContextManager owns
bounded history and query preparation. Provider owns model clients and tracing. State
and static loop budgets are captured once per query, not rewritten between model steps.
Generation completion remains distinct from playback completion and interruption.

## Ownership

Provider schemas, enums and abstractions are in `alphaavatar.agents.avatar.provider`.
Plugin implementations must not introduce SDK types into Core or public output data.
Runtime components use Core LifecycleComponent and LifecycleGroup where appropriate.
AvatarRuntime composes Session, State, Core runtimes, Foundation, capabilities and its
inference client; it is not the plugin lifecycle manager.

Engine starts its consumers before Router enables decisions. It stops admission and
settles Loop execution while its canonical record consumers still exist. Plugin
finalization remains in each plugin. Host owns the surrounding execution lifecycle;
transport detachment releases RTC subscriptions independently of Engine destruction.

InferenceRuntime owns the shared endpoint and serial runner processes. InferenceExecutor
owns only client connections. Host supervises the service but does not create a second
owner for runner processes. Neither failed jobs nor state-changing requests are
replayed automatically by the Host.

## Configuration

Agent configuration selects plugins and processor-owned `init_config` settings. The
main model is `loop.init_config.model`; there is no SDK `llm` section. Tool registration
does not grant approval: exact capability policy or an Engine authorizer is required.
The native provider extras are selected on `alpha-avatar-plugins-provider`, not on an
Agents SDK `providers` extra.

Host loads the shared application file and removes `host` before strictly validating
AvatarConfig. Execution children restore a validated snapshot, retaining the original
Avatar identity and resolved workspace rather than appending the Avatar ID again.
The `alphaavatar` command and its argument parser belong exclusively to Host.

## Boundaries

Native TTS and Character use AlphaAvatar contracts, not AgentSession. Host supplies
Character's scoped RTC transport, and the Character plugin owns browser presentation.
Real renderer, RTC and provider integration still require end-to-end validation.

Session-scoped Perception/Output consistency checks remain unchanged. Persistent
Episodes, cross-attachment recovery, sleep/wake and Dream scheduling are separate work.
