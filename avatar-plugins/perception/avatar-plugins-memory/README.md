# 🧠 AlphaAvatar Memory Plugin

Memory provides persistent conversation, tool and environment memory through independently configured processors. Agent code exposes contracts; extraction prompts, storage, retrieval and finalization remain in this plugin.

## 🧩 Runtime and processors

```text
MemoryRuntime
├── retrieval       Passive Turn retrieval and callable retrieval capabilities.
├── conversation    Durable conversation extraction and consolidation.
├── tool            Useful tool-result memory.
├── environment     Perception-driven environment extraction.
└── MemoryStore     Vector/graph storage and persistence.
```

Each processor owns its configuration, provider gateway, prompts and lifecycle. MemoryRuntime owns contexts, consumer cursors and store orchestration. It does not require Engine to inject assistant messages directly.

## Canonical input

```text
TurnRuntime.events                -> committed user input / Turn context
OutputRuntime.records             -> canonical assistant and tool records
PerceptionRuntime                 -> environment observations
```

Memory is an independent required consumer of canonical records. It acknowledges locally accepted content; that acknowledgement is not proof that extraction or database persistence has finished. A failed required consumer is reported to the journal rather than silently permitting indefinite record loss.

Loop owns canonical assistant/tool publication. Memory does not consume raw provider streams, RTC transcript messages or private reasoning as a substitute for canonical records. Old-Run tool outcomes retain their original scope even after visible output permission has been revoked.

## Conversation configuration

This fragment belongs under `memory.init_config.conversation` in a complete Agent configuration:

```yaml
memory:
  plugin: default
  init_config:
    conversation:
      enabled: true
      pipeline:
        extraction:
          session_gate: false
          relations: false

        consolidation:
          mode: session_merge
          resolve_superseded_items: null
          item_ops: [add]
          candidate_source: union
          similarity_threshold: 0.4
          max_candidates_per_item: 5
          timeout: 30.0
```

ConversationPipelineConfig now contains only extraction and consolidation. Maintenance settings belong directly to consolidation; an old `pipeline.maintenance` mapping or an unknown nested key is rejected, not ignored or translated through a compatibility path.

`session_gate` asks extraction to skip content without durable value. Semantic relation extraction is not implemented and `relations: true` is rejected. Entity mentions and graph nodes do not imply full relation extraction.

| Consolidation mode | Behavior |
| --- | --- |
| `off` | Retain extracted atomic memory without consolidation. |
| `session_summary` | Consolidate the incoming session batch without historical candidates. |
| `session_merge` | Look for compatible existing consolidated memory and merge/insert as planned. |

Candidate source is independently selectable: `consolidated_lookup` searches storage, `query_recall` uses previously recalled candidates, and `union` combines them. Candidates remain isolated by memory type, scope and owner domain. Changing example formatting does not require every example to use the same candidate source.

Only the `add` item operation is supported and the list must contain it. Timeout must be finite and positive. The configured timeout is passed to the consolidation-plan request; it is not a guarantee for the duration of the entire storage/extraction workflow. Ordinary planning failures fall back to atomic memories; cancellation remains cancellation.

`resolve_superseded_items` controls prompt-time resolution; its null default follows the consolidation mode. It is not a tool-execution permission or a cross-owner merge switch.

## 🌍 Environment memory

The environment processor consumes bounded perception windows and associates extracted facts with evidence. Periodic and Turn-triggered work is separate from realtime media ingestion; heavy media payloads are not persisted as ordinary memory text.

Text alone does not establish environment evidence. Enabled audio support uses suitable audio observations/segments within the processor's capture contract, not arbitrary raw buffers placed in record metadata. Visual sampling, audiovisual alignment and provider input adaptation remain separate from conversation consolidation.

## 🕸️ Storage and retrieval

Memory records retain text, kind, ownership, scope, context, provenance and graph-related metadata. Supported memory types include Avatar, Conversation, Tools and ENV. Raw SDK objects and media clients are not stored as memory records.

LanceDB and Qdrant adapters provide vector storage. Retrieval owns text/graph lookup and identity-related resolution rather than adding concrete search methods to MemoryBase. Avatar-owned memory and user-owned memory remain separate ownership domains, even when they can be recalled across episodes.

## Lifecycle

MemoryRuntime exposes `on_start()` / `on_stop()`. Store and processor initialization are owned before awaiting them so partial startup can be cleaned up. Processor `stop(finalize=...)` retains its business meaning; it is not replaced by a generic Core finalizer.

During normal shutdown, Engine settles Loop producers before Memory drains committed Turns and canonical records, finalizes processors and closes the store. Startup rollback uses non-finalizing cleanup. Closing is managed and idempotent; failures do not silently skip ordinary remaining cleanup.

## Installation and examples

```bash
pip install alpha-avatar-plugins-memory
```

Select the plugin and configure provider gateways in [complete examples](../../../examples/README.md). Memory/Persona structured gateways borrow the runtime's ProviderService; they do not have to use the same backend/model as the foreground Loop.
