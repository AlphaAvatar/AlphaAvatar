# DeepResearch Plugin for AlphaAvatar

A modular deep-research and content acquisition middleware for AlphaAvatar, providing unified access to **web search**, **iterative research**, and **content extraction**.

This plugin enables AlphaAvatar agents to perform **broad information gathering**, **exploratory research**, and **multi-step investigation workflows**, without coupling agent logic to any specific search engine, crawler, or research provider.

DeepResearch focuses on **acquiring and structuring external knowledge**.
Persistent storage and long-term reuse are handled by downstream tools such as the **RAG plugin**.

---

## Features

* **Unified Research Interface**
  Abstracts search, browsing, and content extraction behind a single, agent-friendly API.

* **Broad & Exploratory Research**
  Designed for unfamiliar, complex, or open-ended topics that require multiple sources.

* **Multi-step Research Support**
  Supports iterative workflows such as *search → read → refine → compare → synthesize*.

* **Source-aware Outputs**
  Returns structured results including titles, URLs, snippets, and extracted content.

* **Downstream-ready Artifacts**
  Produces Markdown text and PDF files suitable for summarization, analysis, or indexing by RAG.

---

## When to Use DeepResearch

Use this plugin when the task involves one or more of the following:

* Broad information gathering from multiple web sources
* Exploratory research on unfamiliar or complex topics
* Collecting background knowledge, trends, or comparisons
* Answering open-ended questions that cannot be resolved from a single source
* Acquiring external content that may later be indexed by a RAG system

---

## Functionality

It exposes **four core operations (op)** that can be composed into a research pipeline:

* **search**
  Perform a lightweight web search for quick discovery.
  Use this when fast, broad results are needed with minimal reasoning.

* **research**
  Perform deep, multi-step research.
  Use this when the question requires decomposition, iterative searching, cross-source comparison, and reasoning.

* **scrape**
  Given a list of URLs, fetch and extract the main page contents, then merge them into a single Markdown text suitable for downstream processing (e.g., summarization or indexing).

* **download**
  Given a list of URLs, fetch pages and convert them into stored PDF artifacts, returning a list of file references for downstream tools or plugins (e.g., building a local RAG index).

---

## Typical Workflow

1. **Discover information** using `search` or `research`
2. **Acquire content** using `scrape` or `download`
3. **Pass outputs downstream**

   * Summarize or analyze directly
   * Or hand off to the RAG plugin for indexing and long-term retrieval

---

## Installation

```bash
pip install alpha-avatar-plugins-deepresearch
```

---

## Supported DeepResearch Frameworks

### Default: **Tavily**

[Official Website](https://tavily.com)

Tavily is a search and research API designed for LLM and agent workflows, emphasizing **relevance**, **freshness**, and **machine-readable outputs**, making it well-suited for autonomous research agents.

---

Additional DeepResearch backends can be integrated in the future without changing agent logic.
