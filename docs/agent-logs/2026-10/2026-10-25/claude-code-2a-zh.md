# AlphaAvatar v0.6.9 阶段 2A — Claude Code 实施日志

- 分支：`dev/v0.6.9`；日期均为 CST
- 2A 各批次都记录在本文件中，新批次按时间顺序追加到末尾。
- T-10 起（安装、升级回滚与 Doctor 阶段）的记录在 `docs/agent-logs/2026-11/2026-11-03/claude-code-t10-zh.md`；KD/O 表仍以本文件为准。
- 2026-10-26 按用户要求，把原先拆分的三份日志合并为本文件。合并时没有改写批次内容，只去掉了重复的 KD 表和过时的状态行。原 2A-1 和 2A-2a 日志可在 git 历史中查到（`5c2c5b7`、`468c807`）。

## 批次总览

| 批次 | 内容 | 日期 | 基线 HEAD | 提交 | 状态 |
|---|---|---|---|---|---|
| 2A-1 | 最小测试基础设施（21 个测试） | 2026-10-25 | `1ab771a` | `780091c` | 已验收；CI lint、build、install 通过，21 passed |
| 2A-1 审计修正 | 加强两个取消回归测试 | 2026-10-25 | `780091c` | `5c2c5b7` | 已验收；CI 21 passed |
| 2A-2a | `avatar.id` 必填 | 2026-10-25 | `5c2c5b7` | `468c807` | 已验收；CI Lint、Build、Install 通过，23 passed |
| 2A-C1 | 删除未使用的 Host diagnostics | 2026-10-26 | `468c807` | `00cc6ef` | 已验收；CI Lint、Build、Install 通过，23 passed；KD-9 关闭 |
| T-1 | 必要回归测试补全与 KD/O 复核（只改测试） | 2026-11-02 | `f708b26` | `161e35f` | 已 review：测试保留，未验收；按 review 进入 T-2 修复缺陷 |
| T-2 | 修复 KD-11、KD-12、KD-13、O-3，补定向测试与测试设施 | 2026-11-02 | `161e35f` | `1aecf40` | 已 review：KD-11/12/13、O-3 的修复和 Memory/Persona 补测接受；剩余收尾项转入 T-3 |
| T-3 | 修复 KD-14（原 O-8）、KD-15，封住 allowlist 旁路，澄清 KD-13 | 2026-11-02 | `1aecf40` | `dca356f` | 已 review：KD-15、allowlist 旁路、KD-13 文案验收；KD-14 未关闭（持续发声边界），转入 T-4 |
| T-4 | KD-14 补齐：缺口后先确认可靠的静音或结束边界，再接纳语音开始 | 2026-11-02 | `dca356f` | `65bd40f` | 已 review：VAD 接口与短停顿保守丢弃策略接受；普通恢复路径已修好；另有三条旁路，KD-14 仍未关闭，转入 T-5 |
| T-5 | KD-14 收口：恢复要求随输入 generation 保留到边界确认；回放不越过安全下界 | 2026-11-02 | `65bd40f` | `a2b6bde` | 已 review：三条旁路已修好；仍有 1 个 P1（快照更新可绕过恢复要求），KD-14 未关闭，转入 T-6 |
| T-6 | KD-14：缺口窗口中 generation 已存在的证据不被更新的快照覆盖 | 2026-11-02 | `a2b6bde` | `4cb57c2` | 已验收：review 无新阻断问题，KD-14 关闭；本地 195 passed（CI 方式 ×3），review 环境运行 147 项通过（IPC 用例受环境限制） |
| T-7 | KD-14 正式回归；修复 O-1、KD-6、KD-8、O-7；KD-10 时序与 O-4 取消补测试 | 2026-11-02 | `2d1d575` | `7e87782` | 已验收：O-1、KD-6、KD-8、O-7 关闭，KD-14 保持关闭，KD-10③ 时序已覆盖，O-4、O-9 保留观察；本地 229 passed；review 环境 229 项收集、183 项通过，新增 CLI 端到端用例受 AF_UNIX 权限阻断（替换日志传输边界后的配置错误处理路径通过，不计为完整 CLI 端到端） |
| T-8 | 配置公共能力与 CLI 最小闭环：`config init`、`config check`（`check` 已迁入，`config show` 已移除） | 2026-11-02 | `7e87782` | `886efcd`、`e428c9b`、`d9a8b4f`、`4365820`、`e7bc3b3` | **已验收**（验收提交 `e7bc3b3`）：本地 246 passed（CI 方式 ×1）；review 环境选跑 200 项全部通过，此前失败的音频用例已通过；Ruff、格式、workspace、lock 通过；IPC 未独立全量复跑 |
| T-9 | Runner 可配置并行与压力验证（`runtime.inference`、method 级 worker 池、多通道 Executor） | 2026-11-02 | `e7bc3b3` | `41ba2c0`、`69813df` | **已验收**（验收提交 `69813df`）：本地 263 passed（CI 方式 ×1）；review 环境收集 263 项、选跑 202 项通过；回环 TCP 替换 Unix 边界后，14 项并行、10 项 Runtime、5 项默认压力测试通过；Ruff、格式、workspace、lock 通过；原生 AF_UNIX 未独立全量复跑 |

## 已知缺陷（当前状态，只记录不修复）

| ID | 问题 | 归属 | 变更记录 |
|---|---|---|---|
| ~~KD-1~~ | ~~`AvatarConfig` 校验时创建 Workspace、写入 `AVATAR_WORK_DIR`/`AVATAR_TIMEZONE`；同一进程内重复校验会让 ID 重复追加（R3）；没有 base 时会写探测 `/var/lib/<id>`~~ | 已关闭 | 2A-1 记录；2A-2a 移除随机 UUID；**T-1 复核：已修复**。`AvatarInfoConfig` 只做纯校验，loader 不建目录、不写环境变量；同进程重复加载不再嵌套；`/var/lib/<id>` 只在激活时做只读的连续性检查。回归：`test_avatar_config.py`、`test_application_config.py::test_repeated_loads_keep_paths_and_credentials_separate` |
| ~~KD-2~~ | ~~Memory 和 Persona 配置在校验时写 `*_VDB_*` 环境变量（配置被拒绝时也写），并构造 QdrantClient。`check_compatibility=True` 会在构造时发出 HTTP 版本请求，Host 和执行子进程各执行一次，客户端从不关闭~~ | 已关闭 | 2A-1 记录；2A-2a 补充 HTTP 版本请求与客户端未关闭；**T-1 复核：已修复**。`snapshot_vdb_config` 只读取 `QDRANT_URL`/`QDRANT_API_KEY` 作快照，不写环境变量、不构造客户端；Runner 只从 `RunnerLaunch` 快照取配置。回归：`test_avatar_config.py`（已去掉 KD-2 白名单）、`test_runner_launch.py::test_remote_vector_runners_connect_with_their_launch_snapshot` |
| ~~KD-3~~ | ~~Tools 配置把解析后的 secret 写入 `MCP_*` 环境变量~~ | 已关闭 | 2A-1 记录；**T-1 复核：已修复**。`<ENV>` 占位符在校验时解析进 `servers` 快照，不写环境变量；子进程用 launch 快照。回归：`test_avatar_config.py::test_accepted_configuration_only_reads_its_inputs`、`test_application_config.py::test_restore_keeps_frozen_paths_and_inputs_after_the_environment_changes` |
| ~~KD-4~~ | ~~Persona LanceDB 查询中 `user_id` 直接拼接、未转义，不安全~~ | 已关闭 | 2A-1 记录；**T-1 复核：已修复**。`_user_filter` 转义单引号，拒绝空值和 NUL。回归：`test_persona_profile.py::test_lancedb_user_predicates_isolate_quoted_identities_and_resave_idempotently`（真实 lancedb） |
| ~~KD-5~~ | ~~Persona VDB 保存失败的错误没有被正确处理~~ | 已关闭 | 2A-1 记录为"保存只检查结果是否为假值"；2A-2a 按审计统一表述；**T-1 复核：已修复**。空结果和 `*error` 字段都抛 RuntimeError，`save` 汇总为 ExceptionGroup。回归：`test_persona_runtime.py::test_vdb_save_failure_surfaces_instead_of_silently_succeeding` |
| ~~KD-6~~ | ~~Memory Passive Recall 的具体完成状态没有完整传播到 Turn-level diagnostics~~ | 已关闭 | 2A-2a 按审计更正：原表述"检索出错返回 `[]`，与空结果无法区分"不准确，问题不在 MemoryStore；**T-1 复核：仍存在**。`PassiveRecall.wait_context_ready` 只等待完成，timeout/overloaded/unavailable 等状态只写 debug 日志。本轮未补测试；**T-7 修复**：`PassiveRecall` 在唯一的完成门闩处把具体结果（ok/empty/timeout/overloaded/unavailable/error/identity_changed）写入现有的 InputTrace Turn 诊断（`memory.recall`，带哈希的 `turn_id`）；补上原来没有记录的"保留名额全部在途"路径；等待期限和门闩不变。回归：`test_memory_recall_diagnostics.py`；T-7 review（`7e87782`）验收 |
| KD-7 | ToolPolicy 的默认审批策略与部分示例文档不一致。**未授权修改默认行为**；需要另行审查工具权限模型、执行授权和用户确认策略，不能损害合理的自主执行能力 | 独立审查 | 2A-1 记录为"`ToolPolicy.approval_required` 默认为 False，与示例 YAML 注释矛盾"（原归属 Tools 批次）；2A-2a 按审计改为独立审查；**T-1 复核：未变**（loop `config.py` 中默认仍为 False） |
| ~~KD-8~~ | ~~Health 服务默认暴露在网络上（绑定 `0.0.0.0`），`/status` 没有鉴权~~ | 已关闭 | 2A-1 记录；**T-1 复核：未变**（`HealthConfig.bind` 默认 `0.0.0.0`，`/status` 无鉴权）；**T-7 修复**：`HealthConfig.bind` 默认改为 `127.0.0.1`，显式配置的外部绑定保留；`/status` 的字段集合固定为就绪标志、Runner 启动状态和最近执行的 ID/代码/pid，不含配置或凭据。回归：`avatar-host/tests/test_health.py`；`DEPLOY.md`、`avatar-host/README.md` 已同步；T-7 review（`7e87782`）验收 |
| ~~KD-9~~ | ~~`host/diagnostics.py` 无引用、与 Core diagnostics 重复、与计划中的 `host/diagnostics/` 包同名冲突~~ | 已关闭 | 2A-1 记录；**2A-C1 删除文件后解决** |
| KD-10 | **待修复（数据完整性，高优先级）**。临时身份 B 解析为稳定身份 A 的链路有四类风险：① **文件丢失**：会话关闭时 `flush_user_path_migrations(remove_old=True)` 先做不覆盖合并，再 `rmtree` 旧目录，两边同名的文件中旧目录那份被删除；连续解析 B→A→C 会删除稳定用户 A 的目录；② **Memory 归属**：上下文 Owner 只在消费 Turn 或输出记录时才同步，已持久化的 B 记录从不更新 Owner，A 之后检索不到；③ **Persona 合并**：A 已有 Details 时整体丢弃 B 的 Details；身份解析前提交、解析后才消费的 Turn 被 Profiler 丢弃；④ **重复或错误的身份解析**：已稳定的身份可被再次重绑定；`load_profile` 不区分证据来自哪个 Participant，缺少可比较向量时直接视为匹配；未注册 Participant 的声纹和人脸会写入主 Participant | KD10-1…KD10-5，逐批授权 | 2A-2b 审计记为候选；2026-10-27 独立审计确认，并用合成数据离线复现，标为待修复；2A-2b-1 暂缓；**T-1 复核：主体已修复，剩余两点未覆盖**。① 关闭时的 flush/merge/rmtree 已全部删除（源码无引用），改绑不做磁盘 I/O；② 按已接受的设计，历史持久记录的 Owner 不重写（`test_memory_batches_never_reassign_earlier_turns_to_a_corrected_user`），纠正后 A 能否检索 B 的旧记录属于延期的多人历史政策；③ Persona 改为按 Participant 缓存，字段级合并（`merge_profile_items`），来源优先级和乱序增量有回归，但"解析前提交、解析后消费的 Turn"是否被 Profiler 丢弃，本轮没有单独覆盖；④ 身份可纠正是已接受的设计（被动 B→A、主动 A→C，Agent 改绑走 CAS），`load_profile` 按 Participant 加载并在每次 await 后重查身份，Speaker/Face 证据按 Participant 隔离，旧 source generation 的迟到结果不能绑定身份（`test_persona_sensors.py`、`test_participant_identity.py`、`test_session_identity.py`）；**T-7（仅补测试）**：③ 中"身份解析前提交、解析后才被 Profiler 消费的 Turn"已覆盖，按现有设计画像归入解析后的用户、只保存一次，Turn 的 actors 保持冻结，没有静默漏处理（`test_persona_runtime.py::test_turn_committed_before_identity_resolution_is_profiled_for_the_resolved_user`）。仍待处理：② 跨身份检索旧记录，属于延期的多人历史政策；T-7 review（`7e87782`）确认 ③ 的消费时序已覆盖，历史 Turn 的身份信息保持冻结 |
| ~~KD-11~~ | ~~任一 Runner 处于故障状态时，`InferenceRuntime._accept_client` 因 `not self.is_alive`（要求全部 Runner 存活）直接 abort 所有**新**连接。Executor 按 method 懒连接，所以会话在故障窗口内首次使用另一个健康 method 时，收到裸 `ConnectionResetError`，而不是 "temporarily unavailable"。已建立的连接不受影响。与"不同 method 独立推进"不一致；对真实模型 Runner，故障窗口可能持续数秒~~ | 已关闭 | T-1 新增并保留失败复现；review 补充：`do_inference()` 同样受影响，健康连接取消后重连也会被拒；**T-2 修复**：服务准入（`_serving`）与目标 Runner 健康分开判断，总体 `is_alive` 保留给 Host 监测和恢复。回归：`test_inference_runtime.py::test_failed_method_does_not_refuse_first_use_of_a_healthy_method`（已扩展） |
| ~~KD-12~~ | ~~Engine 先 `revoke_run` 再 `interrupt`，若两步之间下一句 TTS 首帧到达：`SegmentPreparer.prepare` 因 output 不再 active 抛 CancelledError，`SpeechStreamer.run` 在 `job.cancelled` 仍为 False 时把它当成"准备阶段自己取消"，转成 `RuntimeError("TTS preparation cancelled itself")`。结果 AUDIO_COMPLETE 的 reason 是 `speech_synthesis_failed`，并记 ERROR 日志；帧循环对同一条件判为 `synthesis_interrupted`，两条路径不一致。PCM 已正确停止，收尾事实都完成~~ | 已关闭 | T-1 新增并保留失败复现（低严重度）；**T-2 修复**：准备阶段的取消在 output 已失效时按打断处理，output 仍有效时保持 Provider 自取消的错误边界。回归：`test_speech_synthesis.py::test_revoked_answer_awaiting_tts_first_audio_is_interrupted_not_failed`、`test_provider_self_cancellation_on_an_active_output_remains_a_failure`；**T-10T2**：这两个回归按"只为修小 BUG 的测试不留在项目中"的规则移出（见 git 历史 `b46c4ea`），缺陷保持关闭；`c09f8dd` review 同意作为低严重度分类测试继续精简，**当前没有直接回归**（这一时序下的 reason 标签和 Provider 自取消边界都没有直接测试） |
| ~~KD-13~~ | ~~打断时 partial alignment 漏计已交付的音频：`SpeechStreamer` 只在 `publish()` 完整返回后累计 samples；帧已被一个消费者取走、另一个消费者仍在反压中时，打断让该调用返回 `None`，这一帧不计入最终 alignment（消费端收到 2 帧 0.020 s，alignment 只有 0.010 s）~~ | 已关闭 | T-1 记为未复现的观察；review 做成确定性复现；**T-2 修复**：按 Output 的接纳序号判断，帧一旦被接纳（与 AUDIO_COMPLETE barrier 覆盖范围一致）即计入，未被接纳的帧不计。回归：`test_speech_synthesis.py::test_interrupted_alignment_covers_audio_already_delivered_to_a_consumer` |
| ~~O-1~~ | ~~初始化期间取消 Runner，要先等满 `close_timeout`（默认 5 s）才发 SIGTERM；测试中以 0.5 s 观测到~~ | 已关闭 | 2A-1 记录；**T-1 复核：仍存在**。实测 `close_timeout=0.5` 时为 0.50 s，`2.0` 时为 2.00 s；**T-7 修复**：关闭时进程从未 READY，就直接进入终止（SIGTERM）与回收，不再先等满 `close_timeout`；已 READY 的进程照旧走 CLOSE 握手。回归：`test_runner_process.py::test_cancelled_initialization_is_terminated_without_a_drain_wait`、`test_ready_runner_still_closes_through_its_drain_path`、`test_inference_runtime.py::test_mixed_close_drains_ready_runners_and_terminates_initializing_ones`；T-7 review（`7e87782`）验收；**T-10T2**：`test_cancelled_initialization_is_terminated_without_a_drain_wait`、`test_mixed_close_drains_ready_runners_and_terminates_initializing_ones` 按规则移出（见 git 历史 `b46c4ea`）；`test_ready_runner_still_closes_through_its_drain_path` 作为就绪 Runner 正常收尾的契约保留；**T-10T3**（按 `c09f8dd` review）：恢复进程层的 `test_cancelled_initialization_is_terminated_without_a_drain_wait`，作为有明确期限的代表场景；Runtime 层的混合关闭用例（×2）作为重复层级仍移出，该层没有直接回归 |
| O-2 | 导入 `alphaavatar.agents.configs` 会立即加载全部插件和 torch、cv2、weasyprint、openai 等（约 1.7 s）；导入期间第三方库会改写 `LD_LIBRARY_PATH`、`QT_QPA_*`、`OPENBLAS_MAIN_FREE` 等变量 | 仅记录 | 2A-2a 新增；**T-1 复核：部分改善**。干净解释器中约 0.92 s，不再导入 torch；仍加载 cv2、weasyprint、openai、numpy 和 memory/persona/router/voice 插件；仍改写 `LD_LIBRARY_PATH`、`QT_QPA_FONTDIR`、`QT_QPA_PLATFORM_PLUGIN_PATH`；T-8：`check`/`config show` 同样会在加载配置时触发这些导入副作用（只影响 CLI 进程自身），不在本批处理；**T-10B review（`0579d81`）**：用 audit hook 实测，首次导入时还会触发第三方库的本机探测：`urllib3` 创建并 bind 一个 IPv6 socket，`weasyprint` 通过 `ctypes.util.find_library` 运行 `ldconfig`、`gcc`、`ld` 并创建、删除临时文件。`config check`、`doctor`、`start` 都会经历这一步；Doctor 文档已写明这条边界，仍只记录、不修复 |
| ~~O-3~~ | ~~`InferenceRuntime` 把 socket 建在 `tempfile` 目录下（`alphaavatar-inference-*/runtime.sock`），TMPDIR 较长时超过 AF_UNIX 路径上限（约 104–108 字节），启动时报 OSError，没有预检~~ | 已关闭 | T-1 新增；review 改判为启动兼容性缺陷；**T-2 修复**：新增 `alphaavatar.core.ipc.private_socket_path`，Inference 与 Host 日志的 socket 优先放在配置的临时目录，超过 100 字节时回退到 `/tmp` 下新建的私有（0700）目录，都不满足时给出明确的 ENAMETOOLONG。回归：`avatar-host/tests/test_local_endpoints.py` |
| O-4 | Speaker/Face 的 `_inference_loop` 依赖在途任务抛出取消。若被等待的调用吞掉取消并正常返回，循环自身的取消会丢失，`_stop()` 会挂住。真实 InferenceExecutor 会传播取消，`_process` 也会重新抛出，所以正常生产路径不受影响；Profiler 有 `cancelling()` 防护，这两个循环没有 | 仅记录（未确认风险） | T-1 新增；只能用吞掉取消的替身复现，且会挂死，所以没有提交失败用例；**T-7（仅补测试）**：按真实调用链的取消契约补了 Speaker/Face 在推理或 VDB 查询未返回时 stop 的回归（8 个组合），stop 在有限时间内完成、任务在关闭前回收、stop 之后迟到结果不再写入身份；真实 InferenceExecutor 与 `PersonaStore._infer` 都会传播取消，"被调用方吞掉取消"的路径不可达，仍只作风险记录（`test_persona_sensors.py::test_stop_with_pending_sensor_work_reaps_it_and_admits_no_late_result`）；T-7 review（`7e87782`）：继续保留观察 |
| ~~O-5~~ | ~~ENV Memory 批次附带的对话上下文只取最后 `max_context_messages`（64）条、`max_context_chars`（8192）字符~~ | 已关闭（设计如此） | T-1 新增，交维护者判断；**review 结论：不需修改**。这是 ENV 的有限辅助 prompt；完整的 Conversation/Tool 输入和原始 Turn 都没有被裁剪 |
| O-6 | `agents/utils/vdb/lancedb.py` 使用已弃用的 `table_names()`，测试中出现 DeprecationWarning（全量 28 条） | 仅记录 | T-1 新增 |
| ~~O-7~~ | ~~`MCPConfig` 未设置 `hide_input_in_errors`，ValidationError 文本可能带出部分原始 `servers` 输入（可能含明文 secret）。CLI 当前只输出字段名~~ | 已关闭 | T-1 新增；**T-7 修复**：`MCPConfig` 与实际校验入口 `AvatarConfig` 都设置 `hide_input_in_errors=True`（内层设置只在它作为顶层模型时生效）；CLI 与执行子进程本就只输出 `format_error`（`include_input=False`）。回归：`test_avatar_config.py::test_rejected_mcp_input_never_reaches_error_output`、`test_cli_entrypoint.py::test_rejected_configuration_secret_never_reaches_cli_output`；T-7 review（`7e87782`）验收 |
| O-9 | `HostConfig`（含 `rtc.init_config`）没有设置 `hide_input_in_errors`，其校验错误的 `str` 可能带出原始输入。LiveKit 凭据来自环境变量而不是配置，CLI 与执行子进程只输出 `format_error`，所以目前没有暴露路径 | 仅记录 | T-7 新增（O-7 检查输出路径时发现，不在本批范围）；T-7 review（`7e87782`）：继续保留观察；T-8 复核：新增的 `check`/`config show` 只输出 `format_error` 与按位置列出的字段，Host 配置错误路径已有回归，不暴露 O-9，继续保留观察 |
| ~~O-8~~ | ~~VAD 积压超过 `max_buffer_sec`（2 s）时最旧的帧被淘汰，语音开头丢失且没有 trace 记录；看起来是有界内存的有意取舍~~ | 升级为 KD-14 | T-2 新增（语音上游测试中观察到，未断言）；review 确定性复现后升级为生产缺陷 |
| ~~KD-14~~ | ~~VAD 积压超过 2 s 缓存时，迟到的 VAD 起点所在的语音正文已被淘汰，`_start_segment` 不检查，剩余部分仍作为正常 `SPEECH_SEGMENT` 发布，没有缺口或取消记录（review 复现：积压 2.4 s 时，32 帧 0.32 s 的发声只剩 8 帧 0.08 s）~~ | 已关闭 | 原 O-8；**T-3 修复（不完整）**：保留 2 s 缓存上限；起点早于最早保留样本时，记录 `audio.speech_lost`（`reason=vad_backlog_overflow`，`missing_count` 为丢失样本数），以 `INPUT_GAP` 发布 `SPEECH_CANCELLED`，不路由剩余帧，并换一条已追上进度的新 VAD 流；只丢 pre-roll 时照常发布。回归：`test_audio_activity.py::test_speech_evicted_by_the_backlog_bound_is_cancelled_and_recovered`；review（`dca356f`）：换流后用户不停顿继续说话，新流把原句尾部当作新的一句，经 STT/TurnTaking 产生正常 COMMIT，KD-14 重开；**T-4 修复**：连续性缺口（`INPUT_GAP`、`VAD_INPUT_REJECTED`、感知流缺口）之后新建的 VAD 流，要先观察到 VAD 自身的结束静音（`min_silence_duration`）或一次 END_OF_SPEECH，才接纳语音开始；此前的 START 视为原句延续，不路由，记 `audio.speech_skipped`（`reason=unconfirmed_boundary`）。回归：`test_audio_activity.py::test_speech_continuing_through_a_gap_is_not_admitted_as_a_new_utterance`；范围说明：`INPUT_GAP` 会退役整个旧 speech epoch（该 speech source generation），其中尚未完成识别、尚未提交的前段也一并退役；已提交的 Turn 不变；review（`65bd40f`）：普通恢复已修好，另有三条旁路被确定性复现：恢复中再次失败会丢掉等待要求；感知缺口后首次发现的输入不受约束；pre-roll 会带回已跳过的尾句。**T-5 修复**：恢复要求属于输入 generation，只在当前流确认边界后解除，再次换流继承；感知缺口时记录 horizon，在其之前首次出现的输入 generation 也要确认边界；确认边界时把回放下界设为确认静音的起点，pre-roll 不越过。回归：`test_recovery_survives_a_stream_that_fails_before_its_boundary`、`test_input_first_seen_after_a_perception_gap_must_confirm_a_boundary`、`test_pre_roll_after_a_gap_never_reaches_back_into_skipped_speech`；review（`a2b6bde`）：快照用最新的 `changed_sequence` 判断 generation 是否在缺口之后出现，而状态更新时间不代表 generation 首次出现的时间；缺口与读快照之间同一 generation 发生一次静音再恢复，尾句会正常成段并经 STT/TurnTaking 产生 COMMIT。**T-6 修复**：缺口窗口内（序号不超过 horizon）该 generation 的任一事件都算"已存在"的证据，即使更新的快照先登记了这路输入，也要求确认边界；每次缺口对同一 generation 只记一次；最新状态序号仍负责过滤旧帧。回归：`test_snapshot_newer_than_a_gap_keeps_the_boundary_requirement`；**T-6 review（`4cb57c2`）验收，关闭**：review 用真实生产者线程独立复验了竞态（尾句不进 STT、无 COMMIT，新句 32 帧正文完整、恰好提交一次）、每次缺口只施加一次要求、generation 隔离 |
| ~~KD-15~~ | ~~`HostLog` 在 `try` 之外创建接收 socket，创建失败（例如沙盒 EPERM）时，之前建立的私有目录不会被清理（既存缺口，review 环境实际触发）~~ | 已关闭 | **T-3 修复**：socket 创建移入 `try`，失败时关闭已创建的 socket、删除目录、恢复 endpoint。回归：`test_local_endpoints.py::test_host_log_construction_failure_releases_its_directory`；**T-10T2**：该回归按规则移出（见 git 历史 `b46c4ea`），缺陷保持关闭；**T-10T3**（按 `c09f8dd` review）：作为资源回收回归恢复，保留 receiver、client 两个参数 |
| ~~KD-16~~ | ~~Host 日志收尾可能丢失最后一条记录：写线程会根据停止前最后一次空的 `select` 结果退出，漏掉随后才入队的记录。实际表现是 `alphaavatar dev`/`start` 因配置无效退出（退出码 2）时，偶尔不显示错误诊断~~ | 已关闭 | T-10T 整理时发现：16 核满载下，HEAD 原入口用例 10 次失败 5 次，空闲时不复现；`b46c4ea` review 用线程屏障确定性复现了这一交错，确认为既存 P2。修复要求：退出前重新确认队列已排空，保留关闭期限和脱敏，补确定性回归，保留入口测试的诊断断言；**KD-16 修复（基线 `84f2c6d`）**：`HostLog._listen` 每轮在 `select` 之前读取停止标志，只有在停止之后才开始、且结果为空的等待才退出；`close()` 是在最后一条记录入队之后才设置停止标志，所以这次等待之前的记录一定会被消费。有界批处理、`shutdown_timeout`、明确报错、脱敏和格式都不变。确定性竞态用例在原逻辑上 10/10 失败、修复后 30/30 通过，验证完成后按"只为修小 BUG 的测试不留在项目中"的规则移出项目（T-10T2）；入口用例的诊断断言保留；**`c09f8dd` review**：生产修复接受，但普通入口测试不能稳定替代，要求保留确定性回归和有界关闭场景；**T-10T3**：两项恢复为 `avatar-host/tests/test_host_log.py` 的常驻回归，反向验证中原逻辑和"停止后读完一批即退出"两种变异分别被发现；**`7c53c4a` 验收，关闭**：确定性诊断回归与有界关闭用例作为常驻测试保留 |
| O-10 | `voice.stt.model` 只在 `STTConfig.get_plugin` 中检查，`config check`（以及 `validate_plugin_settings`）能通过，`start`/`dev` 却在会话装配时以 `ValueError` 失败。`voice.tts.model` 在配置校验时就检查，两者不一致 | 仅记录 | T-10C 新增：Doctor 诊断会话在 `session.start` 报出 |
| O-11 | 模型解析在离线且文件缺失时，`resolve_url_file`/`resolve_hf_file` 先创建命名空间目录和锁文件，然后才报缺失，缓存中会留下空目录和锁文件 | 仅记录 | T-10C 新增：在空缓存上启动整个 Runner 计划时观测到 |
| O-12 | 默认 memory、persona、MCP 的 LanceDB Runner 在 `initialize` 时对 `"dimension-probe"` 做一次 embedding。每次启动都是一次外部调用，可能计费；缺 key 时 Runner 启动失败 | 仅记录 | T-10C 新增：因此 Doctor 启用这些插件时，Runner 启动也需要 `host.doctor.external_services` |
| O-13 | 测试基础设施：pytest-asyncio 在首个异步测试前调用 `asyncio.get_event_loop()`，进程里还没有设置过事件循环时，asyncio 会新建一个，此后无人关闭。之后某个同步测试的 `asyncio.run()` 把它从当前循环上换下，会话结束时 GC 报 `unclosed event loop` 和两个 AF_UNIX socket，pytest 以 exit 1 结束（所有测试均通过）。只在全量运行中出现 | 本轮修复，待 review | T-10C `9993aad` review 修复中发现：用临时插件记录事件循环创建栈定位；用 `git archive` 导出的 `9993aad` 代码与测试复现同样的 exit 1，确认既有。修复：根 `conftest.py` 的 `pytest_configure` 中 `asyncio.set_event_loop(None)`，pytest-asyncio 随后拿到"无当前循环"，不再新建；最小复现与全量均不再出现 |
| KD-17 | 轮次判定在判为轮次结束后，只等待缺失的转录 `transcript_wait_sec`（默认 0.75 s），超时就以 `transcript_timeout` 取消并退役候选，之后到达的 STT 终稿被拒（`retired_segment`）。真实分段 STT（`gpt-4o-transcribe`）从提交到终稿实测为 0.86 s 至 1.76 s。按模板默认配置（含 `my-avatar`），慢于 0.75 s 的 STT 会让用户整句语音被丢弃，没有回应 | 待用户决定，本批未改 | T-10C 真实验收（`6a593f2`）发现：Doctor 报告给出 HOLD +815 ms、CANCEL +1566 ms、终稿 +2442 ms 的链路。验收配置把该值设为 3.0 s 后，同一样本正常提交。可选修复：提高默认值、按 STT 能力（分段或流式）给默认值，或改为等到终稿或出错，再设上限 |

