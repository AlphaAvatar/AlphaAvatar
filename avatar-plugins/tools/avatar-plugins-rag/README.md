# AlphaAvatar RAG Plugin

[中文](README-zh.md)

A Retrieval-Augmented Generation (RAG) tool for AlphaAvatar, enabling agents to **index**, **search**, and **ground answers** on documents stored on the Host.

The index belongs to the session: it lives in the session's own `artifacts/rag/rag_anything/` directory, so each new session starts with an empty one.

The default backend is **RAGAnything**, but the plugin is designed to support multiple RAG frameworks in a pluggable way.

---

## Features

* **Session Knowledge Indexing**
  Index local documents into a searchable index: a file of a format RAG-Anything parses (PDF, Office, images, text), or a directory's `.pdf`, `.docx` and `.pptx` files, recursively.

* **Grounded Answer Generation**
  Retrieve relevant chunks and generate answers grounded in the indexed documents rather than model-only knowledge.

* **Unified RAG Interface**
  Abstracts indexing and querying behind a clean, agent-friendly API, independent of the underlying RAG engine.

* **Integration with DeepResearch**
  PDFs that DeepResearch `download` saves on the Host can be indexed in the same session.

---

## When to Use RAG

### Use **indexing** when:

* The user has authorized storing the documents, e.g. asks to **save**, **store** or **archive** them
  (e.g. “保存一下”, “做个资料库”); a lookup request alone does not authorize indexing

### Use **query** when:

* The user asks questions about content indexed in this session
* Answers must be grounded in the user's documents

---

## Functionality

It exposes **two core operations (op)** that can be composed into an agent workflow:

* **indexing**
  Index the Host-local files or directories `file_paths_or_dir` names. URLs and uploads are not accepted;
  a path that is missing or is not a regular file or directory is skipped and reported.

* **query**
  Retrieve relevant chunks from the session's index for `query` and generate a grounded answer.

`data_source` accepts only `all`; named corpora are not implemented.

---

## Typical Workflow

1. **Acquire content**

   * Local file paths are provided
   * PDFs are downloaded via DeepResearch

2. **Decide persistence intent**

   * Explicit user authorization → index directly
   * Ambiguous intent → ask a clarification question

3. **Index content**

   * Call `indexing` to build or extend the session's index

4. **Retrieve & answer**

   * Call `query` to retrieve relevant chunks
   * Generate grounded, source-aware answers

---

## Configuration

Indexing and queries send document content to an OpenAI-compatible service, with the key
from `OPENAI_API_KEY` and the API root from `OPENAI_BASE_URL` (OpenAI's when unset).
Without the key, unset, empty or blank, the first query or indexing fails and names it,
loading nothing.
This version uses `gpt-4o-mini` for text, `gpt-4o` for images and `text-embedding-3-large`
for embeddings.

| `tools.rag.init_config` | Default | Meaning |
| --- | --- | --- |
| `doc_parser` | `mineru` | `mineru` or `docling`; `docling` is used instead when no GPU is available |
| `openai_base_url` | `OPENAI_BASE_URL` | The API root, over the variable |

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
