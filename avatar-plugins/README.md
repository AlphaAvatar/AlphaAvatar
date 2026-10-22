# Plugin Layout and Boundaries

This document describes the plugin workspace and its runtime boundaries. See the [plugin catalog](../README.md#alphaavatar-plugins) for capabilities and implementation status.

## 📦 Package structure

```text
avatar-plugins/
├── README.md
├── foundation/
│   ├── avatar-plugins-context/
│   ├── avatar-plugins-loop/
│   ├── avatar-plugins-provider/
│   └── avatar-plugins-voice/
├── perception/
│   ├── avatar-plugins-character/
│   ├── avatar-plugins-memory/
│   ├── avatar-plugins-persona/
│   ├── avatar-plugins-router/
│   └── avatar-plugins-status/
└── tools/
    ├── avatar-plugins-deepresearch/
    ├── avatar-plugins-mcp/
    └── avatar-plugins-rag/
```

Each `avatar-plugins-*` directory is an independently packaged workspace member. The layer directories organize the repository; they are not Python packages or separate distributions.

Python namespaces remain `alphaavatar.plugins.<plugin>`, and distribution names remain `alpha-avatar-plugins-<plugin>`. Layer names are not added to imports, entry points, YAML plugin selections, or model cache namespaces.

This aggregate README contains the plugin package tree. Individual plugin READMEs describe their configuration, behavior and limits without repeating a Package structure section.

## Layer responsibilities

### Foundation

Foundation plugins provide reusable execution and model services through `AvatarRuntime.foundation`:

```text
AvatarRuntime
└── foundation: FoundationRuntime
    ├── context: ContextManager
    ├── loop: Loop
    ├── provider: ProviderService
    └── voice: VoiceBundle
        ├── vad
        ├── stt
        └── tts
```

Host constructs Context, Voice and the required Loop, binds Foundation to the runtime, and then initializes Loop. Loop initialization resolves its shared services and checks streaming support; it is not a foreground model request. A `null` Loop is not a disabled operating mode.

Context owns bounded native history and per-query preparation. Provider owns shared model clients and tracing, not conversation history or tool permissions. VoiceBundle owns reusable voice factories; Router owns the individual streams and synthesis jobs that borrow them.

The native main path is Engine -> Loop -> Context/Provider -> OutputRuntime. The OpenAI streaming backend and the LangChain structured-task backend have different capabilities; select `backend: openai` explicitly for the current native realtime Loop.

### Perception

Perception-layer plugins provide persistent memory, identity, interaction coordination, character presentation, and status feedback. This repository layer is broader than raw sensory processing and is distinct from Core's `PerceptionRuntime`.

Router receives `runtime` and borrows `runtime.foundation.voice`. Its factory passes required components to processors. Memory consumes committed Turns and canonical Output records independently. Persona owns identity/profile processing. Status consumes execution facts and produces typed presentation decisions and non-recursive narration.

The Character package provides native AIRI browser lifecycle through an injected CharacterTransport. Host owns room credentials and readiness callbacks; the plugin owns its browser. The shared trusted frontend is deployed separately, and no Character inference runner is registered. Current examples keep `character.plugin: null`; enabling it requires the Character deployment steps. Reflection, Planning and Behavior remain planned capabilities, not implemented standalone packages.

### Tools

DeepResearch, MCP and RAG own their operation schemas, implementations and configuration. Engine collects enabled capabilities; Loop invokes them through the native capability registry, with explicit execution policy and authorization. Tools do not receive a StatusEmitter or a `monologue` argument.

A registered capability is not automatically approved. Aggregate MCP or RAG capabilities must not be labelled read-only merely because one of their operations is read-only. Sandbox remains planned.

MCP owns native MCP client sessions in its isolated runner. One async task enters and exits each connection's transport/session scopes; the runner closes those owners before joining its loop thread. Network deadlines settle local work instead of abandoning a future and implicitly allowing a duplicate call. RAG storage finalization is serialized with its accepted operations.

## Registration and lifecycle

`AvatarModulePlugin` registers module factories independently of LiveKit's plugin registry. Factories create configured instances; the registry does not own execution-specific state.

`alphaavatar.core.lifecycle.LifecycleComponent` defines `on_start()` and `on_stop()`. `LifecycleGroup` owns ordered startup phases, parallel independent components within a phase, and reverse-phase cleanup. Cleanup also covers partial and unstarted initialization. Repeated close requests share owned work, and a closed instance is not restarted.

Processor interfaces can retain their own `start()` / `stop()` methods and meaningful finalization arguments. Memory and Persona keep their business-specific record draining and persistence in their runtimes; those responsibilities do not belong in Core.

`HostExecution` owns Engine and AvatarRuntime inside an execution child. SessionManager orders attachment outputs, Engine and then inputs. On termination, attachment cleanup releases ingress, presentation, subscriptions and the connection before HostExecution settles Engine and Runtime. Engine keeps its internal record consumers alive while accepted tool work settles. `LiveKitConnection` only reports connection events and releases transport resources; it neither destroys executions nor deletes rooms.

A consuming plugin must not close borrowed Foundation services. Keep Core independent of Agents, concrete plugins, Provider SDKs and LiveKit. Do not introduce transport adapters into Engine to share a lifecycle implementation.

## Configuration and model initialization

Examples use five sections: Avatar Identity & Workspace, Runtime, Foundation Plugins, Perception Plugins, and Tools Plugins. These headings organize authoring; the actual keys remain `avatar`, `runtime`, `loop`, `context`, `voice`, `vision`, `router`, `status`, `character`, `memory`, `persona`, and `tools`. `defaults` contains YAML anchors, not runtime configuration. An optional top-level `host` section configures application hosting and RTC; Host removes it before strict AvatarConfig validation.

Plugin configuration stays with its owning plugin or processor. The main model is configured under `loop.init_config.model`; temporal alignment belongs to `runtime.perception.temporal_alignment`. Conversation extraction and consolidation belong to `memory.init_config.conversation.pipeline`.

`prepare_inference_runners()` passes the validated AvatarConfig to plugin-owned selectors. Workers reconstruct the selected plan; selected runners resolve and load models during initialization, before serving realtime requests. Imports and factory registration must not download or load models. Changing enabled components requires restarting the application.

`InferenceRunner` is an execution contract, not a global runner registry. See [Model cache](../docs/models-cache-layout.md) for downloads, offline use and cleanup, [Avatar workspace](../docs/avatar-workspace-layout.md) for stored personal data and backups, and [Examples](../examples/README.md) for complete configurations.

## Workspace maintenance

Place new packages under the appropriate layer and keep their public namespace independent of the physical directory. Update workspace sources, release package lists, dependencies and lockfiles when changing package layout.

Preserve package-relative resources and update repository-relative paths, editable sources and documentation links. AIRI remains a Character submodule. Preserve its pinned revision; source-level lifecycle integration is not evidence of a successful real renderer/RTC validation.

```bash
uv lock --check
uv sync --all-packages --locked
```

Add one catalog row per plugin, not per processor or backend. Keep planned and unsupported integrations explicit. See [Contributing](../CONTRIBUTING.md) and the [v0.6.8 development release notes](../docs/releases/v0.6.8.md); native Host replaces Agents SDK worker hosting, but clean-install and real RTC/renderer validation remain separate requirements.
