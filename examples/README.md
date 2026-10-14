# Native Engine examples

All five configurations use `loop.plugin: realtime` with the main model in
`loop.init_config.model`. `backend: openai` selects the native Responses backend;
plugin-local Memory/Persona providers retain their existing backend settings.
Model and voice identifiers are deployment choices, not guarantees of account access.
The main model identifier is preserved from the repository; change it to one available
on your configured provider before running. `temperature: null` avoids injecting a
sampling parameter into a model that may not accept it.

```bash
ENV_FILE=.env.dev alphaavatar dev examples/agent_configs/mm/pipeline_openai_tools.yaml
```

`defaults` contains YAML anchors only and is removed after aliases are resolved.
Unknown runtime sections, including the removed `llm` section, are rejected rather
than silently ignored. Native history is bounded by `context.init_config.history_*`.
Interruption is configured through `router.init_config.turn_taking.interruption`;
the unused SDK-era `voice.allow_interruptions` setting is removed and rejected.

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
Native Host continues to reject enabled SDK-dependent Character plugins.

## Tool authorization and external services

Tool registration is not approval. `tool_policies: {}` preserves the Loop's
`approval_required: true` default. The current LiveKit entrypoint does not provide
an approval UI or an Engine authorizer. Tool calls requiring approval will be
declined; model responses and voice delivery remain available. To permit a tool,
audit its exact capability ID and configure an explicit policy, or inject an
asynchronous authorizer when assembling the Engine. Do not mark an aggregate MCP
capability read-only merely because one server is a documentation server.

Enabled providers, embeddings, MCP servers and inference runners need their
corresponding dependencies, credentials, network access and model assets.
The multimodal/demo configurations also retain Google environment extraction and
Tavily research; the voice-minimal example does not require those two services.
SDK vendor TTS adapters and SDK worker hosting are still present. These files are
not a claim that all LiveKit Agents dependencies have been removed.
