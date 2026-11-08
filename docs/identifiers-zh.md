# AlphaAvatar 标识与关联约定

本文按标识的应用功能说明其含义、所有者、唯一性范围、生命周期和初始化入口。内容对应当前时序输入窗口实现：Turn-taking 消费感知观测与标注并提出动作，Engine 接纳输入，Core 提交 Turn；人物识别与身份接受不由 Turn-taking 承担。

同名字段必须结合所属类型解释。唯一性范围不是访问权限；知道一个 ID 不代表可以读取它指向的用户资料。表中的初始化入口同时区分自动生成、调用方提供、复用已有引用和供应商映射。

## 1. 应用与接入：定位 Avatar、会话和 Host 执行

| 字段 | 含义与所有者 | 唯一性范围与生命周期 | 初始化入口 |
| --- | --- | --- | --- |
| `avatar_id` / `avatar.id` | 配置中的 Avatar 实例身份，选择 Workspace，并作为 Avatar Memory 的 owner。 | 应用配置命名空间；不等于 Avatar 的 RTC 接入端点。 | 调用方通过 [Avatar 配置](../avatar-agents/alphaavatar/agents/configs/avatar_info_config.py) 提供；Workspace 按该配置装配。 |
| `session_id` | Core `SessionRuntime` 的会话标识，关联参与者、事件及会话目录。 | 在所属运行环境中标识一次 Session；默认 UUID，也可由调用方显式提供。 | [SessionRuntime.__init__()](../avatar-core/alphaavatar/core/session/runtime.py)。 |
| `execution_id` | Host 管理的一次执行实例，由执行管理器持有。 | Host 执行管理器中的启动、停止和状态查询范围；不同于一次模型循环的 `run_id`。 | [ExecutionManager.reserve()](../avatar-host/alphaavatar/host/execution/manager.py) 独立生成 UUID。 |
| `attachment_id` | 会话后端的一次连接附着标识，关联请求与结束通知。 | 对应一次附着；不把连接重建解释为新人物，也不等于 `execution_id` 或 `session_id`。 | `ExecutionManager.reserve()` 独立生成 UUID；后端写入 `SessionRequest`，结束通知复用。 |
| `lease_id` | 执行预留租约的标识，由 Host 预留流程持有。 | 与预留对象、来源和到期时间共同校验；预留失效后不能据旧租约启动执行。 | `ExecutionManager.reserve()` 独立生成 UUID，写入 [ExecutionReservation](../avatar-host/alphaavatar/host/execution/schemas.py)。 |
| Host `source_id` | `SessionRequest`、`ExecutionReservation` 中的后端调度来源。 | 通过 `(backend, source_id)` 关联预留及去重；与媒体 `PerceptionSourceRef.source_id` 是不同命名空间。 | [LiveKitBackend.serve()](../avatar-host/alphaavatar/host/sessions/livekit/backend.py) 在 direct 模式生成 UUID；dispatch 模式由 [LiveKitDispatch](../avatar-host/alphaavatar/host/sessions/livekit/dispatch.py) 采用服务端 `job.id`。 |

- `execution_id`、`attachment_id`、`session_id` 分别描述执行实例、连接附着和会话，不能因为当前恰好一一对应而互相替代。
- Session 关闭不是 Episode 或 Context 的统一结束条件，也不代表所有长期数据已经保存。这些 ID 本身不承诺跨进程恢复任务。
- 会话目录的日期来自 `SessionRuntime.created_at`，不能从 `session_id` 或设备时间串推导。

## 2. 人物关联：区分端点、感知实体、参与者和用户

| 字段 | 含义与所有者 | 唯一性范围与生命周期 | 初始化入口 |
| --- | --- | --- | --- |
| `device_id` | 接入适配层提供的应用端点标识；端点可提供文字、麦克风、摄像头及渲染连接。 | 当前接入后端的命名空间，例如 LiveKit room；不是硬件序列号，重新附着可复用或更换。 | RTC 输入适配器将 LiveKit `participant.identity` 映射为 `device_id`；参见 [音频输入](../avatar-rtc/alphaavatar/rtc/livekit/audio/input.py)、[视频输入](../avatar-rtc/alphaavatar/rtc/livekit/video/input.py)。 |
| `agent_device_id` | Avatar 自身接入端点的角色限定引用，仍属于 `device_id`。 | 对应当前连接，不等于 `avatar_id`。 | 接入配置或后端装配时提供，沿用端点身份。 |
| `entity_id` | 感知输入或跟踪器标记的实体，例如人脸、声纹跟踪对象。 | 用 `(session_id, source_id, source_generation, entity_id)` 完整解释；跟踪过期后不能据相同局部编号认定同人。 | 输入生产者提供；Persona 的 [人脸跟踪](../avatar-plugins/perception/avatar-plugins-persona/alphaavatar/plugins/persona/processors/face/tracking.py) 和 [说话人跟踪](../avatar-plugins/perception/avatar-plugins-persona/alphaavatar/plugins/persona/processors/speaker/tracking.py) 创建带 `face-` / `speaker-` 前缀的 UUID。 |
| `participant_id` | Core Session 中的逻辑参与者，汇集已经确认的输入关联。 | 一个 `SessionRuntime` 中唯一；默认 UUID。身份更正保留该 ID。 | [SessionRuntime.join()](../avatar-core/alphaavatar/core/session/runtime.py) 创建；业务通过 [ParticipantRuntime.join() / ensure_entity()](../avatar-agents/alphaavatar/agents/runtime/modules/participants/runtime.py) 使用。 |
| `user_id` | 长期用户身份，关联 Persona、Identity、Memory 等用户数据。 | 在应用的用户数据命名空间中解释，可跨会话复用；当前身份可更正或明确解绑为 `None`。 | `ParticipantRuntime.join()` 为未指定用户的新参与者分配 UUID；显式用户由调用方提供，后续通过 `bind_user(IdentityRequest(...))` 接受更正。 |
| `primary_participant_id` / `primary_user_id` | 主参与者引用及其当前用户投影，不是第二套人物身份。 | 当前 Session 的主参与者关系；不能作为未知音频人物的默认身份。 | [SessionRuntime.join(primary=...)](../avatar-core/alphaavatar/core/session/runtime.py) 选择主参与者；`primary_user_id` 从当前主参与者投影。 |

