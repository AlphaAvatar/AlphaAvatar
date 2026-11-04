# AlphaAvatar v0.6.9 Context — Claude Code 实施日志

- 分支：`dev/v0.6.9`；日期均为 CST。
- 本文件记录 Context 插件（Builder、History、渲染层）的审查修复与后续 review 收尾，按时间顺序追加。
- 统一的 KD/O 表仍在 `docs/agent-logs/2026-10/2026-10-25/claude-code-2a-zh.md`。

## 批次总览

| 批次 | 内容 | 日期 | 基线 HEAD | 提交 | 状态 |
|---|---|---|---|---|---|
| Context 审查修复 | 旧 profile 兼容读取、历史媒体内容固定、`FIXED` 语音加打字、历史内联图片超限（只报告） | 2026-11-04 | `43c019f` | `8789e9d`（代码与测试，用户提交）；本日志与 KD-18 未提交 | 待复审。P1–P3 已修复并回归；P4 现有机制无法同时满足，登记 KD-18 待用户决定。本地全量 326 passed，与 `8789e9d` 内容一致 |

---

## Context `43c019f` 审查修复

- 基线：`43c019f`。职责边界不变：`ContextBuilder` 只有 `build()` 一个公开入口；History 原样保存 Builder 产出的完整用户消息及顺序；`runtime_context` 每轮重新生成，只注入当前 Turn；上下文压缩不在本批。
- 生产改动只在 Context 插件内：`config.py`、`builder/context_builder.py`、`builder/renderer/input/xml.py` 和 README。

### 1. P1 · 旧 Context profile 无法启动

- 复现：旧版 `config init` 生成的 Context profile 带 `history_max_turns: 32`、`history_max_items: 4096`、`history_max_bytes: 8388608`。`43c019f` 删除这三个字段后，`ContextConfig` 的 `extra="forbid"` 拒绝它们，`config check` 返回 2，`start` 在"validate plugin settings"一步失败。
- 修复：`ContextConfig` 加一个 `mode="before"` 校验器，只去掉这三个键，值不读取、不校验；其他未知字段仍按 `extra="forbid"` 拒绝。`config check`、`start` 和插件构造走的是同一个 `ContextConfig.model_validate`。
- README：历史容量和淘汰的旧描述改为"不设容量、会话内不淘汰、压缩另行实现"，并说明旧字段可读、值被忽略。另补一句：每次查询都会重发历史中的全部图片，所以单靠历史就可能达到提供方的内联媒体上限（见第 4 节）。
- 回归：`avatar-host/tests/configs/test_bundles.py::test_a_context_profile_with_the_removed_history_limits_still_loads`。
  - 用 `config init` 建 bundle，把 Context profile 的正文换成旧版默认正文，文件头保持生成时的原样。
  - 走 `start` 在构造前读取的链路：`config check --json` 返回 0；`load_application` 后 `validate_plugin_settings` 得到默认 `ContextConfig()`。
  - 在旧字段旁再加 `history_max_tokens`，`config check` 返回 2，`fields` 恰为 `context.init_config.history_max_tokens`。
  - 修复前该用例在第一次 `config check` 即失败（返回 2）。

### 2. P2 · 历史图片的请求内容会变

- 复现：A 轮请求编码出原图之后，感知处理器（人脸处理器同样如此）向同一 `MediaPayload` 写入 `ANNOTATED` 视图。Responses 适配器取图时优先 `ANNOTATED`、回退 `RAW`，而 History 中 A 的消息引用的是同一个活的观测对象。结果是：A 轮已建好的请求再次编码（重试或后续模型步）以及 B 轮复用的历史，都变成了标注图。
- 修复：`ContextBuilder.build` 在首次构建当前消息时，把消息中的每个 `ModelImagePart`／`ModelAudioPart` 换成持有 `payload.snapshot()` 的观测副本。快照只复制表示登记表，媒体值本身共享，因此当前请求与 History 用的是同一份固定内容。再次准备同一 Turn 时 Builder 直接复用历史消息，不会重建。
- 回归：`avatar-plugins/foundation/avatar-plugins-context/tests/test_turn_history.py::test_history_sends_the_image_its_turn_sent_after_perception_annotates_it`。
  - 用真实 Responses 适配器编码，比较线上的 `input_image` data URI，不只比较 `ModelInputMessage` 是否相等。
  - 标注之后，A 轮已建请求再次编码、B 轮请求中的 A 历史，都仍是原图。
  - 同时断言 B 轮中 A 的用户消息与 A 轮所发的完全相等，A 的回复紧随其后，两轮各自只有一对 `runtime_context`，且都紧跟本轮用户消息。
