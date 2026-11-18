# AlphaAvatar v0.6.9 收尾 — Claude Code 日志

- 分支：`dev/v0.6.9`；日期为 CST。
- 依据：用户 2026-11-18 起的逐轮审查要求，从 README 批次（`174d1632`）之后开始；每轮的基线是用户上一次的提交。README 核对和 `.env` 加载移到 Host 见 [README 日志](claude-code-readme-zh.md)。

## 批次总览

| 批次 | 内容 | 日期 | 基线 HEAD | 提交 | 状态 |
|---|---|---|---|---|---|
| 收尾 | cleanup 三处保护缺口；凭据空值统一规则；Router 两项计时测试的测量起点；RAG 能力描述 | 2026-11-18 | `174d1632` | `cde30675`（用户提交） | 已提交 |
| 收尾二 | `.env` 凭据与普通变量分开、插值恢复进程值优先；RAG 缺失密钥检查；Router 偶发定位与测试同步 | 2026-11-18 | `cde30675` | `0e0c7b3a`（用户提交） | 已提交 |
| 收尾三 | 凭据按实际声明补齐，删除按名称猜测；日志脱敏覆盖配置声明的密钥和自建服务器密钥 | 2026-11-18 | `0e0c7b3a` | `a6f97174`（用户提交） | 已提交 |
| 收尾四 | `.env` 只解析一次；upgrade 目标使用父命令的文件快照；MCP 的 `${oc.env:NAME}` 按凭据补齐和脱敏 | 2026-11-19 | `a6f97174` | 未提交（用户提交） | 待审查 |

## 收尾（基线 `174d1632`）

依据：用户 2026-11-18 的审查要求。`.env` 移到 Host、`python-dotenv` 迁移、删 RAG `monologue` 和 Core `livekit` extra 已被接受。改动全部留在工作区，未暂存、未提交；实际 LiveKit 通话由用户验收。

### 1. cleanup 的三处保护缺口

- **`.env` 指定的 home**：CLI 先调 `load_env_file()`，再用 `application_paths()` 确定保护目录，与 `start` 的取值顺序一致。环境里 `ALPHAAVATAR_HOME` 未设或为空时，取 `ENV_FILE` 文件里的值。
- **暂存目录**：`survey()` 里新增 `admit()`，env、构建和两类暂存都由它判定去留，预览和锁内删除走同一处。原因顺序不变：current、非安装器所建、被保留 env 依赖，然后是运行中或保护目录，最后是元数据问题。
- **校验失败的计划**：`_plan()` 在计划哈希与目录名不符时，不再返回其中记录的 base。该 env 保留，其依赖记为无法确定，所有基础包因此保留并写明原因。
- 先删 env、再删无引用基础包的顺序，以及安装锁和停机维护约定，都不变。

### 2. 凭据空值统一规则

- **规则**：`alphaavatar.agents.utils.credential(name, environ)` 在值未设、为空或全是空白时返回 None，否则原样返回。
  - Host 的 `fill_credentials()` 用同一规则逐层补齐：环境里已有有效值的保留，无效的让给下一层；下一层的空值不写入。
  - `load_env_file()`（改用 `dotenv_values`）、`load_credentials()` 和 `upgrade` 在锁内的合并都调用它。
- **读取方**：以下读取方改用同一判断，缺失时报出变量名、不打印值：
  - langchain 任务模型与 embedding、Responses 客户端（报错补上变量名）；
  - OpenAI 与 Voice.ai TTS（缺失时报变量名，原先是通用报错）、两种 STT；
  - Tavily、RAG、MCP `<NAME>` 占位符、Qdrant、LiveKit（两处）；
  - setup 判断“已设置”的地方。
- `write_credentials()` 拒绝全空白值。
- **开关和路径**：规则只决定由哪一层供值，不改它们的含义。仓库里读取的开关和路径都把空值当作未设。
- **有意为之的差异**：`.env` 内 `${NAME}` 插值，当文件和环境都定义了 NAME 时，现在取文件里的值。这是 `dotenv_values` 的行为；原先的 `load_dotenv` 取环境里的值。
- **文档**：`.env.template` 开头说明、`docs/cli/config.md`「Credentials」、`setup.md`、`upgrade.md`、`DEPLOY.md`。

### 3. Router 两项计时测试

原先两项测试都从 HOLD 的 trace 记录时刻起算，而计时器早已开始；HOLD 记录一晚，测得的等待就偏短。现在改为：