- `SessionContext.device_id` 表示用户接入端点；`CharacterConnection.device_id` 表示渲染目标端点。字段所属对象决定角色，不要求二者相同。
- `device_ids`、`excluded_device_ids` 是端点集合；`previous_user_id` 是历史引用，均不新增身份层。
- 同设备、同局部实体编号、同 `user_id` 都不会自动合并参与者。不同媒体是否为同一人，由明确的关联证据决定。

### 2.1 映射只有一个权威维护位置

- `device_id → participant_id`：`ParticipantBindings._devices`，用于明确的端点提交者；一个端点的画面仍可包含多人。
- `(PerceptionSourceRef, entity_id) → participant_id`：`ParticipantBindings._entities`；多个来源实体可显式指向同一参与者。
- `participant_id → user_id`：`SessionRuntime` 中当前不可变 `Participant` 快照；Bindings 不复制用户映射。
- `PerceptionSegmentRef → entity`：`ParticipantRuntime` 的有界片段关联状态，不再生成一种人物 ID。
- 业务统一通过 [ParticipantRuntime](../avatar-agents/alphaavatar/agents/runtime/modules/participants/runtime.py) 操作。底层 [ParticipantBindings](../avatar-agents/alphaavatar/agents/runtime/modules/participants/binding.py) 不执行识别模型、目录 I/O 或用户资料读取。

### 2.2 同一端点中的多人

- 手机 `phone-1` 的摄像头中，`(camera-1, 1, face-a)` 和 `(camera-1, 1, face-b)` 可以分别关联不同参与者、不同用户。
- 账户持有者明确提交的文字可使用 `resolve(device_id, endpoint=True)`；麦克风里的未知说话者不能因此归到该账户。
- `ensure_entity(source, entity, participant_id=...)` 可建立跨媒体同人关联；省略参与者时复用已有关系或创建参与者。已有实体要改关联时应显式释放，不能无声覆盖。
- 默认 `resolve()` 不回退到端点关联。未知实体、过期来源、冲突或淘汰片段不能回退到设备用户或主参与者。

## 3. 身份接受：用版本隔离更正、迟到推理和历史引用

| 字段 | 含义与所有者 | 唯一性范围与生命周期 | 初始化入口 |
| --- | --- | --- | --- |
| `Participant.identity_sequence` | 一个参与者当前已接受身份的版本，由 Session 管理。 | 单个 `participant_id` 内解释，初始为 `0`；接受不同身份时递增，不等于 Session 事件序号。 | [SessionRuntime.join() / request_identity()](../avatar-core/alphaavatar/core/session/runtime.py) 创建初始快照并更新版本。 |
| `IdentityRequest.basis_sequence` | 身份判断所依据的参与者版本，由调用方捕获。 | 一次判断的比较依据；当前版本已变化时返回 `STALE`，不得强行覆盖。 | 读取 `Participant.identity_sequence` 后构造 [IdentityRequest](../avatar-core/alphaavatar/core/session/schemas/__init__.py)。 |
| `TurnEntityRef.participant_id / user_id / identity_sequence` | 某 Turn 捕获的身份事实与版本引用，由准入及 Session 投影维护。 | 归属于该 Turn；历史快照不随之后的身份更正而原地改写。 | [AvatarEngine._decision_actors()](../avatar-agents/alphaavatar/agents/avatar/engine.py) 按实际拥有的输入解析，写入 `TurnSnapshot.actors`。 |
| 片段关联 `token` | `ParticipantRuntime` 内部片段登记版本，防止过期推理重新打开关联。 | 一个 Runtime 内的片段登记生命周期；与用户身份、接入凭据均无关。 | [ParticipantRuntime.observe_segment()](../avatar-agents/alphaavatar/agents/runtime/modules/participants/runtime.py) 分配，绑定和完成时验证。 |

- `bind_user()` 接受声明、感知、Agent 和独立决策模型的判断；不限制只识别一次，也不要求 Agent 的目标用户先被感知模块提名。
- `user_id=None` 表示明确解绑，不恢复初始用户、不重新分配 UUID。自动分配仅发生在业务入口创建新参与者时；Core `SessionRuntime.join()` 本身允许未绑定用户。
- `Participant` 是不可变快照。新的读取使用当前接受版本；已捕获的写入可通过 `accepts_identity(..., current=False)` 核验历史，并固定原写入目标。身份更正不会自动迁移用户目录或历史 Memory。
- `identity_history(participant_id)` 保存当前 Session 生命周期内全部已接受身份事件，独立于有界 Session 事件流；它不是持久恢复协议。

### 3.1 主动身份判断使用所属输入

- 能力名为 `participant.identity`，由 Engine 注册当前 `runtime.participants`；处理入口是 `ParticipantRuntime.invoke(request, *, input_id=...)`。
- `input_id` 来自 Loop／Registry 的显式调用上下文，不属于模型参数。读取 `TurnRuntime.get(input_id)`，缺失时拒绝，不回退到 `latest`。
- `invoke()` 先投影该 Turn 的当前接受身份。省略 `basis_sequence` 时使用投影后的身份版本；显式传入版本仍执行比较检查。
- 多参与者输入不能隐式挑一个人，需明确选择目标 `participant_id`。

