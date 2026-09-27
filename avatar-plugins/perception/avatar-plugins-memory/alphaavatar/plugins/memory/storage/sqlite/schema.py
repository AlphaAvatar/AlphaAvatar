# Copyright 2026 AlphaAvatar project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
SQLite schema for AlphaAvatar's authoritative Memory store.

The store is intentionally split into a small set of tables with distinct
responsibilities:

    memory_records
        Current authoritative MemoryItem state.

    memory_refs
        Typed relationships from a memory to owners, participants, and
        original source evidence.

    memory_relations
        Memory-to-memory provenance and supersession relationships.

    memory_checkpoints
        Per-context, per-processor incremental processing progress.

    memory_commits
        Idempotency records for logical memory commits.

    memory_outbox
        Durable asynchronous work for derived indexes and exports.

The SQLite store is authoritative. Vector databases and Markdown exports are
derived representations and must never determine whether a memory commit
succeeded.


memory_records
==============

Stores the current authoritative revision of every MemoryItem.

Frequently queried fields such as scope, type, context, timestamps, and
revision are stored as dedicated columns for efficient filtering and indexing.
The complete MemoryItem is additionally stored in `payload_json`, which is the
canonical representation used to reconstruct the domain object.

A memory revision updates the existing row; this table is not an append-only
revision history.

Example:

memory_id   kind          memory_type   context_id   scope_key    revision   value
--------------------------------------------------------------------------------------------
mem_A       atomic        conversation  ctx_main     owner:*      1          "User likes Porsche"
mem_B       consolidated conversation  ctx_main     owner:*      2          "User prefers 911 GT3"

Conceptually:

    columns
        -> filtering / sorting / indexing

    payload_json
        -> complete MemoryItem reconstruction


memory_refs
===========

Stores typed references between a MemoryItem and external identities or
source evidence.

`ref_group` currently has three logical values:

    owner
        Whose memory domain owns this record.

    participant
        Who participated in the event represented by this memory.

    source
        Which original message, tool event, perception event, or other
        evidence produced this memory.

Ownership, participation, and source provenance are intentionally independent.
For example, an avatar participating in a conversation does not automatically
make the memory avatar-owned.

Example:

memory_id   ref_group     ref_key
-----------------------------------------------
mem_A       owner         user:licheng
mem_A       participant   user:licheng
mem_A       participant   avatar:alphaavatar
mem_A       source        message:msg_123

`payload_json` stores the complete typed reference while `ref_key` provides a
stable searchable key.


memory_relations
================

Stores relationships between MemoryItems.

The two primary relation kinds are:

    source
        The related memory contributed to the derivation of this memory.

    supersedes
        The related memory should be replaced by this memory during
        current-memory resolution.

Derivation and supersession are intentionally separate concepts.

For example, a summary may derive from several memories without replacing
them:

memory_id   relation_kind   related_memory_id
------------------------------------------------
mem_C       source          mem_A
mem_C       source          mem_B

A merged or corrected consolidated memory may both derive from and supersede
its source memories:

memory_id   relation_kind   related_memory_id
------------------------------------------------
mem_D       source          mem_A
mem_D       source          mem_B
mem_D       supersedes      mem_A
mem_D       supersedes      mem_B

This relation table makes reverse resolution possible without storing
`resolved_by_memory_id` inside every source MemoryItem.


memory_checkpoints
==================

Stores incremental processing progress independently for each Memory processor
and context.

Each processor advances its own sequence only after the corresponding
authoritative memory transaction succeeds.

Example:

context_id   processor       sequence
--------------------------------------
ctx_main     conversation    184
ctx_main     tool            51
ctx_main     environment     922

This allows ConversationMemoryProcessor, ToolMemoryProcessor, and
EnvironmentMemoryProcessor to progress independently.

The checkpoint is committed in the same transaction as memory records so the
system cannot reach either invalid state:

    checkpoint advanced, memory missing

or:

    memory committed, checkpoint not advanced

Checkpoint advancement uses compare-and-swap semantics:

    expected current sequence -> new sequence


memory_commits
==============

Stores completed logical commit identities for idempotency.

Realtime pipelines may retry work because of task cancellation, connection
failure, scheduler retry, or process recovery. The same logical batch must
therefore be safe to execute more than once without creating duplicate
memories.

Example:

idempotency_key                 context_id   processor       result
---------------------------------------------------------------------------
conversation:ctx_main:101:110   ctx_main     conversation    mem_A, mem_B
tool:ctx_main:51:52             ctx_main     tool            mem_C

