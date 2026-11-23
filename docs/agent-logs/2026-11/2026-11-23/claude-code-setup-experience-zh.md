# 0.6.9 发布前的安装与 Setup 体验优化 — Claude Code 日志

- 分支：`dev/v0.6.9`，基线 `5bc91176`；日期为 CST。
- 依据：用户 2026-11-23 的任务。用户实际安装、运行交互 Setup 后发现两个问题：
  - `install.sh` 的输出难以分辨；
  - 生成的 profiles 太简略：Voice 缺少 TTS 的设置，Vision 只有 `enabled`，ENV Memory 被关掉。
- 要求：
  - 以 `examples/agent_configs/roles/demo.yaml` 为默认基准，唯一的例外是 Tools 默认关闭；
  - 先选能力，再按组件选 Provider 和模型；
  - YAML 写全、保留注释和空行；
  - 优化安装器的输出；
  - 构建新的候选包，做真实安装和 Setup 验证。
- 范围：不改版本号，不提交，不发布。

## 批次总览

| 批次 | 内容 | 状态 |
|---|---|---|
| 0 | 核对并补全 demo.yaml | 完成，待审查 |
| 1 | 随包分发的完整默认模板，`config init` 写出 | 完成，待审查 |
| 2 | 统一的配置决策：能力开关、按组件选 Provider 和模型、TTS 兼容性、依赖、凭据、摘要；保留注释的写入 | 待开始 |
| 3 | 交互流程：能力 → Provider 和模型 → 凭据 → 摘要 → 安装；方向键列表和编号回退；PTY 验证 | 待开始 |
| 4 | 安装器输出的颜色和分组 | 待开始 |
| 5 | 已有配置的保护、Embedding 变更检查、文档、新候选包的真实验证 | 待开始 |

## 1. 批次 0：demo.yaml

- 核对：
  - 当前代码对 demo 做 `config check` 通过；
  - 逐个 schema 比较，没有失效或未知的键；
  - 其他 4 个示例没有用到 demo 缺少的设置。
- demo 没写出的公开字段约 150 个，都有 schema 默认值。用户选择只补影响行为的设置。
- 补上的设置都写成默认值，并附简短注释：
  - avatar：`timezone`；
  - runtime：`inference.methods` 及 worker 示例；
  - context：`behavior_rules`；
  - loop：`model.timeout`、`trace`；
  - voice：
    - VAD 的 `min_speech_duration`、`min_silence_duration: 0.3`、两个阈值；
    - STT 的 `language`、`prompt`、`delay`，注明各自适用的实现；
    - TTS 的 `timeout`、`first_audio_timeout`、`first_audio_hedge_after`（可能计费两次）、`max_retries`；
  - router：visual addressing 的两个阈值，turn taking 的 `transcript_timeout_sec` 和 `commit_timeout_sec`；
  - memory：ENV `scheduler.max_batch_duration_sec`；
  - persona：speaker 和 face 的 `identity_match_threshold`，face 的 `sample_interval_sec`；
  - host：`execution.max_session_seconds`（注明会话 30 分钟后结束）、`health`、`log` 的 level 和 file、`doctor`。
- `avatar.introduction` 按用户要求重写：
  - 原文自称 demo，并列出 RAG、MCP、DeepResearch；
  - 新文只说明 Avatar 是谁、为谁服务。语音风格、记忆、身份、工具和隐私的规则已在 Context 的系统提示里。
- 验证：
  - 新旧 demo 的有效配置逐项比较（各插件 settings 展开后），只有 `avatar.introduction` 不同；
  - `config check` 通过；离线全量 993 passed。

## 2. 批次 1：随包分发的完整默认模板

### 2.1 改动

- 新增 `avatar-host/alphaavatar/host/configs/templates/`，每个 profile 一个文件：
  - 插件按层放入 `plugins/foundation`、`plugins/perception`、`plugins/tools`；
  - `host.yaml`、`runtime.yaml` 放在顶层（用户要求）。
- 内容是 demo 的值，加上各 schema 的全部公开默认值，覆盖：
  - Host、LiveKit 的 `rtc.init_config`、Runtime；
  - 各段的 Agents 配置；
  - Context、Loop、Router、Memory、Persona 插件的 settings，以及 Status 的 `StatusRuntimeConfig`。
- 排版：
  - 两个空格缩进，组内连续的标量保持紧凑，同级的设置组之间空一行；
  - TTS 的 instructions 保留多行；
  - 保留 demo 的注释，加上字段说明、worker 示例、ENV Memory 用 `GOOGLE_API_KEY` 的说明、Tools 的启用方法和 MCP 的注释示例。