### 3.2 事实归属与私有资料读取分开

- 多人时序窗口保留逐段实际 actors；未知语音不回退到设备或 primary，单段证据冲突只使该段保持未知。
- Persona 先通过 `project_turn(snapshot)` 投影 actors 的当前接受身份；任一 actor 匿名、未绑定／无法取得有效身份，或包含不同用户时，不向该 Turn 提供私有 Persona。同一已接受用户的多个参与者可使用对应资料；后台资料加载与该 Turn 的私有内容准入分别处理。Memory 另按其 identity/scope 规则控制读取。
- 人物识别、关联与属性推理由 Persona 等处理器完成。Turn-taking 消费标注，不绑定用户，不因同一窗口含不同 entity 而使语音段无效。
- 身份变化后的资料加载不能覆盖新身份。已冻结的模型输入和历史保持不变；运行中的身份检查及输出投递保护按既有执行契约处理。

## 4. 媒体关联：沿来源、片段和观测追溯输入

| 字段 | 含义与所有者 | 唯一性范围与生命周期 | 初始化入口 |
| --- | --- | --- | --- |
| `PerceptionSourceRef.source_id` | 一路逻辑媒体或输入来源，由接入适配器或生产者命名。 | 当前 Perception 会话；一个端点可以提供多路来源，不能仅按 `device_id` 合并。 | RTC 音频／视频适配器的 `_source_id()`；其他生产者构造 [PerceptionSourceRef](../avatar-core/alphaavatar/core/env/schemas/reference.py)。 |
| `source_generation` | 同一逻辑来源的启用世代；媒体来源通常由感知来源注册表分配，生产者也可显式指定。 | 与 `source_id` 共同构成完整来源引用；旧世代不能向新流写入结果。 | [PerceptionRuntime.next_source()](../avatar-core/alphaavatar/core/perception/runtime.py) 调用 [MediaSourceRegistry.next_source()](../avatar-core/alphaavatar/core/perception/source_registry.py)，首次为 `1`，之后递增；当前 RTC 文字来源直接指定为 `1`。 |
| `PerceptionSegmentRef.segment_id` | 一段 VAD 语音及其转录、取消等派生事实的关联 ID。 | 用完整 `(source_id, source_generation, segment_id)` 解释；跨 Session 还需 `session_id`。新段不等于新 Turn。 | [AudioActivitySource._start_segment()](../avatar-plugins/perception/avatar-plugins-router/alphaavatar/plugins/router/processors/audio_activity/source.py) 在 VAD START 时生成 UUID，END 后关闭。 |
| `observation_id` | 一次 `EnvObservation` 的标识，由观测生产者持有。 | 当前观测对象及其引用范围；同一片段可产生多个不同观测。 | [EnvObservation](../avatar-core/alphaavatar/core/env/observation.py) 默认 UUID；RTC 文字输入在 [`_read()`](../avatar-rtc/alphaavatar/rtc/livekit/text/input.py) 中用会话、端点、外部 stream ID 构造稳定摘要。 |
| `frame_id` | 一个具体媒体帧的关联标识，音频、视频均可使用。 | 当前帧及指向该帧的标注／证据；不是人物身份，也不代替 `observation_id`。 | RTC [create_frame_id()](../avatar-rtc/alphaavatar/rtc/livekit/utils/frame_id.py) 对会话、轨道、世代、帧序号与帧时间求摘要。 |
| `annotation_id` | 一条 `EnvAnnotation` 的标识。 | 一条独立标注的生命周期；被标注对象仍由 observation／frame 引用定位。 | [EnvAnnotation](../avatar-core/alphaavatar/core/env/annotation.py) 默认 UUID，生产者也可显式提供。 |
| `ImagePayload.image_id` | 图像载荷的可选素材标识，由创建者提供。 | 载荷命名空间；不要求等于 `frame_id`，不能用于判断用户身份。 | [ImagePayload](../avatar-core/alphaavatar/core/media/image.py) 的载荷构造入口。 |
| `TranscriptionEvent.provider_item_id` | STT 服务返回的外部项目引用，由适配器保留。 | 供应商连接／项目命名空间；不是内部 segment ID，允许为空。 | [OpenAI Realtime STT](../avatar-plugins/foundation/avatar-plugins-voice/alphaavatar/plugins/voice/stt/openai_realtime.py) 读取服务端 `item_id`；[TranscriptionEvent](../avatar-agents/alphaavatar/agents/avatar/voice/schema/transcription.py) 默认 `None`。 |

- `EnvObservation.source` 表示该观测的生产来源；`segment.source` 固定被关联的语音片段来源。派生转录可以有自己的生产来源，但仍沿完整 `segment` 追溯原音频。
- `EnvAnnotation.source` 是标注处理器名称，不是媒体 `source_id`。同名字段必须结合所属类型解释。
- Audio Activity 为原输入创建独立的 `router:speech:...` 来源；一段内部的语音帧、结束事件、STT 及取消事实复用同一 `PerceptionSegmentRef`。
- 来源重新创建时分配新 generation；当前 RTC track 的普通解除静音只更新来源状态，不必创建新世代。
- Persona 通过片段 token 核验迟到推理。物理关联完成不等于已识别长期用户；失败、取消、退役、淘汰也会释放等待，但不能标成识别成功。
- OpenAI 分段 STT 当前不提供 `provider_item_id`；不能假定所有 STT 结果都有供应商项目 ID。

## 5. 时序消费：区分事件顺序、消费进度和快照边界

