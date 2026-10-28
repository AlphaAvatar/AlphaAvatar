# AlphaAvatar 标识与关联约定

本文说明 v0.6.9 当前实现中的标识、唯一性范围和关联入口。人的关联统一使用 `device_id`、`entity_id`、`participant_id`、`user_id`；媒体、事件、执行和持久化记录仍保留各自必要的标识。相同字段名必须结合所属类型解释，不能把所有 `id` 或 `source_id` 当作同一种身份。

## 1. 设备、感知实体、会话参与者和用户

| 字段 | 含义与所有者 | 唯一性范围与生命周期 |
| --- | --- | --- |
| `device_id` | 应用接入端点的标识，由接入适配层提供。一个端点可以提供文字、麦克风、摄像头等输入，也可以作为渲染端点。 | 当前接入后端的命名空间，例如一个 LiveKit room。当前适配器使用 `participant.identity`；它不是硬件序列号，重连或重新附着时可以复用或更换。 |
| `entity_id` | 感知到的一个实体，例如同一摄像头画面中的某个人，或音频来源中持续跟踪的一名说话者。由感知输入或跟踪器提供。 | 必须连同 `PerceptionSourceRef` 使用，即 `(source_id, source_generation, entity_id)`；会话之间还需区分 `session_id`。实体跟踪有容量和过期边界，不能把编号相同当作跨来源或跨会话的同一个人。 |
| `participant_id` | 当前会话中的逻辑参与者，由 `SessionRuntime` 管理。它把来自不同媒体的已确认关联汇集到一个会话对象。 | 在一个 `SessionRuntime` 中唯一，默认生成 UUID。身份纠正不更换该 ID；它不等于接入端点、媒体实体或长期用户。 |
| `user_id` | 长期用户身份，指向用户 Persona、Identity、Memory 等数据。由应用声明或身份决策提供。 | 在当前应用用户数据命名空间中解释，可跨会话使用。`Participant.user_id` 是当前判断，可以为 `None`，也可以多次纠正。 |

`agent_device_id` 表示 Avatar 自身的接入端点，仍然属于 `device_id` 的同一种标识；它不等于 `avatar_id`。`SessionContext.device_id` 指当前用户端点，`CharacterConnection.device_id` 指该渲染连接的目标端点。字段所在对象决定角色，不要求这两者取相同值。`device_ids`、`excluded_device_ids` 是端点集合，不是新的 ID 类型。

`primary_participant_id` 只是主参与者的引用；`primary_user_id` 是从当前主参与者推导的值。`previous_user_id` 是身份事件中的历史引用，也不创建第二份当前身份。

实现入口：[Session 契约](../avatar-core/alphaavatar/core/session/schemas/__init__.py)、[SessionRuntime](../avatar-core/alphaavatar/core/session/runtime.py)、[感知引用](../avatar-core/alphaavatar/core/env/schemas/reference.py)、[SessionContext](../avatar-host/alphaavatar/host/sessions/schemas.py)、[CharacterConnection](../avatar-agents/alphaavatar/agents/character/base.py)。

### 映射存在哪里

| 关系 | 唯一维护位置 | 约束 |
| --- | --- | --- |
| `device_id → participant_id` | `ParticipantBindings._devices` | 表示明确提交者的端点关联；一个端点当前至多关联一个提交者，但这不限制该端点画面中的人数。 |
| `(PerceptionSourceRef, entity_id) → participant_id` | `ParticipantBindings._entities` | 每个来源实体独立关联；多个来源实体可以明确关联到同一个参与者。 |
| `participant_id → user_id` | `SessionRuntime.participants[participant_id].user_id` | 当前用户身份只有这一份。`ParticipantBindings` 不复制用户映射。 |
| `PerceptionSegmentRef → entity` | `ParticipantRuntime` 的有界片段状态 | 把声纹推理结果限定到具体音频片段；不新增人物 ID。 |
| `user_id → 读写许可` | 应用注入的 `UserDataAccess` | 独立于身份映射，分别检查读、写权限。 |

