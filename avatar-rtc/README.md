# AlphaAvatar RTC

`alpha-avatar-rtc` owns transport-specific adapters. Its base package depends only
on `alpha-avatar-core`; the `livekit` extra enables LiveKit codecs and adapters.

```python
from alphaavatar.rtc.livekit.audio.codec import from_livekit_audio_frame, to_livekit_audio_frame
from alphaavatar.rtc.livekit.audio.input import LiveKitAudioInput
from alphaavatar.rtc.livekit.audio.output import LiveKitTransientAudioOutput
from alphaavatar.rtc.livekit.status.output import LiveKitStatusOutput
from alphaavatar.rtc.livekit.transcript.output import LiveKitTranscriptOutput
from alphaavatar.rtc.livekit.video.codec import from_livekit_video_frame, to_livekit_video_frame
from alphaavatar.rtc.livekit.video.input import LiveKitVideoInput
```

Transport-neutral image conversion lives in `alphaavatar.core.media.codecs.video`
and is available through `alpha-avatar-core[video]`.

## Lifecycle and ownership

Input adapters receive a LiveKit room and the shared `PerceptionRuntime`.
Output adapters receive a room and the shared `OutputRuntime`.

Adapters expose `on_session_start()` and `on_session_stop()`, structurally
satisfying `alphaavatar.core.lifecycle.SessionLifecycle`.

Each adapter owns its subscriptions, callbacks, tasks, and transport resources.
It must not close the shared room, PerceptionRuntime, or OutputRuntime.

Input adapters unregister only their own room callbacks. Partial startup failures
trigger owned cleanup. Concurrent shutdown requests share one cleanup task, and
caller cancellation is propagated after that cleanup finishes.

An input adapter instance is not restarted after shutdown. Create a new instance
for a new attachment.

Frame identity and source-generation semantics are preserved. Video conversion
remains off the event-loop thread, with binding and source-state checks before
publishing the result.

The package root does not import a backend. RTC adapters must not depend on
`alphaavatar.agents`, perception plugins, or `livekit.agents`.

## Migration status

Audio/video frame codecs, media inputs, and audio/status/transcript outputs live
in this package. Application assembly and lifecycle coordination live in Host.

The audio output adapter still handles only `OutputLane.TRANSIENT`. Assistant
response generation and final TTS remain on the temporary Agents path.

The temporary Agents model/turn/response bridges remain in `avatar-agents` for
removal in item 12. SDK execution ownership is still being migrated.

External messaging bridges are not part of this package or the current Host
entrypoint. Native text interaction and RTC data-channel transport remain in scope.

This migration does not change the current session-scoped execution semantics.
