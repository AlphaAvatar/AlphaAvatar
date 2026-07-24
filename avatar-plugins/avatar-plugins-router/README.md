# 🎯 AlphaAvatar Interaction Router Plugin

The Interaction Router coordinates real-time perception capabilities inside AlphaAvatar.

## 🧭 Module Overview

The Router receives shared perception data from `PerceptionRuntime` and dispatches it through independently managed processors.

Its responsibilities include:

* consuming raw audio, video, screen, and derived perception streams;
* applying perception enrichment such as voice activity detection;
* routing accepted speech into downstream STT and Persona consumers;
* coordinating future multimodal fusion and interaction decisions;
* keeping provider implementations separate from routing logic.

Voice capabilities such as VAD and STT are defined by the AlphaAvatar voice abstraction and implemented by voice plugins. The Router only decides how those capabilities are connected to perception streams.

## ⚙️ Runtime and Processors

`InteractionRouterRuntime` manages the lifecycle of multiple `RouterProcessorBase` implementations.

```text
InteractionRouterRuntime
├── AudioActivityProcessor
├── SpeechTranscriptionProcessor
└── Future processors
```

The runtime is responsible for:

* starting processors in registration order;
* stopping processors in reverse order;
* rolling back already-started processors when startup fails;
* ensuring processor names are unique.

Each processor owns one independent routing capability:

```python
class RouterProcessorBase:
    @property
    def name(self) -> str: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...
```

Processors may consume perception streams, publish derived observations, call injected capabilities, or produce routing decisions.

The default audio flow is:

```text
PerceptionRuntime.audio
        ↓
AudioActivityProcessor
        ↓
PerceptionRuntime.speech
        ↓
SpeechTranscriptionProcessor
        ↓
Transcription events
```

## 🧩 Supported Processors

| Processor                      | Input           | Output               | Function                                                                                                                                                    |
| ------------------------------ | --------------- | -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `AudioActivityProcessor`       | `audio` stream  | `speech` stream      | Uses the injected VAD capability to detect active speech, preserve pre-roll audio, and publish routed speech frames and completed audio segments.           |
| `SpeechTranscriptionProcessor` | `speech` stream | Transcription events | Sends routed speech frames to the injected STT capability and emits interim, final, and error transcription events without blocking perception consumption. |

Planned processors may include multimodal understanding, audio classification, visual event detection, intention routing, and turn-decision processing.

## 📦 Installation

```bash
pip install alpha-avatar-plugins-router
```

The plugin is loaded through the AlphaAvatar configuration.
