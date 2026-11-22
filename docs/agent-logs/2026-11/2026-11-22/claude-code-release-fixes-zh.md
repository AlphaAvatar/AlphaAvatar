# 发布前修复：来源关闭保留已完成的关联、安装后的 PATH 和首次 setup、下载失败的入口 — Claude Code 日志

- 分支：`dev/v0.6.9`，基线 `064222fb`；日期为 CST。
- 依据：
  - 用户 2026-11-22 转来的 review（基于 `064222fb`），三项发布前修复；
  - 用户随后的安装体验要求：README 不要求手动 export，也不展示绝对路径；撤销"不修改 shell 配置"的限制，由安装器自动配置 PATH，并接续首次 setup。
- 范围：
  - 保持不变：KD-49 已确认的规则、O-29～O-32 的延期决定、按类型加 owner 读取的规则、scope 现有的用途、VAD 300 ms 和寻址策略，以及安装器原有的保护（锁、暂存、信号、校验、来源规则）。
  - 本轮不改版本号，不打标签，不发布 release。
  - 改动留在工作区，由用户提交。

## 批次总览

| 批次 | 内容 | 日期 | 基线 HEAD | 提交 | 状态 |
|---|---|---|---|---|---|
| 发布前修复 | KD-50 来源关闭保留已完成的关联；KD-51 安装器为新终端配置 PATH，并在交互安装结束时接续首次 setup；KD-52 下载失败时管道的退出码 | 2026-11-22 | `064222fb` | `09845713` | 已提交 |
| 第二批 | KD-53 缺口和容量淘汰保留已完成的关联；KD-54 PATH 标记异常时不改文件；KD-55 bash 登录终端的 PATH；KD-56 询问 setup 时 Ctrl-C 可能卡住（范围外，验证中发现） | 2026-11-22 | `09845713` | `d9ccfd2b` | 已提交 |
| 第三批 | KD-56 收尾：Ctrl-C 先于等待到达的窗口；截断下载测试不再检查 bash 的措辞 | 2026-11-22 | `d9ccfd2b` | `fa022e9d` | 已提交 |
| 第四批 | KD-56：读取进程创建后、记录进程号前的 TERM、HUP | 2026-11-23 | `fa022e9d` | — | 待审查 |

## 1. KD-50：来源关闭不能作废此前已完成的语音关联（P1）

### 1.1 原因

- 一句话完成关联和身份识别后，它的段状态要留在处理器里，直到属性推理结束（`_identify` → `_enqueue_attribute` → `_describe` → `_retire`）。
- 这时来源关闭，`_cancel_source()` 会对这个来源仍在处理器里的每一段调用 `_invalidate()`，再 `_retire()`。
- `_invalidate()` 调用 `bind_segment(..., None)`，参与者 runtime 把这一段标为 `invalid`，已确认的关联也不例外，之后 `of_turn()` 读到的就是匿名。
- review 在 `064222fb` 上复现了这一点。新写的回归测试换回原版处理器（从仓库外加载）后，来源取消这种情况同样失败：关联是 `invalid`，不是 `bound`。

### 1.2 改动（`persona/processors/speaker/processor.py`）

- 新增 `_abandon(state)`：来源结束时停止这一段剩下的工作。
  - 关联已经是 `bound` 的段不再作废，只调用 `_retire()`：移出处理器，清掉缓冲，放行等待它的 Turn。
  - 其余的段照旧作废后再 `_retire()`。
- `_cancel_source()` 改用 `_abandon()`。之后照旧退役这个来源，并取消正在跑的身份和属性任务。
- 迟到结果仍被拒绝，依靠的是已有的两道检查，而不是作废关联：
  - 段状态已移出处理器，`_is_current()` 不再成立；
  - 来源已退役，`segment_is_current()` 也不成立。
  - 所以排队中或推理完的身份、属性结果，都会在 `_speaks_as()` 处被丢弃。
- 没有改的：
  - 没有为等属性推理而推迟关闭；
  - 没有恢复 Turn 固定参与者；
  - 设备重开（新一代来源）的路径（`_state()` 里的作废）没有改。那条路径原本就不受影响：参与者 runtime 观察到新一代时先退役旧一代，之后对旧段的 `bind_segment(..., None)` 会被拒绝，已确认的关联保留。我一开始也改了这里，核实后撤回，只留下测试。

### 1.3 回归测试（`persona/tests/test_persona_sensors.py`）

`test_a_source_that_ends_keeps_the_association_its_earlier_speech_settled`，参数为 `cancelled-source` 和 `new-generation`：

- 说话人处理器、profiler、Memory 都是真实的，跑在同一个 runtime 上；模型和向量库是替身。Memory 的向量库请求一律"什么都没找到"。
- alice 的一句话完成关联和身份识别，Turn 已提交，属性推理被卡住；这时她开始下一句，随后来源关闭（或设备重开）。
- 断言：
  - 属性推理被取消（`speaker.attribute` 为 `cancelled`）；
  - 未完成的那一段是 `invalid`；
  - 上一句的关联仍是 `bound`，`of_turn()` 读到 alice，Persona 停止之后也一样；
  - 放开卡住的属性推理后，结果没有写入；
  - profiler 在会话结束时把这一轮交给 alice 保存；
  - Memory 写入的对话记忆 owner 是 `user:alice`，scope 为 `owner`。