| 字段 | 含义与所有者 | 唯一性范围与生命周期 | 初始化入口 |
| --- | --- | --- | --- |
| `consumer_id` | 某条流的消费者名称，由消费组件提供。 | 在对应流中维护独立进度；不代表人物，也不生成另一套事件身份。 | 组件声明固定名称，例如 [TurnTakingProcessor](../avatar-plugins/perception/avatar-plugins-router/alphaavatar/plugins/router/processors/turn_taking/processor.py) 的观测、标注和 Turn 消费者；首次读取时建立游标视图。 |
| Core `event_id` | Perception、Turn、Output 中独立事件的标识，由各流生产者持有。 | 所属流／会话中的事件身份；不能按 UUID 排序。 | [PerceptionRuntime._publish_event_locked()](../avatar-core/alphaavatar/core/perception/runtime.py)、[TurnStream.publish()](../avatar-core/alphaavatar/core/turn/stream.py)、[OutputRuntime._dispatch()](../avatar-core/alphaavatar/core/output/runtime.py) 构造事件；输出 journal 则由 [OutputJournal.append()](../avatar-core/alphaavatar/core/output/journal.py) 构造事件。 |
| `PerceptionEvent.sequence` | Perception 全局事件序号，跨保留的观测、标注和来源状态。 | 一个 PerceptionRuntime 内单调递增；初始计数为 `0`，发布的事件序号从 `1` 开始。 | `_publish_event_locked()` 更新 `_event_sequence`，并核验与 `events` 流序号一致。 |
| 各流 `sequence` / `StreamRecord.seq` | 某一具体流的发布序号，由该流持有。 | 只在同一条流中比较；Session、Turn、Output 以及媒体分流各自计数。 | [PerceptionStream.publish()](../avatar-core/alphaavatar/core/perception/stream.py)、`TurnStream.publish()` 分配本流序号；SessionRuntime 在状态操作中分配；输出由 `OutputRuntime._dispatch()` 或 `OutputJournal.append()` 分配。 |
| `cursor_seq` / `committed_cursor_seq` | 本次读取到的位置与消费者上次确认的位置，由消费组件和流共同维护。 | `(stream, consumer_id)` 范围；读取不自动确认，清除消费者后进度不再保留。 | `read_pending()` 产生读取结果，`commit()` 推进确认。Perception／Turn／Session 未登记时按 `0` 解释；[OutputJournal](../avatar-core/alphaavatar/core/output/journal.py) 必须先显式 `register(consumer_id, after=...)`。 |
| `PerceptionCutoff.sequence` | 感知快照的全局事件边界，不另生成 ID。 | 属于一次冻结范围，可为 `0`；不是某个媒体分流的消费游标。 | [capture_cutoff()](../avatar-core/alphaavatar/core/perception/runtime.py) 原子捕获；`capture_snapshot_until()` 按既定事件边界构造快照。 |
| `TurnSnapshot.start_cutoff / cutoff` | 该 Turn 的感知起始基线和最终快照边界。 | 固定在已提交 Turn 中；不证明范围内所有观测都属于该 Turn。 | [TurnRuntime.commit_event_input()](../avatar-core/alphaavatar/core/turn/runtime.py) 捕获；`_record()` 在发布 Turn 后推进内部 `_last_cutoff`。 |
| `InputWindow.observed_sequence` | 当前输入第一条已关闭语音段对应的保留事件序号，供先后输入的提交仲裁使用。 | 引用既有 Perception 事件序号，不是新增全局计数器；段关闭时查回，暂未查到保留事件则为 `0`，后续关闭可补定。 | [TurnTakingCoordinator._consume_speech()](../avatar-plugins/perception/avatar-plugins-router/alphaavatar/plugins/router/processors/turn_taking/coordinator.py) 按 observation 引用查回实际事件。 |

- `annotation_events` 的读取游标只计该标注流中的记录；其中 `PerceptionEvent.sequence` 仍是全局序号。不能把 `batch.cursor_seq` 直接作为全局 cutoff。
- `SPEECH_FRAME`、`TRANSCRIPT_DELTA`、`TRANSCRIPT_UNAVAILABLE` 不进入当前全局保留事件流；实时消费仍通过对应分流处理，不能假设所有观测都有全局事件序号。
- 事件 sequence 表达发布顺序；媒体先后与重叠关系仍使用 `RuntimeTimeRange`。不能用 UUID 排序，也不能把迟到标注的发布时间当作原音频时间。
- `SessionEvent` 使用 `(session_id, sequence)` 标识事件，没有再增加一个事件 UUID。

### 5.1 消费确认不等于 Turn 提交

- Router 处理一批观测后就确认消费游标，此时模型评估可能尚未完成，也可能返回 HOLD。推进游标不能清空待提交音频。
- Core 已有 `capture_cutoff_if_speech_idle()` 与 `wait_for_speech_idle_cutoff()`，原子检查语音活动并捕获边界；无需再造计数器。
- STT 等待可与后续输入重叠。`capture_snapshot_until()` 会补回新 Turn 明确拥有、但被前一个 cutoff 跨过的观测；清理必须同时考虑实际拥有的输入引用。
- 有界流暴露 gap、missed count 和保留边界。过期输入不能通过取“最新一条”补齐成另一份证据。

## 6. 输入与 Turn 准入：关联时序窗口、决策和成功提交

