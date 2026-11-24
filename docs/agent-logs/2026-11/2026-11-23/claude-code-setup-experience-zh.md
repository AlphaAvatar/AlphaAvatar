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
| 3 | 交互流程：能力 → Provider 和模型 → 凭据 → 摘要 → 安装；方向键列表和编号回退；PTY 验证 | 已提交（`3e5b8e2d`）；审查发现的两处已修复（§5.1、§5.2） |
| 4 | 安装器输出的颜色和分组；`cli.html` 的 Setup 画面 | 已提交（`01200003`），通过审查 |
| 5 | 已有配置的保护、Embedding 变更检查、文档、新候选包的真实验证 | 已提交（`e300619e`）；第一轮审查的四处修复已提交（`a9b2081a`，§7）；第二轮复核的 KD-60、KD-61 已修复，候选包已重建并复验，待审查（§8） |

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

## 5. 第三批的审查修复与批次 4（基线 `3e5b8e2d`）

依据：用户对 `3e5b8e2d` 的审查。先修两处边界问题，再做安装器输出的优化，并更新 `docs/cli/cli.html` 里过时的 Setup 画面。

### 5.1 列表结束时的终端恢复窗口（`cli/render.py`）

- 原因：`_listed()` 的 `finally` 先显示光标，再调用 `termios.tcsetattr()` 恢复终端。TERM、HUP、INT 的处理函数在两步之间抛出异常时，恢复被跳过，退出后 `ICANON`、`ECHO` 仍是关闭的。
- 修复：`finally` 第一件事就恢复终端属性。恢复期间信号的处理函数抛出的异常先暂存，属性再恢复一次，光标显示之后才重新抛出。光标的写出改由 `_show_cursor()` 负责，写不出去（`OSError`、`ValueError`）时忽略，报告的仍是列表结束的原因。退出码保持原样：TERM 143，HUP 129，INT 130。
- 回归 `test_a_signal_as_a_list_ends_never_leaves_the_terminal_unrestored`：
  - 4 个注入点（恢复前、恢复后、显示光标前、显示光标后）× 3 种信号，共 12 种；
  - 子进程在真实 PTY 里打开列表，按 Enter 后在注入点给自己发信号；父进程一直持有 PTY，子进程退出后先读终端设置，检查退出码，以及设置与开始前一致、`ICANON` 和 `ECHO` 打开。
- 另有 `test_a_cursor_the_terminal_takes_no_more_of_leaves_its_settings_restored`：光标写出失败，属性照样恢复，选择照常返回。
- 用 `3e5b8e2d` 的 `render.py` 跑这 13 个用例：10 个失败（恢复前、显示光标前、显示光标后各 3 种信号，以及光标写出失败）。恢复后注入的 3 个在旧代码上也通过，因为旧代码的恢复本来就是最后一步。

### 5.2 Vertex 判断与 SDK 的布尔解析不一致（`langchain/embeddings/models.py`）

- 原因：`_vertex()` 用 `bool(vertexai)`，把 `"false"`、`"0"`、`"no"` 都当成 True。例如 `vertexai: ${oc.env:USE_VERTEXAI}` 在 `USE_VERTEXAI=false` 时，项目以为走 Vertex，跳过了 key 检查；SDK 实际走 Developer API，又从环境里读到空白的 key 并构造客户端。
- 依据：锁定的 SDK 中 `vertexai` 是 pydantic 的 `bool | None` 字段。离线对照确认：
  - `"false"`、`"0"`、`"no"`、`"off"`、`"False"`、`False`、`0` 都解析为 False，并且即使给了 `project` 也走 Developer API；
  - `"true"`、`"1"`、`"yes"`、`"on"`、`True`、`1` 都解析为 True；
  - `"maybe"` 由 SDK 以 `vertexai` 字段名报 ValidationError。
- 修复：用 `TypeAdapter(bool | None)` 按同样的规则解析。不是布尔值时交给 SDK 自己按字段名报错，在读 key 之前。环境开关和 `project`/`credentials` 的判断不变。
- 回归，在原有 6 个之外新增 28 个：
  - 7 种"关闭"写法 × 缺失、空串、空白 3 种 key 状态：在项目层按变量名拒绝，不构造客户端；给出有效 key 后照常使用 Developer API；
  - 6 种"开启"写法：环境里只有空白 key 时，仍用 Vertex 自己的认证；
  - 无效值：由 SDK 按字段名拒绝。
- 用 `3e5b8e2d` 的版本跑：15 个失败，即 5 种字符串写法 × 3 种 key 状态。布尔 False 和 0 在旧代码里本来就正确。

### 5.3 编码规范

- 按用户要求，`docs/coding-conventions.md` 新增"Function bodies"一节：
  - 函数内作用明显不同、或各占数行的代码块之间空一行；
  - 注释不是必须的，只在一块明显独立、用途又不能从代码看出时才加一句短注释，不重复代码或 docstring；
  - 示例用 `_vertex`，shell 脚本同样适用。
- `AGENTS.md` 与 `AGENTS-zh.md` 的第 18 节各加一条，文档索引的描述同步更新。
- 本批改到的代码按这条整理：`_vertex`、`_listed` 的循环和清理、`install.sh` 新增的函数。

### 5.4 批次 4：安装器输出（`packaging/linux/install.sh`）

- 结构，与 Python CLI 的报告一致：
  - 标题 `AlphaAvatar / Install`；
  - 编号步骤：`01 Package`（版本、build ID、SHA-256 校验）、`02 Check`（glibc，能否在本机运行；已安装的版本会注明）、`03 Install`（安装位置和 current）、`04 PATH`（每个启动文件一行）；
  - `OK    AlphaAvatar <版本> installed`，下面列出 Build、Command、Current；
  - 有警告时用 `WARN` 行：旧版本 Setup 环境装的能力，以及 PATH 有启动文件没配置上；
  - Setup 的结果单独一行：`OK    Setup done`、`WARN  Setup did not finish (exit N); AlphaAvatar stays installed`、`WARN  Setup cancelled; not run`、`SKIP  Setup not run`；
  - `Next` 下列出命令（青色），说明在后面（暗色）：本终端用的 `source ~/.bashrc`，配置失败时是 `export PATH=…`，还没运行 Setup 时是 `alphaavatar setup`。
- 进行中：终端上，当前步骤的行先以 signal cyan 显示，完成后原地换成结果行；下面有内容时（最新 release、下载地址、curl 的进度条），这一行保留。
- 失败：`FAIL  Not installed` 和原因写到 stderr，与上面的步骤空一行隔开；stdout 上停在出错的那一步。
- 被信号中断，或 `set -e` 处的意外失败，以前什么都不输出。现在在 stderr 写一行，说明哪个版本是 current：
  - `WARN  Interrupted` 或 `WARN  Stopped`，后接 `<旧版本> stays current`、`AlphaAvatar X is current, its PATH and setup not reached` 或 `nothing is installed`；
  - 意外失败写 `FAIL  Not installed (exit N); …`；
  - 终端已经挂断时，写不出去也不影响退出。
- 颜色：
  - 规则与 `log/format.py` 的 `use_color` 相同：设置了 `NO_COLOR`（空值也算）或 `TERM=dumb` 时不着色，否则只在终端上着色；
  - stdout、stderr 各自判断，所以 `curl … | bash` 的 stdin 是管道，输出到终端时照样着色；
  - 配色同 Python CLI：标题品牌蓝，进行中和命令 signal cyan，OK 绿，WARN 黄，FAIL 红，SKIP 和说明暗色；
  - 版本、build ID、路径和结果保持普通颜色。
- 路径以 `~` 显示，复制用的命令用 `printf %q` 加引号。`·` 只在 locale 为 UTF-8 时使用，否则用 `-`。
- 没有改动的行为：下载与校验、整段读取保护、来源规则、安装锁、暂存归属、信号处理、PATH 块，以及 Setup 的接续和读取进程。在问题处按 Ctrl+D 时，现在先换行，结果另起一行。没有新增任何依赖（不用 tput、Python、Node）。
- `docs/DEPLOY.md` 加了一段介绍报告的格式，`source` 的提示改为指向 `Next` 下的那一行。
- 列表的提示：问题旁放不下完整提示时，先改用短提示 `↑↓, type, Enter`，仍放不下才不显示；以前在 72 列下直接不显示。

### 5.5 `docs/cli/cli.html`

