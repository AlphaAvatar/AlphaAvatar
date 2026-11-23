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
| 0 | 核对并补全 demo.yaml | 已提交（`1cb5c828`） |
| 1 | 随包分发的完整默认模板，`config init` 写出 | 已提交（`1cb5c828`），通过审查 |
| 2 | 统一的配置决策：能力开关、按组件选 Provider 和模型、TTS 兼容性、依赖、凭据、摘要；保留注释的写入 | 完成，待审查 |
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

## 3. 批次 2：统一的配置决策（基线 `1cb5c828`）

- 依据：用户对批次 1 的审查。模板方案保留，并一起处理三项：
  - 自建 TTS 切换 `tts-1` 或 `tts-1-hd` 时，继承的 instructions 让配置加载失败；
  - 工具安装说明与实际 catalog 不一致；
  - `url: null` 保留。
- Memory 和 Persona 的 `url: null` 是用户认可的默认：新建配置固定用工作区的 LanceDB，选 Qdrant 时才生成对应配置；已有 Bundle 原样保留。

### 3.1 统一的决策（`avatar-host/alphaavatar/host/tools/setup/choices.py`）

- `Selection` 是唯一的决策对象。字段：
  - 开关：`voice`、`vision`、`local_models`、`env_memory`，以及 `vector_store`；
  - 各部分的选择：`loop`、`conversation`、`tool`、`environment`、`profiler`、`embedding` 各是一个 `Model`（provider、model、可选的自建服务器）；
  - 语音：`transcription` 是 `Transcription`（实现、模型、服务器），`synthesis` 是 `Synthesis`（实现、模型、声音、语速、服务器）。
- 不设置就是参考配置的值，从随包模板读出（`REFERENCE`），与 `config init` 同一个来源。`sections(Selection())` 为空：全部接受默认时，生成的 profiles 就是 `config init` 写出的。
- 每部分可选的 Provider，按实际实现和本版 catalog：
  - Loop：只有 OpenAI，或说 Responses API 的自建服务器；
  - Memory 的 conversation 和 tool、Persona profiler：LangChain 结构化输出支持的 openai、anthropic、google、openrouter，openai 可以是自建服务器；
  - ENV Memory：只有 Google（Gemini 的音视频输入适配器），不接受文本模型或自建服务器；
  - Embedding：openai（可以是自建服务器）、google；
  - STT：`openai_segment`、`openai_realtime`；TTS：`openai`、`voiceai`。
  - 这些都由同一组包提供（provider 的 `[openai]`、`[langchain]` 两个 extra，以及 voice），所以 `requirements()` 不随 Provider 变化，`requirements_offered()` 的并集不变。没有为菜单新增任何实现。
- 同一份决策给出：
  - 最终 YAML：`sections()`；
  - 依赖：`requirements()`；
  - 凭据：`credentials()`；
  - 安装前的摘要：`capabilities()`。
- 凭据：
  - 每个变量只出现一次，并列出读它的部分，例如"the conversation model, memory, …, from OpenAI"，或"your server <url>: …"；
  - 关掉的部分不读任何凭据：ENV 关闭、且没有其他部分用 Google 时，不要求 `GOOGLE_API_KEY`；
  - Voice.ai 读 `VOICEAI_API_KEY`。
- 复用：几个部分选同一个 `Model` 时，每个部分在 YAML 里各自写出 provider 和 model，不用别名。
- 摘要：列出能力开关、各部分的 Provider 和模型、语音输入和输出（声音、语速）、向量库、工具状态。CLI 仍在凭据之后、"Install and enable?"之前显示它，即问答完成后、安装依赖之前。

### 3.2 TTS 参数兼容性

- 规则放在 `TTSConfig` 自己身上：`takes_instructions(plugin, model)`、`takes_speed(plugin)`。原有校验和 Setup 用同一条规则：
  - Voice.ai、`tts-1`、`tts-1-hd` 不接受 instructions；
  - Voice.ai 不接受 1.0 以外的语速。
- 继承自模板的默认值，按实现和模型处理：
  - 不接受 instructions 时写 `instructions: null`，并注明原因，例如 `# tts-1 takes no instructions.`；
  - Voice.ai 写 `speed: 1.0  # Voice.ai takes no speed.`。
- 明确给出不支持的参数时直接报错并点名，例如 `Synthesis("voiceai", …, speed=1.2)` 报 "Voice.ai speech takes no speed"；手写给 `tts-1` 的 instructions 由原有校验报 "does not support instructions"。
- 默认的 `gpt-4o-mini-tts` 保留 demo 的完整 instructions、`speaker: ash`、`speed: 1.15`。

### 3.3 保留注释和排版的改写（`template.py`）

- 新增 `Change` 和 `change_profile(text, changes)`：
  - 在模板原文上，就地替换设置的值；
  - 保留该行原有的注释，或换成给定的说明；
  - 缺少的设置插到父级下面，可以指定插在哪个同级之后，例如 Qdrant 的 `api_key` 紧跟 `url`；
  - 映射值写成块；其他行、整行注释、空行和多行文本都不动。
