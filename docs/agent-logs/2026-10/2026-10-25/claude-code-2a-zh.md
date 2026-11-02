# AlphaAvatar v0.6.9 阶段 2A — Claude Code 实施日志

- 分支：`dev/v0.6.9`；日期均为 CST
- 2A 各批次都记录在本文件中，新批次按时间顺序追加到末尾。
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
| T-4 | KD-14 补齐：缺口后先确认可靠的静音或结束边界，再接纳语音开始 | 2026-11-02 | `dca356f` | 未提交 | 待审查；收集 190 个，190 passed（CI 方式 ×3） |

## 已知缺陷（当前状态，只记录不修复）

| ID | 问题 | 归属 | 变更记录 |
|---|---|---|---|
| ~~KD-1~~ | ~~`AvatarConfig` 校验时创建 Workspace、写入 `AVATAR_WORK_DIR`/`AVATAR_TIMEZONE`；同一进程内重复校验会让 ID 重复追加（R3）；没有 base 时会写探测 `/var/lib/<id>`~~ | 已关闭 | 2A-1 记录；2A-2a 移除随机 UUID；**T-1 复核：已修复**。`AvatarInfoConfig` 只做纯校验，loader 不建目录、不写环境变量；同进程重复加载不再嵌套；`/var/lib/<id>` 只在激活时做只读的连续性检查。回归：`test_avatar_config.py`、`test_application_config.py::test_repeated_loads_keep_paths_and_credentials_separate` |
| ~~KD-2~~ | ~~Memory 和 Persona 配置在校验时写 `*_VDB_*` 环境变量（配置被拒绝时也写），并构造 QdrantClient。`check_compatibility=True` 会在构造时发出 HTTP 版本请求，Host 和执行子进程各执行一次，客户端从不关闭~~ | 已关闭 | 2A-1 记录；2A-2a 补充 HTTP 版本请求与客户端未关闭；**T-1 复核：已修复**。`snapshot_vdb_config` 只读取 `QDRANT_URL`/`QDRANT_API_KEY` 作快照，不写环境变量、不构造客户端；Runner 只从 `RunnerLaunch` 快照取配置。回归：`test_avatar_config.py`（已去掉 KD-2 白名单）、`test_runner_launch.py::test_remote_vector_runners_connect_with_their_launch_snapshot` |
| ~~KD-3~~ | ~~Tools 配置把解析后的 secret 写入 `MCP_*` 环境变量~~ | 已关闭 | 2A-1 记录；**T-1 复核：已修复**。`<ENV>` 占位符在校验时解析进 `servers` 快照，不写环境变量；子进程用 launch 快照。回归：`test_avatar_config.py::test_accepted_configuration_only_reads_its_inputs`、`test_application_config.py::test_restore_keeps_frozen_paths_and_inputs_after_the_environment_changes` |
| ~~KD-4~~ | ~~Persona LanceDB 查询中 `user_id` 直接拼接、未转义，不安全~~ | 已关闭 | 2A-1 记录；**T-1 复核：已修复**。`_user_filter` 转义单引号，拒绝空值和 NUL。回归：`test_persona_profile.py::test_lancedb_user_predicates_isolate_quoted_identities_and_resave_idempotently`（真实 lancedb） |
| ~~KD-5~~ | ~~Persona VDB 保存失败的错误没有被正确处理~~ | 已关闭 | 2A-1 记录为"保存只检查结果是否为假值"；2A-2a 按审计统一表述；**T-1 复核：已修复**。空结果和 `*error` 字段都抛 RuntimeError，`save` 汇总为 ExceptionGroup。回归：`test_persona_runtime.py::test_vdb_save_failure_surfaces_instead_of_silently_succeeding` |
| KD-6 | Memory Passive Recall 的具体完成状态没有完整传播到 Turn-level diagnostics | Memory 诊断批次 | 2A-2a 按审计更正：原表述"检索出错返回 `[]`，与空结果无法区分"不准确，问题不在 MemoryStore；**T-1 复核：仍存在**。`PassiveRecall.wait_context_ready` 只等待完成，timeout/overloaded/unavailable 等状态只写 debug 日志。本轮未补测试 |
| KD-7 | ToolPolicy 的默认审批策略与部分示例文档不一致。**未授权修改默认行为**；需要另行审查工具权限模型、执行授权和用户确认策略，不能损害合理的自主执行能力 | 独立审查 | 2A-1 记录为"`ToolPolicy.approval_required` 默认为 False，与示例 YAML 注释矛盾"（原归属 Tools 批次）；2A-2a 按审计改为独立审查；**T-1 复核：未变**（loop `config.py` 中默认仍为 False） |
| KD-8 | Health 服务默认暴露在网络上（绑定 `0.0.0.0`），`/status` 没有鉴权 | Host 批次 | 2A-1 记录；**T-1 复核：未变**（`HealthConfig.bind` 默认 `0.0.0.0`，`/status` 无鉴权） |
| ~~KD-9~~ | ~~`host/diagnostics.py` 无引用、与 Core diagnostics 重复、与计划中的 `host/diagnostics/` 包同名冲突~~ | 已关闭 | 2A-1 记录；**2A-C1 删除文件后解决** |
| KD-10 | **待修复（数据完整性，高优先级）**。临时身份 B 解析为稳定身份 A 的链路有四类风险：① **文件丢失**：会话关闭时 `flush_user_path_migrations(remove_old=True)` 先做不覆盖合并，再 `rmtree` 旧目录，两边同名的文件中旧目录那份被删除；连续解析 B→A→C 会删除稳定用户 A 的目录；② **Memory 归属**：上下文 Owner 只在消费 Turn 或输出记录时才同步，已持久化的 B 记录从不更新 Owner，A 之后检索不到；③ **Persona 合并**：A 已有 Details 时整体丢弃 B 的 Details；身份解析前提交、解析后才消费的 Turn 被 Profiler 丢弃；④ **重复或错误的身份解析**：已稳定的身份可被再次重绑定；`load_profile` 不区分证据来自哪个 Participant，缺少可比较向量时直接视为匹配；未注册 Participant 的声纹和人脸会写入主 Participant | KD10-1…KD10-5，逐批授权 | 2A-2b 审计记为候选；2026-10-27 独立审计确认，并用合成数据离线复现，标为待修复；2A-2b-1 暂缓；**T-1 复核：主体已修复，剩余两点未覆盖**。① 关闭时的 flush/merge/rmtree 已全部删除（源码无引用），改绑不做磁盘 I/O；② 按已接受的设计，历史持久记录的 Owner 不重写（`test_memory_batches_never_reassign_earlier_turns_to_a_corrected_user`），纠正后 A 能否检索 B 的旧记录属于延期的多人历史政策；③ Persona 改为按 Participant 缓存，字段级合并（`merge_profile_items`），来源优先级和乱序增量有回归，但"解析前提交、解析后消费的 Turn"是否被 Profiler 丢弃，本轮没有单独覆盖；④ 身份可纠正是已接受的设计（被动 B→A、主动 A→C，Agent 改绑走 CAS），`load_profile` 按 Participant 加载并在每次 await 后重查身份，Speaker/Face 证据按 Participant 隔离，旧 source generation 的迟到结果不能绑定身份（`test_persona_sensors.py`、`test_participant_identity.py`、`test_session_identity.py`） |
| ~~KD-11~~ | ~~任一 Runner 处于故障状态时，`InferenceRuntime._accept_client` 因 `not self.is_alive`（要求全部 Runner 存活）直接 abort 所有**新**连接。Executor 按 method 懒连接，所以会话在故障窗口内首次使用另一个健康 method 时，收到裸 `ConnectionResetError`，而不是 "temporarily unavailable"。已建立的连接不受影响。与"不同 method 独立推进"不一致；对真实模型 Runner，故障窗口可能持续数秒~~ | 已关闭 | T-1 新增并保留失败复现；review 补充：`do_inference()` 同样受影响，健康连接取消后重连也会被拒；**T-2 修复**：服务准入（`_serving`）与目标 Runner 健康分开判断，总体 `is_alive` 保留给 Host 监测和恢复。回归：`test_inference_runtime.py::test_failed_method_does_not_refuse_first_use_of_a_healthy_method`（已扩展） |
| ~~KD-12~~ | ~~Engine 先 `revoke_run` 再 `interrupt`，若两步之间下一句 TTS 首帧到达：`SegmentPreparer.prepare` 因 output 不再 active 抛 CancelledError，`SpeechStreamer.run` 在 `job.cancelled` 仍为 False 时把它当成"准备阶段自己取消"，转成 `RuntimeError("TTS preparation cancelled itself")`。结果 AUDIO_COMPLETE 的 reason 是 `speech_synthesis_failed`，并记 ERROR 日志；帧循环对同一条件判为 `synthesis_interrupted`，两条路径不一致。PCM 已正确停止，收尾事实都完成~~ | 已关闭 | T-1 新增并保留失败复现（低严重度）；**T-2 修复**：准备阶段的取消在 output 已失效时按打断处理，output 仍有效时保持 Provider 自取消的错误边界。回归：`test_speech_synthesis.py::test_revoked_answer_awaiting_tts_first_audio_is_interrupted_not_failed`、`test_provider_self_cancellation_on_an_active_output_remains_a_failure` |
| ~~KD-13~~ | ~~打断时 partial alignment 漏计已交付的音频：`SpeechStreamer` 只在 `publish()` 完整返回后累计 samples；帧已被一个消费者取走、另一个消费者仍在反压中时，打断让该调用返回 `None`，这一帧不计入最终 alignment（消费端收到 2 帧 0.020 s，alignment 只有 0.010 s）~~ | 已关闭 | T-1 记为未复现的观察；review 做成确定性复现；**T-2 修复**：按 Output 的接纳序号判断，帧一旦被接纳（与 AUDIO_COMPLETE barrier 覆盖范围一致）即计入，未被接纳的帧不计。回归：`test_speech_synthesis.py::test_interrupted_alignment_covers_audio_already_delivered_to_a_consumer` |
| O-1 | 初始化期间取消 Runner，要先等满 `close_timeout`（默认 5 s）才发 SIGTERM；测试中以 0.5 s 观测到 | 仅记录 | 2A-1 记录；**T-1 复核：仍存在**。实测 `close_timeout=0.5` 时为 0.50 s，`2.0` 时为 2.00 s |
| O-2 | 导入 `alphaavatar.agents.configs` 会立即加载全部插件和 torch、cv2、weasyprint、openai 等（约 1.7 s）；导入期间第三方库会改写 `LD_LIBRARY_PATH`、`QT_QPA_*`、`OPENBLAS_MAIN_FREE` 等变量 | 仅记录 | 2A-2a 新增；**T-1 复核：部分改善**。干净解释器中约 0.92 s，不再导入 torch；仍加载 cv2、weasyprint、openai、numpy 和 memory/persona/router/voice 插件；仍改写 `LD_LIBRARY_PATH`、`QT_QPA_FONTDIR`、`QT_QPA_PLATFORM_PLUGIN_PATH` |
| ~~O-3~~ | ~~`InferenceRuntime` 把 socket 建在 `tempfile` 目录下（`alphaavatar-inference-*/runtime.sock`），TMPDIR 较长时超过 AF_UNIX 路径上限（约 104–108 字节），启动时报 OSError，没有预检~~ | 已关闭 | T-1 新增；review 改判为启动兼容性缺陷；**T-2 修复**：新增 `alphaavatar.core.ipc.private_socket_path`，Inference 与 Host 日志的 socket 优先放在配置的临时目录，超过 100 字节时回退到 `/tmp` 下新建的私有（0700）目录，都不满足时给出明确的 ENAMETOOLONG。回归：`avatar-host/tests/test_local_endpoints.py` |
| O-4 | Speaker/Face 的 `_inference_loop` 依赖在途任务抛出取消。若被等待的调用吞掉取消并正常返回，循环自身的取消会丢失，`_stop()` 会挂住。真实 InferenceExecutor 会传播取消，`_process` 也会重新抛出，所以正常生产路径不受影响；Profiler 有 `cancelling()` 防护，这两个循环没有 | 仅记录（未确认风险） | T-1 新增；只能用吞掉取消的替身复现，且会挂死，所以没有提交失败用例 |
| ~~O-5~~ | ~~ENV Memory 批次附带的对话上下文只取最后 `max_context_messages`（64）条、`max_context_chars`（8192）字符~~ | 已关闭（设计如此） | T-1 新增，交维护者判断；**review 结论：不需修改**。这是 ENV 的有限辅助 prompt；完整的 Conversation/Tool 输入和原始 Turn 都没有被裁剪 |
| O-6 | `agents/utils/vdb/lancedb.py` 使用已弃用的 `table_names()`，测试中出现 DeprecationWarning（全量 28 条） | 仅记录 | T-1 新增 |
| O-7 | `MCPConfig` 未设置 `hide_input_in_errors`，ValidationError 文本可能带出部分原始 `servers` 输入（可能含明文 secret）。CLI 当前只输出字段名 | 仅记录 | T-1 新增 |
| ~~O-8~~ | ~~VAD 积压超过 `max_buffer_sec`（2 s）时最旧的帧被淘汰，语音开头丢失且没有 trace 记录；看起来是有界内存的有意取舍~~ | 升级为 KD-14 | T-2 新增（语音上游测试中观察到，未断言）；review 确定性复现后升级为生产缺陷 |
| ~~KD-14~~ | ~~VAD 积压超过 2 s 缓存时，迟到的 VAD 起点所在的语音正文已被淘汰，`_start_segment` 不检查，剩余部分仍作为正常 `SPEECH_SEGMENT` 发布，没有缺口或取消记录（review 复现：积压 2.4 s 时，32 帧 0.32 s 的发声只剩 8 帧 0.08 s）~~ | 已关闭 | 原 O-8；**T-3 修复（不完整）**：保留 2 s 缓存上限；起点早于最早保留样本时，记录 `audio.speech_lost`（`reason=vad_backlog_overflow`，`missing_count` 为丢失样本数），以 `INPUT_GAP` 发布 `SPEECH_CANCELLED`，不路由剩余帧，并换一条已追上进度的新 VAD 流；只丢 pre-roll 时照常发布。回归：`test_audio_activity.py::test_speech_evicted_by_the_backlog_bound_is_cancelled_and_recovered`；review（`dca356f`）：换流后用户不停顿继续说话，新流把原句尾部当作新的一句，经 STT/TurnTaking 产生正常 COMMIT，KD-14 重开；**T-4 修复**：连续性缺口（`INPUT_GAP`、`VAD_INPUT_REJECTED`、感知流缺口）之后新建的 VAD 流，要先观察到 VAD 自身的结束静音（`min_silence_duration`）或一次 END_OF_SPEECH，才接纳语音开始；此前的 START 视为原句延续，不路由，记 `audio.speech_skipped`（`reason=unconfirmed_boundary`）。回归：`test_audio_activity.py::test_speech_continuing_through_a_gap_is_not_admitted_as_a_new_utterance`；范围说明：`INPUT_GAP` 会退役整个旧 speech epoch（该 speech source generation），其中尚未完成识别、尚未提交的前段也一并退役；已提交的 Turn 不变 |
| ~~KD-15~~ | ~~`HostLog` 在 `try` 之外创建接收 socket，创建失败（例如沙盒 EPERM）时，之前建立的私有目录不会被清理（既存缺口，review 环境实际触发）~~ | 已关闭 | **T-3 修复**：socket 创建移入 `try`，失败时关闭已创建的 socket、删除目录、恢复 endpoint。回归：`test_local_endpoints.py::test_host_log_construction_failure_releases_its_directory` |

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