- `scripts/docs/cli_preview.py` 的 `screen()` 新增支持列表重绘用到的光标上移、清除以下内容和隐藏/显示光标。以前列表的每次重绘都会叠在画面里。
- 录制：
  - 用 `3e5b8e2d` 的 CI 包（`0.6.8-3e5b8e2d9b2a`，artifact 14816175831，`SHA256SUMS` 全部 OK），在空 HOME 里，于真实 PTY 中录制；
  - 机器为 Alibaba Cloud Linux 3，glibc 2.32；凭据都是虚构的；
  - 安装器用本批的 `install.sh`；Setup 用 `--artifacts` 给出 CI 的 wheel，真实下载、安装并校验。
- 新增两个面板：首次安装（拒绝 Setup）、`NO_COLOR` 下再次安装。
- 重录六个 Setup 面板：
  - 新 Bundle：85 个包，212 MB，Validate `PASS · 3 runners`；
  - `setup reference`：105 个包，515 MB，`PASS · 8 runners`；
  - 本版不安装的选择；
  - 拒绝计划；
  - 在 Provider 列表处按 Ctrl+C；
  - `NO_COLOR`。
- 由一个拼接脚本只替换这些 section 和目录项，其余 config、Doctor 面板原样保留。页面开头的说明同时写明了两批面板各自的录制条件；`cli_preview.py` 模板里的同一段同步修改。
- 页面里没有本机路径（用 `/home/tester` 和 `DIR` 遮盖），没有转义字符，除了虚构的 LiveKit 地址没有任何凭据值。

### 5.6 测试

- `tests/setup/test_install_script.py`：
  - 输出断言迁移到新的结构：新增读取步骤结果的 `told()`、读取 `Next` 的 `next_steps()`，以及 `shown()`；
  - 新增 `test_piped_to_bash_a_terminal_gets_the_report_in_color_and_the_same_without`：README 里的 `curl | bash` 在真实 PTY 里运行，分 `xterm-256color`、`NO_COLOR=""`、`TERM=dumb` 三种。三种的画面逐行等于同一份报告；只有第一种带颜色，并检查标题、步骤原地替换、OK、SKIP、命令、说明和问题的颜色，Build 行保持普通颜色；
  - 新增 `test_a_failure_is_said_on_stderr_apart_and_names_the_step_it_ended`、`test_a_terminal_s_stderr_gets_its_failure_in_red`；
  - 信号用例（13 个）断言 stderr 最后一行说明哪个版本是 current；删除失败的用例断言 `FAIL` 行。
- `tests/cli/test_render.py`：信号和光标的 13 个用例（§5.1），短提示用例。
- `provider/tests/test_google_embedding.py`：§5.2 的 28 个。
- 变异测试，都从仓库外加载，安装器的变异通过 pytest 插件替换 `SCRIPT`：
  - 安装器 9 个，全部被发现：按 stdin 判断颜色、忽略 `NO_COLOR`、空的 `NO_COLOR` 仍着色、`TERM=dumb` 仍着色、提前结束不报告、失败不空行、问题行不换行、OK 不着色、步骤不原地替换；
  - 另有 §5.1、§5.2 中用推送版本跑的对照。

### 5.7 验证

- 相关测试：全部 Host 测试和 provider 插件测试，661 passed。
- 离线全量：1126 passed，47 warnings，376 s；运行前后，未跟踪和被忽略的文件一致。
- 仓库规范：`uv lock --check`、`check_workspace.py`、`ruff check .`、`ruff format --check .`（795 个文件）、`bash -n`（build.sh、install.sh）、`git diff --check` 都通过；pre-commit 没有改动任何文件。
- shellcheck（仓库外的临时环境）：新版只剩推送版本原有的一个 SC2046；两处有意打印的 `~` 标注了 SC2088。
- 安装器接续 Setup，用本批 `install.sh` 加 `3e5b8e2d` 包，在 PTY 中重跑：通过终端回答到 "Install and enable?" 再拒绝，以及在列表中按 Ctrl+C；两次的终端设置都恢复，光标显示，没有残留进程，没有写入文件。
- 推送 SHA `3e5b8e2d` 的 CI：Quality（45168132516）和 Linux package（45168132617）都是 success。

### 5.8 未验证与剩余

- 安装器的颜色在 pyte 和 PTY 中验证过，没有在具体的终端程序里由人看过。没有测试 macOS 自带的 bash 3.2（安装器只面向 Linux）。
- `cli.html` 的面板录自 `3e5b8e2d` 包，其中不含本批的 `render.py` 修改。这些修改不改变最终画面：列表结束时会被擦掉，提示不留在画面上。
- config 和 Doctor 的面板没有重录。
- 第五批：Embedding 变更保护、已有 Bundle 的保护、新候选包的完整安装验收。

## 6. 批次 5：已有配置与数据的保护、最终候选包验收（基线 `01200003`）

依据：用户对第四批的审查。本批要求：
- 核对基线 CI；
- 核对已有 Bundle、共享 profiles 和凭据的保护；
- 完成 Embedding 变更保护；
- 构建最终候选包，在干净环境中做安装、真实 Setup、升级和 cleanup 的验收。

### 6.1 基线

- `01200003` 的 Quality（45180883862）和 Linux package（45180883949）都是 success。
- 本批改了生产代码，没有提交，对应的 CI 要等用户提交推送后再核对。

### 6.2 已有 Bundle、共享 profiles 与凭据

- 先核对了现有实现，以下保护都已经存在，直接复用：
  - `setup <bundle>` 不写任何 profile，只在成功后修改默认 Bundle；
  - `create_bundle` 遇到任何已存在的目标文件都拒绝，失败时只删除自己创建的文件；
  - 同名 Bundle 会被拒绝；
  - 已存凭据只在第二次回答 yes 时才替换；
  - 安装失败或取消时，current、Bundle、设置、凭据都保持原样。
- 补上的缺口：Setup 检查名称时只看 Bundle 文件。以前 `profiles/<名称>/` 已经存在时（例如被另一个 Bundle 引用），要等全部问完、下载并安装之后，才在 `enable` 时报 `FileExistsError`；安装会回滚，但人白白答完了全部问题。
  - 修复：新增 `template.taken()`，返回新 Bundle 会覆盖的位置：Bundle 文件或同名的 profiles 目录。交互输入的名称撞上时提示后重问；用 `--name` 给出的直接拒绝，不问任何问题。`create_bundle` 自己的拒绝仍保留，作为最后一道检查。
- 新增回归：
  - `test_a_name_whose_profiles_exist_is_never_written_over_even_shared`：共享的 profile 逐字节不变；在推送版本上失败；
  - `test_an_existing_bundle_set_up_again_keeps_every_file_as_a_person_left_it`。场景：手动改过模型、TTS 语速和注释，Memory 共用另一个 Bundle 的 profile 并关闭了 ENV，另一个 Bundle 是默认并存有凭据。检查：
    - 只问"Install and enable?"，不重新问卷；
    - 取消、失败、成功三种情况下，所有配置文件逐字节不变；
    - 设置和凭据文件不变，只有成功时默认 Bundle 改变；
    - 运行时读到的正是这些修改。

    这个测试在推送版本上也通过，说明这部分保护原本就成立。

### 6.3 Embedding 变更保护

- 现状（先做了一次只读梳理）：
  - 没有任何地方记录向量出自哪个 Embedding 模型。维度只隐含在 LanceDB 的 `vector` 列类型或 Qdrant 的 `VectorParams.size` 里。
  - 启动时探测出的维度只用于新建表，打开已有表时不比较。
  - 因此换成维度相同的另一个模型时，Memory、Persona profiler、MCP 在 LanceDB 和 Qdrant 上都会静默混用两个模型的向量。维度不同时要到写入或搜索时才失败；只有 Persona 的 Qdrant profiler 在启动时由库自己报错。
  - Memory 的 SQLite 是权威数据，向量是投影，没有重建索引的路径。
  - 说话人向量的集合名带模型后缀，人脸和说话人用的是固定模型，不在本批范围内。
- 保护放在向量存储层 `agents/utils/vdb/`。新增 `space.py`：
  - `EmbeddingSpace` 由 provider、model、要求的输出维度（`extra.dimensions` / `output_dimensionality`）和实测维度组成。key、key 的变量名、服务器地址都不算在内，所以轮换凭据不会被当成换了向量空间。
  - 记录写在存储旁边：LanceDB 是表旁的 `<table>.embedding.json`；Qdrant 是伴随集合 `<collection>__embedding` 里的一个点，因为锁定的 qdrant-client 1.15.1 不支持集合元数据。
  - `claim()` 是两个后端共用的判断，在写入任何东西之前完成：
    - 存储不存在：创建，并记录配置的空间；
    - 有记录、但空间不同：拒绝，什么都不改；报错写明两边的模型，并建议给 `<setting>` 换一个名字作为独立索引，或换回原来的 Embedding；
    - 没有记录、但表是空的：记录为配置的空间；
    - 没有记录、表里有向量（本版之前建的）：维度不同就拒绝；维度相同只能当作配置的模型接收，记录标为 `assumed`、记一条警告说明无法核实，之后的更换照样能查出来。
  - 不提供自动删除、重建或迁移。
