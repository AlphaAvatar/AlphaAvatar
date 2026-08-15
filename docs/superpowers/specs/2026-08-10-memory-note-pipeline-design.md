# Memory：note 级对话记忆与可配置维护操作（v0.6.7）

- 日期：2026-08-10
- 状态：已实现，对应 PR 分支 `memory/note-pipeline`
- 基线：`main` @ `f006d17`（v0.6.6，时间对齐多模态运行时）
- 依据论文：*Does Memory Need Graphs? A Unified Framework and Empirical Analysis for Long-Term Dialog Memory*（ACL 2026），参考实现 [UnifiedMem](https://github.com/AvatarMemory/UnifiedMem)
- 前身：`docs/superpowers/specs/2026-08-09-memory-flat-pipeline-design.md`（基于旧 main，范围更大）

> 本文是上述前身文档裁剪到实际发布范围后的版本。差异见 §10。

---

## 1. 背景与依据

### 1.1 论文的可落地结论

论文把记忆系统抽象为六元组 `⟨K, V, Q, I, R, A⟩`，分四阶段：Extraction / Indexing / Retrieval / Answering。与本次相关的实验结论：

| # | 结论 | 关键数据 |
|---|---|---|
| 1 | Key 应包含派生信息 S/F/K（摘要 / 事实陈述 / 关键词），且 merge-by-value 合成单一向量 | HaluMem（V=Key）：`S,F,K` → `[S,F,K]`，QA-C **0.2815 → 0.4785** |
| 2 | Add/Update/Noop 维护操作有效（Delete 不必要） | HaluMem：Mem-R **0.7332 → 0.8069**，QA-C **0.4785 → 0.5861** |

补充结论：在 **V=Key** 设定下 flat 稳定优于 graph（LME-S 0.570 vs 0.518）。AlphaAvatar 当前正是 V=Key。

论文脚注另指出：`separate` 组织在 LongMemEval 上差、但在 HaluMem 上最好——组织策略是场景相关的，不是单向结论。

### 1.2 改动前的现状（已逐项核实）

| 论文维度 | 现状 | 差距 |
|---|---|---|
| Key 表示 | 一条 `MemoryItem` = 一条原子事实。`value` 被嵌入；`node_mentions[].content` 作为独立 `graph_node` 行被嵌入；**`topic` 不进任何向量** | 缺 S；topic 缺席 K |
| 维护操作 | **纯 Add**。`MemoryState.add()` 按 `memory_id` 去重，而 `memory_id` 每次新建即新 UUID，等于不去重 | 缺 Noop/Update |
| K / V | `page_content` 一个字段同时是嵌入源与 prompt 展示文本 | 改善检索必然污染 prompt |

### 1.3 三个必须先澄清的事实

1. **抽取时机**：Conversation/Tool 抽取只在 `on_session_stop` 发生一次（`update()` 的唯一调用方），且抽取的是整段 session。**note 边界天然已存在。**
2. **`node_mentions` 实际是 keyword 而非图节点**：schema 无 relation 字段，prompt 产出的是 `tool:lancedb` / `concept:memory_graph` 这类锚点。KnowGraph/DescGraph 要求 entity 与 relation 联合抽取，结构上无法复用。
3. **`MemoryItem.updated` 与"记忆内容更新"完全无关**：它是持久化脏标记。命名与本次引入的 update 操作撞车，但**它是必要的**——见 §4.5。

---

## 2. 范围

### 2.1 本次做

- `MemoryNote` 数据模型（S/F/K），仅用于 CONVERSATION
- 阶段化、可配置的 pipeline 骨架
- Add / Noop / Update 维护操作
- K（`embedding_text`）与 V（`value`）分离
- 修复：向量检索使用 L2 平方而非余弦
- 修复：会话抽取产出经由截断结构落盘导致的记录丢失
- 首个自动化测试套件

### 2.2 本次不做

| 项 | 原因 |
|---|---|
| 图索引改造（删共现边、DescGraph、entity+relation 联合抽取、`(Score_e,Score_g)` 重排） | 独立一轮 |
| ENV 记忆改造 | 保持 item 形态，零改动 |
| Qdrant 后端 | 开发者已确认自 0.6.3 起暂停 |
| 检索侧分数聚合 / 重排 | 属 retrieval 阶段，与图索引改造一同处理 |
| raw session 持久化（`turns_dir`） | V=session 的前置条件，独立一轮 |
| `MemoryState` 拆分为 View + PendingWrites | 见 §4.5：main 已用另一套机制达成等价语义 |

---

## 3. 架构

### 3.1 阶段映射

| 论文阶段 | 改动前 | 本次 |
|---|---|---|
| I. Extraction | `MemoryDeltaExtractor` + prompts | 产出 note（S/F/K）；`node_mentions` 正名 keywords；可选 session gate |
| II. Indexing & Maintenance | **缺失** | **新增 add/noop/update** |
| III. Retrieval | `search_by_context` | 不改逻辑；修正距离度量 |
| IV. Answering | `memory_content` render | 不改 |

### 3.2 目录结构

```
alphaavatar/plugins/memory/
├── pipeline/
│   ├── config.py          # MemoryPipelineConfig
│   └── registry.py        # 按配置装配策略
└── maintenance/
    ├── base.py            # MaintenanceStrategy 协议 + MaintenanceResult + AddOnly
    ├── llm_judge.py       # 候选预筛 + 判决 + 改写
    └── prompts.py         # 判决 / 改写 prompt
```

不新建 `retrieval/` 包——flat 与 graph 检索的真实接缝不在插件侧（`_search_by_context` 内部同时搜 memory 行与 graph_node 行，且在 runner 进程里），未想清前不建包。

抽取相关代码保持原地修改，不做文件搬迁——搬迁会产生大量与逻辑无关的 diff。

### 3.3 配置

沿用现有 `init_config` 注入路径（与 `provider` 同一模式）。

```yaml
memory:
  init_config:
    pipeline:
      extraction:
        session_gate: false
        keywords: true
      key:
        organization: merge_by_value
        include_topic: true
      value:
        source: note
      maintenance:
        ops: [add, noop, update]     # [add] | [add,noop] | [add,noop,update]
        similarity_threshold: 0.82
        max_candidates_per_note: 5
```

`key.organization` 与 `value.source` 目前各只有一个可实现取值。保留这两个键是为了把论文的 K/V 两轴在代码里显式化，让下一轮成为"扩展枚举"而非"重构"。**未实现取值显式抛错，不做静默降级。**

`maintenance.ops` 是操作集合而非策略名，将来加 `delete` 等操作是扩枚举而非加分支。

---

## 4. 数据模型

### 4.1 `MemoryNote`

```python
class MemoryNote(MemoryItem):
    value: str = ""
    summary: str = ""
    facts: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _compose_value(self) -> "MemoryNote":
        if not self.value:
            self.value = render_note_value(self.summary, self.facts)
        return self
```

**继承而非独立**：`MemoryItem` 已有的字段对 note 语义完全一致，继承可避免重复声明与不一致风险，且 `MemoryState` 的桶类型 `list[MemoryItem]` 无需改动。维护阶段靠 `isinstance(record, MemoryNote)` 区分两者。

**`value` 由 validator 组合**而非直接等同 summary：保持 `value` 原本"完整人类可读记忆内容"的语义，使所有只读 `.value` 的调用方（渲染、markdown 备份）无需感知 note 的存在。validator 仅在 `value` 为空时组合，因此从 VDB 重建时存储文本不会被覆盖。

> **不可变性依赖**：若 facts 被原地修改则 value 会陈旧。maintenance 的 update 操作产出新的 `MemoryNote` 对象，因此不会出现陈旧。**此依赖必须在实现与 review 中被遵守。**

### 4.2 note 边界

**note 边界 = `(session_id, MemoryType.CONVERSATION)`，一个 session 产出一个 note。**

不能按"一个 session 一个 note"简单划分：一次 `update()` 对单个 session 产出两组归属不同的记忆（`memory_type` 与 `object_ids` 都不同），而 `object_ids` 是 flat 检索路径上唯一生效的过滤条件，混入一个 note 会使归属过滤失效。

### 4.3 各 memory_type 的形态

| memory_type | 形态 | 理由 |
|---|---|---|
| **CONVERSATION** | `MemoryNote` | 论文 note 概念针对用户对话记忆 |
| Avatar | `MemoryItem` | 定位是"跨用户跨 session 可复用的规则"，本质是规则库，session 级摘要无意义 |
| TOOLS | `MemoryItem` | prompt 已在 **episode** 层聚合，且 `search → read → save → index` 被明确要求拆为不同 item。session 级 note 会把互不相关的 episode 强行合并 |
| ENV | `MemoryItem` | 周期性抽取，一个 session 多批产出，无 session-note 概念 |

### 4.4 K / V 分离

| | 取自 | 用于 |
|---|---|---|
| **V** | `record.value` | `render_line()` → prompt；markdown 备份；`rebuild` |
| **K** | `record.embedding_text()` | `embed_documents` |

`flatten_records` 输出两个字段；`_save` 中 `memory_texts` 改取 `embedding_text`，行内仍存 `page_content`。

`render_line()` 与 `embedding_text()` 从 `MemoryState` 下沉到记录自身，以获得多态。

> **`doc_kind` 不区分 note 与 item。** 该列区分的是"记忆行 vs 图节点行"：`_search_rows` 以 `doc_kind="memory_item"` 过滤，若 note 写成 `"memory_note"` 则永远检索不到。note 身份由 `extra_data` 中的保留键 `_note` 承载。此法同样满足"不新增表列"。

### 4.5 持久化：沿用 main 的机制，不引入新结构

前身文档提出把 `MemoryState` 拆成 `MemoryView` + `PendingWrites`。**本次不这么做**，因为 v0.6.6 已用另一套机制达成等价语义：

```python
async def _persist_memory_items(self, items, *, timeout) -> bool:
    async with self._save_lock:
        selected = [item for item in items if item.updated]
        ...
        if not await self._save_to_vdb(...):
            return False                                    # 失败：不清标记，可重试
        self.memory_state.mark_saved({i.memory_id for i in selected})
        return True
```

- `updated` **是必要的**，不是冗余：它承载失败重试语义（写盘失败的记录保留标记，下次 save 再试）
- `_save_lock` 提供并发保存保护，前身方案没有
- markdown 与 graph 写盘经 `asyncio.to_thread` 并发，前身方案是顺序阻塞

因此本次保留 `MemoryItem.updated` 与 `mark_saved()`。新建与改写的 note 必须显式设 `updated=True`，否则会被静默过滤、永不落盘。

---

## 5. Extraction 阶段

### 5.1 可配置性 = prompt 片段组合 + 输出 schema 组合

不引入策略类。`keywords` 与 `session_gate` 是同一机制的两个实例：**加一段 prompt 片段 + 给输出 schema 加/改一个字段**。

prompt 由片段拼装：`[基础指令] + [session_gate?] + [keywords?]`。片段不得含字面花括号——`ChatPromptTemplate` 会当占位符。

### 5.2 session gate

以 prompt 片段实现，**不做独立 LLM 调用**。独立 gate 意味着每个 session 多一次往返；抽取 prompt 本身很大，若多数 session 值得抽取，为少数无价值 session 省一次调用却给所有 session 加一次往返，不划算。

### 5.3 输出 schema

conversation 路径**新增独立的 delta 类型**（`ConversationDelta` / `NotePatch`），而非改变现有字段含义。`MemoryDelta` 与 `EnvMemoryDelta` 保持不变，继续服务 tool 与 ENV 路径。三条抽取路径各有明确输出类型。

### 5.4 `node_mentions` 正名为 `keywords`

现有 `GraphNodeMention` 被同时当作图节点与关键词使用，且无 relation 字段。本次在 conversation 路径上正名为 note 级 `keywords`，服务 flat 检索。图节点所需的 entity + relation 联合抽取由图索引改造另行新增。

Avatar / TOOLS / ENV 路径的 `node_mentions` 保持原样。

---

## 6. Maintenance 阶段

### 6.1 数据流

```
新 note → embedding_text → VDB 批量近邻召回 → 相似度 ≥ τ 者进候选
                                                    ↓
                                        批量结构化 LLM 判决
                                                    ↓
                    add → 新 note ／ noop → 丢弃 ／ update → 改写目标 note
```

未产生候选的记录直接 Add，不进 LLM。开销与真实重复率成正比。

**不实现 Delete**（论文结论：旧记忆仍可能有用，如用户提及过往职业）。

### 6.2 正确性规则（`apply_verdicts`，纯函数）

- update 保留目标的原 `memory_id` —— 这是 VDB `delete by id + reinsert` 构成 upsert 的机制基础；原 timestamp 也保留，因为它记录事实被观察到的时间
- update 指向未被列为候选的 id → 回退为 add，防止幻觉 id 覆写任意记忆
- update 的改写结果为空 → 回退为 add，丢弃会导致记忆彻底丢失
- 缺失判决 → 默认 add，使 provider 的空响应降级为 add-only 而非丢数据

**只有 note 可被 update**；老的 plain item 最多触发 noop，避免 item→note 的形态转换。

### 6.3 距离度量（已实测确认）

`similarity_threshold` 只有定义在余弦相似度上才可解释。实测 lancedb 0.25.3：

| query=[1,0,0] | a=[1,0,0] | c=[1,1,0] | d=[2,0,0] | b=[0,1,0] |
|---|---|---|---|---|
| **默认 metric（实测）** | 0.000000 | 1.000000 | 1.000000 | 2.000000 |
| L2 平方（参考） | 0 | 1 | 1 | 2 |
| 余弦距离 `1-cos`（参考） | 0 | 0.293 | 0 | 1 |

默认为 L2 平方距离。所有 `table.search()` 显式 `.metric("cosine")`，相似度取 `1 - _distance`。不依赖"嵌入恰好归一化"——本项目支持的嵌入 provider 仅 OpenAI（归一化）与 Google/Gemini（不保证）。

---

## 7. 修复的缺陷

### 7.1 会话抽取产出经由截断结构落盘

`maximum_memory_num` 的配置描述为 `"The maximum number of memory items to use"`，原意是**渲染上限**。但 `update()` 把产出写进该结构、`save()` 再从中读取，使其意外成为每个 session 的**存储上限**（默认 10）。

v0.6.6 已用"ENV 每批即时落盘"修掉 ENV 一侧。本次让会话抽取同样直接持久化自己产出的完整列表，四条路径行为一致，`MemoryState` 回归纯视图。

**TOOLS 暴露面最大**——工具记忆按 episode 记录，重工具使用的 session 很容易超过默认上限 10。note 化之后 CONVERSATION 每 session 只产出 1 条，风险大幅下降。

### 7.2 语义检索使用 L2 平方距离

见 §6.3。对未归一化向量，**向量模长会参与排序**——而模长在语义检索中不应有意义。

### 7.3 `topic` 从不进入检索

`topic` 声明用途为 `"for retrieval and grouping"`，实际既不进嵌入也不做过滤。本次经 `key.include_topic` 纳入 `embedding_text()`。

### 7.4 仅记录、本次不修

| 缺陷 | 位置 |
|---|---|
| avatar 级共享的 graph JSONL 为无锁全量 read-modify-write，多 session 并发结束时后写者静默覆盖先写者 | `graph_store.py` / `graph_alias.py` |
| `search_by_context` 合并无分数聚合（插入顺序截断），graph 命中常被整段截掉 | `lancedb_runner.py` |
| `_get_memory_items_by_ids` / `_find_memory_ids_by_node_keys` 全表 `to_list()` | `lancedb_runner.py` |
| `GraphLookup` 每次调用全量重读 4 个 JSONL | `memory_runtime.py` |
| Qdrant 后端与 LanceDB 契约漂移 | `qdrant_runner.py` |
| `MemoryGraphNode.embedding` 字段全仓库无写入方 | `graph.py` |
| `cache.add_object_ids` 只增不减，检索过滤范围单调变宽 | `cache.py` |

---

## 8. 兼容与迁移

- 存量 CONVERSATION 记忆为 item 形态（无 `_note` 载荷）
- `rebuild` 按 `extra_data["_note"]` 是否存在分派构造；老行照常可读、可召回、可渲染
- note 的 S/F/K **序列化进现有 metadata JSON 列，不新增表列**——`_ensure_collection` 以"插入占位行再删除"固化 schema 且列名硬编码，走 metadata 可完全避开表结构迁移
- **不提供数据迁移脚本**

---

## 9. 测试

仓库此前配了 pytest 但零测试文件。本次建立测试根，覆盖**可能真会坏的逻辑**：

| 测试对象 | 要点 |
|---|---|
| `render_note_value` / `render_line` | 组合结果；无 facts 分支；尾随空白剥离 |
| `embedding_text` | S/F/K 合并；`include_topic` 开关 |
| note 序列化往返 | S/F/K 保真；`_note` 载荷不泄漏进 `extra_data` |
| 老行重建 | 无 `_note` 载荷时构造为 plain `MemoryItem` |
| 维护判决映射 | update 保留原 id；幻觉 id 回退 add；空改写回退 add；缺失判决默认 add |
| 候选预筛 | 阈值与截断 |
| pipeline 配置 | ops 约束；未实现取值抛错 |
| `MemoryState` 截断 | 钉住"这是渲染视图"这一危险点 |

抽取 prompt 与 provider 管道**刻意不做单测**——在那里 mock provider 只会断言 mock 而非行为。

---

## 10. 与前身文档的差异

| 项 | 前身（2026-08-09） | 本文 |
|---|---|---|
| 基线 | 旧 main `d5aa346` | main `f006d17`（v0.6.6） |
| `MemoryState` 拆分 | 拆为 View + PendingWrites | **不拆**，沿用 v0.6.6 的 `_persist_memory_items` |
| `MemoryItem.updated` | 删除（当时 `mark_saved` 零调用方） | **保留**，v0.6.6 已接上，承载失败重试语义 |
| 数据丢失修复 | 靠不截断的待写队列 | 靠直接持久化抽取产出，与 v0.6.6 的 ENV 做法一致 |
| `doc_kind` | 计划用 `"memory_note"` | 修正为仍用 `"memory_item"`（否则检索不到） |
| `base_trace_metadata` | 实例方法 | `@staticmethod`（跟随 v0.6.6） |
| 版本号 | v0.6.6 | v0.6.7（v0.6.6 已被占用） |

---

## 11. TODO：维护阶段的候选来源做成可配置

**决定（2026-08-15）**：维护阶段的候选记忆来源做成两种，可配置切换，**两种实现都保留**。

| 来源 | 说明 | 成本 |
|---|---|---|
| `query_recall`（新增） | 复用 session 内每轮 `search_by_context` 累积的召回集 | 零额外 RPC |
| `note_lookup`（现状） | 用 note 的 `embedding_text` 单独查一次 | 一次 RPC |

**`query_recall` 的实现约束**：必须**单独累积一份完整召回记录**，不能读 `MemoryState`——视图有 `maximum_memory_num` 上限（示例配置为 28，而 `recall_num=6`，长会话下留存率很低），且按时间戳保留最新，旧记忆优先被挤掉，而那恰恰是最可能需要 update 的部分。

**已知的残余风险**：检索窗口是 `chat_context[-search_context:]` 的原始对话文本，note 的 `embedding_text` 是 summary + facts + keywords 的抽象形态。两者在向量空间中位置不同，ANN 近邻集不保证互相覆盖——summary 层尤其没有任何窗口的字面对应物。这是二阶效应，但需要实测确认。

**验证方法**：在真实 session 上同时记录 A（窗口召回全集去重）与 B（note 直查结果），算差集 `B \ A`。稳定接近空则 `query_recall` 可作默认；否则保留 `note_lookup` 或两者取并集。该测量顺带产出 `recall_num` 是否够用的数据。

---

## 12. 下一轮（图索引改造）预览

不属本次范围，此处仅记录已确认的方向：

1. 新增 entity + relation **联合抽取**（GraphRAG 式），不复用 keywords
2. 删除 `graph_builder.py` 的全对共现边（论文：SimGraph 劣于 flat）
3. `graph_store._merge_node_stub` 的 `if not old.get("content")` 改为描述累积——有界列表拼接，超阈值时才 LLM 压缩
4. LanceDB `graph_node` 行由"每次出现一行"改为"每个 `node_key` 一行"
5. `_search_by_context` 合并改为 `(Score_e, Score_g)` 排序
6. 届时才决定 retrieval 策略置于插件侧（多次 RPC，热路径有超时）还是 runner 侧（单次 RPC，策略代码入驻 runner）
