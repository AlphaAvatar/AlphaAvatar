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
| 发布前修复 | KD-50 来源关闭保留已完成的关联；KD-51 安装器为新终端配置 PATH，并在交互安装结束时接续首次 setup；KD-52 下载失败时管道的退出码 | 2026-11-22 | `064222fb` | — | 待审查 |

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
