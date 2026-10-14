# Voice Plugin for AlphaAvatar

Voice is a Foundation-layer plugin providing VAD, STT and TTS implementations used through `runtime.foundation.voice`.

## Ownership

The shared container is `VoiceBundle`, not VoiceService or a separate runtime. Host selects voice factories and injects the bundle before Router is constructed. Foundation owns the reusable factories and closes them after their borrowers stop.

Router processors own individual VAD/STT streams, TTS requests, queues and cancellation state. ASSISTANT and TRANSIENT synthesis share the selected TTS factory while retaining distinct output identities. Consumers do not close borrowed factories.

## Configuration and inference

```yaml
voice:
  vad:
    plugin: silero

  stt:
    plugin: openai_segment
    model: gpt-4o-transcribe

  tts:
    plugin: openai
    model: gpt-4o-mini-tts
    speaker: ash
    instructions: Speak in a friendly and conversational tone.
```

This is a configuration fragment; full examples also select Loop and Context. Model availability and credentials are deployment-specific.

Interruption policy belongs to `router.init_config.turn_taking.interruption`. The unused `voice.allow_interruptions` field is removed and rejected; it is not a second interruption switch.

Selecting Silero selects its inference runner. Models are resolved during runner initialization, not plugin import. See [Model Loading](../../../docs/model-loading.md) and [Plugin Layout and Boundaries](../../README.md).

## TTS and media contract

TTSBase declares `sample_rate` and `num_channels`; Host configures the RTC audio track from them. Actual frames must remain compatible with the declared format. The native audio path reuses Core AudioFrame/bytes and does not add a second SDK answer-generation chain.

SDK vendor TTS is currently adapted through LiveKitTTSAdapter. That vendor boundary is still present even though Engine/Loop generation, Router synthesis coordination and RTC delivery are native. It must not be described as complete removal of LiveKit Agents dependencies.

```text
Source:       avatar-plugins/foundation/avatar-plugins-voice
Distribution: alpha-avatar-plugins-voice
Namespace:    alphaavatar.plugins.voice
```
