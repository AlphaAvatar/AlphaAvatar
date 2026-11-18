# AlphaAvatar v0.6.9 本机升级（`alphaavatar upgrade`）— Claude Code 实施日志

- 分支：`dev/v0.6.9`；日期均为 CST。
- 本文件是 Linux x86_64 官方安装包本机升级的主日志，按时间顺序追加。
- 统一的 KD/O 表仍在 `docs/agent-logs/2026-10/2026-10-25/claude-code-2a-zh.md`。

## 批次总览

| 批次 | 内容 | 日期 | 基线 HEAD | 提交 | 状态 |
|---|---|---|---|---|---|
| 第一步 | `alphaavatar upgrade` 与 `--check`：按 build ID 区分构建；目标包校验后解包到旁边，目标自己的 `setup <bundle> --plan` 和 catalog 规划默认 bundle 的环境，目标自己的命令验收，之后在安装锁下一次切换 `current`；失败保持原环境 | 2026-11-17 | `afe1feba` | `122128b8`（用户提交） | 已提交 |
| 第二步 | 修复审查发现的三处：默认 bundle 和凭据在安装锁内读取；同构建 `--file` 先只读核对，不复制、不建暂存；目录移入与记录归属在信号延后期间一起完成。新增 `alphaavatar cleanup`（`tools/cleanup/`） | 2026-11-17 | `122128b8` | `9d71447e`（用户提交） | 已提交 |
| 第三步 | cleanup 的三处保护缺口：`.env` 指定的 home、暂存目录、校验失败的计划；记录在 [2026-11-18 日志「收尾」](../2026-11-18/claude-code-readme-zh.md#收尾基线-174d1632) | 2026-11-18 | `174d1632` | `cde30675`（用户提交） | 已提交 |

## 历史记录（合并来源）

原文都保留。

| 原位置 | 原结论 | 现状 |
|---|---|---|
| 安装日志「第 1 项」本项不做 | 升级回滚和旧版本清理属于第 5 项 | 本轮只做升级到新版激活为止；回退、降级、旧版本清理、`0.6.8` 配置迁移已从清单移除 |
| 安装日志第 1 项后续「待定事项」第 3、4 条 | 换基础包后需要重新 `setup`；setup 只增不减 | 升级把「换基础包」和「重新 setup」合成一步；新环境的计划保留当前环境已有的需求，仍只增不减 |
| t10 日志标题「安装、升级回滚与 Doctor 阶段」 | 阶段规划，未实现升级 | 由本日志承接 |

---

## 第一步（基线 `afe1feba`）

依据：用户 2026-11-17 的任务说明。范围：本机升级及其文档，验收以两份 `0.6.9` 构建为准，到新版激活为止；实际 LiveKit 通话由用户验收。改动全部留在工作区，未暂存、未提交。

### 1. 命令

- `alphaavatar upgrade --check`：显示当前构建、目标构建，以及是否为升级。不改任何东西。发布渠道只下载 release 旁边的 manifest。
- `alphaavatar upgrade`：默认目标是最新 release；`--version X.Y.Z` 指定某个 release；`--file PACKAGE` 指定已下载的包，例如 CI 构建。SHA-256 来自 `--sha256`，否则取包旁边的 `.sha256`，与 `install.sh` 相同。`--artifacts DIR|URL` 指定目标构建自身 wheel 的位置。默认规则：`--file` 的 CI 构建取包所在目录，release 构建取它的 release。
- 构建身份：manifest 的 `id`，即 `<version>-<commit>`。两份都标 `0.6.9` 的构建是两个构建，可以互相升级；目标就是当前构建时直接结束，退出码 0；目标版本更旧时拒绝。
- 退出码：0 表示已升级、本已是目标、或 `--check` 已打印；1 表示什么都没改（下载、SHA-256、包、计划、安装、校验失败，版本更旧，另一安装进行中，不在 Linux 包里运行）；2 表示其他错误；130、143、129 表示信号。

### 2. 准备与切换

`tools/upgrade/upgrade.py`（审查后从 `tools/setup/` 移出，见第 9 节）。整个过程持有 `<prefix>/.install.lock`，与 `install.sh`、`setup` 是同一把锁。

1. **Package**：包复制或下载到 `versions/.install-XXXXXX`。这个暂存目录与 `install.sh` 用同一个前缀和标记 `.alphaavatar-install`，两者都能清理对方被杀后留下的暂存。先比对 SHA-256，再读包内 manifest；与当前同一构建就结束，版本更旧就拒绝；然后检查 glibc 和 CPU。之后解包到 `versions/<id>`：用 `tarfile` 的 `data` 过滤器，只允许一个顶层目录。已有同名目录时，manifest 相同才复用，否则拒绝。最后按 `install.sh` 的方式检查：从 `/` 运行 `--version`、`--help`，并导入 manifest 列出的原生模块。
2. **Plan**：用目标基础包自己的 `alphaavatar setup <默认 bundle> --plan` 取需求，这一步用的是目标的配置解析器。再加上当前环境 `plan.json` 记录的需求，用目标的 `catalog.json` 规划。`setup --plan` 被拒绝时，stdout 也输出 `{"error": {"diagnostic": …}}`，升级把这段原因原样报出。当前只运行基础包、没有 setup 环境时，只切换到目标基础包。
3. **Install / Validate**：复用 `environment.install_locked`，也就是 `install()` 去掉加锁那层，新增 `replacing` 参数，允许当前运行的是被替换的旧基础包。新环境在 `envs/<plan>`。切换前依次确认：新环境命令报告目标版本；`probe` 能加载原生库；`config check <bundle> --json` 接受该 bundle。凭据来自环境、`.env` 和已存储的凭据。
4. **切换**：原子替换 `current` 一次。随后通过 `current/bin/alphaavatar --version` 再确认一次，失败就切回原处。切换和这次确认期间信号延后处理。

失败或收到信号时：只删除本次创建的 `versions/<id>`（`current` 没有指向它时）、环境和暂存。`current`、命令入口、上一版本及其环境、应用 home 都不动。升级不写应用 home。上一版本和环境保留，本轮不清理。

### 3. 复用与改动的现有代码

- `environment.py`：
  - 抽出 `download()`，`fetch()` 和升级共用三次重试；
  - 抽出 `sha256()`；
  - 把 `machine_problems()`、`check_machine()`、`megabytes()` 从 setup 命令移到这里，setup 改为调用；
  - `_switch`、`_signals_wait` 改名为公开的 `switch_current`、`signals_deferred`；
  - `install()` 包一层 `install_locked()`。
- `cli/commands/setup.py`：`--plan` 被拒绝时，stdout 输出错误 JSON，stderr 的报告不变。
- `packaging/linux/build.sh`：输出目录多一个 `alphaavatar-linux-x86_64.manifest.json`（包内 manifest 的副本），并列入 `SHA256SUMS`。release 工作流上传整个目录，所以它会随 release 发布，`--check` 和「已是目标」不必下载包。
- 新增 `cli/commands/upgrade.py`，在 `cli/app.py` 注册 `upgrade` 子命令。

### 4. 文档

新增 `docs/cli/upgrade.md`；更新 `docs/cli/README.md`（命令表）、`docs/cli/setup.md`（`--plan` 被拒绝时的 JSON）、`docs/DEPLOY.md`（升级段落），以及 `AGENTS.md`、`AGENTS-zh.md` 的工作区表、变更路线和文档索引。`docs/cli/cli.html` 没有重录。

### 5. 离线测试

新增 `avatar-host/tests/upgrade_samples.py`，在 `pythonpath` 上，两个测试文件共用。它造同一版本的两份构建：包含 manifest、catalog、包自带的 Python 包装脚本，以及替身命令。基础包命令应答 `--version`、`--help`、`setup --plan`；环境命令来自每个构建各自的 `host` wheel，应答 `--version`、probe、`config check`，并记录运行时 `current` 指向哪里。

- `tests/upgrade/test_upgrade.py`（14 项，审查后从 `tests/setup/` 移出）：
  - A→B 只切换一次，计划和校验发生在切换之前，且由目标执行；计划保留当前环境的 `alpha`；新环境能导入 alpha 和 beta；A 保留；
  - 同一构建直接结束；更旧的版本被拒绝；
  - 9 种失败后，`current` 和 prefix 的文件列表都不变：SHA-256 不符、不是包、基础包不能运行、目标计划拒绝、wheel 缺失、混入其他构建的 wheel、配置校验拒绝、经 `current` 确认失败、校验后被中断；
  - 锁被占用时拒绝；
  - 裸基础包只切换基础包；
  - loopback 上模拟 GitHub 布局的 release：`--check` 只请求 manifest；升级下载 `.sha256`、包和 release 里的 wheel；再次升级只请求 manifest；旧构建在 `current` 已变后拒绝；不存在的 release 报 404。
- `tests/cli/test_upgrade.py`（2 项）：`--check` 两个方向的输出；失败、成功、再次运行的报告；应用 home 逐字节不变。
- 修改的测试：`test_setup.py` 断言 `--plan` 被拒绝时输出 JSON；`test_entrypoint.py` 的命令列表加入 `upgrade`。
- 变异验证 13/13 被测试捕获：
  - 计划丢弃当前环境需求；
  - 用运行中构建的 catalog 规划；
  - 不检查基础包；
  - 失败后保留本次解包的版本；
  - 不比对 SHA-256；
  - 切换后不经 `current` 确认；
  - 不加锁；
  - release manifest 不用于提前结束；
  - 不拒绝更旧的版本；
  - 校验前就切换；
  - 失败信息缺少修正后重试的提示；
  - 不调用目标的计划；
  - setup `--plan` 被拒绝时不输出 JSON。

  脚本和日志在会话临时目录 `mutants/`。

### 6. 真实构建验收

同一份工作树在临时 clone（不是本仓库）中，只把各 `version.py` 改为 `0.6.9`，提交后用 `packaging/linux/build.sh --max-glibc 2.32` 构建（uv 0.10.0）。临时 clone 的 tracked 改动与本仓库 `git diff HEAD` 的 SHA-256 相同（`e5a79ba7…`），另加 6 个新文件。

| 构建 | build ID | 内容 |
|---|---|---|
| A | `0.6.9-0600b13e01d0` | 工作树，标为 0.6.9 |
| B | `0.6.9-3ade593c77ca` | A，在 host 的 `version.py` 和 router 的 `__init__.py` 各加一行注释 |
| C | `0.6.9-475826916b93` | A，router 的 `RouterConfig` 新增必填项 `acceptance_marker`（bundle 里没有） |

隔离目录：独立的 HOME、`ALPHAAVATAR_HOME`、prefix 和 bin。命令在 `env -i` 下运行，环境里没有任何凭据。

1. `install.sh --file A`。`alphaavatar setup --artifacts out-A` 在 pty 中逐项回答，结果：bundle `my-avatar`，默认，105 个包、514 MB，8 个 runner；4 个占位凭据按「是」存储为 `credentials-<id>.env`。在 workspace 和模型缓存里各放一个标记文件，记录 home 18 个文件的 SHA-256 作为基线。
2. `--check`：
   - `--file B`：可升级，显示 Current `0.6.9-0600b13e01d0`、Target `0.6.9-3ade593c77ca`；
   - `--file A`：目标就是当前构建；
   - 不带参数，查询真实 GitHub：最新 release v0.6.8 返回 `alphaavatar-linux-x86_64.manifest.json: HTTP 404`，退出码 1。
3. 失败（之后都确认 `current` 仍指向 A 的环境；`alphaavatar --version` 和 `config check`（8 个 runner、valid）正常；home 和 prefix 逐项不变）：
   - 制品校验：`--sha256 000…`，以及改动 1 字节的包副本，都报 `does not match its SHA-256`；
   - 依赖准备：`--artifacts out-A`，第 5 个包 `alpha_avatar_plugins_context-0.6.9…whl: not the planned file`；
   - 配置校验：`--file C`，105 个包装完后，C 的 `config check` 报 `fields: acceptance_marker`，后面附「修正后重试」提示；装好的环境已删除。
4. 升级：`alphaavatar upgrade --file B`（第三方 wheel 从 PyPI 和 PyTorch 下载），57 s，退出码 0。结果：
   - `current` 改为 `envs/73bcf97c85db5e92`；`--check --file B` 报目标就是当前构建；无凭据环境下 `config check` 通过，说明读的是已存储凭据，8 个 runner；
   - 新环境里 host 和 router 的源码都含 B 的标记；
   - A、B 两个环境都是 105 个发行版，名称和版本一致；`plan.json` 的 16 项需求一致，base 从 A 变为 B；
   - home 18 个文件逐字节不变：默认 bundle、Avatar ID、配置、凭据、workspace、模型缓存；
   - `versions/A` 和 A 的环境保留，各约 209 MB 和 1.7 GB。
5. 重复：再执行 `upgrade --file B`，输出 `current already; nothing to do`，prefix 和 home 不变。
6. 裸基础包：只 `install.sh` 装 A，不 setup，升级到 B 后 `current` 指向 `versions/0.6.9-3ade593c77ca`。

第一轮用较早的工作树跑过同样的流程（A `0.6.9-d07f597e5fe1`、B `0.6.9-8cd2fba0c1a7`、C `0.6.9-389ed380ae56`），结果相同。期间修了两处显示：同一构建时第 1 步留下空的 `Package` 行；裸基础包误写「及其环境」。修后按上表重建并重跑。脚本、包和输出在会话临时目录 `upgrade/`（`build-three.sh`、`accept/all.sh`、`accept/steps.sh`、`accept/round2.log`）。

### 7. 检查

- `ruff check .`、`ruff format --check .`、`git diff --check`、`uv lock --check`、`check_workspace.py`：通过。
- 全量离线测试：758 passed。之后改了两处显示，`avatar-host/tests` 重跑 335 passed。

### 8. 未做与待定

- 实际 LiveKit 通话由用户验收。验收用的凭据是占位值。
- 旧版本和旧环境不清理，也没有回退命令（按任务说明移除）。
- 当前环境里有、目标 catalog 里没有的需求，会使升级在计划阶段失败。同一版本的构建之间不会出现；跨版本时怎么处理待定。
- 发布渠道还没有带 Linux 包的 release。从 release 升级的路径只在 loopback 上验证过，没有对真实 release 验证；真实 GitHub 只验证了「没有包」这一种情况。
- CI（`linux-package.yml`）没有加入升级冒烟测试。
- 观察到但没有修改：插件 `init_config` 校验失败时，`config check` 的诊断只给字段名（`fields: acceptance_marker`），没有完整设置路径（`router.init_config.…`）。这是现有格式。
- `docs/cli/cli.html` 未收录 upgrade 画面。

### 9. 审查后修改

- 目标就是当前构建时，`--check` 原来输出 `Up to date: AlphaAvatar <id> is current`。用户指出：A 既能升级到 B，就不能说 A 已是最新。这句话实际只表示目标就是当前构建，不说明没有更新的构建。现改为 `The target is current already: AlphaAvatar <id>`，与升级时的 `is current already; nothing to do` 一致，`docs/cli/upgrade.md` 同步修改。第 6 节按新措辞记述；当时真实构建打印的是旧措辞。
- 用户要求 upgrade 单独一个 tools 目录：`tools/setup/upgrade.py` 移到 `tools/upgrade/upgrade.py`，内容只改了两行导入（改为从 `alphaavatar.host.tools.setup.environment`、`.plan` 绝对导入）；新增 `tools/upgrade/__init__.py`，只有说明；`tools/setup/__init__.py` 恢复为基线内容。`cli/commands/upgrade.py` 的导入、`tests/setup/test_upgrade.py` → `tests/upgrade/test_upgrade.py`、`AGENTS.md` 与 `AGENTS-zh.md` 的变更路线同步修改。

复验（第三轮，代码为上述修改后的工作区）：

- 离线全量测试 758 passed（301 s）；`ruff check .`、`ruff format --check .`、`git diff --check`、`uv lock --check`、`check_workspace.py` 通过。
- 13 个变异对新路径重跑，13/13 被捕获；跑完工作区 20 个改动文件的 SHA-256 与跑前一致。
- 真实构建：clone 回到 `afe1feba`，套用工作区改动（不含日志），只把 16 个 `version.py` 改为 0.6.9；逐文件比对与工作区一致。A `0.6.9-26c8619cf0f5`、B `0.6.9-adac0dac0d0a`、C `0.6.9-3a489cda69aa`，B、C 的构造与第二轮相同。基础包里是 `alphaavatar/host/tools/upgrade/`，没有 `tools/setup/upgrade.py`。
- 按第 6 节的步骤重跑，结果相同：setup A 后 `current` 为 `envs/a4368b9226783a9a`，8 个 runner；`--check --file B` 可升级，`--file A` 输出 `The target is current already`；真实 GitHub 仍为 HTTP 404；SHA-256 错误、改动 1 字节、`--artifacts` 指向 A 的 wheel、C 的配置校验失败，之后 `current`、A 的 `config check`、home 和 prefix 都不变；升级到 B 用时 57 s，`current` 为 `envs/682672ad2be5fa65`，B 的 host 和 router 标记都在，新环境的 upgrade 模块来自 `tools/upgrade/upgrade.py`，两个环境 105 个发行版一致，16 项需求一致，home 18 个文件不变；重复升级直接结束；裸基础包只切换基础包。输出在会话临时目录 `upgrade/accept3/round3.log`。

---

## 第二步（基线 `122128b8`）

依据：用户 2026-11-17 的第二份任务说明。范围：修复第一步审查发现的三处问题；新增独立的 `alphaavatar cleanup` 处理旧环境；用两份 `0.6.9` 构建复验。升级方式不变：为目标准备独立 env，验证通过后再切换 `current`。改动全部留在工作区，未暂存、未提交。

### 1. 审查问题的修复

1. **并发 Setup 校验错 bundle。** 原来 CLI 在取锁前调用 `load_environment()`，读出默认 bundle，并把已存储凭据写进进程环境；取锁前完成的 Setup 改动就看不到了。现在 CLI 只读 `.env`（`init_env()`）。`tools/upgrade` 的 `upgrade()` 拿到 `.install.lock` 后，用一次 `read_stored(paths)` 取默认 bundle 和已存储凭据。目标的 `setup <bundle> --plan` 和 `config check` 用的是同一份快照：bundle 名作为参数传入，凭据放进它们的环境；已设置的环境变量优先，与 start 一致。`Upgraded.bundle` 把这个 bundle 带回 CLI 显示。
2. **同构建 `--file` 仍复制包。** 取锁后先只读核对：文件的 SHA-256（`_read`），再读包内 manifest 的 build ID。如果是当前构建，就直接成功返回，不复制、不建暂存，也不清理其他运行留下的暂存；版本更旧或机器不满足，也在这一步拒绝。实际升级时照旧复制到暂存，复制件再比对一次 SHA-256，解包用的就是这个复制件；复制件里的 build ID 与只读读到的不一致就拒绝。`--check` 也改用 `_read`，SHA-256 不符时的提示与升级一致。
3. **中断可能留下新建目录。** 两组操作各自放进 `signals_deferred()`：`os.rename(解包目录, versions/<id>)` 与 `fresh = base`；`install_locked` 里的 `os.rename(stage/env, envs/<plan>)` 与 `created = True`。同一类问题还有一处，一并处理：`mkdtemp` 建暂存目录、写标记、记录到变量，这三步之间如果收到信号，会留下一个没有标记、谁都不会删的暂存目录。upgrade 和 `install_locked` 各有一处，现在也放进 `signals_deferred()`，而且移到 `try` 内，由 `finally` 清理。
   - 暂存前缀和标记（`INSTALL_STAGE`/`INSTALL_MARK`、`SETUP_STAGE`）移到 `environment.py`，供 upgrade 和 cleanup 共用；`_marked` 改为公开的 `marked(path, mark)`。

### 2. `alphaavatar cleanup`

- **代码位置**：`tools/cleanup/cleanup.py` 中，`survey()` 只读；`cleanup()` 在 `.install.lock` 内重新 `survey()`，再按结果删除。CLI `cli/commands/cleanup.py` 只负责解析参数和输出。`--dry-run` 只调用 `survey()`，不取锁，也不写入。
- **识别**：
  - env：有 setup 标记，`plan.json` 可读，其中的 base 是合法 build ID，目录名等于按 setup 方式算出的 plan ID 前 16 位；
  - 构建：manifest 里的 id 等于目录名，且有 `catalog.json`；
  - 暂存：带标记的 `.setup-*` 或 `.install-*`。
- **保留**（并给出原因）：
  - current 指向的 env 及其基础包，或 current 直接指向的基础包；
  - 运行本命令的构建和 env（`installation.base`、`sys.prefix`）；
  - 所有保留 env 所依赖的基础包；
  - 应用 home 及其缓存所在的目录，或包含它们的目录；
  - 无法判断的：链接、文件、无标记、`plan.json` 缺失/不可读/越界/与目录名不符、没有 manifest 的目录。
  - 只要某个保留 env 依赖哪个基础包判断不了（`envs/` 本身是链接也算），任何基础包都不删。
- **删除**：先删 env，再删基础包。每个目录先在信号延后期间移进一个新的带标记暂存，然后删除内容，最后删标记和暂存。中断时留下的只是带标记的暂存，下一次 cleanup、setup、upgrade 或 install.sh 都会删掉它。某项删除失败就停在那里，不再继续删基础包。
- **upgrade 结尾提示**：改为「The previous version and its environment stay until `alphaavatar cleanup` removes them.」

### 3. 文档

- 新增 `docs/cli/cleanup.md`：用法、先停止 Host（安装锁只挡安装类操作）、清理范围、保留规则和原因、锁内重新检查、中断行为、示例输出、退出码。
- `docs/cli/upgrade.md`：同构建只读核对、复制件再校验、默认 bundle 与凭据在锁内读取、目录移入和记录归属同时完成、旧版本由 cleanup 删除。
- `docs/cli/README.md` 命令表、`docs/DEPLOY.md` 升级段落。
- `AGENTS.md`、`AGENTS-zh.md`：工作区表、变更路线、文档索引。

### 4. 离线测试

- `tests/upgrade/test_upgrade.py`（14 项 → 20 项），新增：
  - 同构建与更旧版本：既不调用 `mkdtemp`，也不调用 `copyfile`，事先放好的带标记暂存保持原样；SHA-256 不符时同构建和 `--check` 都拒绝；
  - 只读核对之后文件被换掉：复制件的 SHA-256 不符，拒绝；
  - 并发 Setup：拿锁前，同一构建真实跑一次 `environment.install` 加 `create_bundle(new, make_default, 凭据 after)`。目标的 plan 和 check 都记录为 `new:after`；目标拒绝 `new` 时升级失败，`current` 和 prefix 不变；
  - 信号：在 `versions/` 或 `envs/` 中，暂存目录刚建好时，或基础包、env 刚 `rename` 到位时，立刻收到 SIGTERM。每种情况结束后 prefix 都不变，`current` 仍是 A 且能运行（共 4 种）。
- `tests/upgrade_samples.py`：替身命令会记录 `UPGRADE_SECRET`；`UPGRADE_REFUSE=<bundle>` 让 check 只拒绝该 bundle。
- `tests/cleanup/test_cleanup.py`（11 项）：
  - 先删 env 再删基础包，之后当前 env 仍能运行，home 不变；
  - survey 不写入（每项的 mtime 和大小不变）；
  - 三种「保留 env 所依赖的基础包被保留」：运行本命令的 env、名称与 plan 不符、包含应用 home；
  - 无法判断的目录都保留并阻止删除基础包；
  - 暂存：带标记的删除，无标记的保留；
  - 删除被 Ctrl-C 中断：留下带标记的暂存，下一次清理掉；
  - 锁内重新检查 current：拿锁前 current 被切回 A，删的是 B 的 env；
  - 锁被占用；
  - 裸基础包，以及 `envs/` 是链接、current 缺失的情况。
- `tests/cli/test_cleanup.py`（3 项）：`--dry-run` 的输出，prefix 与 home 的 mtime 不变；真实删除后再跑一次显示 Nothing to remove；锁被占用和不在安装包内时的拒绝信息。
- `tests/cli/test_entrypoint.py`：命令列表加入 `cleanup`。
- 变异验证 38/38 被捕获：上一轮 13 项（按新代码调整），三处修复 10 项，cleanup 15 项。第一遍 36/38，剩下的两项是「暂存目录创建时不延后信号」，补上 mkdtemp 的信号测试后被捕获。脚本和日志在会话临时目录 `mutants/run4.py`、`run4.log`、`run4b.log`。

### 5. 真实构建复验（第四轮）

clone 取 `122128b8`，套用工作区改动（不含日志），只把 16 个 `version.py` 改为 0.6.9，逐文件比对与工作区一致。三份构建（B、C 的构造同第三轮）：

| 构建 | build ID |
|---|---|
| A | `0.6.9-62c87e3d33de` |
| B | `0.6.9-f3ffa11c18dd` |
| C | `0.6.9-924bc15336f1`，router 多一个 bundle 里没有的必填项，不能加载任何 bundle |

每个包都含 `tools/cleanup/` 和 `cli/commands/cleanup.py`。运行环境与第三轮相同：隔离目录，`env -i`，没有任何凭据。依次执行：

1. **准备**：`install.sh` 安装 A，在终端里交互 setup 出 `my-avatar`（105 个包，8 个 runner，4 个占位凭据已存储）；再 `config init new`。
2. **并发 Setup，目标为 C**：`race.py` 用 current 的 Python 运行 `upgrade --file C`，只是在升级拿锁前插入一次真实的 `alphaavatar setup new`（A 自己的命令，跑完才继续）。结果：
   - setup 把默认 bundle 改成 `new`；
   - 升级拿锁后显示 `02 Plan Bundle new`，105 个包装完后报 `The new environment fails check new`，退出码 1；
   - `current` 仍是 A 的 env，A 的 `config check` 通过（8 个 runner），prefix 与基线一致；home 里只有 `settings.yaml` 变了，是那次 setup 改的。
3. **并发 Setup，目标为 B**：先 `setup my-avatar` 把默认恢复为 my-avatar，再按同样方式插入 `setup new`，然后升级到 B。用时 61 s，`Bundle new`，`Validate PASS · 8 runners`，`current` 指向 B 的 env；host 和 router 的代码来自 B；home 同样只有 `settings.yaml` 变化。
4. **同构建重复升级**：
   - 事先放一个带标记的 `versions/.install-planted`；
   - `upgrade --file B` 输出 `current already; nothing to do`；
   - `versions/` 的 mtime 不变，放好的暂存仍在：没有新建，也没有清理；
   - prefix 和 home 不变；`--check --file B` 输出 `The target is current already`。
5. **切换前中断**：升级到 C，在 `[47/105]` 时对升级进程发 SIGTERM。
   - 退出码 143，输出 `Stopped; AlphaAvatar 0.6.9-f3ffa11c18dd stays current`；
   - C 的 `versions/` 目录、新 env 和暂存都已删除；
   - 与中断前相比，prefix 只少了第 4 步放的 `.install-planted`：这次已进入真实升级，按设计清理了它；
   - `current` 仍是 B，`config check` 通过，home 不变。
6. **预览不写入**：`cleanup --dry-run` 列出 A 的 env（1,816 MB）和 A 的基础包（219 MB），合计 2,034 MB；保留 B 的 env（current）和 B 的基础包（current env 依赖它）。prefix 的 102,240 个条目，类型、大小、mtime 全部不变；home 不变。
7. **保留 env 依赖的基础包不删**：用 A 的 env 里的命令运行 `cleanup --dry-run` 和 `cleanup`。A 的 env 被保留（runs this command），A 的基础包被保留（`kept environments are over it: envs/7c360b3f811392e7 (runs this command)`），输出 `Nothing to remove`，两者都还在。
8. **清理**：用 current 运行 `cleanup`，先删 A 的 env，再删 A 的基础包，`Freed 2,034 MB`；prefix 只剩 B（1.9 G），home 不变；再运行一次输出 `Nothing to remove`。
9. **清理后当前环境仍可启动**：
   - `--version`、`config check`（new 和 my-avatar 都是 8 个 runner）通过，`doctor --no-metrics` 9 passed、6 skipped，env 里 105 个发行版；
   - `alphaavatar start`：第一次报 `OSError errno=98`，因为本机 8081 端口被用户自己从源码运行的 Host（`.venv/bin/alphaavatar start examples/agent_configs/roles/demo.yaml`）占着，未触碰它；
   - 改用 `host.health.port=0` 再启动：health 起在空闲端口，8 个推理 runner 中 VAD、Qwen3 0.6B 寻址、Smart Turn 下载模型后就绪（模型缓存 783 MB）；第 4 个 Memory 向量库用 OpenAI embedding 探测维度时，占位 key 返回 401，Host 停止。用真实凭据启动和通话由用户验收。
10. **裸基础包**：只装 A 的基础包，升级到 B，`cleanup --dry-run` 显示可删 A 的基础包（218 MB），`cleanup` 删除后只剩 B，`--version` 正常。

完整输出在会话临时目录 `upgrade/accept4/round4.log`，race 脚本是 `accept4/race.py`，启动日志是 `accept4/start2.err`。

### 6. 检查

- `ruff check .`、`ruff format --check .`、`git diff --check`、`uv lock --check`、`check_workspace.py`：通过。
- 离线全量测试：与三份构建同时运行时，1 failed / 777 passed。失败的是 Router 的 `test_speech_transcription.py::test_each_wait_between_a_transcript_and_its_turns_decision_is_traced_as_a_span[assessment-failed]`，span 实测 199.91 ms，断言要求不少于 200 ms。本轮没有改动 Router；单独重跑 5 次都通过。之后单独重跑全量：778 passed（305 s）。

### 7. 未做与待定

- 实际 LiveKit 通话由用户验收。
- cleanup 不检测仍在运行的 Host 进程，只在文档和预览的 Next 里要求先停止。
- 发现但未修改：
  - `install.sh` 有同类窗口：`mv -T` 把目录移到 `versions/<id>` 之后才 `fresh=`，期间收到信号会留下新目录；
  - setup、upgrade 和 install.sh 清理旧暂存时直接 `rmtree` / `rm -rf`，中途被打断可能先删掉标记，留下无人清理的残余；
  - 上面那个 Router 计时断言在有负载时偶发失败，它比较的是两条记录各自的时间。
