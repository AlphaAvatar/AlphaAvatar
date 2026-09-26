# Voice Plugin for AlphaAvatar

Voice is a Foundation-layer plugin. It provides VAD, STT, and TTS implementations used by `AvatarRuntime.foundation.voice`.

## Ownership

`VoiceService` belongs to the shared `FoundationRuntime`; Voice is not a separate runtime. Application assembly selects the voice components and injects the service before Router is constructed.

Router and other consumers borrow the components. They own their individual audio streams, buffers, requests, and cancellation state. Foundation owns the reusable components and closes them after consumers have stopped.

## Configuration and inference

The existing top-level `voice` YAML section is unchanged. A layer name is not added to plugin selections or Python imports.

Selecting the `silero` VAD plugin selects its inference runner for startup. The runner resolves its model files during initialization, not during plugin import. The source directory move does not alter model cache paths.

See [Model Loading](../../../docs/model-loading.md) and [Plugin Layout and Boundaries](../../README.md).

## Package

```text
Source:       avatar-plugins/foundation/avatar-plugins-voice
Distribution: alpha-avatar-plugins-voice
Namespace:    alphaavatar.plugins.voice
```

Existing SDK-specific adapters remain in their current implementation locations. Their later migration is separate from this package-layout change.
