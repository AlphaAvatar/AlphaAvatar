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
| 2 | 统一的配置决策：能力开关、按组件选 Provider 和模型、TTS 兼容性、依赖、凭据、摘要；保留注释的写入 | 已提交（`b14b5894`）；审查发现的两处已修复（§4.1、§4.2） |
| 3 | 交互流程：能力 → Provider 和模型 → 凭据 → 摘要 → 安装；方向键列表和编号回退；PTY 验证 | 完成，待审查（§4） |
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

## 4. 第二批的审查修复与批次 3（基线 `b14b5894`）

依据：用户对 `b14b5894` 的审查。先修两处问题，回归通过后继续第三批的交互流程，并用真实 PTY 验证。

### 4.1 Voice 关闭后，自选的 STT/TTS 被重新启用

- 原因：`_changes()` 先按 `voice=False` 写 `plugin: null`，随后又无条件写入非默认实现，覆盖了关闭结果。于是 YAML 启用了 STT/TTS，摘要却显示 Voice off，依赖和凭据里也都没有语音。
- 修复：`Selection.speech()` 在 Voice 关闭时返回 None。凭据、摘要、YAML 都从它取值，三个 plugin 的启停只由 Voice 决定。选过的模型、声音、服务器写在原处，注释注明重新开启时用哪个实现，例如 `plugin: null  # Voice off; openai_realtime turns it on.`。
- 回归 `test_voice_off_runs_no_speech_whatever_was_chosen_for_it_and_keeps_the_choice` 覆盖三种情况：非默认 STT、非默认 TTS、两者都选。检查的内容：
  - 最终 YAML 和实际解析出的能力；
  - 依赖、凭据、摘要；
  - 同样的选择打开 Voice 后照选运行。

  这个测试在推送版本上 3 个参数全部失败。

### 4.2 Google Embedding 的 Vertex/ADC 认证

- 原因：批次 2 让 `_create_google_embedding` 在进入 SDK 之前无条件要求 `GOOGLE_API_KEY`，原本有效的 Vertex/ADC 配置（`vertexai: true`、`project`）因此被提前拒绝。
- 依据锁定的 `langchain-google-genai==4.2.5`，它判断是否走 Vertex AI 的顺序是：
  1. `vertexai` 设置；
  2. 否则看 `GOOGLE_GENAI_USE_VERTEXAI`；
  3. 否则有 `project` 或 `credentials` 就走 Vertex。

  Vertex 由 SDK 自己认证，不需要 API key；Gemini Developer API 必须有 key。SDK 同时读 `GEMINI_API_KEY`。
- 修复：
  - 新增 `_vertex(kwargs)`，按上述顺序判断；
  - API key 照旧按项目规则读：明确给出的 `api_key`、`google_api_key`，否则 `credential(api_key_env)`，空白视为缺失；没有另起变量名时也读 `GEMINI_API_KEY`；
  - 有 key 就交给 SDK；没有 key 且不走 Vertex 时才报缺失；
  - 没有新增 Setup 的 Vertex 菜单。
- 回归 `avatar-plugins-provider/tests/test_google_embedding.py`，6 个用例，覆盖：
  - 普通 key、自定义 `api_key_env`、设置里给出的 key、`GEMINI_API_KEY`；
  - 空串和空白，在构造任何客户端之前就拒绝；
  - Vertex 的三种进入方式：`vertexai: true`、只给 `project`、环境开关。

  SDK 的 `Client` 换成了记录参数的替身，不连接 Google。这组测试在推送版本上 4 个失败。

### 4.3 交互流程（`cli/commands/setup.py`）

- 步骤：
  1. Capabilities：先问开关和向量库，再说明工具：Tools 默认关闭；启用 DeepResearch 或 MCP 要在 tools profile 里打开后运行 `alphaavatar setup <bundle>`；本版 setup 不安装 RAG。最后问 Bundle 名称和 Avatar ID。
  2. Models：每个运行中的部分先选 Provider，再接受默认模型或填写模型。
  3. Credentials。
  4. Install：先显示摘要和计划，确认后安装。
  5. Validate。

  已有 Bundle 用同样的编号，第 2 步显示"As the bundle's settings choose them"。
- 列表：
  - 新增 `Report.choose(question, options, default)`，放在 `cli/render.py`，与 `ask` 并列，没有新建模块；
  - 在终端里是列表：方向键移动；输入文字筛选出包含它的选项，Escape 清空，Backspace 删字；Enter 选中；默认项先被标记，并注明 `(default)`；
  - `TERM=dumb`、`NO_COLOR`、没有终端控制时改为编号：输入数字，或只有一个选项包含的文字，Enter 取默认；无效输入会提示并重问；
  - 列表用 cbreak 模式，Ctrl+C 仍然中断。Ctrl+D 或输入结束报"The input ended; nothing was enabled"，退出码 1。不论怎样结束，都恢复终端设置并重新显示光标；
  - 每行按终端宽度截断，避免折行后重绘错位。