- 接入的五处：
  - Memory：LanceDB、Qdrant；
  - Persona profiler：LanceDB、Qdrant；
  - MCP：LanceDB。

  每处都先检查，再走原有的 `ensure`，例如 Memory 的 Qdrant 仍会为已有集合补建索引。
- Setup 复用这一结果：`recorded_conflicts()` 只读记录文件，不打开存储，也不需要 LanceDB，所以基础包也能运行。它扫描 Avatar 工作区的 `data/indexes/`，以及配置里显式给出的 `client_path`，按记录里的 setting 找到当前配置的存储名和 Embedding：
  - 新 Bundle：在凭据之前检查；
  - 已有 Bundle：在规划安装之前检查。

  局限：尚未询问模型，所以不比较实测维度；Qdrant 这类远端存储只在启动时检查。
- 文档：Memory README、`docs/avatar-workspace-layout.md`、`docs/cli/setup.md`。
- 测试：
  - `avatar-agents/tests/utils/test_vdb_space.py`，8 个，用真实 LanceDB 和内存 Qdrant：
    - 同一模型重开，key、变量名、服务器变化都接受；
    - 换模型（同维度）、改要求的维度、换维度，都拒绝，并且向量和记录逐行不变，之后用原模型照常打开；
    - 另起一个名字作为独立索引；
    - 本版之前建的表：空表被认领；维度不同拒绝；维度相同标为 assumed 并警告；
    - Qdrant 的同一套行为；
    - 只读记录的冲突判断：显式目录、改名、插件关闭的情况都覆盖。
  - `test_launch.py`：Memory 和 Persona 的 LanceDB runner 遇到换了模型的同维度表都拒绝启动，索引目录逐字节不变；轮换 key 的变量名仍能启动。
  - `test_a_bundle_naming_another_embedding_for_the_vectors_its_avatar_keeps_is_refused_first`：已有 Bundle 和新 Bundle 都在安装和凭据之前被拒绝，文件不变；改用独立索引后可以安装。
  - 变异 8 个，全部被发现：
    - 任何空间都相同；
    - 凭据算进模型；
    - 本版之前的表不查维度；
    - 不标 assumed；
    - 插件关闭仍检查；
    - Setup 不查；
    - 不查 profiles 名称；
    - Memory runner 不检查。
- 在干净环境中用候选包的代码复核了一遍（§6.6）。

### 6.4 未发布构建的限制不留到问答之后（O-33）

- 用户要求候选包的限制不能留到答完问题才发现。以前 CI 或本地构建的 Setup（包括安装器提供的那次）要等问完全部问题、开始下载时，才因为本构建的 wheel 没有发布地址而失败。
- 修复：
  - `Sources.own`：只有 release，或给了 `--artifacts`，才能找到本构建的 wheel；
  - Setup 对新 Bundle 在第一个问题之前拒绝；对已有 Bundle 在确认问题之前拒绝，计划可以直接复用已有环境时除外。报错写明 `alphaavatar setup --artifacts DIR`；`--plan` 不受影响；
  - 安装器读取 manifest 的 `release`。用 `--file` 安装、不是 release、且包旁有 wheel 时，提供的 setup 自动带上 `--artifacts <包所在目录>`，`Next` 里给出同样的命令；包旁没有 wheel 时，`Next` 给出 `alphaavatar setup --artifacts DIR`。
- 实现中发现并修正了两处安装器问题：
  - 没有 release 时，`$(…)` 会去掉末尾的空行，最后一个 `read` 读到输入结束，在 `set -e` 下退出；
  - PATH 步骤的循环变量 `file` 覆盖了 `--file` 的值，改名为 `startup`。
- 回归：
  - `test_a_build_that_is_no_release_needs_its_wheels_named_before_anything_is_asked`；
  - 安装器的 `test_a_build_that_is_no_release_offers_setup_its_own_wheels_from_beside_its_package`，两种情况：包旁有 wheel、包旁没有 wheel。

  两者在推送版本上都失败。CLI 测试的替身包改为 release；`docs/bugs-zh.md` 的 O-33 标注已处理；DEPLOY 和 setup 文档同步更新。

### 6.5 最终候选包

| 项 | 内容 |
|---|---|
| 源码 | HEAD `012000034544c301a2c163ee2acd0e35cbe716e7` 加未提交的工作区改动：21 个文件，`git diff` 的 sha256 前缀 `9be89d5f15a11874`。构建开始前和结束后核对过，跟踪文件的 diff 和未跟踪文件都与构建时一致 |
| 构建 | `packaging/linux/build.sh --allow-dirty --max-glibc 2.32`；uv 0.10.0（在仓库外的私有 venv 中）、Python 3.13.12；构建机为 Alibaba Cloud Linux 3（glibc 2.32），不是 CI 的 manylinux_2_28 |
| Build ID | `0.6.8-012000034544-dirty.20261123134847`；manifest 中 `release` 为 null，`commit` 为上述 HEAD，uv.lock sha256 `6e2c34f7…`（与 CI 相同） |
| glibc | 基础包 ≥ 2.17；本地编译的 llama-cpp wheel 需要 ≥ 2.32，所以构建时 `--max-glibc` 放宽到 2.32。CI 的构建以 2.28 为上限，这一差别只来自构建机 |
| 位置 | `~/alphaavatar-candidates/0.6.8-012000034544-dirty.20261123134847/`：基础包、`.sha256`、12 个 wheel、manifest、`install.sh`（与工作区逐字节相同）、`SHA256SUMS`；`acceptance/` 下是验收屏幕、结果、源码 diff 和构建日志 |
| SHA-256 | 包 `60ec733fa90f750164331fd6965e050fb872b1d88a13a7814e4aa155eab0795c`；manifest `27e853bd…0e0f62`；install.sh `02ff07ac…98`；SHA256SUMS `754a7ca2…0f`；`sha256sum -c SHA256SUMS` 全部 OK |

### 6.6 干净环境验收

- 环境：
  - Ubuntu 官方 `ubuntu-base-24.04.5` rootfs，校验和与 Ubuntu 公布的一致；glibc 2.39；
  - 由 bubblewrap 0.4.0 以普通用户 `tester` 运行，与本机只共享网络，以及只读挂入的两份构建目录；
  - 其中没有 python、node、uv、gcc/cc、curl；有 tput，但安装器不用。
  - 这是 Ubuntu 的用户态跑在本机内核 5.10 上，不是完整的虚拟机或镜像，没有 systemd。
  - 让 bwrap 忽略 SIGINT，再由 Ubuntu 的 `env --default-signal` 交还给沙箱内的命令，使 Ctrl+C 和普通终端上一样只到达安装器和 Setup。
  - 每个场景用独立的 rootfs 副本。
- 场景 1：安装器接续真实 Setup。
  - 用 `cat install.sh | bash -s -- --file …` 运行，与 `curl | bash` 一样 stdin 不是终端。
  - 第一次：在 Provider 列表处按 Ctrl+C。Setup 退出码 130，安装器报 "Setup did not finish (exit 130); AlphaAvatar stays installed"，自身退出码 0。终端设置恢复，光标显示，没有残留进程。
  - 第二次：用方向键在向量库列表上下移动，在 Memory 列表输入 `open` 筛选，其余全部接受默认，凭据都是虚构的。
    - 凭据：每个只问一次，没有回显，选择存储；
    - 摘要在问答之后、安装之前；
    - 真实安装 105 个包（514 MB），Validate `PASS · 8 runners`，共 72 秒；
    - 安装器报 `OK    Setup done`，`Next` 给出 `source ~/.bashrc`。
  - 之后：
    - `bash -l` 和 `bash -i` 都能找到命令；不读启动文件的 bash 找不到，说明 PATH 只来自启动文件。第一次检查时这一项曾显示找到了命令，之后 4 次都无法复现，原因未查明；
    - `config check avatar` 通过；
    - `doctor avatar --no-metrics` 退出码 0，只做静态检查，运行时诊断按 `--no-metrics` 标为未运行；
    - `config init ref` 写出的 12 个 profile 正文与 Setup 全部接受默认时写出的完全相同，只有每个文件第一行注释里的 profile 名称不同。
- 场景 2：代表性分支，都在同一个 root 里真实安装并校验。