已撤回：「recall 结果包含 avatar owner」按 Q8 属于有意设计，不再列为缺陷。

处理规则：修复批次先写失败用例，修复后转绿。如果基线测试意外失败，停止并报告，经批准后才标记 `xfail(strict=True, reason="KD-n …")`，不使用 skip，也不放宽断言。T-1 起按用户要求：补测试时发现真实生产缺陷，保留最小失败复现（不标 xfail），报告后继续完成其他独立测试。

---

## 2A-1 最小测试基础设施

- 日期：2026-10-25
- 基线 HEAD：`1ab771aee300cc63c28be7d499d788289c101468`（与 `origin/dev/v0.6.9` 一致）
- 授权范围：2A-1 最小测试基础设施（21 个关键测试、根目录统一 `conftest.py`、现有 CI install job 运行 pytest、不修改生产代码）

### 1. 修改文件

| 类型 | 文件 | 说明 |
|---|---|---|
| 修改 | `pyproject.toml` | 仅 `[tool.pytest.ini_options]` |
| 修改 | `.github/workflows/quality.yml` | `install` job 新增一个 step |
| 新增 | `conftest.py` | 全仓统一隔离 / 资源所有权守卫 |
| 新增 | `avatar-core/tests/test_lifecycle.py` | 4 个测试 |
| 新增 | `avatar-core/tests/test_output_stream.py` | 4 个测试 |
| 新增 | `avatar-core/tests/test_perception_stream.py` | 3 个测试 |
| 新增 | `avatar-core/tests/test_input_trace.py` | 4 个测试 |
| 新增 | `avatar-agents/tests/inference_runner_samples.py` | 无模型的测试 Runner（非测试文件） |
| 新增 | `avatar-agents/tests/test_runner_process.py` | 5 个测试 |
| 新增 | `avatar-host/tests/test_cli_entrypoint.py` | 1 个测试 |
| 新增 | 实施日志 | |

生产代码改动：**0**。依赖、`uv.lock`、`.gitignore` 未改动。

### 2. 设计要点

#### pytest 配置

```toml
addopts = ["--import-mode=importlib", "--ignore=examples", "--strict-markers", "--strict-config"]
testpaths = ["avatar-core/tests", "avatar-agents/tests", "avatar-host/tests"]
pythonpath = ["avatar-agents/tests"]   # spawn 子进程按模块名导入测试 Runner
xfail_strict = true
faulthandler_timeout = 60
tmp_path_retention_policy = "failed"
filterwarnings = ["error::ResourceWarning", "error::pytest.PytestUnraisableExceptionWarning"]
```

#### 根目录 `conftest.py`（autouse）

所有守卫都以「当前测试开始前的基线」做差分，只处理本测试新增的资源，不触碰其他测试或进程已有的资源。

| 守卫 | 行为 |
|---|---|
| `isolated_environment` | 删除凭据类（KEY/TOKEN/SECRET/PASSWORD/CREDENTIAL）及 `AVATAR_*`、`ALPHAAVATAR_*`、`MEMORY_*`、`PERSONA_*`、`MCP_*`、`LIVEKIT_*`、`OPENAI_*`、`HF_*`、`XDG_*`、代理等变量；`HOME`、`TMPDIR`、`tempfile.tempdir`、cwd 指向 `tmp_path`；`ENV_FILE` 指向不存在的文件；离线开关置 1。测试结束后对比环境变量，被改动则恢复改动项并失败（只报告变量名，不输出值）。 |
| `network_denied` | 拒绝 `socket.connect`、`connect_ex`、`sendto`、`getaddrinfo`、`gethostbyname(_ex)`、`create_connection`，**包括 loopback 和 AF_UNIX**；`socketpair()` 不受影响。即使被测代码吞掉 `PermissionError`，测试也会在 teardown 时失败。 |
| `owned_child_processes` | 只针对测试期间新增的 `multiprocessing` 子进程：kill + join，然后判失败。 |
| `owned_tasks` | 只对 coroutine 测试生效：测试后新增的未完成 asyncio task 被 cancel 并判失败，失败信息列出 task 名。 |

**明确限制**：网络守卫是本解释器内的 monkeypatch，**不会继承到 spawn 子进程**，也不是进程级网络沙盒。本批的子进程只有测试 Runner 和 `alphaavatar --help/--version`，它们不联网是由代码构造保证的，没有强制隔离。子进程泄漏检查只覆盖 `multiprocessing`；`subprocess` 子进程靠测试自身的 `subprocess.run(timeout=...)` 回收。

#### Runner 测试的 fd 检查

`test_runner_process.py` 在测试内对比 `/proc/self/fd` 前后差分。比较前先 `resource_tracker.ensure_running()`，因为 stdlib 的 resource tracker 是进程级共享设施，不归 Runner 所有。没有 `/proc` 的平台跳过 fd 比对，进程回收检查照常执行。

#### CI

在 `install` job 中、`Verify lightweight public entrypoint` 之前加入 `Run deterministic offline tests`：

- `timeout-minutes: 5`，`PYTHONDONTWRITEBYTECODE=1`；
- `pytest -p no:cacheprovider --basetemp=$RUNNER_TEMP/pytest --durations=10`；
- 运行前后各做一次 `git status --porcelain --ignored`，用 `diff -u` 校验检出目录不变。

该 job 已经安装完整 workspace 和 dev group，所以没有额外安装成本。

### 3. 测试清单（21 个）

只断言运行契约（状态、顺序、资源、错误类型），不比对日志文本。墙钟只作为宽松的挂起保护（5 s / 30 s），不作为性能断言。

| 文件 | 测试 | 验证的契约 |
|---|---|---|
| lifecycle | `test_cancelled_caller_waits_for_owned_cleanup` | 调用方被取消时，仍先完成自有清理，再传播取消 |
| | `test_phases_start_in_order_and_stop_in_reverse` | phase 顺序启动、逆序停止 |
| | `test_start_failure_stops_every_owned_component_in_reverse` | 启动失败时逆序 stop 全部组件，包括未启动的后续 phase；错误可定位到失败的 phase |
| | `test_cancelled_start_converges_to_a_stopped_single_use_group` | 启动被取消后收敛到已停止状态，不能再次启动 |
| output_stream | `test_interrupt_bypasses_full_reliable_queue_and_blocked_publisher` | INTERRUPT 越过已满的可靠队列和阻塞中的发布方 |
| | `test_unreliable_subscriber_drops_oldest_and_never_blocks_publisher` | 不可靠订阅者丢弃最旧数据并准确计数，发布方不被阻塞 |
| | `test_fail_fast_overflow_retires_only_the_slow_subscriber` | 溢出失败只影响慢订阅者，失败显式抛出，其他订阅者正常收到数据 |
| | `test_cancelled_publisher_reaps_its_fanout_tasks` | 发布方被取消后，每个订阅者的 push task 都被回收 |
| perception_stream | `test_slow_consumer_never_blocks_publisher_and_sees_an_explicit_gap` | 环形缓冲不阻塞发布方，`missed_count` 显式报告缺口 |
| | `test_consumer_cursors_are_independent_and_monotonic` | 各消费者游标独立且只增不减，拒绝提交未来位置 |
| | `test_wait_for_pending_wakes_on_publish_and_times_out_without_data` | 有新发布时被唤醒，无数据时超时返回 |
| input_trace | `test_identities_are_salted_hashes_joined_across_stages` | ID 加盐哈希；同一 trace 内跨阶段可关联，不同 trace 之间不可关联 |
| | `test_invalid_records_are_counted_without_raising_or_retaining_content` | 非白名单字段只计数，不抛异常，不保留 |
| | `test_retention_is_bounded_by_count_and_ttl_with_compact_byte_accounting` | 记录数和 TTL 有上限；`retained_bytes` 等于紧凑 JSON 长度 |
| | `test_frozen_snapshots_are_bounded_and_never_nest` | freeze 有上限，不嵌套旧快照，字节计数准确 |
| runner_process | `test_round_trip_errors_and_close_release_the_child` | 往返 / None / RUN_ERROR 之后通道仍可用；诊断不含异常消息；close 回收子进程且 fd 无泄漏 |
| | `test_initialization_error_is_reported_and_reaped` | INIT_ERROR 只带类型和调用帧（脱敏）；子进程被回收 |
| | `test_dispatched_timeout_retires_the_process_instead_of_reusing_it` | 已派发的请求超时后进程被淘汰、不复用、被回收 |
| | `test_cancelled_queued_request_is_withdrawn_without_breaking_the_runner` | 排队中的请求被取消后撤回，Runner 保持健康 |
| | `test_cancelled_start_reaps_an_initializing_child` | 初始化期间取消（子进程会初始化 60 s）后，在挂起保护时间内收敛并回收 |
| cli_entrypoint | `test_base_cli_needs_no_models_credentials_or_workspace` | `--help`/`--version` 返回 0；不导入 torch/numpy/openai/qdrant/llama_cpp/livekit/omegaconf/plugins/configs；不在 cwd 或 HOME 下创建文件 |

说明：OutputStream 测试只验证队列语义，**不代表**已经验证完整音频播放链路的时延或独立性。

### 4. 验证结果

| 项目 | 命令 | 结果 |
|---|---|---|
| 全量（CI 方式） | `PYTHONDONTWRITEBYTECODE=1 uv run --no-sync pytest -p no:cacheprovider --basetemp=… --durations=10` | **21 passed in 2.22s** |
| 连续重复 | 同上 ×3 | 3/3 次 21 passed，2.22 s / 2.22 s / 2.22 s |
| 单文件独立执行 | 每个测试文件单独运行 | 4 / 4 / 4 / 3 / 5 / 1，全部通过 |
| 从包目录执行 | `cd avatar-core && pytest tests`；`cd avatar-agents && pytest tests` | 15 passed / 5 passed |
| 普通开发调用 | `uv run --no-sync pytest` | 21 passed（会生成被 gitignore 的 `.pytest_cache`，验证后已删除） |
| 检出目录副作用 | 前后 `git status --porcelain --ignored` 做 diff | 无差异 |
| 临时文件 | 测试通过后 `find basetemp -type f` | 0 个文件（只保留空的 basetemp 根目录） |
| 用户目录 | `~/.alphaavatar*`；当前 shell 的 `MEMORY_VDB_*` 等变量 | 均不存在，未受影响 |
| Ruff | `ruff check .`；`ruff format --check .` | All checks passed；624 files already formatted |
| Workspace | `python scripts/check_workspace.py` | consistent: 16 members |
| pre-commit | `pre-commit validate-config` | 通过 |
| Lock | `uv lock --check` | 通过（无依赖变化） |
| 许可头 | `scripts/add_copyright.py <新文件>` | 无需插入 |
| 发布包 | `uv build --offline --package alpha-avatar-{core,agents,host}`，输出到 scratchpad | 3 个 wheel + 3 个 sdist，`tests/`、`conftest`、`inference_runner_samples` 条目数均为 0 |
| CI YAML | `yaml.safe_load(quality.yml)` | 解析通过 |

最慢的 5 个测试都在 runner_process：1.00 s（初始化期间取消；测试里固定等待 0.5 s，再加 `close_timeout=0.5`）、0.43 s、0.31 s、0.13 s、0.13 s。

### 5. 资源隔离：反例验证

反例不提交。它们放在 scratchpad，以 `-p conftest` 加载真实的根目录 `conftest.py` 运行，同时在外部注入 `OPENAI_API_KEY=sk-should-not-leak` 和 `MEMORY_VDB_TYPE=x`。

| 反例 | 结果 |
|---|---|
| 泄漏 asyncio task | ERROR：`Test leaked asyncio tasks: ['leaked-sleeper']` |
| 修改环境变量 | ERROR：`Test changed process environment variables: ['MEMORY_VDB_TYPE']` |
| 连接外网 IP | FAILED（PermissionError），teardown 再报 ERROR |
| loopback / AF_UNIX connect，且被测代码吞掉异常 | ERROR：`Test attempted network access: ['socket.connect']` |
| DNS `getaddrinfo` | FAILED，teardown 再报 ERROR |
| 遗留 spawn 子进程 | ERROR：`Test leaked child processes: ['leaked-child']`，该进程已被 kill |
| 正向对照 | PASSED：`socketpair` 可用；注入的密钥和 VDB 变量已被清除；HOME 位于临时目录 |
| 密钥是否出现在输出中 | `sk-should-not-leak` 出现次数为 0 |

### 6. 已知基线缺陷

见文首的统一 KD 表。

### 7. 剩余风险

1. **CI 调度时序**：有两处依赖 `asyncio.sleep(0)` 循环让出调度：排队请求在第一个请求持有锁期间被取消；发布方阻塞在满队列上。这两处都不涉及 I/O，在 asyncio 下是确定的。Runner 测试的时间参数（0.2 s 超时、0.3 s 执行）对应的是子进程实际要 sleep 60 s 的场景，余量足够。CI 上首次真实运行的结果需要在审计时确认。
2. **网络守卫只覆盖本解释器**（见第 2 节），后续需要网络的测试必须显式声明并另行审查。
3. **共享解释器**：`pythonpath` 把 `avatar-agents/tests` 加入所有测试的 `sys.path`；模块名 `inference_runner_samples` 是唯一的，风险低。
4. **本机运行环境**：机器上有一个 2026-08-17 起运行的旧版 AlphaAvatar 进程（Python 3.11 forkserver）。测试没有连接它的任何 endpoint，也没有争用其资源。

### 8. 未做事项（按授权）

未实现 Doctor/Test/Check CLI、Probe Framework、ScriptedStreamingLLM、ConfigService、Profile/Bundle、Runner 配置迁移、ALPHAAVATAR_HOME 迁移；未修复任何 KD 缺陷或 O-1；未 commit、push，也未开始 2A-2。

### 9. 审计修正（2026-10-25，基线 `780091c752ee232113972c0114f3651935607ae3`）

用户与 ChatGPT 审计了 `780091c`：GitHub Quality 的 lint、build、install 均通过，远端结果 21 passed。审计指出两个测试的有效性问题，本轮**只修改这两个现有测试**。测试数量仍为 21，生产代码零修改。

#### 9.1 `test_cancelled_publisher_reaps_its_fanout_tasks`（`avatar-core/tests/test_output_stream.py`）

- **问题**：取消 Publisher 后先调用 `stream.aclose()`，再依赖全局 Task 守卫检查泄漏。关闭 Stream 本身会唤醒并释放被阻塞的 push，可能掩盖 Publisher 没有自行回收 fan-out Task 的问题。
- **修正**：
  - 创建 Publisher 前先记录 `asyncio.all_tasks()` 基线，阻塞后从差集中取出协程为 `OutputSubscription.push` 的任务，作为本次发布创建的 fan-out Task。
  - 取消前断言：恰好有 1 个 push 待完成（写入已满队列的那个），且 Publisher 尚未完成。
  - **在 `aclose()` 之前**断言：这些 fan-out Task 全部 `cancelled()`，并且基线之后新建的任务已全部结束（`all_tasks() - before == set()`）。只统计本测试创建的 Task，不依赖全局守卫作为唯一证据。

#### 9.2 `test_cancelled_queued_request_is_withdrawn_without_breaking_the_runner`（`avatar-agents/tests/test_runner_process.py`）

- **问题**：依靠固定次数的 `asyncio.sleep(0)` 推进任务，没有在取消前证明第一个请求正在占用 Runner、第二个请求处于排队且未派发。
- **修正**：
  - 新增模块内辅助函数 `wait_until(condition, failure)`：在 `HANG_GUARD` 内以 1 ms 间隔轮询条件，超时则带具体原因 `pytest.fail`。它不是新测试。
  - 只读检查现有的 `RunnerProcess._requests`（每个 exchange 的 `dispatched` 标志）和 `_lock`，不新增生产接口。
  - 第一个条件：串行锁已被持有，且已登记的 exchange 状态为 `[True]`，即第一个请求已派发并占用 Runner。
  - 第二个条件：状态为 `[True, False]`，且第二个 exchange 的协程状态为 `inspect.CORO_SUSPENDED`。获取串行锁是派发前唯一的挂起点，所以这说明它已在锁后等待、尚未派发。
  - 取消后：有界等待注册表只剩第一个 exchange，断言被撤回的 exchange 为 `cancelled()`；第一个请求返回 `b"sleep:1"`；Runner 仍然 alive；随后 `run(b"next") == b"next"`。被撤回的请求如果到达了子进程，这个响应就会错位。
  - 第一个请求的工作负载从 `sleep:0.3` 改为 `sleep:1`，只是为了留出观察窗口，不作为正确性证明。错过窗口时测试会带原因失败，不会误判通过。

#### 9.3 变异验证（只在内存中进行，未提交）

在 scratchpad 中通过 `-p mutants` 插件对运行时做内存级 monkeypatch，仓库文件不变：

| 变异 | 旧测试（`780091c`） | 新测试 |
|---|---|---|
| A：Publisher 被取消时不回收 fan-out Task | **1 passed**（被 `aclose()` 掩盖） | FAILED：`all(task.cancelled() for task in fanout)` 在 `aclose()` 之前失败 |
| B：取消排队请求时不撤回 exchange | **1 passed**（被掩盖） | FAILED：`the queued exchange was not withdrawn`；泄漏的 Runner 被进程守卫 kill |
| 无变异（对照） | — | 2 passed |

#### 9.4 验证结果

| 项目 | 结果 |
|---|---|
| 全量 pytest（CI 方式）×3 | 3/3 次 21 passed（约 2.93 s）；每次 basetemp 文件数为 0 |
| 修改的两个文件各单独运行 ×3 | `test_output_stream.py` 3/3 次 4 passed；`test_runner_process.py` 3/3 次 5 passed |
| 检出目录（含 ignored） | 前后 `git status --porcelain --ignored` 无差异；无 `.pytest_cache` |
| Ruff | `ruff check .` All checks passed；`ruff format --check .` 624 files already formatted |
| Workspace / Lock | `check_workspace.py` consistent: 16 members；`uv lock --check` 通过 |
| 改动范围 | `git diff --stat`：只有上述两个测试文件，+52/−7；无任何非测试文件改动 |

最慢的测试变为 `test_cancelled_queued_request_is_withdrawn_without_breaking_the_runner`，1.14 s，原因是第一个请求的工作负载为 1 s。

