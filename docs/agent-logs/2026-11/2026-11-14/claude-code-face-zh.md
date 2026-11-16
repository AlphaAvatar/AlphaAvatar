# Persona 人脸 — Claude Code 工作日志

- 分支 `dev/v0.6.9`，基线 HEAD `fa58238e`（身份版本改名已提交）；日期 2026-11-14（CST）。
- 接续 Speaker Vector 日志（[claude-code-speaker-vector-zh.md](../2026-11-10/claude-code-speaker-vector-zh.md)）：说话人第五到第十一批定下的规则，在人脸处理器上逐项对照。
- 范围：Persona 人脸的处理器、跟踪与保存，以及用户安排随本轮一起做的 Memory `_session_sequence` 改名。说话人、Speaker Attribute 不在本轮。
- 工作方式与之前相同：先出报告，用户决定后按小批次改；改动留在未暂存的工作区，由用户提交。

## 历史记录（合并来源）

以下来自之前的日志，原处保留，这里只汇总它们与人脸有关的结论和待办：

| 事项 | 来源 | 内容 |
|---|---|---|
| KD-40 保存人脸向量 | Speaker Vector 日志第五批、第六批「遗留」；`docs/bugs-zh.md` KD-40 | 会话结束保存时，人脸向量整份替换用户存储的人脸向量；同一用户的几个参与者各自写入，留下哪一份不固定。说话人的同一问题已由 KD-38、KD-39 修复 |
| 人脸跟踪的 60 秒超时 | Speaker Vector 日志第八批；`docs/bugs-zh.md` KD-43 | 说话人跟踪的超时已取消，人脸跟踪的 `track_ttl_sec`（60 秒）未改 |
| 实体在会话内唯一 | Speaker Vector 日志第九批、第十批及「第十批之后的决定」；`docs/bugs-zh.md` KD-44 | 契约已改为实体在会话内唯一、可以跨来源和代；绑定层和说话人已实现，人脸"在说话人改完后按同一规则修改"。第十批只把人脸的 `release_entity()` 改为只带实体，人脸跟踪器本身未改 |
| 帧任务的参与者快照 | Speaker Vector 日志第十一批「验证（离线）」；`docs/bugs-zh.md` KD-45 | 说话人的段快照已去掉；人脸的 `FaceFrameJob` 仍带参与者快照，留到本轮 |
| 改绑后向量不清空 | Speaker Vector 日志「第十批之后的决定」；`docs/bugs-zh.md` KD-41 | 改绑时人脸向量同样不清空；用户判断根本原因是匹配，延期，随匹配优化处理 |
| 统一向量库 | Speaker Vector 日志第七批 | 人脸处理器和人脸推理改用 `VectorOps.norm()`，cache 的人脸平滑改用 `VectorOps.merge` |
| Memory `_identity_sequence` | Speaker Vector 日志第十一批「留给下一步」 | 实际存的是会话事件序号，改为 `_session_sequence`，用户安排随人脸一起做 |

## 待办

1. 人脸跟踪的 60 秒超时是否取消（对照 KD-43）。
2. 人脸跟踪按会话内实体保存、跨来源和代匹配（KD-44 的人脸部分）。
3. 保存人脸向量：与用户存储的人脸向量合并，同一用户的几个参与者合成一份写入（KD-40，对照 KD-38、KD-39）。
4. 去掉 `FaceFrameJob` 的参与者快照（对照 KD-45）。
5. Memory `state.py` 的 `_identity_sequence` 改为 `_session_sequence`。

下一步：通读人脸处理器、跟踪与保存的代码，逐项给出例子和需要用户决定的地方。

# 第一批：分析与身份两条循环

- 基线 `349e20bf`（说话人处理器的精简与本日志已提交）。用户的要求：先和说话人对称，拆成两条循环，队列容量另行讨论。

## 改之前

`_inference_loop` 只有一个任务，每一帧依次做：人脸分析推理、跟踪关联、`ensure_entity` 取参与者、发布 FACE_DETECTION 标注，最后 `asyncio.gather` 等这一帧所有脸的身份检索（最多 4 个并发，`identity_concurrency`）。检索慢时后面的帧排队等待，只保留最新 2 帧的队列会丢帧，跟踪关联和视觉寻址读的标注都被推迟。

## 修改

| 位置 | 改动 |
|---|---|
| `face/processor.py` | 与说话人相同的 `_serve(lane, queue, process)`：`frame` 一条（`_frame_queue` → `_process`，即原 `_inference_face_job`，按用户要求改名），`identity` 一条（`_identity_queue` → `_identify`，即原 `_update_face`）。帧那条发布标注后把每张有向量、有参与者的脸作为 `FaceIdentityJob` 交给身份那条，不等待；身份那条每次一个。启动、停止与说话人相同：`_consume_task`、`_lanes`，停止时取消全部任务，清空两个队列 |
| `face/config.py` | 删除 `identity_concurrency`：身份检索与说话人一样一次一个，这个设置不再有用。全仓库只有人脸处理器用到它 |

- 身份队列的容量暂用 `max_faces`（默认 16），满了丢最旧的（同一张脸之后的帧还会再来），属性仍在身份那一步更新。容量与策略待与用户讨论。
- `FaceFrameJob` 的参与者快照未动（待办第 4 项）。写测试时看到它的影响：第一帧的检索还没返回时到达的第二帧，快照拍在绑定之前，第一帧绑定后第二帧的身份那一步因版本已变被跳过。拆分之前同样如此，消费循环本来就独立于推理循环拍快照。

## 验证

- 新增 `test_a_slow_face_identity_never_holds_the_next_frames_analysis`：第一帧的检索挂起时，第二帧照样分析、关联并发布标注；放开后身份确定。把帧那条改回逐个等待身份时失败（第二帧要等到挂起的检索 2 秒超时才被分析）。
- Persona 测试通过；ruff、format 通过。

# 第二批：帧队列按秒数配置

- 基线 `a2ba8389`（第一批已提交）。用户的要求：为帧队列引入配置，按"多少秒的输入"表示。
- `face.frame_queue_sec`（默认 0.4 秒）：帧队列容纳一个来源这么多秒的取样帧（每 `VIDEO_PERSONA_INTERVAL_SEC`，即 0.2 秒一帧），帧数为秒数除以取样间隔、先四舍五入到 6 位小数再向上取整，至少 1 帧；分析跟不上时最旧的让位给新帧。Persona README 写明了这个设置。
- 默认值：用户曾考虑调长，以便将来基于历史帧计算人脸动态轨迹。讨论后保持 0.4 秒（与改动前的 2 帧相同）：帧队列是待分析的积压，分析跟得上时基本为空，跟不上时越长分析越落后于实时；历史帧由 PerceptionRuntime 保留（`retention_sec` 默认 60 秒），轨迹更适合以后在跟踪里按秒数保存分析结果。
- 测试：0.4 秒、0.6 秒分别保留 2、3 帧；0、负数、无穷大被拒绝，很短的时间至少 1 帧。三处变异都被发现：写死 2 帧、不四舍五入直接向下取整（0.6 / 0.2 得 2.9999999999999996）、短时间取整为 0（asyncio 的容量 0 表示不设上限）。全量测试 726 个通过。

# 第三批：去掉帧快照，身份那一步读取当前版本（KD-45）