| Bundle | 选择 | 结果 |
|---|---|---|
| own | ENV 关闭；Qdrant；对话用自建服务器 `qwen3-32b`；Memory、tool memory、Persona 通过筛选选"As for the conversation"；Embedding 用自建服务器 `bge-m3`，默认地址沿用前面输入的 | 只问服务器 key（输入 `none`）、OPENAI（语音）、LiveKit、Qdrant，没有问 Google；105 个包 / 427 MB，`PASS · 8 runners` |
| mixed | Voice 关闭；本机模型关闭；Memory 用 Anthropic；tool memory 沿用 Memory；Persona 用 OpenRouter；Embedding 用 Google（都通过筛选） | 没有语音问题；OPENAI、ANTHROPIC、GOOGLE、OPENROUTER 各问一次；保留当前环境已有的依赖；112 个包 / 521 MB，`PASS · 2 runners` |
| speech | STT 用 realtime `gpt-realtime-whisper`；TTS 用 `tts-1`，声音 alloy，语速 1.3 | 提示"tts-1 takes no instructions"；复用环境；`PASS · 8 runners` |
| voiceai | TTS 用 Voice.ai | 不问语速，提示"speaks at 1.0"；`PASS · 8 runners` |

  - 四个 Bundle 的 `config check` 都通过。
  - 每次运行的终端设置都恢复，光标显示，没有残留进程。
- YAML 检查，在宿主机上与随包模板比较：
  - 范围：场景 1 的 `avatar`、`ref`，场景 2 的四个，场景 4 的 `small`；
  - 检查内容：每个 profile 的注释行和空行按原顺序全部保留；缩进每层两个空格；所有 YAML 里都没有出现任何凭据值；
  - 变化只出现在所选的设置上：
    - ENV 关闭时只改 `environment.enabled`，设置保留；
    - Voice 关闭时三个 plugin 为 null，并注明重新开启用哪个实现；
    - Qdrant 写成 `${oc.env:QDRANT_URL}` 和 `${oc.env:QDRANT_API_KEY,null}`；
    - 自建服务器写入 `base_url` 和 `api_key_env: ALPHAAVATAR_SERVER_KEY_…`；
    - `tts-1` 和 Voice.ai 写成 `instructions: null` 并注明原因；Voice.ai 的 `speed: 1.0` 也带注明。
- 场景 3：基础包没有任何插件。
  - `config init` 写出 12 个 profile，每个都与包内模板完全相同；
  - `config check` 退出码 2，逐个列出缺失的插件，以及会安装它的 `alphaavatar setup all`；
  - `--non-interactive` 安装时，`Next` 给出 `alphaavatar setup --artifacts /srv/cand`。
- Embedding：用候选包环境中的代码（真实 LanceDB、独立的测试数据）复核：
  - 同模型、换 key 变量名：照常打开；
  - 换模型（同维度）、换维度：拒绝；
  - 之后用原模型打开：3 行数据都在；
  - 记录内容正确。

### 6.7 升级、准备失败、错误 SHA 与 cleanup

- 两份真实构建：
  - 旧版：CI 为 `01200003` 构建的包（`0.6.8-012000034544`，Linux package 运行 45180883949，artifact 14820508119，`SHA256SUMS` 全部 OK）；
  - 新版：§6.5 的候选包。
- 用旧版自己的 `install.sh` 安装，再用旧版的 Setup 建一个 Voice 关闭、本机模型关闭的 Bundle `small`（`--artifacts` 指向旧版的目录）。另在 Avatar 工作区写入 `records.sqlite3` 和用户 profile，作为独立的应用数据，并记录所有应用数据文件的哈希。

| 步骤 | 结果 |
|---|---|
| `upgrade --sha256 000…` | 退出码 1，"does not match its SHA-256"，报"0.6.8-012000034544 stays current"；current、versions、envs 与之前一致 |
| 准备失败：候选包第一次成功安装之前进行；把包和 `.sha256` 复制到没有 wheel 的目录后 `upgrade --file` | 包通过校验并解包，计划 77 个包；下载到本构建的第一个自带 wheel 时失败（"No such file or directory"），报"0.6.8-012000034544 stays current"；current 不变，解包的候选基础包已删除；`config check small` 通过 |
| `upgrade --file`（包旁有 wheel） | 77 个包 / 188 MB，`PASS · 2 runners`；current 切到新环境，旧版保留到 cleanup；`config check` 通过 |
| `cleanup --dry-run` | 列出旧环境和旧基础包，共 795 MB；`~/.local` 下所有文件的大小和修改时间前后一致，没有写入 |
| `cleanup` | 只删除旧环境和旧基础包；current 的环境和基础包保留；`config check` 通过；应用数据的哈希与升级前一致 |

### 6.8 验证

- 相关测试：Agents、Memory、Persona、Host 的 CLI、setup、configs，以及 provider、安装器，全部通过。
- 离线全量（机器空闲时）：1141 passed，181 warnings，379 s；运行前后，未跟踪和被忽略的文件一致。
  - 与构建同时运行的那一轮有 1 个失败：voice 插件的计时测试 `test_openai_segment.py::…[stall]`，耗时 2668 ms，上限约 800 ms，当时 16 核都在编译 llama-cpp。单独重跑 3 次全部通过；voice 插件本批没有改动。
  - warnings 增多来自 LanceDB `table_names()` 的弃用提示；现有的 `LanceDBClient.table_exists` 一直在用它，新测试调用得更多。
- 仓库规范：`uv lock --check`、`check_workspace.py`、`ruff check .`、`ruff format --check .`（797 个文件）、`bash -n`、`git diff --check` 都通过。shellcheck（仓库外的临时环境）只剩原有的一条 SC2046。
- CI：基线 `01200003` 都是 success；本批的改动尚未提交，没有对应的 CI。

### 6.9 给用户的候选包命令

未发布的候选包（CI 或本地构建）要用 `--file`，Setup 需要 `--artifacts`：

```bash
cd ~/alphaavatar-candidates/0.6.8-012000034544-dirty.20261123134847
sha256sum -c SHA256SUMS
bash install.sh --file ./alphaavatar-0.6.8-012000034544-dirty.20261123134847-linux-x86_64.tar.gz
# 在终端里回答 Y：安装器提供的 setup 会自动带上 --artifacts（本目录）
# 以后，或者另开终端：
alphaavatar setup --artifacts ~/alphaavatar-candidates/0.6.8-012000034544-dirty.20261123134847
```

- 已有安装时，这个包会成为 current（与升级同理）。请先停止 `alphaavatar start`。要与现有安装隔离，可以加 `--prefix DIR --bin-dir DIR`，并设置另一个 `ALPHAAVATAR_HOME`。
- 正式 Release 发布后的默认入口：`curl -fsSL https://github.com/AlphaAvatar/AlphaAvatar/releases/latest/download/install.sh | bash`，不需要 `--file` 或 `--artifacts`。

### 6.10 未验证与剩余

- 本批代码对应的 CI：待用户提交推送后核对；候选包是本地构建的，不是 CI 产物。
- 本地 llama-cpp wheel 需要 glibc ≥ 2.32，CI 构建以 2.28 为上限；2.28 至 2.31 的兼容下限没有实测。
- 干净环境是 bwrap 运行的 Ubuntu 用户态，不是完整的虚拟机或镜像。没有在其他发行版上实测。
- 没有调用任何模型或远程服务，也没有运行 Doctor 的运行时诊断，没有产生费用。Qdrant 和自建服务器都只是配置，没有真实的服务端。
- 剩余的小问题，都没有修复：
  - Setup 写出的 profile 头部仍写着"created by `alphaavatar config init`"，下一行注明了"Chosen with `alphaavatar setup`"；
  - 未发布构建上，`config init` 的 `Next` 只给出 `alphaavatar setup <bundle>`，没有带 `--artifacts`，不过 Setup 会在开始时就拒绝并说明用法；
  - 场景 1 中"不读启动文件的 shell"第一次检查的结果无法复现；
  - LanceDB 的 `table_names()` 弃用提示。

## 7. 第五批的审查修复：向量空间记录（基线 `e300619e`）

审查指出批次 5 的向量空间保护有四处问题（第 1 项为 P1，第 2–4 项为 P2）。本轮只修这四处，VAD、寻址策略、默认 Embedding 和已有配置模板的行为不变。四处都登记在 `docs/bugs-zh.md`（KD-58 至 KD-61，已修复）。

### 7.1 基线

- `e300619e` 的 Quality（45220962724）和 Linux package（45220963046）都是 success。
- 先写回归，在 `e300619e` 的代码上复现，再修复。用法：把推送版本的 `space.py`、`lancedb.py`、`qdrant.py` 放在仓库外，由 pytest 插件替换导入（§7.7）。

### 7.2 记录的归属（第 1 项，P1，KD-58）