业务侧统一通过 [ParticipantRuntime](../avatar-agents/alphaavatar/agents/runtime/modules/participants/runtime.py) 操作：`join`、`get`、`bind_device`、`unbind_device`、`ensure_entity`、`bind_entity`、`release_entity`、`resolve`、`bind_user`、`can_read_user`、`can_write_user`、`user_path`。底层 [ParticipantBindings](../avatar-agents/alphaavatar/agents/runtime/modules/participants/binding.py) 只维护两张关联表，不承担识别策略、目录 I/O 或长期用户状态。

`resolve(device_id, endpoint=True)` 只用于明确的端点提交者；默认不使用端点关联。带实体或片段的解析优先遵循该证据：未知实体、冲突片段、过期来源或已淘汰的片段返回未知，不回退到设备用户或主参与者。缺少端点信息不妨碍保留感知观测，也不自动允许身份绑定。

### 同一输入端有多个人

假设同一手机端点 `phone-1` 的摄像头来源为 `camera-1`，世代为 `1`：

| 输入事实 | 关联结果 |
| --- | --- |
| 画面中的 `face-a` | `(camera-1, 1, face-a) → participant-a → user-a` |
| 同一画面中的 `face-b` | `(camera-1, 1, face-b) → participant-b → user-b` |
| 手机提交的一条明确属于账户持有者的文字 | 可通过端点关联 `phone-1 → participant-a` 解析提交者 |
| 麦克风中尚未确认的说话者 | 保持独立或未知，不能因为来自 `phone-1` 就归到 `participant-a` |

人脸实体和声纹实体只有在关联证据成立时，才通过 `bind_entity` 指向同一个 `participant_id`。同设备、相同 `user_id` 或相同局部 `entity_id` 都不自动合并参与者。若实体已关联另一参与者，应显式释放后重新关联，不能无声覆盖。

以下示例的 `participants` 是当前会话的 `ParticipantRuntime`，演示同一摄像头中两个人的独立身份判断：

```python
from alphaavatar.core.env.schemas import PerceptionEntityRef, PerceptionSourceRef
from alphaavatar.core.session import IdentityRequest, IdentitySource

source = PerceptionSourceRef("camera-1", 1)
person_a = participants.ensure_entity(source, PerceptionEntityRef("face-a"))
person_b = participants.ensure_entity(source, PerceptionEntityRef("face-b"))
participants.bind_user(IdentityRequest(
    participant_id=person_a.participant_id, user_id="user-a",
    source=IdentitySource.PERCEPTION, basis_sequence=person_a.identity_sequence,
))
participants.bind_user(IdentityRequest(
    participant_id=person_b.participant_id, user_id="user-b",
    source=IdentitySource.MODEL, basis_sequence=person_b.identity_sequence,
))
```

该示例不授予用户数据访问。`user_path(user_id, write=...)` 先检查应用许可，只返回类型化路径，不创建目录。

### 纠正、解绑和快照

`bind_user(IdentityRequest(...))` 支持声明、感知、Agent 和独立模型提交身份更正。默认策略不限制“只识别一次”，也不要求 Agent 的目标用户先经过感知提名。应用可以替换身份策略，但数据读写许可仍单独检查。

请求必须携带读取时的 `identity_sequence`，填入 `basis_sequence`；迟到结果会返回 `STALE`，调用方需重新获取参与者并判断是否重试。`user_id=None` 表示解绑，不恢复最初用户，也不生成临时长期用户 ID。若应用确实创建了访客账户，那是明确创建的用户，与尚未识别的感知参与者不同。

`Participant` 是不可变快照。改绑保留 `participant_id`，替换当前快照并递增身份版本。`TurnEntityRef` 中的 `participant_id`、`user_id`、`identity_sequence` 固定该 Turn 的身份事实；这些历史引用不能被后来的纠正悄悄重写，也不授予存储权限。Session 事件流有界，当前 Snapshot 不能替代已遗漏的全部持久化副作用。

