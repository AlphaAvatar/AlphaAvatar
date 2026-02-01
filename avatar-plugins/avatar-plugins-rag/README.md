# RAG Plugin for AlphaAvatar

A modular Retrieval-Augmented Generation (RAG) middleware for AlphaAvatar, enabling agents to **store**, **search**, and **ground answers** on user-provided or locally stored knowledge.

This plugin allows AlphaAvatar agents to work with **persistent knowledge bases** built from files, documents, and web content—decoupling agent reasoning from raw context windows and enabling long-term, reusable memory through retrieval.

The default backend is **RAGAnything**, but the plugin is designed to support multiple RAG frameworks in a pluggable way.

---

## Features

* **Persistent Knowledge Indexing**
  Ingest and store documents (PDF / Markdown / text / HTML / web snapshots) into a searchable local index.

* **Grounded Answer Generation**
  Retrieve relevant chunks and generate answers grounded in explicit sources rather than model-only knowledge.

* **Unified RAG Interface**
  Abstracts indexing and querying behind a clean, agent-friendly API, independent of the underlying RAG engine.

* **Incremental & Reusable Memory**
  Indexes can be extended, refreshed, and reused across conversations and sessions.

* **Seamless Integration with DeepResearch**
  Designed to work naturally with DeepResearch outputs (scraped pages, downloaded PDFs) for building long-term knowledge bases.

---

## Functionality

It exposes **two core operations (op)** that can be composed into an agent workflow:

* **indexing**
  Persist files, documents, or web content into a searchable local index.
  Use this when the content should be saved for future retrieval.

* **query**
  Retrieve relevant chunks from an existing index and generate grounded answers.
  Use this when answering questions based on previously indexed content.

---

## When to Use RAG

### Use **indexing()** when:

* The user explicitly asks to **save**, **store**, **remember**, or **archive** content
  (e.g. “保存一下”, “留着以后查”, “做个资料库”)
* The user provides files or URLs and implies **future reuse**
* Multiple documents are downloaded or collected (e.g. via DeepResearch)
* The same or similar documents are referenced repeatedly across turns

### Use **query()** when:

* The user asks questions about previously indexed content
* Answers must be grounded in user-owned data
* Searching across a growing local knowledge base is required

---

## Indexing vs Temporary Context

Not all content needs to be indexed.

When the user requests content but **indexing intent is unclear**, the agent SHOULD ask a clarifying question, such as:

> “Do you want me to build an index for this so you can search it later?”

* If the user confirms → call `indexing()`
* If not → treat the content as **temporary context only**

This distinction helps avoid unnecessary storage while preserving long-term memory when it matters.

---

## Typical Workflow

1. **Acquire content**

   * User uploads files
   * Local file paths are provided
   * Web pages are scraped or downloaded via DeepResearch

2. **Decide persistence intent**

   * Explicit user intent → index directly
   * Ambiguous intent → ask a clarification question

3. **Index content**

   * Call `indexing()` to build or update the knowledge base

4. **Retrieve & answer**

   * Call `query()` to retrieve relevant chunks
   * Generate grounded, source-aware answers

---

## Installation

```bash
pip install alpha-avatar-plugins-rag
```

---

## Supported RAG Frameworks

### Default: **RAG-Anything**

[Github Website](https://github.com/HKUDS/RAG-Anything)

RAGAnything is a flexible RAG framework optimized for:

* Heterogeneous document formats
* Incremental indexing
* Local-first storage and retrieval
* Agent-oriented workflows

It provides the default indexing and querying backend for the AlphaAvatar RAG plugin.

---

Additional RAG backends can be integrated in the future without changing agent logic.
