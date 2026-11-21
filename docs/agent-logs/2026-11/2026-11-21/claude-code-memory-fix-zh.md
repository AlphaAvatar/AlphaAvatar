# Memory 修复：一轮未归属导致整批记忆只留在 context（KD-49）— Claude Code 日志

- 分支：`dev/v0.6.9`，基线 `b2b4af8b`（KD-49 的登记）；日期为 CST。
- 依据：用户 2026-11-21 的两次真实对话，记忆全部只写进了 `contexts/`；定位后登记为 [KD-49](../../../bugs-zh.md)，用户决定逐步修复。
- 范围：第一批只加诊断，并做 Router 侧的改名和删减，不改行为。改动留在工作区，由用户提交。

## 批次总览

| 批次 | 内容 | 日期 | 基线 HEAD | 提交 | 状态 |
|---|---|---|---|---|---|
| 第一批：诊断 | 每段关联结束、每轮准入、Memory 整批降级各记一行日志；Router 侧 `actors` 改为 `input_devices`，删掉判定上没人读的字段和从未被读取的 `InteractionAddressing` | 2026-11-21 | `b2b4af8b` | — | 待审查 |
| 第二批：方案 | Turn 不在准入时固定参与者；只写方案，不写代码 | — | — | — | 未开始 |

## 1. 问题

- 详见 KD-49。
- 两次单人对话各有一轮的 actor 为空，其余各轮都归属同一个已接受的用户。
- `capture_identity` 只要发现一轮对不上，就把整批标为未归属；`build_memory_items` 随之把整批对话记忆降为 `context`。
- 被动检索只看 `owner:*`、当前 episode 和当前 context，所以之后的会话都检索不到这些记忆。
- 空 actor 有三种来源：准入时 Persona 尚未完成关联、段没有声纹、声纹没匹配上跟踪。原有数据分不出是哪一种。

## 2. 已定的决定

- **命名**：
  - Turn 上的 `actors` 不改名：第二批会移除这个字段。
  - "这一轮有哪些参与者"用 participants 表示，作为根据观测解析出参与者的函数名，匿名段对应空。
  - Router 侧按用途叫 `input_devices`（用户定）。
  - 讨论过 `speakers`、`active_speaker`、`authors`：`speakers` 偏语音，体现不了多模态；active speaker 在 LiveKit 等实时通话里指"此刻正在说话的人"，含义不同，也和 LiveKit 的 `active_speakers_changed` 同名。
- **修复方向（用户提出）**：Turn 不在准入时固定参与者。参与者 ID、用户 ID、实体 ID 由 Persona 确定后与观测关联，消费者在使用时按实际绑定结果取用。这样 Turn 提交之后，Memory 用到人的时候也能拿到准确的绑定。
- **四点决定（用户 2026-11-21）**：
  1. 同一轮内，各组件在不同时刻解析，结果可能不一致：不考虑。身份随时间动态变化，插件没有及时拿到变化属于合理情况。
  2. 身份与观测的关联，和现在的实现一样，以 session、participant runtime 为准，整体改动最小。
  3. 身份的更正和改绑都以事件发布到 session runtime，以 session runtime 为准。
  4. 一批里仍有未归属的内容时 Memory 怎样处理：后面再说。
- **第二批方案必须处理的事实（已核实）**：
  - 会话结束时，来源退役会删掉段关联：Persona 的 `_cancel_source`（`speaker/processor.py`）调用 `participants.retire_source`，后者经 `_drop_source` 删除该来源的全部段记录。
  - 来源退役后 `source_is_current` 为假，`entity_for_segment` 和 `resolve` 都返回空。
  - Memory 的最后一次提取在会话结束之后；段记录上限 1024（`max_segments`）。
  - 所以 participant runtime 要在整个会话期间保留段的关联结果，"必须是当前来源"的检查只留给准入路径。
- **`InteractionAddressing`**：Router 对一段输入的最终寻址结论（谁说、对谁说、寻址方式、置信度、证据来源），在 `65c83b7d`（v0.6.7）引入，作为标注发布，但从引入起就没有任何地方读它。起作用的寻址结果走的是 `TurnTakingDecision.addressees`。用户同意删除，列入第一批（第 3.2 节）。

## 3. 第一批：诊断与 Router 命名

### 3.1 诊断日志

三处日志都是 INFO 级别，生产默认级别就能看到。

| 位置 | 日志 | 内容 |
|---|---|---|
| `participants/runtime.py` 的 `_settle` | `Speaker association settled` | `segment_id`、`source_id`、`source_generation`、`outcome`（`bound`／`unbound`／`invalid`／`released`）、`reason`、`wait_ms`（从登记到结束） |
| `engine.py` 的 `_log_participants` | `Turn participants` | `turn_id`、`input_id`；`participants=<参与者>/<用户>/r<身份版本>`，没归属的写 `unattributed`；`segments=<段>:<状态>`，状态为准入那一刻的 `pending`／`bound`／`unbound`／`invalid`／`unknown` |
| Memory `processors/base.py` 的 `build_memory_items` | `Memory items kept in their context` | `context_id`、`memory_type`、`items`、`reason`（`unattributed_input`／`no_owner`） |

- **未绑定的原因**：Persona 说话人处理器新增 `_unbound_reason`，分三种：
  - `inference_failed`：推理失败或超时；
  - `no_vector`：没有声纹；
  - `no_match`：有声纹但没匹配上跟踪。
- **原因怎样传下去**：
  - 三处调用 `finish_segment_resolution` 的地方都传入原因；
  - `finish_segment_resolution` 新增 `reason` 参数，已绑定时不记原因；
  - trace（`participant.segment_ready`）和日志拿到的是同一个原因。
