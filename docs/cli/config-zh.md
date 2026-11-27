# `alphaavatar config`

[English](config.md)

创建或检查应用配置。两个子命令都不会启动任何东西。

## Bundle 与 profile

**bundle** 是一份完整、可启动的配置。**profile** 是 bundle 引用、并可在多个 bundle 之间共享的一个配置部分。两者都位于应用主目录中：

| 文件 | 内容 |
| --- | --- |
| `<home>/configs/bundles/<name>.yaml` | `avatar`（以及任何内联设置的部分），外加 `profiles` |
| `<home>/configs/profiles/<name>.yaml` | 一个部分的正文，例如 `voice`；`<name>` 可以包含以 `/` 分隔的多段 |
| `<home>/settings/settings.yaml` | `default_bundle`、已存储凭据的文件（`credentials`）及其他用户设置 |
| `<home>/settings/credentials-<id>.env` | [`alphaavatar setup`](setup.md) 存储的凭据，只有你可读 |

```yaml
# configs/bundles/my-avatar.yaml
avatar:
  id: my-avatar
profiles:
  host: my-avatar/host/host                     # configs/profiles/my-avatar/host/host.yaml
  runtime: my-avatar/agent/runtime
  voice: my-avatar/plugins/foundation/voice
  memory: my-avatar/plugins/perception/memory
```

- `profiles` 将一个部分映射到 profile 名称：`host`、`runtime`，或某个插件部分（`context`、`loop`、`voice`、`vision`、`status`、`router`、`character`、`memory`、`persona`、`tools`）。`avatar` 即 Avatar 的身份，保留在 bundle 中。
- profile 按层分组：`host`、`agent`（`runtime`），以及 `plugins/foundation`、`plugins/perception` 和 `plugins/tools`。`config init` 按这种方式写出，`config check` 也按相同的层报告；其他任何名称也可以使用。
- profile 文件就是该部分的正文。它不引用任何东西，因此引用永远不会形成循环；带有自己的 `profiles` 的 profile 会被拒绝。
- 一个部分要么来自 bundle，要么来自一个 profile，不能同时来自两者。
- 名称由 1-64 个小写字母、数字、`-` 或 `_` 组成；profile 名称还可以用 `/` 分隔各段。名称从不是路径，无论工作目录是什么，都在应用主目录内解析。
- 解析符号链接后，按名称指定的 bundle 必须位于 `configs/bundles` 中，profile 必须位于 `configs/profiles` 中，两者都在真实的应用主目录内；指向主目录之外的链接是错误。通过别名访问的主目录，以及留在主目录内的链接，都没有问题。
- YAML 锚点不能跨文件使用。`${...}` 插值在组合之后解析，与单个文件中一样。
- 应用主目录的选择方式与以前相同：先是 `application.home` 覆盖，然后是 `ALPHAAVATAR_HOME`，最后是平台默认值。设置从不决定它，按名称指定的 bundle 也不能改变它。
- 单个 YAML 或 JSON 文件仍按以前的方式加载，也可以使用 `profiles`。

## 选择配置

`config check`、[`doctor`](doctor.md)、`start` 和 `dev` 接受相同的可选参数：

| 参数 | 加载 |
| --- | --- |
| 包含 `/` 或带扩展名，例如 `./avatar.yaml` | 该文件，相对于工作目录 |
| 其他任何单词，例如 `my-avatar` | `<home>/configs/bundles/my-avatar.yaml` |
| 省略 | 设置中 `default_bundle` 指定的 bundle |

- 由参数的写法决定。bundle 不存在是错误，绝不会回退到名称相近的文件，反之亦然。
- 没有参数也没有默认 bundle 时，命令失败，并说明如何创建 bundle。
- `KEY=VALUE` 参数始终是覆盖项，因此 `alphaavatar config check voice.tts.speed=1.2` 检查的是默认 bundle。
- `profiles.<section>=<name>` 选择另一个 profile。其他所有覆盖项都在放入 profile 之后，应用于组合后的配置。
- 加载后，Host 及其会话使用已接受的快照；之后对 profile 的修改在下次启动时生效。