- 和 demo 的差别：
  - **Tools 关闭：** deepresearch 和 rag 是 `plugin: null`，mcp 是 `enabled: false`，`servers: {}`。注明 DeepResearch 读 `TAVILY_API_KEY`，Setup 还不能安装 RAG。
  - **向量库：** Memory 和 Persona 的 `vdb_config` 明确写 `url: null`，即 LanceDB 放在 Avatar 工作区。不写时，环境里的 `QDRANT_URL` 会把向量带到 Qdrant；Setup 本来就写 `url: null`。
- 身份：Bundle 名和 Avatar ID 仍由用户给出。bundle 文件的 avatar 段写 demo 的 `name: AlphaAvatar`、`timezone` 和新的 introduction。
- `template.py`：
  - `SECTIONS` 改为从这些文件读取，按层定位；
  - `config init` 写出的每个 profile 是一行说明加文件原文；
  - `REQUIRED_ENVIRONMENT` 加入 `GOOGLE_API_KEY`，因为 ENV Memory 默认开启。
- `choices.py`：现有的 Setup 流程在凭据里加入 `GOOGLE_API_KEY`，能力说明加上 ENV Memory。按组件选择 Provider、关闭 ENV 的问答在批次 2、3。
- 打包：Host 用 hatchling 打包 `alphaavatar` 目录。构建出的 wheel 含全部 12 个模板文件，安装后不依赖 `examples/`。
- 文档：`docs/cli/config.md` 中 `config init` 的说明。

### 2.2 测试（`avatar-host/tests/configs/test_template.py`）

- `test_every_profile_writes_out_each_public_setting_of_its_schemas`：
  - 每个 profile 的原始 YAML（不经过加载的默认值）覆盖其 schema 的全部字段；
  - 用户自填的映射（`tasks`、`extra`、`servers`、`methods` 等）只要求键存在；
  - 模板目录里每个文件都对应一个段，没有多余文件。
- `test_the_profiles_run_the_reference_configuration_with_no_tool_on`：
  - `config init` 写出的 bundle，与 demo 的有效配置（含 Host，各插件 settings 展开）逐项相等，只有 tools 例外；
  - 没有选中任何工具；
  - ENV Memory 开启，为 Google、`gemini-2.5-flash` 和 `langchain_gemini`。
- `test_the_profiles_are_laid_out_to_be_edited`：
  - 文件末尾、空白、Tab；
  - 偶数缩进，下一层缩进恰好两个空格；
  - 同级设置组之间有空行，组内标量之间没有空行；
  - 指定的注释和多行 instructions 保留。
- `test_init_writes_each_profile_as_it_ships`（12 个参数）：`config init` 写出的正文与随包文件逐字节相同。
- 原有测试的调整：
  - `test_bundles.py`：bundle 的 avatar 段按新值断言，去掉旧的单文件模板对照，与 demo 的对照移到上面；STT 的用例改为替换整个 `stt` 块，否则模板里后面的同名键会覆盖测试写入的值；
  - `cli/test_check.py`：必需凭据多出 `GOOGLE_API_KEY`；
  - `cli/test_setup.py`：脚本化的问答多一个 Google 凭据的回答，测试环境加入虚构的 Google key。
- 变异测试（在内存中改动已加载的模板，不动仓库文件），8 个全部被发现：
  - 漏写一个字段；
  - 改动 demo 的一个值；
  - 设置组之间没有空行；
  - 组内多一个空行；
  - 开启一个工具；
  - 删掉 worker 示例注释；
  - 关闭 ENV；
  - 4 空格缩进。最后这项起初只被其他测试发现，因为它让 YAML 无效；补上"下一层恰好两个空格"的检查后，排版测试也能单独发现合法的 4 空格嵌套。

### 2.3 验证

- 相关测试：configs、setup choices 和 environment、CLI，共 298 passed。
- 离线全量：1008 passed（原 993 个，加上新增的 15 个），47 warnings，362 s；运行前后，未跟踪和被忽略的文件一致。
- 仓库规范：`uv lock --check`、`check_workspace.py`、`ruff check .`、`ruff format --check .`（794 个文件）、`git diff --check` 都通过。

### 2.4 未验证与下一步

- 新模板没有在不含插件的裸基础包上跑过 `config init`。模板只用 Agents 和 Host 的 schema 校验，不导入插件；批次 5 构建新包时验证。
- 现有 Setup 流程改动段落时仍用 `yaml.safe_dump`，被改动的段会丢掉注释和空行，例如关闭本地模型或选用自建服务器时；批次 2 改为保留注释的写入。
- Setup 暂时还不能关闭 ENV：现在的 Setup 总是要求 `GOOGLE_API_KEY`。
