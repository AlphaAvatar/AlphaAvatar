# AlphaAvatar RAG 插件

面向 AlphaAvatar 的检索增强生成（Retrieval-Augmented Generation，RAG）工具，让 agent 能够对存储在 Host 上的文档进行**索引**、**检索**，并**基于文档生成有依据的回答**。

索引属于会话：它位于会话自己的 `artifacts/rag/rag_anything/` 目录中，因此每个新会话都从一个空索引开始。

默认后端是 **RAGAnything**，但本插件的设计支持以可插拔方式接入多种 RAG 框架。

---

## 功能特性

* **会话知识索引**
  把本地文档索引为可检索的索引：RAG-Anything 能解析的格式的文件（PDF、Office、图片、文本），或一个目录中递归包含的 `.pdf`、`.docx` 和 `.pptx` 文件。

* **有依据的回答生成**
  检索相关分块，并基于已索引的文档而不是仅凭模型知识生成回答。

* **统一的 RAG 接口**
  把索引和查询抽象到一个简洁、对 agent 友好的 API 之后，与底层 RAG 引擎无关。

* **与 DeepResearch 集成**
  DeepResearch `download` 保存在 Host 上的 PDF 可以在同一会话中建立索引。

---

## 何时使用 RAG

### 在以下情况使用 **indexing**：

* 用户已授权存储这些文档，例如要求**保存**、**存储**或**归档**它们（例如“保存一下”、“做个资料库”）；仅有查找请求并不授权建立索引

### 在以下情况使用 **query**：

* 用户询问本会话中已索引的内容
* 回答必须基于用户的文档

---

## 功能说明

它提供**两个核心操作（op）**，可组合成 agent 工作流：

* **indexing**
  为 `file_paths_or_dir` 指定的 Host 本地文件或目录建立索引。不接受 URL 和上传；缺失的路径，或既不是普通文件也不是目录的路径，会被跳过并报告。

* **query**
  针对 `query` 从会话的索引中检索相关分块，并生成有依据的回答。

`data_source` 只接受 `all`；命名语料库尚未实现。

---

## 典型工作流

1. **获取内容**

   * 提供本地文件路径
   * 通过 DeepResearch 下载 PDF

2. **判断持久化意图**

   * 用户明确授权 → 直接建立索引
   * 意图不明确 → 提出澄清问题

3. **索引内容**

   * 调用 `indexing` 构建或扩展会话的索引

4. **检索并回答**

   * 调用 `query` 检索相关分块
   * 生成有依据、标明来源的回答

---

## 配置

索引和查询会把文档内容发送到一个兼容 OpenAI 的服务，密钥取自 `OPENAI_API_KEY`，API 根地址取自 `OPENAI_BASE_URL`（未设置时使用 OpenAI 的地址）。没有密钥时（未设置、为空或只含空白），第一次查询或索引会失败并指出该密钥，不加载任何内容。本版本文本使用 `gpt-4o-mini`，图片使用 `gpt-4o`，embedding 使用 `text-embedding-3-large`。

| `tools.rag.init_config` | 默认值 | 含义 |
| --- | --- | --- |
| `doc_parser` | `mineru` | `mineru` 或 `docling`；没有可用 GPU 时改用 `docling` |
| `openai_base_url` | `OPENAI_BASE_URL` | API 根地址，优先于该变量 |

---

## 安装

```bash
pip install alpha-avatar-plugins-rag
```

---

## 支持的 RAG 框架

### 默认：**RAG-Anything**

[Github 网站](https://github.com/HKUDS/RAG-Anything)

RAGAnything 是一个灵活的 RAG 框架，针对以下方面做了优化：

* 异构文档格式
* 增量索引
* 本地优先的存储与检索
* 面向 agent 的工作流

它为 AlphaAvatar RAG 插件提供默认的索引和查询后端。

---

将来可以集成更多 RAG 后端，而无需修改 agent 逻辑。