- 为了接上 profiler 和 Memory，测试辅助函数 `avatar_runtime` 可以传入 provider，`persona_for` 可以开启 profiler。
- 变异测试（仓库外加载）：
  - 已确认的关联也作废，也就是原来的行为：被发现；
  - 未完成的段不作废：被发现。

## 2. KD-51：安装后的 PATH 和首次 setup（P2）

### 2.1 经过

- 第一版：安装器在下一步之前打印当前 shell 要执行的 `export`，README 也加上这一行，不修改 shell 配置文件。
- 用户随后撤销了这个限制。新的要求是：README 不出现手动 export 和绝对路径；安装器自动配置 PATH，并接续首次 setup。
- 参考了 Codex 的安装脚本：它写一段带标记的 profile 内容，结束时从 `/dev/tty` 询问是否立即启动。
- 安装器是子进程，改不了用户当前 shell 的 PATH。所以分成两部分：
  - 自动配置的 PATH 服务新终端；
  - 当前终端的首次 setup，由安装器用命令的完整路径直接运行。

### 2.2 PATH 配置（`packaging/linux/install.sh`）

- 命令目录（`--bin-dir`，默认 `~/.local/bin`）已在 PATH 里：什么都不写，输出 `PATH: … is on PATH already`。
- 否则按登录 shell（`$SHELL`）选启动文件：
  - bash：`~/.bashrc`；
  - zsh：`${ZDOTDIR:-$HOME}/.zshrc`；
  - sh、dash：`~/.profile`。
- 写入的内容以 `# >>> AlphaAvatar >>>` 开始、`# <<< AlphaAvatar <<<` 结束，中间是 `case ":$PATH:" in *":<目录>:"*) ;; *) export PATH="<目录>:$PATH" ;; esac`。所以同一个文件读多次，目录也只加一次。
- 目录名里的 `\`、`"`、`$`、`` ` `` 转义后放在双引号里；含换行的目录名不写。
- 写入方式：
  - 文件里没有这段：追加到末尾，原有内容不动；
  - 已经有这段：逐行重建，第一段换成新内容，其余各行原样；
    - 内容没有变化：不写，输出 `already adds`；
    - 有变化：在同一目录写临时文件，保留原权限，再用 `mv` 替换，输出 `updated`。
  - 启动文件是链接时，改它指向的文件，链接本身保留。
- 不声称没做到的事。以下情况输出 `PATH: not configured: <原因>; to add it yourself:` 和要加的那一行，文件不改：
  - 其他 shell；
  - 启动文件不是普通文件；
  - 写不进；
  - 只有开始标记、没有结束标记。
- PATH 没配上不影响安装结果，安装器照常返回 0。

### 2.3 首次 setup 的询问

- 询问之前：
  - 先完成安装的清理（`cleanup`）；
  - 撤掉 EXIT、INT、TERM、HUP 的 trap；
  - 关闭安装锁的描述符 9，锁随之释放。setup 运行时会自己再拿锁。
- 以下情况不询问，只打印 `Next: alphaavatar setup`：
  - 已经 setup 过：`current` 或之前的指向是 `envs/*`；
  - 使用了 `--non-interactive`；
  - 打不开 `/dev/tty`。
- 询问的读写都通过 `/dev/tty`，由一个子 shell 负责：
  - 回车、`y`、`yes` 表示同意；
  - 其他回答、输入结束（Ctrl-D）和 Ctrl-C 都不运行 setup，输出 `Setup: not run. Next: …`；
  - 问题也由这个子 shell 打印。这样 Ctrl-C 不会落在主脚本还没进入读取的那一刻（见 2.5）。
- 同意后运行 `PATH="$bin_dir:$PATH" "$entry" setup < /dev/tty > /dev/tty 2>&1`：
  - 用管道安装时，bash 的标准输入是下载的脚本，所以 setup 的输入和输出都接到终端；
  - setup 运行期间，主脚本忽略 Ctrl-C，Ctrl-C 只结束 setup。
- 安装和 setup 的结果分开报告：
  - setup 成功：`Setup: done`；
  - setup 取消或失败：`Setup: did not finish (exit N); AlphaAvatar stays installed. Next: …`；
  - 安装器的退出码只代表安装。
- 不运行 Doctor，不启动 Host，不改已有的配置。
- 最后一行说明当前终端：
  - PATH 配上了：`This terminal finds alphaavatar in a new terminal, or after: source <文件>`；
  - 没配上：`… once <目录> is on PATH.`

### 2.4 文档

- README：
  - 安装区是 `curl … | bash` 一行加常用的 setup、doctor、start，没有 export，也没有绝对路径；
  - 我加过一句说明，大意是安装器随后询问 setup、PATH 用于新终端，用户要求删除；
  - 用户之后把两个代码块合回一个，和 HEAD 相同。本轮 README 没有改动。
- DEPLOY（用户要求简洁）：
  - 交互安装随后询问 setup，setup 失败或取消时安装保留；`--non-interactive`（`… | bash -s -- --non-interactive`）和没有终端时不询问；
  - PATH 写入带标记的一段，启动文件按登录 shell 选择；其他 shell 或写不进时给出要加的那一行；当前终端要 `source` 提示的文件，或新开终端；
  - 无人值守示例改为 `bash install.sh --non-interactive`，并在脚本里自己 `export PATH`，因为脚本不读启动文件；
  - 指定版本、本地包、镜像的说明保留。

