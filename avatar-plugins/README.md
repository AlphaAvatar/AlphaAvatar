# Plugin Layout and Boundaries

This document describes the plugin workspace and its runtime boundaries. See the [plugin catalog](../README.md#alphaavatar-plugins) for capabilities and implementation status.

## Workspace layout

```text
avatar-plugins/
├── README.md
├── foundation/
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

## Layer responsibilities

### Foundation

Foundation plugins provide reusable components for other plugins. The current Voice plugin supplies VAD, STT, and TTS implementations through a shared `VoiceService`.

```text
AvatarRuntime
└── foundation: FoundationRuntime
    └── voice: VoiceService
        ├── vad
        ├── stt
        └── tts
```

Voice is a service within `FoundationRuntime`, not a separate runtime. Application assembly creates and injects the foundation before constructing its consumers.

Provider and Context already have implementations elsewhere in the project. Their migration into standalone Foundation plugins is planned; they are not yet services in `FoundationRuntime`.

### Perception

Perception-layer plugins provide user understanding, persistent memory, identity, interaction coordination, character presentation, and status feedback. This repository layer is broader than raw sensory processing and is distinct from the core `PerceptionRuntime` event infrastructure.

Router receives `runtime` directly and borrows voice components from `runtime.foundation.voice`. Its factory passes the required components to individual processors; it does not create another voice service or use an `InteractionRouterDependencies` wrapper.

Reflection, Planning, and Behavior are planned capabilities. Their catalog entries do not imply that package implementations already exist.

### Tools

Tool plugins provide research, document retrieval, and external operations. DeepResearch, MCP, and RAG retain their own implementation and configuration boundaries.

Sandbox is planned. RAG remains the current document-retrieval plugin; a future replacement is not introduced by the directory layout.

## Registration and lifecycle

`AvatarModulePlugin` registers module factories independently of LiveKit's plugin registry. Factories create configured instances; the registry does not own session-specific state.

`AvatarRuntimePlugin` defines the session lifecycle contract. Runtime plugins and their processors own their consumer cursors, queues, tasks, and modality-specific state.

Foundation owns its reusable service components. Consumers own their individual streams, requests, and cancellation state, and must stop before shared services are released. A consuming plugin must not close a borrowed foundation component.

Keep concrete plugin implementations out of the runtime composition layer. Inject services and retain lightweight, type-only imports where runtime imports would create a dependency cycle.

## Configuration and model initialization

Plugin configuration stays with the plugin or processor that owns it. Agent configuration selects a plugin and supplies its options; the directory layer is not a new configuration namespace.

`prepare_inference_runners()` passes the validated `AvatarConfig` object to plugin-owned selectors. Each selector returns only the runner classes required by the active configuration.

Workers reconstruct the selected runner plan. Selected runners resolve and load their model files during initialization, before serving realtime requests. Imports and factory registration must not download or load models, and changing enabled components requires restarting the CLI.

`InferenceRunner` is an execution contract, not a global runner registry. Bootstrap registration selects runners; it does not require eager model initialization.

See [Model Loading](../docs/model-loading.md) for cache paths, integrity checks, offline behavior, and local model overrides.

## Workspace maintenance

Place new packages under the appropriate layer and keep their public namespace independent of the physical directory. Update the root workspace sources, release package list, dependency declarations, and lockfile as required.

When moving an existing package, preserve package-relative resource paths and update repository-relative paths, editable lockfile sources, and documentation links. Airi remains a Character submodule: preserve its registered name and gitlink revision when changing its checkout path.

After resolving any stale editable paths, verify the lockfile and refresh the installed workspace:

```bash
uv lock --check
uv sync --all-packages --locked
```

Add one row to the root plugin catalog for each plugin, not for every processor or model backend. Link implemented plugins to their own README; keep planned entries clearly marked without placeholder links. Put detailed configuration, model support, and extension guidance in plugin documentation.

See [Contributing](../CONTRIBUTING.md) for the release workflow and [v0.6.8 release notes](../docs/releases/v0.6.8.md) for the current migration scope.