| 字段 | 含义与所有者 | 唯一性范围与生命周期 | 初始化入口 |
| --- | --- | --- | --- |
| Router `input_id` | 一次时序输入窗口的稳定身份，也是 Engine 接纳输入的幂等键。 | 同一窗口修订保留 ID；可跨多个 segment、包含多个 entity；取消或拒绝的输入不一定产生 Turn。 | [InputWindow](../avatar-plugins/perception/avatar-plugins-router/alphaavatar/plugins/router/processors/turn_taking/schemas/state.py) 默认生成 UUID，由 `TurnTakingCoordinator._window_for()` 创建。 |
| 直接输入 `input_id` | 文字／图片直接接纳入口的幂等键，不重新生成一份身份。 | 对应一次明确的直接输入；与 Router 窗口共用接纳协议。 | [AvatarEngine._admit_input()](../avatar-agents/alphaavatar/agents/avatar/engine.py) 复用该输入的 `observation_id`。 |
| `revision` | 同一输入证据的修订版本，由输入窗口维护，随 evidence／assessment／decision 传递。 | 只在所属 `input_id` 内比较；用于丢弃异步返回的旧评估，不表示身份版本。 | `InputWindow` 从 `0` 开始；接收语音段、终稿、有效标注或上下文变化时递增，构造模型证据前已有有效版本。 |
| `input_observation_ids` | 一次决定／Turn 明确拥有的输入观测引用集合。 | 固定实际提交成员，不等于端点模型看到的全部背景音频，也不等于 cutoff 范围内全部事件。 | [TurnEvidenceBuilder.build()](../avatar-plugins/perception/avatar-plugins-router/alphaavatar/plugins/router/processors/turn_taking/evidence.py) 收集，Policy 写入决定，Engine 逐项核验并传入 `TurnRuntime`。 |
| `system_notice_segment_ids` | 需要标记缺失转录的原语音段引用，沿用已有 segment ID。 | 属于同一决定拥有的语音输入；不生成新的故障语音段。 | 转录期限或不可用结算时，由 [TurnTakingCoordinator._notice()](../avatar-plugins/perception/avatar-plugins-router/alphaavatar/plugins/router/processors/turn_taking/coordinator.py) 从完整片段引用投影。 |
| `turn_id` | Core 真正提交后生成的 Turn 标识，对应固定输入、cutoff 和 actors 快照。 | 一个已提交 Turn；同一输入 ID 在保留的快照范围内重复接纳会返回既有快照。 | [TurnRuntime.commit_input() / commit_event_input()](../avatar-core/alphaavatar/core/turn/runtime.py) 生成 UUID。 |
| Turn-taking 诊断 `decision_id` | `input.decision` / `turn.admission` 中指向本次决定标注的关联引用。 | 对应一条决定的 `EnvAnnotation.annotation_id`；不同于第 8 节的展示决定 ID。 | 决定通过 `TurnTakingDecision.to_annotation()` 创建标注，发布及准入 trace 复用其 `annotation_id`。 |
| `decision_event_id / decision_event_sequence` | Turn metadata 中指向决定感知事件的引用和全局顺序。 | 固定到本次准入使用的决定事件，不另外创建事件。 | [AvatarEngine._admit_decision()](../avatar-agents/alphaavatar/agents/avatar/engine.py) 复制该 `PerceptionEvent` 的 ID 和 sequence。 |

- `segment_id` 标识一段 VAD 输入，`input_id` 标识待决策输入，`turn_id` 标识已提交快照。三者的对象和生命周期不同，不能互换。
- Turn-taking 按时序消费观测和语义／视觉 addressing 标注；不按人物创建候选表，不识别人或绑定用户。
- 当前未结束的窗口可跨 segment、跨 entity。有效且尚未实际确认的已封闭窗口，其音频也继续参与共享端点上下文，包括等待转录和已发布 COMMIT 尚待确认两种状态；实际拥有的输入引用仍各属原窗口。模型按支持的时间长度裁剪音频；不同人物出现在上下文中不意味着同人，也不会被强制归给一个 actor。
- 带身份、来源、接入状态的准入核验在相应权威入口执行。决定过期、来源取消／换代或证据丢失时，Engine 可以拒绝提出的 COMMIT。

### 6.1 提出决定、封闭输入与实际提交

- HOLD 保留当前输入，后续语音继续参与端点判断。端点已确定但 STT 未齐时，可固定该次输入成员并保存原决定，继续接收新的输入。
- 转录结果按完整 segment 引用返回原输入；不因后来人物识别或来源相同而改归另一个窗口。`transcript_wait_sec` 默认 0.75 秒，是等待观察点；`transcript_timeout_sec` 默认 3 秒，规定该次等待的绝对硬期限，已有期限不能由重评延长。
- `COMMIT` 标注只是提出接纳请求。真正提交后，`TurnRuntime` 发布 `TurnSnapshot` 到已有 Turn 事件流；[TurnTakingProcessor._consume_turns()](../avatar-plugins/perception/avatar-plugins-router/alphaavatar/plugins/router/processors/turn_taking/processor.py) 消费它作为成功确认。
- 成功确认更新 cutoff、回收对应 `input_id`，并刷新受影响的端点上下文。其他尚未提交的输入保留；不能按当前时间或一个消费游标一并清空。
- `admission_deadline_ns` 是接纳期限，不是新 ID。未获确认的已发布记录有界回收；Engine 也核验决定携带的接纳期限，避免超时后重新生效。

### 6.2 Engine 的输入标记不是人物候选或成功确认

- `AvatarEngine._inputs` 以 `input_id` 为键，保存已处理动作的集合。一次输入可以先 INTERRUPT、再 COMMIT，因此两种动作分别防重。
- Engine 可将过时／被拒输入标成终态，避免重放；该标记不证明成功生成了 `TurnSnapshot`。真实成功事实来自 Turn 事件流。
- 标记随 Engine 会话保留，当前不做中途淘汰；`EngineConfig.max_turn_inputs` 默认 `4096`，容量用尽后拒绝新增输入键。
- 直接输入、Router 决定、Loop 能力调用沿用同一 `input_id`。需要所属输入时使用 `TurnRuntime.get(input_id)`，不能用最新 Turn 替代。

## 7. 模型与工具执行：关联 Run、请求、项目和调用结果