### 2.5 实现中发现的问题

- 第一版在主脚本里 `read`，并为 INT 设了 trap。这时按 Ctrl-C 只会执行 trap，`read` 照样等下去，安装器卡住。真实 PTY 测试发现了这个问题。改为由子 shell 读取，Ctrl-C 结束子 shell。
- 第二版由主脚本先打印问题，再进入子 shell。在两者之间按下的 Ctrl-C 会被主脚本的 trap 吃掉，子 shell 照样等输入。改为由子 shell 打印问题，变异测试"问题在读取者之外打印"能稳定发现。

## 3. KD-52：下载失败时，外层管道不能返回成功（P2）

- 第一版把文档入口改成先下载、成功后再执行：`curl -fsSLO … && bash install.sh`。
- 用户选择 README 保留 `curl … | bash` 入口，于是改为：
  - DEPLOY 写明：下载失败、curl 什么都没输出时，bash 读到空脚本并返回 0，整条管道也返回 0；按退出码继续执行的脚本要先下载再运行，或者开启 `pipefail`；
  - 无人值守示例以 `set -euo pipefail` 开头，先 `curl -fsSLO`，再 `bash install.sh --non-interactive`。安装失败整个脚本就停，不会继续 setup。
- 安装器内部的 `{ … }` 仍然保证下载被截断的脚本什么都不执行。

## 4. 验证

### 4.1 安装器测试（`avatar-host/tests/setup/test_install_script.py`）

- 共 66 个：原有 41 个，新增 25 个。
- 删除了上一版 export 方案的 3 个测试：`test_the_documented_install_puts_its_command_on_this_shells_path` ×2 和 `test_the_installer_names_the_directory_the_command_went_to_before_the_next_step`。

PATH 配置：

