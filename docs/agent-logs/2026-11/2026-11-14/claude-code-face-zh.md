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
