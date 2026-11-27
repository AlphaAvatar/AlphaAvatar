# AlphaAvatar DeepResearch 插件

[English](README.md)

面向 AlphaAvatar 的模块化深度研究与内容获取中间件，统一提供**网页搜索**、**深度搜索**和**内容提取**。

本插件让 AlphaAvatar agent 能够进行**广泛的信息收集**和**探索性研究**，而不必把 agent 逻辑耦合到任何特定的搜索引擎、爬虫或研究服务提供方。多步调查来自 Loop 对其操作的组合；每次调用是一个请求。

DeepResearch 专注于**获取并结构化外部知识**。索引留给下游工具，例如 **RAG 插件**，它可以在同一会话中为 `download` 保存的 PDF 建立索引。

---

## 功能特性

* **统一的研究接口**
  把搜索、浏览和内容提取抽象到一个统一的、对 agent 友好的 API 之后。

* **广泛且探索性的研究**
  为需要多个来源的陌生、复杂或开放式主题设计。

* **可组合的操作**
  Loop 把这些操作组合成迭代式工作流，例如*搜索 → 阅读 → 细化 → 比较 → 综合*。

* **标明来源的输出**
  返回结构化结果，包括标题、URL、摘要片段和提取的内容。

* **可供下游使用的产物**
  生成用于总结或分析的 Markdown 文本，以及 Host 上可供 RAG 建立索引的 PDF 文件。

---

## 何时使用 DeepResearch

当任务涉及以下一项或多项时，使用本插件：

* 从多个网页来源广泛收集信息
* 对陌生或复杂主题进行探索性研究
* 收集背景知识、趋势或比较
* 回答无法从单一来源解决的开放式问题
* 获取之后可能由 RAG 系统建立索引的外部内容

---

## 功能说明

它提供**四个核心操作（op）**，可组合成一条研究流水线：

* **search**
  执行轻量的网页搜索，用于快速发现：一次 basic 深度的 Tavily 搜索，五条结果。需要快速、广泛且推理最少的结果时使用。

* **research**
  执行一次更深入的网页搜索：advanced 深度的 Tavily 搜索，五条结果。当问题需要更充分的来源时使用；问题分解和进一步搜索来自再次调用这些操作。

* **scrape**
  给定最多 20 个绝对 HTTP(S) URL，抓取并提取页面主要内容，然后在工具结果中合并为一段 Markdown 文本（例如用于总结）。

* **download**
  给定最多 20 个绝对 HTTP(S) URL，把页面渲染为 PDF 文件，保存在会话的 `artifacts/deepresearch/tavily/` 目录中，并返回其路径供下游工具使用（例如在同一会话中由 RAG 建立索引）。

---

## 典型工作流

1. 使用 `search` 或 `research` **发现信息**
2. 使用 `scrape` 或 `download` **获取内容**
3. **把输出传给下游**

   * 直接总结或分析
   * 或把保存的 PDF 交给 RAG 插件，在同一会话中建立索引

---

## 安装

```bash
pip install alpha-avatar-plugins-deepresearch
```

除非设置 `tools.deepresearch.plugin: null`，否则本插件处于启用状态。它从 `TAVILY_API_KEY` 读取 Tavily 密钥，缺少该密钥时启动失败。`tools.deepresearch.init_config.timeout`（默认 30 s）限制每个 Tavily 请求的时长。把页面保存为 PDF 使用 WeasyPrint，它需要系统的 Pango 库。

---

## 支持的 DeepResearch 框架

### 默认：**Tavily**

[官方网站](https://tavily.com)

Tavily 是为 LLM 和 agent 工作流设计的搜索与研究 API，强调**相关性**、**时效性**和**机器可读的输出**，因此非常适合自主研究 agent。

---

将来可以集成更多 DeepResearch 后端，而无需修改 agent 逻辑。