| 测试 | 覆盖 |
|---|---|
| `test_the_command_goes_on_path_for_new_terminals_in_the_login_shells_startup_file` ×3（bash、zsh、sh） | 启动文件已有内容。第一次安装：标记段加在原有内容之后，新终端（用干净的 PATH 读这个文件）能找到命令。重复安装：输出 `already adds`，文件不变。换一个目录安装：输出 `updated`，仍然只有一段，旧目录不再出现，新终端找到的是新目录 |
| `test_zsh_keeps_its_startup_files_where_zdotdir_says_and_a_linked_file_stays_a_link` | 按 `ZDOTDIR` 选文件；`.zshrc` 是链接时，追加和整段替换都改链接指向的文件，链接保留；`~/.zshrc` 没有被创建 |
| `test_a_directory_on_path_already_is_written_into_no_startup_file` | 目录已在 PATH 里：不写任何文件，也不提示当前终端 |
| `test_a_directory_named_with_spaces_quotes_and_dollars_reads_back_exactly` | 自定义目录名里有空格、`$HOME`、`"`、`` ` ``、`\`，新终端读到的路径完全一致 |
| `test_a_startup_file_left_unconfigured_is_said_so_and_the_installation_stands` ×4 | 其他 shell（fish）、只读文件、启动文件位置是目录、段没有结束标记：输出 `not configured` 和原因，给出要加的那一行，不出现 added 或 updated，home 下的文件全部不变，安装照常完成 |

首次 setup。用真实 PTY（`setsid --ctty`，PTY 是控制终端），在本机的 HTTP 替身上原样运行 README 的那一行 `curl … | bash`。测试用的 setup 是替身，会记录：

- 标准输入是不是终端；
- 安装锁的描述符是否已关闭；
- `flock -n` 能否拿到锁；
- 暂存目录是否已删除；
- 从终端读到的一行。

| 测试 | 覆盖 |
|---|---|
| `test_piped_in_a_terminal_it_offers_setup_and_runs_it_on_that_terminal` ×3（回车、y、yes） | setup 的输入是终端，锁描述符已关闭，锁空闲，暂存已删除，读到终端上输入的 `hello`；输出 `Setup: done`；PATH 那一行在问题之前；没有运行 Doctor，没有启动 Host |
| `test_setup_declined_runs_nothing_and_the_installation_stands` ×4（n、no、Ctrl-D、Ctrl-C） | setup 没有运行，输出 `Setup: not run`，安装保留，已有的 `settings.json` 不变 |
| `test_a_setup_that_fails_or_is_stopped_leaves_the_installation_and_says_which` ×2 | setup 返回 3，或在 setup 中按 Ctrl-C（130）：安装器返回 0，输出 `did not finish (exit N)`，安装和 PATH 配置保留 |
| `test_non_interactive_in_a_terminal_installs_and_configures_but_never_asks` | 在终端里使用 `--non-interactive`：不询问，PATH 照常配置 |
| `test_a_terminal_already_set_up_is_offered_no_setup` | 已经 setup 过的环境：不询问，也不提示 `Next: alphaavatar setup` |
| `test_without_a_terminal_it_never_asks` | 没有控制终端：不询问，只给出 `Next:` |

下载失败与无人值守：

| 测试 | 覆盖 |
|---|---|
| `test_the_unattended_example_installs_asks_nothing_and_goes_on_by_itself` | DEPLOY 的无人值守示例整段运行：安装完成，不询问；示例自己的 `alphaavatar setup my-avatar` 能找到命令并运行 |
| `test_an_unattended_install_that_fails_never_goes_on_to_setup` | 无人值守示例在安装失败时返回 22，PATH 上预先放的同名命令一次也没被执行 |
| `test_piped_a_download_that_fails_succeeds_unless_the_outer_shell_has_pipefail` | README 那一行在下载失败时返回 0，外层开启 `pipefail` 后返回 22 |
| 原有的 `test_piped_to_bash_it_runs_once_whole_and_a_script_cut_short_runs_nothing` ×2 | 截断的脚本什么都不执行，完整的管道安装成功，保留不变 |

### 4.2 稳定性与变异测试

- PTY 的 12 个测试连续运行 3 次，全部通过。
- 变异测试在仓库外的文件副本里运行：对照组 66 个全部通过，16 个变异全部被发现。
  - 锁和清理：setup 前不关闭锁描述符；不先清理暂存。
  - 终端输入：setup 读管道而不是终端；问题在读取者之外打印。
  - 询问条件：`--non-interactive` 时仍然询问；已经 setup 过时仍然询问；回答 no 也当作同意。
  - 结果：setup 失败时安装器也返回失败；setup 中的 Ctrl-C 连带结束安装器。
  - PATH：每次安装都追加一段；不转义 `$`；写失败却声称成功；忽略 `ZDOTDIR`；未知 shell 改写 `~/.profile`；目录已在 PATH 里仍然写入；链接被替换成普通文件。

### 4.3 全量和仓库检查

- 离线全量（`PYTHONDONTWRITEBYTECODE=1 ALPHAAVATAR_MODEL_OFFLINE=1 uv run --no-sync pytest -p no:cacheprovider`）：975 passed，47 warnings，347 s。
  - 运行前后，工作区的文件列表（含被忽略的文件）一致，没有留下字节码或缓存。
  - 全量开始后我又压缩了 DEPLOY 的文字（无人值守代码块没变），所以在最终文档上重跑了安装器和 Persona 测试：150 passed。
- 仓库规范：都通过。
  - `uv lock --check`、`check_workspace.py`（16 个成员）；
  - `ruff check .`、`ruff format --check .`（793 个文件）；
  - `git diff --check`、`bash -n packaging/linux/install.sh`；
  - 对改动文件跑 pre-commit：全部通过，没有改动任何文件。

## 5. 未验证的边界

- **真实 release**：入口依赖 release 发布 `install.sh` 和 Linux 文件。v0.6.9 还没发布，真实 GitHub 上的下载和安装没有跑过，测试用的是本机替身。
- **真实 setup 的界面**：PTY 测试里的 setup 是替身。真实 `alphaavatar setup` 的逐项询问在 `< /dev/tty > /dev/tty` 下如何显示、如何响应，没有用真实安装包验证。
- **zsh 和 dash 本身**：本机没有 zsh 和 dash。测试用 `SHELL` 的名字选文件，再用 sh 读取文件来验证内容；zsh 实际读取 `.zshrc` 没有实测。写入的内容是 POSIX 的 `case`，zsh 也接受。
- **bash 登录 shell**：bash 作为登录 shell（例如 SSH 登录）读的是 `~/.bash_profile` 或 `~/.profile`，不直接读 `~/.bashrc`。常见发行版默认的这两个文件会再读 `~/.bashrc`；如果用户的文件不这样做，新的登录 shell 找不到命令。
- **当前运行的 shell**：选文件依据的是 `$SHELL`（登录 shell），不一定是当前正在用的 shell，例如在 bash 里临时开了 zsh。
- **其他 shell**：fish 等不自动配置，只给出说明和要加的那一行（POSIX 写法）。
- **说话人处理器的其他作废路径**：感知缺口（`batch.has_gap`）和段数超过上限时的淘汰，同样会对可能已确认的段调用 `_invalidate()`。它们不是来源关闭，不在本轮范围内，没有改，也没有验证，只在这里记录。
- **真实通话**：KD-50 没有在真实通话里验证，只有离线回归。
- 没有重跑 240 次中断注入，也没有重跑模型评测。

## 6. 第二批：KD-53～KD-55（基线 `09845713`）

- 依据：用户转来的 review（基于 `09845713`），三处问题。第 5 节里"bash 登录 shell"和"说话人处理器的其他作废路径"两条，就是本批修复的内容。
- 范围不变：Memory 规则、VAD 300 ms、寻址策略、安装器原有的保护；README 的入口不变；不运行 Doctor，不启动 Host。
- 删除了仓库外的旧证据目录 `~/alphaavatar-kd49-check`（用户要求）。本批的变异副本放在任务自己的临时目录里，用完即删。

### 6.1 KD-53：缺口和容量淘汰不能作废已完成的关联

- 原因：`_consume_loop` 遇到 `batch.has_gap`，对处理器里的所有段调用 `_invalidate()` 和 `_retire()`；`_state()` 在段数达到 `max_segments` 时，对最早的段也这样做。已提交 Turn、只剩属性推理的段因此变成 `invalid`。
- 改动：这两处改用 KD-50 的 `_abandon()`：停止剩余工作；已确认（`bound`）的关联保留，未完成的段作废。`_abandon()` 的说明补上这两种原因。
- 没有改：混合声音（`segment_consistency_threshold`）、同一段换设备、新一代来源这几条作废路径；`_invalidate()` 本身。
- 回归 `test_work_given_up_on_a_gap_or_a_full_table_keeps_the_associations_it_settled`，参数为 `gap` 和 `capacity`：
  - 与 KD-50 的测试共用 `remembered_session()`（真实的说话人处理器、profiler、Memory）和 `remembered_as_alice()`（会话结束时的归属检查）。
  - alice 的 Turn 已提交、属性推理卡住；bob 的段已绑定、身份检索卡住；第三段还在说。
  - 缺口：一次发布 300 帧，超过流保留的 256 条，处理器读到缺口。容量：`max_segments=1`，每来一段新的语音就挤掉最早的一段。
  - 断言：alice 和 bob 的段仍是 `bound`，未完成的段是 `invalid`；放开卡住的属性推理和身份检索后，结果都没有被采用（alice 没有写入属性，bob 没有绑定用户）；会话结束时 Turn 仍读作 alice，profiler 交给 alice 保存，Memory 的对话记忆 owner 是 `user:alice`，scope 为 `owner`。
- 换回 HEAD 的处理器（从仓库外加载）后，两种情况都失败：`assert 'invalid' == 'bound'`。
- 变异（仓库外加载）都被发现：
  - `_abandon` 一律作废；
  - `_abandon` 从不作废；
  - 已确认的段不退役；
  - 只留缺口路径为旧写法；
  - 只留淘汰路径为旧写法。

### 6.2 KD-54：PATH 标记异常时不改文件

- 原因：以前只用 `grep` 检查开始、结束标记是否存在。完整的一段之后再出现一个没有结束的开始标记，逐行重建时会跳过它之后的所有行，再报告 `updated`。用 HEAD 的 `install.sh` 复现：之后的用户配置被删除，输出 `PATH: updated …`。
- 改动（`configure_file`）：
  - 写入之前逐行检查全部标记，标记行两边的空白不影响识别；
  - 必须依次开始、结束，不能嵌套，最后一段必须结束；
  - 以下情况一律不改文件，输出行号和原因：
    - 孤立的结束标记（`line N of … ends AlphaAvatar's block, never begun`）；
    - 嵌套（`line N of … begins AlphaAvatar's block inside another`）；
    - 顺序颠倒：先出现结束标记，按孤立的结束标记处理；
    - 末尾没有结束（`AlphaAvatar's block begun on line N of … never ends`）；
  - 只读文件里已有这一段时，也不替换（`cannot write`）。