- 基线 `f7454d36`（第二批的代码已提交）。
- **去掉快照**：`FaceFrameJob` 只剩观测；`_participant_for` 返回 `ensure_entity` 给出的参与者，不再从快照里取当时的版本。快照造成两种丢失（与说话人 KD-45 相同）：这一帧排队时这张脸的参与者还没建出来（快照里没有它，身份那一步被跳过）；或者排队时还没认出来、分析时已经认出来（快照里的旧版本不再被接受）。
- **只去掉快照还不够**：两帧在帧那条循环里紧挨着分析，第二帧分析时第一帧的身份还在排队，第二帧的身份任务带走的仍是版本 0；第一帧绑定后，第二帧因版本已变被跳过。说话人也剩同样的问题：段结束后排在身份队列里的段，被前面一段的绑定作废。这是 KD-45 的第二种丢失。
- **用户的决定**：身份那一步在开始检索前读取参与者当前的版本，人脸和说话人一起改。
  - 人脸 `_identify` 按来源和实体解析当前的参与者，`FaceIdentityJob` 不再带参与者。
  - 说话人 `_identify` 按语音段解析当前的参与者；`_take_entity`、`_finish_segment` 不再保存参与者，`SpeakerSegmentState.participant` 只记身份那一步认出的参与者，供属性使用。
  - 检索前后的检查和 `bind_user` 的版本比对不变，检索期间身份变了仍不覆盖。
- **测试**：
  - 新增 `test_a_frame_queued_before_its_face_changed_still_takes_its_identity_step[created, identified]`，在改之前的代码上两种情况都因"第二帧没有检索"失败；只去掉快照时 `created` 仍失败。
  - 新增 `test_a_segment_queued_behind_its_voices_identification_still_takes_its_identity_step`（说话人）。
  - 变异：身份那一步固定为参与者最初的版本时，说话人 13 个、人脸 4 个测试失败。
  - Persona 与 host `test_turn_actors` 114 个通过；全量测试 729 个通过；ruff、format 通过。
- `docs/bugs-zh.md` 的 KD-45 一并更新。

# 第四批：人脸跟踪改为像说话人那样的 resolve（进行中）

- 用户要求先只改名：`FaceTracks.associate` 改为 `resolve`（`face/tracking.py`，调用处在 `face/processor.py` 的 `_process`），行为不变，Persona 测试通过。
- 基线 `a4762032`（第三批与改名已提交）。
- **取消 `track_ttl_sec`**（对照说话人 KD-43）：人脸跟踪原来 60 秒没见到就退役，第一次出现的人离开画面一分钟再回来，会开新跟踪、得到新的实体和参与者，保存后成为碎片。删除配置项与跟踪器里的超时清理，以及只为它保存的 `seen_at`；跟踪只在来源换代或处理器停止时退役。
  - 测试替身新增 `anonymous_faces`（输出不带实体的脸，走生成跟踪）。新增 `test_a_face_unseen_for_an_hour_is_still_one_participant`：库里没有的人一小时后再出现，仍是同一个实体、同一个参与者。换回带超时的旧跟踪器时失败（一小时后得到另一个实体）。
- **按会话实体保存、跨来源和代匹配**（KD-44 的人脸部分）：`FaceTracks._tracks` 从"（来源, 实体）"改为以实体为键，`FaceTrack.sources` 按顺序记录出现过的来源和代；所有跟踪都是候选，不再只看本来源；来源换代不再让它的跟踪退役，只重新开始这一来源的帧顺序。跟踪只在处理器停止时退役，处理器里每帧的退役释放随之删去，`_release_retired_tracks` 改为与说话人相同的 `_release_tracks`。数量上限 `max_tracks` 和"只记第一帧的向量"未改，留待后面讨论。
  - 新增 `test_one_face_is_one_participant_across_cameras_and_generations`：库里没有的人依次出现在摄像头 1、它的下一代、摄像头 2，始终是一个实体、一个参与者，`sources` 按顺序记下三处。4 处变异都失败：候选只取本来源本代、只取本摄像头、换代时丢掉本摄像头的脸、`sources` 只记第一处；换回完整的旧人脸代码时也失败（三帧得到不同的实体）。
  - `docs/bugs-zh.md` 的 KD-44 移到已修复；`identifiers-zh.md` 第 2 节的实现说明同步更新。
- **去掉跟踪器的来源状态**：`FaceTracks._sources`（每个来源最新的代和上一帧的时间）与别处重复。代由 ParticipantRuntime 管：帧进队列前 `observe_source` 拒绝旧的代，任务前后 `_job_is_current` 检查 `source_is_current`；帧的顺序由取样保证（`_last_sample_ts` 拒绝比上一帧早的帧），帧队列先进先出。删除 `_sources`、`activate`、`current` 和 `resolve` 的顺序检查与 `at` 参数；`max_tracks` 不再限制来源数量（来源上限是 ParticipantRuntime 的 256）。
  - 新增 `test_a_frame_behind_its_sources_latest_is_never_analyzed[older-generation, earlier-frame]`：旧一代的帧（即使拍得更晚）和比本来源上一帧早的帧都不会被关联。
  - 变异：进队列和任务前后的代检查各去掉一道时测试照常通过，两道互为后备（身份那一步之前 `ensure_entity` 也拒绝已退役的代）；两道一起去掉时失败；取样允许更早的帧时失败。
- **取消跟踪数量上限**（与说话人相同）：跟踪不再受 `max_tracks` 限制，受 ParticipantRuntime 的实体与参与者容量（默认 1024）约束。`max_tracks` 只剩限制属性缓存的用途，改名为 `max_face_caches`（默认仍为 128）。`FaceTracks` 只需两个阈值，构造函数与说话人一样改为 `threshold`、`margin`。`identifiers-zh.md` 第 2 节同步。
  - 新增 `test_face_tracks_are_unbounded_and_only_attribute_caches_are_bounded`：`max_face_caches=1` 时一帧三张脸各有跟踪，属性缓存只留最后一个。重新限制跟踪数量、属性缓存不设上限这两处变异都失败。

# 第五批：说话人与人脸都不再接受上游给的实体

- 基线 `76712657`（第四批已提交）。
- 起因：讨论人脸 `resolve` 的 `explicit` 参数时确认，生产中没有任何上游给语音或视频观测带实体（真实的人脸分析不输出 `entity`，RTC 不设置），这条路径只有测试走到；而测试替身默认带实体，大部分测试走的是生产不走的路径。用户的决定与开发规范："不能为了测试而修改生产代码逻辑"，两边同时去掉。
- **说话人**：删除 `_take_entity` 与 `_state` 里建 state 时、段中途拿到实体时的两处处理（含两个实体冲突时作废）；短段不再看下一段是否带身份，`_close_segment` 只按 VAD 秒数判断短段；`_finish_segment` 每段都由跟踪匹配实体。KD-47 里建 state 时 `ensure_entity` 失败那条路径随之消失。
- **人脸**：`FaceTracks.resolve(source, vectors)` 不再有 `explicit`，所有跟踪都由跟踪器生成，`FaceTrack.generated` 删除、向量不再可能为空；处理器不再按观测自带的实体选出 `selected_face_index`。
- **测试**：替身的人脸不再带 `entity`（`anonymous_faces` 删除），`speak()` 不再有 `explicit`；`sense()` 改为返回"这次观测关联到的参与者"的查询（说话人按语音段，人脸按这一帧的标注），`show()` 返回它发布的观测。删除只测已删行为的 `test_a_segment_whose_subject_arrives_on_a_later_frame_takes_it`、`test_a_segment_with_its_own_subject_drops_the_short_speech_before_it` 和 `named-subject` 一例；`test_a_frame_behind_its_sources_latest_is_never_analyzed` 改按用户判断。
- **文档**：Persona README、说话人 `config.py` 注释、`docs/bugs-zh.md` 的 O-25 与 KD-47、`identifiers-zh.md` 的 `entity_id` 一行。
- **留给用户决定**（本批未动）：
  - agents 契约 `FaceDetectionResult.selected_face_index` 已无生产者，也没有读者：用户决定删除，字段、范围校验和序列化一并删去。
  - Router 的音频活动转发 `observation.entity`，轮次判断与语义寻址也读取它；Core 的 `EnvObservation.entity` 在生产中都为空。
  - 说话人的 `invalid` 与 `inference_failed` 现在除 trace 的结果（invalid 与 unbound）外行为相同，可以再看是否合并。