#### 9.5 剩余说明

- 9.2 读取的是 `RunnerProcess` 的私有状态（`_requests`、`_lock`）。这是按审计要求「使用现有状态，不新增生产接口」做的取舍：Runtime 内部重构时，这个测试需要同步更新。
- 未 commit、未 push，也未开始 2A-2。

---

## 2A-2a Require Explicit Avatar ID

- 日期：2026-10-25
- 基线 HEAD：`5c2c5b719b3bbfacc1b297085896f4ca7463d099`（与 `origin/dev/v0.6.9` 一致）
- 授权范围：仅 2A-2a。`avatar.id` 与 `avatar` 段改为必填，移除默认 UUID；不涉及 Workspace 创建、配置导入或进程环境变量传递

### 1. 修改文件

| 类型 | 文件 | 修改 |
|---|---|---|
| 修改 | `avatar-agents/alphaavatar/agents/configs/avatar_info_config.py` | `id: str = Field(min_length=1, max_length=256)`；删除 `import uuid`；`check_id` 规则不变 |
| 修改 | `avatar-agents/alphaavatar/agents/configs/avatar_config.py` | `avatar: AvatarInfoConfig`，去掉 `default_factory` |
| 修改 | `docs/avatar-workspace-layout.md` | 删除 "An omitted ID is generated"，改为说明 `avatar.id` 必填、缺失即拒绝 |
| 新增 | `avatar-agents/tests/test_avatar_config.py` | 1 个参数化测试（2 个用例） |
| 新增 | 实施日志 | |

其他生产代码、依赖、`uv.lock` 和 CI 均未改动。

### 2. 行为契约

- YAML 没有 `avatar` 段：抛出 `ValidationError`，位置为 `avatar`，类型 `missing`。
- 有 `avatar` 段但没有 `id`：位置为 `avatar.id`，类型 `missing`。
- CLI 沿用现有的 `format_error` 输出位置，实测输出为 `error: ValidationError` / `fields: avatar.id`，退出码为 2。
- 不再存在自动生成 ID 的路径。缺少 ID 时，校验在 Workspace 解析之前就失败，不创建任何目录。
- 下列内容均未改动：`work_dir` 语义、`model_post_init`、环境变量、WorkspacePaths、Host loader、restore。restore 快照中始终包含 `id`，因此不受影响。

### 3. 测试

`test_missing_avatar_identity_is_rejected_instead_of_generated[missing-avatar | missing-id]`：

- 断言错误列表恰好是 `[(location, "missing")]`。
- 断言临时 HOME 为空：被拒绝的配置不会创建 Workspace。
- 用 `mock.patch.dict(os.environ)` 隔离环境变量，并断言变化集合 ⊆ `{MEMORY_VDB_CONFIG, MEMORY_VDB_TYPE, PERSONA_VDB_CONFIG, PERSONA_VDB_TYPE}`。原因是 KD-2：Memory 和 Persona 的默认工厂即使在配置被拒绝时也会写这些变量。这里只放行已知的这几个名字，其余任何环境变量写入（例如 `AVATAR_WORK_DIR`）仍会导致测试失败。
- 配置模块在测试文件顶部导入，因为导入链中的第三方库会在导入时修改进程环境变量（见 O-2）。这只是测试层面的安排，**不代表配置校验已经没有副作用**。

#### 变异验证

在 scratchpad 中复制 `alphaavatar.agents` 后修改副本，通过 `PYTHONPATH` 优先加载。仓库文件没有改动。

| 变异 | 结果 |
|---|---|
| M0 不修改（对照组） | 2 passed |
| M1 恢复 UUID 默认值 | `missing-id` 失败：`DID NOT RAISE ValidationError` |
| M2 恢复 `avatar` 的 `default_factory` | `missing-avatar` 失败：位置变成 `('id',)`，而不是 `('avatar',)` |
| M3 配置被拒绝时写入 `AVATAR_WORK_DIR` | 2 个用例都失败：变化集合超出 KD-2 白名单 |
| M4 配置被拒绝时在 HOME 下创建目录 | 2 个用例都失败：临时 HOME 不为空 |

### 4. 验证结果

| 项目 | 结果 |
|---|---|
| 完整 pytest（CI 方式：`-p no:cacheprovider --basetemp`）×3 | 3 次均为 23 passed，原有 21 个 + 新增 2 个，约 4.71 s；basetemp 中 0 个文件 |
| 检出目录（`git status --porcelain --ignored`） | 前后一致 |
| `ruff check .` / `ruff format --check .` | 通过 / 625 个文件已格式化 |
| `scripts/check_workspace.py` / `uv lock --check` | 16 个成员一致 / 通过 |
| 5 个示例 YAML（每个在独立进程中执行 `load_application`，临时 HOME，禁网） | 全部解析成功，路径为 `<base>/<id>`，无联网尝试 |
| 去掉 `avatar.id` 的 demo.yaml 交给 `alphaavatar start` | 拒绝，输出 `fields: avatar.id`，exit=2，HOME 下没有新文件 |

### 5. 剩余风险

- **测试耗时增加**：pytest 总耗时从约 2.9 s 增加到约 4.7 s，原因是收集阶段导入了配置包（torch、cv2 等）。
- **R3（KD-1 中仍未解决的部分）再次复现**：在同一进程里依次加载 5 个示例时，Workspace 路径逐级嵌套：`alphaavatar_tools/alphaavatar_demo/alphaavatar_airi/…`。原因是上一次校验写入的 `AVATAR_WORK_DIR` 被下一次当成 base 使用。每个示例单独一个进程加载时都正确。按授权，本批不修复，留给 2A-2b。
- **本批不保证的事项**：合法配置在校验时仍会创建 Workspace 并写入环境变量；Memory 和 Persona 仍可能在校验时构造 QdrantClient 并联网。

### 6. 已知缺陷

见文首的统一 KD 表。本批的更新：KD-1 移除随机 UUID；KD-2 补充 HTTP 版本请求；KD-5、KD-6、KD-7 按审计更新表述；新增 O-2。

### 7. 未做事项（按授权）

没有修改 Workspace 创建、配置导入或环境变量传递；没有实施 ApplicationPaths、2A-2b、2A-C1；没有修复任何 KD/O 项；没有 commit 或 push。

---

## 2A-C1 Remove unused Host diagnostics

- 日期：2026-10-26
- 基线 HEAD：`468c8075ec0e215fb34ba3f3019903fb0bb32745`（与 `origin/dev/v0.6.9` 一致）
- 授权范围：仅删除 `avatar-host/alphaavatar/host/diagnostics.py`，并记录实施日志

### 1. 修改文件

| 类型 | 文件 |
|---|---|
| 删除 | `avatar-host/alphaavatar/host/diagnostics.py`（118 行） |
| 新增 | 实施日志（现为本文件的本节） |

`alphaavatar.core.log.diagnostics`、其他生产代码、测试、依赖、`uv.lock` 和 CI 均未改动。没有新增兼容模块、别名、`host/diagnostics/` 包或 DiagnosticService。

### 2. 删除依据（审计结论）

- 仓库代码、配置、文档、CI 和脚本中都没有对 `alphaavatar.host.diagnostics` 的直接或动态引用。只有历史日志中的 KD-9 条目提到它，按授权保留。
- `format_error` 的 5 处使用（Host CLI、Host 进程入口、Runner 子进程、Core 日志客户端、Loop 插件）全部来自 Core。
- 被删除的文件是 Core 版本的旧分叉：按广度优先遍历异常链，没有 Core 版本中"先显示叶子原因"的预算保留。删除不会丢失任何正在使用的行为，也不需要合并回 Core。

### 3. 验证结果（删除后基于实际代码执行）

| 项目 | 结果 |
|---|---|
| 完整 pytest（CI 方式：`-p no:cacheprovider --basetemp`，`PYTHONDONTWRITEBYTECODE=1`）×3 | 3 次均为 23 passed，约 4.95 s；basetemp 中 0 个文件 |
| `ruff check .` / `ruff format --check .` | 通过 / 624 个文件已格式化（删除前为 625 个） |
| `scripts/check_workspace.py` / `uv lock --check` / `pre-commit validate-config` | 16 个成员一致 / 通过 / 通过 |
| `uv build --all-packages --no-sources --build-constraints`（离线，输出到 scratchpad） | 成功构建 32 个产物（16 个 wheel、16 个 sdist） |
| 产物元数据 | 32 个产物的 `METADATA`/`PKG-INFO` 都通过 `packaging.metadata` 严格校验；`twine check` 未执行，原因见第 5 节 |
| 发布包内容 | 32 个产物都不含 `host/diagnostics.py`。Host wheel 和 sdist 都从 56 个条目减为 55 个，唯一被移除的是 `alphaavatar/host/diagnostics.py`，没有新增条目 |
| 全新解释器 | `find_spec("alphaavatar.host.diagnostics")` 为 `None`；`import` 抛出 `ModuleNotFoundError`；`alphaavatar.core.log.format_error` 来自 `alphaavatar.core.log.diagnostics` |
| Core diagnostics | `avatar-core` 相对 HEAD 无差异；blob 仍为 `7b7804ed` |
| CI install 作业脚本（`ALPHAAVATAR_MODEL_OFFLINE=1`） | 16 个包版本模块全部可导入；8 个 native lifecycle 组件契约通过 |
| CLI `--help` / `--version` | exit 0 / 输出 `AlphaAvatar 0.6.8` |
| CLI 配置错误（临时 HOME，禁网） | 缺 `avatar.id`：`error: ValidationError`、`fields: avatar.id`，exit 2；配置文件不存在：`error: FileNotFoundError errno=2`，exit 2。输出与删除前逐行一致，无联网尝试，HOME 下没有新文件 |
| 检出目录（`git status --porcelain --ignored`） | 所有检查前后一致；只有 ` D avatar-host/alphaavatar/host/diagnostics.py` 和实施日志 |

### 4. KD-9 关闭记录

- **KD-9**：`host/diagnostics.py` 没有任何引用，与 Core diagnostics 重复，并会与计划中的 `host/diagnostics/` 包同名冲突。
- **状态：已解决（2A-C1）**。文件已删除；全新解释器中不可导入；发布包中不再包含；没有遗留兼容入口。

### 5. 剩余风险与未完成项

- **`twine check` 未在本地执行**：锁定的 build 依赖组中，twine 的传递依赖（如 `cffi==2.0.0`、`readme-renderer`）不在本地 uv 缓存里，而联网下载没有授权。作为替代，本地用 `packaging.metadata` 严格校验了全部产物的元数据。CI 的 Build 作业会执行 `twine check`。本批没有改动任何 README 或项目元数据。
- **外部导入方**：v0.6.8 发布物中包含该模块，直接导入 `alphaavatar.host.diagnostics` 的外部代码会失败。按"不兼容旧行为"的原则，不提供兼容入口。
- **本地环境差异（不影响 CI）**：
  - 被 git 忽略的 `__pycache__` 中仍有 `diagnostics.cpython-311.pyc`。Python 3.13 不会加载它（`find_spec` 为 `None`），它也不进入产物；它不在仓库内，未处理。
  - 本地 `.venv` 的 editable 安装元数据仍报告 0.6.7，源码版本为 0.6.8；CI 会重新同步，未处理。
  - 本地 uv 是 0.11.11，CI 固定使用 0.10.0。

### 6. 已知缺陷

见文首的统一 KD 表。本批的更新：KD-9 关闭；KD-1～KD-8、O-1、O-2 不变。

### 7. 未做事项（按授权）

没有修改 Core diagnostics 或其他生产代码；没有新增测试、依赖或抽象；没有创建 `host/diagnostics/` 或 DiagnosticService；没有开始 2A-2b；没有修复 KD-1～KD-8、O-1、O-2；没有 commit 或 push。

---

## T-1 必要回归测试补全与 KD/O 复核

- 日期：2026-11-02
- 基线 HEAD：`f708b266ef656b35d014b6ef4a04d00b2eda89ef`（`dev/v0.6.9`；ChatGPT 已完成本轮源码 review 和离线回归）
- 授权范围：只补测试和审核，并更新本日志。不修改生产实现，不建设新的测试框架或 CLI 功能
- 说明：2A-C1 之后到 `f708b26` 之间的 25 个提交没有对应的批次日志，本节只记录本轮对当前代码的复核结果

### 1. 修改文件

生产代码改动：**0**。依赖、`uv.lock`、CI 均未改动。

| 类型 | 文件 | 说明 |
|---|---|---|
| 修改 | `pyproject.toml` | `testpaths` 增加 `avatar-plugins/*/*/tests`；注册 `stress` marker |
| 修改 | `conftest.py` | 新增 `--stress-seconds` 选项与 `stress_seconds` fixture；新增按需启用的 `owned_endpoints`（只放行测试自己登记的 AF_UNIX 路径或回环地址）和 `socket_root`（AF_UNIX 短路径，结束时检查无残留）。原有四个守卫未改 |
| 修改 | `avatar-agents/tests/test_avatar_config.py` | 2 → 4 个，去掉 KD-2 白名单 |
| 修改 | `avatar-agents/tests/inference_runner_samples.py` | 追加 `JournalRunner`、`SecondJournalRunner`、`FailingCloseRunner`，原有 Runner 不变 |
| 新增 | `avatar-agents/tests/launch_runner_samples.py` | spawn 子进程可导入的启动配置探针 Runner（非测试文件） |
| 新增 | 17 个测试文件 | 见第 3 节 |

插件测试放在各插件包自己的 `tests/` 下，靠 `testpaths` 通配收集。发布包不包含这些目录（见第 4 节）。

### 2. KD/O 复核结论

逐项对照当前代码，结论已写回文首统一表，历史描述保留，以下只列结论：

| 项 | 结论 | 依据 |
|---|---|---|
| KD-1、KD-2、KD-3 | 已修复，关闭 | 配置校验无环境写入、无目录创建、无客户端构造；Runner 读启动快照 |
| KD-4、KD-5 | 已修复，关闭 | 真实 lancedb 下引号/谓词形式的 user_id 互不串用；保存失败显式报错 |
| KD-6 | 仍存在 | 状态只写 debug 日志 |
| KD-7、KD-8 | 未变 | 默认值未改 |
| KD-10 | 主体已修复 | 剩余：跨身份检索（延期政策）、解析前 Turn 的画像未覆盖 |
| O-1 | 仍存在 | 实测 0.50 s / 2.00 s，与 `close_timeout` 相等 |
| O-2 | 部分改善 | 约 0.92 s，不再导入 torch |
| 新增 | KD-11、KD-12、O-3～O-7 | 见第 6 节 |

`test_avatar_config.py` 收紧后的契约：配置被接受或被拒绝时，进程环境变量与校验前**完全一致**，HOME、TMPDIR、cwd 保持为空，Qdrant 同步／异步客户端和 `lancedb.connect` 均未被构造。配置包仍在收集阶段导入，注释保留 O-2「第三方模块导入副作用」与「配置校验副作用」的区别。

### 3. 新增覆盖

原 23 个 → 现 144 个（净增 121 个，`test_avatar_config.py` 的 2 个已改写）。测试使用真实的 Runtime（AvatarRuntime、Session、Perception、Turn、Output、Participants、InferenceRuntime/Executor、ProcessSupervisor）、SQLite、临时 workspace、本地 lancedb 和真实 spawn。离线替身只用于外部 LLM/embedding/TTS/STT/端点模型、LiveKit 会话主体和推理传输记录。并发由事件和屏障控制，墙钟只作挂起保护。

#### 3.1 配置与 Runner 输入（31 个）

| 文件 | 数量 | 覆盖 |
|---|---|---|
| `avatar-agents/tests/test_avatar_config.py` | 4 | 见第 2 节 |
| `avatar-host/tests/test_application_config.py` | 18 | 同进程按 alpha→beta→alpha 加载，路径与凭证不串（R3 回归）；home 优先级 YAML `application.home` > `ALPHAAVATAR_HOME` > 平台默认（linux/XDG/darwin/win32）；显式 `cache_root`/`workspace_root`；拒绝 `AVATAR_WORK_DIR`、`ALPHAAVATAR_MODEL_CACHE`、相对路径、`avatar.work_dir`；`restore_application` 在环境变量全部改变后仍保持冻结的路径、vdb、MCP token 和推理快照；加载不建目录 |
| `avatar-agents/tests/test_runner_launch.py` | 9 | `RunnerLaunch` 的输入校验与禁止重配；进程内 Runner 与真实 `InferenceRuntime(launch=…)` spawn 的 Runner 读到同一份启动配置（子进程环境被改也不影响）；按配置选择 memory/persona 的 lancedb 或 qdrant、speaker/face、MCP，重建计划与准备的计划一致，计划冲突或被篡改时拒绝；真实 Memory/Persona/MCP 工厂实际调用的 method 等于所选 Runner 的 `INFERENCE_METHOD`；真实 Qdrant/lancedb/MCP Runner 只使用启动快照，不再读取 `QDRANT_*` 或占位符环境变量 |

#### 3.2 身份、历史 Context 与数据归属（15 个）

| 文件 | 数量 | 覆盖 |
|---|---|---|
| `avatar-core/tests/test_session_identity.py` | 5 | 被动 B→A、主动 A→C（C 从未被感知或提名）、改回、解绑都被接受；participant_id 不变，每个版本都保留；迟到的旧 basis 为 STALE，评估期间 Session 变化时 CAS 失败；事件流有界缺口不影响身份历史；工作线程改身份能唤醒消费者 |
| `avatar-agents/tests/test_participant_identity.py` | 5 | device、participant、user 三类 ID 互相独立；已提交 Turn 的 actors 不被改写，已捕获的写入保留旧身份路径；Agent 改绑使用自身 Turn 和版本，不回退到最新 Turn；迟到识别结果不能重开已淘汰或已退役的关联；Memory 批次不把旧 Turn 改归给纠正后的用户 |
| `avatar-plugins-loop/tests/test_identity_switch.py` | 4 | Agent 改绑 A→C 后本次 run 继续完成，新请求按 C 准备前缀，并保留已接受的工具调用；B→A 之后迟到的 B 模型输出不交付、不进入新请求；身份切换期间返回的 B 私有检索结果不进入新 Context；身份未变时缓存更新不重写已捕获前缀 |
| `avatar-plugins-context/tests/test_identity_switch.py` | 1 | 纠正后为 B 捕获的前缀被拒绝构建，B 那一轮已接受的历史原样保留 |

没有加入"只能修改未识别身份"或"目标必须先被感知提名"之类的断言。

#### 3.3 Memory／Persona（33 个）

| 文件 | 数量 | 覆盖 |
|---|---|---|
| `avatar-plugins-memory/tests/test_memory_runtime.py` | 9 | 抽取失败不推进 checkpoint，输入以原生 TurnSnapshot 保留；成功但结果为空时正常推进；Turn 窗口已淘汰时，154 条输入、6 万字符在关闭时一次完整抽取，没有定时、分块或后台任务；两个 Context 中任一个失败或被取消时，另一个提交完成后才关闭 Store；ENV 失败批次只重试自己的范围，不吞并新批次，重试耗尽后不跨过空洞提交；持久化重放不回退、不覆盖新 checkpoint（SQLite）；1 个 stress |
| `avatar-plugins-persona/tests/test_persona_runtime.py` | 8 | Turn 缺口不确认、不画像；只有完成启动后的正常关闭才写画像/VDB/`runtime_state.md`，启动被取消和同 tick 取消时都不写；Provider 吞掉取消后返回的 delta 被丢弃；VDB 保存失败的三种形态都报错（KD-5） |
| `avatar-plugins-persona/tests/test_persona_profile.py` | 11 | 来源优先级 chat > face > speech，与到达顺序无关；缓存中的 chat 事实不被传感器覆盖；append/remove 的 6 种乱序都收敛，重复投递幂等；runtime_state 重复和迟到保存幂等；lancedb 引号 user_id 隔离（KD-4） |
| `avatar-plugins-persona/tests/test_persona_sensors.py` | 5 | Speaker/Face 的向量与属性只进入各自 Participant；旧 generation 或已取消 source 的迟到结果不绑定身份，并以新 generation 结果作为 FIFO 屏障，证明迟到结果确实被处理过 |

复杂多人历史抽取和误识别纠错政策按要求没有扩展。

#### 3.4 语音时序、输出和取消（24 个）

| 文件 | 数量 | 覆盖 |
|---|---|---|
| `avatar-core/tests/test_output_runtime.py` | 9 | 打断后已接纳的媒体不交付，AUDIO_COMPLETE barrier、INTERRUPTED 回执、interrupted final transcript 仍完成；barrier 排在可靠反压中的帧之后；旧 Run 的内容已进入队列也会被扣留；结束发布超时会让交付失败关闭，不挂起；调用方取消后 publication 和 fan-out 在 `aclose()` **之前**已回收；被撤销 Run 的结束事实取消时视为被取代；interrupt 队列溢出：非可靠订阅者只淘汰自己，可靠订阅者导致交付失败关闭；1 个 stress |
| `avatar-plugins-router/tests/test_speech_synthesis.py` | 9 | 连续短句时 PCM 逐字节正确，最终 alignment 连续，时长等于实测 PCM；alignment 容量压力只暂停短句准入，不影响已准入的 PCM；慢字幕消费者不拖慢 PCM；barge-in/stale-run × 句中/等待下一句：旧 PCM 和文本不交付，TTS 流和任务在 stop 之前已回收，收尾事实完成；KD-12 复现；1 个 stress |
| `avatar-plugins-router/tests/test_speech_transcription.py` | 6 | speech→STT→candidate→decision→turn.committed 的 InputTrace 证据链有界、加盐哈希、不含原文；transcript 超时后迟到的 final 不复活 candidate；旧 source generation 的流、迟到帧和迟到识别结果都被退役；重复帧、段后迟到帧、帧序缺口不进入 provider；段退役后同流迟到 final 记为 stale；SPEECH_CANCELLED 取消 candidate |

#### 3.5 跨组件生命周期与 Runner（17 个 + 3 个 stress）

| 文件 | 数量 | 覆盖 |
|---|---|---|
| `avatar-agents/tests/test_inference_runtime.py` | 9 | 不同 method 独立推进，同一 method 当前串行、同进程；客户端/服务端容量拒绝不影响已接纳请求；已派发超时淘汰进程，SIGKILL 后 `recover_failed_runners` 换新 pid，尝试过的请求不重放，`restart_limit` 生效；已派发后客户端取消，服务端消化旧响应，下一调用只拿到自己的结果；部分启动失败、启动中取消、某个 Runner close 失败时，所有子进程、fd、socket 目录和 endpoint 环境变量都被回收；3 轮启停无泄漏；KD-11 复现 |
| `avatar-agents/tests/test_runtime_lifecycle.py` | 3 | Loop/Context 收尾时 Provider、推理、Output 仍可用；某个收尾步骤失败或被取消不跳过其余资源；关闭调用方被取消时，等全部释放后才传播取消 |
| `avatar-host/tests/test_host_lifecycle.py` | 5 | `create_avatar_runtime` 回滚时推理仍可用，回滚失败时保留原始错误；启动取消先回滚再传播；真实 `ExecutionManager`/`ProcessSupervisor`/entrypoint 子进程在收到停止信号后仍完成一次推理，Host 释放共享推理时 `all_reaped=True`；子进程未回收时不释放推理，其余步骤照常执行 |
| `avatar-agents/tests/test_runner_stress.py` | 3（stress） | 见第 5 节 |

`host.processes.capacity` 是会话执行容量，不是 Runner 并行度；可配置的 Runner 并行尚未实现，没有当作已有功能测试。

#### 3.6 变异验证（只在内存中修改，仓库文件不变）

各领域用 scratchpad 中的 `-p` 插件对生产代码做内存 monkeypatch，以下变异都会让对应测试失败：

- 校验时写 `MEMORY_VDB_TYPE`；恢复时重新读 `QDRANT_URL`；Memory 工厂固定用 lancedb；`config_for` 合并环境变量；上次加载路径被当作 base（R3）。
- `identity_basis_is_current` 恒为 True；request_identity 跳过版本检查；Memory 用当前身份重写 Turn actors；`_memory_is_current` 恒为 True。
- 抽取失败仍推进 checkpoint；prompt 截断到 32768 字符；增加后台历史任务；丢弃 128 条之前的输入；finalize 去掉 `return_exceptions`；忽略 Turn 缺口；启动被取消后仍 finalize；去掉 `cancelling()` 检查；不转义 user_id；忽略 VDB 保存的 error 字段。
- delivery guard 忽略打断；调用方取消后不回收 publication；STT 不退役旧 generation。
- AvatarRuntime 先关推理再关 Foundation；Host 去掉"子进程全部回收"门槛；Host 在 manager 之前关闭推理；InferenceRuntime 遇到第一个关闭失败就停止；RunnerProcess 已派发失败后不淘汰进程。

