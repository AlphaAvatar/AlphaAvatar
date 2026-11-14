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