- 规则仍在 `tools/setup/choices.py`，CLI 只负责问答和展示：
  - `default_model(part, provider, server)`：只在参考配置自己的 Provider 下给出参考模型；换了 Provider 或自建服务器，没有默认模型，必须填写；
  - `REUSE` 和 `reusable()`：Memory、Tool memory、Persona 可以沿用前面已选的对话类模型（`As for memory: …`），前提是该部分接受那个 Provider；ENV（音视频）和 Embedding 不参与沿用；
  - `TOOLS`：工具说明，step 1 和摘要用同一句；
  - `SPEECH_SERVED`：自建语音服务器对应的实现，识别为 `openai_segment`，合成为 `openai`；`Transcription` 和 `Synthesis` 对其他组合直接拒绝。
- 跳过无关问答：
  - ENV 关闭时不问它的模型，也不要 Google key；
  - Voice 关闭时不问语音的 Provider、模型、声音、语速；
  - Voice.ai 不问语速，声音 ID 可以留空；
  - 不读 instructions 的模型给出说明。
- 服务器：后面的部分默认填入前面输入过的地址。语音只沿用满足语音要求的地址（非本机须 `https://`）。
- 名称：交互输入的名称已被占用时提示并重问；用 `--name` 给出的仍然直接拒绝。
- 摘要的位置不变：问答和凭据之后、安装依赖之前。摘要多了一项：TTS 不读 instructions 时注明"no instructions"。

### 4.4 验证中发现的已有缺陷（基线之前就存在）

- **交互选择 Qdrant 必然失败**，除非 `QDRANT_URL` 事先已经设置：
  - 原因：凭据步骤之前，Setup 为了取 `host.rtc` 解析了整个新 Bundle，`${oc.env:QDRANT_URL}` 在被询问之前就报缺失。`5bc91176`、`1cb5c828`、`b14b5894` 都有这个问题，是 PTY 走完整流程时发现的；它阻塞了一个可选项，所以本批一并修复；
  - 修复：`_host(texts, name)` 只读新 Bundle 的 host profile（Setup 从不修改它），不再解析 Avatar 的各部分；
  - 原来的整体解析还顺带从 `.env` 和保存的凭据里补全 Bundle 引用的变量。这一步现在由 `fill_configured` 对要询问的变量显式完成，所以 `.env` 或保存的值仍然显示"Enter keeps it"；
  - 回归 `test_voice_off_asks_nothing_of_speech_and_vectors_in_qdrant_read_its_url`：问到 URL 后启用成功，YAML 里只有 `${oc.env:QDRANT_URL}`，不出现输入的地址；`.env` 里有值时 Enter 保留。
- `_server` 用 `str.capitalize()`，把"API root"显示成"api root"，改为只把首字母大写。
- 批次 2 的一个测试用例组合了 `openai_realtime` 和自建 http(s) 服务器。实际上 realtime 通过 WebSocket 连接 `wss://…/realtime`，这个组合不能运行。用例改为 `openai_segment`，限制写入 `Transcription`。

### 4.5 测试

- `tests/cli/test_render.py`：
  - 编号回退：越界、多个选项都包含的文字、唯一匹配、Enter、数字；
  - 真实 PTY（`pty.openpty` 加子进程，子进程把它设为控制终端）共 8 种：Enter 取默认；向下越过末尾回到开头；向上；输入筛选；Backspace 放宽后标记不变；无匹配时 Enter 无效，Escape 清空；Ctrl+C；Ctrl+D。每种都检查：
    - 列表显示期间终端处于不回显、逐键读取的模式，且 ISIG 打开；
    - 结束后终端设置恢复，光标重新显示；
  - 24 列的窄终端：每行都不超过宽度。
- `tests/cli/test_setup.py`：
  - 新增 `Person`：按问题文字回答，其余回车，并记录所有提示；原有的顺序队列全部迁移过来；
  - 新增 `test_each_part_is_asked_its_provider_then_its_model_and_each_key_once`，选择组合为：Memory 用 Anthropic，Tool memory 沿用 Memory，Persona 用 OpenRouter，Embedding 用 Google，STT 用 realtime，TTS 用 Voice.ai。检查：
    - 默认模型只出现在参考 Provider 下；
    - Voice.ai 不问语速；
    - 每个 key 只问一次，并列出读它的部分；
    - 摘要在凭据之后、安装之前；
    - 写出的 Bundle 按回答运行；
  - Ctrl+C 停在名称或 Provider 列表、输入在模型问题处结束：都不写任何文件，退出码分别为 130 和 1；
  - 已被占用的名称会重问，`--name` 直接拒绝；
  - `setup <bundle>` 安装成功后，被编辑过的 Bundle 的配置文件逐字节不变；
  - 测试包的 catalog 改为包含 Setup 提供的全部依赖，Qdrant 因此能规划。
