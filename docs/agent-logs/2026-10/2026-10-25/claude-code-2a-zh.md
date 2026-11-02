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
| T-1 | 必要回归测试补全与 KD/O 复核（只改测试） | 2026-11-02 | `f708b26` | 未提交 | 待审查；收集 144 个，142 passed，2 个为保留的缺陷复现（KD-11、KD-12） |

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
| KD-11 | **新增（T-1，失败复现已保留）**。任一 Runner 处于故障状态时，`InferenceRuntime._accept_client` 因 `not self.is_alive`（要求全部 Runner 存活）直接 abort 所有**新**连接。Executor 按 method 懒连接，所以会话在故障窗口内首次使用另一个健康 method 时，收到裸 `ConnectionResetError`，而不是 "temporarily unavailable"。已建立的连接不受影响。与"不同 method 独立推进"不一致；对真实模型 Runner，故障窗口可能持续数秒 | 需单独授权（Inference） | 复现：`avatar-agents/tests/test_inference_runtime.py::test_failed_method_does_not_refuse_first_use_of_a_healthy_method` |
| KD-12 | **新增（T-1，失败复现已保留，低严重度）**。Engine 先 `revoke_run` 再 `interrupt`，若两步之间下一句 TTS 首帧到达：`SegmentPreparer.prepare` 因 output 不再 active 抛 CancelledError，`SpeechStreamer.run` 在 `job.cancelled` 仍为 False 时把它当成"准备阶段自己取消"，转成 `RuntimeError("TTS preparation cancelled itself")`。结果 AUDIO_COMPLETE 的 reason 是 `speech_synthesis_failed`，并记 ERROR 日志；帧循环对同一条件判为 `synthesis_interrupted`，两条路径不一致。PCM 已正确停止，收尾事实都完成 | Router/Speech 批次 | 复现：`avatar-plugins/perception/avatar-plugins-router/tests/test_speech_synthesis.py::test_revoked_answer_awaiting_tts_first_audio_is_interrupted_not_failed` |
| O-1 | 初始化期间取消 Runner，要先等满 `close_timeout`（默认 5 s）才发 SIGTERM；测试中以 0.5 s 观测到 | 仅记录 | 2A-1 记录；**T-1 复核：仍存在**。实测 `close_timeout=0.5` 时为 0.50 s，`2.0` 时为 2.00 s |
| O-2 | 导入 `alphaavatar.agents.configs` 会立即加载全部插件和 torch、cv2、weasyprint、openai 等（约 1.7 s）；导入期间第三方库会改写 `LD_LIBRARY_PATH`、`QT_QPA_*`、`OPENBLAS_MAIN_FREE` 等变量 | 仅记录 | 2A-2a 新增；**T-1 复核：部分改善**。干净解释器中约 0.92 s，不再导入 torch；仍加载 cv2、weasyprint、openai、numpy 和 memory/persona/router/voice 插件；仍改写 `LD_LIBRARY_PATH`、`QT_QPA_FONTDIR`、`QT_QPA_PLATFORM_PLUGIN_PATH` |
| O-3 | `InferenceRuntime` 把 socket 建在 `tempfile` 目录下（`alphaavatar-inference-*/runtime.sock`），TMPDIR 较长时超过 AF_UNIX 路径上限（约 104–108 字节），启动时报 OSError，没有预检 | 仅记录 | T-1 新增；测试改用根 conftest 的 `socket_root` 短路径 |
| O-4 | Speaker/Face 的 `_inference_loop` 依赖在途任务抛出取消。若被等待的调用吞掉取消并正常返回，循环自身的取消会丢失，`_stop()` 会挂住。真实 InferenceExecutor 会传播取消，`_process` 也会重新抛出，所以正常生产路径不受影响；Profiler 有 `cancelling()` 防护，这两个循环没有 | 仅记录（未确认风险） | T-1 新增；只能用吞掉取消的替身复现，且会挂死，所以没有提交失败用例 |
| O-5 | ENV Memory 批次附带的对话上下文只取最后 `max_context_messages`（64）条、`max_context_chars`（8192）字符。这是补充上下文，不是抽取输入；ENV 默认关闭，批次按事件数/时长有界 | 待维护者判断 | T-1 新增；conversation/tool 抽取已验证不截断。是否与"不截断文本"冲突，请维护者决定 |
| O-6 | `agents/utils/vdb/lancedb.py` 使用已弃用的 `table_names()`，测试中出现 DeprecationWarning（全量 28 条） | 仅记录 | T-1 新增 |
| O-7 | `MCPConfig` 未设置 `hide_input_in_errors`，ValidationError 文本可能带出部分原始 `servers` 输入（可能含明文 secret）。CLI 当前只输出字段名 | 仅记录 | T-1 新增 |

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