例外：Face/Speaker 的迟到结果保护有多层，单独去掉一层的变异会存活。已用探针确认测试确实走到了迟到路径。

### 4. 实际运行命令与结果

均在 `cd /home/ecs-user/AlphaAvatar && source .venv/bin/activate` 之后执行。

| 项目 | 命令 | 结果 |
|---|---|---|
| 全量（CI 方式）×3 | `PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider --basetemp=<scratchpad>/ptN --durations=10` | 3 次均为 **2 failed, 142 passed**，约 19.5–20.5 s。失败的始终只有 KD-11、KD-12 两个复现。basetemp 只保留失败用例的 1 个文件（retention=failed），`/tmp/aa-*` 无残留 |
| 检出目录 | 前后 `git status --porcelain --ignored` 做 diff | 无差异 |
| 各包目录单独运行 | `cd <pkg> && pytest tests`（8 个目录） | core 29、agents 37+1F、host 24、memory 9、persona 24、router 14+1F、loop 4、context 1，合计 144 |
| 单文件 ×3 | 各领域分别执行 | 全部稳定，结果与全量一致 |
| Ruff | `ruff check .`；`ruff format --check .` | All checks passed；668 files already formatted |
| Workspace/Lock/pre-commit | `scripts/check_workspace.py`；`uv lock --check`；`pre-commit validate-config` | 16 members consistent；通过；通过 |
| 许可头 | 检查所有新增/修改的 `.py` | 均为 "Copyright 2026 AlphaAvatar project" |
| 发布包 | `uv build --offline --package <8 个相关包>`，输出到 scratchpad | 16 个产物中 `tests/`、`conftest`、`*_runner_samples` 条目均为 0 |

最慢的用例：ENV 重试 `[recovered]` 2.00 s（调度器真实退避）、Runner 故障恢复 1.64 s、ENV `[exhausted]` 1.50 s、Host 子进程回收 1.32 s。全量从约 4.6 s 增加到约 20 s，仍在 CI 测试步骤 5 分钟的限制内。

警告：28 条 DeprecationWarning，全部来自 O-6，未压制。

### 5. 合成压力 / 长测入口

- 入口：`pytest -m stress --stress-seconds=<N> -s`。
- 默认 `--stress-seconds=0` 时，每个 stress 用例只跑一轮有界的确定性流程，随默认命令和 CI 一起收集并执行。设置 N 后，每个用例循环 N 秒，并打印计数和延迟。
- 不变量断言在每一轮都执行：无丢失、无重复、无错发，无重放，子进程、fd、socket 目录、环境变量无泄漏，PCM/barrier/alignment 精确，输入全部抽取一次。
- 下表是**合成结果**，在共享开发机上测得，只用于发现回归和作为后续 Doctor/Check/Test 的验收基线，**不代表实机或真实服务的性能**。

| 用例 | 默认（一轮，6 个共 3.7 s） | `--stress-seconds=15`（6 个共 93.6 s） |
|---|---|---|
| core 连续短输出 | rounds=32，frames=93 | rounds=23913，frames=71736 |
| Runner 多会话多 method 并发 | 96 请求，0 错配，p50 0.87 ms | 2119 轮，203424 请求，0 错配，每 method 峰值在途 4，p50 0.88 ms，max 2.68 ms |
| Runner kill/恢复循环 | 1 次，约 151 ms | 98 次，恢复 p50 150.13 ms，max 154.31 ms，无重放 |
| Runtime 启停循环 | 1 个周期，约 337 ms | 45 个周期，p50 335.20 ms，无泄漏 |
| Memory 持续写入后关闭抽取 | 400 条输入 | 412 轮，164800 条输入 |
| 语音连续回答（慢 alignment/字幕） | 3 个回答，11 句，24 帧 | 1287 个回答，8996 句，18018 帧 |

结束后 basetemp 无残留文件，`/tmp/aa-*` 无残留。

### 6. 发现的问题

**生产缺陷（保留失败复现，未修复，等待决定）**

- **KD-11**：Runner 故障期间新连接被全部拒绝，首次使用健康 method 时得到裸 `ConnectionResetError`。已对照 `runtime.py::_accept_client` 逐行确认。
- **KD-12**：revoke 与 interrupt 之间 TTS 首帧到达时，打断被误判为合成失败。已对照 `segmentation.py` 的 `prepare` 和 `streaming.py` 的 `run` 确认。

**观察与风险**：O-3～O-7，见文首表。另有四项不入表：

- `docs/identifiers-zh.md` 写"默认以 Turn 捕获的版本作比较"，而 `ParticipantRuntime.invoke` 先 `project_turn`，默认 basis 是当前已接受版本，与 capability 描述一致。建议统一文档措辞。
- 混合批次（B 的 Turn 加 A 的 Turn）当前标记为 unattributed，但 `owner_refs` 含 user-a。属于延期的多人抽取政策，没有断言。
- payload 恢复一轮后，`vision.sample_interval_sec` 由 `1` 变为 `1.0`。数值等价，测试比较解析后的 JSON。
- 语音 fork 早期一次非确定性运行中看到：打断恰好落在"帧已到播放器、`output.publish` 尚未返回"时，partial alignment 比实际交付的 PCM 少一帧。没有复现，现有测试避开了这个时序。

### 7. 三类验证的区分

| 类别 | 本轮状态 |
|---|---|
| 确定性离线回归 | 144 个用例，在默认命令和 CI 中运行；网络守卫只覆盖本解释器，真实 IPC 只放行测试自有 endpoint；spawn 子进程运行测试自带或本地 Runner，在构造上不联网（只读写本地文件、使用离线 embedding 替身、继承离线环境变量），没有进程级网络沙盒 |
| 合成压力测试 | 6 个 `stress` 用例，默认一轮，`--stress-seconds` 可控时长；结果见第 5 节，只代表合成负载 |
| 真实设备 / 服务验收 | **本轮未做**。没有连接真实 LLM、TTS、STT、Qdrant、MCP 服务器或 LiveKit，也没有在移动端或实机上运行 |

### 8. 未覆盖项

- KD-6 的状态传播（诊断批次）；KD-7、KD-8（默认值，未授权修改）。
- KD-10 ③ 中"解析前提交、解析后消费的 Turn"的画像；改绑后 Persona 按 Participant 的重载；`MemoryRuntime.visible_items`。
- 完整 AvatarEngine 准入路径（需要 router/status/memory/persona 全部插件）；Engine `_admit_decision` 只模拟了 `commit_event_input`。
- Host `_serve` 全流程和 `_monitor` 自动恢复循环（只验证了 `recover_failed_runners`）；真实的"子进程无法回收"（在 supervisor 边界模拟）。
- Memory retrieval/recall、consolidation、outbox 重试；EnvironmentProcessor 带真实 provider 的端到端流程；Persona Qdrant 后端；Face source 不可用时的迟到路径。
- 真实插件 Runner（lancedb/qdrant/MCP）在 spawn 子进程中运行：子进程无法替换 embedding provider，所以只在进程内测试，spawn 一侧用探针 Runner 证明快照一致。
- addressing/视觉证据融合、commentary→final_answer handoff、`max_concurrent_streams>1` 的预取；真实 fail-fast 字幕订阅者溢出后的级联（是否为预期策略不明确，没有断言）。
- 复杂多人历史抽取、误识别纠错策略（按要求延期）。

### 9. 后续功能边界（本轮不标为完成）

- Runner：当前是不同 method 独立进程、同一 method 串行；`host.processes.capacity` 是会话执行容量，不是 Runner 并行度。可配置的 Runner 并行仍待实现。
- CLI：只有 `dev`/`start` 和 `--help`/`--version` 轻量入口。安装配置向导、升级回滚、脱敏诊断导出，以及 doctor/check/test 尚未实现。`configs/profiles`、`configs/bundles` 目录存在，不代表完整配置流程已实现。
- 第 5 节的压力入口和结果只作为后续 Doctor/Check/Test 的验收依据。

### 10. 剩余风险

1. **CI 会变红**：KD-11、KD-12 两个复现按要求保留为失败，在修复或另行决定之前，默认 `pytest` 和 CI install job 会失败。
2. **私有状态依赖**：部分测试读写私有成员，Runtime 内部重构时需要同步更新：
   - 只读：`RunnerProcess._requests`/`_lock`，`InferenceRuntime._runners`；
   - 读写：`AvatarHost._manager`/`_supervisor`/`_health`/`_inference`。
3. **测试替身注入方式**：Host 子进程测试通过临时 `PYTHONPATH` 下的 `sitecustomize` 替换需要 LiveKit 的 `run_execution`；插件替换使用 monkeypatch 临时改写注册表。
4. **轮询辅助函数重复**：多个测试文件各自定义 1 ms 级轮询的 `wait_until`，沿用 2A-1 的模块内写法，没有抽成公共框架。
5. **测试时长与时序**：全量耗时增加约 15 s；ENV 重试用例依赖调度器的真实退避时长，但正确性只由事件判定。

### 11. 未做事项

- 没有修改生产代码，没有修复任何 KD/O。
- 没有新增 CLI 功能或通用测试框架，没有改 CI。
- 没有 commit 或 push。

---

## T-2 修复 review 确认的缺陷并补定向测试

- 日期：2026-11-02
- 基线 HEAD：`161e35f6453c76f6f29ecd08b9ad72948732bc7a`（T-1 的提交）
- 依据：ChatGPT 对 `161e35f` 的 review。结论是"测试值得保留但未验收，直接修复明确缺陷，不先加 xfail"。本轮范围：
  - 修复 KD-11、KD-13（review 新确认的 partial alignment 漏计）、KD-12、O-3；
  - 补 Memory、Persona、语音上游三处测试缺口和三项测试设施问题；
  - O-5 不改代码，只修正日志措辞。
- review 环境说明：review 方本地选跑了 113 项，其中 3 项因系统禁止创建 AF_UNIX socket 而无法运行，所以 review 没有把 T-1 的"142／2"当作独立复测结果。本节结果都在本机得到。

### 1. 修改文件

| 类型 | 文件 | 说明 |
|---|---|---|
| 修改 | `avatar-agents/alphaavatar/agents/runtime/inference/runtime.py` | KD-11：服务准入与目标 Runner 健康分开判断；O-3：socket 目录改用 `private_socket_path` |
| 修改 | `avatar-plugins/perception/avatar-plugins-router/.../speech_synthesis/streaming.py` | KD-12：准备阶段取消的分类；KD-13：按接纳序号计入音频 |
| 修改 | `avatar-core/alphaavatar/core/output/runtime.py` | 新增只读 `audio_sequence(output_id)`，与已有的 `text_sequence` 同类 |
| 新增 | `avatar-core/alphaavatar/core/ipc.py` | `private_socket_path`、`MAX_SOCKET_PATH = 100` |
| 修改 | `avatar-host/alphaavatar/host/log/runtime.py` | O-3：Host 日志 socket 改用 `private_socket_path` |
| 修改 | `conftest.py` | `--stress-seconds` 拒绝负数、NaN、无穷；`owned_endpoints` 只接受绝对 AF_UNIX 路径或数字回环 `(host, port)`，并按 socket family 匹配 |
| 修改 | `avatar-agents/tests/test_runner_process.py`、`test_inference_runtime.py`、`test_runner_stress.py` | fd 泄漏检查改为按 target 计数（`Counter`），不再比较 target 集合 |
| 修改 | `avatar-agents/tests/test_inference_runtime.py` | 扩展 KD-11 回归 |
| 修改 | `avatar-plugins/perception/avatar-plugins-router/tests/test_speech_synthesis.py` | KD-13 回归；Provider 自取消边界；离线 TTS 增加 `self_cancel` |
| 修改 | `avatar-plugins/perception/avatar-plugins-memory/tests/test_memory_runtime.py` | +6 |
| 修改 | `avatar-plugins/perception/avatar-plugins-persona/tests/test_persona_sensors.py` | +10 |
| 新增 | `avatar-plugins/perception/avatar-plugins-router/tests/test_audio_activity.py` | 4 |
| 新增 | `avatar-host/tests/test_local_endpoints.py` | 4 |
| 新增 | `avatar-core/tests/test_isolation.py` | 13 |

用例数从 144 增加到 183，共 +39。依赖、`uv.lock`、CI 均未改动。

### 2. 修复说明

**KD-11（P1）**

- 新增私有属性 `_serving`：服务已启动、未在关闭、server 正在监听。
- `_accept_client()` 和 `do_inference()` 改用它做准入，不再用总体 `is_alive`。
- `do_inference()` 再检查目标 method：
  - 未注册时抛 ValueError；
  - 已注册但 Runner 缺失（恢复中）或不健康时，抛 `RuntimeError("Inference runner temporarily unavailable")`，与 socket 路径的报错相同。
- 总体 `is_alive`（全部 Runner 存活）保持不变，继续供 Host `_monitor`、health 和 `start()` 使用。
- 按 review 要求，没有改成"任一 Runner 存活"，也没有只包装 `ConnectionResetError`。

**KD-13（partial alignment 漏计）**

- 原因：只有 `publish()` 返回事件后才累计 samples。帧已被一个消费者取走、另一个消费者仍在反压中时，打断让 `publish()` 返回 `None`，这一帧就没有计入。
- 修复：
  - 发布前读取 `output.audio_sequence(output_id)`。
  - 发布结束后（正常返回、返回 `None` 或抛异常都一样），在 `finally` 中判断序号是否前进。前进说明这一帧已被 Output 接纳，计入 samples 和 `published_audio_seconds`。
  - 在接纳前就被拒绝（guard 不通过）的帧不计入。
- 依据：接纳正是 OutputRuntime 记录 `last_audio_sequence`、让 AUDIO_COMPLETE barrier 覆盖该帧的边界。源码注释原文："A frame may reach one subscriber before another suspends in backpressure"。
- 按 review 要求，没有把计数无条件移到发布之前。
- 残余：已被接纳、但被打断撤回、没有任何消费者取走的帧也会计入。帧是串行发布的，所以每次打断最多多计一帧（本测试中一帧 10 ms）；实际播放量另由播放回执给出上界。（T-3 澄清：此表述有歧义，以 T-3 第 2 节为准。）

**KD-12（P2）**

- 准备阶段收到取消时，只有同时满足以下三条才判为 Provider 自取消（`TTS preparation cancelled itself` → `speech_synthesis_failed`）：
  - 当前任务没有在被取消；
  - 任务本身没有被取消；
  - output 仍然有效（新增这一条）。
- output 已失效（撤销 Run 或打断）时按打断处理，与帧循环中同一条件的判断一致。

**O-3（P2，启动兼容性）**

- `private_socket_path(prefix, name)` 优先在配置的临时目录下用 `mkdtemp`（0700）建私有目录。
- 如果完整 socket 路径超过 100 字节（比 macOS/BSD 的 104、Linux 的 108 都更保守），POSIX 下回退到 `/tmp` 下新建的私有目录。
- 都不满足时抛 `OSError(ENAMETOOLONG)`，给出明确错误。
- Inference 和 Host 日志这两个默认启动路径都改用该函数。
- 测试中的 `socket_root` 仍保留，用于隔离和检查残留。

**O-5**：按 review 结论，不改代码，日志措辞已改为"ENV 的有限辅助 prompt"。

### 3. 定向测试补齐

| 方面 | 新增覆盖 |
|---|---|
| KD-11 | 扩展 `test_failed_method_does_not_refuse_first_use_of_a_healthy_method`。故障期间健康 method 能正常使用：<br>• Executor 首次连接；<br>• 进程内 `do_inference()`；<br>• 已派发后取消再重连。<br>故障 method 在两个入口都报 "temporarily unavailable"。总体 `is_alive` 仍为 False，`recover_failed_runners()` 可恢复。日志证明被拒绝的请求从未执行 |
| KD-13 | `test_interrupted_alignment_covers_audio_already_delivered_to_a_consumer`：第二个可靠音频消费者停止读取，播放器已收到 2 帧时打断，最终 partial alignment 的结束时间等于已交付的 0.020 s |
| KD-12 边界 | `test_provider_self_cancellation_on_an_active_output_remains_a_failure`：output 仍有效时 Provider 自取消，仍判为 `speech_synthesis_failed` 并记 ERROR |
| O-3 | `test_local_endpoints.py`：短 / 长临时目录 × Inference / Host 日志，共 4 个。长目录时回退到 `/tmp`；路径不超过 100 字节；目录权限 0700；真实请求和日志都能送达；关闭后目录被删除，临时目录无残留 |
| Memory | 6 个：<br>• Tool 抽取失败时，tool checkpoint 不推进、输入保留、`on_stop` 报出错误，conversation 照常推进；<br>• 一个 Context 的 Tool 失败或被取消，不会让其他 Context fail-fast，全部 Conversation/Tool 收尾完成后才关闭 Store；<br>• 模型记录按自身 `identity_basis` 归属（无纠正 / 执行前纠正 / 执行后纠正三种情况） |
| Persona | 10 个，speaker 与 face 各一半，source 始终有效：<br>• VDB 查询未匹配（`None` 或空 `user_id`）时不绑定，证据留在本 Participant，不升级为错误；<br>• 查询期间 Agent 改绑 A→C，迟到结果被丢弃、不覆盖 C，C 之后正常工作；<br>• 匹配作为对照，正常绑定 |
| 语音上游 | `test_audio_activity.py` 4 个：走真实 `AudioActivityProcessor` → `AudioActivitySource` → `SileroVADStream` 入口，VAD 模型用离线替身。覆盖：<br>• 尾静音回溯后，段边界、帧序和 PCM 精确；<br>• VAD 积压时，积压窗口从 pre-roll 边缘按源顺序回放，并与之后的实时帧无缝衔接；<br>• 旧 generation 退役时取消打开的段，丢弃迟到帧 |
| 测试设施 | `test_isolation.py` 13 个：`--stress-seconds` 的负数、NaN、无穷值都报用法错误（exit 4），有限值通过；`owned_endpoints` 拒绝相对路径、bytes、抽象命名空间、非回环地址、主机名、非法端口和 4 元组；已登记的 AF_UNIX endpoint 可以连通 |

### 4. 变异验证

| 变异 | 结果 |
|---|---|
| `_accept_client` 改回总体 `is_alive` 准入 | KD-11 回归失败 |
| `do_inference` 改回总体 `is_alive` 准入 | KD-11 回归失败 |
| 临时恢复 `HEAD` 版 `streaming.py`（之后已逐字节还原） | KD-13 回归失败（`0.01 == 0.02`）；KD-12 复现失败 |
| KD-12 修过头：准备阶段的取消一律视为打断 | Provider 自取消边界用例失败（`synthesis_interrupted`） |
| socket 目录改回直接 `mkdtemp` | O-3 的两个长目录用例失败 |
| Memory：Tool 吞掉异常；Tool 收尾 fail-fast；忽略模型记录的 identity_basis | 均有用例失败 |
| Persona：去掉查询后的身份重查（speaker 或 face）；未匹配也当作匹配；Store 去掉空 `user_id` 过滤 | 均有用例失败 |
| 语音上游：关闭回溯；倒序回放积压；不回放积压；speaking 时不实时路由；不退役旧 generation | 均有用例失败 |

Persona 补充：重查与 CAS 之间没有 await，所以单独去掉 CAS 的变异无法被测试单独抓到；只去掉重查时，未匹配用例能抓到。

### 5. 运行命令与结果

均在 `cd /home/ecs-user/AlphaAvatar && source .venv/bin/activate` 之后执行。

| 项目 | 结果 |
|---|---|
| 全量（CI 方式：`PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider --basetemp=… --durations=8`）×3 | 3 次均为 **183 passed**，约 22.3–23.3 s；basetemp 无残留文件；`/tmp/aa-*` 无残留；本轮没有新增 `/tmp/alphaavatar-*`（机器上已有的 54 个均是 8–10 月旧运行留下的，未处理） |
| 检出目录 | 前后 `git status --porcelain --ignored` 无差异 |
| 包目录单独运行 | core 42、host 28、router 21、memory 15、persona 34，全部通过 |
| 压力入口默认一轮 | `pytest -m stress`：6 passed，3.66 s |
| Ruff / Workspace / Lock / pre-commit | `ruff check .` 通过；672 files already formatted；16 members consistent；`uv lock --check` 通过；所有改动文件的 pre-commit hook 通过 |
| 发布包 | `alpha-avatar-core` wheel 包含 `alphaavatar/core/ipc.py`，`tests/` 条目为 0 |

警告：仍是 O-6 的 28 条 DeprecationWarning。

### 6. 仍未解决与未覆盖

- 未改动：KD-6、KD-7、KD-8、O-1、O-2、O-4、O-6、O-7、O-8；KD-10 的两点剩余见文首表。
- KD-13 的残余：每次打断最多多计一帧（见第 2 节；T-3 已澄清含义）。
- Memory：Conversation 在身份切换下的 consolidation 路径没有覆盖；混合批次归属属于延期政策，没有断言。
- Persona：只覆盖了 Agent 主动改绑，没有覆盖另一传感器的被动改绑（例如 speaker 查询期间 face 改绑）；Qdrant 后端的未匹配形态没有覆盖。
- 语音上游：
  - 真实 ONNX Silero 和 LiveKit 音频输入使用离线替身；
  - `VAD_INPUT_REJECTED` 和 `INPUT_GAP` 恢复路径没有覆盖；
  - O-8 的积压淘汰行为没有断言。
- 真实设备和服务验收：本轮仍未做。

### 7. 未做事项

- 没有 commit 或 push。
- 没有修改 CI、依赖或 CLI。
- 没有处理第 6 节所列的未授权项。

---

## T-3 review 收尾：KD-14、KD-15、allowlist 旁路、KD-13 表述

- 日期：2026-11-02
- 基线 HEAD：`1aecf40e2ef3b5b099b2eecebcc36618ac44ccc7`（T-2 的提交）
- 依据：ChatGPT 对 `1aecf40` 的 review。结论是 KD-11、KD-12、KD-13、O-3 的修复和 Memory/Persona 补测可以接受，剩下以下收尾项：
  - O-8 升级为生产缺陷（现编号 KD-14），P1；
  - HostLog 构造失败时遗留目录（现编号 KD-15），P2；
  - 测试 allowlist 的 `^=` 旁路；
  - KD-13 日志表述需要澄清。
- review 环境说明：默认收集 183 项，选跑 144 项全部通过；完整 IPC 成功路径受该环境权限限制，没有独立复跑。

### 1. 修改文件

| 类型 | 文件 | 说明 |
|---|---|---|
| 修改 | `avatar-plugins/perception/avatar-plugins-router/.../audio_activity/source.py` | KD-14：`_start_segment` 检查迟到的 VAD 起点是否已被淘汰 |
| 修改 | `avatar-host/alphaavatar/host/log/runtime.py` | KD-15：接收 socket 的创建移入 `try`，失败时完整清理 |
| 修改 | `conftest.py` | `owned_endpoints.allows()` 在放行边界重新校验地址形态；去掉无法覆盖全部写入方式的 `update`/`__ior__` 重载，保留 `add()` 的提前报错 |
| 修改 | `avatar-plugins/perception/avatar-plugins-router/tests/test_audio_activity.py` | +2：KD-14 回归，以及只丢 pre-roll 的对照 |
| 修改 | `avatar-host/tests/test_local_endpoints.py` | +2：接收 socket、客户端 socket 分别创建失败 |
| 修改 | `avatar-core/tests/test_isolation.py` | 地址用例改为先绕过 `add()` 插入，再验证 `allows()` 拒绝；用例数不变 |

用例数从 183 增加到 187。依赖、`uv.lock`、CI 均未改动。

### 2. 修复与澄清

**KD-14（P1，原 O-8）**

- 原因：`_append_frame` 只保留最近 `max_buffer_sec` 的帧。VAD 积压超过这个长度时，迟到的 START 指向的语音正文已被淘汰，但 `_start_segment` 不检查，仍然回放剩余的帧，最后发布一个"完整的"`SPEECH_SEGMENT`。
- 修复：2 s 上限保留不变。在路由任何帧之前，比较语音起点 `speech_start_sample` 与最早保留的样本：
  - 起点更早，说明语音正文已丢失：
    - 记录 `audio.speech_lost`，`reason=vad_backlog_overflow`，`missing_count` 为丢失的样本数；
    - 以 `SpeechCancellationReason.INPUT_GAP` 让 source 失败，为该段发布 `SPEECH_CANCELLED`，剩余帧一帧都不路由；（T-4 范围澄清：source 失败会退役整个旧 speech epoch，不只这一段，见 T-4 第 2 节）
    - Processor 沿用现有的 `INPUT_GAP` 退役路径，下一帧到来时新建 source 和 VAD 流，旧积压一并丢弃，新流从当前位置开始，不再落后。
  - 只丢了 pre-roll（语音起点之前的缓冲）时，正文完整，照常发布。
