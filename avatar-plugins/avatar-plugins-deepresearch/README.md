下面是**参考 Memory / Character 插件 README 风格**，并结合 **DeepResearch 实际职责**，为你补充完成的一份 **DeepResearch Plugin for AlphaAvatar** 的 README 草案。内容已默认 **DeepResearch 当前使用 Tavily API**，并把 Tavily 的能力结构化地融入插件设计中，保持与前两个插件在抽象层级与语气上的一致性。

---

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
