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
| 2A-C1 | 删除未使用的 Host diagnostics | 2026-10-26 | `468c807` | 未提交 | 等待审计 |

## 已知缺陷（当前状态，只记录不修复）

| ID | 问题 | 归属 | 变更记录 |
|---|---|---|---|
| KD-1 | `AvatarConfig` 校验时创建 Workspace、写入 `AVATAR_WORK_DIR`/`AVATAR_TIMEZONE`；同一进程内重复校验会让 ID 重复追加（R3）；没有 base 时会写探测 `/var/lib/<id>` | 2A-2b / 2A-2d | 2A-1 记录；2A-2a 移除随机 UUID |
| KD-2 | Memory 和 Persona 配置在校验时写 `*_VDB_*` 环境变量（配置被拒绝时也写），并构造 QdrantClient。`check_compatibility=True` 会在构造时发出 HTTP 版本请求，Host 和执行子进程各执行一次，客户端从不关闭 | 需单独授权 | 2A-1 记录；2A-2a 补充 HTTP 版本请求与客户端未关闭 |
| KD-3 | Tools 配置把解析后的 secret 写入 `MCP_*` 环境变量 | 需单独授权 | 2A-1 记录 |
| KD-4 | Persona LanceDB 查询中 `user_id` 直接拼接、未转义，不安全 | Persona 批次 | 2A-1 记录 |
| KD-5 | Persona VDB 保存失败的错误没有被正确处理 | Persona 批次 | 2A-1 记录为"保存只检查结果是否为假值"；2A-2a 按审计统一表述 |
| KD-6 | Memory Passive Recall 的具体完成状态没有完整传播到 Turn-level diagnostics | Memory 诊断批次 | 2A-2a 按审计更正：原表述"检索出错返回 `[]`，与空结果无法区分"不准确，问题不在 MemoryStore |
| KD-7 | ToolPolicy 的默认审批策略与部分示例文档不一致。**未授权修改默认行为**；需要另行审查工具权限模型、执行授权和用户确认策略，不能损害合理的自主执行能力 | 独立审查 | 2A-1 记录为"`ToolPolicy.approval_required` 默认为 False，与示例 YAML 注释矛盾"（原归属 Tools 批次）；2A-2a 按审计改为独立审查 |
| KD-8 | Health 服务默认暴露在网络上（绑定 `0.0.0.0`），`/status` 没有鉴权 | Host 批次 | 2A-1 记录 |
| ~~KD-9~~ | ~~`host/diagnostics.py` 无引用、与 Core diagnostics 重复、与计划中的 `host/diagnostics/` 包同名冲突~~ | 已关闭 | 2A-1 记录；**2A-C1 删除文件后解决** |
| O-1 | 初始化期间取消 Runner，要先等满 `close_timeout`（默认 5 s）才发 SIGTERM；测试中以 0.5 s 观测到 | 仅记录 | 2A-1 记录 |
| O-2 | 导入 `alphaavatar.agents.configs` 会立即加载全部插件和 torch、cv2、weasyprint、openai 等（约 1.7 s）；导入期间第三方库会改写 `LD_LIBRARY_PATH`、`QT_QPA_*`、`OPENBLAS_MAIN_FREE` 等变量 | 仅记录 | 2A-2a 新增 |

已撤回：「recall 结果包含 avatar owner」按 Q8 属于有意设计，不再列为缺陷。

处理规则：修复批次先写失败用例，修复后转绿。如果基线测试意外失败，停止并报告，经批准后才标记 `xfail(strict=True, reason="KD-n …")`，不使用 skip，也不放宽断言。

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