- 选择"退役并新建流"而不是"跳过本段、沿用旧流"的原因：旧流的积压仍超过缓存长度，沿用它只会在下一句重复丢失；这也与感知流缺口（`_recover_gap`）和 `VAD_INPUT_REJECTED` 的现有恢复方式一致。

**KD-15（P2，既存缺口）**

- 接收 socket 在 `try` 外创建，创建失败时（例如沙盒拒绝 AF_UNIX，返回 EPERM），`private_socket_path` 已建好的目录不会被删除。
- 修复：创建移入 `try`；失败时关闭已创建的 socket，删除目录，恢复 endpoint 环境变量。

**测试 allowlist 旁路**

- `^=`、`symmetric_difference_update()` 等 set 运算不经过 `add()`，可以插入远程地址，之后 `allows()` 只检查成员关系就会放行。
- 修复：`allows()` 先按 socket family 取出地址键，再用与 `add()` 相同的 `_local_address` 校验，最后才检查成员关系。

**KD-13 表述澄清（代码不变）**

- partial alignment 描述的是**已被 Output 接纳的音频**，实际播放了多少由播放回执确认。
- T-2 中"每次打断最多多计一帧"只指这一次在途发布的记账：被打断时正在发布的那一帧已被接纳，所以计入。
- 它不是整体播放误差的上界；帧时长由 TTS 决定，也不固定为 10 ms（10 ms 只是测试替身的帧长）。

### 3. 回归与验证

| 变异 / 对照 | 结果 |
|---|---|
| 临时恢复 `HEAD` 版 `source.py`（之后已逐字节还原） | `[speech-evicted]` 失败：等不到取消，直到 10 s 挂起保护超时；`[pre-roll-evicted]` 照常通过 |
| 临时恢复 `HEAD` 版 `host/log/runtime.py`（之后已逐字节还原） | `[receiver]` 失败，并因目录残留在 teardown 报 ERROR；`[client]` 通过（原代码已处理这条路径） |
| `allows()` 去掉边界校验、只查成员（临时改动，之后已还原） | 8 个地址用例中 7 个失败；bytes 路径本就因类型不是 str 被拒，不受影响 |

KD-14 回归 `test_speech_evicted_by_the_backlog_bound_is_cancelled_and_recovered`：

- `[speech-evicted]`：VAD 被挡住时推入 240 帧，其中 32 帧是语音。断言：
  - 只出现一个 `SPEECH_CANCELLED(input_gap)`；
  - 没有任何 `SPEECH_FRAME` 或 `SPEECH_SEGMENT`；
  - `audio.speech_lost` 的 `missing_count` 等于 3840 个样本（24 帧）；
  - 同一路输入的下一句在新的 speech source generation 上得到完整、精确的段。
- `[pre-roll-evicted]`：推入 210 帧，只丢 pre-roll；段照常发布，内容从最早保留的帧开始，没有取消。

运行结果（均在 `cd /home/ecs-user/AlphaAvatar && source .venv/bin/activate` 之后执行）：

| 项目 | 结果 |
|---|---|
| 全量（CI 方式：`PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider --basetemp=…`）×3 | 3 次均为 **187 passed**，约 22.2–23.3 s；basetemp 无残留；`/tmp/aa-*` 无残留；本轮没有新增 `/tmp/alphaavatar-*` |
| 检出目录 | 前后 `git status --porcelain --ignored` 无差异 |
| 压力入口默认一轮 | 6 passed，3.70 s |
| Ruff / Workspace / Lock / pre-commit | 均通过（672 files already formatted；16 members consistent） |

### 4. 仍未解决

- KD-6、KD-7、KD-8、O-1、O-2、O-4、O-6、O-7 未改动；KD-10 的两点剩余见文首表。
- 语音上游的 `VAD_INPUT_REJECTED` 和感知流 `INPUT_GAP` 恢复路径仍没有专门的回归用例。
- 真实设备和服务验收仍未做。

### 5. 未做事项

- 没有 commit 或 push。
- 没有修改 CI、依赖或 CLI。

---

## T-4 KD-14 补齐：缺口后的语音边界

- 日期：2026-11-02
- 基线 HEAD：`dca356fa919a0f3bcccea695b3228be895519b89`（T-3 的提交）
- 依据：ChatGPT 对 `dca356f` 的 review。
  - 已验收：KD-15、allowlist 旁路、KD-13 文案；同意"取消旧流、重建 VAD"的取舍。
  - KD-14 不能关闭，原因是持续发声的边界，已稳定复现：
    1. 推入 16 帧静音、224 帧讲话，触发缺口、取消并换流；
    2. 用户不停顿，继续说 32 帧、再接 16 帧尾静音；
    3. 新流把这 32 帧原句尾部当作普通语音段，经过真实的 STT/TurnTaking 链路后产生正常 COMMIT，没有缺口或 partial 标记。
  - T-3 的恢复测试在恢复前先推了静音，所以没有抓到这个问题。
- 要求：保留 2 s 缓存上限和换流策略；缺口后的恢复阶段先确认可靠的静音或结束边界，再接纳下一次语音开始；加入"换流后持续讲话"的回归，同时保留"静音后正常恢复"的对照；在日志中准确说明 `INPUT_GAP` 的影响范围。

### 1. 修改文件

| 类型 | 文件 | 说明 |
|---|---|---|
| 修改 | `avatar-agents/alphaavatar/agents/avatar/voice/vad.py` | `VADBase` 新增抽象属性 `min_silence_duration`：结束一个语音段所需的连续静音时长 |
| 修改 | `avatar-plugins/foundation/avatar-plugins-voice/alphaavatar/plugins/voice/vad/silero.py` | `SileroVAD` 实现该属性，返回配置的 `min_silence_duration` |
| 修改 | `avatar-plugins/perception/avatar-plugins-router/.../audio_activity/source.py` | 新增 `recovering` 参数和"等待边界"状态（`_await_boundary`） |
| 修改 | `avatar-plugins/perception/avatar-plugins-router/.../audio_activity/processor.py` | 记录哪些输入在连续性缺口后需要恢复，为下一条 VAD 流打开恢复状态 |
| 修改 | `avatar-plugins/perception/avatar-plugins-router/tests/test_audio_activity.py` | +3：换流后持续讲话的回归 |

用例数从 187 增加到 190。依赖、`uv.lock`、CI 均未改动。

接口变化：`VADBase` 的实现必须提供 `min_silence_duration`。仓库中只有 `SileroVAD` 一个实现；按"不保留兼容层"的原则，没有提供默认值。

### 2. 修复说明

- **新流不能证明新的一句话。** 缺口之后新建的 VAD 流可能从一句话的中间开始。新流里出现 START，只说明流重建了，不说明用户开始了下一句。
- **恢复状态。** Processor 在以下三种连续性缺口后，记录该输入的 generation，并让它的下一条 VAD 流以 `recovering=True` 启动：
  - KD-14 的语音正文丢失（`INPUT_GAP`）；
  - 感知流缺口（`_recover_gap`，所有已知输入都标记，不论当时有没有活动的流）；
  - VAD 输入队列拒收（`VAD_INPUT_REJECTED`）。

  新输入 generation（例如重连）不算缺口，不进入恢复状态。
- **确认边界的两种方式。** 在恢复状态下，满足任一条件才算确认了可靠边界，之后的 START 照常接纳：
  - 一次 END_OF_SPEECH；
  - 一个非讲话窗口，且连续静音大于 0、并达到 VAD 自己的 `min_silence_duration`。

  确认之前出现的 START 被视为原句延续：不打开段、不路由帧，记录 `audio.speech_skipped`（`reason=unconfirmed_boundary`）。
- **"大于 0"这一条的来源。** 变异验证中发现，当 `min_silence_duration` 为 0 时，第一个"尚未判为讲话"的语音窗口（连续静音为 0）也会被当成边界。因此额外要求确实观察到静音。
- **取舍。** 恢复状态下，如果停顿短于 VAD 的结束静音，紧接着的话也会按原句延续丢弃，并有 trace 记录。这是有意的保守选择：缺口让边界变得不确定，宁可丢一句并留下记录，也不把半句话当成完整输入提交。

**`INPUT_GAP` 的影响范围（澄清）**

- 缺口时退役的是整个旧 speech epoch，即该 speech source generation，而不只是被截断的那一段。
- 这个 epoch 中尚未完成识别、尚未提交的前段也一并退役：下游 STT 按旧 generation 关闭流，迟到的识别结果不再发布。
- 已经提交的 Turn 不受影响。
- `VAD_INPUT_REJECTED` 与感知流缺口同样会退役 speech epoch，范围相同。
- T-3 日志中"为该段发布 `SPEECH_CANCELLED`"的表述不完整，已在原处加注。

### 3. 回归与验证

`test_speech_continuing_through_a_gap_is_not_admitted_as_a_new_utterance`，3 个参数：

| 参数 | 场景 |
|---|---|
| `evicted-continuous` | review 的复现：16 帧静音、224 帧讲话，触发缺口后不停顿，继续 32 帧讲话、16 帧尾静音 |
| `evicted-short-pause` | 同上，但续说前停顿 5 帧（0.05 s），短于 VAD 的 0.1 s 结束静音 |
| `vad-rejected-continuous` | 268 帧讲话使 VAD 队列拒收，换流后不停顿继续讲话 |

断言：
- 原句延续的所有帧既没有被路由，也没有成段；
- 只记录了一次 `audio.speech_skipped`；
- 下一句（先静音再讲话）完整成段，所在的 speech source generation 大于 1；
- 只有 evicted 场景出现 `SPEECH_CANCELLED`：队列拒收时旧流没有打开的段。

T-3 中"先静音再恢复"的用例保留为对照，仍然通过。

| 变异 / 对照 | 结果 |
|---|---|
| 临时恢复 `HEAD` 版 `source.py` 和 `processor.py`（之后已逐字节还原） | 3 个持续讲话用例失败，6 个对照通过 |
| 换流后从不等待边界（`recovering` 恒为 False，内存变异） | 3 个持续讲话用例在"路由帧必须全部属于新的一句"这条断言上失败，抓到的就是缺陷本身；对照通过 |
| 结束静音阈值改为 0（内存变异） | 只有 `evicted-short-pause` 失败，它正是阈值的守卫 |

运行结果（均在 `cd /home/ecs-user/AlphaAvatar && source .venv/bin/activate` 之后执行）：

| 项目 | 结果 |
|---|---|
| 全量（CI 方式：`PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider --basetemp=…`）×3 | 3 次均为 **190 passed**，约 22.3–24.3 s；basetemp 无残留；`/tmp/aa-*` 无残留；本轮没有新增 `/tmp/alphaavatar-*` |
| `test_audio_activity.py` ×3 | 9 passed ×3 |
| 检出目录 | 前后 `git status --porcelain --ignored` 无差异 |
| 压力入口默认一轮 | 6 passed，3.69 s |
| Ruff / Workspace / Lock / pre-commit | 均通过 |

### 4. 未覆盖与仍未解决

- 回归断言停在 Audio Activity 的输出层：原句延续不产生任何 `SPEECH_FRAME` 或 `SPEECH_SEGMENT`，下游因此没有可提交的输入。没有像 review 那样串起真实的 STT/TurnTaking 链路断言 COMMIT。
- 感知流缺口路径（`_recover_gap`）的恢复状态只做了代码审查，没有专门的回归用例（需要构造感知事件流溢出）。
- KD-6、KD-7、KD-8、O-1、O-2、O-4、O-6、O-7 未改动；KD-10 的两点剩余见文首表；真实设备和服务验收仍未做。

### 5. 未做事项

- 没有 commit 或 push。
- 没有修改 CI、依赖或 CLI。

---

## T-5 KD-14 收口：恢复要求的归属与回放下界

- 日期：2026-11-02
- 基线 HEAD：`65bd40f2289cf9e511cddac8a2d5d84ed8d0374f`（T-4 的提交）
- 依据：ChatGPT 对 `65bd40f` 的 review。
  - 已接受：新增的 VAD 接口；短停顿时保守丢弃的策略；普通恢复路径已修好。
  - KD-14 仍不能关闭，因为还有三条旁路，均已确定性复现：

| # | 旁路 | review 的复现 |
|---|---|---|
| 1 | Processor 在创建流时就 `pop` 掉恢复标志 | 新流尚未确认静音就遇到 VAD 超时，下一条流直接接纳了后续 32 帧尾句 |
| 2 | `_recover_gap()` 只标记已有的 `_inputs`，随后才从快照恢复未知输入，后者不受约束 | 用受支持的 `event_maxlen=64` 缩小复现（测试配置，不是默认缓冲）：96 帧连续讲话发生缺口后，剩余 64 帧尾部仍作为正常段发布 |
| 3 | 确认边界后只解除等待，没有限制回放下界 | 合法配置 `pre_roll=0.3s`、结束静音 `0.1s` 下，下一句重新带入了此前跳过的 14 帧语音 |

- 收口约束（review 提出）：
  - 恢复要求属于输入 generation，直到确认边界才解除；再次换流、从快照恢复输入都必须继承。
  - 恢复后的回放不能越过安全采样下界，pre-roll 同样受约束。

### 1. 修改文件

| 类型 | 文件 | 说明 |
|---|---|---|
| 修改 | `avatar-plugins/perception/avatar-plugins-router/.../audio_activity/processor.py` | 恢复要求的归属；感知缺口 horizon |
| 修改 | `avatar-plugins/perception/avatar-plugins-router/.../audio_activity/source.py` | 新增 `on_boundary` 回调；回放下界 `_route_floor` |
| 修改 | `avatar-plugins/perception/avatar-plugins-router/tests/test_audio_activity.py` | +3 个回归；测试夹具支持配置 `pre_roll_sec`、`event_maxlen`，离线 VAD 可以按需超时 |

用例数从 190 增加到 193。依赖、`uv.lock`、CI 均未改动。

### 2. 修复说明

**旁路 1：恢复要求随输入 generation 保留**

- 创建流时只读取恢复标志，不再删除。
- 只有当前活动的流通过 `on_boundary` 回调报告"已确认边界"时，Processor 才解除该 generation 的恢复要求。
- 流在确认之前因任何原因退役（VAD 超时或错误、格式变化、静音等），要求都会保留，下一条流继续等待边界。
- 只有输入进入新的 generation 时才清除旧要求，下面一条例外。

**旁路 2：感知缺口时记录 horizon**

- `_recover_gap()` 记录缺口批次的 `latest_seq` 作为 horizon。
- 已知输入照旧标记。
- 对于未知输入，以及缺口后才前进的输入 generation，只要首次出现的事件序号不超过 horizon，就同样标记为恢复中。这些 generation 位于缺口后保留的窗口内，此前的音频可能已经丢失。
- 这样，从快照恢复的输入和在保留窗口里首次出现的输入，都继承了恢复要求；horizon 之后才出现的新 generation 不受影响。

**旁路 3：回放下界**

- 确认边界时，把回放下界设为确认静音的起点，即 `samples_index - raw_accumulated_silence * sample_rate`（T-6 补正：原文漏写换算系数）。
- `_start_segment` 的 `route_start_sample` 取 pre-roll 起点和这个下界中较大的一个。
- 跨越下界的帧，以及起点早于下界的帧，都不回放。
- 因此 pre-roll 可以覆盖确认边界的那段静音，但不会回到之前被跳过的语音。

### 3. 回归与验证

| 用例 | 场景与断言 |
|---|---|
| `test_recovery_survives_a_stream_that_fails_before_its_boundary` | KD-14 换流后继续讲话；在重建的流确认边界之前，让离线 VAD 推理超时一次，使这条流失败；之后的尾句仍被跳过，`audio.speech_skipped` 共 2 次，下一句成段且不含旧帧（T-6 补正：T-5 时只断言了这两点，不足以称"完整"；T-6 已补上讲话帧完整的断言） |
| `test_input_first_seen_after_a_perception_gap_must_confirm_a_boundary` | `event_maxlen=64`；112 个事件先于消费者到达，Processor 在讲话中途才第一次见到这路输入；断言出现一次 `audio.input_gap`，剩余尾部不成段，下一句成段且不含旧帧（T-6 补正同上） |
| `test_pre_roll_after_a_gap_never_reaches_back_into_skipped_speech` | `pre_roll=0.3s`；被跳过的尾句之后只有 0.16 s 静音（足以确认边界，但短于 pre-roll），紧接下一句；断言路由的帧和成段的帧都不早于那段静音，下一句的讲话帧完整 |

| 变异 / 对照 | 结果 |
|---|---|
| 临时恢复 `HEAD` 版 `source.py` 和 `processor.py`（之后已逐字节还原） | 3 个新用例都在"路由帧必须全部属于新的一句"这条断言上失败；其余 9 个通过 |
| 创建流时删除恢复标志（只还原旁路 1 的修复，内存变异） | 只有旁路 1 的用例失败 |
| 感知缺口时 horizon 记为 0（内存变异） | 只有旁路 2 的用例失败 |
| 确认边界后把回放下界恢复为 0（内存变异） | 只有旁路 3 的用例失败 |

T-3、T-4 的回归（静音后恢复、持续讲话、短停顿、VAD 队列拒收）全部保留并通过。

运行结果（均在 `cd /home/ecs-user/AlphaAvatar && source .venv/bin/activate` 之后执行）：

| 项目 | 结果 |
|---|---|
| 全量（CI 方式：`PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider --basetemp=…`）×3 | 3 次均为 **193 passed**，约 22.4–23.4 s；basetemp 无残留；`/tmp/aa-*` 无残留；本轮没有新增 `/tmp/alphaavatar-*` |
| `test_audio_activity.py` ×3 | 12 passed ×3 |
| 检出目录 | 前后 `git status --porcelain --ignored` 无差异 |
| 压力入口默认一轮 | 6 passed，3.73 s |
| Ruff / Workspace / Lock / pre-commit | 均通过 |

### 4. 仍未覆盖

- 断言仍停在 Audio Activity 的输出层，没有串起真实的 STT/TurnTaking 链路去断言 COMMIT。
- 恢复要求在 MUTED、ENDED 等状态后会一直保留，直到下一次确认边界或 generation 前进。这符合"属于输入 generation"的约束，但没有专门用例。
- KD-6、KD-7、KD-8、O-1、O-2、O-4、O-6、O-7 未改动；KD-10 的两点剩余见文首表；真实设备和服务验收仍未做。

### 5. 未做事项

- 没有 commit 或 push。
- 没有修改 CI、依赖或 CLI。

---

## T-6 KD-14：快照不能抹掉缺口窗口中的证据

- 日期：2026-11-02
- 基线 HEAD：`a2b6bde44feda492317dabc28d979894484e2bdf`（T-5 的提交）
- 依据：ChatGPT 对 `a2b6bde` 的 review。T-5 的三条旁路已修好，但仍有 1 个 P1，KD-14 暂不能关闭。
- 问题：`_accept_input` 用快照中最新的 `changed_sequence` 判断这个 generation 是否在缺口之后才出现。但状态更新的时间并不代表 generation 首次出现的时间。review 用真实生产者线程做了确定性复现：
  1. 输入此前尚未被 Processor 登记，连续讲话触发事件缺口，缺口批次的 `horizon=97`。
  2. 读取快照之前，同一 generation 发生一次静音再恢复，状态序号变为 99。
  3. 快照先登记了这路输入，因为 99 > 97，没有设置"等待边界"要求。
  4. 后续同一句话的 32 帧尾音正常成段，并经真实的 STT/TurnTaking 链路产生了 1 次 COMMIT；没有并发状态变化的对照组则正确跳过尾音，COMMIT 为 0。
- review 的建议：
  - 最小修改：保留缺口批次中"这个 generation 已经存在"的证据，合并更新的快照后仍要求它确认边界；
  - 最新状态序号继续负责过滤旧帧；真正位于 horizon 之后的新 generation 保持现有行为；
  - 补一个上述并发回归，断言尾句不进入 STT、不产生 COMMIT。
- 另外两处非阻断的日志问题：
  - T-5 的下界公式漏了 `* sample_rate`；
  - T-5 前两个新用例只证明了"成段且没有旧帧"，不足以宣称讲话帧"完整"。

### 1. 修改文件

| 类型 | 文件 | 说明 |
|---|---|---|
| 修改 | `avatar-plugins/perception/avatar-plugins-router/.../audio_activity/processor.py` | 缺口证据集合 `_gap_evidence` 和 `_require_boundary`；`_accept_input` 依据证据而不是"首次登记"来设置恢复要求 |
| 修改 | `avatar-plugins/perception/avatar-plugins-router/tests/test_audio_activity.py` | +2：并发回归和对照组，接入真实的 STT/TurnTaking 链路；`assert_only_utterance` 增加讲话帧完整性断言，T-5 的三个用例同步加强 |

用例数从 193 增加到 195。依赖、`uv.lock`、CI 均未改动。

### 2. 修复说明

- **以证据代替首次登记。** 缺口之后，只要某个 generation 有一个序号不超过 horizon 的事件（帧或状态），就说明它在缺口窗口内已经存在，此前的音频可能已经丢失，因此要求它确认边界。不论这路输入是由更新的快照先登记的，还是在缺口时就已知，都适用。
- **每次缺口只记一次。** 同一次缺口中，每个 generation 只设置一次恢复要求（`_gap_evidence`）。之后到达的窗口内事件不会重新施加已经确认过的要求。每次新缺口都会重置这个集合。
- **其余行为不变：**
  - 最新状态序号（`changed_sequence`）照旧过滤状态变化之前的旧帧；
  - horizon 之后首次出现的新 generation 照旧清除旧要求、不进入恢复；
  - 缺口时已知的输入照旧标记，现在统一经由 `_require_boundary`。
- **日志补正。** T-5 第 2 节的下界公式已改为 `samples_index - raw_accumulated_silence * sample_rate`，代码本身原就有此换算。T-5 第 3 节"完整成段"的表述已在原处加注。

### 3. 回归与验证

`test_snapshot_newer_than_a_gap_keeps_the_boundary_requirement`：`event_maxlen=64`，接入真实的 `SpeechTranscriptionProcessor` 和 `MultimodalTurnTakingProcessor`。离线 STT 在段提交时给出终稿，端点模型对每个已转写的候选都判定说完。

| 参数 | 场景 |
|---|---|
| `snapshot-at-gap`（对照） | 先发布 ACTIVE 状态，再发 96 帧（16 帧静音、80 帧讲话）；97 个事件先于消费者到达，形成缺口，horizon=97 |
| `state-after-gap` | 同上；另外在 Processor 读完缺口批次、读取快照之前注入同一 generation 的 MUTED、ACTIVE（序号 98、99），模拟 review 中生产者线程的时序 |

两种参数的断言相同：
- 尾句（32 帧讲话、16 帧尾静音）不路由、不成段，没有进入 STT；
- 下一句成段，所有讲话帧都在段内，不含旧帧；
- STT 只收到下一句这一段；
- COMMIT 恰好 1 次；
- 全程只有 1 次 `audio.input_gap`。后续音频分段推入，避免第二次缺口按"已知输入"重新打上标记、掩盖这条旁路。编写时就遇到过这种情况：一次性推入 112 帧会触发第二次缺口，使 HEAD 代码误通过。

| 变异 / 对照 | 结果 |
|---|---|
| 临时恢复 `HEAD` 版 `processor.py`（之后已逐字节还原） | 只有 `state-after-gap` 失败：出现 2 个段、2 次 COMMIT，与 review 的复现一致；对照组和其余 12 个用例通过 |

运行结果（均在 `cd /home/ecs-user/AlphaAvatar && source .venv/bin/activate` 之后执行）：

| 项目 | 结果 |
|---|---|
| 全量（CI 方式：`PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider --basetemp=…`）×3 | 3 次均为 **195 passed**，约 22.4–24.4 s；basetemp 无残留；`/tmp/aa-*` 无残留；本轮没有新增 `/tmp/alphaavatar-*` |
| `test_audio_activity.py` ×3 | 14 passed ×3 |
| 检出目录 | 前后 `git status --porcelain --ignored` 无差异 |
| 压力入口默认一轮 | 6 passed，3.73 s |
| Ruff / Workspace / Lock / pre-commit | 均通过 |

### 4. 说明与仍未覆盖

- 并发时序是在 `get_source_states` 处确定性注入的，模拟"读完批次之后、读取快照之前"有生产者写入；没有使用真实线程。
- "每次缺口只记一次"这一点（确认边界后，窗口内的迟到事件不会重新施加要求）没有专门用例。review 已独立验证该行为，并建议后续纳入正式回归（不阻塞验收）。
- KD-6、KD-7、KD-8、O-1、O-2、O-4、O-6、O-7 未改动；KD-10 的两点剩余见文首表；真实设备和服务验收仍未做。

