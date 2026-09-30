# AlphaAvatar RTC

`alpha-avatar-rtc` owns transport-specific adapters. Its base package depends only on
`alpha-avatar-core`; the `livekit` extra enables LiveKit codecs and output adapters.

```python
from alphaavatar.rtc.livekit.audio_codec import from_livekit_audio_frame, to_livekit_audio_frame
from alphaavatar.rtc.livekit.audio_output import LiveKitTransientAudioOutput
from alphaavatar.rtc.livekit.status_output import LiveKitStatusOutput
from alphaavatar.rtc.livekit.transcript_output import LiveKitTranscriptOutput
from alphaavatar.rtc.livekit.video_codec import from_livekit_video_frame, to_livekit_video_frame
```

Transport-neutral image conversion lives in `alphaavatar.core.media.codecs.video`
and is available through `alpha-avatar-core[video]`. Perception plugins must use
these neutral helpers rather than importing a LiveKit adapter.

## Lifecycle and ownership

Output adapters receive the LiveKit room and AlphaAvatar `OutputRuntime` through
constructor injection. They expose `on_session_start()` and `on_session_stop()`,
structurally satisfying `alphaavatar.core.lifecycle.SessionLifecycle`.

Each adapter owns its subscriptions, tasks, and transport resources. It does not
own or close the shared room or `OutputRuntime`. Session assembly controls startup
and shutdown order.

The package root does not import a backend. RTC adapters must not depend on
`alphaavatar.agents`, perception plugins, or `livekit.agents`.

## Migration status

Frame codecs and audio, status, and transcript output adapters have moved here.
Audio/video input and connection assembly remain in `avatar-agents`.

The audio adapter still handles only `OutputLane.TRANSIENT`. Assistant response
generation and final TTS remain on the temporary Agents path.

The temporary Agents model/turn/response bridges remain in `avatar-agents` for
removal in item 12.