- **测量起点**：fixture 记录 Turn Taking 新建的每个 `TranscriptWait`，`waited()` 从它的 deadline 减去硬截止推出起点。第二项测试记录 `_hold` 实际等待的 deadline，断言等待持续到 deadline，并且 deadline 减去 SPAN 落在两个真实事件之间：完成判断是段关闭之后、首个 HOLD 记录之前；寻址是评估结束之后、hold span 开始之前。
- **日志开销**：`held_late()` 把 HOLD 的 trace 推迟 20 ms，同时阻塞事件循环；两项测试各在推迟与不推迟两种情况下运行。
- 期限内终稿采用、超期终稿隔离、明确 HOLD 三项回归保留，生产代码未改。

### 4. RAG 能力描述

`service.py` 改为 “Indexing changes this session's index”。

### 5. 验证

- 定向测试：
  - Host 的 configs、cli、upgrade、cleanup、setup，加 Voice、Provider：306 passed（改读取方之后）。
  - 新增回归：
    - cleanup：异常计划两种、暂存目录两种、CLI `.env` home 两种；
    - 凭据：分层表 1 项、读取方 2 项、空白值拒存 1 项；
    - upgrade 3 项；setup 1 处；
    - Router 两项测试各 2 种推迟。
- 变异测试：22 个全部被抓到（`mutants/run5.py`）。
  - cleanup 5 个、凭据 13 个、Router 生产代码 2 个；
  - 另有 2 个把测试改回从 HOLD 起算，在推迟 20 ms 时失败。
  - 第一轮 setup 的“已设置”判断（K9）没被抓到，给 setup 测试补上空白服务器密钥后抓到。
- 仓库检查：`ruff check`、`ruff format --check`、`git diff --check`、`uv lock --check`、`check_workspace.py` 通过，改动文档的链接 0 处问题。
- 离线全量测试：795 passed（304 s），无失败。

### 6. 发现未改

- `config check` 不检查会话传输凭据，LiveKit 凭据缺失要到 `start`，或者 Linux 包里的 `setup <bundle>` 才报。
- cleanup 不读 bundle，YAML 里的 `application.home` 不影响它的保护目录；只有从别处的 YAML 文件启动时，这才可能与 `start` 不同。

## 收尾二（基线 `cde30675`）

上一轮的 cleanup 三处保护、Router 按真实 deadline 计时、RAG 能力描述已接受。本轮四项。

### 1. `.env`：凭据与普通变量分开

- **更正**：上一轮“开关和路径都把空值当作未设，规则不改变行为”的判断不成立。进程里 `CUDA_VISIBLE_DEVICES=""` 表示不用 GPU，却被文件里的 `0` 覆盖，`gpu_available()` 因此可能从 False 变成 True。
- **普通变量**：`load_env_file()` 改回用 python-dotenv 的 `load_dotenv` 加载。进程已设置的变量保留，空值也保留；`${NAME}` 先读进程值。
- **凭据和 `ALPHAAVATAR_*` 自有变量**：空值或全空白算未设，依次由文件、setup 存的值补上。
  - 实现：加载期间先把这类空值移出环境，让文件值补上；加载后删去文件写入的空值，再放回进程原有的空值。
- **怎样算凭据**：按名字判断。以下划线分隔的词里含 `KEY`、`APIKEY`、`SECRET`、`TOKEN`、`PASSWORD`、`PAT` 或 `URL` 的变量算凭据。
  - 只能按名字：加载 `.env` 时还没读配置，插件又在子进程里按需读取，加载器无从知道配置会读哪些变量。
  - 自建服务器的密钥（`ALPHAAVATAR_SERVER_KEY_*`）和 `ALPHAAVATAR_HOME` 属于自有变量。
  - 自定义 `api_key_env` 名字符合即按凭据处理，例如 `MY_PROVIDER_API_KEY`。不符合的按普通变量处理：进程里设成空值会挡住文件值，读取方按变量名报缺失。
- **未改的部分**：setup 存的凭据和 `upgrade` 锁内的合并照旧用 `fill_credentials()`；setup 只存凭据。
- **文档**：`.env.template` 开头说明、`docs/cli/config.md`「Credentials」、`DEPLOY.md`、RAG README。

### 2. 插值恢复为进程值优先

- 上一轮改用 `dotenv_values()` 后，`${NAME}` 先读文件值。
- 随第 1 项回到 `load_dotenv` 后，`${NAME}` 先读进程值。
- 进程里为空白的凭据在加载期间不在环境里，所以引用读到的是它最终加载成的值。

