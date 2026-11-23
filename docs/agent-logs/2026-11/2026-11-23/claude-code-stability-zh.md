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

资源每 15 秒采样一次，共 121 次，覆盖整个进程树。表中的身份按采样记录的 PID 和命令行核对：

| 进程（PID） | 身份 | 第 150 s → 第 1800 s |
|---|---|---|
| 3803371 | 采样所挂的 shell（`bash -c`） | 3 MB、4 fd，不变 |
| 3803379、3803380 | `timeout` 和 `uv run` | 0 MB、3 fd；37 MB、11 fd，不变 |
| 3803388 | pytest 主进程，推理运行时就在其中 | RSS 124 MB → 760 MB，线性增长，约 0.39 MB/s；fd 44、线程 2，不变 |
| 3803395 | `multiprocessing.resource_tracker`，辅助进程，不是 Runner | 14 MB、5 fd，不变 |
| 3803396、3803397、3803398 | 3 个 Runner（`multiprocessing.spawn` 的 `spawn_main`），每个 method 一个 | 37／40／40 MB → 38／41／41 MB；各 9 fd，不变 |
| — | 测试写的 journal | 0 → 420 MB（测试自己的记录） |

- 共 8 个进程，从第 15 秒到结束一直是这 8 个 PID，没有新增或替换。
- 3 个 Runner 各对应哪个 method，无法从采样确认：命令行在 90 个字符处截断，3 个都是 `spawn_main`；测试的 journal 文件里有进程号，但运行结束后已随临时目录删除。
- 此前把 resource tracker 也算作 Runner，写成了"4 个 Runner"，这里已更正。

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
- 复跑时每 5 秒采样一次。下面的"子进程"按命令行核对，都包含 1 个 resource tracker：
  - 故障恢复：fd 保持 21，子进程 3 个，即 2 个 Runner（journal、echo）和 resource tracker；被杀的 Runner 由新进程替换，采样时数量不变。RSS 在 115 秒内增长 3.2 MB。用 tracemalloc 查明，这是 pytest 的日志捕获保留的 LogRecord，每次恢复两条。关掉捕获（`-p no:logging`）后，约 490 次恢复只增长 0.3 MB，主要是测试自己的列表；运行时代码约 0.02 MB，属于采样时仍在途的对象。
  - 重复启停：fd 和子进程数随启停所处的阶段变化。25 次采样中，13 次是 2 个 Runner 加 tracker，10 次是 1 个 Runner 加 tracker，其余两次在启动前后。RSS 增长 0.8 MB。
  - 2 个 worker：fd 36，子进程 4 个，即 echo Runner、2 个 parallel worker 和 tracker；RSS 增长 1.9 MB，就是测试的 46k 项延迟列表。
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

O-33：未发布 CI 包的使用限制（用户 2026-11-23 决定保留，不改）：

- 安装器在终端里接着提供的 setup 不带 `--artifacts`。对 CI 构建，这一步会在问完全部问题、下载前 5 个包之后失败，报"not published; pass --artifacts"；安装本身保留。正式 release 不受影响。
- 安装 CI 构建时，对安装器的询问回答 `n`，再运行 `alphaavatar setup --artifacts <产物目录>`。

## 5. 最终安装验收步骤（供用户执行）

### 5.1 依据

- **判断实际构建：** 两个包的 `--version` 都只显示 `0.6.8`，不能用来区分构建。
  - `current` 指向 `envs/<plan>` 时，看该环境 `share/alphaavatar/plan.json` 的 `base`；
  - `current` 指向 `versions/<build>` 时，目录名就是 build ID，也可以看基础包 `share/alphaavatar/manifest.json` 的 `id`。
- **升级失败测试的顺序：**
  - 升级时，目标计划的环境如果已经存在且完整，`upgrade` 会直接复用（"installed already"），不再取 wheel（`upgrade.py`、`Installation.reusable`）；已经解压的同一个基础包也会复用。
  - 所以缺 wheel 的升级失败，必须在 `fa02` 的基础包和环境都还没安装时进行，也就是在任何一次 `fa02` 正常升级之前。
  - 两个构建自带的 12 个 wheel 内容都不同，setup 也没有自己的下载缓存，所以 `fbef` 的文件替代不了 `fa02` 的。
  - 失败的那次运行会删除它自己解压的 `fa02` 基础包和环境暂存。
- **错误的 SHA：** 只验证包校验，在 Package 阶段、解压之前就失败，不能替代环境准备失败的验收。

### 5.2 步骤

每个新终端里先定义：