- 链接和权限的处理不变：改链接指向的文件，临时文件保留原权限后替换。
- 回归 `test_markers_out_of_order_leave_the_startup_file_as_it_was_to_the_byte` 有 6 种情况：
  - 完整一段之后接一段没有结束的；
  - 孤立的结束标记；
  - 先结束后开始；
  - 嵌套；
  - 末尾没有结束；
  - 标记行两边有空白。

  启动文件是链接时，断言链接指向的文件内容、权限、inode 和修改时间都不变，目录里没有留下临时文件，安装照常完成，并给出要加的那一行。`unconfigured` 测试新增"只读文件里已有这一段"。

### 6.3 KD-55：bash 登录终端的 PATH

- 原因：bash 只写 `~/.bashrc`。登录式 bash 读 `~/.bash_profile`、`~/.bash_login`、`~/.profile` 中第一个存在的文件；已有 `.bash_profile` 且不加载 `.bashrc` 时，登录终端找不到命令。用 HEAD 的 `install.sh` 复现：`bash -l` 中找不到。
- 改动：
  - bash 写两个文件：`~/.bashrc`，以及登录时读的那个文件；
  - 三个都不存在时写 `~/.profile`，不新建会遮住它的 `.bash_profile` 或 `.bash_login`；
  - 段内的 `case` 保证两个文件都被加载时，目录也只加一次；
  - 每个文件各输出一行结果；任何一个没配上时，再给出 `PATH: to add it yourself:` 和要加的那一行；
  - 最后一行：都配上时写 `in a new terminal, or after: source …`；只配上一个时只写 `after: source …`，不声称新终端都能找到。
- 回归实际启动 `bash -l` 和 `bash -i`（只给系统 PATH 和测试的 home），不手动加载安装器选的文件：
  - `test_bash_finds_the_command_in_new_terminals_logged_in_or_not` 有 5 种情况：没有启动文件；只有不加载 `.bashrc` 的 `.bash_profile`（同时有 `.profile`）；`.bash_profile` 加载 `.bashrc`；只有 `.bash_login`；只有 `.profile`。
    - 两种启动方式都找到命令，PATH 里这个目录只出现一次；
    - 原有内容保留，不新建其他启动文件；
    - 重复安装输出 `already adds`，所有文件逐字节不变。
  - `test_bash_with_a_startup_file_it_cannot_write_says_so_and_configures_the_other`：`.bashrc` 只读时如实说明，`~/.profile` 照常配置，登录终端能找到命令。
  - 空格和特殊字符目录的测试、PTY 测试里对 PATH 的检查，也改为实际启动 `bash -l` 和 `bash -i`；sh 的测试实际启动 `sh -l`。