| 字段 | 含义与所有者 | 唯一性范围与生命周期 | 初始化入口 |
| --- | --- | --- | --- |
| `run_id` | 一次模型／工具循环的执行标识，由 Loop 持有。 | 一个 Run 内可有多个模型请求；与 `turn_id`、`context_id` 共同定位执行、取消和输出归属。 | [LoopExecution.__init__()](../avatar-plugins/foundation/avatar-plugins-loop/alphaavatar/plugins/loop/execution.py) 用 UUID 构造 [LoopIdentity](../avatar-agents/alphaavatar/agents/avatar/loop/schemas/identity.py)。 |
| 模型 `request_id` | 一次 `ModelRequest` 的内部请求标识。 | 请求范围；同一 Run 的后续模型步骤使用新的请求 ID。 | [ModelRequest](../avatar-agents/alphaavatar/agents/avatar/provider/schemas/request.py) 默认 UUID；Loop 为日志关联提前生成并显式传入。 |
| `response_id` / `generation_id` | 供应商响应或生成记录的引用，由 Provider 适配器映射。 | 供应商协议命名空间；不代表 Run、Turn 或用户身份。 | [OpenAI Responses 流适配](../avatar-plugins/foundation/avatar-plugins-provider/alphaavatar/plugins/provider/openai/llms/stream.py) 读取响应 ID；[responses.py](../avatar-plugins/foundation/avatar-plugins-provider/alphaavatar/plugins/provider/openai/llms/responses.py) 将其映射到 `generation_id`。 |
| 模型项目 `id` / 流事件 `item_id` | 消息、工具调用、结果、控制项等项目的身份及引用。 | 所属模型输入／输出项目范围；opaque provider 项保留原始协议 ID。 | [模型项目构造器](../avatar-agents/alphaavatar/agents/avatar/provider/schemas/model_input.py) 接受生产者提供的 ID；Provider 映射服务端项目，Loop 为本地派生结果创建项目 ID。 |
| `call_id` | 一次工具调用与结果共用的关联键。 | 调用链内解释；不同调用不能因工具名相同而复用。 | Provider 从模型工具调用映射，`ModelFunctionCall` 显式接收；[LoopTools](../avatar-plugins/foundation/avatar-plugins-loop/alphaavatar/plugins/loop/tools.py) 将原 `call_id` 写入结果。 |
| `group_id` | 模型项目中的可选调用分组引用，由生产者提供。 | 所属供应商／项目协议范围；不是参与者或执行实例身份。 | `ModelFunctionCall(..., group_id=...)`，默认 `None`。 |
| `AvatarCapability.id` / `tool_name` | 注册能力的逻辑名称及模型工具协议名称。 | Registry 命名空间；前者等于 `name`，后者是清洗并在必要时附摘要的投影，不是随机 ID。 | [AvatarCapability](../avatar-agents/alphaavatar/agents/runtime/capability/schemas/capability.py) 接收 `name`；`id`、`tool_name` 属性派生。 |
| `tool_id` | 工具或能力协议中的来源引用，按所属记录解释。 | 具体 Registry、Provider 或 Memory 来源范围；不能无条件当成 `call_id`。 | 工具注册／适配时提供；Memory 的工具来源工厂显式接收已有 `tool_id`。 |
| `trace_id` | 一次 Provider 调用追踪记录的标识。 | 追踪记录范围；不是用户身份，也不作为重放请求的幂等键。 | [ProviderTracer.build_trace_id()](../avatar-agents/alphaavatar/agents/avatar/provider/trace.py) 生成 `ptrace_` 加 UUID，由 Gateway 写入追踪记录。 |

- 模型项目 `id` 和 `call_id` 不同：一个标识调用项目，另一个把调用和结果配对。结果可以有自己的项目 ID，同时保留原调用的 `call_id`。
- `input_id` 定位输入，`turn_id` 定位提交快照，`run_id` 定位执行，`request_id` 定位一次模型请求。供应商返回 ID 不替代内部关联链。
- 能力具有 ID 或展示为 tool 不代表可执行或已获授权；`input_schema=None` 的描述能力仍不可调用，Registry 和执行策略独立核验。
- 同一个 Run 捕获的能力定义、模型前缀和历史按执行契约复用；不能通过换 ID 把迟到工具结果混入新身份上下文。

## 8. 输出与展示：关联内容、块、对齐和执行事实