### 5. 未做事项

- 没有 commit 或 push。
- 没有修改 CI、依赖或 CLI。

---

## T-7 KD-14 正式回归与四项系统修复

- 日期：2026-11-02
- 基线 HEAD：`2d1d575efc49cbd31ac7057890e2defafd0fd8b2`（`dev/v0.6.9`，与远端一致）。上一轮的日志修改已包含在这个提交中，工作区开始时是干净的，没有需要保留的未提交改动。
- 授权范围：
  1. KD-14 正式回归（只加测试）；
  2. 修复 O-1、KD-6、KD-8、O-7；
  3. KD-10 剩余的 Persona 时序和 O-4 先补测试，按证据决定是否修生产代码；
  4. 保持既定架构边界；KD-7 不变；配置公共服务、CLI、Runner 并行留待后续批次。

### 1. 结果分类

| 类别 | 项 |
|---|---|
| 已修复 | O-1、KD-6、KD-8、O-7 |
| 仅补测试 | KD-14（保持已关闭）；KD-10 ③ 的时序（现有设计通过）；O-4（真实调用链通过，仍作风险记录） |
| 仍待处理 | KD-7（默认审批策略，另行审查）；KD-10 ②（跨身份检索，属于延期的多人历史政策）；O-2、O-6；O-9（新增，仅记录）；真实设备和服务验收 |

### 2. 修改文件

生产代码：

| 文件 | 项 | 改动 |
|---|---|---|
| `avatar-agents/alphaavatar/agents/runtime/inference/process.py` | O-1 | `_close` 记录关闭前是否 READY；从未 READY 的进程直接强制回收 |
| `avatar-plugins/perception/avatar-plugins-memory/.../retrieval/passive.py` | KD-6 | 新增 `_trace`，在 `_finish` 完成门闩处记 `memory.recall`；补记"保留名额全部在途"路径的 `overloaded` |
| `avatar-host/alphaavatar/host/application/config.py` | KD-8 | `HealthConfig.bind` 默认改为 `127.0.0.1` |
| `avatar-agents/alphaavatar/agents/configs/plugins/tools/tools_config.py` | O-7 | `MCPConfig` 设置 `hide_input_in_errors=True` |
| `avatar-agents/alphaavatar/agents/configs/avatar_config.py` | O-7 | `AvatarConfig` 设置 `hide_input_in_errors=True` |
| `DEPLOY.md`、`avatar-host/README.md` | KD-8 | 说明默认只绑定本机、显式绑定的含义，以及 `/status` 的返回内容 |

测试：

| 文件 | 改动 |
|---|---|
| `avatar-agents/tests/inference_runner_samples.py` | 新增 `GateInitRunner`（初始化时进入测试可观察的屏障）和 `ClosingRunner`（正常关闭时留下关闭钩子的痕迹）；删除已无人使用的 `SlowInitRunner` |
| `avatar-agents/tests/test_runner_process.py` | 原来依赖 `sleep(0.5)` 的初始化取消用例改为屏障驱动；新增 READY 正常关闭用例 |
| `avatar-agents/tests/test_inference_runtime.py` | 原混合取消用例改为屏障驱动，并扩为 cancel/close 两个参数 |
| `avatar-agents/tests/test_avatar_config.py` | +6（O-7） |
| `avatar-host/tests/test_cli_entrypoint.py` | +1（O-7，CLI 端到端） |
| `avatar-host/tests/test_health.py` | 新增，3 个（KD-8） |
| `avatar-plugins/perception/avatar-plugins-memory/tests/test_memory_recall_diagnostics.py` | 新增，7 个（KD-6） |
| `avatar-plugins/perception/avatar-plugins-persona/tests/test_persona_runtime.py` | +4（KD-10） |
| `avatar-plugins/perception/avatar-plugins-persona/tests/test_persona_sensors.py` | +8（O-4） |
| `avatar-plugins/perception/avatar-plugins-router/tests/test_audio_activity.py` | +3（KD-14）；夹具新增 `event_batch_size` 参数和 `ConsumerGate` 调度屏障 |

用例数从 195 增加到 229。依赖、`uv.lock`、CI 均未改动。

### 3. 各项验收

**KD-14 正式回归（只加测试，保持已关闭）**

- 调度屏障 `ConsumerGate` 包装感知事件流的 `wait_for_pending`，让 Audio Activity 只读取测试允许的批次数；每个用例都断言 `audio.input_gap` 的次数，避免额外的缺口掩盖目标问题。
- 3 个用例：

| 用例 | 场景与断言 |
|---|---|
| `test_confirmed_boundary_is_not_reimposed_by_the_rest_of_its_gap_window` | 每批 8 个事件；只放行两批，其中 16 帧静音足以确认边界，确认后再放行窗口内剩余的旧事件；然后让 VAD 超时，强制换流，并立即讲话（不先静音）。断言这句话完整成段、没有 `speech_skipped`、只有 1 次缺口 |
| `test_each_gap_requires_its_own_boundary` | 两次缺口都发生在讲话中途；第二次缺口时没有活动的流，只有"每次缺口重新记证据"才会再次施加要求。断言每次缺口后续说都被跳过（缺口次数与跳过次数都为 1、2），下一句只含新的帧 |
| `test_generation_first_seen_after_the_horizon_is_admitted_at_once` | 缺口被读取之后，新的输入 generation 直接讲话。断言段从它的第一帧开始，讲话帧完整，只有 1 次缺口 |

- 变异验证（内存）：
  - 去掉"每次缺口只施加一次"：只有第 1 个用例失败；
  - 新缺口不重置证据：只有第 2 个用例失败；
  - 忽略 horizon：只有第 3 个用例失败。
- 第 1 个用例的屏障条件只读访问了私有的 `_recovering`，用于判断"边界已确认"；断言仍然只针对可观察的段与 trace。

**O-1（已修复）**

- 改动：`RunnerProcess._close` 记录进程关闭前是否 READY；从未 READY 时，以 `force=True` 回收，即先 SIGTERM，按需再 kill，不再先空等 `close_timeout`。READY 进程的 CLOSE 握手不变。
- 验收：
  - 不用固定 sleep：Runner 在初始化中进入一个文件屏障，测试看到屏障后才取消。
  - 不用苛刻的耗时阈值：`close_timeout` 设为挂起保护的 2 倍（60 s），旧代码会因空等而超过 30 s 的挂起保护，新代码立即收敛。
  - 终止顺序与回收：从 Runner 自己的 `Inference process settled` 诊断读取退出码和 forced 标记。
- 3 组用例：

| 用例 | 断言 |
|---|---|
| 初始化进入屏障后取消 | 退出码为 `-SIGTERM`、forced=True；pid 已回收 |
| READY 进程正常关闭 | 关闭钩子执行；退出码 0、forced=False |
| READY 与初始化中进程混合关闭（调用方取消 `start()` / 直接 `close()` 两种） | 已 READY 的进程经 CLOSE 正常关闭（关闭钩子执行、退出码 0）；初始化中的进程被 SIGTERM 终止；启动状态为 ready/cancelled；子进程、socket 目录和 endpoint 环境变量全部释放 |

- 对照：换回 `HEAD` 版 `process.py` 时，3 个取消或混合用例失败（超过挂起保护），READY 正常关闭照常通过。

**KD-6（已修复）**

- 通道：现有的 Turn 诊断就在 `perception.input_trace` 中（`turn.committed`、`turn.admission` 都带加盐哈希的 `turn_id`），没有新增诊断框架。Host 的 `CoreEventTrace` 只订阅 Core 事件流，所以没有选它。
- 改动：
  - `_finish` 是唯一的完成门闩，在它确定结果后记一条 `memory.recall`，字段只有 `turn_id`、`outcome`、`evidence_count`，不含回忆文本；
  - 原来有一条终止路径没有任何记录（保留名额全部在途时，该 Turn 不会被回忆），现在补记为 `overloaded`；
  - 没有改等待期限、门闩、调度或 MemoryStore。
- 状态（沿用已有值）：ok、empty、timeout、overloaded、unavailable、error、identity_changed。
- 回归：7 个用例，按 Turn 提交顺序与 `turn.committed` 关联，每个 Turn 恰好一条记录。timeout 用例同时断言截止之前就绪被挡住、截止之后才释放。
- 变异：
  - 不记录：7 个全部失败；
  - 错标状态：被换标签的 5 个失败；
  - 只去掉新补的记录：只有对应用例失败。

**KD-8（已修复）**

- 改动：默认 `bind` 为 `127.0.0.1`；显式配置（例如 `0.0.0.0`）保留，并且经 payload 恢复后不变。
- `/status` 的实际字段：
  - 顶层：`ready`、`inference_ready`、`session_backend_ready`、`active_executions`、`admission_available`、`recent_executions`、`inference_runners`、`inference_methods`；
  - Runner 视图：method、启动状态、ready、耗时、异常类型名；
  - 执行视图：execution_id、backend、source_id（LiveKit job id）、state、reason、pid、stop_reason。

  原因字符串受 IPC 模式 `^[a-zA-Z0-9_:.-]*$` 约束，最长 128。不返回配置或凭据。
- 回归：
  - 默认绑定与显式外部绑定：检查实际监听地址；
  - 状态输出：起一个真实的 Health 服务，通过只放行的回环地址 GET `/status`，断言字段集合固定，且虚构的 LiveKit key/secret、VDB key、MCP token、配置路径和 VDB URL 都不出现。
- 对照：换回 `HEAD` 版配置时，默认绑定用例失败。
- 实现保持最小：没有引入账户、权限或认证框架。

**O-7（已修复）**

- 实测：内层模型上的 `hide_input_in_errors` 只在它作为顶层模型被校验时生效。实际路径 `validate_application` → `AvatarConfig.model_validate` 由外层模型决定，所以除了题目要求的 `MCPConfig`，`AvatarConfig` 也必须设置。
- 回归（6 个）：经 `AvatarConfig` 和直接校验 `MCPConfig` 两条路径 × 三种错误输入（未知字段、server 不是映射、vdb_config 不是映射）。断言虚构 secret 不出现在以下任何输出中，同时错误位置仍然准确：
  - `str`、`repr`；
  - `traceback.format_exception`，即 `logging.exception` 打印的内容；
  - `format_error`（CLI 和执行子进程使用的诊断）；
  - `errors(include_input=False)`、`json(include_input=False)`。
- CLI 端到端：`alphaavatar dev` 加载这样的配置，退出码 2，输出只有 `fields: tools.mcp.token`，不含 secret，也不创建应用目录。这一路径原本就只走 `format_error`，所以用例在旧代码上同样通过，用于防止回退。
- 对照：
  - 换回 `HEAD` 版两个配置文件：6 个用例全部失败；
  - 只修 `MCPConfig`：经 `AvatarConfig` 的 3 个仍然失败。
- 新增观察 O-9：`HostConfig` 同样没有隐藏输入，但目前没有暴露路径，不在本批范围。

**KD-10 剩余时序（仅补测试）**

- 设计：Profiler 按 participant 记录 Turn；收尾时以参与者当时的身份抽取画像，保存到解析后的用户名下；已提交 Turn 的 actors 保持冻结。
- 回归：4 个组合，即感知改绑 / Agent 改绑 × Profiler 启动前已提交 / 运行中提交。Turn 以生成的身份提交，解析为 alice 时断言 Profiler 尚未消费。之后断言：
  - 画像提示包含该 Turn；
  - 只为 alice 保存一次；
  - 生成用户的目录不存在；
  - Turn 的 actors 不变。
- 结果：现有代码通过，没有静默漏处理，不修生产代码。
- 变异：Profiler 丢弃"actor 版本与当前身份不一致"的 Turn 时，4 个组合全部失败。

**O-4（仅补测试）**

- 真实调用链：`InferenceExecutor` 和 `PersonaStore._infer` 都会传播取消，"被调用方吞掉取消"的路径不可达。
- 回归：8 个组合，即 Speaker/Face × 推理挂起 / VDB 查询挂起 × 结果一直挂起 / stop 开始时结果就绪。断言：
  - stop 在挂起保护内完成；
  - 测试新建的任务在 runtime 关闭之前全部结束；
  - stop 之后释放结果，身份和证据都不再变化。
- 结果：现有代码通过；O-4 仍只作风险记录。
- 变异：stop 时不取消在途任务，4 个"一直挂起"的组合失败。
- 观察（不是缺陷）：stop 开始时结果就绪的情况下，Face 的 `_stop` 先等待 poll 任务收尾，worker 可能在 stop 期间处理这个已就绪的结果。stop 完成之后不再写入。

### 4. 运行命令与结果

均在 `cd /home/ecs-user/AlphaAvatar && source .venv/bin/activate` 之后执行。

| 项目 | 结果 |
|---|---|
| 定向回归：runner_process、inference_runtime、avatar_config、health、cli_entrypoint、memory、persona、audio_activity | 116 passed |
| 全量（CI 方式：`PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider --basetemp=… --durations=6`）×1 | **229 passed**，29.7 s；basetemp 无残留；`/tmp/aa-*` 无残留；本轮没有新增 `/tmp/alphaavatar-*` |
| 检出目录 | 前后 `git status --porcelain --ignored` 无差异 |
| 压力入口默认一轮 | 6 passed，3.82 s |
| Ruff / 格式 / Workspace / Lock / pre-commit | All checks passed；674 files already formatted；16 members consistent；`uv lock --check` 通过；改动文件的 hook 全部通过 |

### 5. 验证类别与限制

- **离线确定性回归**：本批全部新增用例都属于这一类。外部模型、Provider、VDB 和推理传输使用离线替身；真实 spawn 和 IPC 只放行测试自有的 endpoint。
- **合成压力**：只跑了默认一轮，没有长时运行。
- **真实设备和服务验收**：未做。没有连接真实的 LiveKit、模型或 VDB 服务；Health 的外部绑定只在本机验证了监听地址。
- 测试读取或改写了以下私有状态，Runtime 内部重构时需要同步调整：
  - KD-14 屏障条件：`AudioActivityProcessor._recovering`、`_sources`；
  - KD-8：`AvatarHost._inference`；Health 监听地址 `_runner.addresses`；
  - O-4：`persona._processors`。
- O-1 用例读取 Runner 的 INFO 诊断记录（`Inference process settled`）来判断退出码和是否强制回收。

### 6. 未做事项

- 没有 commit 或 push。
- 没有修改 KD-7 的默认审批行为。
- 没有实现配置公共服务、CLI 新功能或 Runner 并行。

---

## T-8 配置公共能力与 CLI 最小闭环

- 日期：2026-11-02
- 基线 HEAD：`7e877827989a0f19737b40ca422256f970e3fc19`（`dev/v0.6.9`，与远端一致），开始时工作区干净。
- 先完成的记录：T-7 已验收（见总览与 KD 表），O-1、KD-6、KD-8、O-7 关闭，KD-14 保持关闭，KD-10③ 的时序已覆盖，O-4、O-9 保留观察。
- 授权范围：在现有 `avatar-host/alphaavatar/host/configs` 上整理可复用的 Python 接口；新增 `check`、`config show`、`config init`；`dev`/`start` 保持兼容。
- 不在本批：Profile/Bundle、交互向导、Web/TUI/Agent 配置入口、Doctor 实际探测、安装升级回滚、Runner 并行。

### 1. 公共接口（`alphaavatar.host.configs`）

| 接口 | 来源 | 说明 |
|---|---|---|
| `load_application(path, overrides)` | 既有 | 读取 YAML/JSON，应用 `KEY=VALUE` 覆盖，解析路径并校验，无副作用 |
| `validate_application(value, paths=)`、`restore_application(payload)` | 既有 | 不变 |
| `check_application_paths(config)` | 新增，抽取自原有的启动逻辑 | 启动前的只读检查：工作区连续性、旧身份目录；不创建、移动或删除数据。`start` 改为调用它，行为不变 |
| `describe_application(config)` | 新增（`view.py`） | 生效配置的安全投影，可直接输出为文本或 JSON |
| `describe_error(error)` | 新增（`view.py`） | 结构化错误：只有 `type`、`fields`（字段位置）和 `diagnostic`（`format_error` 的输出） |
| `render_template(avatar_id)`、`write_template(path, avatar_id=)`、`REQUIRED_ENVIRONMENT` | 新增（`template.py`） | 最小模板、带校验的写入、需要设置的环境变量清单 |

Core 新增 `alphaavatar.core.log.error_fields`：它就是 `format_error` 原本私有使用的字段位置提取函数，改为公开，以 `include_input=False`、`include_context=False` 调用 `errors()`，只返回位置。

### 2. 命令

> T-8 收敛（第 10 节）：顶层 `check` 已迁移为 `config check`，`config show` 已移除；本节保留首版记录。

```bash
alphaavatar check <config> [KEY=VALUE ...] [--json]
alphaavatar config show <config> [KEY=VALUE ...] [--json]
alphaavatar config init <path> --avatar-id <id>
```

**`check`**

- 加载链与 `start` 相同：`.env`（`ENV_FILE`）、覆盖、默认值、路径解析、只读路径检查。
- 通过：退出码 0，输出 avatar_id、home、workspace。
- 失败：退出码 2；文本模式向 stderr 输出 `format_error`（含 `fields: …`）；`--json` 向 stdout 输出 `{"valid": false, "error": {type, fields, diagnostic}}`。

**`config show`**

- 加载链与 `check` 相同，然后输出 `describe_application`；文本模式是 YAML，`--json` 是 JSON。
- 失败时的输出与 `check` 一致。

**`config init`**

- 校验 avatar id 并渲染模板，之后才创建文件和缺失的父目录。
- 以 `x` 模式创建，已有文件一律拒绝覆盖（退出码 2，原文件不变）。
- 写入失败时删除已创建的文件和本次新建的父目录。
- 成功后列出需要设置的环境变量和下一步命令。

**共同边界**

- `check`/`show` 不创建 HostLog，不需要 AF_UNIX socket；不启动 Host、Runner、模型或后台任务；不构造 VDB/MCP 客户端；不创建应用或 Avatar 目录；不写任何文件。
- `dev`/`start` 的参数和行为不变；`--help`/`--version` 仍只做轻量导入，新命令的模块都是按需导入的。

### 3. 脱敏投影

`ApplicationConfig.payload` 是包含真实凭据的启动快照，`show` 不使用它，也不直接打印 `model_dump()`。`describe_application` 按以下规则生成：

1. **结构**：与配置文件一致，即 `application`（生效的 home/cache_root）、`host`，再加上各 Avatar 分段；`avatar.workspace_root` 即生效的工作区路径。
2. **有类型的字段**：原样展示，包括插件选择、运行参数、路径和数值；字段名像凭据的字符串值（token/secret/passw/api_key/auth/credential/cookie/private）替换为 `[redacted]`。
3. **插件自定义的映射**：按模型字段类型识别（`dict`/`dict[...]`，如 `init_config`、`vdb_config`、MCP `servers` 等 15 处），无法可靠判断敏感性，所以保留键名、布尔、数值和 null，但所有字符串一律替换为 `[hidden]`。不为此建设字段注册框架。
4. **按值兜底**：
   - 从启动快照中收集所有敏感键下的字符串（含去掉 `Bearer`/`Basic` 前缀后的值），在输出的每个字符串中替换为 `[redacted]`，从而覆盖被插值到普通字段里的已解析凭据；
   - 再对每个字符串使用 Host 日志的 `Redactor`：屏蔽环境变量中的凭据值，去掉 URL 中的账号密码、查询串和片段，屏蔽认证头和 `key=value` 形式的凭据。
   - 脱敏作用在值上，而不是序列化后的文本上，所以 JSON 仍然合法。
5. **错误输出**：只用 `format_error` 或 `describe_error`，两者都不含输入值、上下文或异常消息。

实现中修正过一处误判：起初模式里有 `session`，使 `host.execution.on_session_end` 的值被当成凭据，进而按值替换掉了其他字段。会话类字段不是凭据，已从模式中删除，回归断言覆盖了这类非敏感字段。

### 4. 模板

- 内容只包括：avatar（id、name、introduction）、主模型、语音（silero/openai_segment/openai）、关闭 vision、Memory/Persona 的集合名和 embedding、它们的提供方任务，以及默认关闭的工具。用 YAML 锚点复用 embedding 和任务配置，与示例的写法一致。
- 每一项都对应默认插件启动所需的内容。
- 不写 `application.home` 或任何本机绝对路径，保留 Host 的平台路径选择。
- 凭据只在注释里说明：通过环境变量或 `.env` 提供（`OPENAI_API_KEY`、`LIVEKIT_URL/API_KEY/API_SECRET`）；MCP 示例以注释形式给出 `<ENV_VAR>` 占位符的写法。
- `avatar.id` 以 JSON 字符串（合法的 YAML 双引号标量）写入用户给定的值，不随机生成。

### 5. 修改文件

| 类型 | 文件 |
|---|---|
| 新增 | `avatar-host/alphaavatar/host/configs/view.py`、`template.py`；`avatar-host/alphaavatar/host/cli/commands/config.py`；`avatar-host/tests/test_config_commands.py` |
| 修改 | `avatar-host/alphaavatar/host/configs/__init__.py`（导出公共接口）、`loader.py`（`check_application_paths`）；`avatar-host/alphaavatar/host/cli/app.py`（新增子命令）、`commands/run.py`（改用 `check_application_paths`）；`avatar-core/alphaavatar/core/log/diagnostics.py`、`__init__.py`（公开 `error_fields`） |
| 文档 | `avatar-host/README.md`（命令、边界与 Python 接口）；`README.md`（Quick Start 的 Step 1 改名为 Configuration，包含凭据、`config init`、`check`、`config show`，以及应用目录、缓存和离线模式的设置；Step 2 只保留启动）、`examples/README.md`（先 `check` 再启动）；`docs/cli/doctor.md`、`docs/cli/test.md`（当前命令列表，`check` 仅覆盖配置校验，其余仍为计划） |

依赖、`uv.lock`、CI、配置格式、工作区和凭据引用方式都没有改变。

### 6. 回归与验证

`avatar-host/tests/test_config_commands.py`，9 个用例。进程内调用的用例在"沙盒"下运行：拒绝创建 AF_UNIX socket（EPERM），Qdrant 和 LanceDB 客户端一构造即失败，同时有禁网和子进程守卫。

| 用例 | 断言 |
|---|---|
| `check…effective_overrides` | 覆盖生效（`avatar.id=renamed`，workspace 随之变化）；非法覆盖报出字段，不回显值；JSON 失败结构只含字段；没有触碰 socket 或客户端；目录与执行前完全一致 |
| `show…without_credentials` | 文本（YAML）与 JSON 内容一致；保留覆盖后的参数、插件选择和生效路径；VDB、MCP headers 被隐藏；插值到 introduction 里的凭据被替换；5 个虚构敏感值都不出现；没有创建目录 |
| `error_output_never_echoes_rejected_values` ×4 | Avatar 分段错误与外层 Host 分段错误（LiveKit `init_config` 中的凭据字段）× 文本/JSON：`check` 和 `show` 都不回显被拒绝的值；JSON 错误只有 `type`/`fields`/`diagnostic` |
| `init…loads_once_inputs_are_set` | 只新建请求的文件和父目录；id 为给定值；模板不含本机路径和凭据值；`load_application` 能加载，Memory/Persona 插件配置能通过各自的模型校验；`check` 通过 |
| `init_never_overwrites…` | 拒绝覆盖，原文件不变；非法 id 在创建任何目录之前失败；写入时磁盘已满（ENOSPC）的情况下，文件和新建的父目录全部清理 |
| `console_commands_run_without_the_host_log_socket` | 用真实的 console script 依次执行 init、check、show：均不创建 HostLog socket，也不创建工作区；`--help` 列出 dev/start/check/config |

变异验证（内存）：

| 变异 | 失败的用例 |
|---|---|
| `show` 直接输出完整的启动快照 | show 用例 |
| 去掉按值脱敏 | show 用例 |
| check 准备了应用和工作区目录 | check、show 用例 |
| 加载前创建 HostLog | 6 个进程内用例（被 AF_UNIX 沙盒拒绝） |
| 模板写入失败后不清理 | init 失败清理用例 |

运行结果（均在 `cd /home/ecs-user/AlphaAvatar && source .venv/bin/activate` 之后执行）：

| 项目 | 结果 |
|---|---|
| 定向回归：`avatar-host/tests` | 43 passed |
| 全量（CI 方式）×1 | **238 passed**，32.1 s；basetemp 无残留；`/tmp/aa-*` 无残留；本轮没有新增 `/tmp/alphaavatar-*` |
| 检出目录 | 前后 `git status --porcelain --ignored` 无差异 |
| 压力入口默认一轮 | 6 passed |
| Ruff / 格式 / Workspace / Lock / pre-commit | 全部通过（678 files already formatted；16 members consistent） |
| 发布包 | `alpha-avatar-host` wheel 包含新模块，不含 `tests/` |
| 仓库示例（手工核对，非用例） | 5 个示例 YAML 在临时 HOME 下 `check` 和 `config show --json` 都返回 0，注入的虚构密钥出现 0 次，HOME 下没有新文件 |

