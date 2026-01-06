# DeepResearch Plugin for AlphaAvatar

A modular deep-research middleware for AlphaAvatar, providing unified access to web search, real-time information retrieval, and multi-step research workflows.

This plugin enables AlphaAvatar agents to perform **fact-finding**, **evidence-backed reasoning**, and **long-horizon research tasks** without coupling agent logic to any specific search engine or web crawling implementation.

## Features

* **Unified Research Interface:** Abstracts web search, browsing, and content extraction behind a single, agent-friendly API.
* **Real-time Web Access:** Fetches up-to-date information beyond the model’s static knowledge cutoff.
* **Multi-step Research Support:** Designed for iterative research loops such as *search → read → refine → synthesize*.
* **Source-aware Results:** Returns structured results with titles, URLs, snippets, and raw content to support citation and grounding.
* **Pluggable Backends:** Easily switch between different research/search providers without changing agent logic.

---

## Installation

```bash
pip install alpha-avatar-plugins-deepresearch
```

---

## Supported DeepResearch Frameworks

### Default: **Tavily**

[Official Website](https://tavily.com)

Tavily is a search and research API purpose-built for LLM and agent workflows. It emphasizes **relevance**, **freshness**, and **machine-readable outputs**, making it well-suited for autonomous research agents.