- `tests/setup/test_choices.py`：`default_model`、`REUSE`/`reusable`、`SPEECH_SERVED` 的规则各有一个测试；Voice 关闭的交叉回归见 §4.1。
- 变异测试（仓库外加载修改过的模块，PTY 子进程通过 `sitecustomize` 加载同一个变异）。以下 15 个全部被发现：
  - 换 Provider 后沿用默认模型；不提供沿用；
  - ENV 关闭仍问模型；Voice 关闭仍问语音；
  - 占用的名称不重问；不处理输入结束；
  - 询问凭据前解析整个 Bundle（即 §4.4 的缺陷）；不从 `.env` 和保存值补全；
  - 不恢复终端；光标保持隐藏；输入不筛选；编号模式不认文字；忽略 Ctrl+D；
  - realtime 接受自建服务器；行不截断。

  另外，推送版本的 `_changes` 和 Google embedding 分别在 §4.1、§4.2 的回归上失败。

### 4.6 真实终端验证

- 交互流程：
  - 方法：把 Setup 放进真实 PTY（`pty.fork`，TERM=xterm-256color），对着替身包运行，和 CLI 测试一样：不下载，`enable()` 照常写入；
  - 屏幕用 VT 模拟器 pyte 还原，pyte 装在仓库外的临时 uv 环境里；
  - 每个用例都检查：退出码、终端设置是否恢复、光标是否显示、是否有残留进程、HOME 下是否写了文件。

| 用例 | 结果 |
|---|---|
| 完整流程：方向键、筛选、沿用、Qdrant、Voice.ai，问完凭据后安装 | 退出码 0，按回答写出 Bundle |
| `TERM=dumb`：编号模式，越界和歧义文字重问，用文字选中 Qdrant 和 Google；换 Provider 后模型必须填写 | 拒绝安装，退出码 1，屏幕上没有控制字符，未写文件 |
| `NO_COLOR` 下编号模式里按 Ctrl+C | 130 |
| 列表中 Ctrl+D | 1，提示"The input ended" |
| 文本问题中 Ctrl+D | 1 |
| 列表中 Ctrl+C | 130 |
| 列表显示时收到 SIGTERM | 143 |
| 12 行的终端：列表在底部滚动、反复重绘 | 屏幕上始终只有一份列表，标记正确 |
| 无效的服务器地址和语速（`fast`、`9`）被重问；占用的名称重问；后续部分沿用服务器；`tts-1` 写成 `instructions: null` | 0 |

  以上用例的终端设置都恢复了，光标都重新显示，没有残留进程，除第一行和最后一行外 HOME 下都没有写文件。

- 安装器接续 Setup：
  - 包：`b14b5894` 的 CI 包，Linux package 运行 45153808355，artifact 14808086639；`SHA256SUMS` 全部 OK；
  - 包里的这三个 Host 文件先确认与 `b14b5894` 一致，再替换为本批版本，删除对应的 `.pyc` 后重新打包；
  - `install.sh` 与仓库里的文件逐字节一致。在隔离的 HOME 中通过管道交给 bash（`cat install.sh | bash -s -- --file …`），在 PTY 里运行；
  - 回答安装器的询问后，Setup 经 `/dev/tty` 接收真实输入：方向键、输入筛选（`qd` 选中 Qdrant，`goo` 选中 Google）、沿用、凭据都正常。在"Install and enable?"回答 n，Setup 退出码 1，安装器报"Setup: did not finish (exit 1); AlphaAvatar stays installed"，自身退出码 0；
  - 另一次在列表中按 Ctrl+C：Setup 退出码 130，安装器继续给出报告，退出码 0；
  - 两次都检查了：终端设置恢复，光标显示，没有残留进程，没有写入配置或凭据，输入的密钥没有出现在任何文件里；
  - 中途另有一次因为脚本出错，在问答中途断开了 PTY：挂断后安装器和 Setup 都已退出，没有残留进程。
- 屏幕记录和脚本都放在仓库外（`$CLAUDE_JOB_DIR/tmp/pty`）。

### 4.7 验证

- 相关测试：全部 Host 测试、provider 插件、voice 插件、Agents 配置，共 662 passed。
- 离线全量：最终代码上 1079 passed，47 warnings，371 s；运行前后，未跟踪和被忽略的文件一致。
- 最终代码上，§4.6 的 PTY 用例和两次安装器接续又全部重跑了一遍，结果相同。
- 仓库规范：`uv lock --check`、`check_workspace.py`、`ruff check .`、`ruff format --check .`、`git diff --check` 都通过。
- 推送 SHA `b14b5894` 的 CI：Quality（45153808150）和 Linux package（45153808355）都是 success。`1cb5c828` 的 Quality 失败，原因是离线测试超过 10 分钟被中止，不是用例失败。

### 4.8 未验证与剩余

- `docs/cli/cli.html` 里的 Setup 画面仍是旧流程，没有重新录制。安装器配色在批次 4 完成后，再一并重录。
- 方向键列表在 PTY 加 pyte 中验证过，没有在具体的终端程序（GNOME Terminal、iTerm2、tmux 等）里由人操作过。
- 安装器验证用的是替换了三个文件的 CI 包，不是新构建的候选包。在"Install and enable?"处回答了 n，没有下载、安装 wheel，也没有运行真实的 `config check`。新候选包的完整验收在批次 5。
- 没有调用任何模型或远程服务。
- 已有 Bundle 的保护和 Embedding 变更的检查在批次 5。
