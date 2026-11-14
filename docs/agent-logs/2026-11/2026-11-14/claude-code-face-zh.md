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