### 7. 限制与仍待处理

- **O-2**：加载配置时仍会导入插件和第三方库，改写 CLI 进程自身的少量环境变量，约需 1 秒。这不影响"不创建、不连接"的契约，按要求不在本批扩大处理。
- **O-9**：新输出路径不暴露它（只输出 `format_error` 和字段位置），继续保留观察；`HostConfig` 本身没有改动。
- **脱敏是尽力而为**：类型字段按键名、插件映射按"所有字符串"、另加按值兜底。任意插件映射中的非字符串值（数字、布尔）仍会显示。这是有意的取舍：它们是运行参数。
- **模板**：只验证了能加载，插件配置模型能通过校验；没有在真实服务下启动。模型名称沿用仓库示例，是否可用取决于部署账号。
- `AvatarHost._serve` 中原有的同一段只读检查没有改用新函数，行为相同，留待以后整理。
- 本批全部是离线确定性回归；没有做真实设备或服务验收。

### 8. 未做事项

- 没有 commit 或 push。
- 没有实现 Profile/Bundle、交互向导、Doctor 探测或安装升级。

### 9. 输出优化与 CLI 文档整理（基线 `886efcd`）

> T-8 收敛（第 10 节）：`config show` 及其 YAML 高亮已移除；`check` 的样式、摘要边界修复和安全投影保留。

- 基线：`886efcdad71b05c1f1341969921fd090141798c6`（T-8 首版已提交），开始时工作区干净。
- 依据：已确认的 CLI 展示方案，以及把 `docs/cli` 按一级命令拆分、内容简洁的要求。
- 加载、校验和隐藏策略都没有改变；美化只作用在已经脱敏的数据上。

#### 9.1 输出

- **`check`**
  - 成功：stdout 输出绿色粗体 `OK`，再输出 `configuration and read-only path checks passed`；摘要字段左对齐，字段名变暗。
  - 失败：stderr 输出红色粗体 `ERROR` 和 `format_error`；代码位置等辅助行变暗，`fields:` 行保持醒目。
  - 文字标识在无色时同样输出。
- **`config show`**：保留 YAML 结构并逐行高亮：
  - 键名：品牌蓝 `BRAND_BLUE`；
  - 数值、布尔、null：`SIGNAL_CYAN`；
  - `'[hidden]'`、`'[redacted]'`：灰色 `DIM`；
  - 普通值：默认前景色。

  不加行号，不加外框。YAML 设为不折行（`width=inf`），多行字符串的引号续行原样输出，不按键名着色。
- **颜色策略**：复用 `use_color("auto", stream)`，stdout 与 stderr 各自检测；非终端、`NO_COLOR`、`TERM=dumb` 时无色。`--json` 始终输出纯 JSON。输出流和退出码不变。
- **没有采用 Rich**：直接复用 `host/log/format.py` 中现有的 ANSI 品牌色常量（新增 `GREEN`、`RED`，供日志级别颜色共用），因此不新增依赖，也不存在样式标记解析：`[hidden]`、`[redacted]` 和用户字符串天然按字面输出。帮助和版本入口仍为轻量导入。

#### 9.2 check 摘要的输出边界（修复）

- **问题**：首版的 `check` 摘要直接输出原始的 avatar_id、home、workspace，没有经过 `show` 的脱敏和控制字符清理。
- **修复**：新增 `describe_summary(config)`，与 `describe_application` 共用同一个 `_scrubber`：已知凭据按值替换，再经 Host 日志 `Redactor` 屏蔽环境变量凭据、处理 URL、清理 ANSI 和控制字符。文本与 JSON 摘要都使用它。
- **一并修正**：
  - `_scrubber` 现在也清理插件映射中的键名，原来只处理值；
  - `Redactor.__call__` 与 `clean` 新增可选的 `limit` 参数，默认值不变，日志行为不变。配置视图传入 `limit=None`，长于 8192 字符的值完整保留，不会被截断。

#### 9.3 回归（新增 9 个，文件共 18 个）

| 用例 | 断言 |
|---|---|
| `only_an_enabled_terminal_gets_styles_and_json_stays_plain` ×4（终端 / 管道 / `NO_COLOR` / `TERM=dumb`） | 只有可用的终端才着色：`OK` 的样式、键名蓝色、数值青色、`[hidden]` 灰色、普通值默认色；在终端上 `--json` 仍是纯 JSON |
| `each_stream_detects_its_own_terminal` ×2 | stdout 与 stderr 分别判断是否着色；失败只输出字段，不输出被拒绝的值 |
| `show_renders_long_and_markup_like_values_literally` ×2（终端 / 管道） | 超过 8192 字符、带空格的长文本和长路径各占一行、不被截断；`[bold red]this[/]`、`[hidden]` 等按字面输出；注入的 ESC 序列被清除 |
| `check_summary_passes_the_same_output_boundary_as_show` | 已知凭据被复用为 Avatar ID、home 路径中含 ANSI 控制序列：文本和 JSON 摘要都没有 ESC 或 `\u001b`，也没有凭据；ID 显示为 `[redacted]` |

变异验证（内存）：

| 变异 | 失败的用例 |
|---|---|
| 摘要不经过脱敏 | 摘要用例 |
| 恢复 8192 字符截断 | 两个长内容用例 |
| YAML 恢复按 80 列折行 | 两个长内容用例 |
| 忽略 `NO_COLOR` / `TERM=dumb` | 对应两个参数 |
| 总是着色 | 7 个用例 |

写测试时发现，最初的长文本主体是一串没有空格的连续字符，折行变异因此没有被抓到；已改成由单词组成的长文本。

#### 9.4 CLI 文档

- 按要求删除了 `docs/cli/README.md` 和 `docs/cli/design/`。
- 现在每个一级命令一个文件：`dev.md`、`start.md`、`check.md`、`config.md`（包含 `show` 与 `init`）、`doctor.md`、`test.md`，共 151 行。
- `doctor.md`、`test.md` 原来是长篇设计规格（202 行、229 行），现在压缩为"计划中"状态、目的和计划用法。完整规格仍可在 `886efcd` 中查到，例如 `git show 886efcd:docs/cli/doctor.md`。
- `avatar-host/README.md` 的说明精简为命令示例，并加上指向 `docs/cli/` 的链接。

#### 9.5 验证

| 项目 | 结果 |
|---|---|
| 定向回归：`avatar-host/tests`、`avatar-core/tests` | 94 passed |
| 全量（CI 方式）×1 | **247 passed**，32.1 s；basetemp 无残留；`/tmp/aa-*` 无残留；检出目录前后一致 |
| 压力入口默认一轮 | 6 passed |
| Ruff / 格式 / Workspace / Lock / pre-commit | 全部通过 |

#### 9.6 限制

- 颜色使用 24 位真彩色（品牌色）。不支持真彩色的终端会显示近似色，文字不受影响。
- YAML 高亮按行解析 `yaml.safe_dump` 的输出，只决定颜色，不改变内容。少见的键名形式（例如键名内含 `:`）只是不着色。
- 本节修改没有 commit 或 push。

### 10. CLI 收敛（基线 `e428c9b`）

- 基线：`e428c9b6828919ec6375299c81a412159cbc2ced`（输出优化已提交），开始时工作区干净，没有未提交的修改。
- 依据：看过实际终端截图后确认的收敛方案。

#### 10.1 命令

最终保留：

```text
alphaavatar config init <path> --avatar-id <id>
alphaavatar config check <file> [KEY=VALUE ...] [--json]
alphaavatar start <file> [KEY=VALUE ...]
alphaavatar dev <file> [KEY=VALUE ...]
```

- 顶层 `check` 迁移为 `config check`，旧入口直接删除，不保留别名；`alphaavatar check …` 现在是 argparse 用法错误（退出码 2）。
- `config show` 及其帮助入口已删除；`alphaavatar config show …` 同样是用法错误。
- 未来顶层 `check` 的 Agent 检查用途留给对应批次，本批不预留空命令。
- `start`、`dev` 照常执行原有校验；手动 `config check` 只是可选的启动前检查。

#### 10.2 config check 输出

- 输出与迁移前的 `check` 完全相同，只是入口改为 `config check`：
  ```text
  OK  configuration and read-only path checks passed
      avatar_id  alphaavatar_tools
      home       /home/ecs-user/.local/share/alphaavatar
      workspace  /home/ecs-user/.local/share/alphaavatar/avatars/alphaavatar_tools
  ```
- 绿色粗体 `OK`；字段名左对齐并以暗色弱化，值保持默认前景色。
- 失败时：stderr 输出红色粗体 `ERROR  configuration and read-only path checks failed`，接着是 `format_error` 给出的字段位置，代码位置等辅助行变暗。
- 摘要来自 `describe_summary`，已脱敏并清理控制字符。
- 曾按收敛方案改为两行输出（`Configuration valid: <file>` / `Avatar: …`）。看过实际终端后，用户要求保持原来的样式，已恢复。
- 后续按用户确认补充摘要字段（仍为同一对齐格式）：rtc、loop、voice（vad/stt/tts）、router、character、memory 与 persona（插件和向量库后端类型，persona 另含 speaker/face 开关）、tools（启用的工具，MCP 只计 server 数量）、health（监听地址；未设端口时显示 `8081 (dev: free port)`）。
  - 只取有类型的配置选择，以及由它们直接推导的事实；向量库后端由现有的 `vdb_backend()` 推导，与启动时的判断一致。不含任何地址、集合名、URL 或插件自定义设置。
  - 模型名（位于插件自定义设置中）和凭据存在性检测没有加入。
  - 后端推导与 persona 选项校验在启动时同样会执行，所以"Qdrant 只配 host、不配 port"这类启动期错误，现在 `config check` 也会提前报出。
- `--json` 保留原有的键，新增 `plugins`、`health` 两个对象：`{"valid": true, "avatar_id", "home", "workspace", "plugins", "health"}`（均已脱敏）或 `{"valid": false, "error": {type, fields, diagnostic}}`。
- 颜色策略不变：stdout 与 stderr 各自用 `use_color` 检测；非终端、`NO_COLOR`、`TERM=dumb` 时无色；JSON 始终不着色。
- 按用户要求，`config check` 与 `config init` 的文本输出前后各加一个空行，使报告与命令行分开；`--json` 输出不变。
- `config init` 的成功提示改为两种可选的下一步：`alphaavatar dev <path>`（会先校验）和 `alphaavatar config check <path>`（可选，只校验不启动）。模板注释同步改为"可选校验，start 也会校验"。

#### 10.3 删除与保留

| 删除 | 保留 |
|---|---|
| `show` 命令、YAML 高亮（`_highlight`、`_LINE`、`_PLAIN`、`_MARKERS`、`_open_quote`）、不折行 YAML 渲染 | 公共接口 `describe_application`、`describe_summary`、`describe_error`（供检查结果和后续诊断使用） |
| show 专属的测试：长内容渲染、终端高亮配色 | 凭据按值替换、控制字符清理、映射键名清理、`Redactor` 的 `limit` 参数（视图不截断） |

`host/log/format.py` 新增的 `GREEN`/`RED` 仍用于 `OK`/`ERROR` 和日志级别颜色；`BRAND_BLUE`/`SIGNAL_CYAN` 仍由 banner 使用。没有引入 Rich。

#### 10.4 测试（`test_config_commands.py`，18 → 16 个）

| 用例 | 覆盖 |
|---|---|
| `check_reports_valid_and_invalid…` | 新入口；文本输出逐行比对（原有的标题和 avatar_id/home/workspace，加上新增的插件、存储、工具和 health 行）；JSON 新增 `plugins`/`health`，原有键不变；摘要中不出现 VDB 或 MCP 地址；缺端口的远程向量库会报错；覆盖生效；失败标题和字段；沙盒下不触碰 socket、客户端或目录 |
| `safe_projection_keeps_useful_settings_without_credentials`（由 show 用例迁移为公共接口测试） | 选择、参数、覆盖与生效路径保留；VDB 和 MCP headers 隐藏；超过 8192 字符的文本完整保留；复用的凭据被替换；值和映射键名中的 ESC 被清除；5 个虚构敏感值都不出现 |
| `error_output_never_echoes_rejected_values` ×4 | Avatar 分段与外层 Host 分段 × 文本/JSON，都只走 `config check` |
| `check_summary_passes_the_same_output_boundary` | 已知凭据被复用为 Avatar ID、home 路径和文件名中含 ESC：文本与 JSON 摘要都没有 ESC、`\u001b` 或凭据 |
| `only_an_enabled_terminal_gets_styles…` ×4 | 终端、管道、`NO_COLOR`、`TERM=dumb`；JSON 始终不着色 |
| `each_stream_detects_its_own_terminal` ×2 | stdout 与 stderr 分别检测 |
| `init_writes_a_minimal_template…` | init 提示同时给出 `dev` 和可选的 `config check`；模板可以加载；`config check` 通过 |
| `init_never_overwrites…` | 拒绝覆盖、非法 ID、写满时清理 |
| `console_commands_run_without_the_host_log_socket` | 真实命令行入口执行 init 和 `config check --json`；旧的 `check`、`config show` 返回 2；顶层帮助为 `{dev,start,config}`，`config --help` 为 `{init,check}` |

- 内存变异：摘要不脱敏、映射键名不清理，两项分别被对应用例抓到。
- 本节之前已验证的变异（按值脱敏、HostLog 依赖、颜色策略等）对应的断言仍然保留。

#### 10.5 文档

- `docs/cli/check.md` 已删除。配置相关说明集中到 `docs/cli/config.md`（`config init` 与 `config check`）；`start.md`、`doctor.md` 的链接改为指向 `config.md#config-check`。
- 根目录 `README.md` Step 1：`config init`，再加上标为可选的 `config check`，删除 `config show`。
- `examples/README.md`：`config check` 标为可选。
- `avatar-host/README.md`：只保留 init/check 示例和 Python 接口清单。

#### 10.6 验证

| 项目 | 结果 |
|---|---|
| 定向回归：`avatar-host/tests` | 50 passed |
| 全量（CI 方式）×1 | **245 passed**，32 s；basetemp 无残留；`/tmp/aa-*` 无残留 |
| Ruff / 格式 / Workspace / Lock / pre-commit / 压力入口默认一轮 | 全部通过 |

检出目录对比时的一个观察：测试开始前仓库根目录有一个未跟踪文件 `my-avatar.yaml`，测试结束后消失。用户确认它是自己手工测试时创建并删除的，与测试套件无关。另外做了哨兵实验：在仓库根目录放置带标记内容的 `my-avatar.yaml` 和 `t8-sentinel.yaml`，再跑一次全量（245 passed），两者都原样保留，随后删除。

#### 10.7 最终交付清单（T-8）

- **命令**：`config init`、`config check`；`start`/`dev` 不变；顶层 `check` 和 `config show` 已删除。
- **公共接口**（`alphaavatar.host.configs`）：`load_application`、`validate_application`、`restore_application`、`check_application_paths`、`describe_application`、`describe_summary`、`describe_error`、`render_template`、`write_template`、`REQUIRED_ENVIRONMENT`；Core 公开 `error_fields`。
- **安全**：安全投影、按值替换已知凭据、Host 日志 `Redactor`（不截断）、控制字符与映射键名清理、错误只输出字段位置；Host 配置错误路径有回归；O-9 未暴露。
- **文档**：`docs/cli/{config,dev,start,doctor,test}.md`、`README.md`、`examples/README.md`、`avatar-host/README.md`。
- **仍待处理**：O-2（导入副作用）、O-9（观察）；Runner 并行进入下一批；没有做真实设备或服务验收。
- 本节修改没有 commit 或 push。

### 11. `d9a8b4f` review 收尾（基线 `d9a8b4f`）

- 基线：`d9a8b4fd88de01cbcaa2e93f295125ff2c349e1b`（CLI 收敛已提交），开始时工作区干净。
- review 结论：命令收敛方向正确，但有 4 项需要收尾，T-8 暂不标为已验收。命令结构和摘要方案保持不变，修复都是局部的。
- review 环境：收集 245 项，选跑 196 项通过、3 项失败，失败均对应下表第 4 项；IPC 用例仍受环境限制。

| # | 问题 | 修复 |
|---|---|---|
| 1 | `_scrubber` 对固定字段名也做凭据替换。合法配置中出现 `Authorization: "Bearer health"` 时，`health` 键被替换：文本输出先打印 OK、再抛 `KeyError`，JSON 返回成功却缺少字段。`"Bearer "` 剥离前缀后为空字符串，替换时会把 `[redacted]` 插进每个字符之间 | 模型字段名作为固定结构保留，只有来自配置数据的动态键（插件自定义字典中的键，用 `_DynamicKey` 标记）才经过清理；凭据候选剥离前缀后不足 4 个字符的一律过滤。CLI 先完整生成所有输出行，再打印 `OK` |
| 2 | `config init` 可能悄悄改变 Avatar ID：原始 ID `a\u0085b` 本应被拒绝，但写入 YAML 后 U+0085 被折叠成空格，变成 `a b` 并通过校验 | 渲染前先用 `AvatarConfig` 校验原始 ID；渲染后再确认读回的 ID 与输入完全相同，不同则报错。合法的非 ASCII ID 原样保留 |
| 3 | 父目录创建失败时清理不完整：外层目录创建成功、内层因 ENOSPC 失败，清理遇到不存在的内层目录（`FileNotFoundError`）就停止，外层空目录被遗留 | 遇到本来就不存在的目录时继续向上清理；只有遇到其他 `OSError`（例如目录非空）才停止 |
| 4 | 颜色测试没有隔离外部继承的 `NO_COLOR`/`TERM=dumb`，却断言应当着色 | 新增测试夹具 `color_capable`：清除 `NO_COLOR`，设置 `TERM=xterm-256color`，结束时恢复。生产代码继续尊重禁用颜色的设置 |

#### 11.1 回归（16 → 17 个）

| 用例 | 覆盖 |
|---|---|
| `credential_values_never_rewrite_fixed_fields`（新增） | MCP 的 Authorization 分别为 `Bearer health` 和 `Bearer `：`config check` 文本完整输出（含 `health`、`tools … (2 servers)` 两行），JSON 键集合完整，`avatar_id` 不被改写；`describe_application` 保留 `host.health`，两个 server 键名不变 |
| `init_never_overwrites…`（扩展） | `a\x85b` 被拒绝（`fields: avatar.id`），不创建任何文件或目录；`助手-1` 原样写入，并能原样加载；外层目录已创建、内层 mkdir 返回 ENOSPC 时，所有新建目录都被清理 |
| 两个颜色用例 | 使用 `color_capable` 夹具；在外部设置 `NO_COLOR=1` 或 `TERM=dumb` 的情况下，17 个用例照样全部通过 |

对照与变异：

| 对照 | 结果 |
|---|---|
| 临时恢复 `HEAD` 版 `view.py`、`template.py`、`commands/config.py`（之后逐字节还原） | 凭据用例失败（`KeyError: 'plugins'`，由空候选替换引起）；init 用例失败（`a\x85b` 被接受） |
| 只去掉"遇到不存在的目录继续清理" | 清理断言失败：遗留了 `outer` 目录 |
| 保留空候选过滤，只让固定字段名也参与替换 | 凭据用例失败：`KeyError: 'health'` |

#### 11.2 验证

| 项目 | 结果 |
|---|---|
| 定向回归：`avatar-host/tests` | 51 passed；在外部设置 `NO_COLOR=1` 或 `TERM=dumb` 时，`test_config_commands.py` 也是 17 passed |
| 全量（CI 方式）×1 | **246 passed**，32 s；basetemp 无残留；检出目录前后一致 |
| Ruff / 格式 / Workspace / Lock / pre-commit | 全部通过 |

修改文件：`avatar-host/alphaavatar/host/configs/view.py`、`configs/template.py`、`cli/commands/config.py`、`avatar-host/tests/test_config_commands.py`，以及本日志。没有 commit 或 push。

### 12. `4365820` review 与验收

- 基线：`4365820`（第 11 节的修复已提交），开始时工作区干净。
- review 结论：上轮四项修复复核通过，生产代码可以验收；只剩一处旧测试的调度问题。补齐后将 T-8 标为已验收，下一批进入 Runner 并行。
- review 环境：收集 246 项，选跑 199 项通过、1 项失败（就是下面这个调度问题）；17 项配置命令测试全部通过；IPC 用例没有独立全量复跑。

**问题**

- `test_audio_activity.py` 的 `fail_vad()` 在注入 VAD 推理超时之后才推入 4 帧静音。
- 这 4 帧可能遇到一个已经关闭、但还没报告失败的 VAD 输入队列，从而合法地触发 `VAD_INPUT_REJECTED`。这是一种连续性缺口，会给下一条流打上恢复要求。
- 测试原本假设新流不需要等待边界，于是出现了在挂起保护时间内等不到结果的失败。

**修复（只改测试，音频生产代码不变）**

- `fail_vad()` 改为：
  1. 关闭离线 VAD 的推理闸门；
  2. 推入 4 帧，等待它们被 Audio Activity 消费，即已经进入旧流；
  3. 设置超时并打开闸门。
- 这样超时只会发生在这些帧被旧流接收之后，失败原因确定是非缺口的 `VAD_ERROR`。
- 新增 `speech` 参数。`test_recovery_survives_a_stream_that_fails_before_its_boundary` 原来有一段内联的同类注入，也改为使用这个辅助函数。在竞态下，那个用例虽然仍会"通过"，但走的是缺口路径，覆盖不到它要验证的"非缺口失败后仍保留要求"。

**验证**

| 项目 | 结果 |
|---|---|
| `test_audio_activity.py` ×3 | 17 passed ×3 |
| 3 个相关用例，4 个 CPU 满载进程下连续 30 次 | 0 失败 |
| KD-14 变异重跑（创建流时删除标志、不去重、不按缺口重置、忽略 horizon） | 各自只让对应用例失败，原有的缺口断言仍然有效 |
| 全量（CI 方式）×1 | **246 passed**，31.9 s；basetemp 无残留；检出目录前后一致 |
| Ruff / 格式 / Workspace / Lock | 全部通过 |

**T-8 最终状态**

- 已验收。
- 命令：`config init`、`config check`、`start`、`dev`。
- 公共接口、安全边界和文档见第 10.7 节。
- 仍待处理：O-2、O-9（观察），以及真实设备和服务验收。
- 下一批：Runner 并行。
- 本节修改没有 commit 或 push；之后由用户提交为 `e7bc3b3`。

**最终复核（`e7bc3b3`）**

- 验收提交：`e7bc3b3`（即上面的测试屏障收尾）。
- review 环境选跑 **200 项全部通过**，此前失败的 `fail_vad()` 相关音频用例已通过。
- Ruff、格式、workspace、lock 检查通过。
- IPC 用例没有在 review 环境独立全量复跑。
- T-8 正式收口。

---

## T-9 Runner 可配置并行与压力验证

- 基线：`e7bc3b3`（T-8 验收提交），开始时工作区干净。
- 范围：同一 inference method 的真实执行并行，默认行为不变；配置放在 `RuntimeConfig.inference`（替换最初的 `host.inference` 方案，实施前已调整，未产生过 `host.inference` 入口）。
- 不做：自动扩缩容、动态批处理、通用资源调度；不新增 CLI 命令，不恢复 `config show`。

### 1. 最小设计（实施前）

**配置：`RuntimeConfig.inference`（`InferenceConfig`）**

- 配置类只负责参数和纯校验；调度、回收在 `runtime/inference`。
- 服务端（Host 消费一次，构建共享 Runner 池）：`max_pending`、`queue_timeout`、`request_timeout`、`initialize_timeout`、`close_timeout`、`restart_limit`、`restart_window_seconds`。
- 客户端（各会话的 Executor）：`client_timeout`（等待本地通道 + 连接 + 发送）；等待响应的预算仍取自服务端握手（排队 + 执行 + 结算），与服务端推理超时分开。
- 按 method 覆盖：`methods.<method>.workers`，默认 1，上限 8。不按 CPU 核数自动增加副本。
- `HostConfig` 不重复维护 Runner 配置；会话容量 `host.processes.capacity`、Health、监督轮询仍归 Host。

**并行能力声明**

- `InferenceRunner.REPLICABLE: ClassVar[bool] = False`。只有声明为 `True` 的 Runner 允许 `workers > 1`；否则明确报错。
- 能力跟随 Runner 类声明，Host、MCP、调度器中不出现 method 字符串。
- 本批声明：Silero VAD（状态随请求传递）、Smart Turn v3（单请求无状态）。VDB（读改写、进程内锁）、MCP 目录、Semantic Addressing（进程内 KV 缓存、多线程 llama.cpp）、Speaker／Face（可能使用 CUDA，未验证）保持单实例。

