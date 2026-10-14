# AlphaAvatar RTC

`alpha-avatar-rtc` owns transport-specific adapters. Its base package depends only on `alpha-avatar-core`; the `livekit` extra enables LiveKit codecs and adapters.

```python
from alphaavatar.rtc.livekit.audio.codec import from_livekit_audio_frame, to_livekit_audio_frame
from alphaavatar.rtc.livekit.audio.input import LiveKitAudioInput
from alphaavatar.rtc.livekit.audio.output import LiveKitTransientAudioOutput
from alphaavatar.rtc.livekit.status.output import LiveKitStatusOutput
from alphaavatar.rtc.livekit.text import LiveKitTextInput
from alphaavatar.rtc.livekit.transcript.output import LiveKitTranscriptOutput
from alphaavatar.rtc.livekit.video.codec import from_livekit_video_frame, to_livekit_video_frame
from alphaavatar.rtc.livekit.video.input import LiveKitVideoInput
```

Transport-neutral image conversion lives in `alphaavatar.core.media.codecs.video` and is available through `alpha-avatar-core[video]`.

## Lifecycle and ownership

Media inputs receive a LiveKit room and shared PerceptionRuntime. Text input receives an injected submit callback; Host binds it to Engine admission without introducing an RTC-to-Agents dependency. Output adapters receive a room and shared OutputRuntime.

Adapters expose `on_start()` and `on_stop()` for Core lifecycle coordination. Each owns its subscriptions, callbacks, tasks and transport resources. It must not close the shared room, PerceptionRuntime or OutputRuntime. HostExecution owns component ordering and runtime release; LiveKitConnection owns room-disconnection policy.

Partial startup triggers owned cleanup. Concurrent shutdown callers share cleanup, and caller cancellation is propagated after it settles. Closed input adapters are not restarted. Video conversion remains off the event-loop thread, with source-generation checks before publication.

The package root does not import a backend. RTC adapters must not depend on `alphaavatar.agents`, concrete perception plugins or `livekit.agents`.

## Native input and output

`LiveKitTextInput` consumes the `lk.chat` text stream, checks the transport-supplied sender identity and bounded complete content, then invokes the injected submit callback. It does not pre-publish a second perception copy. Attached byte streams are not implemented by this text adapter.

Despite its retained class name, `LiveKitTransientAudioOutput` serves both ASSISTANT and TRANSIENT output on one audio track. It does not own a model or a second TTS pipeline. Host supplies the audio format declared by the selected TTS provider.

Consumers read `event.output` and its typed scope, source and payload. Interruptions use Runtime-fixed exact targets, not a new broad match against a later output. Playback feedback and final transcript delivery remain distinct from generation completion. Internal status decisions and canonical records are not projected as client status content.

## Migration status

Codecs, media/text inputs and audio/status/transcript outputs live here. Application assembly lives in Host. Engine/Loop own native generation; Router owns synthesis and transcript synchronization. The obsolete SDK model/turn/response and record bridges are removed, not alternative supported paths.

Voice provides native async PCM synthesis; RTC only converts/delivers the resulting Core frames. SDK worker hosting elsewhere in the workspace remains. SDK-dependent Character transport is not enabled by the native Host. This migration does not yet provide connection-independent execution or persistent task recovery.
