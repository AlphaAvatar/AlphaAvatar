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
  - 保存规则抽成 `_saved(observed, loaded, beta)`，说话人与人脸共用：载入的是同一身份时按 `beta`（`FACE_BETA` 0.95，注释写明含义）合并，没有存储的向量时用会话向量，载入没有完成时不写。`saved_face_vector` 由存储写入；写入副本 `_BaseProfile.vectors_only()` 同时保留存储的说话人和人脸向量。
  - `PersonaRuntime.save()` 对 `voice` 和 `face` 都按用户合成一份。
- 测试：说话人的三个保存测试扩为说话人、人脸各一组并改为不指明传感器的名字（`docs/bugs-zh.md` 的 KD-38、KD-39 随之更新），测试替身可以给出存储的人脸向量。6 处变异全部被发现：保存时直接用会话向量、存储写会话向量、参与者不合并人脸、会话人脸改回逐帧滑动合并、写入副本丢掉会话人脸、写入副本丢掉存储的人脸向量。其中两处起初存活：人脸每帧等权时，测试数据里第一个参与者两帧的平均恰好与第二个参与者那一帧同方向，换成不同方向后都失败。
- `docs/bugs-zh.md` 的 KD-40 移到已修复；Persona README 补上人脸向量的会话平均与保存规则。