```bash
P=~/.local/lib/alphaavatar
FBEF=~/aa/fbef/alphaavatar-0.6.8-fbef4a3a29c7-linux-x86_64.tar.gz
FA02=~/aa/fa02/alphaavatar-0.6.8-fa022e9d5628-linux-x86_64.tar.gz
build() {  # current points to, and the build it runs
  echo "current -> $(readlink "$P/current")"
  grep -h '"base"' "$P/current/share/alphaavatar/plan.json" 2>/dev/null \
    || grep -h '"id"' "$P/current/share/alphaavatar/manifest.json"
}
```

1. **下载并校验。** 前提是干净的 Linux x86_64 用户，没有 `~/.local/lib/alphaavatar` 和应用目录。

   ```bash
   mkdir -p ~/aa/fbef ~/aa/fa02
   gh run download 45053394322 -R AlphaAvatar/AlphaAvatar -n alphaavatar-linux-x86_64-fbef4a3a29c7c1693c9ec2a5c185f43a9b9945a4 -D ~/aa/fbef
   gh run download 45042934752 -R AlphaAvatar/AlphaAvatar -n alphaavatar-linux-x86_64-fa022e9d5628f13a8d02eb1b7c7e1bb57b9ee44c -D ~/aa/fa02
   (cd ~/aa/fbef && sha256sum -c SHA256SUMS) && (cd ~/aa/fa02 && sha256sum -c SHA256SUMS)
   ```

   预期：各 15 项 OK。从浏览器下载的是 zip，解压到对应目录即可。

2. **干净安装候选构建。**

   ```bash
   bash ~/aa/fbef/install.sh --file "$FBEF"
   ```

   - 预期输出 `Installed AlphaAvatar 0.6.8, build 0.6.8-fbef4a3a29c7`，以及 `PATH: added …` 两行（bash 写 `~/.bashrc` 和登录时读的文件）。
   - 询问 `Run alphaavatar setup now…? [Y/n]` 时回答 `n`（O-33），输出 `Setup: not run. Next: alphaavatar setup …`。
   - `build` 显示 `current -> versions/0.6.8-fbef4a3a29c7`。

3. **新终端里的 PATH。** 新开一个终端，先定义上面的变量，再运行：

   ```bash
   command -v alphaavatar       # ~/.local/bin/alphaavatar
   bash -lc 'command -v alphaavatar'   # 登录 shell 也能找到
   alphaavatar --version        # AlphaAvatar 0.6.8
   ```

4. **真实交互 setup。**

   ```bash
   alphaavatar setup --artifacts ~/aa/fbef
   ```

   按提示回答，以成功结束。`build` 显示 `current -> envs/<plan>` 和 `"base": "0.6.8-fbef4a3a29c7"`。把这个 `<plan>` 记作 `ENV_FBEF`。

5. **Doctor：** `alphaavatar doctor`。

6. **启动和正常停止：** `alphaavatar start`，按 Ctrl+C，或者在另一个终端发送 SIGTERM。`echo $?` 应为 0。

7. **环境准备失败，原环境保留。** 先停掉 Host。确认前提：`ls "$P/versions" "$P/envs"` 只有 `0.6.8-fbef4a3a29c7` 和 `ENV_FBEF`，`fa02` 从未装过。

   ```bash
   mkdir -p ~/aa/bare
   cp "$FA02" "$FA02.sha256" ~/aa/bare/
   alphaavatar upgrade --file ~/aa/bare/alphaavatar-0.6.8-fa022e9d5628-linux-x86_64.tar.gz; echo "exit=$?"
   ```

   - 预期：Package 一步通过 SHA-256 校验；Install 一步在第一个本构建自带的 wheel（`alpha_avatar_plugins_context`）处失败，因为包旁边没有它；`FAIL  Upgrade failed; AlphaAvatar 0.6.8-fbef4a3a29c7 stays current`，`exit=1`。
   - 之后检查：
     - `build` 仍是 `ENV_FBEF` 和 `0.6.8-fbef4a3a29c7`；
     - `ls -a "$P/versions" "$P/envs"` 只有原来的两项，没有 `0.6.8-fa022e9d5628`，也没有 `.install-*`、`.setup-*` 暂存；
     - `alphaavatar config check` 通过；可以再 `alphaavatar start`、Ctrl+C。

8. **包校验失败**（单独一项，不替代第 7 步）：

   ```bash
   alphaavatar upgrade --file "$FA02" --sha256 0000000000000000000000000000000000000000000000000000000000000000; echo "exit=$?"
   ```

   预期在 Package 阶段失败，`exit=1`，`build` 不变。