### 3. RAG 缺失密钥

- **检查位置**：`_load()` 是 query 和 indexing 共用的惰性加载入口，现在一开始就检查密钥。
- **缺失时**：报 `OPENAI_API_KEY is required for RAG`，不导入依赖，也不建模型和 embedding 回调。
- **惰性不变**：构造工具时仍不加载。失败的加载任务会被缓存，再次调用报同样的错。

### 4. Router 偶发

**定位**：用临时 probe 记录每次决策时的 loop 时间和完成判断的 deadline，脚本在 scratch，不入库。

- 正常运行时，决策只比 deadline 早 49 ms；日志推迟 20 ms 的对照下只早 29 ms。
- 200 ms 的预算有 150 ms 被吃掉。deadline 在输入关闭、开始等转写时就已设下；此后 fake model 每读一次 `capabilities` 都同步阻塞 50 ms，一次评估要读三次。
- 在决策前注入 60 ms 停顿就复现了同一失败：决策晚于 deadline 12 ms，直接 `commit`（`uncertainty_timeout`），没有 hold，测试等满 10 s 仍没有 `input.hold`。

**调整**（只改测试，生产代码未动）：

- fake model 的延迟移到 `supports()`，每次评估开始时阻塞一次。
- 测试先等到“输入开始等转写”的 HOLD 决策出现，再发终稿，固定等待路径。
- SPAN 从 0.2 s 改为 0.5 s，margin 变为 449/429 ms。
- 先等 commit，再断言 hold。失败时列出每个决策的动作、原因和距段关闭的毫秒数，不再空等 10 s。

**复验**：

- 注入 60 ms、300 ms 停顿都通过；注入 600 ms 时在 0.8 s 内失败，并报出 `('commit', 'uncertainty_timeout', 701)`。
- 16 个 CPU 全部占满时，转写测试文件连跑 8 轮全部通过。

**新增用例**：`test_words_later_than_an_uncertain_completions_wait_commit_it_unheld`。deadline 过后才到的终稿仍会被评估，然后直接 `commit`，带 `router.speech_completion_uncertain`，没有 hold。

20 ms 日志延迟对照，以及期限内终稿采用、超期终稿隔离、明确 HOLD 的回归都保留。

### 5. 验证

- **新回归**：
  - 普通变量 1 项：覆盖 CUDA 和代理的空值、同名插值、引用空白凭据、`ALPHAAVATAR_HOME`、凭据的空行。用 `cde30675` 的加载器跑，它在 CUDA、代理、插值三处失败。
  - RAG 6 项：query 和 indexing 各配空串、全空白，再加有密钥的对照。
  - Router 1 项。
- **变异测试**：14 个全部被抓到（`mutants/run6.py`）。其中 `.env` 8 个、RAG 2 个、Router 生产代码 2 个，另沿用上轮 2 个：R2 让 hold 提前结束，R4 把测试改回从 HOLD 起算。
- **仓库检查**：`ruff check`、`ruff format --check`、`git diff --check`、`uv lock --check`、`check_workspace.py` 通过，改动文档的链接 0 处问题。
- **离线全量**：803 passed（306 s），无失败；之后改了一个测试名和两处注释，受影响的 3 个测试文件重跑通过。
- **未验证**：
  - 该 SHA 的 CI 没有查看；
  - 真实安装包没有复验；
  - 没有调用计费服务；
  - LiveKit 通话由用户验收。

### 6. 发现未改

- **日志脱敏漏掉自建服务器的密钥**：Core 日志脱敏按变量名挑出要按值遮盖的环境变量（`_SECRET_KEY`：token、secret、password、api_key 等），其中不含 `ALPHAAVATAR_SERVER_KEY_*`。离线核对：同一行里 `OPENAI_API_KEY` 的值被遮，自建服务器密钥的值原样输出；后者只有在 `Authorization` 头这类模式里才被遮。
- **两个自有变量不把空值当作未设**：`ALPHAAVATAR_MAX_SESSION_SECONDS` 和 `ALPHAAVATAR_SEMANTIC_ADDRESSING_THREADS` 的读取方直接 `int()`。各层都没有有效值、只剩空值时会报解析错误，而不是按未设处理。这是原有行为，本轮加载规则没有改变它。

## 收尾三（基线 `0e0c7b3a`）

