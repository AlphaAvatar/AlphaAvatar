# 发布前持续稳定性验证与安装验收材料 — Claude Code 日志

- 分支：`dev/v0.6.9`，基线 `fbef4a3a`；日期为 CST，2026-11-23。
- 依据：用户的任务：
  - 补长时间运行、取消、队列积压和多路语音输入的证据；
  - 准备安装验收材料。用户已完成实际通话验收，结果正常。
- 范围：
  - 复用现有的 pytest 入口，`alphaavatar test` 留待后续；
  - 不改版本号，不提交，不合并 main，不发布 release；
  - 保持 Memory、Persona、VAD 300 ms、寻址和安装行为不变。
- 环境：
  - 本机 16 核、31 GB 内存，Linux x86_64，bash 4.4，Python 3.13.13；
  - 全部用 `PYTHONDONTWRITEBYTECODE=1 ALPHAAVATAR_MODEL_OFFLINE=1 uv run --no-sync pytest -p no:cacheprovider`；
  - 资源采样脚本和临时文件放在仓库外。

## 0. 证据分类

| 类别 | 内容 | 来源 |
|---|---|---|
| 普通通话验收 | 真实设备、真实模型和服务下的对话 | 用户 2026-11-23 的验收，结果正常；KD-49 的真实通话核对见 [Memory 修复日志](../2026-11-21/claude-code-memory-fix-zh.md) 11.6 节。本批没有再跑通话 |
| 专项故障注入 | 杀进程、取消、超时、容量拒绝、缺口、迟到结果、信号 | 第 2、3 节，离线确定性测试 |
| 合成压力 | 模型无关的 Runner 和替身，按时长循环 | 第 1 节，只代表合成负载，不代表设备或生产性能 |
| 安装包验证 | CI 构建、校验值、隔离环境里的安装冒烟 | 第 4 节；完整安装和真实 setup 由用户验收 |

真实模型的结果：本批没有运行真实模型或远程服务，大样本也没有发布（`large_samples.json` 的 `published` 为 false），这类测试无法运行。真实模型的数据来自用户的通话验收，以及此前的真实 Doctor（[诊断日志](../2026-11-20/claude-code-diagnosis-zh.md) 9.3 节、第 10 节）。KD-19 仍按已接受的 STT 模型限制处理。

## 1. 合成压力

`--stress-seconds` 对每个被选中的用例分别生效。每一阶段单独运行 pytest，并明确列出用例。预估合计约 55 分钟，实际从 02:28 跑到 03:24，之后又复跑了 9 分钟。

### 1.1 核心并发，30 分钟

- 用例：`test_stress.py::test_concurrent_sessions_and_methods_never_lose_duplicate_or_misroute_results`，参数 `--stress-seconds 1800`。
- 配置：
  - 4 个会话，各有一个 `InferenceExecutor` 连接；
  - 3 个 method（`test.echo`、`test.journal`、`test.journal.second`），每个 method 一个 Runner 进程，以 spawn 方式启动；
  - 每轮每个会话、每个 method 串行发 8 个请求，各会话、各 method 之间并发；
  - 各类超时 60 秒。

| 项 | 结果 |
|---|---|
| 时长 | 1811.5 s（02:28:31–02:58:43） |
| 完成量 | 187,840 轮，18,032,640 个请求，每个 method 6,010,880 个；约 9,960 req/s |
| 错配、丢失、重复 | 0；两个 journal method 都恰好执行一次，各在一个进程里 |
| 错误、拒绝、超时 | 0 |
| 每个 method 同时在途的峰值 | 4（等于会话数） |
| 延迟 | p50 1.19 ms，最大 11.77 ms |

资源每 15 秒采样一次，共 121 次，覆盖整个进程树：

| 项 | 第 150 s → 第 1800 s |
|---|---|
| 进程数 | 8 → 8 |
| Runner 进程 RSS | 14／37／40／40 MB → 14／38／41／41 MB |
| Runner 进程 fd | 5／9／9／9 → 不变 |
| 主进程 fd、线程 | 44、2 → 不变 |
| 主进程 RSS | 124 MB → 760 MB，线性增长，约 0.39 MB/s |
| 测试写的 journal | 0 → 420 MB（测试自己的记录） |