- 范围说明：
  - 目前渲染器不产出 `ModelAudioPart`，所以音频部分的固定没有直接测试覆盖。
  - 实时渲染器附带的 `RealtimeModelInput`（对齐结果和选帧）没有改动：当前没有适配器消费它，Responses、LangChain text 和 Gemini 遇到它都直接拒绝。

### 3. P3 · `FIXED` 同轮语音加打字会丢语音

- 复现：`FIXED` 对齐（`REALTIME` 输入模式强制使用，或配置 `runtime.perception.temporal_alignment.mode: fixed`）不生成 speech 切片，转录以普通 `TRANSCRIPT_SEGMENT` 观测落入每个与它重叠的切片。渲染层只渲染 `temporal_slice.speech`，于是转录被丢掉。打字照常渲染成 `<text_input>`，Builder 看到 `<text_input` 就不再加 `<committed_text>` 回退。最终本轮请求只有打字，History 随后也只保留打字。
- 修复（渲染层，`xml.py`）：
  - 非 speech 切片中的 `TRANSCRIPT_SEGMENT` 按观测标识去重，只在它出现的第一个切片（即它开始时所在的切片）渲染一次。
  - 渲染复用 `_speech_parts`：同一段的 `SPEECH_SEGMENT` 若在本 Turn 中，就配对给出 `audio_available` 并以它为时间锚，与对齐器的锚定规则一致；输出 `segment_id`、`start`／`end` 和 `<transcript>`。
  - 段落在切片内按开始时间与音源事件、帧、通知一起排序。
  - 只含转录的切片不再被跳过。
  - 打字仍走 `<text_input>`；`<committed_text>` 的回退条件不变，仍是"渲染结果里既没有 `<text_input>` 也没有 `<transcript>`"。
- 回归：`test_turn_history.py::test_fixed_slices_keep_speech_beside_typing_in_the_request_and_its_history`。
  - 依次输入：语音段 1、打字、跨两个固定切片的语音段 2，语音段 2 中间有一个摄像头启动事件。
  - 断言本轮请求中两段 `<speech>` 的段落标识、相对时间、`audio_available="true"`、转录，以及切片内事件的顺序；`<transcript>` 恰好 2 个，没有 `<committed_text>`，打字在 `<text_input>` 中。
  - 下一轮复用的历史与本轮所发的用户消息完全相等，回复紧随其后，`runtime_context` 只跟在下一轮自己的消息后面。
- 残留边界（未复现，未修改）：如果快照因感知缺口保留了打字事件、却丢了转录事件，回退条件不会触发，语音仍会静默缺失。要覆盖这一情况，需要把回退判定改为比对已提交文字与已渲染文字，超出本次"已有事件缺渲染"的范围。

### 4. P4 · 历史内联图片累计超限后，纯文字轮也会失败（KD-18，待用户决定）

- 触发条件：
  - Responses 适配器对每个请求从零累计内联字节（每张图的 JPEG 字节；只有帧时按 `jpeg_quality` 现场编码），超过 `input_options.max_inline_bytes`（默认 20 MiB）即拒绝。
  - History 完整保留每轮的图片，每个请求都重发全部历史图片。因此当历史与本轮图片字节之和首次超过上限时，该轮失败。
  - 该轮用户消息在 `prepare` 阶段（模型调用之前）就已进入 History，此后每一轮，包括纯文字轮，都必然超限。
  - 估算：按默认每轮最多 4 帧、每帧 S 字节，约 20 MiB ÷ (4·S) 个带图轮次后触发。