## 凭据

`start`、`dev`、`config check`、[`doctor`](doctor.md)、[`setup`](setup.md) 和 [`upgrade`](upgrade.md) 从以下来源中第一个持有值（既非空、也不只含空白）的来源取得每个凭据（[`cleanup`](cleanup.md) 为确定应用主目录，按同样方式读取前两个来源）：

1. 环境；
2. `ENV_FILE` 指定的 `.env` 文件（默认 `.env`）；
3. [`alphaavatar setup`](setup.md) 存储的凭据，位于设置指定的文件中。

- 凭据是配置为其指定的变量，名称不限：每个 `api_key_env` 插值后的结果，例如 `${oc.env:TTS_KEY_NAME,MODEL_AUTH}`（bundle 自己的变量、自有服务器的 `ALPHAAVATAR_SERVER_KEY_<hash>`）；其 MCP 服务器中，每个 `<NAME>` 占位符和 `Authorization` 头中的每个 `${oc.env:NAME}`；配置未指定时各组件读取的变量（`OPENAI_API_KEY`、`OPENROUTER_API_KEY`、`ANTHROPIC_API_KEY`、`GOOGLE_API_KEY`、`VOICEAI_API_KEY`、`TAVILY_API_KEY`、`QDRANT_URL`、`QDRANT_API_KEY` 和三个 `LIVEKIT_*`）；以及 setup 存储的凭据。
- 空的或只含空白的凭据视为未设置：它让位于下一个来源，绝不会取代其他来源的值；值按其设置原样取用，包括其中的空格。
- `.env` 本身按 python-dotenv 的方式加载：环境已设置的变量保持不变，即使为空也是如此，因此空的 `CUDA_VISIBLE_DEVICES` 仍会隐藏所有 GPU，空的 `ALPHAAVATAR_MODEL_OFFLINE` 仍允许下载；值为空的行会把对应变量设为空。它只解析一次：`${NAME}` 先读取环境中的值，再读取文件中前面的行，绝不读取后面的行；它按环境中的原样读取凭据，即在凭据填入之前读取。
- 在配置中，`${oc.env:NAME}` 读取默认凭据或已存储的凭据，以及 `Authorization` 头所指定的凭据，读取发生在凭据填入之后。其他任何 `${oc.env:NAME}`，例如 MCP 服务器的 `X-Region: ${oc.env:REGION}`，按环境中的原样读取普通变量，即使为空也是如此，并且日志会显示其值。`\${oc.env:NAME}` 是文本，因为 OmegaConf 对其做了转义，它不读取任何东西。
- `upgrade` 只读取一次 `.env`；目标构建的计划和检查从 `/` 运行，读取的是这些值而不是文件：它们读到的正是 `upgrade` 读到的值。
- `ALPHAAVATAR_HOME` 决定存储凭据的应用主目录，它为空或只含空白时同样视为未设置：此时由文件中的值决定。
- 在所有来源中都未设置、为空或只含空白的凭据即为缺失：读取它的组件拒绝启动，并指出变量名，绝不显示其值。日志会隐藏配置所指定凭据的值和服务器 key 的值，就像隐藏名称表明其为凭据的变量的值一样。
- 配置本身读取、但没有值的变量，在每个命令中都会导致加载失败，并在读取它的设置项处按名称指出：在会创建 MCP 的情况下（`enabled` 且有 `plugin`），服务器凭据在填入后仍未设置、为空或只含空白，无论是通过 `<NAME>` 占位符还是通过 `Authorization` 中的 `${oc.env:NAME}`（绝不会以 `Bearer ` 发送）；以及其他任何没有默认值、且变量未设置的 `${oc.env:NAME}`（设置为空的变量插值为空；空默认值写作 `${oc.env:NAME,''}`：`${oc.env:NAME,}` 含义相同，但 OmegaConf 会警告这种写法已弃用）。在 `Authorization` 中，每次调用都按 OmegaConf 的求值方式处理，包括嵌套的默认值：`${oc.env:NAME,default}` 只在 `NAME` 未设置时才取默认值，因此 `NAME` 为空或只含空白，或默认值本身没有值，同样会被拒绝。未创建的 MCP 不发送任何内容，也不要求任何凭据，但其设置仍会进行插值。[`config check`](#config-check) 展示了这种情况如何报告。

- 默认 bundle 与已存储的凭据来自对设置的同一次读取：其间提交的 setup 不会改变其中任何一个。
- 无法读取的设置或已存储凭据（YAML 或 UTF-8 无效、存储的文件缺失、不是普通文件）不提供任何已存储凭据：按名称指定的 bundle 或文件仍会加载，而不带配置参数的运行会失败，并指出需要修复的文件。
- YAML 以 `${oc.env:NAME}` 读取变量；凭据绝不写入 bundle 或 profile 文件。
- setup 按自有服务器命名的 key 变量 `ALPHAAVATAR_SERVER_KEY_<hash>`，会与当前生效的 `base_url` 核对：`base_url` 被改到另一台服务器或被删除的 bundle，会在持有它们的设置项处失败，例如 `loop.init_config.model`。见 [setup 的凭据说明](setup.md#credentials)。

## `config init`

创建参考 bundle 及其 profile，并在尚未设置默认 bundle 时将其设为默认：内容是不开启任何工具的参考配置（`examples/agent_configs/roles/demo.yaml`）。语音和视觉开启，Memory（含 ENV 记忆）和 Persona 开启，模型来自 OpenAI，ENV 记忆的模型来自 Google。

```bash
alphaavatar config init <name> --avatar-id <id>
```

```text
AlphaAvatar / Config init
OK    Bundle created

Configuration
  Bundle       my-avatar
  Profiles     ~/.local/share/alphaavatar/configs/profiles/my-avatar
  Default      my-avatar

Required credentials
  OPENAI_API_KEY
  GOOGLE_API_KEY
  LIVEKIT_URL · LIVEKIT_API_KEY · LIVEKIT_API_SECRET

Next
  alphaavatar config check my-avatar
  alphaavatar doctor my-avatar
```

- 已设置默认 bundle 时，`Default` 显示那个已有的 bundle，并标注 `(unchanged)`。凭据只列出名称，绝不显示其值。在 Linux 包中，[`alphaavatar setup`](setup.md) 运行之前，`Next` 为 `alphaavatar setup my-avatar`，它会安装该 bundle 所需的内容、检查并启用它。

- 写入给定的 Avatar ID，并写出所有公开设置：取参考配置中的值，参考配置未指定时取其 schema 的默认值，并附有注释，供编辑。这些 profile 随包提供，不需要参考文件。工具关闭。在 `tools.yaml` 中开启后，DeepResearch 和 MCP 由 `alphaavatar setup <bundle>` 安装，因为此版本的 catalog 提供它们；catalog 不提供 RAG，`config check` 和 `setup` 会在 `tools.rag.plugin` 处指出这一点。

```text
configs/bundles/my-avatar.yaml                 avatar, plus the profiles below
configs/profiles/my-avatar/
  host/host.yaml                               RTC transport, health, logs, doctor
  agent/runtime.yaml                           inference runners
  plugins/foundation/{context,loop,voice,vision}.yaml
  plugins/perception/{status,router,character,memory,persona}.yaml
  plugins/tools/tools.yaml                     deepresearch, rag, mcp
```
- 不写入凭据，也不写入本机路径。
- 在 Linux 包中，`alphaavatar setup` 运行之前，它将 `alphaavatar setup <name>` 列为下一步：bundle 保持写出时的样子（包括之后的修改），在 setup 完成安装之前，`config check` 会指出需要安装的内容。
- 绝不覆盖现有的 bundle 或 profile 文件；复用已存在的目录。按加载时的方式检查每个目标：bundle 必须位于 `configs/bundles` 中，profile 位于 `configs/profiles` 中，设置位于 `settings` 中，都在真实的应用主目录内。
- 只在尚未设置时才设置 `default_bundle`。读取、判断和替换设置都在同一个锁（`settings/.write.lock`，由锁库维护）下进行，因此并发运行的 `init` 不会都成为默认。是符号链接的锁文件会被拒绝，因为打开它会清空其指向的内容。
- 文件是普通的块映射时，追加 `default_bundle`，保留其他设置和注释。否则（`default_bundle: null`、流映射、显式的文档结束标记），重新写出相同的值，但不带注释。设置以原子方式替换。
- 替换设置即提交该 bundle。在此之前，失败或 Ctrl+C 只删除它创建的文件和空目录；现有文件、共享的 profile 和设置保持不变，设置的锁文件可能保留。在此之后，完整的 bundle 保留，中断仍会被报告。

在环境或 `.env` 中设置以下变量，绝不要写在这些文件中：

| 变量 | 用于 |
| --- | --- |
| `OPENAI_API_KEY` | 模型、语音、embedding、Memory 和 Persona |
| `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | 会话传输 |

先检查它，再用 [`alphaavatar doctor my-avatar`](doctor.md) 诊断，然后用 [`alphaavatar dev my-avatar`](dev.md) 启动。

## `config check`

校验配置，不启动任何东西。这一步是可选的：`start` 和 `dev` 在启动前会执行相同的校验。

```bash
alphaavatar config check [<bundle> | <file>] [KEY=VALUE ...] [--json]
```

它执行与 `start` 相同的加载步骤：`.env` 和已存储的[凭据](#凭据)、配置选择、profile、覆盖项、默认值、路径解析、schema 校验、只读的工作区检查，以及内置插件各自的设置 schema（realtime loop、context、router、memory、persona；例如缺少 `model` 的 loop 会在 `loop.init_config.model` 处失败）。但它不启动 Host、runner 或模型，不连接任何服务，不创建目录或设置，也不需要本地日志 socket。

```text
AlphaAvatar / Config check
OK    Configuration and read-only path checks passed

Configuration
  config         bundle my-avatar  (default)
  avatar_id      my-avatar
  home           /home/me/.local/share/alphaavatar
  workspace      /home/me/.local/share/alphaavatar/avatars/my-avatar

host
  rtc            livekit
  health         127.0.0.1:8081 (dev: free port)

agent
  inference      8 runners  (workers: alphaavatar.voice.vad.silero x2)

plugins/foundation
  context        default
  loop           realtime
  voice          vad=silero  stt=openai_segment  tts=openai
  vision         on  (input: vlm)

plugins/perception
  status         default
  router         default  (audio activity on, semantic addressing on, visual addressing on, turn
                 taking on, interruption on)
  character      none
  memory         default  (vdb: lancedb; retrieval on, conversation on, tool on, environment off)
  persona        default  (vdb: lancedb; profiler on, speaker on, face off)

plugins/tools
  deepresearch   none
  rag            default
  mcp            default  (1 server)
```

摘要先列出所检查的文件或 bundle，然后按 profile 层列出各项事实：插件选择、视觉及其输入、内置 router、status、memory（包括 `environment`，即 ENV 记忆）和 persona 处理器的开关、向量存储类型、已启用的工具、Host 将启动的推理 runner 及其 worker 数量，以及健康检查地址；绝不列出服务 URL、collection 名称或其他由插件定义的设置。开关按各插件自己的 schema 读取，因此省略的开关显示其默认值；`--json` 在 `plugins` 下给出相同的值：`vision`、`router` 和 `status` 是对象（`plugin` 及其开关；在 v0.6.9 之前，`router` 和 `status` 是插件名称字符串），`memory` 和 `persona` 带有各自的处理器开关。拼写错误、未被选择或不支持复制的 `runtime.inference.methods` 条目会失败，并给出其字段位置。

```text
AlphaAvatar / Config check
ERROR Configuration and read-only path checks failed

  error: ValidationError
    fields: avatar.timezone
```

```text
AlphaAvatar / Config check
ERROR Configuration and read-only path checks failed

  error: ConfigReferenceError
    Bundle 'my-avatar': profiles.voice references missing profile 'my-avatar/voice': /home/me/.local/share/alphaavatar/configs/profiles/my-avatar/voice.yaml
```

没有值的变量会在读取它的设置项处被指出，包括 MCP 服务器和请求头；凭据（`<NAME>` 占位符，或 `Authorization` 中的 `${oc.env:NAME}`）已在环境、`.env` 文件和已存储的凭据中查找过：

```text
AlphaAvatar / Config check
ERROR Configuration and read-only path checks failed

  error: MissingVariables
    Variables the configuration reads hold no value; set them in the environment or in the .env
    file ENV_FILE names (default .env):
      tools.mcp.servers.code.headers.Authorization reads the credential GITHUB_PAT, which is not set
      tools.mcp.servers.code.headers.X-Region reads REGION, which is not set, and ${oc.env:REGION} has no default
```

插值先进行，因此 `<NAME>` 占位符要在这些变量设置之后才会被报告（`tools.mcp.servers.docs.headers.Authorization reads the credential MCP_PAT, which is empty`）；同时被校验拒绝的其他字段只按路径指出（`avatar.timezone is not
valid`）。因其他原因失败的插值（如引用了不存在的设置）会在其设置项处指出，并附上任何此类变量，
例如 `avatar.timezone holds an interpolation that cannot be
resolved`。在已安装的包中，如果某个实现没有任何已安装的包提供，会说明此版本的 setup 是否安装它，并给出针对所检查 bundle 的命令：
`` loop.plugin: no installed package provides loop 'realtime'; `alphaavatar setup my-avatar`
installs it (alpha-avatar-plugins-loop) ``。对于配置文件（setup 不接受文件），会显示
`setup installs it for a bundle, not a file`，不给出命令。

- 错误输出到 stderr，stdout 保持为空；错误指出失败的字段、bundle、profile 或变量，绝不显示被拒绝的值、文件内容、校验消息或异常自身的文本。终端放得下时，错误行完整输出；在较窄的终端上，每个出错的设置及其问题、包和安装方式各占一行。
- `--json` 输出 `{"valid": true, "config", "avatar_id", "home", "workspace", "plugins", "inference", "health"}`（`config` 为 `{"bundle", "default", "file"}`；`inference` 将每个 runner 方法映射到其 worker）或 `{"valid": false, "error": {"type", "fields", "diagnostic", "problems", "action"}}`：`fields` 是出错的设置，`problems` 列出每个出错设置及其 `line`、`location`、`problem`、`package`、`action` 和 `variable`，`action` 是下一步操作，与 [`doctor`](doctor.md) 的 `config.load` 给出的一致；凭据和控制字符已被移除。
- 文本遵循[各命令共用的布局](README.md#output)：终端一行放不下的值，续行与该值的起始位置对齐，如上面 100 列宽度下的 `router`。在终端中，分组以粗体信号青显示，未开启的工具 `none` 显示为黄色；管道、`NO_COLOR` 和 `TERM=dumb` 得到相同的文本，但不带样式。

## 退出码

| 退出码 | `init` | `check` |
| --- | --- | --- |
| 0 | 已创建 | 有效 |
| 2 | 文件已存在、名称或 ID 无效、设置不可读或写入失败 | 配置、选择或引用无效，路径检查失败，或在没有配置参数时设置或已存储凭据不可读 |