- 主进程 RSS 增长的归因：同一用例另跑 90 秒，用 tracemalloc 比较第 20 秒和第 80 秒：
  - Python 层 60 秒内共增长 1.7 MB，其中 1.48 MB 是测试自己的延迟列表（`test_stress.py:108`）；
  - 推理运行时的代码净增长约为 0。
- 30 分钟里这个列表累积了 1,800 万项，与 RSS 的增长相符。
- 结束后：没有残留的 Runner 进程；`/tmp/aa-*` 下没有比本次开始更新的 socket 目录。现有的 22 个都在 2026-11-06～11-14 之间，不是本批产生的，没有动。

### 1.2 故障恢复、重复启停、队列积压

| 用例 | 时长 | 结果 |
|---|---|---|
| `test_runner_failure_churn_recovers_without_replaying_attempted_work` | 180 s；复跑 120 s | 杀进程 1,169 次，恢复 1,169 次，恢复耗时 p50 149.6 ms、最大 154.4 ms；复跑 776／776 次，p50 150.4 ms、最大 153.3 ms。每次被杀时在途的那个请求按预期失败，没有重放；健康的 method 不受影响 |
| `test_repeated_runtime_start_stop_reclaims_processes_descriptors_and_socket` | 180 s；复跑 120 s | 536 次启停，每次 p50 335.6 ms、最大 343.9 ms；复跑 359 次。每次之后都断言子进程、fd、socket 目录和环境变量全部回收 |
| `test_parallel_workers_…_under_session_load[1]` | 120 s | 4 个会话每轮同时发 32 个请求，每个执行 5 ms，排给 1 个 worker：23,296 个请求，194 req/s；延迟 p50 85.8 ms、最大 166 ms；排队估计 p50 80.8 ms；同时执行的峰值为 1；拒绝、超时、错误、错配、泄漏的子进程和 fd 都是 0 |
| `…[2]` | 120 s | 46,336 个请求，386 req/s；延迟 p50 44.9 ms、最大 84.3 ms；排队估计 p50 39.8 ms；峰值 2，用了 2 个进程；其余同上，都是 0 |

- 积压的恢复：每一轮都在 worker 数量的上限内排空，下一轮从零开始。两次运行中，延迟最大值稳定在 166 ms 和 84 ms，没有持续增长。
- 复跑时每 5 秒采样一次：
  - 故障恢复：fd 保持 21，子进程 3 个，RSS 在 115 秒内增长 3.2 MB。用 tracemalloc 查明，这是 pytest 的日志捕获保留的 LogRecord，每次恢复两条。关掉捕获（`-p no:logging`）后，约 490 次恢复只增长 0.3 MB，主要是测试自己的列表；运行时代码约 0.02 MB，属于采样时仍在途的对象。
  - 重复启停：fd 和子进程数随启停所处的阶段在两个值之间变化；RSS 增长 0.8 MB。
  - 2 个 worker：fd 36，子进程 4 个；RSS 增长 1.9 MB，就是测试的 46k 项延迟列表。
- 第一次运行这几项时，采样脚本写错了：`( … & )` 里的 `$BASHPID` 让采样器只采到了它自己。所以资源数据以复跑为准，第一次运行只用它的测试结果。

### 1.3 其他 stress 用例，各 60 秒

| 用例 | 结果 |
|---|---|
| `avatar-core` `test_back_to_back_short_outputs_keep_pcm_barriers_and_retention_exact` | 95,624 轮，286,870 帧，字幕 286,870 条 |
| Memory `test_sustained_turns_and_records_are_all_extracted_once_at_close` | 1,276 轮，510,400 条输入，关闭时全部恰好提取一次 |
| Router `test_back_to_back_answers_keep_pcm_and_alignment_under_slow_presentation[speech0]` | 4,000 个回答，27,977 个短句，55,980 帧，66.7 个回答/s |