# 第六批：Router 与 Engine 不再读取观测自带的实体

- 起因：用户问 Router 为什么要用实体。核对后更正了一个说法：寻址的融合并不把"说话的人"和"在看谁的脸"对上，证据只按语音段、观测或时间归到输入，没有语义证据时任意一张朝向 Avatar 的脸都会被采用；说话人实体在 Router 里只是附带的描述（`actors`、证据的 `speaker`），生产代码只在 `fusion.py` 按来源保留最新的视觉证据时读到它的来源。多人时的这个缺口按用户决定与同段多人一起记在 O-25，随多人问题在后续版本处理。
- 用户决定清理。Router 和 Engine 读取 `observation.entity` 的地方在生产中都只会读到空值：
  - 音频活动不再把原始音频观测的实体转发到语音帧、语音段和取消通知。
  - 轮次判断的输入窗口里，每段的主体只记来源和设备（`_subject`）。
  - 语义寻址的说话人只取 Persona 对语音段的关联（`entity_for_segment`），`_Transcript` 不再带实体。
  - 视觉寻址只用人脸标注里的实体，删除"只有一张脸且观测带实体"的分支。
  - Engine 的 `_decision_actors` 不再收集观测上的实体、也不再做它与关联的冲突检查，每段的参与者只来自 Persona 的关联。
- 测试改为通过 ParticipantRuntime 绑定语音段的关联（Persona 实际做的事）表示说话人：语义寻址的 `Speech.speak`、轮次判断与 host 链路的说话辅助函数不再给观测带实体；删除"观测实体与关联冲突"一例，"whoever they name"的几组参数随之合并。变异：Engine 对语音段改用设备解析、语义寻址的说话人不取关联，测试都失败。
- 下一步待用户确认：删除 Core 的 `EnvObservation.entity`（及语音帧、语音段等构造函数的参数）。

# 第七批：删除 Core 的 `EnvObservation.entity`

- 用户确认后删除：`EnvObservation` 的 `entity` 字段、`_create` 的参数和 `to_dict` 的输出（各个按种类的构造函数都转交给 `_create`，随之不再接受它）。元数据里保留 `entity_id` 为保留字段，观测仍不能借元数据冒充实体。
- 第六批之外还有两处在传递它，一并删除：Router 的语音转写把语音段的实体带进转写和"转写不可用"观测（`_SegmentState.entity`），Engine 为文字、图片直接输入解析参与者时传入观测的实体。
- 一段语音的实体现在只来自 Persona 的关联，一张脸的实体只在人脸标注里；`identifiers-zh.md` 的 `entity_id` 一行写明了这一点。
- 测试在第五、六批已不再给观测带实体，本批没有改测试；全量测试 725 个通过，ruff、format、`git diff --check` 通过。

# 第八批：人脸检测结果的契约移到 Persona

- 用户的要求：把 `agents/avatar/vision/schemas/face_detection.py` 移到 `agents/persona/schemas/`。它定义的是 Persona 人脸处理器发布的 FACE_DETECTION 标注（`FaceDetectionResult`、`FaceDetection`、`FaceKeypoints5`、`ImagePoint2D`），只依赖 Core；`avatar/vision` 留下的 `VisualSelection`、`VisualFrameSelector` 是 Context 为模型输入挑选画面用的，与它无关。
- `agents.persona.schemas` 导出这四个类型，`agents.avatar.vision` 不再导出；Persona 人脸处理器、Router 视觉寻址的处理器与朝向估计、Persona 测试改从 `alphaavatar.agents.persona.schemas` 导入。
- 移动时用了 `git mv`，它把重命名暂存了，违反"改动都留在未暂存的工作区"；随即用 `git reset -- <两个路径>` 撤回，工作区保持移动后的状态。
- 工作区结构检查、ruff、format 通过；全量测试 725 个通过。

# 第九批：人脸跟踪的向量取各帧的平均

- 原来每条跟踪只记第一帧的向量，之后不再更新；说话人在 KD-42 已改为按时长加权平均。用户决定人脸也取平均，每帧权重相同（人脸没有可作权重的时长）。
- `FaceTrack.face` 改为 `WeightedMean`：新跟踪以第一帧开始，之后每帧以权重 1 加入；同一帧里所有脸都对着这一帧之前的跟踪打分，打分之后才加入。Persona README 补上人脸跟踪的说明（跨来源和代、不限数量、`face.max_face_caches` 只限属性缓存、向量取各帧平均）。
- 新增 `test_a_face_track_is_the_mean_of_the_frames_it_took`：脸依次转到 0°、45°、60°、-10°，始终是同一条跟踪。只记第一帧（60° 那帧余弦 0.5）、只记最新一帧（-10° 对 60° 余弦 0.34）两处变异都失败。

# 第十批：保存人脸向量（KD-40）

- 改之前：会话中每次身份那一步都按 0.95 旧 / 0.05 新合并人脸向量（前几帧占大头）；保存时整份替换用户存储的人脸向量；同一用户的几个参与者各自写入，留下哪一个不固定。
- 与说话人的 KD-42、KD-38、KD-39 相同：
  - 会话中的人脸向量改为身份那一步所取各帧的平均（`DefaultPersonaCache._face`，`WeightedMean`，每帧权重 1）。agents 契约 `PersonaCache` 的 `face_vector` setter 改为 `add_face_vector(vector)`，人脸处理器随之改用它。
  - 保存规则抽成模块级的 `_saved_vector(session, stored, read=, beta=)`，说话人与人脸共用（起初写成类里的 `_saved`，放在了属性之间，不符合编码规范的类内顺序；被属性调用的辅助函数改为放在类之前）：载入的是同一身份时按 `beta`（`FACE_BETA` 0.95，注释写明含义）合并，没有存储的向量时用会话向量，载入没有完成时不写。`saved_face_vector` 由存储写入；写入副本 `_BaseProfile.vectors_only()` 同时保留存储的说话人和人脸向量。
  - `PersonaRuntime.save()` 对 `voice` 和 `face` 都按用户合成一份。
- 测试：说话人的三个保存测试扩为说话人、人脸各一组并改为不指明传感器的名字（`docs/bugs-zh.md` 的 KD-38、KD-39 随之更新），测试替身可以给出存储的人脸向量。6 处变异全部被发现：保存时直接用会话向量、存储写会话向量、参与者不合并人脸、会话人脸改回逐帧滑动合并、写入副本丢掉会话人脸、写入副本丢掉存储的人脸向量。其中两处起初存活：人脸每帧等权时，测试数据里第一个参与者两帧的平均恰好与第二个参与者那一帧同方向，换成不同方向后都失败。
- `docs/bugs-zh.md` 的 KD-40 移到已修复；Persona README 补上人脸向量的会话平均与保存规则。