- 问题：Qdrant 只凭名称就把 `<collection>__embedding` 当成自己的记录，并写入 point 0，用户同名集合里的数据会被覆盖。
- 修复（`agents/utils/vdb/qdrant.py`）：
  - 记录集合在创建时带唯一的命名向量 `alphaavatar_embedding_space`（1 维，DOT）。这个标记从创建起就存在，无法在事后补上；
  - 集合里的每个点都必须是完整的、带标记的记录（字段集合完全一致，见 `space.is_record`）；
  - `e300619e` 写的记录集合（无名 1 维 DOT 向量，只有 point 0，记录不带标记）只读，从不写入；
  - 其他同名集合都拒绝。拒绝发生在创建或写入任何东西之前，主集合也不会被创建。报错写明该集合没有被改动，建议移走它或给存储换一个名字。
- LanceDB 的 `<table>.embedding.json` 同样要求是完整记录，否则拒绝，文件保持原样。

### 7.3 空表也比较维度（第 2 项，P2，KD-59）

- 问题：没有记录的旧表只在非空时比较实际维度；用 8 维配置打开 4 维的空表，会写下错误的记录，之后原来的 4 维配置也被拒绝。
- 修复（`space.claim()`）：只要表或集合已存在，不论是否为空，都先比较实际维度；不符时在写记录之前拒绝，原配置照常可以打开。有记录时，实际维度也必须与之相符。不提供自动删除或重建。

### 7.4 Setup 预检只看会打开的存储（第 3 项，P2，KD-60）

- 问题：`recorded_conflicts()` 只按设置路径和集合名匹配记录，改用 Qdrant 或换到新的 `client_path` 后，仍会因为旧 LanceDB 表的记录被拒绝。
- 修复：按 runner 选择存储的规则找到这次会打开的存储，只核对它：
  - 后端用 `vdb_backend()` 判断，Qdrant 的不看；
  - 目录：配置了 `client_path` 时就是这个目录；没有配置时，是 Avatar 自己的 `data/indexes/` 之下、记录里也没有 `client_path` 的那一个；
  - 名称一致，插件已选且未关闭。
- 记录新增 `client_path` 字段（设置里写的目录，没写时为 null）。`e300619e` 写的记录没有这个字段，在默认目录里照样核对。
- 显式目录位于 Avatar 目录之内时，同一份记录会被扫到两次，现在只计一次。
- 预检仍然只读文件，不需要 LanceDB，所以基础包上可以运行（§7.9）。Qdrant 只在启动时检查，这一点不变。

### 7.5 并发首次登记（第 4 项，P2，KD-61）

- 问题：检查、创建和登记分开执行。
  - Qdrant：两个 Host 同时登记同一模型时，一方报伴随集合 already exists；伴随集合为空时，两个不同模型可以同时登记成功，后写的覆盖先写的；
  - LanceDB：有同样的窗口，后写的覆盖先写的，或者并发建表失败。
- 设计：仲裁放在存储本身，不用进程内的锁（进程锁管不到另一台 Host）。
  - 登记只新增，不覆盖：
    - LanceDB：记录先完整写到旁边的临时文件，再用 `os.link` 放到位，只有第一个能成功；文件系统不支持硬链接时，改用 `open("x")` 独占创建；
    - Qdrant：每次登记写一个属于这次打开的点（uuid4）。撤回时只删自己的点，已经据此打开存储的 Host 的记录不会被别人撤掉。
  - 登记后重新读取全部记录，发现别的模型就撤回自己的记录并拒绝。所以不论交错顺序如何，两个模型都不可能同时拿到使用权；同一模型的多条记录表示同一个空间，安全复用。
  - 记录集合或主存储被别的 Host 同时创建时，容忍一次创建失败，再确认它已经存在。
- 已知的代价：两个不同模型恰好同时首次登记同一个存储时，可能双方都撤回、都拒绝（见 `test_hosts_registering_into_an_empty_record_at_once_never_both_take_it`）。这时没有任何向量被写入，重新启动即可。

### 7.6 兼容与限制

- `e300619e` 写的记录（LanceDB 的 JSON、Qdrant 的 point 0）：读取、遵守，从不改写；新记录才带标记和 `client_path`。
- 本版之前没有记录的存储：维度相符时只能当作配置的模型接收，记为 `assumed` 并警告。这一点无法核实，仍是明确的限制。
- 轮换凭据、key 的变量名或服务器地址都不算换模型。
- 跨 Host 的 Qdrant 仲裁只在 qdrant-client 的本地内存模式下、用受控交错验证过，没有对真实 Qdrant 服务端运行（本次会话里运行本地 Qdrant 服务端的操作未获许可）。正确性依赖服务端让 `wait=True` 的写入对随后的读取可见：单节点成立；多副本集群取决于它的一致性设置，没有验证。
- LanceDB 的仲裁依赖同一文件系统上 `link`/`O_EXCL` 的原子性；网络文件系统上的行为没有验证。

### 7.7 测试

- `avatar-agents/tests/utils/test_vdb_space.py`：从 6 个函数增加到 17 个（22 个用例），都用真实的临时 LanceDB 和内存 Qdrant：
  - 第 1 项：同名但不属于自己的集合被拒绝，其中的点、payload、向量都不变，主集合没有被创建；
  - 第 2 项：空的旧表或集合维度不符时拒绝（LanceDB、Qdrant 各一），什么都没记录，原维度照常打开；
  - 第 3 项：预检只核对会打开的存储，Qdrant、新的 `client_path`、Avatar 目录之内的显式目录都覆盖；
  - 第 4 项：受控交错，不靠时序运气。`Interleaved` 包住真实客户端，让两个线程在指定方法的第 n 次调用之前或之后，于同一个 barrier 会合：
    - 两个 Host 都读到"未登记"之后才登记：同一模型都能打开；两个模型至多一个打开，剩下的记录就是打开者的；
    - 空的记录集合、两个模型，都登记完才各自重读：都拒绝，都撤回；
    - LanceDB 的同一组交错；
    - 有向量的旧集合、同一模型，同时创建记录集合：都打开；
    - 读到"未登记"之后另一个 Host 才登记（LanceDB、Qdrant 各一）：不覆盖，后来者拒绝；
    - 撤回只删自己的点；
  - `e300619e` 写的记录被遵守，而且逐字节不变。
- `avatar-host/tests/cli/test_setup.py` 的 Embedding 预检测试增加：同名集合在 Qdrant 上不再被拒绝。
- 在推送版本上：12 个审查用例失败。Qdrant 同一模型、在主集合读取处会合的那个用例在旧代码上通过，旧代码在这一点上的失败（并发创建记录集合）由"有向量的旧集合"用例复现。另有一个旧测试失败，因为它预期的记录字段增加了标记和 `client_path`。Setup 的新增情形在推送版本的 `space.py` 上失败。
- 变异 10 个，全部被发现：
  - 任何同名集合都当作记录；
  - 空表不比较维度；
  - 预检不看后端；
  - 预检不看目录；
  - 登记后不重读；
  - Qdrant 撤回时不删除；
  - LanceDB 记录用 `os.replace` 覆盖；
  - 主存储被并发创建时直接失败；
  - 已有记录时仍然登记；
  - 所有 Host 共用按空间计算的点 ID（第一版的设计，撤回会删掉别人的记录）。

  第七个起初没有被发现，为此补了"读到未登记之后另一个 Host 才登记"的两个测试；第十个是在复核时发现的设计缺陷，改为每次打开自己的点 ID 并补了测试。

### 7.8 新候选包

| 项 | 内容 |
|---|---|
| 源码 | HEAD `e300619e141a889efe7c2e9f157a17656afefaae` 加本轮未提交的改动：11 个跟踪文件，没有未跟踪文件，`git diff` 的 sha256 前缀 `c794ebec55449211`。构建前后核对过，diff 与构建时一致 |
| 构建 | `packaging/linux/build.sh --allow-dirty --max-glibc 2.32`；uv 0.10.0（仓库外的私有 venv）、Python 3.13.12；构建机 Alibaba Cloud Linux 3（glibc 2.32） |
| Build ID | `0.6.8-e300619e141a-dirty.20261123173515`；manifest 中 `release` 为 null，`commit` 为上述 HEAD，uv.lock sha256 `6e2c34f7…`（与 CI 相同） |
| 内容核对 | 包内基础环境的 `space.py`、`lancedb.py`、`qdrant.py`，以及 Memory、Persona、MCP wheel 中的三个 LanceDB runner，都与工作区逐字节相同 |
| 位置 | `~/alphaavatar-candidates/0.6.8-e300619e141a-dirty.20261123173515/`：基础包、`.sha256`、12 个 wheel、manifest、`install.sh`（与工作区逐字节相同）、`SHA256SUMS`；`acceptance/` 下是验收屏幕、结果、源码 diff 和构建日志。§6.5 的旧候选包不再作为验收包 |
| SHA-256 | 包 `f6d14ea74a60f21b0e10e229fb76ecc88e172d4fcc4f99482ee9ce3e9393a058`；manifest `5404e5d2…83ce`；install.sh `02ff07ac…98`；SHA256SUMS `1caa6ad1…8499`；`sha256sum -c SHA256SUMS` 全部 OK |

