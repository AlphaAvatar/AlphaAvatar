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

`voice.stt.language` and `voice.stt.prompt` are optional; both are unset by default.
- `language` is an ISO-639-1 code (`zh`, `en`) the model takes as given. Unset, or `auto`, sends none: the model detects the language itself, which is what speech that mixes or switches languages needs. A fixed language is a hint, not detected evidence; `TranscriptionEvent.language` repeats this setting and is never a detection.
- `prompt` guides the transcription (names, style, keeping every sentence).
- `openai_segment` takes both; `openai_realtime` takes `language` and `delay` but no `prompt`. A setting the selected implementation does not take is refused by `config check`, at its location (`voice.stt.prompt`), as any unknown setting is.

Interruption policy belongs to `router.init_config.turn_taking.interruption`. The unused `voice.allow_interruptions` field is removed and rejected; it is not a second interruption switch.

Selecting Silero selects its inference runner. Models are resolved during runner initialization, not plugin import. See [Model cache](../../../docs/layouts/models-cache.md) and [Plugin Layout and Boundaries](../../README.md).

## Native TTS and media contract

TTSBase declares an immutable `sample_rate` and `num_channels`. Host configures the
RTC audio track from them. `synthesize(text)` returns a single-consumer TTSStreamBase
with `aclose()`; Router closes each stream it opens explicitly with `aclose()`.

Both `openai` and `voiceai` are AvatarModulePlugin factories; configuration constructs
no vendor client, and no LiveKit TTS adapter, chunked stream or audio emitter is on
the TTS path.

| Plugin | Request path | Requested wire format | Core output |
| --- | --- | --- | --- |
| OpenAI | `/v1/audio/speech` | `response_format: pcm`, `stream_format: audio` | 24 kHz mono PCM_S16LE |
| Voice.ai | `/api/v1/tts/speech/stream` | `audio_format: pcm_32000` | 32 kHz mono PCM_S16LE |

Provider schemas live in `tts/openai.py` and `tts/voiceai.py`; `tts/codec/pcm.py` owns
the bounded stream lifecycle, PCM framing, the request budget and retries for both.
OpenAI streams through the OpenAI SDK's streaming response over its own `httpx`
client, with the SDK's retries off; Voice.ai uses the codec's aiohttp transport.
Neither decodes compressed audio or resamples PCM.
TCP fragments are assembled into immutable Core frames; this is not an end-to-end
zero-copy claim. Audio content is not stored in an unbounded response buffer.

Each provider lazily opens one reusable HTTP client. Each admitted request owns a
bounded frame queue, its attempt tasks and a first-audio timer; there is no task per
frame.
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

`timeout` is the request's HTTP and retry waiting budget; frames waiting in the
queue and local playout do not spend it. A slow consumer pauses the producer, without
dropping frames, and the consumer's own deadline bounds that wait: Router's phrase
workflow may impose a shorter one. These limits bound the provider's own requests
and frame queue, not the OS/TCP buffers or whole-process memory.

A request makes at most `max_retries` + 1 attempts (default 1 + 1), and only before
its first frame is emitted; after audio has started nothing is retried. While the
first attempt has produced no audio after `first_audio_hedge_after` (default 2.5 s,
`null` disables it), one speculative attempt starts from that quota and the first to
produce audio wins: it can be billed as a second synthesis. `first_audio_timeout`,
`read_timeout` and `retry_interval` bound the first frame and the gaps between reads,
and set the pause before a retry, which grows with each attempt.

Non-200 responses, content-type mismatches, encoded/compressed responses, empty
bodies, truncated samples and excessive audio are errors. Common container headers
are rejected rather than being played as raw PCM. This does not prove the content
or sample rate of arbitrary raw bytes: that remains a vendor wire-contract promise.
Voice.ai's generated API reference labels the default response as audio/mpeg while
also listing PCM output options. This implementation requires an actual PCM-compatible
content type; a mismatched live response fails, never guesses or plays MP3 as PCM.
Vendor-account integration and listening tests remain required before release.

Keys come from `OPENAI_API_KEY` and `VOICEAI_API_KEY`, or the variable
`voice.stt.api_key_env` / `voice.tts.api_key_env` names, never YAML key fields. For
TTS, OpenAI also honors `OPENAI_BASE_URL`; `voice.tts.base_url` explicitly overrides
the URL base for either provider. TTS servers require HTTPS; loopback HTTP is
permitted for local gateways/tests. Embedded URL credentials, query strings,
fragments and redirect following are rejected. Errors omit credentials, input text
and HTTP error bodies. A local provider server remains a trusted operator
configuration. STT uses OpenAI's API unless `voice.stt.base_url` names another, and
does not read `OPENAI_BASE_URL`.

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
