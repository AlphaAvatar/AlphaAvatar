# AlphaAvatar v0.6.9 配置诊断与 Doctor 体验优化 — Claude Code 日志

- 分支：`dev/v0.6.9`；日期为 CST。
- 依据：用户 2026-11-20 的任务。上一批安装包复验已通过审查，参考基线 `4a46fcab`。
- 范围：
  - 只做离线实现和验证：不调用计费服务，不连接真实 LiveKit，不发布 release。
  - Web／App 引导留到 0.7.0。
  - 代码改动留在工作区，由用户审查后提交。
- 相关日志：
  - Doctor 历史批次见 [claude-code-doctor-zh.md](../2026-11-03/claude-code-doctor-zh.md)；
  - 本轮处理的两项问题来自 [claude-code-package-check-zh.md](../2026-11-19/claude-code-package-check-zh.md) 第 8 节。

## 批次总览

| 批次 | 内容 | 日期 | 基线 HEAD | 提交 | 状态 |
|---|---|---|---|---|---|
| 配置诊断与 Doctor | 缺失变量按设置路径和变量名报告；setup 提示给出 bundle 的命令；Doctor 报告先给结论，再给端到端、阶段和详细诊断 | 2026-11-20 | `4a46fcab` | `66d72583` | 已提交 |
| 收尾修正 | `action` 脱敏；转义的 `\${oc.env:}` 不再误报；`Authorization` 凭据为空时拒绝加载；P95 说明 | 2026-11-20 | `66d72583` | `8c23a217` | 已提交 |
| 收尾二与真实 Doctor | 空凭据检查只针对会创建的 MCP；`${oc.env:NAME,default}` 的空凭据；真实 Doctor 视觉开、关各 5 轮 | 2026-11-20 | `8c23a217` | `79147886` | 已提交 |
| 延迟定位 | 嵌套默认值凭据；Doctor 文本收尾；提交等待与 Context 就绪定位；空记忆不做 embedding；VAD 默认 0.3 s | 2026-11-20 | `79147886` | `c6ea6c19` | 已提交 |
| 收尾三 | `${oc.env:NAME,}` 的空默认值不再误报；寻址策略与模型限制的记录；延迟收益口径 | 2026-11-20 | `c6ea6c19` | `69e00be8` | 已提交 |
| 安装中断收尾 | `install.sh` 的信号窗口与归属记录；install、setup、upgrade 的暂存目录最后删标记；ROADMAP、KD-7 状态 | 2026-11-21 | `69e00be8` | `6806fa5b` | 已提交 |
| 删除失败与 O-10 | `install.sh` 删除失败时保留标记（KD-48）；STT model 必填前移到配置校验（O-10）；O-11 延期；SIGKILL 空目录边界接受（O-26） | 2026-11-21 | `6806fa5b` | — | 待审查 |

## 1. 基线与 CI