- DEPLOY 的 PATH 段补上 bash 的两个文件，以及"标记异常的文件保持原样"。

### 6.4 KD-56：询问 setup 时 Ctrl-C 可能卡住（范围外，验证中发现）

- 发现：本批第一次离线全量里，`test_setup_declined_runs_nothing_and_the_installation_stands[ctrl-c]` 失败；只跑这个测试，15 次失败 8 次。安装器显示 `^C` 后不再输出，也不退出。
- 原因：第一批把问题的打印和读取放进命令替换里的子 shell。进程状态显示，子 shell 收到 Ctrl-C 后仍停在 `read`，信号被吞掉了。Ctrl-C 恰好落在打印之后、`read` 开始之前时就会这样。把打印挪进子 shell 只是缩小了这个窗口。
- 改动：
  - 读取放到后台。非交互 shell 的后台任务忽略 SIGINT，由安装器自己接收；它在 `wait` 里等待，被捕获的信号总会让 `wait` 立即返回；
  - 之后结束读取，回答经 `mktemp` 建的临时文件传回；
  - INT 和 EXIT 的 trap 在启动读取之前设好。安装器以任何方式结束，包括收到 TERM、HUP（bash 对这两个信号同样运行 EXIT trap），都会结束读取进程、删除临时文件，不会留一个进程在终端上读走用户 shell 的下一行；
  - 问题结束后撤掉这些 trap，后面 setup 的处理不变。
- 新回归 `test_an_installer_ended_at_its_question_leaves_no_reader_on_the_terminal`，参数为 TERM 和 HUP：
  - 用户的 shell 运行 README 那一行后继续存在，和真实终端一样。如果让它退出，终端挂断时内核会结束它留下的进程，问题就被掩盖了；
  - 在询问时向安装器发信号，断言它以 143 或 129 退出，读取进程不再存在，临时目录为空。
- 验证：
  - 在仓库外用真实 PTY 探测 40 次，每次一出现问题就按 Ctrl-C，全部正常结束；
  - 全量测试同时运行时，PTY 的 12 个测试连续 10 轮通过。
- 变异测试（仓库外的文件副本）：
  - 读取放回前台、EXIT 时不结束读取进程、不删临时文件：都被发现；
  - 去掉 TERM、HUP 的 trap 时测试照样通过，原因是 bash 自己会运行 EXIT trap。这两个 trap 是多余的，已删除。
- 局限：旧的写法在变异测试的副本里 5 次都通过，说明这个竞态只是有时出现，测试不能稳定地发现它。
- 这项不在本批点名的三处问题之内。因为它让要求的离线全量失败，而且只涉及询问这一段，我直接修了。如果要拆出去，只需撤回 `install.sh` 里询问的那一段和这个新测试。

### 6.5 验证

- 相关测试：安装器 79 个（第一批 66 个，本批新增 13 个）；KD-56 之前，Persona、参与者 runtime 和安装器合计 256 passed。
- 安装器变异测试：在仓库外的文件副本里运行，只跑 PATH 相关的 23 个测试。对照组全部通过，HEAD 的 `install.sh` 有 17 个失败，9 个变异全部被发现：
  - 标记只认完全相同的行；
  - 放过嵌套；
  - 放过孤立的结束标记；
  - 放过没有结束的段；
  - bash 只写 `.bashrc`；
  - 登录文件固定写 `.profile`；
  - 登录文件固定写 `.bash_profile`；
  - 只读文件里有这一段时仍然替换；
  - 只配上一个文件时仍声称新终端都能找到。
- 离线全量（`PYTHONDONTWRITEBYTECODE=1 ALPHAAVATAR_MODEL_OFFLINE=1 uv run --no-sync pytest -p no:cacheprovider`）：
  - 第一次 987 passed、1 failed，就是 KD-56；
  - 修好后的最终一次 990 passed，47 warnings，350 s；运行前后，工作区的文件列表（含被忽略的文件）一致。
- 仓库规范：都通过。
  - `uv lock --check`、`check_workspace.py`（16 个成员）；
  - `ruff check .`、`ruff format --check .`（793 个文件）；
  - `git diff --check`、`bash -n packaging/linux/install.sh`；
  - 对改动文件跑 pre-commit：全部通过，没有改动任何文件。
- CI：`09845713`（第一批）的 Quality 和 Linux package 都通过。本批还没有提交，没有对应的 CI。

### 6.6 未验证的边界

- 真实安装流程没有跑：v0.6.9 未发布，真实 setup 的终端界面也没有验证，由用户最后验收。
- zsh 没有实际启动验证（本机没有 zsh）；`.zprofile` 不写，非交互的登录 zsh 不读 `.zshrc`。
- 发行版的 `/etc/profile` 改写 PATH 的方式各不相同；本机的 bash 登录测试通过，其他发行版没有验证。
- KD-53 只有离线回归，没有真实通话；缺口和容量淘汰在真实通话里很少出现。

## 7. 第三批：KD-56 收尾、截断下载测试（基线 `d9ccfd2b`）

- 依据：用户转来的复查（基于 `d9ccfd2b`）。KD-53～KD-55 已通过，保持不变；只处理两项。
- 范围：不做其他重构，不改版本号。