9. **正常升级到 `fa02`。**

   ```bash
   alphaavatar upgrade --check --file "$FA02"   # Upgradable to 0.6.8-fa022e9d5628, Current 0.6.8-fbef4a3a29c7
   alphaavatar upgrade --file "$FA02"; echo "exit=$?"
   ```

   - 预期 `Upgraded to AlphaAvatar 0.6.8-fa022e9d5628`，`Previous 0.6.8-fbef4a3a29c7`，`exit=0`。wheel 从包旁边的 `~/aa/fa02` 取。
   - `build` 显示新的 `envs/<plan>`（记作 `ENV_FA02`）和 `"base": "0.6.8-fa022e9d5628"`；`--version` 仍是 `0.6.8`。

10. **返回候选构建。**

    ```bash
    alphaavatar upgrade --file "$FBEF"; echo "exit=$?"
    ```

    预期 `Upgraded to AlphaAvatar 0.6.8-fbef4a3a29c7`，`exit=0`。计划与之前相同时，Plan 一步显示 "installed already"，复用 `ENV_FBEF`。`build` 显示 `"base": "0.6.8-fbef4a3a29c7"`。

11. **cleanup 预览和数据保护。** 先停掉所有 `alphaavatar start`、`dev`、`doctor`。应用目录默认是 `${XDG_DATA_HOME:-~/.local/share}/alphaavatar`；设置了 `ALPHAAVATAR_HOME` 时以它为准。

    ```bash
    H=~/.local/share/alphaavatar
    (cd "$H" && find . -type f -print0 | sort -z | xargs -0 sha256sum) > ~/aa/home-before.txt
    alphaavatar cleanup --dry-run
    alphaavatar cleanup; echo "exit=$?"
    (cd "$H" && find . -type f -print0 | sort -z | xargs -0 sha256sum) > ~/aa/home-after.txt
    diff ~/aa/home-before.txt ~/aa/home-after.txt && echo "application home unchanged"
    build; ls "$P/versions" "$P/envs"; alphaavatar config check
    ```

    - 预期：`--dry-run` 列出要删的 `envs/ENV_FA02` 和 `versions/0.6.8-fa022e9d5628`，保留 `ENV_FBEF`（current）和 `versions/0.6.8-fbef4a3a29c7`，并说明原因，不做任何改动。
    - `cleanup` 删除上述两项，`exit=0`；应用目录前后完全相同；`build` 仍是候选构建；`config check` 通过。

12. **实际通话：** 沿用已通过的验收结果。

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

## 8. 验收文档整理（基线 `ca8d5f52`）

- 依据：用户复查。这轮持续稳定性验证按约定的合成负载范围接受，KD-57 也已通过复查。
- 基线：`ca8d5f52` 相对 `fbef4a3a` 只改了 `test_stress.py` 和文档，生产代码不变，安装产物继续用 `fbef4a3a` 的构建。Linux package 的路径过滤不包括测试和文档，所以 `ca8d5f52` 没有新的安装包构建。
- 本轮只整理文档和证据，没有重跑压力测试或离线全量：
  - 5.1、5.2 改写验收步骤：
    - 缺 wheel 的 `fa02` 升级失败放到任何一次 `fa02` 正常升级之前，并写明前提和原因（环境复用）；
    - 错误的 SHA 单列为包校验失败；
    - 每一步用 `current`、`plan.json` 的 `base` 或 manifest 的 `id` 判断实际构建。
  - 1.1、1.2 按采样记录的 PID 和命令行，更正进程身份：
    - 30 分钟运行中是 3 个 Runner 加 1 个 resource tracker，不是 4 个 Runner；
    - 复跑表里的"子进程"也包含 tracker；
    - Runner 与 method 的对应关系无法确认，已如实注明。
  - O-33 按用户决定，作为未发布 CI 包的使用限制保留。
- CI：`ca8d5f52` 的 Quality（[run 45120681604](https://github.com/AlphaAvatar/AlphaAvatar/actions/runs/45120681604)）最终为 failure：
  - lint、build 都通过；
  - install 任务的 "Run deterministic offline tests" 一步，993 个用例全部通过，用时 600.81 s，随后超过这一步 10 分钟的上限，被判超时；
  - 同样 993 个用例，`fbef4a3a` 在 CI 上用了 429 s。更早几次是 504 s、534 s、578 s，这次最慢的几个用例也都变慢了，说明是 CI 机器速度的波动，不是某个用例的回归；
  - `ca8d5f52` 相对 `fbef4a3a` 只改了测试（KD-57，只会更快）和文档。
  - 登记为 O-34。没有改 workflow，也没有重跑 CI，由用户决定。候选构建 `fbef4a3a` 的 Quality 和 Linux package 都通过。
