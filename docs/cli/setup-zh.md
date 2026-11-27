# `alphaavatar setup`

[English](setup.md)

安装 bundle 所需的内容、检查它，然后把它设为默认 bundle。该命令属于 Linux x86_64 包：请先用 `install.sh` [安装该包](../DEPLOY.md#or-install-the-linux-package-then-choose-capabilities)。

```bash
alphaavatar setup                    # a new bundle, asked part by part from the reference
alphaavatar setup my-avatar          # an existing bundle, as config init made it or as edited
alphaavatar setup my-avatar --plan   # print the install plan, change nothing
```

| 选项 | 含义 |
| --- | --- |
| `BUNDLE` | 一个现有 bundle：不询问能力、模型或凭据，凭据来自环境、`.env` 或已存储的凭据；在终端中显示它的摘要和 `Install and enable?`。省略时，setup 在终端中询问 |
| `--name`, `--avatar-id` | 新 bundle 的名称（默认 `avatar`）和 Avatar ID（默认与名称相同）；不能与 `BUNDLE` 同时使用 |
| `--artifacts DIR\|URL` | 当前构建不是 release 时，其自身 wheel 所在的位置：CI 或本地构建的目录。不提供时，这类构建会在第一个问题之前被拒绝 |
| `--plan` | 以 JSON 输出安装计划：包、大小、SHA-256；不安装也不写入任何内容。被拒绝时同样在那里输出 `{"error": {"diagnostic": …}}`，原因与报告中给出的一致 |

## 询问：新 bundle

`alphaavatar setup` 从 `config init` 写出的参考配置开始，按 Enter 即保留参考配置的每个答案。在终端中，它逐步询问：

1. **能力**：语音（语音输入和输出，在本机进行语音活动检测）、视觉（摄像头帧送达模型）、本机模型（轮次判断、寻址、人脸和说话人识别）、ENV 记忆（由 Google 的 Gemini 从会话的音频和视频中提取的记忆），以及 Memory 和 Persona 存放向量的位置（Avatar 工作区中的 LanceDB，或你的 Qdrant）。关闭的部分保留其设置，以便之后重新开启，并且不再询问任何内容：不问模型，也不问凭据。默认不开启任何工具，并说明如何开启：在 bundle 的 tools profile 中开启 DeepResearch 或 MCP，然后运行 `alphaavatar setup <bundle>`；此版本的 setup 不安装 RAG。然后询问 bundle 名称（已有 bundle 使用该名称时会再次询问）和 Avatar ID。
2. **模型**：每个开启部分的供应商，然后是它的模型。

   | 部分 | 供应商 |
   | --- | --- |
   | 对话 | OpenAI，或提供 OpenAI Responses API 的自有服务器 |
   | Memory、工具记忆、Persona 画像 | OpenAI、Anthropic、Google、OpenRouter，或自有服务器 |
   | ENV 记忆 | Google |
   | Embedding | OpenAI、Google，或自有服务器 |
   | 语音识别 | `openai_segment`、`openai_realtime`，或提供 OpenAI 音频 API 的自有服务器 |
   | 语音合成 | `openai`、`voiceai`，或提供 OpenAI 音频 API 的自有服务器 |

   默认使用参考配置的供应商，并提供其模型作为默认选项；选择其他供应商时需要手动输入模型，不沿用任何模型。Memory、工具记忆和 Persona 画像可以使用为前面某个部分选择的模型（`As for memory: …`）。自有服务器会询问其 URL，并提供之前输入过的 URL；语音需要 `https://`，除非服务器在本机上；后端会拒绝的 URL 会被再次询问。语音合成会询问音色（Voice.ai 可不填），实现支持时还会询问语速；不读取 instructions 的模型（`tts-1`、`tts-1-hd`、Voice.ai）会写为 `instructions: null`。
3. **凭据**：所选配置读取的每个变量询问一次，并注明读取它的部分；然后询问是否存储这些凭据。
4. **安装**：分组显示 bundle 的运行配置和安装计划（bundle、其能力、每个部分的模型、语音、向量存放位置和工具，然后是安装信息），再询问是否安装并启用。现有 bundle 的这些内容按其设置的原样得出：每个处理器的模型按其所选任务中的名称显示（`provider.task`，Persona 为 `profile_delta_task`）；关闭的处理器显示为 `Off`，并附上其设置中保留的模型；每个存储的 embedding（Memory、Persona 和 MCP 共用时显示为一行，否则每个各占一行并列出其存储）；已开启的工具；各存储所在的位置；自有服务器只显示其地址，不含凭据、query 或 fragment。设置中交给非默认插件决定的内容，或其网关缺少的任务，显示为未指明，绝不显示成另一个模型。

在终端中，从列表中选择供应商：方向键移动，输入文字会把列表缩小到包含所输入内容的选项，Escape 清除输入，Enter 选择标记的选项。使用 `TERM=dumb` 或 `NO_COLOR` 时，选项带编号：输入编号，或输入只有一个选项包含的文字；Enter 选择默认项。Ctrl+C 或输入结束（Ctrl+D）会让终端保持原样，不写入任何内容。

没有终端时，setup 以退出码 1 拒绝运行，并给出 `alphaavatar setup <bundle>`。

## 指定：现有 bundle

`alphaavatar setup <bundle>` 按 `start` 的解析方式，安装 bundle 设置所选的内容（包括覆盖项和修改）：每个部分的插件、供应商的后端、向量存储，以及开关保留开启的本地模型。只写明模型名称的模型任务，与 `start` 一样，从 provider schema 的默认值中取得其类型和后端。制定计划时不导入任何插件。bundle 的插件打开的 LanceDB 索引，如果是用不同于 bundle 为其指定的 embedding 模型生成的，同样会在安装任何内容之前失败：给该存储换一个名称，或配置生成它时所用的模型。查找索引的位置与 `start` 打开它的位置相同：其 `client_path` 指定的目录，否则是 Avatar 自身为该插件准备的目录；Qdrant 索引按 `start` 打开它的方式检查。此版本的 setup 不为其安装任何内容的选择（例如不在 catalog 中的插件），会在安装任何内容之前失败，并按其设置项指出：

```text
FAIL  Setup failed; nothing was enabled
      This release's setup installs nothing for: tools.rag.plugin: tools.rag 'default'
```

这是 CI 和无人值守安装的方式，在 [`config init`](config.md#config-init) 之后，或使用你自己的 bundle：

```bash
alphaavatar config init my-avatar --avatar-id my-avatar
alphaavatar setup my-avatar           # credentials from the environment
alphaavatar config check my-avatar
```

凭据来自环境、`.env` 或已存储的凭据，并且不会存储任何凭据。在安装任何内容之前，按 `start` 的读取方式离线检查所选会话传输的凭据，不连接任何服务：LiveKit 的三个变量必须存在，且其 URL 必须为 `wss://`，除非服务器在本机上。任何一个缺失或格式错误都会立即失败，并指出其名称，绝不显示其值：

```text
FAIL  Setup failed; nothing was enabled
      The session transport (livekit) cannot start: LIVEKIT_API_KEY and LIVEKIT_API_SECRET are
      required, in the environment, .env or the stored credentials
```

没有终端时，不询问对计划的确认。安装后的检查是在新环境中对该 bundle 运行 `config check`，因此它需要却缺少的凭据也会在那里失败，并且不会启用任何内容。

## 凭据

| 变量 | 用于 |
| --- | --- |
| `OPENAI_API_KEY` | 来自 OpenAI 的内容：模型、embedding、任务、语音 |
| `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, `OPENROUTER_API_KEY`, `VOICEAI_API_KEY` | 选择该供应商的部分；ENV 记忆开启时，Google 的 key 也用于 ENV 记忆 |
| `ALPHAAVATAR_SERVER_KEY_<hash>` | 每个自有服务器，变量名根据其 URL 生成；服务器不需要 key 时可填任意文本 |
| `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | 会话传输 |
| `QDRANT_URL`, `QDRANT_API_KEY` | 向量存放在你的 Qdrant 中时使用；只有 Qdrant 要求时才需要 key |

- 服务器的变量名根据其 URL 的 scheme、host、端口和路径生成。写出默认端口或末尾带 `/` 仍是同一个 URL；路径不同则是另一台服务器。它的 key 只发送给该服务器，自有服务器绝不会收到 `OPENAI_API_KEY`。加载时会将该变量与应用覆盖项后生效的 `base_url` 核对：`base_url` 被改到另一台服务器或被删除的 bundle，在 [`config check`](config.md#config-check) 和 `start` 中都会失败。你自己命名的变量可以指向任何地方。
- 已在环境、`.env` 或已存储凭据中设置的值，按 Enter 即保留；空值或只含空白的值视为未设置，会被询问。哪个来源优先，见 [config 的凭据说明](config.md#credentials)。
- 输入的值只有在回答 yes 后才会存储到 `<home>/settings/credentials-<id>.env`，该文件只有你可读；已存储的值可能被其他 bundle 读取，只有再次回答 yes 才会被替换。这些值绝不会被输出或写到其他地方。

## 执行过程

- 根据包内的 catalog 制定计划：每个产物都带有版本和 SHA-256。当前环境已有的内容保留在计划中，因此之前的 bundle 仍能工作。参考 bundle 约需下载 515 MB（语义寻址需要 x86-64-v3 CPU）；本机除语音活动检测外不运行任何模型时，约为 210 MB。
- 首先检查机器（glibc、CPU）和可用空间（约为下载量的四倍）。
- 在当前版本旁安装到 `<prefix>/envs/<plan>/`，或复用相同计划的环境，然后检查它：其原生库能够加载，且其 `alphaavatar config check` 接受该 bundle。
- 只有这时才将 `<prefix>/current` 切换到它并启用 bundle。对 `settings.yaml` 的一次替换同时把该 bundle 设为默认，并指明随它存储的凭据，因此即使 setup 被强制终止，两者也要么都保持原样，要么都是新的。
- 在此之前失败或被中断时，当前版本、命令、bundle、设置和凭据都保持原样，本次运行创建的环境会被删除：先将它整体移入一个带标记的暂存目录；暂存目录（本次运行的，或某次被停止的运行留下的）在最后才去掉标记，因此即使运行在这时被停止，留下的也只有带标记的暂存目录，下一次安装会删除它们。模型权重不属于计划：runner 在启动时将其下载到模型缓存中，在 `start` 和 [`doctor`](doctor.md#runtime-start) 的运行时诊断中都是如此。
- 获取 `install.sh` 使用的同一个锁 `<prefix>/.install.lock`：一个安装正在运行时，向该 prefix 进行的第二个安装会被拒绝。不是普通文件的锁，例如链接或管道，会被拒绝并保持原样。

它分五个步骤报告，每个步骤完成后占一行。在终端中，当前步骤以信号青显示，其所在行显示正在进行的下载；管道、日志或 `NO_COLOR` 下，每个产物各占一行。询问模式下，每个步骤的问题显示在该步骤下方，计划显示在确认之前：

```text
AlphaAvatar / Setup

01  Capabilities
    Each question starts from the reference configuration: Enter keeps its answer.
    Voice: speech in and out, voice activity detected on this machine? [Y/n]:
    Models on this machine: turn taking, addressing, face and speaker recognition? [Y/n]: n
    …
    Tools  None enabled (default)
           Enable DeepResearch or MCP in the tools profile,
           then run: alphaavatar setup <bundle>
           RAG is not available through setup in this release.
    …
01  Capabilities   Bundle first · Voice on · Vision on · Local models off · ENV memory on
02  Models
    Provider for the conversation: OpenAI
      Model for the conversation [gpt-5.6-luna]:
    Provider for memory: ↑↓ to move, type to narrow, Enter to choose
      As for the conversation: OpenAI gpt-5.6-luna
    › OpenAI  (default)
      Anthropic
      …
02  Models         OpenAI · Google
03  Credentials    Ready
04  Install

    Configuration
      Bundle          first · will become the default
      Avatar ID       first
      Version         0.6.9 · linux-x86_64

    Capabilities
      Voice           On
      Vision          On
      Local models    Off
      ENV memory      On

    Models
      Conversation    OpenAI       gpt-5.6-luna
      …

    Storage & Tools
      Vectors         LanceDB · Avatar workspace
      Tools           None enabled (default)
                      Enable DeepResearch or MCP in the tools profile,
                      then run: alphaavatar setup first
                      RAG is not available through setup in this release.

    Installation
      Packages        85
      Download        212 MB
      Plan            97138f31be7bfc50
      Environment     ~/.local/lib/alphaavatar/envs/97138f31be7bfc50

    Install and enable? [Y/n]: y
04  Install        85 packages · 212 MB
05  Validate       PASS · 3 runners

OK    Bundle enabled
      Default       first
      Environment   ~/.local/lib/alphaavatar/envs/97138f31be7bfc50
      Start reads OPENAI_API_KEY, LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET from the
      environment or .env.

Next
  alphaavatar doctor first
```

现有 bundle 根据其设置报告相同的步骤：

```text
01  Capabilities   Bundle reference · Voice on · Vision on · Local models on · ENV memory on
02  Models         As the bundle's settings choose them
03  Credentials    From the environment, .env or those stored
04  Install        105 packages · 514 MB
05  Validate       PASS · 8 runners
```

`Validate` 统计新环境中 `config check` 计划的推理 runner 数量。失败、拒绝计划或 Ctrl+C 会在 stderr 上报告为 `FAIL  Setup failed; nothing was enabled`、`WARN  Cancelled; nothing was enabled`、`WARN  Interrupted; nothing was enabled` 或 `WARN  The input ended; nothing was enabled`，原因显示在下方；使用 `--plan` 时，步骤也输出到 stderr，stdout 只留给计划的 JSON。之后用 [`alphaavatar doctor`](doctor.md) 诊断该 bundle，再用 [`alphaavatar start`](start.md) 或 [`alphaavatar dev`](dev.md) 启动它。每个界面（包括颜色）都收录在 [cli.html](cli.html) 中。

## 退出码

| 退出码 | 含义 |
| --- | --- |
| 0 | 已启用，或已输出 `--plan` 的结果 |
| 1 | 未启用任何内容：回答了 no、输入结束、没有可询问的终端且未指定 bundle、setup 不安装的选择、缺少凭据、机器或可用空间不满足、下载或检查失败、另一个安装正在运行 |
| 2 | 安装前被拒绝：`--name` 指定的 bundle 已存在、设置不可读、其他错误 |
| 130 | 被 Ctrl+C 中断；SIGTERM 为 143，SIGHUP 为 129 |