### 1.4 发现：worker 池压力用例的后处理是平方复杂度（KD-57，已修）

- 现象：`[1]` 设置 120 秒，实际 180 秒；`[2]` 实际 372 秒。从采样看，负载在 125 秒左右就停了，剩下的时间都花在测试自己的后处理上。
- 原因：`waits = sorted(latency - statistics.median(executions) for latency in latencies)` 对每个延迟都重新求一次中位数。
- 修复：只改测试，中位数只求一次。复跑 120 秒：两组都在 120 秒结束，结果与修复前相同。
- 默认的单轮运行：`test_stress.py` 5 passed。

## 2. 专项故障注入（各运行一次）

73 个用例全部通过，耗时 21 s：

- 推理（`test_runtime.py`、`test_process.py`、`test_parallel.py`、`test_launch.py`）：
  - 容量满时拒绝，不影响已接受的请求；
  - 队列和执行超时：撤回，或退役对应进程，不重放；
  - 已分派的请求超时后退役进程；
  - 取消排队中的请求，或取消初始化：撤回，不损坏 Runner；
  - 客户端取消时释放通道，不收到过期结果；
  - 杀掉 worker：回收并重建，同组的另一个 worker 继续服务；没有 worker 时，等待中的请求立即失败；
  - 一个 method 失败不影响另一个 method 首次使用；
  - 启动只成功一部分、关闭失败、恢复过程中关闭：都回收全部进程和 socket；
  - 重复启停；关闭可重复调用；多路语音来源各自保持状态、结果和取消。
- 输出与生命周期：
  - `avatar-core` 的 output runtime、output stream 和 lifecycle；
  - `avatar-agents` 的 runtime lifecycle；
  - Host 的 lifecycle、本地 socket 和 Health。
- 唯一的警告来自 `test_launch.py` 里 LanceDB 的 `table_names()` 弃用，已由 O-6 跟踪。

## 3. 语音输入与关联

- 18 个文件，323 个用例，连续 5 轮全部通过，共执行 1,615 次，每轮 68.6～71.7 s，没有时好时坏的用例。
- 覆盖的文件：
  - Router：audio activity、speech transcription、turn taking、smart turn、semantic addressing；
  - Voice：OpenAI segment STT；
  - Host：turn admission、transcript deadline、turn participants；
  - Agents：participant segments、participant identity；
  - Core：perception stream、input trace、session identity；
  - Persona：sensors、runtime；
  - Context：turn history；
  - Memory：memory runtime。

| 关注点 | 用例 |
|---|---|
| 普通语音；input／segment／STT 终稿／Turn cutoff 的关联证据 | `test_stt_final_joins_segment_input_decision_and_turn_cutoff_evidence`；`test_each_wait_between_a_transcript_and_its_turns_decision_is_traced_as_a_span` |
| 自然停顿、跨段累计 | `test_a_held_input_goes_on_across_its_segments`、`test_words_later_than_an_uncertain_completions_wait_commit_it_unheld`、`test_speech_joining_a_waiting_input_keeps_its_own_transcript_budget`、`test_a_held_turn_keeps_the_words_it_has_and_marks_the_segment_it_lost` |
| 迟到终稿不污染后续轮次 | `test_late_stt_final_after_transcript_timeout_never_revives_the_input`、`test_after_the_deadline_the_source_speaks_again_and_the_late_final_stays_its_own`、`test_a_transcript_past_its_deadline_commits_the_notice_and_its_late_final_joins_nothing`、`test_recognition_after_its_segment_retired_is_stale_on_a_live_stream`、`test_a_sealed_input_retired_by_its_source_or_a_bound_takes_no_late_words` |
| 取消 | `test_cancelled_speech_epoch_cancels_its_input_and_ignores_later_frames`、`test_an_assessment_answering_after_its_cancellation_decides_nothing`、`test_a_hold_its_speaker_ends_by_speaking_on_is_traced_as_cancelled`、`test_a_stale_decision_is_ignored_and_closes_its_input` |
| 缺口、积压 | audio activity 的 7 个缺口用例；`test_slow_consumer_never_blocks_publisher_and_sees_an_explicit_gap`；`test_speech_evicted_by_the_backlog_bound_is_cancelled_and_recovered`；Persona 缺口和容量淘汰（KD-53） |
| 归属有界、正确 | `test_past_the_bound_an_association_is_released`、`test_a_turns_participants_are_read_from_its_inputs_whenever_asked`、`test_an_acknowledgement_retires_only_the_input_it_owns`、`test_a_committed_input_is_never_admitted_again`，以及 Persona 和 Memory 对 owner 的断言 |