### 7.1 Ctrl-C 先于等待到达

- review 的复现：问题已显示、尚未进入 `wait "$reader"` 时收到 Ctrl-C，INT 的处理只打印一个换行，之后照样进入 `wait`。后台读取忽略 SIGINT，安装器仍要再输入一次 `n` 才结束。
- 本机（bash 4.4）上还有两点：
  - INT 的 trap 在启动读取之前就设好时，bash 4.4 的读取进程收到 Ctrl-C 会自己结束；review 用的 bash 上则忽略。行为随版本不同。
  - Ctrl-C 恰好打断问题本身的写入时，`printf` 返回 "Interrupted system call"，`set -e` 让安装器以 1 退出，没有任何取消的说明。HEAD 的 `install.sh` 在本机就是这样失败的（下面的新测试，3 次都失败）。
- 改动（`packaging/linux/install.sh`，只改询问这一段）：
  - INT 的 trap 记录 `cancelled=1` 并换行；
  - 不再用 `wait`：每 0.1 秒查看一次取消标记和读取进程是否还在（`kill -0`）。Ctrl-C 无论落在哪一刻，包括 `wait` 这类内建命令刚开始时 bash 自己的空隙，最晚在下一次查看时生效；
  - 查看结束后结束读取进程并回收；取消时不读回答文件；
  - 读取进程显式忽略 Ctrl-C（`trap '' INT`），结束它始终由安装器负责，各 bash 版本一致；
  - 问题的写入失败（被 Ctrl-C 打断）不再算安装失败；
  - 取消时输出 `Setup: cancelled, not run. Next: …`。不运行 setup，安装保留，退出码 0；
  - EXIT 的 trap 在读取进程已结束时也不会中途停下，临时文件照样删除。
- 回归 `test_a_ctrl_c_before_the_installer_waits_for_its_answer_cancels_with_nothing_more_typed`，时序是确定的：
  - 安装器的输出重定向到文件，终端上只剩它写的问题；启动前先向终端发送 XOFF（Ctrl-S），停止输出；
  - 等到读取进程已经存在，且安装器停在写问题这一步（进程处于睡眠状态，0.3 秒后仍是）。这时它一定还没开始等待；
  - 发送一次 Ctrl-C（它同时恢复输出），之后不再输入任何内容；
  - 断言：安装器输出 `Setup: cancelled, not run.`，退出码 0；读取进程已不存在，临时目录为空；setup 没有运行，安装保留；
  - 用户的 shell 在安装器结束后继续存在。如果让它退出，终端挂断时内核会结束遗留的读取进程，问题就被掩盖了。
- 原有测试的调整：
  - Ctrl-C 的拒绝用例改为断言 `Setup: cancelled, not run.`；
  - TERM、HUP 的测试和新测试共用 `question_reader()`：按标准输入是终端来找读取进程，因为安装器现在还有一个 `sleep` 子进程。
- 变异测试（仓库外的文件副本）：
  - 被发现：不记录取消；问题写入失败时安装失败；查看结束后不结束读取进程；
  - 没被发现，符合预期：
    - 用 `[[ -n "$cancelled" ]] || wait` 代替查看：剩下的只是 `wait` 开始时微秒级的空隙，无法确定性地命中；
    - 读取进程不显式忽略 Ctrl-C：本机 bash 4.4 上它会被 Ctrl-C 结束，两种写法表现相同。显式忽略是为了让其他版本也一致。
  - HEAD 的 `install.sh`：新测试 3 次都失败。

### 7.2 截断下载测试

- `test_piped_to_bash_it_runs_once_whole_and_a_script_cut_short_runs_nothing[half]` 要求 stderr 含 `syntax error`。截断点落在引号里时，CI 的 bash 只输出 `unexpected EOF while looking for matching`；本机 bash 4.4 两行都输出，所以本地通过。`d9ccfd2b` 的 Quality 因此失败（1 failed, 989 passed）。
- 改为不检查措辞：退出码 2，stdout 为空，stderr 不为空（bash 说明了原因）。没有下载请求、没有创建安装目录和命令目录，这些断言保留。

### 7.3 验证

- 安装器测试：80 passed。询问相关的 PTY 测试连续 6 轮通过。
- 离线全量（`PYTHONDONTWRITEBYTECODE=1 ALPHAAVATAR_MODEL_OFFLINE=1 uv run --no-sync pytest -p no:cacheprovider`）：991 passed，47 warnings，350 s；运行前后，未跟踪和被忽略的文件一致。
- 仓库规范：都通过。
  - `uv lock --check`、`check_workspace.py`（16 个成员）；
  - `ruff check .`、`ruff format --check .`（793 个文件）；
  - `git diff --check`、`bash -n packaging/linux/install.sh`；
  - 对改动文件跑 pre-commit：全部通过，没有改动任何文件。
- CI：
  - `d9ccfd2b`：Linux package 通过，Quality 失败，原因就是 7.2 的措辞断言；
  - 本批还没有提交，没有对应的 CI。

### 7.4 未验证的边界

- 本机只有 bash 4.4，review 和 CI 用的较新 bash 上，没有在本机运行新测试。新测试要等提交后的 CI 才会在那个版本上运行。
- 每 0.1 秒查看一次，意味着回答后最多晚 0.1 秒继续，等待期间每秒启动约 10 次 `sleep`。
- 真实安装流程和真实 setup 的终端界面仍由用户最后验收。