上一轮 RAG 在共享惰性加载入口检查凭据、Router 的延迟注入与等待路径同步都已接受。本轮两项。

### 1. 凭据按实际声明补齐

- **问题**（审查复现）：上一轮按名称里的词和 `ALPHAAVATAR_*` 前缀判断凭据。
  - 漏判：`api_key_env: MODEL_AUTH` 在进程里为空时，挡住了 `.env` 的值；Setup 存有旧值时，又越过 `.env` 取了旧值。
  - 误判：进程里 `ALPHAAVATAR_MODEL_OFFLINE=""`，被 `.env` 的 `1` 覆盖，离线开关从 False 变成 True。
- **现在的流程**：
  1. `load_env_file()` 按 python-dotenv 原样加载，进程已设置的值（含空值）保留，`${NAME}` 先读进程。它返回文件里的值，留给后面补齐凭据。
     - `ALPHAAVATAR_HOME` 保留已确认的规则：进程里为空或空白时取文件值，用来选 home。
  2. `load_credentials()` 读已存凭据后，补齐两类名字，顺序都是有效进程值 → `.env` → 已存值：
     - 组件在配置不指定时读的默认变量名，即 `DEFAULT_CREDENTIALS`；
     - Setup 存过的名字。
  3. 配置组装后、校验前，`load_application()`/`load_selections()` 拿到 `load_environment()` 返回的读取结果（`settings`），按配置里实际声明的名字补齐，顺序相同：
     - 每个 `api_key_env`，名字不限；
     - MCP servers 里的 `<NAME>` 占位符。
     - 补齐发生在占位符解析之前。
- **默认变量名**：`DEFAULT_CREDENTIALS` 列出组件在配置未指定时读取的确切名字，不按关键词匹配。新增测试逐个构造读取方，不传变量名，用空环境验证它报出的变量名都在这份清单里。
- **调用点**：start/dev、`config check`、Doctor、setup（已有 bundle 的规划，以及新 bundle 的凭据询问前）都传入 `settings`；`upgrade` 锁内对目标环境按“默认 + 已存”名字、`.env` → 已存值的顺序补齐，目标构建加载自己的 bundle 时再按声明补齐。
- **插值**：`.env` 里的 `${NAME}` 回到 python-dotenv 的规则：先读进程值，进程里的空值也读进来。所以引用一个进程里为空的凭据会读到空值；上一轮这种引用读的是文件值。被引用的凭据本身照常补齐。
- **文档**：`.env.template` 开头说明、`docs/cli/config.md`「Credentials」、`DEPLOY.md`、`upgrade.md`，删去上一轮写进去的命名限制。

### 2. 日志脱敏

- **Core**：新增 `hide_variables(names)`。上层传入变量名，Core 只负责隐藏这些变量的值，不依赖 Agents 或 Host。
  - 名单写在 `ALPHAAVATAR_LOG_HIDDEN`（只存变量名），每个 `Redactor` 刷新时读取，所以由这个进程启动的子进程也会隐藏这些值。
- **Host**：传入两类名字：
  - 配置声明的凭据名，即 `api_key_env` 和 MCP 的 `<NAME>`；
  - 环境里所有 `ALPHAAVATAR_SERVER_KEY_*`。
  - 名字本身已经表明是凭据的（`*_API_KEY` 等）照旧由 Core 按名称识别。start 在加载配置后刷新 Host 日志的脱敏名单。
- **`config check` 的变化**：会写入 `ALPHAAVATAR_LOG_HIDDEN`，只含变量名。原有“不写任何变量”的测试改为排除这一项，并断言它只含 `MCP_DOCS_TOKEN` 这个名字、不含值。
- **两点核对**：
  - 日志客户端把异常对象作为参数时只输出 `<RuntimeError>`；`format_error` 只输出异常类型和位置。所以异常消息只有在代码自己把 `str(error)` 拼进日志正文时才会带出密钥值，测试按这种写法覆盖。
  - URL 不进名单，日志里仍保留服务器地址。

### 3. 验证