## 2. 媒体来源、片段和观测

| 字段或引用 | 定义 | 使用范围 |
| --- | --- | --- |
| `PerceptionSourceRef.source_id` | 一路逻辑媒体或输入来源，由接入层/生产者提供，例如音轨、视频轨、文字来源。 | 当前 Perception 会话；同一端点可以有多个来源。不得仅按 `device_id` 合并。 |
| `source_generation` | 同一 `source_id` 的启用世代。 | 与 `source_id` 一起构成完整来源引用。重新启用递增；旧世代不能重新绑定当前参与者。它是版本号，不是另一种来源 ID。 |
| `PerceptionSegmentRef.segment_id` | 一段输入音频及其转录、取消等派生事实的关联标识。 | 必须连同完整 `source` 使用。VAD、STT 和 Router 使用同一片段链，不另造“识别后片段 ID”。 |
| `observation_id` | 一次 `EnvObservation` 的标识，默认 UUID。 | 区分音频、转录、图像、文字等具体观测；同一片段可以产生多个观测。 |
| `frame_id` | 一个具体视频帧的关联标识。 | 让帧、感知注释和相关证据指向同一画面。当前 LiveKit 实现从会话、轨道、世代、帧序号和时间构造。 |
| `annotation_id` | 一条 `EnvAnnotation` 的标识，默认 UUID。 | 注释通过 `observation_id` 或 `frame_id` 指向已有对象，不能代替被注释对象的 ID。 |
| `ImagePayload.image_id` | 图像载荷可选的素材标识，由创建者提供。 | 载荷命名空间；当前不要求它等于 `frame_id`，也不据此判断用户身份。 |
| `provider_item_id` | STT 服务返回的外部项目标识。 | 只用于供应商证据关联，不能代替内部片段引用。 |

`EnvObservation.source` 指观测生产来源；`segment.source` 固定原始片段来源。派生转录可以有自己的生产来源，关联音频时应沿 `segment` 追溯。`EnvAnnotation.source` 则是注释处理器名称，不能当成 `PerceptionSourceRef.source_id`。

来源退役会释放实体和片段关联，已存在的 Session 参与者及历史事件保留。片段 admission `token` 用于拒绝过期推理结果；片段被淘汰后，即使同名片段再次出现，旧 token 也不能重新打开关联。

实现入口：[EnvObservation](../avatar-core/alphaavatar/core/env/observation.py)、[EnvAnnotation](../avatar-core/alphaavatar/core/env/annotation.py)、[来源注册表](../avatar-core/alphaavatar/core/perception/source_registry.py)、[LiveKit 帧标识](../avatar-rtc/alphaavatar/rtc/livekit/utils/frame_id.py)、[图像载荷](../avatar-core/alphaavatar/core/media/image.py)、[STT 契约](../avatar-agents/alphaavatar/agents/avatar/voice/schema/transcription.py)。

## 3. 应用、会话、Turn 和执行