When an already committed `idempotency_key` is submitted again, the store
returns the previous MemoryCommitResult instead of writing the batch again.

Conceptually:

    at-least-once execution
        +
    durable idempotency
        =
    exactly-once logical commit


memory_outbox
=============

Stores durable asynchronous work created by an authoritative Memory commit.

Each Memory revision normally creates derived work for targets such as:

    index
        Update the Qdrant/LanceDB retrieval index.

    export
        Update the human-readable Markdown export.

Example:

event_id   target    memory_id   revision
------------------------------------------
1          index     mem_A       1
2          export    mem_A       1
3          index     mem_B       2
4          export    mem_B       2

Outbox events are created in the same SQLite transaction as the authoritative
MemoryItem revision.

The realtime write path therefore ends after the SQLite WAL commit:

    extraction / consolidation
        -> memory_records
        -> memory_refs
        -> memory_relations
        -> memory_checkpoints
        -> memory_outbox
        -> COMMIT
        -> return

Derived work happens asynchronously afterwards:

    memory_outbox
        -> INDEX  -> embedding -> Qdrant / LanceDB
        -> EXPORT -> Markdown

`lease_owner` and `lease_until` allow multiple workers to consume outbox events
without processing the same event concurrently.

Example:

event_id   state        lease_owner   lease_until
--------------------------------------------------
1          processing   indexer-1     1789552030
2          pending      NULL          NULL

If a worker disappears, an expired lease makes the event claimable again.

This design keeps VDB/network/file I/O outside the authoritative SQLite
transaction and therefore keeps Memory commits short, durable, and suitable
for AlphaAvatar's low-latency asynchronous realtime pipeline.
"""

SCHEMA_VERSION = 3

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memory_records(
    memory_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    memory_type TEXT NOT NULL,

    episode_id TEXT NOT NULL,
    context_id TEXT NOT NULL,
    runtime_session_id TEXT,
    parent_context_id TEXT,
    task_id TEXT,

    scope_key TEXT NOT NULL,

    value TEXT NOT NULL,
    topic TEXT,

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_ts REAL NOT NULL,

    revision INTEGER NOT NULL CHECK(revision > 0),
    payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_memory_records_scope
ON memory_records(scope_key, memory_type, kind, updated_ts DESC);

CREATE INDEX IF NOT EXISTS ix_memory_records_context
ON memory_records(episode_id, context_id);

CREATE TABLE IF NOT EXISTS memory_refs(
    memory_id TEXT NOT NULL
        REFERENCES memory_records(memory_id) ON DELETE CASCADE,

    ref_group TEXT NOT NULL,
    ref_key TEXT NOT NULL,
    payload_json TEXT,

    PRIMARY KEY(memory_id, ref_group, ref_key)
);

CREATE INDEX IF NOT EXISTS ix_memory_refs_lookup
ON memory_refs(ref_group, ref_key, memory_id);

CREATE TABLE IF NOT EXISTS memory_relations(
    memory_id TEXT NOT NULL
        REFERENCES memory_records(memory_id) ON DELETE CASCADE,

    relation_kind TEXT NOT NULL,

    related_memory_id TEXT NOT NULL
        REFERENCES memory_records(memory_id) ON DELETE RESTRICT,

    PRIMARY KEY(memory_id, relation_kind, related_memory_id)
);

CREATE INDEX IF NOT EXISTS ix_memory_relations_related
ON memory_relations(relation_kind, related_memory_id, memory_id);

CREATE TABLE IF NOT EXISTS memory_checkpoints(
    context_id TEXT NOT NULL,
    processor TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK(sequence >= 0),
    updated_at REAL NOT NULL,

    PRIMARY KEY(context_id, processor)
);

CREATE TABLE IF NOT EXISTS memory_commits(
    idempotency_key TEXT PRIMARY KEY,
    request_hash TEXT NOT NULL,

    context_id TEXT NOT NULL,
    processor TEXT NOT NULL,

    result_json TEXT NOT NULL,
    committed_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_outbox(
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key TEXT NOT NULL UNIQUE,

    target TEXT NOT NULL,
    memory_id TEXT NOT NULL
        REFERENCES memory_records(memory_id) ON DELETE CASCADE,

    revision INTEGER NOT NULL,

    state TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at REAL NOT NULL,

    lease_owner TEXT,
    lease_until REAL,
    last_error TEXT
);

CREATE INDEX IF NOT EXISTS ix_memory_outbox_ready
ON memory_outbox(target, state, available_at, lease_until, event_id);
"""