- 当前错误行为：
  - 已由测试证实：`ResponsesAdapter.encode` 在发出网络请求之前抛出 `ModelCapabilityError("Inline media exceeds the configured request limit", code="image_input")`。
  - 按代码路径（`loop/execution.py` 的异常处理），未专门测试：Loop 运行以 FAILED 结束，reason `execution_failed`，`error_type=ModelCapabilityError`，`error_code=image_input`，没有回复。
  - 会话内无法恢复，因为 History 不淘汰。
  - 错误码 `image_input` 落在一个本身不带图的纯文字轮上；Doctor 会把 `ModelCapabilityError: image_input` 判为"图像被拒"，并尝试关闭视觉的降级，原因归错。
- 已核对的现有机制，均不能同时满足"保留完整媒体"和"满足上限"：
  - 适配器只有两条路：内联 data URI，或来自 `IMAGE_URI`（RAW 视图）的 http(s) URL，后者不计入内联字节。摄像头和屏幕帧从不带 `IMAGE_URI`：生产代码中没有任何调用方给 `ImagePayload.create` 传 `uri`。
  - 请求固定为 `store: false`、`truncation: "disabled"`；没有 `previous_response_id`，没有文件上传或 `file_id`。
  - `ModelRequest`／`ModelGenerationOptions` 没有媒体预算。
  - Context 在 `43c019f` 已删除历史媒体占位（`compact_historical_message`），请求投影没有预算。
- 可选处理（待决定）：

  | 方案 | 做法 | 代价 |
  |---|---|---|
  | A | Context 请求投影加媒体预算：History 仍完整保存，请求中超出预算的最早历史图片换成文字占位，本轮图片优先 | 与后续"上下文压缩"重叠；请求不再逐字重放历史；Context 需要知道提供方上限 |
  | B | Responses 适配器在超限时省略最早的历史图片并加文字标记，只有本轮自身超限才失败 | 只影响该适配器；适配器开始改写请求内容 |
  | C | 每张图用 Files API 上传一次，按观测缓存 `file_id` 并引用 | 媒体完整、请求小；新增上传延迟、提供方侧存储／保留期／隐私和删除生命周期；仅限 OpenAI |
  | D | 服务端会话状态（`store: true` + `previous_response_id`） | 提供方保存对话；与本地规范历史、身份重绑和隐私默认值冲突 |
  | E | 调大 `max_inline_bytes` 或降低画质 | 只是推迟触发点；画质改变内容 |
  | F | （可与上述并用）超限改用独立错误码，例如 `inline_limit` | 不修复会话失效，只避免 Doctor 和日志把纯文字轮的失败归因到视觉 |

  建议：近期做 F，A 并入后续上下文压缩。最终由用户决定。
- 回归：`test_turn_history.py::test_history_images_past_the_inline_limit_refuse_every_later_turn`。它固定当前的触发条件和行为（docstring 标注 KD-18）：
  - 两轮各 600 字节、上限 1000：第一轮通过；第二轮被拒，`code == "image_input"`。
  - 第三轮纯文字：在默认上限下仍能编码出两张历史图片（History 完整保存），在 1000 上限下同样被拒。
  - 决定处理方式后，按决定改写该用例的断言。

### 5. 连续两轮复验

- P2、P3 两个用例都覆盖连续两轮：
  - 每轮各自恰有一对 `runtime_context`（call 与 output），且紧跟本轮用户消息。
  - 上一轮的历史中没有 `runtime_context`。
  - 历史用户消息与上一轮所发的完全相等，包括媒体内容（P2 比较适配器编码后的图片）、段落和时间位置（P3）。
  - 用户消息与回复的顺序不变：`[system, 上一轮用户消息, 上一轮回复, 本轮用户消息, runtime_context ×2]`。

### 6. 基线既有失败与测试适配

`43c019f` 基线全量：316 passed、6 failed，用时 2 分 08 秒，磁盘剩余 13 GB，与磁盘空间无关。6 项都是测试仍在使用 `d004ec4`／`43c019f` 改动前的接口。处理方式是只改调用点；唯一改动的断言见下表第一行。