- **新回归**：
  - `MODEL_AUTH` 分层 5 种：文件值；文件先于旧的已存值；文件为空白时取已存值；进程有效值；全部缺失。同一用例验证 MCP 的 `<MCP_PAT>` 从 `.env` 补上后占位符正常解析，并验证不传 `settings` 时不补齐。
  - 普通变量表：`CUDA_VISIBLE_DEVICES`、`HTTPS_PROXY`、`ALPHAAVATAR_MODEL_OFFLINE` 的空值保留，`gpu_available()` 和 `models_offline()` 都是 False；同名插值读进程值。
  - 默认变量名清单对照各读取方的实际默认值。
  - upgrade：模块测试新增“文件先于已存值”和“默认凭据”两种；CLI 测试新增 `.env` 先于已存值。setup：`.env` 里有、环境里为空白的服务器密钥，按回车保留。
  - 脱敏：Core 测试覆盖普通文本、异常文本、结构化字段，以及子进程继承；Host 测试从加载配置一直走到 Host 日志的真实输出，确认四个虚构密钥值都没有出现，服务器地址、失败信息、异常类型和其他字段保留。
- **变异测试**：18 个全部被抓到（`mutants/run7.py`）。第一轮 upgrade CLI 不传 `.env` 值的那个变异没被抓到，补了 CLI 测试后抓到。
  - 没有测试覆盖：start 在加载配置后刷新 Host 日志脱敏名单的那一行（`run.py`）。子进程会自己读名单，不受影响。
- **仓库检查**：`ruff check`、`ruff format --check`、`git diff --check`、`uv lock --check`、`check_workspace.py` 通过，改动文档的链接 0 处问题。
- **离线全量**：814 passed（306 s），无失败；之后只改了 `.env.template` 的注释措辞。
- **未验证**：
  - 该 SHA 的 CI 没有查看；
  - 真实安装包没有复验；
  - 没有调用计费服务；
  - LiveKit 通话由用户验收。

### 4. 记录，未改

- `ALPHAAVATAR_MAX_SESSION_SECONDS`、`ALPHAAVATAR_SEMANTIC_ADDRESSING_THREADS` 遇空值报解析错误，按要求本批不处理。
- 配置里用 `${oc.env:NAME}` 引用的变量按普通变量读取：组装时直接取环境值，进程里为空时不会被 `.env` 补上。setup 写的 `${oc.env:QDRANT_URL}` 不受影响，因为 `QDRANT_*` 在默认清单里。

## 收尾四（基线 `a6f97174`）

上一轮“按配置声明补齐凭据”和“上层向 Core 传脱敏名单”两个方向接受。插值行为确定为标准 python-dotenv：凭据补齐后不重新计算引用。本轮修三处审查复现的问题。

### 1. `.env` 只解析一次

- **问题**：`load_env_file()` 先 `load_dotenv()`，再用 `DotEnv` 重新解析一遍取快照。第二遍能看到第一遍刚写进环境的变量。
  - 复现：进程 `OPENAI_API_KEY=""`、`SHARED_KEY` 未设置，文件 `OPENAI_API_KEY=${SHARED_KEY:-file-default}`，下一行 `SHARED_KEY=file-secondary`。单次解析应得 `file-default`，原来得到 `file-secondary`。
- **修复**：只建一个 `DotEnv(override=False)`，调用一次 `dict()`。同一份结果先按 python-dotenv 的规则写入环境（已设置的值保留，空值也保留），再作为文件快照返回。
  - `PYTHON_DOTENV_DISABLED` 照 `load_dotenv` 的判断处理。用的是 python-dotenv 的私有函数 `_load_dotenv_disabled`，版本由 `uv.lock` 固定，有测试覆盖。
  - `ALPHAAVATAR_HOME` 的空值规则不变。

### 2. upgrade 目标使用父命令的文件快照

- **问题**：目标构建的 `setup --plan` 和 `config check` 从 `/` 运行，相对的 `ENV_FILE` 找不到。upgrade 只按默认名和已存名补齐，配置另外声明的名字没有文件值可用。
  - 复现：项目目录下 `ENV_FILE=.env.dev`，进程 `MODEL_AUTH=""`，文件里有有效值，MCP header 为 `Bearer <MODEL_AUTH>`，Setup 没存这个名字。目标规划报 `MODEL_AUTH` 缺失。
- **修复**：upgrade 把本次 `load_env_file()` 的结果以 JSON 放进传给目标命令的环境（`ALPHAAVATAR_ENV_FILE_VALUES`），不放命令行。
  - 目标的 `load_env_file()` 看到它就用这份值，不再读任何文件。
  - 目标仍按自己的 bundle 解释配置，按自己的声明从这份快照、再从已存值补齐。
  - 锁内读设置和已存凭据、按“默认 + 已存”名字补齐的做法保留。

### 3. MCP 的 `${oc.env:NAME}` 脱敏

