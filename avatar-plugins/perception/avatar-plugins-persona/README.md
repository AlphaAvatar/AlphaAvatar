# 🧬 AlphaAvatar Persona Plugin

Persona provides independently configurable user profiling, speaker recognition and face recognition. Concrete processing, identity resolution and persistence live in the plugin; public profile and processor contracts remain in Agents.

## Overview

```text
PersonaRuntime
├── ProfilerProcessor  -> profile deltas
├── SpeakerProcessor   -> speaker identity and attributes
├── FaceProcessor      -> visual identity and annotations
├── PersonaCache       -> active per-user state
└── PersonaStore       -> persistent profile/identity state
```

Each processor owns its configuration and lifecycle. Provider configuration and prompts are placed under the owning processor, not a parallel plugin-global provider tree. Disabling Profiler does not disable face/speaker identity recognition or profile persistence.

## Processors

| Processor | Main input | Responsibility |
| --- | --- | --- |
| Profiler | Committed conversation/Turn context | Extract persistent profile deltas without regenerating the complete profile. |
| Speaker | Routed speech observations | Compute speaker embeddings (CAM++; 3 s windows, and speech shorter than a window once at its own length), resolve identity and update voice attributes, each on its own bounded lane: a Turn's Context waits only for its segments' identities, up to `speaker.identity_wait_sec`; attributes reach later Turns. Vectors are stored per voice model, in `speaker_collection_name` suffixed with it (`_campplus`); another model's vectors are never searched or merged. |
| Face | Video/screen observations | Sample frames, recognize identities and publish face/attribute annotations. |

Speaker and Face use bounded inference queues and preserve source identity. Raw audio or video is not persisted as a Persona profile. Face annotations enrich perception evidence without overwriting its raw observation.

Profile loading, identity merging and runtime user metadata remain separate from model-based extraction. Timezone, login time, session ID and login count are system-observed values, not generated profile facts.

## Runtime and lifecycle

PersonaRuntime owns cache/context coordination, source binding, initial profile loading and final saving. It exposes Core lifecycle hooks `on_start()` / `on_stop()`. Processors keep `start()` / `stop(finalize=...)` so normal finalization remains distinct from startup rollback.

Partially started processors are tracked before their startup awaits. Shutdown stops all owned processors before final persistence; cancellation cannot simply abandon owned cleanup. Concurrent close requests share work. Cleanup or save failure remains an error, not a successful close because a log was emitted.

Profile state is loaded/persisted through PersonaStore, with LanceDB and Qdrant backends accessed through the shared inference runtime rather than synchronous database calls on the realtime loop.

A speaker track is one voice in the session: it is matched on any source and generation, keeps each it was heard on, and lasts until the speaker processor stops; tracks are not limited in number. A speaker track's vector and a participant's speaker vector are each the mean of the segments they took, every segment's vector weighted by the seconds of audio it is from: a 3 s window, or a shorter segment's own length. The participant's vector stays apart from the user's stored speaker vector while the session runs. A save merges it into the one loaded for the same identity, 0.95 stored / 0.05 session; participants bound to one user save one vector of all their speech. A user with no stored speaker vector takes it as is, as does a user the session allocated, which has nothing stored; for another user whose load did not complete, the stored speaker vector is left unchanged.

## Capabilities and context

Enabled processors contribute to AvatarCapabilityRegistry. Capabilities are runtime descriptors and, where callable, typed operations; they are not merely prompt metadata. Disabled processors do not advertise enabled functionality.

Engine binds Persona as a read source to ContextManager. Context captures relevant source content for one query; it does not take ownership of Persona or ask it to rebuild State between model steps. Persona does not own foreground generation or RTC delivery.

## Configuration

```yaml
persona:
  plugin: default
  init_config:
    profiler:
      enabled: true
    speaker:
      enabled: true
      inference_queue_size: 1
    face:
      enabled: false
```

This fragment illustrates independent enablement. Complete examples also configure embedding storage and the Profiler provider gateway. Voice-only examples explicitly disable Face and visual addressing; multimodal examples can enable them. See [Examples](../../../examples/README.md).

## Installation and development

```bash
pip install alpha-avatar-plugins-persona
```

The workspace still declares Python 3.11 support; the project-wide Python upgrade is separate work.

Keep responsibilities local:

```text
Identity/cache orchestration -> PersonaRuntime
Persistence                  -> PersonaStore
Public profile contracts     -> alphaavatar.agents.persona.schemas
Profiler implementation      -> processors/profiler/
Speaker implementation       -> processors/speaker/
Face implementation          -> processors/face/
```

Do not move modality-specific implementation into Engine merely to share startup logic. Foundation services are borrowed, and their owner releases them only after Persona has stopped.