# 第十一批：会话结束时按用户合并 Persona 缓存

- 用户的要求：在 Persona `runtime.py` 提供一个函数，把同一 `user_id` 的几个缓存合并、去重成一个，在 `on_stop` 里用它刷新 `self._persona_cache`，让 Profiler 更新资料和保存都变简单。
- 改之前：Profiler 在自己的 `stop(finalize=True)` 里对每个参与者的缓存各提取一次资料；同一用户的几个参与者各提取一次、各写入一次。保存时再把同一用户的声纹、人脸向量临时合成一份（第十批），资料各写各的，靠向量库按字段合并。
- 用户确认的顺序（`PersonaRuntime._close`）：
  1. 停止全部处理器；
  2. 取消在途的载入；
  3. `_merge_caches()` 让每个用户只剩一个缓存；
  4. 对停止成功的处理器按原顺序调用 `finalize_caches()`；
  5. `save()`，每个用户写入一次。

  只有正常结束（`finalize`）才做第 3～5 步。
- 合并规则：
  - `DefaultPersonaCache.absorb(other)`：只接受同一用户的缓存，否则报错。
  - 保留下来的缓存属于该用户最早加入、身份仍被接受的参与者。没有用户或身份不被接受的缓存原样保留，保存时照旧跳过。
  - 轮次按 `turn_id` 去重，按提交时间排序。
  - 观测到的资料逐字段用 `merge_profile_field` 合并，与 `profile` 属性合并载入资料的方式相同；时间取较晚的，`detail_operations` 接在后面。
  - 声纹和人脸用 `WeightedMean.extend` 合并。
  - 载入：保留的缓存没有完成载入、另一个完成了时，取对方的载入和运行状态。
  - 登录时间取最早的。
- 其他改动：
  - agents 契约：`PersonaProcessorBase.finalize_caches()` 默认不做任何事；`PersonaBase.save()` 去掉 `user_id` 参数。它在仓库里没有调用方，带它时的 `PermissionError` 分支一起删除。
  - `save()` 遍历合并后的缓存，删除第十批按用户合成声纹、人脸向量的那段代码。
  - Profiler：`_stop` 只停消费者并收完剩下的轮次；提取移到 `finalize_caches()`，`_update_profile` 改为只接收缓存。
  - Doctor 测试替身的 `save` 签名随之修改。
  - Persona README 的生命周期一节写明合并与结束顺序；`docs/bugs-zh.md` 的 KD-39 补记本批，并更新回归测试的名字。
- 测试：
  - 改了两个：
    - 提供方吞掉取消的测试改为在 `stop` 之后取消 `finalize_caches()`；
    - 同一用户多个参与者的保存测试改名为 `test_participants_of_one_user_save_once_with_all_they_were_observed`，alice 只写入一次。
  - 新增两个：
    - `test_a_users_caches_merge_into_one_holding_all_they_observed`：资料按来源优先、同来源取较晚的；载入、运行状态与最早登录；声纹均值；不同用户报错。
    - `test_a_users_participants_are_profiled_and_saved_once_with_all_their_turns`：后加入的参与者先说话，一个轮次同属两人；每个用户只提取一次，轮次不重复、按提交顺序；每个用户写入一次，带着提取出的名字。
  - 13 处变异全部被发现：
    - 缓存：不取对方的载入、不取对方的运行状态、不取最早登录、轮次不排序、轮次不去重、均值不合并、资料直接覆盖、字段集合不合并；
    - 运行时：不合并、保留最后加入的参与者、不调用 `finalize_caches`、先保存后提取；
    - Profiler：不提取。
- 验证（离线）：
  - 工作区结构检查、ruff、format、`git diff --check` 通过。
  - 全量测试 736 个，735 个通过。失败的 `test_late_stt_final_after_transcript_timeout_never_revives_the_input[listening0]` 是之前见过的 Router 计时用例，与本批无关，单独重跑 5 次都通过。

# 第十二批：Memory `_identity_sequence` 改为 `_session_sequence`

- 待办第 5 项。Memory `state.py` 的会话上下文里，这个字段存的是 `sync_identity` 读到的会话快照序号（`SessionSnapshot.sequence`），再写进 `MemoryIdentitySnapshot.sequence`；它不是参与者的身份版本，改名后不再和 `identity_revision` 混淆。
- 只改这个私有字段的三处，按词边界替换；仓库里没有别的引用，行为不变。
- 验证（离线）：Memory 的 ruff、format 通过，Memory 测试 30 个通过；`git diff --check` 通过。没有重跑全量测试。
- 待办 1～5 项至此都已完成。

# 第十三批：删除 `candidate_count`

- 用户的目标：人脸按离摄像头由近到远排序，主参与者默认绑定最近的那张脸，以减少噪声。本批是第一步，按用户的判断删除多余的 `candidate_count`；排序留到下一批。
- 改之前：人脸处理器把整帧检测到的人脸数（`len(faces)`，包括没有向量、不会被跟踪的脸）作为 `candidate_count` 传给 `ensure_entity`，再放进 `AssociationRequest`。`PrimaryParticipantIdentityPolicy` 只在它等于 1 时把人脸交给主参与者。因此主参与者的摄像头里一帧有两张以上的脸时，没有一张交给主参与者，每张都成为新参与者；之后设备上已有别的参与者，主参与者再也得不到人脸。说话人一直传默认值 1。
- 删除：
  - Core `AssociationRequest.candidate_count` 字段及其校验；
  - `ParticipantRuntime.ensure_entity` 的同名参数、校验和转交；
  - 策略里 `candidate_count != 1` 这一条；
  - 人脸处理器 `_participant_for` 的参数。

  策略的其余条件不变：设备属于主参与者、主参与者还没有这一类实体、设备上没出现过别的参与者。
- 现在一帧的几张脸里，最先处理的那张交给主参与者，其余成为新参与者。最先处理的是检测器给出的第一张，还不是最近的那张；下一批排序后才是最近的那张。`identifiers-zh.md` 写的"主参与者设备上的第一个人脸实体交给主参与者"与此一致，没有改。
- 测试：
  - 原来没有测试覆盖"多张脸不交给主参与者"，删除后全量测试照旧。
  - 新增 `test_a_frame_of_several_faces_fills_the_primary_participant_with_one`：用 Host 装配的 `PrimaryParticipantIdentityPolicy`，主参与者的摄像头一帧出现两张脸，一张属于主参与者，另一张属于新参与者。为此测试辅助函数 `avatar_runtime` 可以传入身份策略。
  - 把四个文件换回 HEAD 的版本后，这个测试失败（主参与者得到 0 张脸）。
- 验证（离线）：
  - ruff、format、`git diff --check` 通过。
  - 删除后全量测试 736 个，735 个通过，失败的仍是 Router 计时用例 `test_late_stt_final_after_transcript_timeout_never_revives_the_input[listening0]`。
  - 新增测试后，Persona、参与者和 Core 的测试 182 个通过。

# 第十四批：一帧的人脸由近到远排序