- **问题**：`${oc.env:GITHUB_PAT}` 在配置组装时就被 OmegaConf 插值。后面扫描配置时只剩值，认不出来源，所以名字不进脱敏名单，普通错误文本里的值仍然保留。
- **收集阶段**：放在 `loader._composed`，profiles 合并、overrides 应用之后，OmegaConf 插值之前。这是唯一还能看到引用写法的阶段。
  - 在这里对未插值的配置收集声明：每个 `api_key_env`；MCP servers 里的 `<NAME>` 和 `${oc.env:NAME}`。
  - 补齐和脱敏都在这一步，之后才插值。所以 MCP 里的 `${oc.env:NAME}` 和 `<NAME>` 一样：进程里为空时先取 `.env`、再取已存值，并且它的值从日志隐藏。
  - MCP servers 以外的 `${oc.env:NAME}` 仍按普通变量处理：不补齐，也不进名单。
- Core 的 `hide_variables`、Host 的刷新方式和子进程继承都没变。

### 4. 文档

`.env.template` 开头说明、`docs/cli/config.md`「Credentials」、`docs/cli/upgrade.md`、MCP README 的凭据一段。

### 5. 验证

- **新回归**：
  - 单次解析：复现用例原样写入，凭据得 `file-default`，`SHARED_KEY` 得 `file-secondary`；`PYTHON_DOTENV_DISABLED=1` 时不加载。旧代码下这条测试得到 `file-secondary`。
  - upgrade（CLI）：项目目录下用相对的 `ENV_FILE=.env.dev`，进程 `MODEL_AUTH=""`，只有 MCP header 声明这个名字，Setup 没存。目标的规划和校验换成真实的 Host 加载代码（`load_environment` + `load_application`），从 `/` 运行，读到的都是 `.env.dev` 的值；规划后把文件改成别的值，校验读到的仍是父命令那一次的值。所有子进程命令行和 upgrade 的输出里都没有这个值。去掉快照传递后，这条测试失败，报错与审查复现相同（`MODEL_AUTH` 缺失）。
  - 声明的凭据：`MODEL_AUTH` 分层用例新增一个 `${oc.env:GITHUB_PAT}` 的 MCP server，进程为空时取 `.env` 的值。
  - 脱敏：Host 日志测试把两个 MCP server 写进 profile，一个用 `<MCP_PAT>`，一个用 `${oc.env:GITHUB_PAT}`。五个虚构密钥值都不出现在输出里；服务器地址、失败信息、异常类型和其他字段保留；介绍里用 `${oc.env:REGION}` 引用的普通变量值照常显示。
- **变异测试**：28 个全部被抓到（`mutants/run8.py`）：上一轮的 18 个按新代码调整后重跑，新增 10 个，覆盖两次解析、文件覆盖进程值、插值先读文件、忽略 `PYTHON_DOTENV_DISABLED`、不写环境、不传快照、目标忽略快照、目标按绝对路径重读文件、不收集 `${oc.env:}`、把所有 `${oc.env:}` 都当凭据、插值后才收集。
- **仓库检查**：`ruff check`、`ruff format --check`、`git diff --check`、`uv lock --check`、`check_workspace.py` 通过，改动文档的链接 0 处问题。
- **离线全量**：816 passed（309 s），无失败；之后只改了文档和工作记录。
- **未验证**：
  - 该 SHA 的 CI 没有查看；
  - 真实安装包没有复验，目标构建在测试里是假构建，规划和校验换成了源码里的加载代码；
  - 没有调用计费服务；
  - LiveKit 通话由用户验收。

### 6. 记录，未改

- `ALPHAAVATAR_MAX_SESSION_SECONDS`、`ALPHAAVATAR_SEMANTIC_ADDRESSING_THREADS` 遇空值报解析错误，仍按要求不处理。
- MCP servers 以外、写在凭据位置的 `${oc.env:NAME}` 仍按普通变量处理，例如 `vdb_config.api_key: ${oc.env:MY_QDRANT}`。setup 写的 `${oc.env:QDRANT_API_KEY,null}` 不受影响：`QDRANT_*` 在默认清单里，`*_API_KEY` 也按名称隐藏。
- 文件快照放在一个环境变量里，受 Linux 单个环境变量 128 KiB 的上限约束（`MAX_ARG_STRLEN`）。超过时目标命令应无法启动，这一点没有实测。普通 `.env` 远小于这个上限。