### 7.9 干净环境复验

环境与 §6.6 相同（`ubuntu-base-24.04.5`、glibc 2.39、bubblewrap 0.4.0、普通用户、没有 python/node/uv/编译器），每个场景用新的 rootfs 副本。

- 场景 1：安装器接续真实 Setup，用 `cat install.sh | bash -s -- --file …` 运行。
  - 在 Provider 列表处按 Ctrl+C：Setup 退出码 130，安装器报 "Setup did not finish (exit 130); AlphaAvatar stays installed"，自身退出码 0；
  - 再次安装：方向键上下移动、在 Memory 列表输入 `open` 筛选，其余接受默认，凭据都是虚构的。105 个包 / 514 MB，`PASS · 8 runners`，74 秒，`OK    Setup done`；
  - 两次的终端设置都恢复，光标显示，没有残留进程；
  - 之后：`bash -l`、`bash -i` 都能找到命令，不读启动文件的 bash 找不到；`config check avatar` 通过；`doctor avatar --no-metrics` 退出码 0；`config init ref` 通过。
- 场景 2：代表性分支，在同一个 root 里真实安装。

| Bundle | 结果 |
|---|---|
| own（ENV 关闭、Qdrant、自建服务器） | 105 个包 / 427 MB，`PASS · 8 runners` |
| mixed（Voice 关闭、Anthropic、OpenRouter、Google Embedding） | 112 个包 / 521 MB，`PASS · 2 runners` |
| speech（realtime STT、`tts-1`） | 复用环境，`PASS · 8 runners` |
| voiceai | 复用环境，`PASS · 8 runners` |

  四次的终端设置都恢复，没有残留进程。
- YAML 检查，范围是 7 个 Bundle：场景 1 的 `avatar`、`ref`，场景 2 的四个，场景 4 的 `small`。
  - 注释行和空行都按原顺序保留，缩进每层两个空格，没有出现任何凭据值；
  - 变化只出现在所选的设置上；`avatar` 唯一的不同是场景 5 手改的语速，被保留。
- 场景 3：只有基础包。`config init` 写出 12 个 profile，与包内模板完全相同；`config check` 退出码 2，逐个列出缺失的插件和 `alphaavatar setup all`；`Next` 给出 `alphaavatar setup --artifacts /srv/cand`。
- 场景 6（新增）：基础包上的 Setup 预检，在场景 3 的 root 里进行。这里没有任何插件，也没有 LanceDB（`import lancedb` 失败）。先在 Avatar 默认的索引目录写一份 openai `text-embedding-3-small` 的记录，再运行 `setup all --plan`：
  - Embedding 相同：给出计划，退出码 0；
  - 改为 Google：退出码 1，报"holds vectors of openai text-embedding-3-small"；
  - 同名集合改用 Qdrant：给出计划；
  - 用 `client_path` 指定另一个目录：给出计划；
  - 没有安装任何东西；第二轮运行前后 `~/.local` 下的文件完全一致。第一轮在基础运行时里写了两个标准库 `.pyc`，这是已有的打包问题，登记为 O-35，与本轮无关。第一轮另外因为我的脚本用错了 Python 路径而重跑。
- 场景 5（新增）：已有配置的保护，在场景 1 的 root 里、Setup 之后进行。
  - 在终端里对已有的 `avatar` 再运行 Setup：只问是否安装并启用。configs 和 settings 下的全部文件（包括凭据文件和 `settings.yaml`）哈希都不变；
  - 手改 `voice.yaml` 的语速后，不带终端再运行 Setup：通过，手改的内容逐字节保留；
  - 用包内的代码在 Avatar 的 Memory 表旁写下记录（带标记，`client_path` 为 null），再把 Bundle 的 Embedding 改为 Google：Setup 退出码 1，"Setup failed; nothing was enabled"，所有文件不变；
  - 同名集合改用 Qdrant：不再拒绝，安装 Qdrant 依赖（112 个包 / 521 MB），`PASS · 8 runners`；之后 YAML 改回原样；
  - 用包内的代码复核存储层：
    - Qdrant 同名集合里有用户数据：拒绝，数据不变，主集合没有被创建；
    - 维度不同的空集合、空表（Qdrant、LanceDB 各一）：拒绝，什么都没记录，原维度照常打开；
    - LanceDB 读到"未登记"之后另一个 Host 才登记：拒绝，记录不变。
- 场景 4：升级与 cleanup。
  - 旧版是 CI 为 `e300619e` 构建的包：`0.6.8-e300619e141a`，Linux package 运行 45220963046，artifact 14841461318，`SHA256SUMS` 全部 OK；新版是 §7.8 的候选包。
  - 用旧版自己的 `install.sh` 和 Setup 建 Bundle `small`（Voice 关闭、本机模型关闭），再用旧版的代码在 Memory 表旁写下记录：不带标记，也没有 `client_path`，正是旧版的格式。另写入 `records.sqlite3` 和用户 profile，并记录所有应用数据文件的哈希。

| 步骤 | 结果 |
|---|---|
| `upgrade --sha256 000…` | 退出码 1，"does not match its SHA-256"，报 "0.6.8-e300619e141a stays current"；current、versions、envs 不变 |
| 准备失败：在候选包第一次成功安装之前进行，包和 `.sha256` 放在没有 wheel 的目录 | 计划 77 个包 / 188 MB；取本构建的第一个自带 wheel 时失败（"No such file or directory"），报 "stays current"；current、versions、envs 不变；`config check small` 通过 |
| `upgrade --file`（包旁有 wheel） | 77 个包 / 188 MB，`PASS · 2 runners`；current 切到新环境，旧版保留到 cleanup；`config check` 通过 |
| 旧版写的记录 | 候选包按同一模型打开；换成 Google 时存储层拒绝，Setup 也在安装之前拒绝；记录内容不变 |
| `cleanup --dry-run` | 预计释放 795 MB；`~/.local` 下所有文件的大小和修改时间前后一致 |
| `cleanup` | 只删除旧环境（577 MB）和旧基础包（218 MB）；current 保留；`config check` 通过；应用数据（包括旧版的记录和 LanceDB 表）的哈希与升级前一致 |

### 7.10 验证

- 相关测试：Agents、Memory、Persona、tools 插件、Host 的 CLI 和 setup，648 passed。
- 离线全量（机器空闲时）：1155 passed，221 warnings，378 s；运行前后，未跟踪和被忽略的文件一致。
- 仓库规范：`uv lock --check`、`check_workspace.py`、`ruff check .`、`ruff format --check .`（797 个文件）、`bash -n`、`git diff --check`、对改动文件的 pre-commit 都通过，pre-commit 没有改动文件。
- CI：基线 `e300619e` 都是 success；本轮的改动尚未提交，没有对应的 CI。

### 7.11 给用户的候选包命令

未发布的候选包要用 `--file` 安装，Setup 需要 `--artifacts`：

```bash
cd ~/alphaavatar-candidates/0.6.8-e300619e141a-dirty.20261123173515
sha256sum -c SHA256SUMS
bash install.sh --file ./alphaavatar-0.6.8-e300619e141a-dirty.20261123173515-linux-x86_64.tar.gz
# 在终端里回答 Y：安装器提供的 setup 会自动带上 --artifacts（本目录）
# 以后，或者另开终端：
alphaavatar setup --artifacts ~/alphaavatar-candidates/0.6.8-e300619e141a-dirty.20261123173515
# 已有安装时，改用升级：
alphaavatar upgrade --file ~/alphaavatar-candidates/0.6.8-e300619e141a-dirty.20261123173515/alphaavatar-0.6.8-e300619e141a-dirty.20261123173515-linux-x86_64.tar.gz
```

- 升级前请先停止 `alphaavatar start`。要与现有安装隔离，可以加 `--prefix DIR --bin-dir DIR`，并设置另一个 `ALPHAAVATAR_HOME`。
- 正式 Release 发布后的默认入口仍是 `curl -fsSL https://github.com/AlphaAvatar/AlphaAvatar/releases/latest/download/install.sh | bash`，不需要 `--file` 或 `--artifacts`。