- 用户决定：只排序，不要求最近的一张比第二张明显更大。讨论时确认过，若加差距而差不多近的那帧不交给主参与者，这一帧的脸照样会成为新参与者，设备也已出现过别的参与者，主参与者在会话内再也得不到人脸（`_association_devices` 只在 `ParticipantRuntime` 关闭时清空）。
- 改之前：检测器按检测分数给出人脸，`faces[: max_faces]` 留下的是分数最高的；第十三批后，主参与者拿到的是检测器给出的第一张。
- 改动：
  - 人脸处理器在 `faces[: max_faces]` 之前，用模块级的 `_face_area` 按人脸框面积从大到小排序（近大远小）。没有框的脸面积为 0，排在最后。
  - 标注、跟踪、身份检索都按这个顺序：超过 `max_faces` 时不跟踪的是最远的脸，近的脸先做身份检索，主参与者设备上的新脸由最近的那张交给主参与者。
  - 跟踪的匹配与顺序无关（每张脸都对着这一帧之前的跟踪打分）；Router 的视觉寻址遍历全部人脸，也不依赖顺序。
  - `max_faces` 加注释。Persona README 补上排序规则。`identifiers-zh.md` 的主参与者规则补上"取人脸框最大的那张"和"设备上出现过别的参与者后不再交给主参与者"，第十一批没更新的 KD-39 那句也一并改为"会话结束时合并为一个缓存"。`docs/bugs-zh.md` 的 O-25 记下两人离摄像头差不多远时交给谁不确定，随多人问题处理。
- 测试：
  - 测试替身可以给每张脸指定框的边长（`face_sizes`）。
  - 第十三批的测试收紧为 `test_a_frame_of_several_faces_fills_the_primary_participant_with_the_nearest`：检测器先给出较远的 alice，较近的 bob 属于主参与者，并且先做身份检索。
  - 新增 `test_past_max_faces_the_farthest_faces_of_a_frame_are_not_tracked`：`max_faces=1` 时只跟踪、检索较近的那张，较远的那张留在标注里、没有实体。
  - 三处变异都被这两个测试发现：不排序、由远到近、截取之后才排序。没有框的脸排在最后这一条没有单独的测试。
- 验证（离线）：ruff、format、工作区结构检查、`git diff --check` 通过；全量测试 738 个全部通过。

# 第十五批：人脸评估第一步——协议与下载范围

- 用户的要求：参照声纹评估，先比较人脸向量模型的区分能力（基线 buffalo_l `w600k_r50`，设备端候选 OpenCV SFace FP32，视结果再测 INT8 与 YuNet + SFace），再在完整画面中校准链路的三个阈值（跟踪、margin、身份检索），规则照搬 R1、R2。默认模型、生产阈值和发布方式由用户决定。
- 评估代码：`dev/v0.6.9` `61eb8294`，工作区无改动。材料在 `/home/ecs-user/alphaavatar-face-eval/`（不随仓库提供）：协议草稿 `protocol/v1.md`（未冻结），脚本 `harness/inventory.py`、`harness/select_split.py`，清单 `manifests/`，模型 `models/`。
- 数据：本机 HF 账号 `AlphaAvatar` 已能读取门控数据集 `ProgramComputer/voxceleb`（revision `547dfb16`）。只读了 `vox2_meta.csv` 和各 mp4 zip 的目录（共 1,128,246 段，deflate 压缩，中位 189 KB），没有下载媒体。
  - 按 seed 选出：校准用 dev 150 人（男女各 75），共 1,348 段，约 300 MB；独立测试用官方 test 全部 118 人，共 1,075 段，约 245 MB。
  - 每人一段原始视频注册，另 4 段原始视频探测。
- 模型来源都已固定并记下哈希：
  - `buffalo_l.zip` 取自 InsightFace GitHub release v0.7，SHA256 `80ffe37d…ca2f`，大小与代码里的 `archive_size` 一致。生产缓存中的 `w600k_r50.onnx` 与包内文件哈希相同。
  - SFace 与 YuNet 取自 OpenCV 的 HF 仓库（`3d708243`、`3cc26e7f`），文件哈希与 LFS 记录一致。
  - 许可：buffalo_l 的检测、识别、年龄性别模型都只限非商业研究（InsightFace README；商用需联系 InsightFace）；SFace 是 Apache-2.0；YuNet 是 MIT。
  - 训练数据：SCRFD 用 WIDER FACE，`w600k_r50` 用 WebFace600K，年龄性别用 CelebA；SFace 未说明（论文用 CASIA-WebFace、VGGFace2、MS-Celeb-1M）。
  - VoxCeleb2 的身份取自 VGGFace2，评估身份与训练数据可能重叠，见协议第 2 节。
- 第三阶段需要完整画面。VoxCeleb2 的裁脸片段不适用；AMI 会议视频（CC BY 4.0，多摄像头，同一组人跨会议）可以下载，每路约 50～70 MB，待用户决定，另需同意录制的专门场景。
- 下一步：用户确认协议后冻结；然后下载选中的段、抽帧、检测、提取两种向量，计算第二阶段结果。

## 第十五批（续）：协议冻结、下载与 FP32 对照

### 协议冻结

- 用户确认口径后补完 `protocol/v1.md` 并冻结：2026-11-15T11:20:30Z，sha256 `bf337905aa9d54a88946ee4bd7679a11ee6f050754a5aea5322b34b816255dd7`。`protocol/frozen.txt` 同时记下：
  - 代码 `61eb8294`；
  - 数据 `ProgramComputer/voxceleb@547dfb16`；
  - 划分清单 `split-v1.json`（`312c8e8d…`）和模型清单 `models.json`（`0cd390d7…`）。
- 补进协议的口径：
  - 主要工作点：五人库陌生人误认 ≤1%，每个模型在 dev 上独立取阈值后用于 test。
  - 探索性读数：≤0.1% 和配对 FAR 10⁻⁴。
  - 分开报告三类错误：陌生人被认成已注册、已注册被认成另一人、已注册被拒识。每个数都给次数、分母，以及按身份整群的 bootstrap 区间。
  - 低清晰度：既报告同一批通过检测的脸，也报告计入漏检后的整体结果。
  - 偏航角：沿用正常画面的估计。
  - 筛选判据：5 个百分点。
  - 附录 A 写定第三阶段的场景：AMI 按录制系列整体划分；需要参与者同意录制的场景单独列出。
- 画面放在 640×480 的中灰画布中央：224 px 的裁脸片段直接送检测会被放大到 640，与摄像头画面不符。
- dev 阈值在计算 test 之前写入 `results/thresholds-dev.json`，哈希 `9bcc7c44…` 补记在 `frozen.txt`。
- 冻结后只有一处补充，记在 `protocol/changes.md`：延迟测试另记加载模型前后常驻内存之差。只看进程峰值时，导入 InsightFace 就到了 765 MB，看不出小模型的占用。

### 下载与提取

- 先单独取一段（`dev/mp4/id00018/b5WWyS25FAw/00098.mp4`，压缩后 305,659 B）：收到 306,201 B，网卡计数 387,788 B（含 HTTPS 开销）；解压后大小和 CRC32 都对。
- 全部 2,423 段：有效载荷 546.3 MB（压缩数据 545.0 MB），网卡计数 619.4 MB，用时 201 s，落盘 538 MB。整个评估目录 1.8 GB。
- 核对：SCRFD 的五点顺序与 YuNet 逐点一致，可以直接按 YuNet 的格式交给 SFace 的 `alignCrop`；`1k3d68` 的输出依次是 pitch、yaw、roll。
- 提取：8 个进程各用 1 线程，共 77,510 帧（dev 42,699，test 34,811），用时 2.8 小时。
  - 漏检很少：正常条件 dev 39 帧、test 7 帧；低清晰度 dev 11 帧、test 32 帧。VoxCeleb2 的片段都以人脸为中心，检测几乎没有受到考验。

