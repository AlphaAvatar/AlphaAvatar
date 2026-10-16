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

Selecting Silero selects its inference runner. Models are resolved during runner initialization, not plugin import. See [Model cache](../../../docs/models-cache-layout.md) and [Plugin Layout and Boundaries](../../README.md).

## Native TTS and media contract

TTSBase declares an immutable `sample_rate` and `num_channels`. Host configures the
RTC audio track from them. `synthesize(text)` returns a single-consumer TTSStreamBase
with `aclose()`; Router already consumes this contract with `contextlib.aclosing`.

Both `openai` and `voiceai` are AvatarModulePlugin factories. Agents configuration
neither constructs a vendor SDK nor wraps one in LiveKitTTSAdapter. The adapter,
SDK chunked streams and SDK audio emitter are removed from the TTS path.

| Plugin | Endpoint | Requested wire format | Core output |
| --- | --- | --- | --- |
| OpenAI | `/v1/audio/speech` | `response_format: pcm`, `stream_format: audio` | 24 kHz mono PCM_S16LE |
| Voice.ai | `/api/v1/tts/speech/stream` | `audio_format: pcm_32000` | 32 kHz mono PCM_S16LE |

Provider schemas live in `tts/openai.py` and `tts/voiceai.py`; `tts/pcm.py` owns the
common async HTTP transport and bounded stream lifecycle. It uses the already
declared aiohttp dependency. It does not decode compressed audio or resample PCM.
TCP fragments are assembled into immutable Core frames; this is not an end-to-end
zero-copy claim. Audio content is not stored in an unbounded response buffer.

Each provider lazily opens one reusable HTTP session. Each admitted request owns
at most one producer task and a bounded frame queue; there is no task per frame.
Dormant requests count against capacity until closed, and do not start HTTP until
first consumption. Exhaustion, early exit and cancellation must close the stream.
Closing the factory first closes all streams, including dormant ones, then the
HTTP session. Concurrent close callers share managed cleanup, and a caller's
cancellation is propagated after that cleanup has completed.

These optional `voice.tts` settings retain the flat configuration layout:

```yaml
voice:
  tts:
    plugin: openai
    model: gpt-4o-mini-tts
    speaker: ash
    timeout: 30.0
    frame_size_ms: 20
    queue_frames: 8
    max_streams: 4
    max_audio_seconds: 120.0
```

The request timeout includes HTTP and local queue backpressure. Router's phrase
workflow may impose a shorter deadline. These limits bound the provider's own
requests and frame queue, not the OS/TCP buffers or whole-process memory. Slow
consumption fails explicitly at its deadline rather than silently dropping frames.
Requests are not retried automatically, including after partial audio delivery.

Non-200 responses, content-type mismatches, encoded/compressed responses, empty
bodies, truncated samples and excessive audio are errors. Common container headers
are rejected rather than being played as raw PCM. This does not prove the content
or sample rate of arbitrary raw bytes: that remains a vendor wire-contract promise.
Voice.ai's generated API reference labels the default response as audio/mpeg while
also listing PCM output options. This implementation requires an actual PCM-compatible
content type; a mismatched live response fails, never guesses or plays MP3 as PCM.
Vendor-account integration and listening tests remain required before release.

Keys come from `OPENAI_API_KEY` and `VOICEAI_API_KEY`, not YAML key fields. OpenAI
also honors `OPENAI_BASE_URL`; `voice.tts.base_url` explicitly overrides the endpoint
base for either provider. Remote endpoints require HTTPS; loopback HTTP is permitted
for local gateways/tests. Embedded URL credentials, query strings, fragments and
redirect following are rejected. Errors omit credentials, input text and HTTP error
bodies. A local provider endpoint remains a trusted operator configuration.

OpenAI instructions are passed through when configured; models `tts-1` and `tts-1-hd`
reject them. Voice.ai does not accept this instructions setting and rejects it
rather than ignoring it. User-facing applications must disclose AI-generated speech.

Router still owns phrase segmentation, output identity, interruption, alignment and
completion barriers. TTS transport closure is not proof of playout or a new source
of OutputRuntime control events. Native Host owns application and execution-process
hosting. Native Character presentation consumes the existing RTC audio, without
another TTS provider or playback track.

## Wire references

- [OpenAI speech API](https://developers.openai.com/api/reference/resources/audio/subresources/speech/methods/create)
- [OpenAI speech formats](https://developers.openai.com/api/docs/guides/text-to-speech#supported-output-formats)
- [Voice.ai streaming API](https://voice.ai/docs/api-reference/text-to-speech/speech-stream)

```text
Source:       avatar-plugins/foundation/avatar-plugins-voice
Distribution: alpha-avatar-plugins-voice
Namespace:    alphaavatar.plugins.voice
```
