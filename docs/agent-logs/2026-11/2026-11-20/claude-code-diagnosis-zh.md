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
| 配置诊断与 Doctor | 缺失变量按设置路径和变量名报告；setup 提示给出 bundle 的命令；Doctor 报告先给结论，再给端到端、阶段和详细诊断 | 2026-11-20 | `4a46fcab` | — | 待审查 |

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
- 安装包内的 setup 提示：测试用模拟的 `Installation` 和 catalog 验证。CI 的 Linux package job 会在本轮提交后检查 `alphaavatar setup reference` 一行。
- 实际 LiveKit 通话由用户验收。

## 6. 发现未改

- `Authorization` 里的 `${oc.env:NAME}` 补齐后仍为空或空白时，OmegaConf 照常插值为 `Bearer `，加载不报错；同样位置的 `<NAME>` 会报缺失。本轮只改诊断，没有改加载语义。
- 插值先于校验：`${oc.env:}` 缺失和 `<NAME>` 缺失同时存在时，要分两次看到。
- 运行时读取的凭据（例如 STT 的 `api_key_env`）缺失时：
  - 读取方的消息写了变量名；
  - Doctor 的会话诊断只显示错误类型、位置和提供方分类，例如 `ModelRequestError: missing_api_key`，不显示变量名；
  - 要显示变量名，需要各插件发布可安全显示的字段，涉及多个插件，未在本轮改。

## 7. 证据索引

- 试跑配置和输出：会话临时目录 `diag/`（含一份有缺失 MCP 变量的 `avatar.yaml`）。
- Doctor 离线三轮文本：会话临时目录 `doctor-text.txt`。`docs/cli/doctor.md` 的示例取自这次输出，路径改为 `avatar.json`。