### 结果（test，dev 冻结的阈值；完整表格在 `results/phase2-report.md`）

dev 阈值：

| 模型 | 1% 工作点 | 0.1% | 配对 FAR 10⁻⁴ |
|---|---|---|---|
| buffalo_l | 0.1975 | 0.266 | 0.282 |
| SFace FP32 | 0.3915 | 0.461 | 0.4745 |

test 共 23 个五人随机户。陌生人检索 766,467 次，已注册检索 26,577 次。

| 1% 工作点 | 陌生人被认成已注册 | 已注册被认成另一人 | 已注册被拒识 | 已注册正确识别 |
|---|---|---|---|---|
| buffalo_l | 12,403（1.62%，1.32～1.95） | 5（0.02%，0.00～0.06） | 273（1.03%，0.23～2.43） | 26,299（98.95%，97.50～99.78） |
| SFace FP32 | 12,826（1.67%，1.36～2.02） | 20（0.08%，0.00～0.21） | 978（3.68%，2.09～5.47） | 25,579（96.24%，94.49～97.78） |

| 分组（已注册正确识别 / 陌生人误认） | buffalo_l | SFace FP32 |
|---|---|---|
| 正脸 <20°（13,031 帧） | 99.18% / 1.62% | 97.30% / 1.40% |
| 侧脸 20～45°（11,348） | 98.72% / 1.61% | 96.02% / 1.85% |
| 大侧脸 ≥45°（2,198） | 98.82% / 1.68% | 91.17% / 2.35% |
| 低清晰度：同一批脸 26,559 帧，正常 → 退化 | 98.95% → 98.78% | 96.24% → 95.11% |
| 低清晰度、大侧脸（2,184） | 98.58% / 1.77% | 86.90% / 2.64% |
| 女：陌生人误认 | 1.77%（261,360 次） | 2.73% |
| 男：陌生人误认 | 1.54%（505,107 次） | 1.13% |

- 计入漏检后，正常条件的正确识别 buffalo_l 98.94%、SFace 96.23%；退化条件 98.71%、95.05%。
- 探索性读数（test）：

  | 读数 | buffalo_l | SFace FP32 |
  |---|---|---|
  | 0.1% 工作点：正确识别 / 陌生人误认 | 98.15% / 0.13% | 90.38% / 0.18% |
  | 配对 FAR 10⁻⁴ 的 TAR | 97.87% | 88.45% |
  | 五人难户：被认成另一人 | 7/25,676（0.03%） | 88/25,676（0.34%） |
  | 会话级：陌生人至少被认成一次（23,677 个"片段 × 户"） | 2,221 | 2,316 |
  | 会话级：已注册至少被认错一次（818 段） | 2 | 3 |

- **判据**：
  - `SFace − buffalo_l` 的正确识别率差值为 −2.71 pp，按身份 bootstrap 区间 −3.98～−1.57 pp，没有跨过 −5 pp（dev 上为 −3.10 pp）。
  - 但两个模型的 test 陌生人误认都超过 1%（1.62%、1.67%），按冻结的判据标为**待复验**。
- 延迟与内存（单张脸，batch 1；Xeon 6982P-C，onnxruntime 1.23.1 CPU，OpenCV 4.11.0 DNN）：

  | 模型（后端） | 1 线程中位 | 4 线程中位 | 加载运行后增加的常驻内存 |
  |---|---|---|---|
  | det_10g（ORT） | 217 ms | 65 ms | 137～142 MB |
  | w600k_r50（ORT） | 246 ms | 65 ms | 436～450 MB |
  | SFace（OpenCV DNN） | 21 ms | 7.7 ms | 87 MB |
  | SFace（ORT） | 18 ms | 11 ms | 134 MB |

  SFace 在两种后端上的向量一致，余弦 0.99999994。

### 主要失败场景

1. **阈值迁移到新人群后误认偏高**：在 dev 上取 1% 的阈值，到 test 的身份上两个模型都变成约 1.6%。两者同样偏高，所以模型比较仍然成立；但生产阈值不能只按一个人群取，需要留余量或换更多样的数据。
2. **逐帧检索的累积**：在 1% 的单帧工作点上，约 9.4% 的陌生人片段在一个户里至少被认成一次。生产每帧都检索，单帧误认必须远低于这个工作点。生产的 0.45 比这里所有的工作点都严，链路上的实际效果留给第三阶段量。
3. **SFace 在大侧脸和低清晰度上下降明显**：大侧脸正确识别 91.2%，叠加低清晰度后 86.9%（拒识 13%）；buffalo_l 都在 98.5% 以上。
4. **SFace 的性别差异**：同一阈值下女性陌生人误认 2.73%，男性 1.13%；buffalo_l 是 1.77%、1.54%。
5. **SFace 对相似的人区分较弱**：五人难户中被认成另一人 0.34%，buffalo_l 是 0.03%。
6. **工作点越严，差距越大**：0.1% 时正确识别差 7.8 个百分点，配对 FAR 10⁻⁴ 时 TAR 差 9.4 个百分点。

### 局限

- VoxCeleb2 的身份取自 VGGFace2，很可能与两个模型的训练数据重叠，绝对值偏乐观。
- 裁脸片段没有考验检测，多人同框、远处小脸和真实摄像头都没有覆盖。
- 低清晰度是合成的。
- 只在一台 x86 服务器 CPU 上测，没有测移动设备。
- 同一段的相邻帧相关，区间按身份整群处理。

### 下一轮建议（由用户决定）

- 按判据，SFace FP32 标为待复验：1% 工作点上差距在 5 个百分点以内，但实际误认率超标。生产需要更严的工作点，在那里 SFace 落后 8～9 个百分点，侧脸、低清晰度、女性陌生人和相似的人这几处更弱。
- 它的优势在部署：识别快约 12 倍（1 线程 21 ms 对 246 ms），常驻内存约为五分之一（87 MB 对 约 440 MB），许可是 Apache-2.0；buffalo_l 只限非商业研究。
- 如果目标是可商用或移动设备：
  - INT8 和 YuNet 可以继续测。INT8 不用重新检测，用已存的框和五点在原帧上重新对齐即可，成本很低。
  - 但 INT8 一般不会比 FP32 准，所以更值得做的是扩大可商用候选的范围。
- 如果目标只是这一版的识别效果，建议第三阶段直接用 buffalo_l 校准链路的三个阈值。

### 其他（本批期间）

- 用户确认后，删除了 HF 上的旧仓库 `AlphaAvatar/plugins-persona`。
  - 两个分支里的模型文件与新仓库固定的 `model.onnx` 哈希相同，近 30 天下载 0。
  - PyPI 上 `alpha-avatar-plugins-persona` 0.5.4～0.6.6 从这个仓库下载说话人模型，首次安装会失败；用户接受。
- `persona-speaker-attribute-onnx` 的 README 改为说明原仓库已删除，提交 `72f6fcc0`，模型文件未动。

# 第十六批：严格工作点、AuraFace 与第三阶段的数据（进行中）

