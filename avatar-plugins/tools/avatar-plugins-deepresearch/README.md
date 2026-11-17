# AlphaAvatar DeepResearch Plugin

A modular deep-research and content acquisition middleware for AlphaAvatar, providing unified access to **web search**, **deeper search**, and **content extraction**.

This plugin enables AlphaAvatar agents to perform **broad information gathering** and **exploratory research**, without coupling agent logic to any specific search engine, crawler, or research provider. Multi-step investigation comes from the Loop composing its operations; each call is one request.

DeepResearch focuses on **acquiring and structuring external knowledge**.
Indexing is left to downstream tools such as the **RAG plugin**, which can index the PDFs `download` saves within the same session.

---

## Features

* **Unified Research Interface**
  Abstracts search, browsing, and content extraction behind a single, agent-friendly API.

* **Broad & Exploratory Research**
  Designed for unfamiliar, complex, or open-ended topics that require multiple sources.

* **Composable Operations**
  The Loop composes the operations into iterative workflows such as *search → read → refine → compare → synthesize*.

* **Source-aware Outputs**
  Returns structured results including titles, URLs, snippets, and extracted content.

* **Downstream-ready Artifacts**
  Produces Markdown text for summarization or analysis, and PDF files on the Host that RAG can index.

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
  Perform a lightweight web search for quick discovery: one basic-depth Tavily search, five results.
  Use this when fast, broad results are needed with minimal reasoning.

* **research**
  Perform one deeper web search: advanced-depth Tavily search, five results.
  Use this when the question needs more thorough sources; decomposition and further searching come from calling the operations again.

* **scrape**
  Given up to 20 absolute HTTP(S) URLs, fetch and extract the main page contents, then merge them into a single Markdown text in the tool result (e.g., for summarization).

* **download**
  Given up to 20 absolute HTTP(S) URLs, render the pages into PDF files in the session's `artifacts/deepresearch/tavily/` directory, returning their paths for downstream tools (e.g., RAG indexing in the same session).

---

## Typical Workflow

1. **Discover information** using `search` or `research`
2. **Acquire content** using `scrape` or `download`
3. **Pass outputs downstream**

   * Summarize or analyze directly
   * Or hand saved PDFs to the RAG plugin for indexing in the same session

---

## Installation

```bash
pip install alpha-avatar-plugins-deepresearch
```

The plugin is enabled unless `tools.deepresearch.plugin: null`. It reads the Tavily key from
`TAVILY_API_KEY` and fails at startup without it. `tools.deepresearch.init_config.timeout`
(default 30 s) bounds each Tavily request. Saving pages as PDF uses WeasyPrint, which needs the
system's Pango library.

---

## Supported DeepResearch Frameworks

### Default: **Tavily**

[Official Website](https://tavily.com)

Tavily is a search and research API designed for LLM and agent workflows, emphasizing **relevance**, **freshness**, and **machine-readable outputs**, making it well-suited for autonomous research agents.

---

Additional DeepResearch backends can be integrated in the future without changing agent logic.