## 4. 安装包验证

候选 SHA 为 `fbef4a3a29c7c1693c9ec2a5c185f43a9b9945a4`。

| 项 | 内容 |
|---|---|
| Quality | [run 45053394345](https://github.com/AlphaAvatar/AlphaAvatar/actions/runs/45053394345)：success |
| Linux package | [run 45053394322](https://github.com/AlphaAvatar/AlphaAvatar/actions/runs/45053394322)：success。在 manylinux_2_28 里构建，再在干净的 ubuntu:24.04 上按 DEPLOY 安装，并运行 `setup reference --artifacts` |
| Artifact | [`alphaavatar-linux-x86_64-fbef4a3a…`](https://github.com/AlphaAvatar/AlphaAvatar/actions/runs/45053394322/artifacts/14766314214)（id 14766314214，85.1 MB，保留到 2026-12-22） |
| Build ID | `0.6.8-fbef4a3a29c7`（版本未改）；manifest 中 `release` 为 null，Python 3.13.12，uv 0.10.0，uv.lock sha256 `6e2c34f7…` |
| 基础包 | `alphaavatar-0.6.8-fbef4a3a29c7-linux-x86_64.tar.gz`，sha256 `4139e32f79fba91d51344e25aceba15920d1c84d3ee96e4b19cec541c8bd623f` |
| `install.sh` | sha256 `47a5b5420a894c06542ab34f1ab60acbe23bc2e137fc903e4e7abf6af7ac0fc4`，与该提交里的文件逐字节相同 |
| manifest | sha256 `fbcac888cfadb617de7452f54730d1fcd69000fb5d8b978a55017e3eecf8f6cd` |
| wheels | 本构建自带 12 个，与基础包 catalog 记录的 sha256 一一对应；catalog 里另有 121 个第三方分发，带固定的 sha256，setup 时从各自的索引下载 |
| `SHA256SUMS` | 15 项，本地 `sha256sum -c` 全部 OK |
| 升级用的上一构建 | `fa022e9d`：[run 45042934752](https://github.com/AlphaAvatar/AlphaAvatar/actions/runs/45042934752)，[artifact 14762422473](https://github.com/AlphaAvatar/AlphaAvatar/actions/runs/45042934752/artifacts/14762422473)；build `0.6.8-fa022e9d5628`；包 sha256 `f03d84c7564e55a6c4444171747412a4a4b4b9d2c7e93a4e9fa251e1bf6e4b85`；`SHA256SUMS` 15 项全部 OK |

本地冒烟在隔离的 `HOME` 里进行，没有碰本机已有的安装：

- `install.sh --non-interactive --file …`：退出 0，PATH 写入 `.bashrc` 和 `.profile`；
- `alphaavatar --version` 输出 `AlphaAvatar 0.6.8`；`config init reference` 正常；
- `setup reference --plan --artifacts <构建目录>`：105 个包；
- `upgrade --check --file <fa022e9d 的包>`：可以升级到 `0.6.8-fa022e9d5628`；
- `cleanup --dry-run`：没有可删除的。

本地没有运行完整的 setup，也就是没有下载模型和 wheel。CI 的 verify 任务完成过 `setup reference --artifacts`。

发现（O-33，未改，待用户决定）：

- 安装器在终端里接着提供的 setup 不带 `--artifacts`。对 CI 构建，这一步会在问完全部问题、下载前 5 个包之后失败，报"not published; pass --artifacts"；安装本身保留。正式 release 不受影响。
- 验收时对安装器的询问回答 `n`，再自己运行 `setup --artifacts`。
- 如果要修，改 `install.sh` 就会换成新的候选 SHA。

## 5. 验收步骤（供用户执行）

假设两个构建分别放在 `~/aa/fbef` 和 `~/aa/fa02`。下载：`gh run download <run> -R AlphaAvatar/AlphaAvatar -n <artifact 名> -D <目录>`，或者从上面的链接下载后解压。

1. 校验：`cd ~/aa/fbef && sha256sum -c SHA256SUMS`。
2. 干净安装：`bash ~/aa/fbef/install.sh --file ~/aa/fbef/alphaavatar-0.6.8-fbef4a3a29c7-linux-x86_64.tar.gz`。询问是否运行 setup 时回答 `n`（O-33）。
3. 新开一个终端，检查 PATH：`command -v alphaavatar`、`alphaavatar --version`。
4. 真实交互 setup：`alphaavatar setup --artifacts ~/aa/fbef`。
5. `alphaavatar doctor`。
6. `alphaavatar start`，之后按 Ctrl+C 或发送 SIGTERM 正常停止，退出码为 0。
7. 升级成功（先停 Host）：
   - `alphaavatar upgrade --check --file ~/aa/fa02/alphaavatar-0.6.8-fa022e9d5628-linux-x86_64.tar.gz`；
   - `alphaavatar upgrade --file` 同一个包，wheel 从它旁边取；
   - 再 `alphaavatar upgrade --file ~/aa/fbef/alphaavatar-0.6.8-fbef4a3a29c7-linux-x86_64.tar.gz`，回到候选构建。
8. 准备失败时保留原环境：
   - `mkdir ~/aa/bare && cp ~/aa/fa02/alphaavatar-0.6.8-fa022e9d5628-linux-x86_64.tar.gz{,.sha256} ~/aa/bare/`；
   - `alphaavatar upgrade --file ~/aa/bare/alphaavatar-0.6.8-fa022e9d5628-linux-x86_64.tar.gz`：旁边没有本构建的 wheel，安装阶段失败，退出码 1，提示 "stays current"；
   - 或者给一个错误的 `--sha256`，在 Package 阶段就失败；
   - 之后 `readlink ~/.local/lib/alphaavatar/current`、`alphaavatar --version` 都不变，`alphaavatar doctor` 照常。
9. cleanup 预览和数据保护：
   - `alphaavatar cleanup --dry-run`，列出 `current` 没在用的环境和基础包，以及保留的项和原因；
   - 停掉 Host 后运行 `alphaavatar cleanup`；
   - 前后对比应用目录（默认 `~/.local/share/alphaavatar`）的文件清单和校验值，应完全不变。
10. 实际通话沿用已通过的验收结果。

## 6. 本批的改动与验证

- 代码：`avatar-agents/tests/runtime/inference/test_stress.py`（KD-57，只改测试）。生产代码没有改动。
- 文档：`docs/bugs-zh.md` 新增 KD-57 和 O-33；新增本日志。
- 离线全量：993 passed，47 warnings，352 s。运行前后未跟踪和被忽略的文件一致，只多了运行期间新建的本日志。
- 仓库规范：都通过。
  - `uv lock --check`、`check_workspace.py`（16 个成员）；
  - `ruff check .`、`ruff format --check .`（793 个文件）；
  - `git diff --check`；
  - 对改动文件跑 pre-commit：全部通过，没有改动任何文件。

## 7. 未验证的边界

- 完整安装、真实交互 setup、Doctor、启停、升级和 cleanup 的实际执行，由用户验收。本地只做了第 4 节的冒烟。
- 合成压力用的是模型无关的 Runner 和替身，不代表真实模型的延迟或吞吐，也不代表设备上的表现。
- 本机只有 bash 4.4；KD-56 的新测试在较新 bash 上的结果，以 CI 为准。