## 8. 第四批：读取进程的归属窗口（基线 `fa022e9d`，2026-11-23）

- 依据：用户转来的复查。`fa022e9d` 的 Ctrl-C 和截断下载修复已通过，Bash 5.2.37 上安装器 80 项测试全部通过；只剩这一个窗口。
- 实际通话：用户已验收通过。第 5 节、第 6.6 节里"KD-50、KD-53 没有在真实通话里验证"这两条，由这次验收补上。剩下由用户验收的是安装和真实 setup 流程。

### 8.1 问题

- 安装器在 `{ …; } &` 创建读取进程之后、执行 `reader=$!` 之前收到 SIGTERM（或 SIGHUP）时，EXIT 清理看到的进程号是空的。
- 安装器以 143 退出、临时文件删除，读取进程却成为孤儿，继续读终端。
- review 确定性复现：创建读取进程后、记录进程号前暂停父进程，发送 SIGTERM 后恢复；外层用户 shell 保持存活，排除了终端挂断自动清理的影响。

### 8.2 改动（`packaging/linux/install.sh`，只改询问这一段）

- 创建读取进程之前，TERM、HUP 的 trap 改为只记下信号（`held=TERM`、`held=HUP`）；`reader=$!` 之后撤掉这两个 trap，记下过信号的，用 `kill -s "$held" "$$"` 按原信号重新发给自己。这时 EXIT 清理已经能找到读取进程，安装器以原信号结束（143、129），之后什么都不再做，问题也不会显示。
- 读取进程一律用 KILL 结束，EXIT 清理和询问结束后都是。验证中发现，只暂缓还不够：
  - 读取进程刚启动时继承了安装器用于暂缓的 trap，还没来得及撤掉时收到的 TERM 会被它吞掉；
  - 用 TERM 结束时，HUP 的情况 6 次里有 5 次留下读取进程；改用 KILL 后，TERM、HUP 各 8 次都正常。
  - 读取进程只读一行，不持有需要清理的资源；回答文件由安装器删除。`wait` 的输出已重定向，不会显示 `Killed`。
- 回收之后清空记录的进程号（`reader=""`）。之后再触发 EXIT 清理，也不会去结束一个可能已被别的进程复用的进程号；只回收本次创建的进程。
- Ctrl-C 的语义不变：取消询问，不运行 setup，安装保留，退出码 0。

### 8.3 回归

`test_a_signal_as_the_reader_starts_before_it_is_recorded_still_ends_it`，参数为 SIGTERM 和 SIGHUP：

- 测试里的 `Tracer` 通过 libc 调用 ptrace（`PTRACE_SEIZE` 并跟踪 fork），不依赖 strace 或 gdb；ptrace 不可用时跳过。
- 原样运行 README 那一行，安装器一出现就接管它，跟踪它的每次 fork：
  - 新进程在第一次停下时就放开；
  - 回答文件已经存在后的第一次 fork，就是创建读取进程的那一次。这时读取进程已经存在，安装器停在内核里，还没执行 `reader=$!`。在这里发送信号，再放开安装器。
- 用户 shell 在安装器结束后继续存在。
- 断言：退出码 143 或 129；读取进程不再存在；临时目录为空；问题没有显示；安装有效。
- 同样的办法用在仓库外的探测脚本上：HEAD 的 `install.sh` 每次都留下读取进程（TERM、HUP 各 2 次）；修复后 TERM、HUP 各 8 次都正常。

### 8.4 验证

- 新测试连续 5 轮通过。
- 变异测试（仓库外的文件副本，跑询问相关的测试）：
  - 对照组通过；
  - HEAD 的 `install.sh`：新测试的两个参数都失败（2 次）；
  - TERM、HUP 不暂缓：都失败（2 次）；
  - 暂缓的信号不再处理：失败；
  - 暂缓不撤掉：失败；
  - 读取进程用 TERM 结束：4 次里 3 次失败。这个竞态发生在读取进程刚启动的一瞬间，测试只能以较高概率发现，不能每次都发现。
- 安装器测试：82 passed（第三批 80 个，本批新增 2 个）；询问和信号相关的 17 个测试连续 3 轮通过。
- 离线全量（`PYTHONDONTWRITEBYTECODE=1 ALPHAAVATAR_MODEL_OFFLINE=1 uv run --no-sync pytest -p no:cacheprovider`）：993 passed，47 warnings，353 s；运行前后，未跟踪和被忽略的文件一致。
- 仓库规范：都通过。
  - `uv lock --check`、`check_workspace.py`（16 个成员）；
  - `ruff check .`、`ruff format --check .`（793 个文件）；
  - `git diff --check`、`bash -n packaging/linux/install.sh`；
  - 对改动文件跑 pre-commit：全部通过，没有改动任何文件。
- CI：
  - `fa022e9d`：Quality 和 Linux package 都通过；
  - 本批还没有提交，没有对应的 CI。

### 8.5 未验证的边界

- 本机是 bash 4.4；新测试要等提交后的 CI 才会在较新的 bash 上运行。
- 安装和真实 setup 流程由用户最后验收。