| 字段 | 定义与所有者 | 范围与关联 |
| --- | --- | --- |
| `avatar_id` / `avatar.id` | 配置中的 Avatar 实例身份。 | 应用级；用于选择 Workspace 和 Avatar Memory owner。它与渲染端点 `agent_device_id` 无关。 |
| `session_id` | `SessionRuntime` 的会话标识，默认 UUID。 | 关联参与者、事件和会话持久目录。关闭 Session 不等于完成 Episode/Context，也不等于提交全部长期数据。 |
| `execution_id` | Host 创建的一次执行实例标识。 | 执行管理器负责启动、停止和状态查询；不等于内部模型循环的 `run_id`。 |
| `attachment_id` | Host 与会话后端的一次附着标识。 | 关联 `SessionRequest` 与 `SessionEnd`，与执行、Core Session 分别建模。 |
| `lease_id` | 一次执行预留租约的标识。 | 与预留对象和到期时间一起防止失效预留被使用，不用于识别人。 |
| Host `source_id` | `SessionRequest` / `ExecutionReservation` 中的后端调度来源。 | 通过 `(backend, source_id)` 管理预留/去重，与媒体来源不是同一个命名空间。 |
| `turn_candidate_id` | Router 收集中的一次输入候选，默认 UUID。 | 一个候选可包含多个片段；同一候选的证据修订保留 ID。 |
| `input_id` | Turn 接纳入口的幂等关联键。 | 当前 Router 路径直接复用 `turn_candidate_id`，直接输入路径复用 `observation_id`，不重复生成 UUID。 |
| `turn_id` | `TurnRuntime` 提交后生成的 Turn 标识。 | 关联确定的观测集合、感知 cutoff 和身份快照；候选未必会提交，因此与候选有不同生命周期。 |
| `run_id` | 模型/工具循环的一次运行标识。 | `LoopIdentity` 将其与 `turn_id`、`context_id` 关联，用于运行状态、取消和输出归属。 |
| `consumer_id` | 某条事件流的消费者标识。 | 在该流中维护独立游标；不代表参与者或用户。 |

当前结构区分连接附着、Session、执行和工作上下文，但这些 ID 本身不承诺断线任务恢复或跨进程持久续跑。`pid` 只是运行进程的操作系统进程号。

实现入口：[Avatar 配置](../avatar-agents/alphaavatar/agents/configs/avatar_info_config.py)、[Host 执行契约](../avatar-host/alphaavatar/host/execution/schemas.py)、[TurnCandidate](../avatar-plugins/perception/avatar-plugins-router/alphaavatar/plugins/router/processors/turn_taking/schemas/state.py)、[输入接纳](../avatar-agents/alphaavatar/agents/avatar/engine.py)、[TurnRuntime](../avatar-core/alphaavatar/core/turn/runtime.py)、[Turn 契约](../avatar-core/alphaavatar/core/turn/schema.py)、[LoopIdentity](../avatar-agents/alphaavatar/agents/avatar/loop/schemas/identity.py)。

## 4. 模型、工具、输出与事件

| 字段 | 定义与范围 |
| --- | --- |
| 模型 `request_id` | 一次模型请求，默认由 `ModelRequest` 生成；供应商的同名请求字段应按其协议解释。 |
| `response_id`、`generation_id` | 供应商响应/生成记录的关联标识，可能由适配器从同一供应商值映射；不再充当会话或运行身份。 |
| 模型项目 `id` / `item_id` | 消息、工具调用项、控制项等模型输入/输出项目的标识。流事件使用 `item_id` 引用对应项目；供应商 opaque 项保留原始协议 ID。 |
| `call_id` | 一次工具调用的关联标识，同一次调用和结果使用同一个值。它与模型项目自身的 `id` 职责不同。 |
| `group_id` | 模型项目中可选的调用分组引用，由生产者提供；不生成新的参与者身份。 |
| `capability_id`、`tool_id`、`tool_name` | 能力注册或工具协议中的名称/引用。当前 `AvatarCapability.id` 返回注册 `name`，`tool_name` 是面向协议的名称投影；Memory 的 `tool_id` 记录工具来源。 |
| `trace_id` | 一条模型调用追踪记录的标识，供诊断关联。 |
| `output_id` | 一份输出内容的标识，由输出生产者提供；`OutputIdentity` 同时固定 lane 和 `OutputScope`，关联 context、turn 及可选 run。 |
| `chunk_id` | 输出文本或转录块的标识。`source_chunk_ids` 引用已有源块，用于派生转录与对齐。 |
| `alignment_id` | 一组文本/音频时序对齐记录的标识，用 revision 表达修订。 |
| `batch_id` | 输出记录批次的标识，与 producer、scope 和内容 digest 共同校验批次一致性。 |
| `decision_id` | 一次输出状态展示决策的标识；`source_event_id` 引用其执行事实来源。展示决策不等于新的执行事实或工具授权。 |
| Core `event_id` | Perception、Turn、Output 等流中一个事件的标识。流内顺序由 `sequence` 表达，不能按 UUID 排序。SessionEvent 本身使用 `(session_id, sequence)`，没有另加 event UUID。 |