- **状态记录**：
  - `_SegmentState.settled` 改为 `outcome`，记下怎样结束；
  - 新增 `segment_association(segment)` 查询当前状态。作废优先于已绑定；已释放或从未登记的段返回 `unknown`。
- **采样时刻**：Engine 在提交这一轮后立即写日志。从解析 actor 到这里没有 `await`，所以取到的就是解析时的状态。直接输入（文字、图片）也写一行，没有段。
- **怎样读**：看一轮里 `unattributed` 对应的段。
  - 准入时是 `pending`，之后那段的 `Speaker association settled` 为 `outcome=bound`：属于关联晚到，第二批的方案能解决；
  - `outcome=unbound reason=no_vector|no_match|inference_failed`：这一段根本没有关联结果。

### 3.2 Router

- `InputWindow`、`TurnTakingEvidence`、`InteractionAddressing` 上的 `actors` 改名为 `input_devices`，`InteractionAddressing` 序列化的键也改了。`InputWindow.input_devices` 仍取各段 subject。
- `TurnTakingDecision.actors` 删除：Engine 准入时根据观测重新解析，从不读它，只有一个 Router 测试断言过它。
- 同步修改：Router README 的说法、Engine 中 `_decision_actors` 的注释。
- 删除 `InteractionAddressing`（用户同意）：
  - 类和它的导出；
  - core 的 `AnnotationKind.INTERACTION_ADDRESSING`，只有它在用；
  - 协调器发布这条标注的代码；
  - policy 的 `_result` 里只为构造它而传的 `addressing_mode`、`addressing_confidence`、`addressing_evidence_ids` 三个参数和 `_evidence_ids`；
  - 删除后变成只写不读的两个字段：`TurnTakingEvidence.input_devices`、`TurnTakingAssessment.addressing_evidence_observation_ids`。`InputWindow.input_devices` 仍被 `mode()` 读取，保留。
- 发现，未改：
  - fusion 合并的寻址证据 `evidence_observation_ids` 现在只剩一个测试在读（`test_semantic_addressing.py`）。它属于视觉、语义寻址处理器还在发布、也还在被消费的证据标注，删除就要改这两个处理器的标注格式，所以没有动。
  - `TurnTakingPolicyResult` 现在只剩 `decision` 一个字段。去掉这层包装要改协调器里十几处，也没有动。

### 3.3 文档

- `docs/cli/doctor.md`：`association_ready` 一行补上未绑定的三种原因和两条新日志。
- `docs/bugs-zh.md`：KD-49 写明诊断方法和修复方向。

## 4. 验证

| 测试 | 改动 |
|---|---|
| `avatar-agents/tests/test_participant_segments.py` | 结束方式的参数化里新增"带原因的未绑定"，并断言日志行的字段；新增 `test_where_an_association_stands_is_told_until_it_is_released`，覆盖 pending、bound、unbound、作废优先、释放后为 unknown |
| `avatar-plugins/.../persona/tests/test_persona_sensors.py` | 推理超时和失败断言 `inference_failed`；段没有音频断言 `no_vector`；新增 `test_a_voice_no_track_takes_settles_its_segment_unbound_and_says_why`，断言 `no_match` |
| `avatar-host/tests/test_turn_actors.py` | 三种情形（两人各自绑定、一人绑定一段待定、两段都待定）都断言 `Turn participants` 这一行的参与者和各段状态 |
| `avatar-plugins/.../memory/tests/test_memory_runtime.py` | 执行后才更正身份时，断言 `Memory items kept in their context`；没有降级时不写这一行 |
| `avatar-plugins/.../router/tests/test_turn_taking.py` | 去掉对 `commit.actors` 的断言，字段已删除 |

- 受影响各包的测试：411 passed（Router、avatar-agents、Persona、Memory、轮次说话人、Doctor）；删除 `InteractionAddressing` 后，Router、avatar-agents、轮次说话人 186 passed。
- 变异 9 个全部被发现，跑完已恢复：
  - 不记结束日志；丢掉原因；作废不优先；`no_match` 记成 `no_vector`；不记推理失败；
  - 不写每轮日志；不列各段；Memory 降级不记；Memory 每批都记。
- 离线全量：按 Quality 的方式运行。删除 `InteractionAddressing` 之前 903 passed（310.13 s；原 900 加新增 3）；删除之后 903 passed（309.81 s），测试前后工作区完全一致。
- 仓库规范：`ruff check .`、`ruff format --check .`（791 个文件）、`check_workspace.py`、改动文件的 pre-commit 都通过。

## 5. 未验证 / 后续

- **真实通话没有跑**：你下一次真实通话会产生这些日志行，到时就能确定空 actor 属于哪种原因、各占多少。
- **日志量**：每段一行、每轮一行，都是 INFO。
- **第二批**：方案文档，把第 2 节的决定和必须处理的事实落成改动清单。要改的地方：
  - participants runtime 的 `project_turn`、`identity_basis`、身份工具，以及段关联的保留；
  - Persona 的 runtime 和 profiler；
  - Memory 的 state、recall、template 和身份证据；
  - Context、Loop 的测试，以及 Doctor 的说明；
  - `AGENTS.md`、`identifiers-zh.md`。

## 6. 证据

会话临时目录 `participants/`：
- `mutate_diag.py`：变异脚本；
- `full.txt`、`full2.txt`：删除前后两次离线全量的输出；
- `checkout-diff.txt`、`checkout-diff2.txt`：对应的测试前后工作区对比。
