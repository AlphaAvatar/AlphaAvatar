# Native Engine examples

[中文](README-zh.md)

All five configurations use `loop.plugin: realtime` with the main model in
`loop.init_config.model`. `backend: openai` selects the native Responses backend;
plugin-local Memory/Persona providers retain their existing backend settings.
Model and voice identifiers are deployment choices, not guarantees of account access.
The main model identifier is preserved from the repository; change it to one available
on your configured provider before running. `temperature: null` avoids injecting a
sampling parameter into a model that may not accept it.

```bash
ENV_FILE=.env.dev alphaavatar config check examples/agent_configs/mm/pipeline_openai_tools.yaml  # optional
ENV_FILE=.env.dev alphaavatar dev examples/agent_configs/mm/pipeline_openai_tools.yaml
```

`defaults` contains YAML anchors only and is removed after aliases are resolved.
Unknown runtime sections, including the removed `llm` section, are rejected rather
than silently ignored. Native history is kept whole; the former
`context.init_config.history_max_*` settings are accepted and ignored.
Interruption is configured through `router.init_config.turn_taking.interruption`;
the unused SDK-era `voice.allow_interruptions` setting is removed and rejected.

## Configuration layout

The checked-in multimodal example is the formatting reference. All configurations use the same sections in order; only the multimodal example has the optional sixth:

1. Avatar Identity & Workspace
2. Runtime
3. Foundation Plugins (`loop`, `context`, `voice`, `vision`)
4. Perception Plugins (`defaults` anchors, `router`, `status`, `character`, `memory`, `persona`)
5. Tools Plugins (`tools`)
6. Host & RTC Access (`host`)

Keep two-space indentation, section separators and purposeful blank lines. Preserve folded introduction/voice instructions and YAML anchors; do not replace them with serialized one-line strings.

Temporal alignment is `runtime.perception.temporal_alignment`, not a sibling of perception. Conversation pipeline configuration contains extraction and consolidation only. `item_ops`, `candidate_source`, `similarity_threshold`, `max_candidates_per_item` and `timeout` now belong inside `pipeline.consolidation`; a `pipeline.maintenance` mapping is rejected.

The multimodal reference and Demo set `candidate_source: union`; voice-minimal sets `consolidated_lookup` explicitly; the Hiyori examples retain the processor default, `consolidated_lookup`. This formatting migration does not force one candidate policy on every scenario.

## Runner parallelism

By default every selected inference method runs in one runner process that all sessions
share. A method can opt in to more independent processes; each holds its own model copy,
so memory grows with every worker, and nothing scales automatically:

```yaml
runtime:
  inference:
    methods:
      alphaavatar.voice.vad.silero:
        workers: 2  # 1-8
```

- Only runners that declare themselves replicable accept `workers` above 1: Silero VAD
  (`alphaavatar.voice.vad.silero`) and Smart Turn v3
  (`alphaavatar.router.turn_taking.smart_turn_v3`). Vector stores, MCP, semantic
  addressing, speaker and face runners stay at one worker.
- `max_pending` bounds requests per method, waiting and executing together;
  `queue_timeout` and `request_timeout` bound the wait for a worker and one execution;
  `client_timeout` bounds a session's local wait, connect and send. Restarts follow
  `restart_limit` within `restart_window_seconds`.
- A misspelled, unselected or non-replicable entry is rejected when the file loads;
  `alphaavatar config check` shows the effective workers. On the command line use the
  mapping form, since dots in a path would split the method name:
  `'runtime.inference.methods={alphaavatar.voice.vad.silero: {workers: 2}}'`.
- Session capacity stays `host.processes.capacity`; it is independent of runner workers.

## Scope

| Configuration | Scope |
| --- | --- |
| `mm/pipeline_openai_tools.yaml` | Multimodal input and configured tool plugins |
| `roles/demo.yaml` | Multimodal assistant demo with four context frames |
| `voice/pipeline_openai_tools_minimal.yaml` | Voice tools; no environment/face/video processing or Tavily |
| `voice/pipeline_openai_airi.yaml` | Hiyori-style voice persona using OpenAI TTS; no animated character |
| `voice/pipeline_voiceai_airi.yaml` | Hiyori-style voice persona using Voice.ai TTS; no animated character |

AIRI-style examples explicitly set `character.plugin: null`. Their names describe
the retained persona, not support for the old animated AIRI/AgentSession transport.
Native Host now supports the native Character lifecycle when explicitly configured.
These examples do not enable it automatically. A trusted frontend must be served
separately; follow [Character setup](../avatar-plugins/perception/avatar-plugins-character/README.md).

## Tool authorization and external services

Enabled plugins grant their capabilities to each Run. With `tool_policies: {}` they
run without a second approval: the Loop's `approval_required` defaults to `false`.
An exact capability policy can deny one with `enabled: false` or require
`approval_required: true`; the native Host supplies no authorizer, so such a
capability is not offered to the model. Enable only trusted tools: their operations
can spend provider credits or change data. Do not mark an aggregate MCP capability
read-only merely because one server is a documentation server.

Enabled providers, embeddings, MCP servers and inference runners need their
corresponding dependencies, credentials, network access and model assets.
The multimodal/demo configurations also retain Google environment extraction and
Tavily research; the voice-minimal example does not require those two services.
The OpenAI and Voice.ai TTS selections use native streaming PCM providers with fixed
sample rates. Character has a native lifecycle, but real renderer/RTC validation is
still required.