| 测试 | 失败原因 | 改动 |
|---|---|---|
| Context `test_identity_switch.py::test_identity_correction_rebuilds_the_prefix_but_keeps_accepted_history` | 调用已删除的 `accept_turn` 和旧 `ContextPrepareRequest(input=…, turn_id=…, input_id=…)` | 改为 `ContextPrepareRequest(turn=…, context_id=…)`。原断言 `history == ["My name is B.", "Hello B."]` 依据的是旧设计（历史种子重渲染为纯文本）；按新设计改为与首次构建的用户消息完全相等，并要求其中含 "My name is B."，比原断言更严格 |
| Loop `test_identity_switch.py` 4 项 | `accept_turn` 和旧 `LoopRequest(input_id, turn_id, input)` | 改为 `LoopRequest(turn=…, context_id=…)`；断言未改 |
| Host `doctor/test_session.py::test_degradations_follow_the_original_cause_and_both_configurations_are_reported` | Doctor 替身 `drop_speech` 打补丁的 `renderer.op._speech_xml` 在 `d004ec4` 已改名 | 替身改为打补丁 `renderer.input.xml._speech_parts`，同时让 Builder 看到 `text=None` 的快照。原因：`43c019f` 新增的 `<committed_text>` 回退会把被删的转录补回请求。变异 D1（只删语音、保留回退）使反向用例失败，证明这一步必要。断言未改 |

### 7. 验证

- 修复前后对照：分别把三个生产文件还原为 `43c019f`，对应用例各自失败（P1、P2、P3 各一项），其余通过。
- 变异：

  | 编号 | 变异 | 结果 |
  |---|---|---|
  | M1 | 旧字段集合少 `history_max_bytes` | 捕获 |
  | M2 | 校验器丢弃所有未知字段 | 捕获 |
  | M2b | `extra="ignore"` | 捕获 |
  | M3 | 不做 payload 快照 | 捕获 |
  | M4 | 跨切片转录不去重 | 捕获 |
  | M5 | 只含转录的切片仍被跳过 | 捕获 |
  | M6 | 不与 `SPEECH_SEGMENT` 配对 | 捕获 |
  | M7 | 转录在切片内排到其他条目之后 | 首轮存活：同一切片内没有其他条目；补入切片内摄像头事件后捕获 |
  | D1 | Doctor 替身保留 `committed_text` | 捕获 |

- 全量：326 passed、0 failed，用时 2 分 19 秒，CI 同方式，磁盘剩余 13 GB。运行期间用户提交了 `8789e9d`；该提交相对 `43c019f` 的差异与所测工作区逐字节一致（已比对 diff 哈希和新测试文件）。
- ruff、ruff format、`uv lock --check`、`scripts/check_workspace.py` 和 pre-commit（改动文件）均通过。

### 8. 改动文件（`8789e9d`）

- 生产：
  - `avatar-plugins/foundation/avatar-plugins-context/alphaavatar/plugins/context/config.py`
  - `avatar-plugins/foundation/avatar-plugins-context/alphaavatar/plugins/context/builder/context_builder.py`
  - `avatar-plugins/foundation/avatar-plugins-context/alphaavatar/plugins/context/builder/renderer/input/xml.py`
  - `avatar-plugins/foundation/avatar-plugins-context/README.md`
- 测试：
  - 新增 `avatar-plugins/foundation/avatar-plugins-context/tests/test_turn_history.py`（3 项）
  - `avatar-host/tests/configs/test_bundles.py`（1 项）
  - `avatar-plugins/foundation/avatar-plugins-context/tests/test_identity_switch.py`
  - `avatar-plugins/foundation/avatar-plugins-loop/tests/test_identity_switch.py`
  - `avatar-host/tests/doctor_doubles.py`
- 未提交：本日志，以及 2A 日志中的 KD-18 行和指向本日志的说明行。

### 9. 待用户决定

- KD-18 的处理方式（第 4 节方案 A–F）。
- 第 3 节的残留边界：是否把 `<committed_text>` 回退判定改为比对已提交文字与已渲染文字。