语音输入沿用 `segment_id`，语音输出沿用 `output_id` 及其块/对齐引用；当前没有单独的 `speech_id` 或 `playback_id` 契约。

实现入口：[模型请求](../avatar-agents/alphaavatar/agents/avatar/provider/schemas/request.py)、[模型项目](../avatar-agents/alphaavatar/agents/avatar/provider/schemas/model_input.py)、[模型流](../avatar-agents/alphaavatar/agents/avatar/provider/schemas/stream.py)、[追踪记录](../avatar-agents/alphaavatar/agents/avatar/provider/schemas/trace_record.py)、[能力注册](../avatar-agents/alphaavatar/agents/runtime/capability/schema.py)、[输出身份](../avatar-core/alphaavatar/core/output/schemas/identity.py)、[输出记录](../avatar-core/alphaavatar/core/output/schemas/records.py)、[输出块](../avatar-core/alphaavatar/core/output/schemas/chunk.py)、[对齐](../avatar-core/alphaavatar/core/output/schemas/alignment.py)、[展示决策](../avatar-core/alphaavatar/core/output/schemas/decision.py)。

## 5. Memory、上下文和图

| 字段 | 定义与范围 |
| --- | --- |
| `memory_id` | Workspace Memory 主记录标识，默认 UUID。导出、索引和图关联引用同一记录；`source_memory_ids`、`supersedes_memory_ids` 引用已有 Memory。 |
| `episode_id` | 一组相关经历的归属标识，由运行上下文提供，当前 StateRuntime 为根 Episode 生成 UUID。不等于会话连接。 |
| `context_id` | 一个工作上下文的标识，由运行上下文提供；Turn、Loop、Output 和 Memory 可共同引用。`parent_context_id` 指向父上下文。 |
| `task_id` | `MemoryContextRef` 可选的上游任务引用，由调用者提供；不表示当前已经实现持久任务调度。 |
| `MemoryScope.scope_id` | 带类型的既有 ID：EPISODE 时是 `episode_id`，CONTEXT 时是 `context_id`，OWNER 时必须为空。不是额外生成的范围 ID。 |
| `MemoryOwnerRef.id` | 按 kind 解释为 `avatar_id` 或 `user_id`；`kind:id` 是类型化查询键。Owner 与检索 scope 分别表达归属和可见范围。 |
| `MemoryParticipantRef.id` | 按 kind 引用 user、avatar、tool 或 entity。entity 值不能单独证明跨来源身份，媒体来源需由对应来源引用和 Memory 上下文保留。 |
| `MemorySourceRef.source_id` | 按 kind 引用原始消息、工具调用、运行事件或媒体来源；感知实体来源同时保存 `source_generation` 与 `entity_id`，片段来源同时保存 `segment_id`。 |
| `MemoryGraphNode.id` | 图存储中的唯一节点标识。节点 `key` 用于语义去重/关联，`content` 用于检索，三者职责不同。 |
| `MemoryGraphLink.source_id / target_id` | 图边两端的节点 ID；`source_key / target_key` 是对应语义键。这里的 source 不表示媒体或设备。 |
| `MemoryOutboxEvent.event_id` | SQLite outbox 的整数记录标识，与 Core 流中的事件 UUID 不同；`worker_id / lease_owner` 关联当前投影消费租约。 |

`owner:*` 表示 Owner scope；具体归属仍由 owners 决定，不是向所有用户授权。`episode:<id>`、`context:<id>` 复用已有 Episode/Context ID。感知实体的 Memory 来源键由完整三元组编码，避免分隔符拼接混淆；跨会话解释时仍需结合 `MemoryContextRef.session_id`。