- 用户看过第一轮后决定：第三阶段用 buffalo_l 跑完整链路，SFace FP32 用同一批素材对照；暂缓 INT8，YuNet 单独做检测对照；补测 AuraFace-v1 的识别精度。
- **严格工作点在 test 上的实际误认率**（`harness/strict_points.py`；`changes.md` 记为补充读数，不改变冻结的阈值和判据）：

  | 工作点（dev 冻结） | 五人库陌生人误认：buffalo_l | SFace | 配对 FAR：buffalo_l | SFace | 正确识别：buffalo_l | SFace | 差值（区间） |
  |---|---|---|---|---|---|---|---|
  | 0.1% | 991/766,467（0.129%） | 1,417（0.185%） | 793/3,182,283 | 1,084 | 98.15% | 90.38% | −7.77 pp（−10.63～−5.48） |
  | 配对 FAR 10⁻⁴ | 489（0.064%） | 858（0.112%） | 401（1.26×10⁻⁴） | 638（2.0×10⁻⁴） | 97.83% | 88.60% | −9.23 pp（−12.21～−6.84） |

  - 在这两个工作点上，SFace 的误认率更高，识别率也更低。
  - 在 test 上直接取阈值、让两者误认率相同（事后读数，只作说明）：
    - 1% 时差 −3.66 pp（−5.43～−2.22，跨过 −5 pp）；
    - 0.1% 时差 −9.77 pp；
    - 0.01% 时差 −16.78 pp（SFace 拒识 20.6%）。
- **AuraFace-v1**（`fal/AuraFace-v1@af6d057c`）：
  - 识别模型 `glintr100.onnx` 仓库标为 Apache-2.0，训练数据称"商业数据集"，无法核实。它与 InsightFace antelopev2 的同名文件不是同一个文件（大小和 CRC32 都不同）。
  - 同一仓库里的检测、年龄性别、关键点文件与 InsightFace buffalo_l 的文件哈希相同，原始许可仍是只限非商业研究。
  - 附录 B 已在计算前冻结（`v1-addendum-auraface.md`，sha256 `a79dcac6…`）：沿用全部帧、框、五点、户和判据；低清晰度的五点重新检测，并要求框与已存的一致。
  - 重建核对：抽 20 段，在重建的画布上重算 buffalo_l 向量，与已存向量的最小余弦为 0.999999821。提取在后台运行中。
- **AMI 视频**（CC BY 4.0，语料与标注同一许可）：
  - 公开标注里有 35 个系列、140 人，没有人出现在两个系列中，所以按系列划分也就是按人划分。`meetings.xml` 给出每人的近景摄像头和全局编号。
  - 默认视频是 352×288：近景人脸 58～88 px，房间视角的人脸只有 5～36 px，全部低于 48 px 门限。
  - 原始的 `_orig.avi` 是 720×576 DivX，每路 350～455 MB。IDIAP 的 L、R 视角上人脸约 50～75 px，刚过门限；ES 的 Corner、TS 的 Overview 仍只有 10～39 px。
  - AMI 适合跨会话的单人识别（近景），以及少量小脸的多人同框（IDIAP L/R 原始视频）；旁人先靠近、遮挡、离开再入镜、主用户坐得更远这些场景，需要专门录制。
- **观察（未改）**：`FaceAnalysisRunner` 没有设置 onnxruntime 的线程数，用的是 InsightFace 的默认值（物理核数）；说话人的两个 runner 限制为 min(CPU/2, 4)。在核数少的设备上，人脸检测会占满全部核心；第三阶段会在生产配置下实测丢帧。

## 第十六批（续）：三个模型的对比与阈值

- 用户把本轮限定为模型对比和阈值校准，专录和完整 Avatar 链路的验收移出本轮。
- 附录 C（`v1-addendum-thresholds.md`，sha256 `9532a85d…`）在计算前冻结，内容：
  - 三模型的帧级对比，加 buffalo_l 生产阈值 0.45 作对照；
  - 按会话选身份阈值，照搬 R1、R2，绑定方式与生产相同：首帧过阈值即绑定，低于阈值不解绑，匹配到别人就改绑；
  - 跟踪阈值和分差用生产的 `FaceTracks` 回放。会话分三种：单人、两人先后、两人同框。
- 每一步都先在 dev 上选点、记下哈希，再计算 test。
- 冻结后的说明与偏离都记在 `changes.md`：
  - AuraFace 阈值文件里一个字段名取错；
  - 取舍曲线是事后读数，不用于选点；
  - 跟踪的冻结规则选出了错合并更多的点，因此另加一个规则之外的候选："dev 上错合并为 0 的最小阈值，分差保持 0.08"，在看 test 之前写入。
- AuraFace 的 dev 阈值：1% 工作点 0.326，0.1% 为 0.397，配对 FAR 10⁻⁴ 为 0.4155。
  - 它明显弱于 SFace：0.1% 工作点上正确识别 78.97%（buffalo_l 98.15%，SFace 90.38%）；在 test 上取阈值、使误认率相同时，差距为 −19.45 pp。
  - 核对过预处理：输入归一化、112 尺寸、通道顺序都按模型卡，重算的向量与已存的一致。模型卡自己公布的 CFP-FP 95.2%、CPLFW 90.9% 也偏低，与这里一致。
- 汇总表见 `results/summary-round2.md`（标"事后"的读数只说明取舍）：

  | 模型 | 身份阈值 | 陌生人会话误绑 | 已注册至少一次正确 | 按帧绑对 | 帧级拒识 |
  |---|---|---|---|---|---|
  | buffalo_l 0.275（冻结规则） | 0.275 | 319/25,990（1.23%） | 99.35% | 99.01% | 2.0% |
  | buffalo_l 0.35（事后） | 0.35 | 20（0.08%） | 98.70% | 98.22% | 5.5% |
  | buffalo_l 0.40（事后） | 0.40 | 3（0.01%） | 97.17% | 96.83% | 9.8% |
  | buffalo_l 0.45（生产） | 0.45 | 0 | 94.13% | 92.92% | 17.0% |
  | SFace 0.48（冻结规则） | 0.48 | 380（1.46%） | 97.17% | 96.05% | 12.2% |
  | SFace 0.52（事后） | 0.52 | 101（0.39%） | 94.35% | 92.45% | 19.4% |
  | AuraFace 0.415（冻结规则） | 0.415 | 282（1.09%） | 93.48% | 92.49% | 24.6% |
  | AuraFace 0.43（事后） | 0.43 | 159（0.61%） | 92.61% | 90.73% | 27.5% |

  | 跟踪（test） | 单人最大跟踪占比 | 先后两人错合并（随机 / 相近） | 同框错合并 |
  |---|---|---|---|
  | buffalo_l 0.225 / 0（冻结规则） | 99.8% | 1/472 / 12/472 | 0 |
  | buffalo_l 0.30 / 0.08（dev 错合并为 0） | 99.8% | 0 / 1/472 | 0 |
  | buffalo_l 0.65 / 0.08（生产） | 89.2% | 0 / 0 | 0（未分配 3.1%） |
  | SFace 0.55 / 0.08（dev 错合并为 0） | 98.7% | 0 / 1/472 | 0 |
  | AuraFace 0.475 / 0.08（dev 错合并为 0） | 96.4% | 0 / 0 | 0 |