`4a46fcab` 的两条 push CI 都通过：
- Quality [44568083634](https://github.com/AlphaAvatar/AlphaAvatar/actions/runs/44568083634)：`lint`、`build`、`install` 三个 job 通过，全量 821 passed（411.81 s）。
- Linux package [44568083632](https://github.com/AlphaAvatar/AlphaAvatar/actions/runs/44568083632)：`build` 和 `verify` 通过。

## 2. 原有能力与缺口

先读了 `config check`、Doctor 的实现、CLI 文档和测试，再逐项对照任务。

| 要求 | 已有 | 缺口 |
|---|---|---|
| 缺少凭据时给出变量名和位置 | 各凭据读取方在消息里写变量名 | 配置加载阶段：MCP `<NAME>` 只显示 `fields: tools.mcp`；`${oc.env:NAME}` 缺失只显示 "Invalid YAML, configuration override, or interpolation" |
| 安装建议可执行 | 已说明 setup 是否安装 | 只写 `alphaavatar setup`。对 MCP 这类插件，不带参数的交互式 setup 不会选它；对单文件配置也给出同一句 |
| 统一诊断入口 | `format_failure`、`describe_error` | `config check`、Doctor、setup 各自拼装下一步，文字不一致 |
| 一个 doctor 入口，一份配置和凭据 | 已有：`prepare` 读 `.env` 和存储的凭据，授权和子进程都用同一份快照，子进程继承已补齐的环境 | — |
| 按视觉开关选择场景，不用文本回退 | 已有：`session.plan` 按有效配置选 `voice_vision` 或 `voice`，没有文本场景 | 没有直接针对选择规则的回归 |
| 固定样本、多轮、首轮单列、中位数／范围／样本数 | 已有 | — |
| 标明哪些检查会下载模型或调用外部服务 | 已有一次性授权和跳过原因 | 检查清单（`--list`）不说明哪项会下载或调用 |
| Input／Context／Output 三段边界 | 已有：`measure.NODES` 和 `STAGES` 与任务表一致，三段之和等于首个音频帧 | 文本未说明端到端的起止和所测的 Host 层 |
| 详细指标（STT、Context／关联、模型请求、音频供给、视觉、Runner） | JSON 全部都有 | 文本只显示端到端和三段；Runner 结果不含 worker 数；两个模型请求指标缺失时没有原因 |
| 报告顺序：结论和失败位置，再端到端、阶段、详细诊断 | — | 文本顺序是会话、Runner、场景、延迟、失败轮 |
| PASS/FAIL/SKIP 含义；缺失不写 0；保留失败轮 | 文档有状态表；缺失值为 `—`；失败轮单独成表 | 文本里没有状态含义 |
| 客户端观察的等待不写成服务端耗时 | 指标名和文档已区分 | 端到端边界写作 "server side"，容易误读为服务方耗时 |
| 导出报告含配置摘要和有界关联证据，已脱敏 | 证据有界（64 条，保留关键节点），按会话加盐的标识 token，过同一输出边界 | JSON 顶层没有配置摘要 |

## 3. 本轮改动

### 3.1 配置诊断

- **Agents**（`avatar-agents/alphaavatar/agents/utils/env_utils.py`）：
  - 新增 `MissingVariable(ValueError)`，带变量名和读取它的键路径；
  - `resolve_env_placeholders` 递归时带上键路径；
  - MCP 配置从 `servers` 起算（`tools_config.py`）。
- **Host 公共诊断**（新文件 `avatar-host/alphaavatar/host/configs/problems.py`）：
  - `Problem`：设置路径、问题、包、修复动作、变量名。
  - `ConfigProblems` 是共同基类，`MissingCapabilities` 和新的 `MissingVariables` 都继承它。
  - `missing_variables`：把 Pydantic 校验错误里的 `MissingVariable` 转成完整路径，例如 `tools.mcp.servers.docs.headers.Authorization`。同一次校验里其他出错字段只写路径。
  - `unresolved`：插值失败时，找出没有默认值、变量又未设置的 `${oc.env:NAME}`。`Authorization` 里的按凭据说明；其他的说明没有默认值。找不到时只给出插值失败的设置路径。
  - `setup_installs`、`next_step`、`describe_error`：setup 提示和下一步统一在这里生成，`config check`、Doctor 和 JSON 用的都是这些函数。
- **消息格式**：
  - 写成 `<设置> reads the credential MCP_PAT, which is not set`，不用冒号。
  - 原因：日志脱敏边界会把 `Authorization: …` 后面的词当作值隐藏，连变量名一起隐藏了（试跑时发现）。
  - 空值或空白写 `is empty`。
- **加载流程**（`loader.py`）：
  - `_avatar` 统一校验 Avatar 设置，`_validate` 和 `load_selections`（`setup <bundle>` 规划用）都经过它；
  - 插值失败经过 `unresolved`；
  - `ApplicationConfig.source` 记录配置来自哪个 bundle 或文件，`load_application` 设置它。
- **setup 提示**（`capabilities.py`）：
  - bundle 写 `` `alphaavatar setup my-avatar` installs it (pkg) ``；
  - 文件写 `setup installs it for a bundle, not a file (pkg)`，不给命令；
  - 不在 catalog 的仍写 "this release's `alphaavatar setup` does not offer it"。
- **调用方**：
  - `config check`：失败时仍保留已选的来源；所有 `ConfigProblems` 都逐条显示，窄终端分行。JSON 增加 `problems` 和 `action`。
  - Doctor `config.load`：动作改用 `next_step`。
  - Doctor `packages.capabilities`、`packages.alphaavatar`：给出 bundle 的 setup 命令；文件不给。
  - `start`／`dev`、`setup` 经过同一套加载，显示相同的消息。
- **CI**（`.github/workflows/linux-package.yml`）：只安装基础包时的 `config check` 断言改为 `` `alphaavatar setup reference` installs it ``。

### 3.2 Doctor

- **检查清单**（`doctor.py`、`schemas/report.py`）：
  - `CheckSpec.reaches` 标明授权后可能下载模型或调用外部服务的检查：`session.start`、`models.runners`（下载模型；向量库 runner 启动时的探测请求）、`services.external`、`session.scenarios`；
  - `--list` 文本和 JSON 都显示；
  - `models.runners` 的标题原来写 "from the model cache, offline"，已过时，改为与文档一致。
- **报告组织**（`cli/commands/doctor.py`）：
  - 顺序：Checks、Not verified、状态含义一行、Scenarios、Failed rounds、Latency（通过轮；有失败轮时再给全部轮）、Details、Session、Runners、Run again as JSON。
  - Latency 表下注明起止：从最后语音样本所在帧进入，到 Host 输出边界，不含 RTC 传输和客户端播放。
  - Details：按全部轮（含失败轮）显示 JSON 已有的详细指标。分组为 STT（Turn 采用的终稿）、Turn taking 与 Context、模型请求首次尝试、音频输出、视觉（仅 `voice_vision`）、Doctor 输入。
  - 每行标签写明起点；客户端观察的等待写 "network and service"。
  - 缺失项为 `—`，并在表下写明原因。
- **Runner**：`RunnerResult` 增加 `workers` 和 `ready_workers`（来自运行时状态）；文本显示 `1 worker`，未全部就绪时写成 `n of m workers`。
- **JSON**：`Report.configuration` 是 `config check --json` 同样的摘要，经过同一输出边界；Runner 规划失败时为 `null`。
- **指标**（`measure.py`）：
  - 端到端边界从 "server side" 改为 "diagnostic input to the Host's output boundary"；
  - 提供方记录里缺少 `client_ms`、`prepare_ms` 等字段时，注明 "its provider logs no such step"，不再只写未观察到。
- 没有新增 trace 或业务字段，也没有读取 processor 私有状态。量测层只解释已有记录。

## 4. 验证

| 类别 | 项目 | 结果 |
|---|---|---|
| 新增回归 | `test_check.py::test_a_variable_holding_no_value_is_named_at_the_setting_that_reads_it` | 覆盖 `${oc.env:}` 凭据与普通变量、`<NAME>` 未设置与空白、与其他非法字段同时出现；`config check` 文本、JSON 与 Doctor `config.load` 一致；输出里没有 `Bearer`、URL、行内值、虚构值和 Pydantic 消息 |
| 新增回归 | `test_capabilities.py` 安装包用例 | bundle 给 `alphaavatar setup alpha`，文件给 "for a bundle, not a file" 且不含命令；JSON 的 `problems` 和 `action` |
| 新增回归 | `test_doctor.py` | 文件配置的 `packages.capabilities` 不给 setup 命令；`--list` 的 `reaches`；报告 `configuration` 已脱敏 |
| 新增回归 | `test_session.py` | 场景按有效视觉配置选择（vlm、realtime、text-only、off；无 TTS 时不运行任何场景）；Details 表与 JSON 的全部轮数值一致，不重复 Latency 的行；Host 边界说明；Runner worker |
| 新增回归 | `test_measure.py` | 提供方记录缺少字段时为 `null`、0 样本，并写明原因 |
| 变异 | 9 个 | 全部被测试发现：解析器不带路径；不解释校验错误；插值失败仍报笼统错误；消息改回 `<设置>: …`（会被脱敏隐藏变量名）；总是选 `voice`；Runner 不带 worker；不画 Details；报告不带配置摘要；不写缺字段原因 |
| 等价变异 | 1 个 | 去掉 `input_mode != "text"` 后行为不变：`VisionConfig` 已把 text-only 规范为关闭，已在测试说明里写明 |
| 受影响测试 | Host 与 Agents 全部测试 | 477 passed（261 s） |
| 离线全量 | `uv run pytest` | 826 passed（307 s；原 821 + 新增 5） |
| 仓库检查 | ruff check、ruff format --check（790 个文件）、`git diff --check`、`uv lock --check`、`check_workspace.py`（16 个成员） | 通过 |
| 对应 SHA 的 CI | `4a46fcab` | 两条都通过；本轮改动未提交，没有 CI |
| 真实服务 | — | 未运行，见第 5 节 |

## 5. 待真实复验

以下只在离线替身上验证过，需要真实服务或真实安装包才能确认：
- Details 表在真实链路上的内容：
  - STT 分解（httpcore trace 才有建连、TLS、上传、等待）；
  - OpenAI 提供方的 `client_ms`、`prepare_ms`；
  - `voice_vision` 的视觉分组；
  - 真实 TTS 的首个 PCM。
- 真实 runtime 下 Runner 的 worker 数和就绪数（替身每个 runner 1 个 worker）。
- 安装包内的 setup 提示：测试用模拟的 `Installation` 和 catalog 验证。（已确认：`66d72583` 的 Linux package job 在真实安装包上检查到 `alphaavatar setup reference` 一行，见第 8 节。）
- 实际 LiveKit 通话由用户验收。

## 6. 发现未改

- `Authorization` 里的 `${oc.env:NAME}` 补齐后仍为空或空白时，OmegaConf 照常插值为 `Bearer `，加载不报错；同样位置的 `<NAME>` 会报缺失。本轮只改诊断，没有改加载语义。（收尾已改，见第 8 节。）
- 插值先于校验：`${oc.env:}` 缺失和 `<NAME>` 缺失同时存在时，要分两次看到。
- 运行时读取的凭据（例如 STT 的 `api_key_env`）缺失时：
  - 读取方的消息写了变量名；
  - Doctor 的会话诊断只显示错误类型、位置和提供方分类，例如 `ModelRequestError: missing_api_key`，不显示变量名；
  - 要显示变量名，需要各插件发布可安全显示的字段，涉及多个插件，未在本轮改。

## 7. 证据索引

- 试跑配置和输出：会话临时目录 `diag/`（含一份有缺失 MCP 变量的 `avatar.yaml`）。
- Doctor 离线三轮文本：会话临时目录 `doctor-text.txt`。`docs/cli/doctor.md` 的示例取自这次输出，路径改为 `avatar.json`。

## 8. 收尾修正（基线 `66d72583`）

依据：用户 2026-11-20 对本批的审查意见，按最小范围修正四处。另外两项（插值与占位符缺失分两次显示；运行时提供方错误缺变量名）按用户意见只记录，不改。

### 8.1 基线 CI

`66d72583` 两条 push CI 都通过：
- Quality [44682379608](https://github.com/AlphaAvatar/AlphaAvatar/actions/runs/44682379608)：全量 826 passed（538.20 s）。
- Linux package [44682379710](https://github.com/AlphaAvatar/AlphaAvatar/actions/runs/44682379710)：`verify` 在真实安装包上检查到 `` `alphaavatar setup reference` installs it ``。第 5 节的 setup 提示一项因此已确认。

### 8.2 改动

- `error.action` 脱敏：`describe_error()` 的 `action` 也经过同一个 `Redactor`。复现方式：虚构凭据值同时用作 bundle 名，缺包时 `action` 原样带出这个值。Doctor 的 action 本来就在报告出口统一处理，不用改。
- 转义文本不再误报：
  - 扫描 `${oc.env:NAME}` 时按 OmegaConf 的规则判断：前面是奇数个反斜杠时，这段是普通文本；偶数个时，照常插值。已在 OmegaConf 2.3.0 上核对。
  - 插值实际失败的设置（`full_key`，`a.b[0]` 写成 `a.b.0`）不和已列出的变量重复时，作为一项单独列出：`<设置> holds an interpolation that cannot be resolved`。同时有缺失变量时，两者一起报告。
  - 只有插值失败、没有缺失变量时，改为 `ConfigProblems`，JSON 的 `fields` 因此带上位置。原来这里是 `ConfigReferenceError`，`fields` 为空。
- `Authorization` 凭据为空时拒绝加载：
  - 针对 `Authorization` 中按凭据识别的 `${oc.env:NAME}`（不带默认值）。补齐的顺序不变：有效进程值、`.env`、Setup 保存值。
  - 补齐后仍未设置、为空串或只有空白时，报告完整的设置路径和变量名，与 `<NAME>` 一致，不再加载成 `Bearer `。
  - 插值成功后由 `unset_credentials()` 检查；插值失败时，由 `unresolved()` 和其他缺失项一起列出。
  - 普通变量仍按 OmegaConf 读取，进程里的显式空值照常保留。这条规则只针对 `Authorization` 凭据。
- 文档：
  - `docs/cli/doctor.md`：P95 只出现在通过轮的 `Latency` 表。`Details`、全体轮表和 JSON 的 `all_` 字段都没有 P95。
  - `docs/cli/config.md`：补充转义规则、凭据为空的拒绝和插值失败的报告方式。

### 8.3 验证

| 类别 | 项目 | 结果 |
|---|---|---|
| 新增回归 | `test_capabilities.py::test_the_next_step_naming_the_bundle_passes_the_output_boundary` | 凭据值作 bundle 名时，`action`、`problems`、文本都不含该值 |
| 新增回归 | `test_check.py::test_escaped_interpolation_reads_nothing_and_a_failing_one_keeps_its_setting` | 用户给的 YAML：转义文本照常加载；`avatar.timezone` 按位置报告，不出现 `LITERAL_NAME`；偶数个反斜杠时变量照常插值，和插值失败一起报告；`config check` 文本、JSON 与 Doctor `config.load` 一致 |
| 扩展回归 | `test_check.py` 缺失变量用例 | 进程中为空白、各来源都没有值时报 `which is empty`；普通变量为空时照常插值 |
| 扩展回归 | `test_credentials.py::test_in_an_mcp_server_only_authorization_interpolates_a_credential` | 进程中为空或空白时，先用 `.env`，再用 Setup 保存值；不补齐时两处都按完整路径拒绝 |
| 新增回归 | `test_loading.py::test_an_interpolation_failing_in_a_list_is_named_once_by_its_path` | 列表项的位置写成 `a.b.0`，同一设置只列一次 |
| 变异 | 8 个 | 全部被测试发现：`action` 不脱敏；不判断反斜杠奇偶；不列插值失败的位置；不检查空凭据；凭据只判断是否未设置；不改写 `[0]`；插值失败的位置总是重复列出；`unresolved()` 不报普通变量 |
| 受影响测试 | Host 与 Agents 全部测试 | 480 passed（261 s；原 477 + 新增 3） |
| 离线全量 | `uv run pytest` | 829 passed（306 s；原 826 + 新增 3） |
| 仓库检查 | ruff check、ruff format --check（790 个文件）、`git diff --check`、`uv lock --check`、`check_workspace.py`（16 个成员） | 通过 |
| 同 SHA CI | — | 本轮改动未提交，没有 CI；提交后需核对 |
| 真实服务 | — | 未运行：不调用计费服务，不连接 LiveKit |

### 8.4 待复验与记录

- 实际 LiveKit 通话由用户验收。第 5 节其余各项（Details 表的真实链路内容、真实 worker 数）仍待真实运行。
- 只记录，不改：插值缺失和 `<NAME>` 缺失分两次显示（本轮已接受）；运行时提供方错误不带变量名，以后按提供方补充。

## 9. 收尾二与真实 Doctor（基线 `8c23a217`）

依据：用户 2026-11-20 的审查意见。`8c23a217` 的两条 CI 都通过（Quality [44701864076](https://github.com/AlphaAvatar/AlphaAvatar/actions/runs/44701864076) 全量 829 passed；Linux package [44701864091](https://github.com/AlphaAvatar/AlphaAvatar/actions/runs/44701864091)）。

### 9.1 改动

- 关闭的 MCP 不再要求凭据：`MCPConfig.creates`（`enabled` 且有 `plugin`）同时决定 `<NAME>` 的解析和空凭据检查。Host 按插值后的值，用 `MCPConfig` 校验这两项。MCP 未创建时，`Authorization` 里的引用按普通插值处理：变量为空时照常加载；未设置且没有默认值时，仍按 OmegaConf 插值失败报告。
- 带默认值的引用：`${oc.env:NAME,default}` 也纳入扫描。补齐的顺序不变：有效进程值、`.env`、Setup 保存值。
  - 变量未设置、默认值有效时，正常加载；
  - 变量为空或空白，或默认值为空、空白或 `null` 时，按完整路径和变量名拒绝；
  - 普通变量仍保留显式空值。
- `credentials.authorizations()` 列出各 `Authorization` 头及其路径，`interpolated_credentials()` 改为复用它。
- 文档：`docs/cli/config.md` 加入 MCP 未创建和默认值两条规则。

### 9.2 离线验证

| 项目 | 结果 |
|---|---|
| 新增回归 | `test_credentials.py`：MCP 关闭和 `plugin: null` 两种情况；默认值的 8 种组合（进程值、`.env`、保存值、默认值、空、空白、空默认值、`null` 默认值），普通变量为空时保留；`test_check.py` 的转义用例加了带默认值的普通变量 |
| 变异 | 8 个，全部被发现：总当作已创建；不匹配默认值；忽略已设置的空值；`null` 当有效值；任何默认值都当有效；`creates` 不看 `plugin`；普通变量不看默认值；不写"默认值为空" |
| Host 与 Agents | 490 passed（261 s） |
| 离线全量 | 839 passed（309 s；原 829 + 新增 10） |
| 仓库检查 | ruff check、format、`git diff --check`、`uv lock --check`、`check_workspace.py` 通过 |

### 9.3 真实 Doctor

- 方式：
  - 从源码 `.venv` 运行，不另外构建安装包（磁盘只剩约 7 GB）；
  - `env -i`，只带隔离的 `HOME`、`ALPHAAVATAR_HOME`、`PATH`、`LANG`、`TERM`，在临时目录中运行；
  - 凭据只取 `.env.dev` 的四个变量，写入权限 600 的文件，经 `ENV_FILE` 读入；
  - `config init accept` 用默认值（视觉 `vlm`，8 个 runner）；
  - 每组只运行一次 `doctor accept host.doctor.external_services=true [vision.enabled=false] --rounds 5 --json`；
  - 文本报告由 CLI 自己的渲染器从 JSON 重建。静态报告的实时文本和重建文本逐字相同；
  - `doctor_compare.py` 对单份和两份重算，都以退出码 0 结束。
- 结果：

| 组 | 场景 | 通过 | 耗时 | runtime 启动 | 模型缓存 |
|---|---|---|---|---|---|
| 视觉开 | `voice_vision`（`voice` SKIP："Vision is on: voice_vision speaks to it"） | 5/5 | 3 min 21 s | 137.48 s | 净增 1,689.4 MB（空缓存） |
| 视觉关 | `voice`（`voice_vision` SKIP："Vision is off or text only"） | 0/5，均停在 `stt.final` | 1 min 14 s | 20.13 s | 未增长 |

- 指标（第 1 轮；后 4 轮中位数）：

| 指标 | 视觉开 | 视觉关（全部轮） |
|---|---|---|
| 端到端首个音频帧 | 8,947；5,187 ms | 4,085；3,653 ms |
| Input／Context／Output | 2,383／751／5,813；1,573／755／2,483 ms | 1,266／845／1,974；1,259／754／1,661 ms |
| STT 终稿（等待应答头） | 1,661（1,552）；852（746）ms | 586（508）；579（485）ms |
| 连接、TLS、上传、首事件 | 4.1、6.1、5.6、0.5；8.1、5.4、4.5、0.4 ms | 4.2、8.6、4.7、0.5；7.9、5.7、5.2、0.4 ms |
| 请求准备、编码、client | 8.5、0.6、0.0；5.1、0.5、0.0 ms | 7.0、0.5、0.0；3.7、0.5、0.0 ms |
| 图片、请求大小、尝试次数 | 4、65.1 KB、1 | 0、19.7 KB、1 |
| 发送到首个流事件 | 4,495；394 ms | 698；360 ms |
| 首个文本 delta | 4,968；1,127 ms | 1,076；777 ms |
| TTS 首个 PCM | 706；995 ms | 667；606 ms |
| 视觉 | 最后必需输入 2,862；2,011 ms；帧发布 0.8 ms；最旧帧 2,565；2,362 ms；最新帧到提交 26；94 ms；等帧未观测（选的都是已有帧） | — |

- 核对：
  - 10 轮的 Input、Context、Output 之和与端到端相差不到 0.01 ms，各阶段的分项之和与阶段总数相同；
  - 首轮单独列出，失败轮保留（视觉关的 `Latency` 和 `Details` 按全部轮列出，`Failed rounds` 列出每一轮）；
  - 缺失值写 `null` 并附原因，没有写成 0；
  - 8 个 runner 都是配置 1 个 worker、就绪 1 个，与配置摘要 `inference` 一致；
  - `session.cleanup` 两次都 PASS，事后没有残留进程，Avatar 的工作区没有创建；
  - stdout 第一个字符是 `{`，stderr 为 0 字节，按值检索四个凭据，JSON、重建的文本和对照表里都没有。
- 视觉关 0/5 是已知的 KD-19：分段 STT 在求和样本上丢第二句。终稿只含第一句，按句归因为 `lost: stt`（第 3、4 批是 1/5）。
- 调用量：
  - 10 个会话；
  - STT 10 次；
  - 模型首次请求 10 次，没有重试；
  - TTS 每轮至少 1 次；
  - 记忆检索 10 次；
  - 模型下载约 1.7 GB，不计费。
- 费用：按此前各批每轮约 0.02～0.03 美元，估计 0.2～0.5 美元，以账单为准。

### 9.4 发现，未改

- JSON 里阶段行与端到端用两套名称写同一组事件：阶段写 "Final speech → First audio frame"，边界为 "the Turn's first model request, one clock"；端到端写 "last voiced sample in → first answer audio frame out"，边界为 "diagnostic input to the Host's output boundary"。数值一致，文本表下有说明。
- runner 只在服务过调用后才记录摘要，没有调用时 `calls` 为 `null`，报告不写原因。本次 `persona.face.analysis` 两组都是这样，`persona.speaker.attribute` 在视觉开时也是。卡片样本里没有人脸时 face 是否本就不调用，没有追查。
- 文本中只有第 1 轮缺失的格子显示 `—`，表下不写原因（JSON 有原因）。例如视觉关第 1 轮的语义 addressing："no semantic addressing ran for the final, or none is traced"。
- 已知、未变：
  - 定时保持为 500 ms（O-23 addressing 等待超时）；
  - Context 就绪等待约 240 ms；
  - 视觉开第 1 轮和第 4 轮，请求发出到首个流事件较长（4.5 s、2.3 s）。这是 Host 观测到的网络与服务合计等待，尚未进一步定位。

### 9.5 待办

- 同 SHA CI：本轮改动提交后再核对。
- 用户验收：完整安装、setup、doctor、start，以及实际 LiveKit 通话。
- 原始证据在会话临时目录 `real/`：`work/` 下有两份 JSON、重建的文本、核对与对照输出；`home/` 是隔离的 home 和模型缓存。不入库。

## 10. 延迟定位（基线 `79147886`）

依据：用户 2026-11-20 的任务。`79147886` 的两条 CI 都通过（Quality [44715074521](https://github.com/AlphaAvatar/AlphaAvatar/actions/runs/44715074521) 全量 839 passed；Linux package [44715074464](https://github.com/AlphaAvatar/AlphaAvatar/actions/runs/44715074464)）。真实运行仍用源码 `.venv`，隔离方式同第 9 节。原始证据在会话临时目录 `real/`：`trace-*`、`vad/`、`stt-tail/`、`final/`。

### 10.1 改动

- **嵌套默认值**：`credentials.env_calls()` 用 OmegaConf 自己的 grammar 找出各个 `oc.env` 调用，转义文本不算调用。凭据（已创建 MCP 的 `Authorization`）的每个最外层调用，在该头旁边交给 OmegaConf 求值，嵌套默认值也一样，结果为空、空白或 `null` 时拒绝。原来的正则（`_ENV`、`_OC_ENV`）删除。补齐顺序和已有回归都不变。
- **Doctor 文本**：
  - 只有第 1 轮缺、后续轮有值的格子，表下给出第 1 轮自己的原因（`…, round 1: …`）；
  - 通过轮表的第 1 轮没通过时，写明这一点；
  - runner 没有调用摘要时写 `no call summary observed`；
  - `devices.media` 写明画面是共享屏幕，读取摄像头的处理（例如人脸识别）不在覆盖范围内。
- **Context 就绪**：
  - LanceDB 召回先在本地查一次。这些 owner、scope 下没有记忆时，不做远程 embedding，直接返回空。按构造，结果与原来相同；
  - core 的 `TurnRuntime` 为每个就绪消费者记一条 debug 日志（`Turn context consumer … wait_ms`），可以区分 Speaker 和 Memory。
- **VAD**：`VADConfig` 和 Silero 的 `min_silence_duration` 默认值从 0.55 改为 0.3。模板和 CLI 文档都没有写这个值。
- 第 9.4 节"在服务侧"改为测量口径；`bugs-zh.md` 的 O-16、O-20、O-23 补上本轮实测。

### 10.2 定位

方法：用会话临时目录里的 `trace_doctor.py` 包住 Doctor。它不改结果，只记录以下内容，包括 runner 进程里的：语义推理的标签和分数、轮次判断读取的寻址记录与判定、各次 hold 和提交的 reason 与 notice、各就绪消费者的等待、`MEMORY PASSIVE RECALL` / `MEMORY RECALL` / `MEMORY VECTOR RECALL`。视觉开、关各 5 轮。

- **提交等待约 500 ms**：
  - 10 轮都属于"判断实际返回 UNKNOWN"；
  - 语义推理在终稿后 17～301 ms 返回，目标段一致，结果被采用，1 ms 内重新判断；
  - `p_avatar` 为卡片样本 0.284、求和样本 0.168～0.193，落在不确定区间 0.1645～0.3755；
  - 于是等到 0.5 s 上限，以 `uncertainty_timeout` 提交，附 `router.addressing_uncertain`（视觉关的回答 "Were you asking me?" 与此一致）；
  - 没有出现"判断未及时返回"或"有效结果到达却没有重新判断"，所以没有改实现。
- **Context 就绪约 240 ms**：
  - Speaker 身份等待 0.4～0.6 ms；
  - Memory 被动召回 222～281 ms（第 1 轮一次 469 ms），其中远程 embedding 215～275 ms（一次 444 ms）、向量检索 5～24 ms、解析 0 ms；
  - 10 轮的候选数都是 0，因为 Doctor 的临时工作区里没有记忆。

### 10.3 VAD 550／300 复验

当前代码、视觉关，每个样本两个阈值各 5 轮，交替先后。样本是第五批的 `pause_in`、`hesitate`、`multi`（句中停顿 0.42～0.51 s），另加 `pause_350`：由 `pause_in` 剪成 0.35 s 停顿，没有调用 TTS。

| 样本（句中停顿） | 通过 550 → 300 | 每轮 STT 段数 | VAD 关闭（中位数） | 首音频（后 4 轮中位数） |
|---|---|---|---|---|
| pause_350（0.35 s） | 2/5 → 3/5 | 1 → 1 | 661 → 421 ms | 3,733 → 3,331 ms |
| pause_in（0.42 s） | 4/5 → 1/5 | 1 → 1 | 681 → 442 ms | 3,348 → 3,270 ms |
| hesitate（0.43 s） | 3/5 → 5/5 | 1 → 2 | 701 → 461 ms | 3,494 → 3,438 ms |
| multi（0.46～0.51 s） | 5/5 → 4/5 | 1 → 3 | 682 → 421 ms | 3,795 → 3,318 ms |

- 正确性：
  - 40 轮都只提交一次 Turn，没有提前回复或丢段；
  - 300 下切开的 2～3 段都并入同一输入，内容完整；
  - 缺句都发生在单段内，两个阈值下都有：STT 采用的终稿缺第二句，为 KD-19。报告里归因为 `unknown`，因为替换样本的有声段与任务句子对不上，是 harness 的限制；
  - multi-300 的一次失败是答案前加了 "Were you asking me?"，属于寻址不确定，不是 VAD 的问题。
- 对照：同一段 `pause_in` 语音，结尾静音 0.44 s 与 0.68 s（即两个阈值的段尾）直接各送 STT 10 次，第二句都只保留 1/10。段尾少约 240 ms 静音与丢句无关。
- 代价：停顿较长的样本，STT 请求从每轮 1 次增加到 2～3 次。

### 10.4 结果

最终代码，默认配置，`alphaavatar doctor`，视觉开、关各 5 轮。对照为第 10.2 节的 trace 运行（550 ms，每轮都做 embedding）。下表为后 4 轮中位数：

| 指标 | 视觉开 前 → 后 | 视觉关 前 → 后 |
|---|---|---|
| 最后有声样本 → VAD 关闭 | 721 → 461 ms | 681 → 421 ms |
| Turn 提交 → Context 就绪检查完成 | 248 → 5.5 ms | 241 → 5.6 ms |
| 终稿 → Turn 提交 | 504 → 504 ms | 504 → 504 ms |
| 端到端首音频 | 4,412 → 3,479 ms | 3,813 → 3,372 ms |

- 实际省下的是两段确定的等待：
  - VAD 关闭早 260 ms，每轮都是；
  - Context 就绪少约 240 ms，因为没有可召回的记忆。有记忆的真实会话仍要做这次 embedding，Doctor 测不到这种情况。
- 端到端的变化还包含 STT、模型和 TTS 的波动。各段中位数不能相加，也不能算精确占比。
- 正确性：
  - 视觉开 5/5 通过；
  - 视觉关 0/5，其中 4 轮是 KD-19；
  - 第 3 轮 STT 终稿在提交后 3.8 s 才到，超过 3 s 的转写期限，按设计带 notice 提交（KD-17 的恢复路径），模型请对方重说，与 VAD 无关；
  - `session.cleanup` 两次都 PASS，没有残留进程；
  - 8 个 runner 配置 1、就绪 1，与计划一致；
  - stdout 只有 JSON，stderr 为 0 字节；
  - 125 份输出按值检索，没有凭据。
- 文本由 CLI 渲染器从 JSON 重建，`doctor_compare.py` 重算都以退出码 0 结束。新增的三类说明都出现了。

### 10.5 离线验证

| 项目 | 结果 |
|---|---|
| 新增回归 | 嵌套默认值 8 种组合（`test_credentials.py`）；第 1 轮原因与"第 1 轮未通过"说明（`test_session.py`）；runner 无摘要；`devices.media` 摄像头一行（`test_doctor.py`）；空记忆不 embedding（新 `test_lancedb_recall.py`）；就绪消费者日志（`test_memory_runtime.py`） |
| 变异 | 凭据求值 6 个；Doctor 文本 4 个（无摘要一项先漏掉，抽出 `_started()` 并直接测试后发现）；LanceDB 跳过 3 个；消费者日志 1 个。全部被发现 |
| 离线全量 | 851 passed（303 s；原 839 + 新增 12） |
| 仓库检查 | ruff check、format（791 个文件）、`git diff --check`、`uv lock --check`、`check_workspace.py`（16 个成员）通过 |

### 10.6 调用量与结论更正

- 调用量：
  - Doctor 60 轮：trace 10 轮、VAD 对照 40 轮、最终 10 轮；
  - 直接 STT 20 次（另有 1 次因本地读取凭据有误被拒，401，不计费）；
  - 第一次 trace 运行因 harness 错误，会话未启动，没有调用。
  - 估计 1.2～1.8 美元，以账单为准。
- 更正上一轮分析：
  - 各阶段中位数不能相加作为精确占比；
  - "图片带来约 350 ms"没有对照证据：视觉开、关用的是不同样本和不同请求，需要同一样本只改图片的对照；
  - "第 1 轮慢是冷连接"也未验证：第 1 轮 STT 的建连和 TLS 与后续轮相近，慢在等待应答头和模型首个事件，属于网络与服务合计；
  - KD-20 已修复，并已用真实连接复用验证（同一 stream 后续段复用连接，8/8）。预建连接不再受它阻塞。
- 下一步建议（未做）：
  - 语义寻址对未点名的直接提问落在不确定区间，是否调整区间或单人场景的默认，需要用户决定；
  - 有记忆时，可以在终稿到达时预先做 embedding，与 0.5 s 的提交等待重叠；
  - 流式 STT 可以让转写与说话重叠，需复验准确率（第 7 节视觉开 0/5 听错）；
  - TTS 可以在第一个短句时就请求；
  - 预建 STT/TTS 连接，可以省下每会话首段的建连与 TLS（4～8 ms + 5～9 ms），收益小。
- 待复验：同 SHA CI（提交后）；实际 LiveKit 通话和完整安装流程由用户验收。

## 11. 收尾三（基线 `c6ea6c19`）

依据：用户 2026-11-20 的任务，认可 VAD 默认 300 ms 和无候选时跳过 embedding。`c6ea6c19` 的两条 CI 都通过（Quality [44758894301](https://github.com/AlphaAvatar/AlphaAvatar/actions/runs/44758894301) 全量 851 passed；Linux package [44758894342](https://github.com/AlphaAvatar/AlphaAvatar/actions/runs/44758894342)）。本轮没有付费调用。

### 11.1 改动

- **空默认值**：OmegaConf 把 `${oc.env:OPTIONAL_NAME,}` 读成变量加一个逗号，逗号后没有元素，求值时传 `""` 作默认值。`env_calls()` 原来按元素个数判断有无默认值，漏掉了它：别的字段插值失败时，会多报 "OPTIONAL_NAME … has no default"。现在按 grammar 里的逗号判断。
- 回归：
  - `test_check.py` 的转义用例：单独使用时加载为空串；另一字段失败时，config check 文本、JSON 和 Doctor 都不提 OPTIONAL_NAME；
  - `test_credentials.py`：`Authorization` 中 `${oc.env:AUTH_TOKEN,}`，未设置时按"默认值为空"拒绝。
- 文档：`docs/cli/config.md` 注明 `${oc.env:NAME,}` 的默认值为空。

### 11.2 决定与记录

- 寻址策略保持现状（用户决定）：不调整全局阈值，不新增单人模式，不关闭语义寻址。约 500 ms 是实际返回 UNKNOWN 后的既定等待（第 10.2 节）。第 10.6 节的第一条建议就此关闭。
- 模型限制与系统验收分开：
  - KD-19 的转录丢句按已知模型限制保留；外部请求超过期限时，按已有契约恢复（第 10.4 节第 3 轮）；
  - 系统验收看音频完整提交、跨段累计、终态与取消、超期结果隔离，以及诊断是否准确，不再为固定样本全部答对扩大模型实验。
- 延迟收益口径（证据为第 10.2、10.4 节的真实 Doctor 运行，原始数据仍在会话临时目录 `real/`）：
  - 明确的阶段收益：最后有声样本 → VAD 关闭少 240～260 ms，每轮都有；Turn 提交 → Context 就绪少约 240 ms，只在这些 owner、scope 下没有合格记忆候选时成立，有记忆时仍做 embedding；
  - 终稿 → 提交的 504 ms 不变；
  - 观察到的端到端首音频（后 4 轮中位数）视觉开 4,412 → 3,479 ms、视觉关 3,813 → 3,372 ms，是不同运行的观察，含 STT、模型和 TTS 的波动，不作为收益；各阶段中位数也不相加。
- 后续优化项：有记忆时提前做 embedding、流式 STT、TTS 切句、预建连接。

### 11.3 发现，未改

- OmegaConf 2.3 对 `${oc.env:NAME,}` 发出 `UserWarning`（"some elements are missing: please replace them with empty quoted strings"），`config check` 和 Doctor 都会打到 stderr，带 site-packages 路径。语法仍被接受，结果为空串；`${oc.env:NAME,''}` 不触发警告。是否在 Host 里屏蔽，或在文档里推荐后一种写法，待用户决定。

### 11.4 验证

| 项目 | 结果 |
|---|---|
| 相关回归 | `test_check.py`、`test_credentials.py` 66 passed |
| 变异 | 改回按元素个数判断：两个回归都失败，其中 config check 输出原样复现误报 |
| 离线全量 | 852 passed（303 s；原 851 + 新增参数用例 1） |
| 仓库检查 | ruff check、format（791 个文件）、`git diff --check`、`uv lock --check`、`check_workspace.py`（16 个成员）通过 |

## 12. 安装中断收尾（基线 `69e00be8`）

依据：用户 2026-11-21 的任务。`69e00be8` 的两条 CI 都通过（Quality [44763949105](https://github.com/AlphaAvatar/AlphaAvatar/actions/runs/44763949105) 全量 852 passed；Linux package [44763949326](https://github.com/AlphaAvatar/AlphaAvatar/actions/runs/44763949326)）。两处异常中断见[升级日志](../2026-11-17/claude-code-upgrade-zh.md)第二步第 7 节。本轮没有付费调用。

### 12.1 改动

- **`install.sh` 的信号窗口**：
  - 会话内实测：没有 trap 时，bash 收到 SIGTERM、SIGHUP 会立刻执行 EXIT trap，与仍在运行的子进程并行，子进程在 cleanup 之后才完成。`mv -T` 成功到 `fresh=` 之间的窗口就是这样留下新目录的。
  - 现在，做出目录或链接并记录的步骤先 `hold`（trap 只记下信号），步骤的命令经 `calm` 忽略信号运行（Ctrl-C 也送到子进程）；步骤完成并记录后，`release` 再按原信号退出（130、143、129）。
  - 覆盖：建 `versions/`；建暂存目录并写标记；`mv -T` 到 `versions/<id>`；建命令目录与链接；切换 `current`；切换后检查失败时的恢复。
- **`install.sh` 的归属记录与清理**：
  - 清理 trap 在取得锁后立即设置，不再等暂存目录建好；
  - `versions/`（`made_versions`）和为命令新建的目录（`made_bin`，到原已存在的最深一层）都记录，失败时只删空目录；去掉 `made_prefix`；
  - 本次的新版本目录在退出时先整体移进暂存目录，再随它删除。
- **标记最后删除**：
  - `environment.py` 新增 `remove_marked()`（先删内容，最后删标记和目录，这两步等待信号）、`remove_stages()`，以及 `discard()`（整体移进一个新的带标记暂存目录，再删除，即原 cleanup 的做法）；
  - setup、upgrade 清理旧暂存目录改用前两个；setup 重建死掉的部分环境、失败后删除本次环境，upgrade 删除本次基础包，改用 `discard()`；cleanup 的 `_remove` 改为调用它们，行为不变；
  - `install.sh` 的 `remove_stage` 同样最后删标记。
- 文档：
  - `docs/cli/config.md` 推荐 `${oc.env:NAME,''}`；省略写法仍支持（OmegaConf 提示已弃用），没有加全局 warning 过滤；
  - `docs/cli/setup.md`、`upgrade.md` 说明删除方式；
  - ROADMAP 去掉 rollback，按已确认范围写为安装、向前升级、清理不用的版本，没有回退或降级；
  - `bugs-zh.md` 的 KD-7 移到已修复：默认不二次审批是用户 2026-11-18 的决定，README 和示例已一致（README 日志）；
  - 升级日志第 7 节的两条标注已处理。

### 12.2 验证

| 项目 | 结果 |
|---|---|
| `install.sh` 回归（`test_install_script.py`） | 在步骤完成后、记录前发信号：建暂存目录、`mv -T`、切换 × SIGTERM、Ctrl-C（进程组 SIGINT）、SIGHUP；步骤进行中发 SIGTERM；首次安装建命令链接时 SIGTERM；清理旧暂存时整组 SIGKILL。每项核对 current、命令可运行、数据不变、无残余，并重试。旧脚本下 14 项失败，其中 9 项失败在状态上：留下无标记暂存目录、留下 `versions/9.9.9-other`、留下命令链接和目录、旧暂存丢了标记 |
| setup、upgrade 回归 | 删除旧暂存、重建死掉的环境、删除本次环境（setup）；删除旧暂存、删除本次基础包和环境（upgrade）时 Ctrl-C：只留带标记的暂存目录，current、设置不变，下一次运行清掉并完成 |
| 变异 | Python 6 个、`install.sh` 8 个，全部被发现 |
| 临时布局注入（会话临时目录 `interrupt/`） | 布局：`install.sh` 装 A、setup 建 A 的环境、应用 home 有设置和工作区文件。`install.sh` 装 B、setup 新计划、upgrade 到 B，各发 SIGTERM、Ctrl-C（进程组）、SIGHUP、SIGKILL（进程组），时刻均分 20 处，共 240 次。每次都核对 current 是原来的或已完成切换的、命令能运行、数据不变、没有未知目录，再重试。TERM、INT、HUP 180 次都不留残余；KILL 60 次中 30 次只留带标记的暂存目录，从未出现无标记的。重试后与不中断时的结果一致，只有 1 次例外：upgrade 切换后被杀，重试是同一构建的升级，按契约直接结束、不清理；这时 `cleanup` 识别出两个暂存目录（"a stage a stopped … left"）并删除，已另行核对 |
| 离线全量 | 870 passed（309 s；原 852 + 新增 18：`install.sh` 14、setup 3、upgrade 1） |
| 仓库检查 | ruff check、format（791 个文件）、`git diff --check`、`uv lock --check`、`check_workspace.py`（16 个成员）、`bash -n` 通过 |

### 12.3 发现，未改

- SIGKILL 无法捕获。只在两处相邻系统调用之间被杀时，会留下空的、无标记的暂存目录：建目录到写标记之间，删标记到 `rmdir` 之间。按现有契约（无标记的不删）保留，不影响之后的安装；240 次注入没有碰到。（用户已接受，登记为 O-26，见第 13 节）
- 被杀后留下的带标记暂存目录，由下一次真正安装的 `install.sh`、setup、upgrade 或 `cleanup` 删除；同一构建的 upgrade 不动任何东西，也不删它们（已有契约与测试）。
- O-10 仍可复现：`voice.stt.model` 只在 `STTConfig.get_plugin` 检查，`voice.tts.model` 在配置校验时检查。（已修复，见第 13 节）

## 13. 删除失败与 O-10（基线 `6806fa5b`）

依据：用户 2026-11-21 的任务。`6806fa5b` 的两条 CI 都通过：Quality [44800024253](https://github.com/AlphaAvatar/AlphaAvatar/actions/runs/44800024253)（lint、build、install，全量 870 passed）；Linux package [44800023991](https://github.com/AlphaAvatar/AlphaAvatar/actions/runs/44800023991)（build、verify）。本轮没有付费调用；VAD 300 ms、寻址策略和 embedding 实现都不变。

### 13.1 改动

- **`install.sh` 删除失败时保留标记（KD-48）**：
  - 问题：review 在 `6806fa5b` 上复现。清理以 `remove_stage "$stage" || true` 调用，函数内的 `set -e` 不起作用；某个子项删除失败后仍删掉标记，留下非空、无标记的暂存目录。
  - 修复：`remove_stage` 的每个子项删除失败即返回，标记和剩余内容保留，由下一次运行删除。
  - 下一次运行清理旧暂存时的调用本来就受 `set -e` 约束，行为不变：删不掉时以 rm 的错误结束，标记保留。
  - Python 一侧的 `remove_marked` 删除失败时 `rmtree` 抛出，标记本来就保留，不改。
- **O-10**：
  - `STTConfig.model` 改为字段校验（`validate_default`）：启用 STT 插件时，缺失、空串、全空白都拒绝；关闭时不需要。
  - 规则与 TTS 相同，只是落在字段上，诊断定位到 `voice.stt.model`。
  - `get_plugin` 里装配会话时的检查随之删除。
  - config check、Doctor、setup、start 都经 `AvatarConfig` 校验，没有分别加检查。

### 13.2 决定与记录

- O-11 登记为已知限制，移到 bugs 的「观察与延期」，不阻塞 0.6.9。共享锁文件属于缓存管理，异常收尾不删锁文件，也不删整个缓存目录。
- SIGKILL 的空目录边界按用户决定接受，登记为 O-26：保持「无法确认归属的目录不删除」，不扩大清理权限。
- `bugs-zh.md`：O-10 移到已修复（foundation 节），新增 KD-48（Host 节）。

### 13.3 验证

| 项目 | 结果 |
|---|---|
| `install.sh` 回归 | 新增 `test_a_stage_whose_removal_fails_keeps_its_mark_for_the_next_run`，覆盖两条路径：本次暂存（包校验失败后由清理删除）、旧暂存（由下一次运行删除）。PATH 上的 rm 拒绝删除暂存目录里标记以外的内容。核对：暂存目录还在，带标记，剩余内容还在；current、命令、数据不变；恢复 rm 后重试，暂存被删除，安装完成。旧脚本下「本次暂存」失败，留下无标记的 `.install-*`；「旧暂存」通过，那里 `set -e` 起作用 |
| 临时布局验证（会话临时目录 `interrupt/removal_failure.py`） | 布局同第 12 节。用只读目录造成真实的删除失败，不替换 rm。4 个场景：`install.sh` 解包后目录变只读再收到 SIGTERM，由清理删本次暂存；`install.sh` 被 SIGKILL 后留下暂存、其中目录只读，由下一次 `install.sh` 删除；setup、upgrade 各遇到一个带标记、含只读目录的旧暂存。新脚本 4/4：运行以非 0 结束，暂存带标记并保留剩余内容，current、命令、数据不变，没有未知目录；恢复写权限后重试，结果与不中断时一致。旧脚本：第 1 个场景留下无标记的 `.install-*`（只剩 `tree`），重试后仍在；其余 3 个与新脚本相同 |
| O-10 回归 | `test_avatar_config.py`：关闭、缺失、空串、全空白、有效 5 种，拒绝时位置为 `voice.stt.model`。`test_check.py`：缺失、空串、全空白下，config check 的文本和 JSON、Doctor 的 `config.load`、start 都定位到 `voice.stt.model`；start 在子进程中运行，校验之后的第一步换成退出，规则失效时也不会启动 Host。`test_setup.py`：setup 返回 2，没有安装或启用任何东西。旧代码下 7 项失败（config check 报 OK），关闭和有效两种通过 |
| 变异 | `install.sh`：去掉 `\|\| return`（即旧脚本）被发现。STT 规则 5 个都被发现：不校验默认值（缺失漏过）；只拒 `None`；不去空白；忽略 plugin（关闭也拒）；改为 TTS 式的模型级校验（只定位到 `voice.stt`） |
| 离线全量 | 881 passed（310 s；原 870 + 新增 11：`install.sh` 2、`test_avatar_config.py` 5、`test_check.py` 3、`test_setup.py` 1） |
| 仓库检查 | ruff check、format（791 个文件）、`git diff --check`、`uv lock --check`、`check_workspace.py`（16 个成员）、`bash -n` 通过 |

### 13.4 发现，未改

- TTS：`voice.tts.model` 缺失时，校验在模型级（`model_validator`），诊断只定位到 `voice.tts`（config check 文本为 `voice.tts is not valid`）；STT 现在定位到字段。按本轮范围不改。
- setup、upgrade 删不掉旧暂存目录（如权限被改）时，CLI 只报 `PermissionError errno=13` 和 shutil 里的代码位置，不写是哪个目录；`install.sh` 由 rm 写出路径。本轮之前就是这样。