`data/memory/records.sqlite3` 是 Workspace 级权威记录，`exports/` 与本地索引是派生结果。身份判断变化不会把整个用户目录迁移到另一用户，也不能通过修改 scope 自动获得读取权限。

实现入口：[MemoryItem](../avatar-agents/alphaavatar/agents/memory/schemas/memory_item.py)、[MemoryContextRef](../avatar-agents/alphaavatar/agents/memory/schemas/context.py)、[MemoryScope](../avatar-agents/alphaavatar/agents/memory/schemas/scope.py)、[Memory 引用](../avatar-agents/alphaavatar/agents/memory/schemas/reference.py)、[图契约](../avatar-agents/alphaavatar/agents/memory/schemas/graph.py)、[存储提交与 outbox](../avatar-agents/alphaavatar/agents/memory/schemas/store.py)、[StateRuntime](../avatar-agents/alphaavatar/agents/runtime/modules/state/runtime.py)。

## 6. 版本、游标和路径键不是新身份

| 字段或概念 | 含义 |
| --- | --- |
| `identity_sequence` / `basis_sequence` | 单个参与者的身份版本与请求所依据的版本；不同于整个 Session 的事件序号。 |
| `source_generation` | 单个来源的世代，防止旧流结果进入新流。 |
| `candidate_revision` / candidate `revision` | 同一 Turn 候选的证据修订号，防止旧决策覆盖新证据。 |
| `sequence`、`cursor_seq`、`committed_cursor_seq` | 某条事件流的发布顺序、读游标和确认游标；不同流的数值不能互相比较。 |
| `cutoff.sequence` | 提交 Turn 时引用的 Perception 流边界，不是 Turn ID，也不代替来源/片段证据。 |
| `revision`、`content_index`、`output_index` | 各自记录的修订或内容位置，必须结合所属记录解释。 |
| 片段 `token` | ParticipantRuntime 内部的 admission 版本；不是用户标识或授权凭据。连接中的 `token` 则是接入凭据，两者不得混用或统一输出到诊断。 |
| `avatar_key`、`user_key`、`session_key`、`memory_key` 等路径键 | `path_key(logical_id)` 的文件系统投影。可直接使用的安全键保持原值，其余使用带前缀的 SHA-256，不做小写化或截断。逻辑 ID 保留原值，不能从哈希目录名反推用户。 |
| `digest` | 内容校验摘要，不能代替记录身份或权限。 |

目录的日期分层来自 Session 的 `created_at`，不应从 `session_id`、设备时间串或目录哈希猜测。应用级路径与 Workspace 路径分别由 [ApplicationPaths](../avatar-core/alphaavatar/core/workspace/application.py) 和 [WorkspacePaths](../avatar-core/alphaavatar/core/workspace/paths.py) 定义，显式目录创建位于 [operations.py](../avatar-core/alphaavatar/core/workspace/operations.py)。

## 7. 接入边界与命名规则

内部端点字段统一为 `device_id`，感知实体字段统一为 `entity_id`，不维护旧端点或实体字段别名。字段的复数形式、角色限定以及历史引用表示已有 ID 的集合或用途，不新增身份层。

第三方协议仍使用其真实字段：LiveKit 的 `participant.identity`、`participant_identity`、`sender_identity`，以及 Airi 的 `agentIdentity` 只在适配边界转换。外部 `track_sid` 标识媒体轨道，`room_name` 标识房间；模型下载的 `repo_id` 和语音服务的 `voice_id` 也按供应商命名空间解释，不能改成用户或设备 ID。

新增消费者应接收完整的类型化引用，跨层传递既有 ID；只有生命周期或被标识对象确实不同，才需要新 ID。身份、媒体归属和数据授权分别通过各自入口判断，不能仅凭相同字符串相互推导。