### 7.12 未验证与剩余

- 本轮代码对应的 CI：待用户提交推送后核对；候选包是本地构建的，不是 CI 产物。
- Qdrant 的跨 Host 仲裁没有对真实服务端验证，多副本集群的一致性设置也没有验证（§7.6）。LanceDB 的仲裁在网络文件系统上没有验证。
- 没有调用任何模型或远程服务，没有运行 Doctor 的运行时诊断，没有产生费用。Qdrant 和自建服务器都只是配置。
- §6.10 列出的限制不变：本地 llama-cpp wheel 需要 glibc ≥ 2.32；干净环境是 bwrap 运行的 Ubuntu 用户态，不是完整的虚拟机；Setup 写出的 profile 头部注释；`config init` 的 `Next` 不带 `--artifacts`；LanceDB 的弃用提示。
- 新登记、未修复：O-35，基础包内标准库的 `.pyc` 过期，安装后首次导入时会重新编译并写回基础包目录。

## 8. 第五批第二轮审查修复：三 Host 复用窗口与预检定位（基线 `a9b2081a`）

`a9b2081a` 的复核：KD-58（集合归属）和 KD-59（空表维度）通过；KD-60、KD-61 仍有缺口，本轮修复。O-35 按用户决定登记为已知限制，延期，本轮不修。VAD、寻址策略、默认 Embedding 和配置模板行为不变，没有增加自动删除、重建或迁移。

### 8.1 基线

- `a9b2081a` 的 Quality（45232942545）和 Linux package（45232942318）都是 success。
- 先写回归，在 `a9b2081a` 上复现，再修复（§8.5）。

### 8.2 KD-61：Host 只依赖不会被撤回的记录

- 用户的反例（真实内存 Qdrant，受控交错）：
  1. C（模型二）读到没有记录；
  2. A（模型一）登记，尚未重读；
  3. B（模型一）看到 A 的记录，跳过登记直接打开；
  4. C 登记；A 重读发现 C，撤回并拒绝；
  5. C 重读只剩自己，打开。

  结果 B 和 C 用两个模型同时拿到使用权。根因是 B 依赖了 A 尚未确认、之后仍可能撤回的记录。
- 复现时另外发现两处：
  - 重读失败或被中断时，记录不会撤回；
  - Qdrant 一页只读 64 条，超过就把整个存储当作"不是记录"而拒绝。
- 新的契约（`space.claim()`），记录分为已确定和待定（`pending: true`）两种：
  - Host 只依赖已确定的记录。已确定的记录永不撤回；有同一模型的已确定记录时直接打开，不写任何东西。
  - 没有已确定记录时，先写入自己的待定记录再重读：
    - 这时出现了已确定记录：撤回自己的，按它处理（同一模型则打开，否则拒绝）；
    - 仍然没有：只有在不存在其他模型的记录（不论待定还是已确定）时，才把自己的改为已确定，否则撤回并拒绝。
  - 确定之前出现任何异常，包括 Ctrl+C（`BaseException`），都会撤回自己的记录；撤回本身失败时记一条警告，原异常照常抛出。
- 为什么安全：Host 先写后读，确定后永不撤回。若两个 Host 分别确定了两个模型，每一方的重读都必然早于对方的写入；而写入又早于各自的重读，两者矛盾。所以不论交错顺序如何，所有已确定的记录、所有成功打开的 Host 都属于同一模型。Qdrant 的分页读取不是快照，这里把"开始读取"当作读取时刻：开始读取之前已写入且仍存在的记录都会被读到，论证照样成立。
- 后端：
  - Qdrant：每次打开写一个属于自己的点（uuid4），先写待定，确定时改写同一个点；撤回只删自己的点；分页读取全部记录（每页 256 条）。
  - LanceDB：唯一的记录文件用硬链接独占放置、永不撤回，放置即为已确定；没有待定状态。
- 记录数量：已确定的记录只在"同时首次登记、都没看到已确定记录"时才会多于一条，数量受同时登记的 Host 数限制；之后重新打开不再新增。待定记录只会因为 Host 被强制终止而留下。

### 8.3 KD-60：与 Runner 共用存储位置的解析

- 复核发现的两个方向（真实临时 LanceDB）：
  - 漏报：显式把 `client_path` 指向默认目录时登记，之后删掉 `client_path`、换 Embedding。物理位置完全相同，但因为记录里的 `client_path` 不为空而跳过检查；
  - 误报：默认库移到 `indexes/memory/lancedb-backup` 后，递归扫描仍会读到备份里的记录，阻止在默认位置新建独立库。
- 修复：
  - `lancedb_directory()`（`agents/utils/vdb/config.py`）：设置了 `client_path` 就是 `Path(client_path).expanduser()`，否则是 Avatar 工作区下的 `indexes/<namespace>/lancedb`。Memory、Persona、MCP 三个 LanceDB runner 和 Setup 都调用它。
  - 命名空间沿用插件自己的规则，取插件的包名，抽成 `ResolvedPlugin.namespace_of(module)`。基础包上没有插件，所以构建时 `catalog.py` 把每个实现的入口点模块写进 catalog 的 `modules`，Setup 由此得到命名空间。新增的测试核对：本机每个已安装插件，从入口点模块得出的命名空间都与 runner 实际使用的一致。
  - Setup 只读那个目录本身（不再递归扫描整个 `indexes` 子树）。一条记录只有在其 `setting` 属于这一节、且该设置现在仍指向这张表时才计入，所以共用目录的各节各自计一次。
  - 不再根据记录里的 `client_path` 推断位置，新记录也不再写这个字段；`a9b2081a` 写下的带 `client_path` 的记录照样读取。
  - catalog 缺少 `modules` 时，Setup 报错并停止，不会悄悄跳过检查。

### 8.4 限制与验证范围

- Host 在登记过程中被强制终止（例如 SIGKILL）时，会留下待定记录：没有 Host 依赖它，同一模型可以照常打开；但空存储上的其他模型会在它旁边被拒绝，报错写明"is being recorded … or was left so by one stopped while recording it"。不会自动删除。
- 两个不同模型同时首次登记时，可能双方都拒绝（见 `test_three_hosts_reading_one_another_s_records_at_once_all_refuse_then_one_reopens`）。这时没有写入任何向量，重试即可。
- 相对路径的 `client_path` 按各自进程的工作目录解析，Setup 与 `start` 的工作目录不同时可能指向不同位置；模板不使用相对路径。
- Qdrant 只在 qdrant-client 的本地内存模式下验证：多个 Host 是同一进程里的线程，共用一个内存存储，用受控交错排序。
  - 真实单节点服务端：本轮没有运行（上一轮运行本地服务端的操作未获许可，本轮没有再尝试）。按设计，正确性依赖服务端让 `wait=True` 的写入对随后开始的读取可见，单节点应当成立，但未实测；
  - 多副本集群：取决于它的读写一致性设置，没有验证。
- LanceDB 的独占放置依赖同一文件系统上 `link`/`O_EXCL` 的原子性；网络文件系统上没有验证。

### 8.5 测试

- `avatar-agents/tests/utils/test_vdb_space.py`，共 32 个用例，用真实临时 LanceDB 和内存 Qdrant。新增的 `Hosts` 帮助类让每个 Host 在自己的线程里运行，并停在指定客户端调用（第 n 次）之前或之后，由测试决定谁先继续，不依赖线程时序。新增：
  - 用户的三 Host 反例：C 被拒绝；B 的已确定记录逐字段不变；A、C 的记录都已撤回；
  - LanceDB 上的同一组交错；
  - 三个同模型 Host 同时登记：都打开，第四个 Host 不再新增记录；
  - 三个 Host 中有另一个模型、逐个重读：只有最后一个打开，始终只有一个模型；
  - 三个 Host 都重读完才撤回：全部拒绝、全部撤回，之后重试可以打开；
  - 重读失败、被 Ctrl+C 中断：撤回、没有残留；被强制终止：留下待定记录，重试的同一模型打开，另一个模型被拒绝；
  - 601 条记录、最后一页有另一个模型：被读到并拒绝；删掉它之后同一模型重复打开，记录数不变；
  - 预检：Persona 默认目录的冲突；Memory、Persona、MCP 共用目录，且两节用了同名设置时各自只计一次；catalog 没有该插件时不检查；移走的旧库不再计入。
- `avatar-host/tests/cli/test_setup.py`：Setup 端到端的两个方向：
  - `test_setup_reads_the_record_where_start_opens_the_store`：拒绝，所有文件不变；
  - `test_setup_leaves_a_store_moved_aside_to_itself`：可以安装，备份不变。

  测试用的 catalog 按已安装的入口点补上 `modules`。
