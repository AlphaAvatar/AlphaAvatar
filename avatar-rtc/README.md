# AlphaAvatar RTC

`alpha-avatar-rtc` owns transport-specific adapters. Its base package depends only on
`alpha-avatar-core`; the `livekit` extra enables LiveKit frame conversion.

```python
from alphaavatar.rtc.livekit.audio_codec import from_livekit_audio_frame, to_livekit_audio_frame
from alphaavatar.rtc.livekit.video_codec import from_livekit_video_frame, to_livekit_video_frame
```

Transport-neutral image conversion lives in `alphaavatar.core.media.codecs.video`
and is available through `alpha-avatar-core[video]`. Perception plugins must use
these neutral helpers rather than importing a LiveKit adapter.

The package root does not import a backend. RTC adapters must not depend on
`alphaavatar.agents`, perception plugins, or `livekit.agents`.

## Migration status

Frame codecs have moved here. Audio/video input, output adapters, and connection
assembly remain in `avatar-agents` until the next migration batch. The temporary
Agents model/turn/response bridges remain there for removal in item 12.
