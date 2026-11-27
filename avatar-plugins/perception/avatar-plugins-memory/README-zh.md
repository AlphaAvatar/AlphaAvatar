# 🧠 AlphaAvatar Memory 插件

[English](README.md)

Memory 通过各自独立配置的处理器，提供持久的对话、工具和环境记忆。Agent 代码只暴露契约；提取 prompt、存储、检索和收尾都留在本插件中。

## 🧩 运行时与处理器

```text
MemoryRuntime
├── retrieval       Passive Turn retrieval and callable retrieval capabilities.
├── conversation    Durable conversation extraction and consolidation.
├── tool            Useful tool-result memory.
├── environment     Perception-driven environment extraction.
└── MemoryStore     SQLite records, with vector index and Markdown/graph exports.
```

每个处理器拥有自己的配置、Provider 网关、prompt 和生命周期。MemoryRuntime 拥有上下文、消费者游标和存储协调。它不要求 Engine 直接注入助手消息。

## 规范输入

```text
TurnRuntime.events                -> committed user input / Turn context
OutputRuntime.records             -> canonical assistant and tool records
PerceptionRuntime                 -> environment observations
```

Memory 是规范记录的一个独立的必需消费者。它确认已在本地接受的内容；这一确认不能证明提取或数据库持久化已经完成。必需消费者失败时会报告给 journal，而不是悄悄允许记录无限期丢失。

Loop 负责发布规范的助手／工具记录。Memory 不会用原始 Provider 流、RTC 转写消息或私有推理来替代规范记录。旧 Run 的工具结果即使在可见输出权限被撤销后，仍保留其原来的范围。

## 对话配置

在完整的 Agent 配置中，此片段位于 `memory.init_config.conversation` 下：

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

ConversationPipelineConfig 现在只包含 extraction 和 consolidation。维护设置直接属于 consolidation；旧的 `pipeline.maintenance` 映射或未知的嵌套键会被拒绝，既不会被忽略，也不会经兼容路径转换。

`session_gate` 让提取阶段跳过没有持久价值的内容。语义关系提取尚未实现，`relations: true` 会被拒绝。实体提及和图节点并不意味着完整的关系提取。

| 整合模式 | 行为 |
| --- | --- |
| `off` | 保留提取出的原子记忆，不做整合。 |
| `session_summary` | 整合传入的会话批次，不使用历史候选。 |
| `session_merge` | 查找兼容的已有整合记忆，并按计划合并／插入。 |

候选来源可以独立选择：`consolidated_lookup` 检索存储，`query_recall` 使用之前召回的候选，`union` 合并两者。候选仍按记忆类型、scope 和所有者域隔离。修改示例格式并不要求每个示例都使用相同的候选来源。

只支持 `add` 条目操作，且列表必须包含它。timeout 必须是有限的正数。配置的 timeout 会传给整合计划请求；它并不保证整个存储／提取流程的耗时。普通的规划失败会回退为原子记忆；取消仍然是取消。

`resolve_superseded_items` 控制 prompt 阶段的解析；其默认值 null 跟随整合模式。它不是工具执行权限，也不是跨所有者合并的开关。

## 🌍 环境记忆

环境处理器消费有界的感知窗口，并把提取出的事实与证据关联起来。周期性工作和由 Turn 触发的工作与实时媒体接收相互独立；大体积的媒体载荷不会作为普通记忆文本持久化。

仅有文本不能构成环境证据。启用音频支持时，使用的是处理器采集契约范围内合适的音频观测／片段，而不是放在记录元数据中的任意原始缓冲区。视觉采样、音视频对齐和 Provider 输入适配与对话整合相互独立。

## 🕸️ 存储与检索

Memory 记录保留文本、种类、所有权、scope、上下文、来源和图相关元数据。支持的记忆类型包括 Avatar、Conversation、Tools 和 ENV。原始 SDK 对象和媒体客户端不会作为记忆记录存储。

SQLite 记录是权威记录；outbox 为其投影提供数据：LanceDB 或 Qdrant 向量索引，以及 Markdown／图导出。一个向量索引只保存一个 embedding 模型的向量：创建它所用的模型记录在索引旁；记录为其他模型的索引，即使维度相同，也会在启动时被拒绝，对于启动时打开的 LanceDB 索引，`alphaavatar setup` 同样会拒绝，且索引中的内容都不做改动；如需单独的索引，给 `vdb_config.collection_name` 另起一个名字。密钥、存放密钥的变量或服务器地址都不属于模型。在开始记录模型之前创建的索引，只有在其向量（空索引也算）符合配置的维度时，才被视为配置的模型，而维度无法验证模型本身；维度不同的索引会被拒绝。共享同一索引的多个 Host 同时记录模型也是安全的：相同的模型在每个 Host 上都能打开它，两个不同的模型绝不会都打开它。检索负责文本／图查找和身份相关的解析，而不是在 MemoryBase 上添加具体的搜索方法。检索按记忆的类型和所有者读取记忆，从不按 scope 读取。Avatar 记忆通过 Avatar 读取，因此每个读取方都能读到。对话、工具和环境记忆只由其用户所有者读取，可在任何上下文中读取，即使 Avatar 也是其所有者之一。scope 决定导出目录，以及整合可以合并哪些记忆。环境记忆属于 Avatar 和会话的主参与者，即开启会话的人，无论此人是否出现在观测内容中。它的 scope 就是它的上下文。

## 生命周期

MemoryRuntime 暴露 `on_start()` / `on_stop()`。存储和处理器的初始化在 await 之前就已纳入所有权管理，因此部分完成的启动也能被清理。处理器的 `stop(finalize=...)` 保留其业务含义，不会被通用的 Core 收尾器替代。

正常关闭时，Engine 先让 Loop 生产者收尾，然后 Memory 排空已提交的 Turn 和规范记录、对处理器执行收尾并关闭存储。启动回滚使用不做收尾的清理。关闭过程受管理且幂等；失败不会悄悄跳过其余的常规清理。

## 安装与示例

```bash
pip install alpha-avatar-plugins-memory
```

在[完整示例](../../../examples/README.md)中选择插件并配置 Provider 网关。Memory／Persona 的结构化网关借用运行时的 ProviderService；它们不必与前台 Loop 使用相同的后端／模型。