| 字段 | 含义与所有者 | 唯一性范围与生命周期 | 初始化入口 |
| --- | --- | --- | --- |
| `output_id` | 一份输出内容的身份，由内容生产者提供；Core `OutputIdentity` 同时固定 lane 与 scope。 | 在当前输出运行环境及其归属范围内解释；可以有多个文本块、音频帧和对齐修订。 | [LoopFeedback.output_id()](../avatar-plugins/foundation/avatar-plugins-loop/alphaavatar/plugins/loop/feedback.py) 使用 `run_id:item_id`；状态播报使用 `status:decision_id`；[OutputIdentity](../avatar-core/alphaavatar/core/output/schemas/identity.py) 不自动生成。 |
| `chunk_id` | 一个输出文本块或转录块的标识。 | 所属输出及派生对齐链；不是新 output。 | [OutputTextChunk / OutputTranscriptChunk](../avatar-core/alphaavatar/core/output/schemas/chunk.py) 默认 UUID，生产者可显式提供。 |
| `source_chunk_ids` | 派生转录／对齐引用的已有源块集合。 | 关联原文本与派生结果，不另外创建源块。 | 语音／字幕同步生产者构造输出块时复制源 `chunk_id`。 |
| `alignment_id` | 一组文本／音频时序对齐记录的稳定身份。 | 估计与实测修订沿用该 ID，另以 alignment `revision` 区分版本。 | [SpeechStreamer.run()](../avatar-plugins/perception/avatar-plugins-router/alphaavatar/plugins/router/processors/speech/speech_synthesis/streaming.py) 构造 `output_id:speech:segment.index`；[OutputTextAudioAlignment](../avatar-core/alphaavatar/core/output/schemas/alignment.py) 字段必填。 |
| `batch_id` | 一批输出记录的幂等关联键，由记录生产者提供。 | 与 producer、scope 和内容 digest 一起核验；不是内容摘要本身。 | [LoopExecution._commit()](../avatar-plugins/foundation/avatar-plugins-loop/alphaavatar/plugins/loop/execution.py) 构造 `loop:run_id:批次序号`，传入 [OutputRecordBatch](../avatar-core/alphaavatar/core/output/schemas/records.py)。 |
| `OutputStatusDecision.decision_id` | 一次状态展示决定的身份，由状态展示处理器生成。 | 一次展示决定；不同于输入决定的 annotation ID，不代表新执行事实。 | [PresentationProcessor._publish()](../avatar-plugins/perception/avatar-plugins-status/alphaavatar/plugins/status/processors/presentation/processor.py) 生成 UUID，构造 [OutputStatusDecision](../avatar-core/alphaavatar/core/output/schemas/decision.py)。 |
| `source_event_id` | 展示决定所依据的执行／Turn／投递事件引用。 | 指向原事件，不另生成 ID；原事件所属流决定其含义。 | `PresentationProcessor._publish()` 复制 `ActivityNotice.source_event_id`；Activity 处理器从触发事件复制 `event_id`。 |
| `OutputRuntime.text_sequence(output_id)` | 该输出最后一次本地接纳文本的 Output 事件序号。 | 未知或尚未接纳时为 `0`；不是远端送达或播放确认，也不是新的文本 ID。 | [OutputRuntime](../avatar-core/alphaavatar/core/output/runtime.py) 在接纳文本事件时登记，查询接口按原 `output_id` 返回。 |

- `OutputScope` 复用 `context_id`、`turn_id` 和可选 `run_id`；输出身份还包含 lane，不能只用一段文本猜归属。
- 输入语音复用 `segment_id`；输出语音沿用 `output_id`、块和对齐引用。当前没有独立的 `speech_id` 或 `playback_id` 契约。
- 输出对齐中的 `segment.index` 是该输出内部的合成分段位置，不是输入 `PerceptionSegmentRef.segment_id`。
- 本地接纳、订阅者收到、远端播放是不同边界。任一订阅者收到 final 不能证明所有终态发布已经结束。

## 9. Memory 与工作上下文：确定长期记录、范围和来源

| 字段 | 含义与所有者 | 唯一性范围与生命周期 | 初始化入口 |
| --- | --- | --- | --- |
| `memory_id` | Workspace Memory 权威记录的身份，导出、索引和图引用同一记录。 | 当前 Workspace Memory 数据库主键；改写同一聚合记录保留 ID、递增记录 revision。 | [MemoryItem](../avatar-agents/alphaavatar/agents/memory/schemas/memory_item.py) 默认生成带连字符 UUID；`MemoryProcessor.build_memory_items()` 等构造时触发。 |
| `episode_id` | 一组相关经历的归属 ID，由运行上下文提供。 | 与会话连接生命周期不同；可显式复用，ID 本身不保证恢复执行。 | [StateRuntime](../avatar-agents/alphaavatar/agents/runtime/modules/state/runtime.py) 默认 UUID；Memory 根上下文复制该值，子上下文默认继承父 Episode。 |
| `context_id` / `parent_context_id` | 工作上下文身份及其父引用，供 Turn、Loop、Output、Memory 关联。 | 默认根 Context 随 StateRuntime 创建；子 Context 在所属运行上下文中检查唯一性。 | `StateRuntime` 默认 UUID；[MemoryContextRef.child(context_id=...)](../avatar-agents/alphaavatar/agents/memory/schemas/context.py) 接收调用方提供的子 ID，复制父 ID 为 `parent_context_id`。 |
| `task_id` | Memory 上下文可选的上游任务引用。 | 由调用方的任务命名空间解释，不代表已经实现持久任务调度。 | `MemoryContextRef(..., task_id=...)`，默认 `None`；没有自动 UUID 生成器。 |
| `MemoryScope.scope_id` | 按 scope kind 复用既有 Episode／Context ID。 | EPISODE 使用 `episode_id`，CONTEXT 使用 `context_id`，OWNER 必须为空。 | [MemoryScope.episode() / context() / owner()](../avatar-agents/alphaavatar/agents/memory/schemas/scope.py)，不生成新的范围 ID。 |
| `MemoryOwnerRef.id` | 按 kind 引用 `avatar_id` 或已接受的 `user_id`。 | Owner 命名空间，类型化查询键为 `kind:id`；归属与读取范围分别表达。 | [MemoryOwnerRef.avatar() / user()](../avatar-agents/alphaavatar/agents/memory/schemas/reference.py) 复制已有 ID。 |
| `MemoryParticipantRef.id` | 按 kind 引用 user、avatar、tool 或 entity。 | 对应引用类型的命名空间；局部 entity 值不能单独证明跨来源同人。 | [MemoryParticipantRef](../avatar-agents/alphaavatar/agents/memory/schemas/reference.py) 构造时显式传入已有 ID。 |
| `MemorySourceRef.source_id` | 按 kind 引用原始消息、工具调用、运行事件或感知来源。 | 来源类型及原始协议范围；感知引用还保存 generation、segment 或 entity。 | `MemorySourceRef.message()`、`tool_call()`、`tool_result()`、`runtime_event()` 及感知来源工厂，均复制传入值。 |
| `MemoryGraphNode.id` | 图节点记录的唯一标识。 | 当前图记录范围；与语义去重键 `key`、检索内容 `content` 分工不同。 | [MemoryGraphNode](../avatar-agents/alphaavatar/agents/memory/schemas/graph.py) 默认生成 `node_` 加 UUID；[graph_builder.py](../avatar-plugins/perception/avatar-plugins-memory/alphaavatar/plugins/memory/storage/graph/graph_builder.py) 构造节点。 |
| 图边 `source_id / target_id` | 边两端的既有图节点 ID。 | 可被多条边重复引用；source 不表示媒体来源，边本身没有独立 ID。 | `build_graph_from_mentions()` 复制端点节点的 `id`；`source_key / target_key` 同时保留语义键。 |
| `MemoryOutboxEvent.event_id` | SQLite outbox 整数记录标识。 | 单个数据库表内唯一、递增；不是 Core 事件 UUID。 | [commit_sync()](../avatar-plugins/perception/avatar-plugins-memory/alphaavatar/plugins/memory/storage/sqlite/commit.py) 插入记录时，由表的 `INTEGER PRIMARY KEY AUTOINCREMENT` 分配。 |
| Outbox `worker_id / lease_owner` | 投影 Worker 实例身份及当前认领者引用。 | Worker 实例与认领租约范围；`lease_owner` 复制 Worker ID，不另生成身份。 | [MemoryOutboxWorker.__init__()](../avatar-plugins/perception/avatar-plugins-memory/alphaavatar/plugins/memory/storage/outbox.py) 生成 `memory:target:UUID`；[claim_outbox_sync()](../avatar-plugins/perception/avatar-plugins-memory/alphaavatar/plugins/memory/storage/sqlite/outbox.py) 复制为 `lease_owner`。 |

