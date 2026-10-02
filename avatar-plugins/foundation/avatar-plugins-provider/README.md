# AlphaAvatar Provider Plugin

The public contract is `alphaavatar.agents.avatar.provider`. It owns task
configuration, model input, prompts, media, tool call/result records, structured
results, streaming types, and SDK-independent Gateway orchestration.

This package owns SDK-specific construction, input adaptation, output parsing,
and usage normalization. The implemented backend in this migration is
`langchain`; OpenAI, OpenRouter, Google, and Anthropic model access still uses the
existing LangChain integrations. No empty native-vendor backends are registered.

`ProviderTaskConfig.backend` selects an installed backend implementation.
`ProviderTaskConfig.provider` selects the model vendor or endpoint family inside
that backend. They are distinct fields.

## Loading

Install `alpha-avatar-plugins-provider[langchain]`. The `alphaavatar.provider`
entry-point group discovers backend modules. Loading the selected module
registers LLM and embedding factories through the existing AvatarModulePlugin
registry. Entry-point metadata is discovery, not a second model registry.

Package roots do not load SDK clients. Factory metadata is resolved once per
backend per process. Backend loading errors propagate instead of silently
falling back to another provider.

## Calls and ownership

Structured calls receive an AlphaAvatar ModelInput and a Pydantic schema. A
backend must return a validated ProviderModelResult, not an SDK Runnable or
message. The Gateway owns task-level tracing and never builds LangChain chains.

Business prompts and result schemas remain with their Memory/Persona
processors. ModelPrompt renders text templates and ModelInputSlot values without
converting observations, inventing perception events, or mutating input items.

LangChain SDK model construction retains the existing per-call behavior.
Shared Foundation Provider service, pooled client ownership, and managed trace
draining are not implemented by this boundary migration.

EmbeddingBase exposes asynchronous requests. WorkerEmbeddingBase additionally
supports the existing blocking embedding calls in isolated VDB inference
workers. These blocking methods are not realtime event-loop entrypoints. The
private LangChain embedding wrapper also satisfies LangChain's Embeddings type
for existing Qdrant integration.

## Multimodal and stream contracts

ModelMediaPart holds bytes or a URI plus media kind and MIME type. Constructing
it performs no I/O. ModelFunctionOutput uses `parts`, just like input messages;
its `text` property is only a projection and never replaces the full content.

Adapters reject unsupported parts instead of silently discarding them. Schema
representability does not imply support by every backend, model, or API mode.
The existing Gemini ENV adapter retains its temporal audiovisual encoding.
The default text task adapter does not accept media, tool, or control records.

ModelRequest carries model-facing tool definitions; it does not register or
execute tools. The existing runtime capability registry remains authoritative.

StreamingLLMBase defines a request-scoped async context manager. A successful
stream ends with ModelResponseCompleted; exceptions and cancellation propagate.
Exiting the context must close the request stream. Deltas are not complete tool
arguments, and a completed tool call still requires argument validation before
execution. Reasoning parts are separate from user-visible text.

The LangChain task backend does not advertise StreamingLLMBase. Native streaming
implementation, capability/tool execution integration, final Assistant output,
and LiveKit Agents removal remain separate work. Session/Episode semantics do
not change here.
