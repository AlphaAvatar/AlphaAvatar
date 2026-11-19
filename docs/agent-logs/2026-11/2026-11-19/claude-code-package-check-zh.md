# AlphaAvatar v0.6.9 真实安装包隔离复验 — Claude Code 日志

- 分支：`dev/v0.6.9`；日期为 CST。
- 依据：用户 2026-11-19 的任务，即对 `0f564502` 构建真实 Linux 安装包，在隔离环境中复验安装、首次配置、凭据规则、升级与清理。Doctor 优化留到下一批。
- 范围：不调用计费服务，不连接真实 LiveKit，不发布 release。代码改动留在工作区，由用户审查后提交。

## 批次总览

| 批次 | 内容 | 日期 | 基线 HEAD | 提交 | 状态 |
|---|---|---|---|---|---|
| 安装包复验 | 4 个真实包在干净根文件系统中安装、配置、升级、清理；修复 `config check` 把 MCP、DeepResearch 说成 setup 不提供 | 2026-11-19 | `0f564502` | — | 待审查 |

## 1. 验收对象

**`0f564502` 的 CI**（push 触发，两条均 success）：
- Quality [44466785895](https://github.com/AlphaAvatar/AlphaAvatar/actions/runs/44466785895)：`lint`、`build`、`install` 三个 job 通过；`install` 中全量测试 821 passed、41 warnings，用时 535.59 s。
- Linux package [44466785847](https://github.com/AlphaAvatar/AlphaAvatar/actions/runs/44466785847)：
  - `build` 在 manylinux_2_28 中构建 `alphaavatar-0.6.8-0f564502841e`，构件 zip 的 SHA-256 为 `9ed63645…6e`；
  - `verify` 在 ubuntu:24.04 容器中先确认 python3、python、node、gcc、cc、c++ 都不存在，再校验 SHA256SUMS，安装后跑 `config init`、仅基础包的 `config check`、`setup reference --artifacts`（105 个包）和 `config check`（8 个 runner，`silero x2`）。

**本地构建**：
- 构建在仓库的临时 clone 里进行，不在本仓库。clone 的 `0f564502` 与仓库 HEAD 一致，工作区干净。
- 只把 16 个 `version.py` 从 0.6.8 改为 0.6.9，在 clone 内提交为 A，其余构建基于 A。
- 构建条件：uv 0.10.0，`packaging/linux/build.sh --max-glibc 2.32`；主机为 Alibaba Cloud Linux 3，内核 5.10.134，glibc 2.32，16 核。每个包约 63 s。各包均为基础包 glibc >= 2.17，12 个 wheel，glibc >= 2.32。

| 包 | clone 提交 | build ID | SHA-256 | 字节 | 与 A 的差别 |
|---|---|---|---|---|---|
| A | `65f0ea1b` | `0.6.9-65f0ea1ba3e1` | `7fd43ee6…6e506c` | 65865923 | —（`0f564502` + 版本号） |
| B | `b57fd32a` | `0.6.9-b57fd32ae234` | `103ded95…ee6fd7` | 65866724 | host `version.py`、router `__init__.py` 各多一行注释 |
| C | `35066bae` | `0.6.9-35066bae7141` | `3c212b46…27d8c9` | 65867469 | router 配置多一个 bundle 没有的必填项 `acceptance_marker` |
| D | `eb1856f5` | `0.6.9-eb1856f50c08` | `2b2fbd4f…e8d139` | 65866942 | B，host `version.py` 再多一行 |
| E | `e8ee9846` | `0.6.9-e8ee98460ff9` | `049e1c35…499781` | 65866915 | A + 本轮工作区修复（第 6 节） |

## 2. 隔离环境

- **干净根文件系统**：
  - 镜像为 `ubuntu-base-24.04.5-base-amd64.tar.gz`，SHA-256 `e77b6f10…0c86`，与 cdimage.ubuntu.com 的 SHA256SUMS 一致；glibc 2.39。
  - 用 bubblewrap 0.4.0 运行：根文件系统只读；独立的 user、PID、UTS、IPC 命名空间；用户 tester（uid 1000）。
  - 环境变量用 `env -i` 清空，只留 HOME、PATH（`~/.local/bin:/usr/bin:/bin`）、LANG、TERM 和各步骤自己加的变量。
  - 只挂载验收目录和包目录（路径与主机相同），`/tmp`、`/run` 为 tmpfs，网络与主机共享。仓库和用户的 `~/.cache` 都不挂载。
- **确认缺席**：python、python3、node、npm、uv、pip、pip3、gcc、cc、c++、make、ld、curl、wget；`/usr/lib`、`/usr/local/lib` 下也没有 python 或 node。所以安装后的 CLI 不可能用到源码目录、开发 venv 或 `uv run`。
- **安装位置**：安装用默认位置，但都在隔离的 HOME 里：`~/.local/bin`、`~/.local/lib/alphaavatar`、`~/.local/share/alphaavatar`。
- **未触及**：用户自己的 Host、配置、凭据、workspace 和缓存都没有挂进来。8081 端口未用到，本轮没有运行 `start`。
- **哪部分不是干净机器**：内核与网络用的是主机的，根文件系统和用户空间是干净的。驱动验收的脚本（pty 录制、文件哈希、JSON 解析）在主机上运行，被测的每条 `alphaavatar` 命令都在干净根文件系统中运行。

## 3. 安装与首次配置（A）

| 步骤 | 结果 |
|---|---|
| `install.sh --file A`，SHA256SUMS 全部 OK | 0，3 s；`~/.local/bin/alphaavatar -> current -> versions/0.6.9-65f0ea1ba3e1` |
| 在 `/`、`/tmp`、运行目录、HOME 下执行 `command -v`、`--version`、`--help` | 都找到 `~/.local/bin/alphaavatar`，输出 `AlphaAvatar 0.6.9`；启动器用包内 Python，带 `-I` |
| 仅基础包：`config init reference`，`config check` | 0；2，逐个设置写出缺失的插件和 setup 会装的包 |
| 交互式 `setup`（pty 录制，全部默认：语音、视觉、本机模型、LanceDB、OpenAI；bundle `my-avatar`；4 个虚构凭据，存储确认 y） | 0，56 s；105 个包，514 MB，Validate PASS · 8 runners；`credentials-<id>.env` 权限 0600，存的正是 OPENAI_API_KEY 和 3 个 LIVEKIT_*；`default_bundle: my-avatar` |
| `config check` | 0，8 个 runner |
| bundle 加上 MCP 两个 server 和 `voice.tts.api_key_env: ${oc.env:TTS_KEY_NAME,MODEL_AUTH}` 后 `config check` | 2，`tools.mcp.plugin` 缺包，提示“this release's setup does not offer it”（第 6 节） |
| `setup my-avatar` | 0，54 s；114 个包，装上 MCP，Validate PASS · 9 runners，新环境成为 current |
| `doctor --no-metrics` | 0：9 PASS（system.platform、python.version、packages.alphaavatar、config.load、config.runners、packages.capabilities、paths.home、paths.cache、paths.workspace），6 SKIP（session.start、models.runners、services.external、session.scenarios、session.cleanup：`--no-metrics` 或无外部服务授权；devices.media：Doctor 不开设备），0 FAIL |

MCP 写法：
- `docs` 的 Authorization 为 `Bearer <MCP_PAT>`；
- `code` 的 Authorization 为 `Bearer ${oc.env:GITHUB_PAT}`，另有 `X-Region: ${oc.env:ACCEPT_REGION}`。`X-Region` 没有默认值，所以 `ACCEPT_REGION` 缺失时插值就会失败。

## 4. 凭据规则在包中的行为

所有值都是虚构的，形如 `fictional-<来源>-<用途>-0042`，来源由值本身标明。

**包内加载探针**：
- 由安装环境自己的 Python `-I` 运行，代码路径确认来自 `versions/0.6.9-65f0ea1ba3e1/python/…/site-packages`。
- 它调用 `config check` 自己的加载函数 `alphaavatar.host.cli.commands.config._load`，再用 Host 的 HostLog（与 `start` 的创建方式相同）记录一行引用所有已加载值的日志。
- 只打印来源标签，不打印值。

| 情况（进程 / .env / setup 已存） | 结果 |
|---|---|
| 进程都有有效值 | 全部取进程值 |
| 进程 OPENAI 为空、MODEL_AUTH 为 Tab、MCP_PAT 为空、GITHUB_PAT 为空白，`.env` 都有值；LIVEKIT_API_KEY 为空白且 `.env` 没有 | 前四个取 `.env`，LIVEKIT_API_KEY 取已存值 |
| `.env` 中 `OPENAI_API_KEY=` 为空，进程未设；LIVEKIT_URL 进程为空，`.env` 为引号包住的空白 | 都取已存值 |
| 普通变量在进程中显式为空：ACCEPT_REGION、CUDA_VISIBLE_DEVICES、ALPHAAVATAR_MODEL_OFFLINE，`.env` 里有值 | 都保持空；`X-Region` 为空 |
| `TTS_KEY_NAME=CHOSEN_AUTH`，CHOSEN_AUTH 进程为空、`.env` 有值 | `api_key_env` 为 CHOSEN_AUTH，取 `.env` 值，列入隐藏名单；TTS_KEY_NAME 不列入 |
| 未设 TTS_KEY_NAME | 默认值 MODEL_AUTH 列入隐藏名单 |
| `.env`：`OPENAI_API_KEY=${SHARED_KEY:-…default…}`，后一行 `SHARED_KEY=…later…`；进程 OPENAI 为空 | 取 default，只解析一次 |
| `PYTHON_DOTENV_DISABLED=1`，`.env` 有 OPENAI | 不读文件，取已存值 |
| MCP_PAT 进程为空白，`.env`、已存值都没有 | 加载失败，错误写出变量名 `MCP_PAT` |
| 日志（每个情况） | 声明的凭据（MODEL_AUTH、CHOSEN_AUTH、MCP_PAT、GITHUB_PAT）和名字表明是密钥的（OPENAI_API_KEY、LIVEKIT_API_KEY/SECRET）都显示为 `[redacted]`；地址、区域、错误类型和位置都保留 |

日志中可见的值是 LIVEKIT_URL、ACCEPT_REGION、TTS_KEY_NAME，以及只在 `.env` 内部使用的 SHARED_KEY，都符合现有规则：
- LIVEKIT_URL 不是密钥，setup 以明文方式询问它，名字也不匹配密钥规则；
- 其余三个是普通变量。

Host 日志记录异常时只写类型和位置（`error: RuntimeError at …`），不写异常消息。

**通过真实 CLI 观察**：

`setup my-avatar` 离线检查 LiveKit URL。已存值是合法的 `wss://`，`.env` 是远程的 `ws://`（不合法），所以检查通过与否说明值来自哪里：

| 进程 LIVEKIT_URL | `.env` | 结果 |
|---|---|---|
| 合法 `wss://` | `ws://` | 0，进程值生效 |
| 空 | `ws://` | 1，`Remote LiveKit connections require TLS`，不引用值；说明 `.env` 先于已存值 |
| 空白 | `ws://` | 1，同上 |
| 未设 | `LIVEKIT_URL=`（空） | 0，取已存值 |

四次 setup 前后 home 的哈希不变，不存任何东西。

`config check`：
- MCP_PAT、GITHUB_PAT、ACCEPT_REGION 在进程中为空，值在 `.env` 中：0，9 个 runner，`mcp default (2 servers)`；
- MCP_PAT 缺失：2，`fields: tools.mcp`；
- ACCEPT_REGION 缺失：2，`ValueError at loader:211`。

`ALPHAAVATAR_HOME`（第二个 home `home2` 里只有 bundle `other`），从 `config check --json` 的 `home` 读：

| 情况 | home |
|---|---|
| 进程未设，`.env` 指向 home2 | home2 |
| 进程为空、为空白 | home2 |
| 进程设为默认 home | 默认 home |
| `.env` 中为空 | 默认 home |
| `ALPHAAVATAR_HOME=${ACCEPT_ROOT:-home2}` 后一行 `ACCEPT_ROOT=later-home` | home2，只解析一次 |
| `PYTHON_DOTENV_DISABLED=1` | 默认 home |
| 相对路径 | 2，`ValueError at absolute_root` |

**泄漏扫描**：
- 本轮全部 97 份 CLI 输出与录制中（含第 6 节的复验），虚构值只出现在交互式 setup 录制里，就是输入时回显的 LIVEKIT_URL（按设计明文询问）。
- home 中，除了已存凭据文件，没有任何文件含有虚构值。

## 5. 升级与清理

升级命令都在运行目录下执行。已存的只有 OPENAI 和 LIVEKIT_*；MCP_PAT、MODEL_AUTH、GITHUB_PAT 在进程中为空，值只在 `.env.accept` 里；ACCEPT_REGION 只在文件里。目标包的规划和校验在 `/` 下运行，所以只有拿到快照才能成功。

| 步骤 | 结果 |
|---|---|
| `--file B --sha256 <错>` | 1，说明 SHA-256 不符；prefix、home 不变 |
| A → C，相对 `ENV_FILE=.env.accept` | 1，62 s；规划通过（从 `/` 拿到 ACCEPT_REGION）；Validate 失败于 `fields: acceptance_marker`，说明已越过 MCP 校验。`current` 保持 A 的环境；C 的环境和基础包已删；prefix、home 不变；A 的 `config check` 为 0（9 runners），`doctor --no-metrics` 9 passed · 6 skipped |
| A → B，相对 `.env.accept`；规划完成后 5 s 时改写该文件（清空 MCP_PAT、删掉 ACCEPT_REGION） | 0，58 s；114 个包，Validate PASS · 9 runners；`current` 为 B 的新环境，host 与 router 都含 B 的那一行，基础包为 B；home 不变 |
| 对照：B 自己在 `/` 下用同样的变量 `config check` | 2，`ValueError at loader:211`：重新读文件就找不到这些值 |
| `cleanup --dry-run` | 0；列出 A 的两个环境和 A 的基础包（3,856 MB）；prefix 145,769 项的类型、大小、修改时间都不变；home 不变 |
| `cleanup` | 0；删掉这 3 项，保留 current 和它的基础包 B；home 不变（含人为放入的用户数据和 1 MiB 模型缓存文件）；`config check` 为 0 |
| B → D，绝对路径 `.env.accept2`；规划后改写 | 0，59 s；Validate PASS；`current` 为 D，host 含 B、D 两行，router 含 B 那一行 |
| 对照：D 自己读改写后的文件 `config check` | 2，`ValueError`：校验用的不是重新读取的文件 |
| 再次 `upgrade --file D`，以及 `--check` | 0，“current already; nothing to do”，`versions/` 未写，prefix、home 不变；`--check` 说明目标已是当前版本 |
| `envs/` 里放一个没有 setup 标记的目录 `stranger`，`cleanup --dry-run`，再 `cleanup` | 只删 B 的环境；`stranger` 保留，“no setup mark”；B 的基础包因“the base of envs/stranger cannot be told”而保留 |
| 手动移走 `stranger` 后再 `cleanup` | 删掉 B 的基础包；剩下 D 的环境和基础包；home 不变；`config check my-avatar` 为 0，`doctor --no-metrics` 9 passed · 6 skipped |

## 6. 发现并修复：`config check` 把 MCP 和 DeepResearch 说成 setup 不提供

**现象**：
- 在安装包里，bundle 启用 MCP 后，`config check` 写 `tools.mcp.plugin: no installed package provides tools.mcp 'default'; this release's \`alphaavatar setup\` does not offer it`。
- 而包的 catalog 写有 `tools.mcp: default → alpha-avatar-plugins-mcp`，紧接着 `alphaavatar setup my-avatar` 就把它装上了。DeepResearch 同理。
- 只有安装包里会出现这条提示；源码检出不提示 setup。

**原因**：
- `host/configs/capabilities.py` 的 `offered()` 只保留交互式 setup 的选项能装到的包（`requirements_offered()`）。这个过滤来自第 1 项第三轮（`eb2404a0`），当时只有交互式 setup。
- 之后有了 `setup <bundle>`，它按 catalog 的 `plugins` 表规划 bundle 的选择，而这条提示没有跟着改。
- catalog.py 的文档写明 `plugins` 表就是“config check and Doctor tell a person setup can install”；`docs/DEPLOY.md` 也写 config check 和 doctor 会说明本版 setup 是否安装它。

**修改**：
- `offered()` 直接返回运行中安装包 catalog 的 `plugins` 表，与 `setup <bundle>` 用的是同一张表。提示的措辞不变，CI 的 grep 仍然匹配。
- `tests/configs/test_capabilities.py` 里原先断言 DeepResearch “不提供”，现在改为：
  - 断言它显示“installs it (alpha-avatar-plugins-deepresearch)”；
  - catalog 里没有的 router `x` 仍显示“does not offer it”；
  - 用同一张表调用 `bundle_requirements`，确认 DeepResearch 的选择被规划、没有列为无人安装。
- 这条测试在 HEAD 的 `capabilities.py` 上失败，改后通过。
- 文档已经描述修复后的行为，没有改文档。

**包级复验**（E = A + 修复）：
- 在两个新的 HOME 中分别只装 A、E 的基础包，同样的 `config check tools.mcp.enabled=true tools.mcp.plugin=default tools.deepresearch.plugin=default tools.rag.plugin=default`：
  - A：MCP、DeepResearch、RAG 三行都写“does not offer it”；
  - E：MCP、DeepResearch 写“`alphaavatar setup` installs it (alpha-avatar-plugins-mcp / -deepresearch)”，不在 catalog 的 RAG 仍写“does not offer it”。
- 主安装从 D 升级到 E：0，59 s，Validate PASS · 9 runners；`config check` 为 0，`doctor --no-metrics` 9 passed · 6 skipped；`cleanup` 删掉 D，home 不变。之后移除了两个基础包安装。

## 7. 验证

| 类别 | 结果 |
|---|---|
| 源码测试（工作区） | `test_capabilities.py` 2 passed；改动后的测试在 HEAD 的代码上失败，在 `offered()` 返回空表的变异上也失败；离线全量 821 passed（312 s） |
| 仓库检查 | `ruff check`、`ruff format --check`（789 个文件）、`git diff --check`、`uv lock --check`、`check_workspace.py`（16 个成员）均通过 |
| `0f564502` 的 CI | Quality、Linux package 均 success（第 1 节） |
| 真实安装包 | A、B、C、D、E 在干净根文件系统中按第 3–6 节验证 |
| 本轮修复所在 SHA 的 CI | 未提交，没有 CI |

## 8. 发现未改

- MCP 的 `<NAME>` 缺失时，`config check` 只显示 `fields: tools.mcp`，不写变量名。解析器自己的错误里有变量名，但 config check 只列字段。`docs/cli/config.md` 写的是“what reads it refuses to start and names the variable”。源码检出同样如此，不是包级问题。
- `${oc.env:NAME}` 缺失时只显示 `ValueError at loader:211`，已在 README 日志中记录。
- `config check` 的提示写的是 `alphaavatar setup`；对 MCP 这类交互式 setup 不会选中的插件，实际要运行的是 `alphaavatar setup <bundle>`。措辞没改，以免影响 CI 的 grep。

## 9. 未验证

- 真实服务：OpenAI、LiveKit 通话、模型下载、`start`、Doctor 运行时测试都没有运行，凭据都是占位值。LiveKit 通话由用户验收。
- glibc 2.28 的下限没有实测，只实测了 2.39（干净根）。
- 干净根用的是主机的内核和网络。

## 10. 证据索引

以下都在会话临时目录 `pkgcheck/`（不在仓库）中：
- 构建：`build.sh`、`build.out`、`build-{A,B,C,D,E}.log`，包在 `out-{A..E}`，clone 在 `src`；
- 环境：`env.sh`、`root/`；
- 用例：`cases.sh`、`steps.sh`、`acc/tools/probe.py`；
- 输出：`acc/out/`，其中 `probes.txt`、`cli.txt`、`home.txt`、`step-*.txt`、`doctor-A.json`；录制在 `acc/rec/`；
- CI 日志：`ci/`。
- 验收结束后删除了安装树（`acc/user/.local/lib/alphaavatar`，2.0 GB）；保留包、clone、输出和 home（约 680 MB）。