- `MemoryContextRef` 自身不自动生成 Episode／Context ID；它引用 StateRuntime 或调用方给出的已有上下文。`open_context()` 的重复检查不等于全球唯一性承诺。
- `owner:*` 只表示 Owner scope，实际归属仍由 owners 决定，不代表向所有用户授权。`episode:<id>`、`context:<id>` 也复用已有 ID。
- 环境 Memory 的运行事件来源当前使用 `session_id 或 episode_id` 加事件 sequence 的复合键；不能假定 `MemorySourceRef.runtime_event()` 总是收到 Core 的事件 UUID。
- 感知实体来源必须保留完整来源三元组；片段引用保留 source、generation、segment。跨会话追溯还需 `MemoryContextRef.session_id`。
- `data/memory/records.sqlite3` 是 Workspace 级权威记录，`exports/` 和本地索引是派生结果。身份更正不会通过改 scope 或移动用户目录自动授予读取权限。

## 10. 路径与外部协议：投影既有身份而不新增身份层

| 字段 | 含义与所有者 | 唯一性范围与生命周期 | 初始化入口 |
| --- | --- | --- | --- |
| `avatar_key / user_key / session_key / memory_key` 等路径键 | 逻辑 ID 的文件系统安全投影，由路径层派生。 | 所属根目录中的路径命名空间；逻辑 ID 保留原值，不能从摘要目录名反推身份。 | [path_key(logical_id)](../avatar-agents/alphaavatar/agents/workspace/paths.py)：可安全使用时保持原值，否则生成 `~id-` 加 SHA-256，不做小写化或截断。 |
| `digest` / 内容 hash | 内容一致性和批次校验摘要，由相应生产者计算。 | 只对具体编码、内容和用途有效；不代替记录 ID 或访问权限。 | 对应载荷／记录／存储入口按其协议计算；不能假定整个项目只有一种摘要算法。 |
| `pid` | 操作系统进程号。 | 当前操作系统的进程生命周期，可在进程退出后复用。 | 操作系统创建进程时分配，由进程管理代码读取。 |
| LiveKit `participant.identity / participant_identity / sender_identity` | 外部连接端点字段，边界适配为内部 `device_id`。 | 对应 LiveKit room／连接协议命名空间，不是 Core 参与者 ID。 | LiveKit SDK／接入配置提供，RTC 与 Host 适配层映射。 |
| `track_sid / room_name / stream_id` | 第三方轨道、房间或传输流引用。 | 供应商协议命名空间，不能与内部来源／参与者编号直接互换。 | 服务端或 SDK 分配，接入适配器读取并用于构造内部引用。 |
| 模型 `repo_id` / 语音 `voice_id` | 模型仓库或声音资产的供应商名称。 | 所属模型平台／语音服务范围，不代表人物身份。 | 配置和模型／服务适配器显式接收。 |
| 连接 `token` | 接入认证凭据，不属于本文的身份关联键。 | 按接入协议和有效期使用；与第 3 节的片段关联 token 完全不同。 | Host／连接后端根据其认证契约提供；不作为诊断关联 ID 输出。 |

- 角色限定、复数形式及历史引用不会产生新的 ID 类型。Airi 的 `agentIdentity` 等外部字段也只在适配边界转换。
- 新增 ID 必须有不同的被标识对象或生命周期；否则传递既有 ID 或完整类型化引用，避免为同一对象重复生成 UUID。
- 应用根路径由 Host [ApplicationPaths](../avatar-host/alphaavatar/host/workspace/application.py) 定义；Workspace、用户、会话路径由 Agents [WorkspacePaths](../avatar-agents/alphaavatar/agents/workspace/paths.py) 定义。
- 显式目录创建分别位于 Host 和 Agents 的 `workspace/operations.py`。路径键的创建、目录 I/O、身份接受和权限核验是不同职责。
- 依赖方向保持 RTC → Core、Agents → Core、Host → Agents；插件消费已有 Runtime 契约，不把具体识别、模型或后端实现移入 Core。