- 改写结果再解析一遍，必须等于对原数据做同样的修改，否则报错，不写出可能走样的文件。
- Setup 所有改动段落的路径都改用它，不再 `safe_dump`：
  - 关闭能力：设置保留，只把开关或 `plugin` 设为 off，并注明怎样重新开启；
  - 自建服务器、Qdrant、TTS 兼容性。
- 工具说明：`tools.yaml` 第一行、RAG 的注释和 `docs/cli/config.md` 统一为：DeepResearch 和 MCP 由 `alphaavatar setup <bundle>` 按本版 catalog 安装，不提供 RAG。这与实际报错 "this release's `alphaavatar setup` does not offer it" 一致。

### 3.4 其他

- Google embedding 改为通过 `credential()` 读 key：环境、`.env`、保存值，空白视为缺失，与 OpenAI 的写法一致。原来交给库自己读环境变量，空白值不会被当作缺失。
- 现有入口：`alphaavatar setup` 的问答在本地模型之后新增 ENV Memory 的开关，现有问题改为生成新的 `Selection`。按组件选择 Provider 的菜单在批次 3。
- 文档：`docs/cli/setup.md` 写明 ENV 开关、关闭后保留设置且不需要凭据，以及凭据只问一次；`docs/cli/config.md` 修正了工具说明。

### 3.5 测试

- `avatar-host/tests/setup/test_choices.py`：原有测试迁移到新的决策；开关组合从 16 种增至 32 种，加入 ENV。新增：
  - `test_speech_out_keeps_the_settings_its_implementation_and_model_take`：`gpt-4o-mini-tts`、`tts-1`、`tts-1-hd`、Voice.ai 四种，配置都能加载，instructions、语速、声音和说明注释都符合规则；
  - `test_a_setting_speech_out_does_not_take_is_refused_by_name`；
  - `test_env_memory_off_keeps_its_settings_runs_nothing_and_asks_no_google_key`：ENV 关闭后设置保留、不运行；只有其他部分用 Google 时才问 Google key；ENV 只接受 Google；
  - `test_each_part_takes_its_own_provider_and_model_and_each_key_is_asked_once`：
    - Loop 用自建服务器，Memory 用 Anthropic，tool 用 OpenRouter，Persona 和 Embedding 用 Google，ENV 保持 Gemini；
    - 凭据逐个核对，start 解析出的依赖与计划一致；
    - 每个 Provider 用虚构的 key 构造，确认读到了 key；Google key 为空白时，embedding 拒绝启动；
  - `test_a_part_that_reuses_another_s_model_writes_it_out_for_each`；
  - `test_a_changed_profile_keeps_every_other_setting_comment_and_blank_line`，三组选择：
    - 整行注释和空行按顺序不变；
    - 行尾注释除了被说明替换的，全部保留；
    - 没有设置丢失；缩进每层两个空格；
    - 变化只出现在所选的设置上。
- `avatar-host/tests/cli/test_setup.py`：脚本化问答多一个 ENV 的回答。新增 `test_env_memory_switched_off_asks_no_google_key_and_keeps_its_settings_to_switch_on`：真实跑一遍 Setup，回答 ENV 为 n，没有出现 Google 的问题，写出的 Memory profile 中 ENV 关闭、设置和注释保留。服务器 key 的测试把终端加宽到 1000 列，因为用途说明变长后，问题会折行。
- 变异测试（仓库外加载修改过的模块），9 个全部被发现：
  - instructions 对所有模型都保留；
  - 继承的 instructions 不清除；
  - ENV 关闭仍问 Google key；
  - ENV 关闭仍运行；
  - ENV 接受任意 Provider；
  - 改写时丢掉行尾注释（起初没被发现，补上行尾注释的检查后被发现）；
  - Voice.ai 语速不检查；
  - Google embedding 交给库读 key；
  - 凭据不去重。

### 3.6 验证

- 相关测试：configs、setup、CLI、Agents、Foundation 插件、Memory、Persona，共 753 passed。
- 离线全量：1052 passed（批次 1 为 1008 个，加上新增和参数化后多出的 44 个），47 warnings，367 s；运行前后，未跟踪和被忽略的文件一致。
- 仓库规范：`uv lock --check`、`check_workspace.py`、`ruff check .`、`ruff format --check .`（794 个文件）、`git diff --check` 都通过。

### 3.7 剩余事项

- 按组件选择 Provider 和模型的问答、方向键菜单、完整的交互流程和 PTY 验证，在批次 3。现在的 CLI 只问开关、ENV、向量库，以及 OpenAI 或自建服务器。
- 安装器配色在批次 4；已有 Bundle 的保护、Embedding 变更检查、新候选包的真实安装和 Setup 验证在批次 5。