**计划与校验（纯操作）**

- `prepare_inference_runners` 拆出纯函数 `plan_inference_runners(config)`：只运行插件 bootstrap、对照 `runtime.inference` 检查拼错/未选中的 method 和不可复制的 Runner，不写环境变量、不启动进程、不加载模型。
- 配置加载／还原（`validate_application`）、`config check`、摘要、Host 启动都调用同一个检查。
- `prepare_inference_runners` = 计划 + 写入计划环境变量，仅 Host 启动时调用。

**服务端调度（`runtime/inference/pool.py`）**

- 每个 method 一个 `RunnerPool`，持有 N 个独立 `RunnerProcess`；每个进程内部仍串行，并且一次只接受 1 个请求（`max_pending=1` 作为不变量保护）。
- 容量：`max_pending` 按 method 计算，**包含执行中和等待中**的请求，不随 worker 或连接数量倍增；`workers` 不能超过 `max_pending`。
- 优先交给空闲 worker；没有空闲 worker 时，在池内有界 FIFO 队列中等待，不预先塞给某个 worker。
- 排队阶段受 `queue_timeout` 约束；超时或取消的请求从队列撤回，之后不会执行。分派后受 `request_timeout` 约束；执行超时沿用既有策略：回收该 worker，不重放。
- 服务端连接处理在请求挂起期间同时监视客户端：客户端断开时撤回排队请求；已分派的请求由原 worker 读完响应并丢弃，迟到响应不会串到其他请求。
- 健康：全局 `is_alive` 要求每个 method 的所有 worker 就绪；请求准入只要求该 method 至少一个 worker 就绪（降级运行）。全部 worker 不可用时，等待者立即收到"暂时不可用"。
- 恢复：按 worker 槽位先安全回收，再在既有的每 method 重启额度内重建；替换进程就绪前不接收请求，健康 worker 继续服务。

**客户端（`InferenceExecutor`）**

- 复用现有串行连接单元 `_InferenceConnection`（保留连接锁）；每个 method 增加最多 `workers` 个通道，空闲通道放在 FIFO 队列中，等待受 `client_timeout` 与 `max_pending` 限制。
- 一个通道同一时间只有一个请求，请求与响应的归属由通道独占保证；取消仍然丢弃该通道的连接。
- 限制来自会话进程从启动快照还原出的同一份 `runtime.inference`。

**诊断**

- `InferenceRunnerStatus` 增加：`workers`、`ready_workers`、`executing`、`waiting`、`rejected`、`queue_timeouts`、`execution_timeouts`、`restarts`。不包含请求内容、模型输入或凭据。
- `ready` 含义不变：该 method 配置的 worker 全部就绪（`workers=1` 时与原先相同）。

- 实施中按用户补充调整：`MAX_INFERENCE_WORKERS = 8` 放在 `alphaavatar/agents/constants.py`，`runtime_config.py` 从那里导入。

### 2. 实现与设计的差异

- 校验错误用 pydantic `ValidationError`，位置就是出错的覆盖项，如 `runtime.inference.methods.<method>` 或 `…<method>.workers`。原因：CLI 的 `format_error` 只输出类型和字段位置，不输出异常文本；普通 `ValueError` 无法说明哪一项出错。
- 计划检查放在 `validate_application`（加载／还原的共同入口），所以 `config check`、`start`/`dev`、会话子进程还原都会执行。副作用：远端 VDB 缺端口这类计划错误，现在加载时就报告（原来在摘要或启动时才报告），原因链不变。
- 命令行覆盖：带点的 method 名必须用映射写法 `'runtime.inference.methods={alphaavatar.voice.vad.silero: {workers: 2}}'`。点路径写法会把名字拆开，被 `extra="forbid"` 拒绝，不会被静默接受。
- 进程内调用 `InferenceRuntime.do_inference(timeout=…)` 时，同一个显式预算分别约束排队和执行，与原有语义一致。

### 3. 修改文件

| 文件 | 改动 |
|---|---|
| `avatar-agents/alphaavatar/agents/constants.py` | `MAX_INFERENCE_WORKERS = 8` |
| `avatar-agents/alphaavatar/agents/configs/runtime_config.py` | `InferenceMethodConfig`、`InferenceConfig`，`RuntimeConfig.inference` |
| `runtime/inference/runner.py` | `InferenceRunner.REPLICABLE = False` |
| `runtime/inference/pool.py`（新增） | `RunnerPool`：每 method 的有界 FIFO 调度、容量、排队超时、计数 |
| `runtime/inference/process.py` | `busy`、`on_settled` 回调（不改交换和回收逻辑） |
| `runtime/inference/runtime.py` | 按 method 建池；按 worker 启动、恢复、关闭；连接处理监视客户端断开；快照计数 |
| `runtime/inference/executor.py` | `_InferenceChannels`：每 method 至多 `workers` 个串行连接；`InferenceExecutor(endpoint, config)`、`from_env(config)` |
| `runtime/inference/bootstrap.py`、`__init__.py` | `plan_inference_runners`（纯）、`check_inference_config`；`prepare_inference_runners` 改为调用纯计划 |
| `runtime/inference/schemas.py` | 状态增加 worker、执行、等待、拒绝、超时、重启计数 |
| `silero_runner.py`、`smart_turn_v3.py` | `REPLICABLE = True`，并注明依据 |
| `avatar-host/.../application/application.py` | 用 `avatar.runtime.inference` 构建共享运行时 |
| `avatar-host/.../application/bootstrap.py` | 会话 Executor 使用还原出的同一份配置 |
| `avatar-host/.../configs/loader.py` | 加载时检查推理计划 |
| `avatar-host/.../configs/view.py`、`cli/commands/config.py` | 摘要增加 `inference`（各 method 的 worker 数）与一行文本 |
| `docs/cli/config.md`、`examples/README.md` | 检查输出示例；并行配置示例和支持边界 |
| 测试 | 新增 `test_inference_parallel.py`（11 项）；`test_runner_stress.py` 增加并行场景（workers 1/2）；新增 1 项 Host 配置测试；样本 Runner 增加 `ParallelRunner`、`SecondParallelRunner`、`SileroProtocolRunner`；其余测试只随新构造参数和输出行调整 |

### 4. 配置示例与支持边界

```yaml
runtime:
  inference:
    methods:
      alphaavatar.voice.vad.silero:
        workers: 2  # 1-8，显式开启；每个 worker 持有一份模型
```

| Runner | 允许 `workers > 1` | 依据 |
|---|---|---|
| Silero VAD | 是 | 上下文与循环状态随请求传入并返回；进程内只有只读 ONNX 会话 |
| Smart Turn v3 | 是 | 每个请求是完整音频窗口，请求之间无状态 |
| Memory／Persona／MCP VDB | 否 | 读改写与进程内锁，多实例一致性未证明 |
| Semantic Addressing | 否 | 进程内 KV 前缀缓存、多线程 llama.cpp；正确性可能不受影响，但内存与 CPU 占用会成倍增加，未验证 |
| Speaker（vector/attribute）、Face | 否 | 可能使用 CUDA，显存占用与多实例行为未验证 |

- 拼错、未选中或不可复制的覆盖会在加载时报错，并给出字段位置。
- 默认值：`max_pending=64`（按 method，含执行中）、`queue_timeout=30`、`request_timeout=30`、`client_timeout=35`、`initialize_timeout=300`、`close_timeout=5`、`restart_limit=2`、`restart_window_seconds=300`。
- `host.processes.capacity`（会话数）与 worker 数相互独立。

### 5. 调度语义（实现后）

- 容量：`max_pending` = 等待 + 已交给 worker + 执行中（包括调用方已离开、worker 仍在读响应的请求）。不随 worker 或连接数倍增；`workers ≤ max_pending`。
- 每个 worker 一次只接一个请求；`RunnerProcess(max_pending=1)` 保护这个不变量，调度出错时会拒绝，而不是悄悄排队。
- worker 空闲后立即同步交给最早的等待者（`on_settled → wake`），等待者不会被预先绑定到某个 worker。
- 排队阶段被取消、超时或客户端断开：撤回，以后不会执行，计入 `queue_timeouts`（超时时）。
- 已分派后调用方离开：原 worker 读完响应并丢弃，worker 在此期间保持忙碌，迟到响应不会被交给其他请求。
- 执行超时：沿用既有策略，回收该 worker，不重放，计入 `execution_timeouts`。
- 所有 worker 都不可用时，等待者立即收到"暂时不可用"，新请求被拒绝。
- 恢复：每次处理一个槽位，先回收再重建，替换进程就绪后才接收请求；同 method 的健康 worker 继续服务；重启额度按 method 共享。
- 健康：`is_alive` 要求所有 worker 就绪，所以降级时 Host 的监视器会触发恢复，`ready`/会话准入与原来一样会暂时关闭；请求准入只要求该 method 至少一个 worker 就绪，因此已建立的会话在降级期间仍可推理。

### 6. 测试

`avatar-agents/tests/test_inference_parallel.py`：全部经过真实 `InferenceExecutor` → unix socket → 服务端 → `RunnerProcess`（spawn）。时序依靠 Runner 进入、测试打开的文件闸门，不用固定 sleep 或速度倍率。

| 用例 | 覆盖 |
|---|---|
| `test_a_replicable_runner_stays_serial_until_configured` | 默认 1：第二个请求在服务端等待，同一 PID |
| `test_two_workers_run_one_sessions_requests_at_once_and_never_exceed_the_limit` | 同一 Executor 两个请求同时位于两个不同 PID 的 Runner 内（屏障）；第三个请求在服务端等待，不会进入；乱序完成，结果归属正确；等待者交给先空出的 worker |
| `test_results_stay_with_their_callers_across_executors_and_methods` | 3 个 Executor × 2 个并行 method × 2 次调用，逆序放行；串行 method 不被阻塞；每个请求只执行一次 |
| `test_full_queue_rejects_and_cancelled_requests_never_run_or_leak_results` | 容量含执行中（2 + 1）；第 4 个被拒绝；排队取消被撤回且从未执行；执行中取消由 worker 读完并丢弃，worker 不被回收；之后各通道只拿到自己的结果 |
| `test_queue_and_execution_timeouts_withdraw_or_retire_without_replay` | 排队超时撤回、从未执行；执行超时只回收那个 worker；降级期间另一个 worker 继续服务；恢复后 `restarts=1`；不重放 |
| `test_a_killed_worker_is_reaped_and_rebuilt_while_its_peer_keeps_serving` | 杀掉一个 worker：在途请求失败且不重放，同伴的在途请求完成；恢复；替换进程初始化失败时同伴继续服务；重启额度耗尽后不再尝试 |
| `test_waiting_requests_fail_at_once_when_no_worker_is_left` | 两个 worker 都被杀时，等待者立即失败，不等排队超时；恢复后继续服务 |
| `test_partial_start_failure_and_cancelled_initialization_release_every_worker` | 第 2 个 worker 初始化失败、初始化中取消：进程、fd、socket 目录、端点变量全部回收；诊断不含 Runner 消息 |
| `test_close_is_idempotent_and_reclaims_every_worker_and_channel` | 两轮启停、在途请求、重复关闭，回收所有资源 |
| `test_parallel_configuration_is_validated_before_any_process_starts` | 非法数值、类型、额外键、未裁剪名称、`workers > max_pending`；未选中与不可复制的覆盖报错位置；不启动任何进程 |
| `test_concurrent_voice_sources_keep_their_own_state_results_and_cancellation` | 真实 `SileroVADStream` × 3 共享一个 Executor，服务端为 Silero 协议的无模型 Runner（2 个 worker）。一路被闸门挡住并取消，另外两路继续；各自状态只反映自己的历史（语音 1000、静音 1），事件各自正确（说话者 start/end，聆听者无事件）；被取消的那一路不影响其 worker |

Host：`test_runner_parallelism_is_checked_against_the_selected_plan_and_survives_restore`（`config check` 文本与 JSON 展示 worker 数；`restore_application` 得到相同的 `runtime.inference`；未选中、拼错、不可复制、`max_pending=0` 分别报出字段位置；不写计划环境变量，不构造客户端、socket 或文件）。

### 7. 变异验证（文件临时替换后逐字节恢复）

| 变异 | 结果 |
|---|---|
| M1 客户端忽略 workers（固定 1 个通道） | 被杀死（两个请求无法同时进入） |
| M2 服务端不监视客户端断开 | 被杀死（排队请求未被撤回） |
| M3 容量不计执行中 | 被杀死（第 4 个未被拒绝） |
| M4 调度不检查 worker 是否忙 | 被杀死 |
| M5 去掉排队时限 | 被杀死 |
| M6 恢复时连同健康 worker 一起重建 | 被杀死（同伴 PID 改变） |
| M7 全局健康改为"任一 worker 就绪" | 被杀死 |
| M8 不检查 `REPLICABLE` | 被杀死（agents 与 Host 两侧） |
| M9 没有 worker 时不让等待者失败 | 被杀死 |
| M10 调用方离开后提前释放 worker | 被杀死 |
| M11 接受未选中的 method 覆盖 | 被杀死 |
| M12 新请求不让位于等待者 | **存活**：等价变异。worker 空出时 `wake()` 同步交给等待者，不会出现"有空闲 worker 且有等待者"的可观察状态；这个判断只是防御 |

### 8. 运行结果

| 项目 | 结果 |
|---|---|
| 全量（CI 方式：`--basetemp`、检出前后对比）×1 | **260 passed**，43.0 s；检出目录前后一致 |
| `test_inference_parallel.py` ×10 | 0 失败 |
| 并行 + 运行时 + 配置命令（39 项），16 个满载 burner 占满 16 核 ×5 | 0 失败（每轮约 38 s） |
| Ruff / 格式 / `scripts/check_workspace.py` / `uv lock --check` / pre-commit 配置 | 全部通过 |

**合成压力（`--stress-seconds 30`，模型无关的 Runner，非设备或生产性能）**

| 场景 | 结果 |
|---|---|
| 既有并发归属（4 会话 × 3 method） | 3017 轮，289632 次请求，0 错配；p50 1.24 ms，max 3.38 ms |
| 既有故障回收 | 284 次杀进程，284 次恢复，恢复 p50 101.5 ms；无重放 |
| 既有启停 | 133 轮，p50 225.7 ms；无残留 |
| 并行 workers=1（4 会话 × 8 并发，每次执行 5 ms） | 5824 次，0 错误，194 req/s；延迟 p50 86.2 ms／max 168.5 ms；执行 p50 5.07 ms；估算排队 p50 81.1 ms；并发峰值 1；无拒绝、超时、残留进程或 fd |
| 并行 workers=2（同上） | 11584 次，0 错误，385.5 req/s；延迟 p50 44.8 ms／max 85.0 ms；执行 p50 5.07 ms；估算排队 p50 39.7 ms；并发峰值 2（2 个进程）；无拒绝、超时、残留进程或 fd |

"估算排队" = 端到端延迟 − 执行时间中位数，包含客户端和 IPC 开销。

**真实模型（本机缓存的 Silero v6.2.1，CPU，16 核；只在本地测量，不是 CI 用例，也不是设备或服务验收）**

8 路持续流、4 个 Executor，每路 300 个窗口，每路的请求按顺序发送：

| workers | 吞吐 | p50 | p99 | max |
|---|---|---|---|---|
| 1 | 5311／5449 req/s | 0.71／0.72 ms | 1.19／0.80 ms | 237.9／221.3 ms |
| 2 | 7736／7853 req/s | 1.01／1.00 ms | 1.15／1.24 ms | 3.16／2.82 ms |

- 吞吐约提高 45%；p50 略升（多一个进程竞争）。
- workers=1 时有一次约 0.2 s 的最大值，原因没有排查（可能是首次推理预热）。
- 8 路实时音频约需 250 req/s，单 worker 已有充分余量；本机 Silero 并行的收益有限，主要价值在更慢的模型（如 Smart Turn）和更多路数。Smart Turn 没有做真实模型测量。

### 9. 限制与仍待处理

- 只在两个 Runner 上声明可复制；其余保持单实例，需要独立证据后才能开放。
- 服务端 `max_clients=256` 仍是固定默认值。并行后，连接数约为 会话 × method × worker；默认容量（5 会话）下远低于上限，大规模并行时需要另行评估。
- 降级时 `is_alive` 为假，沿用"任一 Runner 不健康就暂停新会话准入并触发恢复"的既有策略；重启额度耗尽时 Host 仍然 fail closed，即使同 method 还有健康 worker。
- 没有真实设备、LiveKit 会话或 GPU 上的验证；真实模型只测了 Silero（本机 CPU）。
- 本地测量脚本用 `tempfile.mkdtemp()` 在 `/tmp` 留下 4 个空目录（`tmp71l1dagq`、`tmpqkgtb0yt`、`tmp45q1idsn`、`tmpyeclts4j`）。自动删除被权限策略拒绝，未清理。
- O-2、O-4、O-9、KD-7、KD-10② 继续观察。

### 10. 未做事项

- 没有新增 CLI 命令，没有恢复 `config show`，没有自动扩缩容、动态批处理或通用资源调度。
- 没有修改各 processor／store 的使用方式；插件仍通过原有 `do_inference` 接口调用。
- 本批修改没有 commit 或 push。

### 11. `41ba2c0` review 收尾（基线 `41ba2c0`）

- review 结论：配置归属、Host 共享池、默认单 worker、可复制声明、容量控制和响应归属符合要求；有 1 个进程回收问题（P2）和 1 个关闭边界问题，修复前不标为已验收。
- review 环境：收集 260 项，选跑 202 项通过；11 项并行测试和 5 项默认压力测试通过（只把 Unix 监听和连接换成测试自有的回环 TCP，真实子进程和协议不变）；Ruff、格式、workspace、lock 通过。AF_UNIX 监听受限，原生 IPC 没有独立全量复跑。

#### 11.1 问题与原因

| 问题 | 原因 | 修复前的确定性复现 |
|---|---|---|
| P2：恢复与关闭并发时遗留新 Runner 进程 | 恢复在 `await` 回收旧 worker 之后，没有再检查关闭状态，继续创建替代 worker；关闭按旧快照把槽位清成 `None`，丢掉了替代 worker 的引用；恢复又继续处理下一个槽位 | 两个 worker 都被杀死，恢复正在回收第一个时请求关闭：关闭和恢复都返回后仍有替代进程存活，日志显示恢复继续处理了 worker=1。另一个窗口：关闭中断替代 worker 的初始化时，`CancelledError` 传给了并未被取消的恢复调用方 |
| Executor 关闭返回时本地排队调用尚未退出 | `_InferenceChannels.close()` 只等待连接关闭；排队者要等通道依次回到队列后才失败，此时 `close()` 已经返回 | 1 个在途、16 个本地排队：`close()` 返回时排队调用仍未结束 |

#### 11.2 修复（`runtime.py`、`executor.py`）

- 恢复在回收旧 worker 之后、计数和创建之前检查关闭状态；关闭一旦开始就返回 `False`，不再创建进程，也不计入重启。创建 worker 与写入槽位之间没有 `await`，所以关闭开始后不会出现它看不到的 worker；关闭开始前创建的 worker 都在槽位里，由关闭统一回收，正在初始化的也会被中断。
- 关闭中断替代 worker 的初始化时，恢复内部把这次取消转为返回 `False`；如果是调用方自己被取消（`cancelling()`），照常传播。
- 关闭只清空它回收的那个 worker 所在的槽位，按对象比较。
- 关闭回收全部 worker 后，等待恢复锁释放，因此返回时恢复已经结束。
- `_InferenceChannels` 记录在途和本地排队的调用；关闭连接后，等它们全部离开才返回。已关闭的通道回到队列后依次拒绝本地等待者，报错为 "Inference connection is closed"；在途调用照旧收到取消；服务端已分派的请求照旧由原 worker 读完并丢弃。
- Host 的关闭顺序不受影响：Host 先取消监视任务，再关闭推理服务。这次的竞态出现在恢复和关闭由不同调用方并发触发时。

#### 11.3 回归测试（`test_inference_parallel.py`，修复前均失败）

| 用例 | 覆盖 |
|---|---|
| `test_close_during_recovery_starts_no_worker_and_reclaims_every_one[reaping]` | 两个 worker 都被杀死；启动恢复后让出一次事件循环，恢复此时已过检查、正在回收第一个失效 worker，这时请求关闭。断言：关闭返回时恢复已结束并返回 `False`；没有子进程残留；没有启动替代进程（`inits` 仍为 2）；`restarts=0`；重复关闭后仍无残留 |
| 同上 `[starting]` | 替代 worker 被 `init3.hold` 闸门挡在初始化中时请求关闭。断言：初始化被中断，恢复返回 `False`，调用方没有收到取消；第二个槽位没有被重建（`inits=3`）；无残留 |
| `test_executor_close_returns_after_its_running_and_locally_queued_calls_left` | 一个通道，1 个在途（闸门挡住）、16 个本地排队。`close()` 返回时 17 个调用全部结束：在途调用收到取消，排队调用收到 closed；放行后在途请求在原 worker 上结束，排队的请求都没有执行 |

`[reaping]` 的时机靠 asyncio 的任务调度保证：恢复任务先于测试的后续步骤运行，第一次挂起就在回收旧 worker 处。这里没有公开的观察点；如果以后在回收之前加入新的 `await`，用例仍会覆盖"恢复中途关闭"，但窗口可能会变。

#### 11.4 变异验证（文件临时替换后按 SHA-256 恢复）

| 变异 | 结果 |
|---|---|
| N1 关闭开始后恢复仍创建 worker | 被杀死（`[reaping]` 有替代进程残留） |
| N2 关闭中断初始化时，把取消传给恢复调用方 | 被杀死（`[starting]`） |
| N3 关闭不等待恢复结束 | **存活**：被中断的恢复在同一批事件循环回调里同步返回，眼下观察不到差别；作为防御保留，让"关闭返回时恢复已结束"不依赖回调顺序 |
| N4 关闭按旧快照无条件清空槽位 | **存活**：有了 N1 的检查，关闭开始后槽位只会从 worker 变成 `None`，不会换成新 worker；作为防御保留，即 review 指出的第 486–498 行 |
| N5 Executor 关闭不等待本地排队调用 | 被杀死 |

#### 11.5 运行结果

| 项目 | 结果 |
|---|---|
| 全量（CI 方式：`--basetemp`、检出前后对比）×1 | **263 passed**，43.0 s；检出目录前后一致 |
| 3 个新用例 ×20 | 0 失败 |
| `test_inference_parallel.py`（14 项）×10 | 0 失败 |
| 并行、运行时、配置命令测试（42 项），16 个满载 burner 占满 16 核 ×5 | 0 失败（每轮 33–37 s） |
| `test_runner_stress.py --stress-seconds 10` | 5 passed：并发 96768 次请求、0 错配；故障回收 96 次杀进程、96 次恢复；启停 45 轮；并行 workers=1 为 1952 次、194 req/s，workers=2 为 3872 次、386 req/s；0 错误，无残留进程或 fd |
| Ruff、格式、`scripts/check_workspace.py`、`uv lock --check`、对改动文件运行 pre-commit | 全部通过 |

- 修改文件：`runtime/inference/runtime.py`、`runtime/inference/executor.py`、`avatar-agents/tests/test_inference_parallel.py`、本日志。
- 收尾修改随 `69813df` 提交。§9 记录的 4 个 `/tmp` 空目录仍未清理。

### 12. `69813df` 复核与验收

- 结论：**T-9 已验收**，验收提交 `69813df`，没有新的阻断问题。
- 恢复与关闭：
  - 旧复现不再创建或遗留替代进程；
  - 关闭中断初始化时，恢复返回 `False`；
  - 调用方主动取消时，仍传播 `CancelledError`；
  - 关闭返回前，恢复已经结束。
- Executor 关闭：
  - 64 个调用的复现中，`close()` 返回时全部结束，`pending=0`；
  - 并发关闭、排队取消和清理异常都能正确收尾。
- review 环境：
  - 收集 263 项，直接选跑 202 项通过；
  - 回环 TCP 替换 Unix 监听和连接边界（保留真实子进程和协议）后，14 项并行、10 项 Runtime、5 项默认压力测试全部通过；
  - Ruff、格式、workspace、lock 检查通过，仓库无修改；
  - 原生 AF_UNIX 全量复跑仍受该环境限制。
- 不阻塞验收的已知事项：
  - `[reaping]` 用例目前确实进入预期窗口，以后重构可能改变这个窗口；
  - N3、N4 两个存活的防御性变异，不再扩大修改。
- 下一阶段：安装、升级失败回滚及 Doctor。