- `avatar-host/tests/setup/test_choices.py`：`catalog.py` 从 wheel 的入口点读出模块；每个已安装插件从入口点模块得出的命名空间，都等于 `resolve_plugin(...).namespace`。
- 在 `a9b2081a` 上（推送版本的 `space.py`、`lancedb.py`、`qdrant.py`，CLI 测试另加 `setup.py`，从仓库外替换导入）：
  - 失败：三 Host 反例（C 也打开了）；三个 Host 都重读完才撤回（B 依赖 A 的记录直接打开，没有等到登记）；重读失败、被中断（记录残留）；601 条记录（被当作"不是记录"拒绝）；Setup 的漏报和误报两个测试；
  - 通过（作为防护保留）：被强制终止、LanceDB 三 Host、三 Host 逐个重读两种情形；
  - 预检的单元测试在 `a9b2081a` 上只是因为签名不同而失败，不计作复现。
- 变异 13 个，全部被发现：
  - 把待定记录当作已确定；
  - 只在拒绝时撤回；
  - 按已确定记录打开时保留自己的待定记录；
  - 从不确定；
  - 确定前忽略其他模型的待定记录；
  - 只读一页；
  - Qdrant 登记时直接写成已确定；
  - 目录规则忽略 `client_path`；
  - 目录规则固定一个命名空间；
  - 预检递归扫描上一级；
  - 不核对记录属于哪一节；
  - Setup 不传 catalog 的模块；
  - `catalog.py` 记录整个入口点值。

  `catalog.py` 的变异需要替换仓库里的文件本身（它的测试按路径加载），运行后已恢复，校验和一致。
- 相关测试组 792 passed；离线全量 1168 passed，241 warnings，384 s，运行前后未跟踪和被忽略的文件一致。

### 8.6 新候选包

| 项 | 内容 |
|---|---|
| 源码 | HEAD `a9b2081a3f8a4dd7d5f062c631700f5c672c0124` 加本轮未提交的改动：17 个跟踪文件，没有未跟踪文件，`git diff` 的 sha256 前缀 `e5ab378bf7d2cf24`。构建前后核对过，diff 与构建时一致 |
| 构建 | `packaging/linux/build.sh --allow-dirty --max-glibc 2.32`；uv 0.10.0（仓库外的私有 venv）、Python 3.13.12；构建机 Alibaba Cloud Linux 3（glibc 2.32） |
| Build ID | `0.6.8-a9b2081a3f8a-dirty.20261123185340`；manifest 中 `release` 为 null，`commit` 为上述 HEAD，uv.lock sha256 `6e2c34f7…`（与 CI 相同） |
| 内容核对 | 基础环境里的 `space.py`、`qdrant.py`、`lancedb.py`、`config.py`、`resolved_plugin.py`、Setup 的 `setup.py`，以及 Memory、Persona、MCP wheel 里的三个 LanceDB runner，都与工作区逐字节相同；包内 catalog 的 `modules` 与 `plugins` 列出同样的实现，Memory 为 `alphaavatar.plugins.memory.factory` |
| 位置 | `~/alphaavatar-candidates/0.6.8-a9b2081a3f8a-dirty.20261123185340/`；`acceptance/` 下是验收屏幕、结果、源码 diff 和构建日志。§7.8 的候选包不再作为验收包 |
| SHA-256 | 包 `6e9e4df164051fabd16eda0c10af86d6c72d625f0e43119d31edffa59d24a707`；manifest `ff189f65…cbe5`；install.sh `02ff07ac…98`；SHA256SUMS `d3b24b21…c9c7`；`sha256sum -c SHA256SUMS` 全部 OK |

### 8.7 干净环境复验

环境与 §6.6 相同，每个场景用新的 rootfs 副本。

- 场景 1，安装器接续真实 Setup：
  - Ctrl+C 退出码 130，安装保留；
  - 完整走一遍：105 个包 / 514 MB，`PASS · 8 runners`，`OK    Setup done`；
  - 两次的终端设置都恢复，没有残留进程；
  - 之后 `bash -l`、`bash -i` 都能找到命令；`config check`、`doctor --no-metrics`、`config init` 都通过。
- 场景 2，代表性分支：own（105 个包 / 427 MB）、mixed（112 个包 / 521 MB，`PASS · 2 runners`）、speech、voiceai（复用环境），都通过。7 个 Bundle 的 YAML 检查没有问题，也没有任何凭据值。
- 场景 3，只有基础包：与 §7.9 相同，通过。
- 场景 6，基础包上的预检（没有插件，没有 LanceDB），记录所在的位置由包内 catalog 的 `modules` 得出：

| 情形 | `setup all --plan` |
|---|---|
| 记录在默认目录，Embedding 相同 | 给出计划 |
| 改为 Google | 退出码 1，"holds vectors of openai text-embedding-3-small" |
| 同名集合改用 Qdrant | 给出计划 |
| `client_path` 指向另一个目录 | 给出计划 |
| `client_path` 显式指向默认目录，改为 Google | 退出码 1 |
| `a9b2081a` 写的、带 `client_path` 的记录，设置里已删掉 `client_path` | 退出码 1（`a9b2081a` 在此漏报） |
| 默认库移到 `lancedb-backup` | 给出计划（`a9b2081a` 在此误报） |

  `~/.local` 下的文件前后完全一致。脚本先运行一次 `--plan`，让 O-35 的 `.pyc` 先写完，再开始比较。
- 场景 5，已有配置保护（场景 1 的 root）：
  - 已有 Bundle 再运行 Setup，所有文件哈希不变；手改的内容保留；
  - 换 Embedding 被拒绝，所有文件不变；
  - 同名集合改用 Qdrant 后照常安装；
  - 用包内的代码复核了集合归属、空表维度、读到"未登记"之后另一个 Host 才登记三种情形。
- 场景 4，从 CI 为 `a9b2081a` 构建的包（`0.6.8-a9b2081a3f8a`，Linux package 运行 45232942318，artifact 14846539395，`SHA256SUMS` 全部 OK）升级：
  - 旧版的代码写下带 `"client_path": null` 的记录，正是那一版的格式；
  - SHA-256 错误：拒绝，状态不变；
  - 在候选包第一次成功安装之前准备失败：拒绝，状态不变，`config check` 通过；
  - 升级：77 个包 / 188 MB，`PASS · 2 runners`；
  - 升级后，同一模型照常打开，另一个模型被存储层和 Setup 拒绝，记录内容不变；
  - `cleanup --dry-run`：预计释放 795 MB，`~/.local` 下所有文件不变；
  - `cleanup`：只删除旧环境和旧基础包；应用数据（包括旧版的记录和 LanceDB 表）的哈希与升级前一致。

### 8.8 验证

- 源码测试：§8.5；仓库规范检查（`uv lock --check`、`check_workspace.py`、`ruff check .`、`ruff format --check .`、`bash -n`、`git diff --check`、对改动文件的 pre-commit）都通过，pre-commit 没有改动文件。
- 候选包与源码：一致性见 §8.6；构建之后只改了本日志，日志不进包。
- 真实服务：没有调用任何模型或远程服务，没有运行 Doctor 的运行时诊断，没有产生费用。Qdrant 的验证范围见 §8.4。
- CI：`a9b2081a` 都是 success；本轮的改动尚未提交，没有对应的 CI。

### 8.9 给用户的候选包命令

```bash
cd ~/alphaavatar-candidates/0.6.8-a9b2081a3f8a-dirty.20261123185340
sha256sum -c SHA256SUMS
bash install.sh --file ./alphaavatar-0.6.8-a9b2081a3f8a-dirty.20261123185340-linux-x86_64.tar.gz
alphaavatar setup --artifacts ~/alphaavatar-candidates/0.6.8-a9b2081a3f8a-dirty.20261123185340
# 已有安装时（先停止 alphaavatar start）：
alphaavatar upgrade --file ~/alphaavatar-candidates/0.6.8-a9b2081a3f8a-dirty.20261123185340/alphaavatar-0.6.8-a9b2081a3f8a-dirty.20261123185340-linux-x86_64.tar.gz
```

正式 Release 之后，入口仍是 `curl -fsSL https://github.com/AlphaAvatar/AlphaAvatar/releases/latest/download/install.sh | bash`。

### 8.10 未验证与剩余

- 本轮代码对应的 CI：待用户提交推送后核对。
- 真实 Qdrant 服务端（单节点）和多副本集群、网络文件系统上的 LanceDB：没有验证（§8.4）。
- 强制终止留下的待定记录不会自动删除（§8.4）。
- O-35 延期；§6.10 列出的其他限制不变。