- 耗时（单张脸，batch 1；Xeon 6982P-C），检测 det_10g 每帧另需 217 ms（1 线程）/ 65 ms（4 线程）：

  | 模型（后端） | 1 线程 | 4 线程 | 常驻内存增加 |
  |---|---|---|---|
  | w600k_r50（ORT） | 245 ms | 65 ms | 462 MB |
  | SFace（OpenCV DNN） | 21 ms | 7.6 ms | 85 MB |
  | SFace（ORT） | 18 ms | 11 ms | 138 MB |
  | AuraFace glintr100（ORT） | 152 ms | 42 ms | 764 MB |

- 结论交给用户决定：
  - **模型**：buffalo_l 在所有精度读数上最好。误认风险相近（会话误绑约 0.4%）时，至少一次正确 buffalo_l 约 99%、SFace 94.3%；AuraFace 在 0.61% 误绑下只有 92.6%。SFace 的优势只在部署和许可；AuraFace 精度最低、内存最大，训练数据无法核实，不推荐。
  - **buffalo_l 身份阈值**：冻结规则选出的 0.275 到 test 上陌生人误绑 1.23%，不推荐。建议在 dev 合格区间内取 0.40：误绑 0.01%，至少一次正确 97.2%，帧级拒识 9.8%。如果要求陌生人零误绑，保持 0.45：至少一次正确 94.1%，拒识 17%。实际会话比这里的 20 秒长，检索次数更多，误绑会累积，所以不建议低于 0.35。
  - **跟踪阈值**：生产的 0.65 / 0.08 在单人会话里有 10.8% 的帧不在最大跟踪中。回放显示 0.30～0.50 / 0.08 几乎没有错合并，分裂可降到 1% 以下。但会话短、同框是拼合的，没有遮挡和离开再入镜，标为**待验证**。
- 局限：VoxCeleb2 身份很可能与训练数据重叠（SFace 若用了 VGGFace2，则一定重叠）；会话最长 20 秒；低清晰度是合成的；只在一台 x86 CPU 上测。

## 第十六批收尾：用户的决定与补充读数

- 用户决定：模型继续用 buffalo_l；本轮阈值校准收尾。
  - **生产人脸身份匹配阈值从 `0.45` 调到 `0.40`**。跟踪 `0.65 / 0.08` 不变，标为待验证。
  - 0.40 是根据本批回放选出的：看过 test 后，在 dev 合格区间 0.275～0.465 内选的，不是冻结规则选出的点。之后要在独立数据上按 0.40 原样验证。
  - 用户接受的取舍：两档阈值都没有观察到已注册用户被认成另一人；0.40 把至少一次认对从 94.1% 提到 97.2%，帧级拒识从 17.0% 降到 9.8%，代价是陌生人会话误绑从 0/25,990 增到 3/25,990。0.45 的零次误绑也只是这批样本上的观测。
  - SFace 和 AuraFace 暂时都没有替换的依据。
- 生产改动：`avatar-agents/alphaavatar/agents/constants.py` 的 `FACE_MATCH_THRESHOLD` 由 0.45 改为 0.40，并按 `SPEAKER_MATCH_THRESHOLD` 的写法加注释，说明它是 buffalo_l `w600k_r50` 向量的余弦。人脸处理器的检索和身份请求的理由文字都引用这个常量，没有别处写死 0.45；文档里没有写这个数值。
- 补充读数（`harness/misidentified.py`，用已有向量）：
  - buffalo_l 在 0.40 和 0.45 下，已注册者被认成另一位已注册者：会话 0/460（正常和低清晰度都是），帧 0/26,577（正常）、0/26,559（低清晰度）。
  - 同样的阈值换成五人难户（同性别、最相近的人，22 户），会话 0/440，帧 0/25,676。所以"至少一次认对"和"曾经认错"在 buffalo_l 上没有同时发生过。
  - SFace（低清晰度，0.48 时 2/460、0.52 时 1/460）和 AuraFace（低清晰度 1/460）有少量会话两者同时发生。
- 口径（已写进 `results/summary-round2.md`）：
  - **按帧绑对**：分母是已注册会话的全部帧 26,581（含没检测到人脸的 4 帧），分子是处理完该帧后绑定为本人的帧，绑定会延续。
  - **帧级拒识**：分母是做了检索的帧 26,577，分子是该帧自己的检索 top-1 低于阈值的帧。
  - 0.40 时两者是 25,738/26,581（96.83%）和 2,613/26,577（9.83%），0.45 时是 24,699（92.92%）和 4,524（17.02%）。相加超过 100%，因为一帧可以被自己的检索拒识，同时仍处在之前的正确绑定上。

# 第十七批：Persona 的阈值与常量移出 agents

- 用户的要求：`agents/constants.py` 里只有 Persona 用到的常量，不放在 agents 层。按 AGENTS.md，处理器自己的设置跟着处理器走。
- 改动：
  - **身份阈值放进各自插件的配置**：`speaker.identity_match_threshold`（默认 0.6，CAM++ 向量的余弦）和 `face.identity_match_threshold`（默认 0.40，buffalo_l `w600k_r50` 向量的余弦），放在各自的跟踪阈值旁边，同一行注释说明是哪个模型的余弦。两个处理器的检索和绑定理由都改为读配置。理由：评估说明身份阈值随模型而变，0.40 和 0.45 之间也是部署时的取舍。
  - **保存权重留作 Persona 插件内的常量**：`SPEAKER_BETA`、`FACE_BETA` 移到 `cache.py` 模块级。它们是 PersonaRuntime 的存储规则，决定用户存储的向量更新得多快，没有校准过，不适合作为部署可调项。
  - **推理告警阈值留作人脸处理器的常量**：`FACE_INFERENCE_THRESHOLD`（1.0 秒）原样移到 `face/processor.py`，注释说明含义。之前已报告、未改：告警文字说"比实时慢"，但每 0.2 秒取一帧、队列缓冲 0.4 秒，0.2～1.0 秒之间已经在丢帧却不告警。
  - **用户追加：人脸取帧间隔放进人脸配置**：`face.sample_interval_sec`（默认 0.2，必须为正），替代 `VIDEO_PERSONA_INTERVAL_SEC`。它与已在配置中的 `face.frame_queue_sec` 一起决定帧队列长度，也是部署时要按 CPU 调的项（buffalo_l 的检测单线程每帧 217 ms）。配置要求为正之后，处理器里"间隔大于 0 才判断"的分支就不再需要，已删去。
  - `agents/constants.py` 删去这六个常量，不留别名。仓库里没有其他引用；Persona README 补上两个身份阈值和取帧间隔的说明。
- 测试：
  - 测试替身记录每次向量检索收到的阈值。
  - 新增 `test_each_sensor_searches_and_binds_with_its_configured_identity_threshold`（说话人、人脸各一）：配置 0.37 时，检索收到 0.37，绑定理由写的也是 0.37。四处变异都被发现：两个处理器的检索、绑定理由各改回写死的值。
  - 帧队列的配置测试扩为 `test_the_sampling_interval_and_frame_queue_take_positive_times_and_size_the_queue`；新增 `test_a_source_is_sampled_once_per_configured_interval`（间隔 1 秒时，0、0.5、1.2 秒三帧只分析两帧）。三处变异都被发现：取帧、队列长度改回固定的 0.2，去掉为正的检查。
  - 第二个测试起初让队列只放两帧，"取帧固定 0.2"的变异因为队列丢帧碰巧也得到两帧而存活；把队列加大到能放下全部三帧后被发现。
- 验证（离线）：ruff、format、工作区结构检查、`git diff --check` 通过；全量测试 741 个全部通过。
