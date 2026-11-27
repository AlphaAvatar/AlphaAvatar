# `alphaavatar doctor`

诊断安装和一份配置：先做静态检查，再做运行时诊断。Doctor 像 `start` 一样启动 bundle 的运行时，按真实输入的节奏向它送入一段固定的语音样本，测量输出的内容，并把它唯一的场景运行多次，每次都在独立的会话中，以便报告每个指标在各轮中的结果。运行时像为真人服务时一样完成自己的工作；Doctor 只负责提供输入、观察、判定和清理。一条命令完成两者，无需另外启动任何东西。

```bash
alphaavatar doctor                                      # the default bundle, if there is one
alphaavatar doctor [<bundle> | <file>] [KEY=VALUE ...]  # as config check selects them
alphaavatar doctor --rounds 10                          # the scenario 10 times (default 5)
alphaavatar doctor --no-metrics                         # the static checks alone
alphaavatar doctor --json                               # the same report as JSON
alphaavatar doctor --list                               # the checks, without running any
```

可选参数和覆盖项遵循 [`config check`](config.md#choosing-a-configuration)：相同的 `.env` 和已存储的[凭据](config.md#credentials)，相同的主目录、bundle 或文件选择、profile、覆盖项、校验以及只读的工作区检查。没有参数也没有默认 bundle 时，Doctor 会说明如何创建一个，并照常检查所有不需要配置的项目。`--no-metrics` 不做运行时诊断：不启动任何 runner，也不联系任何服务。否则，运行哪些内容取决于配置启用了什么，并且须经终端前的用户或配置[授权](#授权)。`--rounds N`（1 到 50）是唯一控制运行量的设置。要诊断另一份配置，例如另一个 STT 插件，就指明它：用覆盖项或另一个 bundle，每次运行单独报告。

## 检查项

| ID | 检查内容 | 需要配置 | 经授权后可能访问 |
| --- | --- | --- | --- |
| `system.platform` | 操作系统；Host 所需的 POSIX 本地 socket API（AF_UNIX）——只检查是否存在，不打开 | | |
| `python.version` | 解释器是否属于 AlphaAvatar 支持的 Python 版本 | | |
| `packages.alphaavatar` | 已安装的 AlphaAvatar 包来自同一个发布版本；Host 的依赖已安装 | | |
| `config.load` | 选择、profile、覆盖项和校验，以及 `config check` 的结果 | | |
| `config.runners` | 配置选定的推理 runner 和 worker | 是 | |
| `packages.capabilities` | 已启用能力所需的包：RTC 后端、loop、context、模型供应商后端、voice、router、status、character、memory、persona 和工具，及其 extra 和版本 | 是 | |
| `paths.home` | 应用主目录：其来源、状态、所有者和权限模式、写权限、设置、bundle、剩余空间；目标不存在的链接判为失败 | | |
| `paths.cache` | 缓存根目录：状态、写权限、已下载的模型、剩余空间 | | |
| `paths.workspace` | Avatar 的工作区：状态、写权限、剩余空间 | 是 | |
| `session.start` | 该配置的一个临时会话：像 `start` 那样装配并就绪 | 是，会话 | 外部服务 |
| `models.runners` | 计划的 runner 按 `start` 的方式启动，缺少的模型文件会下载：运行时的[启动](#运行时启动)样本，以及每个 runner 的启动、worker、调用、排队和执行指标 | 是，会话 | 模型下载、外部服务（向量库的探测） |
| `services.external` | 模型、语音、向量库、工具和 MCP 服务：只有经授权后，会话才会访问；从不联系 RTC 服务器 | 是 | 外部服务 |
| `session.scenarios` | 固定样本经过每条已启用的模态链路，附指标和证据 | 是，会话 | 外部服务 |
| `session.cleanup` | 会话、executor、运行时、runner 进程、socket 和临时工作区均已回收 | 是，会话 | |
| `devices.media` | 麦克风、摄像头和播放器：属于客户端设备，从不打开——不验证 | | |

静态检查不创建、不下载、不加载、不启动、不联系任何东西，也不打开任何 socket；只有运行时诊断可能下载模型文件或调用服务，且只在[授权](#授权)之后。`--list` 列出每项检查可能访问的对象。Doctor 无法读取的 `.env` 会作为 `config.load` 失败出现在同一份报告中。无法加载的配置会使 `config.load` 失败，内容与 [`config check`](config.md#config-check) 给出的相同，并经过同样的诊断：按路径指出每个出错的设置，例如读取了一个没有值的变量的 MCP 服务器和请求头，并以 `action` 给出下一步，对所检查的 bundle 给出 `alphaavatar setup <bundle>`；以文件指定的配置不给 setup 命令。进程中首次导入配置会加载插件，`config check` 和 `start` 也是如此，其中一些库在导入时会探测本机：`urllib3` 会打开并绑定一个 IPv6 socket，以测试是否支持 IPv6。

## 诊断会话

它就是 `start` 会运行的那个运行时：计划的 runner 在同一个推理运行时中启动，启动方式、runner 计划、模型解析和缓存都与 `start` 相同：已缓存的模型文件直接加载，缺少的则下载。每个会话的 Engine、插件和输出运行时都来自 Host 自身的 `create_execution`。VAD、STT、轮次判断、Context、Loop、模型和 TTS 都按配置工作。不同之处在于：

- **进程。** 诊断在 Doctor 自己的一个进程中运行，该进程是其自身进程组的组长。它的推理 socket 和日志捕获都留在该进程内，调用方的环境和 logger 保持原样。在 Host 内部运行时，它不继承该 Host 的推理 socket、runner 计划或日志客户端（`ALPHAAVATAR_INFERENCE_SOCKET`、`ALPHAAVATAR_INFERENCE_PLAN`、`ALPHAAVATAR_LOG_CLIENT`）。它或其 runner 打印的内容写入 Doctor 临时目录中的一个文件，而不是终端：失败的 runner 在 `models.runners` 中指明，未留下报告就退出的进程会连同它打印的最后一行一起指明。stdout 只承载报告，因此 `--json` 的输出可以直接解析。Ctrl+C 只送达 `doctor` 命令，由它请求该进程停止；未能及时退出的进程会连同其整个进程组（包括 runner）一起被终止。
- **快照。** 授权依据 Doctor 已加载并校验的配置决定，诊断进程启动的正是同一份快照：其间不会重新读取任何内容。
- **存储。** 诊断写入的内容单独隔离：快照被移到一个临时目录上，包括 Avatar 的工作区，以及默认 memory、persona 或 MCP 存储显式指定的任何本地 LanceDB 路径；后者移到该目录内默认路径所在的位置。远程向量库（Qdrant）保存着 Doctor 无法隔离的真实 Avatar 数据：此时诊断不运行，除非配置声明其远程存储保存的是测试数据（`host.doctor.test_stores: true`）；这时诊断会写入它们，`session.start` 会把每个都标为测试存储。该目录也是进程的临时根目录，因此其运行时的 socket 也放在这里，结束后该目录被删除。模型缓存是配置自身的缓存，与 `start` 的用法相同。
- **传输。** Doctor 扮演 RTC 后端的角色：它在 RTC 输入适配器发布媒体的位置、按它们的节奏（20 ms 的麦克风帧，屏幕帧按 `runtime.perception.video_publish_interval_sec`）发布样本，并像 RTC 传输那样读取输出边界，充当本地音频队列。不涉及任何 RTC 服务器、客户端或设备。

不计划任何 runner 的配置是有效的：`models.runners` 因无可启动而跳过，`session.start` 报告会话自身的启动。没有语音（VAD、STT 和 TTS）的配置没有 Doctor 可运行的场景：不询问、不启动任何东西，`session.start` 说明缺少什么。

### 授权

运行时诊断会启动运行时，可能下载缓存中缺少的模型文件，并调用配置中指定的服务，这些服务往往按调用计费。它只在授权后运行，且一次授权全部内容。在终端中，Doctor 在静态检查之后说明它将做什么，并只询问一次：

```text
Runtime diagnosis
  It starts this bundle's runtime as start does, then runs this scenario 5 times, each time
  in a session of its own:
    voice_vision  Speech and screen frames in one model request
  Model files the cache lacks are downloaded first, as start would.
  It calls the services this configuration names:
    model providers (langchain, openai)
    speech recognition (openai_segment)
    speech synthesis (openai)
    embeddings as alphaavatar.memory.vdb.lancedb starts
    embeddings as alphaavatar.persona.vdb.lancedb starts
  Calls to these services may be billed.
    Run the diagnosis? [y/N]:
```

回答 yes 只授权这一次运行，针对的是 Doctor 已加载并检查过的配置：这次运行使用同一份快照和同一个计划：列出的场景和轮数，就是其预算所依据的、也正是实际运行的。回答 no、直接按 Enter、输入结束或使用 `--no-metrics` 时，只做静态检查：`session.start`、`models.runners` 和 `session.scenarios` 为 `SKIP`，即 `Not run: the diagnosis was declined`（或 `left out with --no-metrics`），`session.cleanup` 说明没有启动任何东西。在此之前不启动任何东西，连 runner 也不启动，无论它来自哪个包。使用 `--json` 时，问题输出到 stderr，stdout 仍然只有 JSON。

没有终端时（例如在 CI 中）不会询问：只有配置能授权。

```yaml
# host profile (configs/profiles/<bundle>/host/host.yaml)
doctor:
  external_services: true   # default false: the runtime diagnosis, downloads and calls included
  test_stores: false        # true: the remote vector stores named hold test data Doctor may write
```

或只为一次运行授权：`alphaavatar doctor my-avatar host.doctor.external_services=true`。已在配置中授权时不会再询问。既没有终端也没有该设置时，运行时诊断不运行：`session.start` 列出它将调用的服务，以及如何允许它运行。

`services.external` 列出配置中指定的每个服务：是否已配置、已授权、已访问（它应答了会话的某个阶段）和已通过（它完成了该阶段的服务，且没有 Turn 停在那里），或者其中哪些项是 Doctor 运行的任何内容都无法体现的。没有 Turn 使用过的模型供应商，按向量库在其 runner 启动时发给它的探测来判定：全部启动即为通过；只有探测本身失败（`EmbeddingProbeError`）时才判为失败；向量库在发出探测之前就失败（例如 LanceDB 未能打开其本地存储），或更早的 runner 使它们未能启动时，判为未观测到；runner 自身的失败见 `models.runners`。

### 运行时启动

运行时只启动一次，其 runner 逐个启动，每个都在自己的 `runtime.inference.initialize_timeout` 之内完成（含下载），与 `start` 时相同；某个 runner 失败，启动即失败，并给出它自己的错误及其抛出位置，其余都不再运行。这一次启动就是一个样本，即 `models.runners` 中的 `runtime_start`：包括它的耗时（从启动开始到其结束：所有 runner 就绪，或出现第一个失败），以及这期间模型缓存的变化，只计净变化（`the model cache grew by 8.4 MB (net)` 或 `did not grow`）：扫描缓存无法区分下载和文件替换，因此从不断言其中任何一种，首次启动的增长也绝不会被当作使用缓存的启动。本机关闭下载（`ALPHAAVATAR_MODEL_OFFLINE` 或 `HF_HUB_OFFLINE`）时无法加载其模型的 runner，会像在 `start` 时一样失败，action 也会说明这一点。随后给出每个 runner 自己的启动时间、处理的调用，以及排队等待和执行的峰值。

### 场景

| 场景 | 条件 | 输入 | 完整回答必须是 |
| --- | --- | --- | --- |
| `voice_vision` | 已配置 VAD、STT 和 TTS，视觉开启（`vlm` 或 `realtime`） | 口述 "What color is the card on my screen?"（一句话），同时以共享屏幕的方式提供一张绿色卡片的图片 | `green`，或说明该颜色的一个短句：`The card is green.` |
| `voice` | 已配置 VAD、STT 和 TTS，视觉关闭或仅文本 | 口述 "What is two plus three? Answer with just the number."：两句话，每句都须出现在转录中 | `5` 或 `five` |
| `image_input` | — | 目前还没有输入传输能把图像送入会话 | |
| `visual_output` | 已配置 Character | 它的帧在浏览器参与者中渲染，不携带 Turn | |

只运行一个场景：视觉开启时为 `voice_vision`，关闭时为 `voice`；另一个为 `not_enabled`。要诊断两者，就运行两次 Doctor，其中一次加上 `vision.enabled=false`。场景运行 `--rounds` 次，默认 5 次，每次都在独立的会话中：任何 Turn 都不带有另一个 Turn 的历史。运行时为所有轮次只启动一次；第 1 轮是启动后的第一轮，与之后各轮分开显示。文本指标（首个文本、文本完成）属于语音场景本身；不运行键入文本的场景。

颜色用一句话来检查，这样检查的是图片；是否丢句则用两句话来检查。对 `voice`，每句话都必须出现在已提交的转录中。对每句话，JSON 中的 `sentences` 分别保存各层对其声音的记录：

- `coverage`：已关闭的语音片段包含了它多少声音（`full`、带 `covered_ms` 的 `partial`，或 `none`），以及相应的 `segments`；其声音无法定位时为 `null`，例如录音的有声段与句子对不上时；
- `stt`：STT 是否及时为包含它的片段返回了终稿（`final`），没有返回（`no_final`，或其片段如何结束），还是只在 Turn 提交之后才返回（`late`）；
- `adopted`：Turn 是否采用了该终稿，以其首个请求所指明的为准；
- `content`：Turn 采用的终稿是否包含这句话的词；未采用任何终稿时为 `null`，因为看不到其文本。

没有被听到的句子归入第一个丢失它的层：没有片段包含其声音，或只有某个片段包含其部分声音时，归为 `vad`；没有它的终稿，或 Turn 采用的终稿漏掉了它的词时，归为 `stt`（一个片段包含两句话、其终稿只有第一句，就属于这种情况）；它的终稿到了，但在 Turn 提交之后才到，或及时到达却未被采用时，归为 `turn`；证据无法定位时，归为 `unknown`。该轮相应停在 `vad.closed`、`stt.final`、`turn.committed`，`unknown` 则停在 `transcript`。终稿未到时就已决定的 Turn 会等待它，最长到 `transcript_timeout_sec`（3 s）：及时到达的终稿并入该 Turn；到期限时，每个仍没有终稿的片段在原位置带上一条 `voice.transcription_unavailable` 通知，决定继续进行，之后才到的终稿被作废，绝不会被后续的 Turn 采用。这些只说明一轮在哪里丢了句子，不说明轮次判断为何如此。

语音样本是随 Host 包发布的录音（`alphaavatar/host/tools/doctor/
samples/`，16 kHz 单声道 PCM16，时长约 2.4 s 和 3.3 s），
由 `scripts/quality/doctor_samples.py make` 用 FFmpeg 的 flite 语音离线制作；`scripts/quality/doctor_samples.py check` 通过 Doctor 读回这些样本，CI 只用构建好的 wheel 执行这项检查。Doctor 不需要其他任何东西：只有测试才用的小样本放在各自包的 `tests/fixtures/` 中，大样本（长时间、多流或负载运行）放在 Hugging Face Dataset 中，只有需要它们的测试才会获取。样本播完后，麦克风会像真实麦克风一样继续发送静音，直到 Turn 结束。转录必须包含问题中的词。忽略大小写、首尾空白和标点后，回答是预期答案之一即为通过；对卡片，只说明颜色而不含其他内容的短句也通过（`The card is green.`、`It's green.`）。颜色错误、同时提到另一种颜色、否定、含糊其辞（`maybe`、`I think`、`looks`）、疑问（`Green?`），或包含该数字的另一个数，都不通过。图片以屏幕共享帧的形式提供，因为它没有人脸：摄像头会让 Turn 进入音视频模式，该模式会等待卡片无法给出的视觉寻址。

每个场景以一个结果结束：`passed` 或 `failed`（已测量），`not_enabled`（配置未选择它），`conditions_unmet`（已选择，但缺少授权、模型、样本或会话），`no_coverage`（已选择，但 Doctor 目前还无法驱动或观测它），或 `interrupted`。失败的场景给出其 `blocked_stage`：`input`、`vad.closed`、`stt.final`、`turn.committed`、`frames.selected`、`model.request`、`request.input`、`request.content`、`request.frames`、`model.first_event`、`text.first`、`text.complete`、`audio.first`、`outputs.complete`、`run.completed` 中第一个未到达的阶段；所有阶段都到达但回答不符合任务时为 `answer`；Turn 本身以超时、中断或会话失败结束时，分别为 `turn.timeout`、`turn.interrupted`、`turn.session_failed`。它还给出生产者分类的 `cause`，供应商给出代码时附上该代码，例如 `ModelCapabilityError: image_input`、`ModelRequestError: http_401` 或 `speech_synthesis_failed`。

语音输入和选中的帧必须汇合在同一个模型请求中。Loop 记录每个请求实际携带的内容：Turn 提交的输入、Turn 的每条输入观测是否在其中（以其文字或音频部分的形式），以及它的帧。Turn 的首个请求携带 Turn 已提交的输入时，`request.input` 通过；携带样本 STT 终稿的那条观测时，`request.content` 通过；携带 Doctor 发布的帧时，`request.frames` 通过。Turn 的 Run 的每个输出单独判定（`outputs`）：`completed`、`failed`、`interrupted`、`timed_out` 或 `not_ended`，并附原因；只有全部输出都完成时，`outputs.complete` 才通过。以超时、中断或会话失败结束的 Turn 保持该结局，即使其输出之后完成也是如此：迟到的内容留作证据，只有已完成的 Turn 才给出完成时间。

任何一轮失败的场景都会使 `session.scenarios` 失败：五轮中有一轮失败也值得知道；未运行的场景则作为部分覆盖给出警告。

### 失败如实报告

Doctor 只运行给定的配置，不运行其他任何东西：没有备用配置，没有第二个运行时，也没有键入的 Turn。拒绝接收图片的模型（`ModelCapabilityError: image_input`；OpenAI 适配器在无法编码或内联图片时会这样报告）使 `voice_vision` 在模型处失败，下一步建议选择能接收图像的模型，或关闭视觉；无法启动的 runner 使启动失败；失败的语音输出使该轮失败，其各个输出逐一判定。凭据被拒、通用的 HTTP 400（`ModelRequestError: http_400`）、出故障的服务：各自保留自己的原因。

### 指标

所有时间都在同一个时钟上，即会话的单调时钟；每个指标都从**最终语音**（final speech）起算：即携带样本最后一个有声采样点的帧被发布的时刻；尾随的静音照常随后发送。指标都属于 Host，从诊断输入到 Host 的输出边界：每项测量都止于 Host 的输出。Host 在某个服务上观测到的等待，例如 `stt_wait` 或 `model_first_event`，既包含服务也包含网络：没有一项是服务自身的耗时。LiveKit 的传输、客户端显示或播放的内容以及物理设备都不测量，因为没有任何 RTC 服务器、客户端或设备参与；`devices.media` 会说明这一点，它们另行测量。图片是共享屏幕，从不是摄像头的帧，因此读取摄像头的功能（例如人脸识别）不会在其上运行：`devices.media` 也会说明这一点。

端到端指标依次为：`first_text`（Runtime first text，即输出的第一个回答文本块）、`first_audio_frame`（运行时输出的第一个回答音频帧）、`response_final`（所有输出完成）、`text_complete` 和 `audio_last_frame`；后三项只在所有输出都完成时给出。

从最终语音到第一个音频帧，一轮会经过一串节点，它们都属于 Turn 的首个模型请求，以及由该请求流式输出其文本的那些输出。其阶段 `input`、`context` 和 `output` 各自从结束上一阶段的节点开始，因此对于所有边界都齐全的一轮，三者之和恰好等于 `first_audio_frame`；每一行从它前一个节点开始：

| 阶段 | 行（`<stage>.<node>`） | 起点 | 终点 |
| --- | --- | --- | --- |
| `input` | `input.vad_close` | Final speech | VAD close：下一行所述终稿所在的片段关闭 |
| | `input.final_transcript` | VAD close | Final transcript：请求携带的最后一个 STT 终稿 |
| `context` | `context.turn_commit` | Final transcript | Turn commit |
| | `context.context_ready` | Turn commit | Context readiness check complete |
| | `context.context_built` | Context readiness check complete | Context built：Loop 在 Context 构建返回处记录 `context.built`，以它发起的请求标识 |
| | `context.request_sent` | Context built | Model request sent：完成编码并交给传输层，取首次尝试；其间请求的组装计入这一行 |
| `output` | `output.first_text_delta` | Model request sent | 该请求的 First text delta |
| | `output.tts_request` | First text delta | 其回答的 TTS request |
| | `output.first_pcm` | TTS request | First PCM（HTTP PCM 供应商会记录它） |
| | `output.first_audio_frame` | First PCM | First audio frame |

阶段内缺失或乱序到达的节点并入下一行：该行从按顺序观测到的最后一个节点开始（其 `start` 指明该节点，`merged` 列出被略过的节点），且不作为这两行中任何一行的样本。缺少边界的阶段不测量，并说明是哪个节点以及原因（`Model request sent not observed: its provider logs no request sent`）；不涉及该边界的行仍照常测量。请求的重试是一次独立的尝试：`model_request_attempts` 统计尝试次数，证据逐一列出，节点取第一次。首个请求没有流式输出文本、由后来的请求作答时，output 阶段不测量：其第一个音频帧回答的是后来的请求。

| 指标 | 起点 | 终点 |
| --- | --- | --- |
| `first_visual_output_frame` | — | 无：没有视觉输出到达输出边界 |
| `last_required_input` | 最终语音 | 最后一个选中帧或有声采样点进入（`voice_vision`） |
| `audio_duration`, `audio_frame_interval`, `audio_max_gap` | 输出的回答音频帧 | |
| `audio_underruns` | 第一个回答帧 | 最后一个：在第一帧时启动的实时队列会在何处断流 |
| `audio_rtf` | 第一个回答帧 | 最后一个：生成耗时与音频时长之比，两者都给出 |
| `stt_request_to_final` | 片段提交给 STT | 该请求的最后一个终稿 |
| `stt_queue`, `stt_connect`, `stt_tls`, `stt_upload`, `stt_wait`, `stt_first_event`, `stt_stream` | 该终稿的 STT 请求，按其插件的计时（`stt.request`） | 它在插件队列中的等待；它新建连接时的 TCP 连接和 TLS 握手（连接复用时没有，并注明）；上传；从音频发出到应答头的等待，网络和服务合计；从这些应答头到首个流事件，以及到转录完成。传输层未追踪的请求（调用方自带的客户端，或发送前就失败的请求）只有排队一项：其余为未观测到，既不算复用也不算新建。不计时的插件，这些指标都不测量 |
| `context_ready_wait` | Context 请求该 Turn 的上下文 | 就绪（Context manager 自己的指标） |
| `association_ready` | 最终片段的语音关闭 | 其关联首次就绪（负值：在此之前已就绪）。没有任何环节等待它：Turn 的参与者在需要时随时读取，因此只有在准入之后才就绪时，note 会说明这一点，因为在那之前读取参与者的环节（例如该 Turn 自身的上下文）看到的是未归属的片段；会话结束时的 Memory 仍会读到它。就绪不等于已识别；证据指明它是如何释放的（`participant.segment_ready`），未绑定的还说明原因：`inference_failed`、`no_vector` 或 `no_match`。Host 日志中有相同的信息：每个片段一行（`Speaker association settled`，已知时附语音长度 `speech_ms`），每个 Turn 一行，列出准入时每个片段的关联（`Turn participants`）。短于一秒的语音在关闭时以未绑定（`no_vector`）定案，其来源的下一段语音之后可以绑定它；`Speaker association bound late` 会说明这一点 |
| `addressing_queue`, `addressing_inference` | 对该 Turn 最终转录的语义寻址（`addressing.semantic`） | 从入队（转录到达）到开始的等待，然后是其推理，即模型运行与它向推理服务发出的请求合计。在给出结果前就被取消的判断（例如 Turn 先提交时）只作为证据：不测量 |
| `assessment_queue`, `speech_completion_assessment`, `decision_holds` | router 的追踪（`input.assessment`、`input.hold`） | 轮次判断模型的最后一次评估：从入队（其语音关闭或其转录到达）到开始的等待；然后，在 Turn 的终稿与其提交之间，该模型的各次运行（被替换的那次也计入）和定时 hold，各自只计这段区间内的部分。hold 用于等待不确定的说完判断或寻址（`speech_completion_wait_sec`、`addressing_wait_sec`，取两者中较晚的期限）；基于文本的寻址，其期限从它所需的转录到达后才开始。终稿 → 提交这一行扣除它们后剩下的，是 router 自身的处理 |
| `model_request_client`, `model_request_prepare`, `model_request_encode`, `model_request_frames`, `model_request_bytes`, `model_request_attempts` | 首次尝试发送 | 客户端就绪（ms）、从取到请求到首次尝试发送（ms）、在此编码（ms）、图片数、已发送的请求体（字节）、尝试次数：供应商自己的记录 |
| `model_first_event` | 模型请求已发送 | 首个流事件，它可能只表示响应已开始 |
| `frame_input_to_available`, `selected_frame_age` | 帧到达 | 发布到感知；模型请求 |
| `last_selected_frame_to_cutoff` | 最新的选中帧输入 | Turn 已提交（负值：它在 cutoff 之后到达） |
| `vision_wait` | Turn 已提交 | 帧可用：只在观测到等待时给出，迄今从未出现 |
| `session_ready` (`session.start`) | 会话装配 | Engine 就绪：所有会话的中位数，每个会话的值见 `values` |
| `runtime_start` (`models.runners`) | 运行时启动开始 | 所有 runner 就绪，或第一个失败：其 note 为模型缓存的净变化 |
| `queue_wait_max`, `execution_max` (`models.runners`) | 每个 runner 自己的汇总 | |

每个指标给出其值、单位、起止事件、样本数和边界；事件未观测到时，值为 `null`、样本数为 0，指标知道原因时由 `note` 说明（`not recorded: the turn ended by timeout`）。已测量的指标，其 `note` 则用来描述该指标。

`session.scenarios` 在 `summaries` 中汇总各轮，每个场景一项，附其各轮运行所用的 `configuration`（模型、STT 和 TTS 的后端及模型、视觉）以及它们听到的 `sample`（按名称和内容摘要）：运行和通过的轮数、其余各轮停在哪里（`stopped_at`），以及对每个指标，在通过的轮次上：单独给出第一轮的值（`first`），然后是之后通过且观测到该指标的各轮：其数量、中位数和范围（`samples`、`median`、`low`、`high`），从 20 个样本起还给出第 95 百分位数（`p95`）。`all_` 字段给出除第 95 百分位数外的相同内容，范围是观测到该指标的每一轮，包括失败的轮次，第 1 轮同样单独给出（`all_first`、`all_samples`、`all_median`、`all_low`、`all_high`）；`merged` 统计其值从更早节点起算的轮数。文本显示通过各轮的表格，有任何一轮未通过时，还显示所有轮次的表格；`n` 是计入的后续轮数。每轮自己的指标保留在该轮中，见 `scenarios`，并附其 `round`。一台机器上的少数几轮描述的是这台机器和这些服务当下的情况，而不是这条管线的一般行为。

`scripts/quality/doctor_compare.py NAME=REPORT.json ...` 把保存的报告并排对比：用同样的方法从各轮重新计算每个指标，与报告自身的汇总核对（有差异时指明，退出码为 1），并统计 hold、取消、已作废片段的终稿、重试的请求以及按层统计的丢句。它还检查汇总是否覆盖了各轮：各轮运行过的每个场景和配置都有一份汇总，没有不对应任何轮次的汇总，每份汇总都含有其各轮具有的指标和它们给出的 `stopped_at`。

### 证据

每个已测量的场景按顺序列出观测到的内容，时间相对于响应起点：Doctor 的输入（`input.voiced_end`、`input.screen_first`），输入追踪的各阶段（`perception.speech_closed`、`stt.terminal`、`input.decision`、`turn.committed`、`context.frame_selected`、`model.request`、`model.request_frame`、…），Loop 和语音日志（`context.built`、`model.started`、`model.first_event`、`stt.request`、`speech.request`、…），以及输出事件（`output.text_chunk`、`output.audio_frame`、`output.control`、`output.playback`）。追踪按会话对标识加盐；证据显示其缩短后的 token（`turn`、`decision`、`input`、`segment`、`run`、`request`、`observation`），相同的 token 即同一个标识：片段关联其输入、决定和 Turn（router 的输入就是 Turn 的输入）；Turn 关联其模型请求及该请求的帧，以及其 Run 的输出。`request` 汇总这些关联，`frames` 说明请求携带的帧中哪些是 Context 选中的，每帧都与 Doctor 发布的某一帧对应。这里的 Turn 指本会话中已提交、且其感知范围包含本次输入的那个 Turn，因此其他 Turn 或会话的迟到事件绝不会被计入。没有 Turn 提交时，证据从语音输入自身的声音开始跟踪（其片段、STT 和轮次判断决定），因此报告会指明它停在哪个阶段，例如在 STT 终稿到达之前，输入因缺少转录而被取消。证据是有界的，保留链路开始、转折和结束之处，并经过与报告其余部分相同的输出边界。

### 时限

运行时的启动与 `start` 采用相同的时限：每个 runner 受其自身的 `runtime.inference.initialize_timeout`（默认 300 s）限制，含下载，因此报告的错误就是它自己的超时；Doctor 的时限是所有 runner 的超时之和再加 30 s，只用来兜住不遵守任何时限的启动。装配一个会话及其就绪最多 180 s，一个 Turn 最多 60 s，全部内容最多比启动时限多 480 s，超过三个 Turn 后每多一个 Turn 再加一个 Turn 的时限；关闭有自己的时限。一旦请求了停止或预算已用尽，就不再启动任何东西；每一步保持其等待结束时的状态：在期限之后才返回的步骤仍算超时，它返回的内容会被关闭。不能自行结束的 Turn 被结束时，其样本播放和输出也随之结束。Ctrl+C 停止诊断：正在运行的部分被关闭，未运行的轮次如实报告为未运行，退出码为 130；取消 `Diagnosis.run()` 时，会在抛出异常前以同样的方式关闭。无论成功、失败、超时还是中断，会话及其 executor 都先于运行时关闭，然后删除临时目录；其中任何部分、某个 runner 进程或诊断进程本身不得不被强制终止或留下了残留时，`session.cleanup` 失败。请求停止后，诊断进程有 60 s 完成关闭；察觉其退出后，还有几秒用于回收，因为内核要在已结束进程的管道关闭片刻之后才允许回收它。每次强制终止都会指明错过的期限和已等待的时长；强制终止几秒后仍未回收的进程如实报告，并任其留下，绝不无限期等待。

## 结果

| 状态 | 含义 |
| --- | --- |
| `PASS` | 已检查，正常 |
| `WARN` | 可以工作，但需要注意：尚无配置、包来自不同的发布版本、剩余空间不足 1 GiB、`start` 时会下载某个模型 |
| `FAIL` | `start` 或 `dev` 会失败，或按当前配置无法工作；某个已测量的场景失败 |
| `SKIP` | 未运行或无法在此验证：需要配置、授权或客户端 |

文本输出在检查项下方用一行说明这些状态。跳过的检查总会说明原因，未测量的指标显示为 `—`（JSON 中为 `null`）并说明原因，绝不显示为 `0`；失败的轮次保留在报告中，出现在它自己的表格和 `Failed rounds` 中，绝不会被排除在描述本次运行的指标之外。

| 退出码 | 含义 |
| --- | --- |
| `0` | 没有检查失败；允许有警告和跳过的检查 |
| `1` | 至少一项检查失败 |
| `2` | 参数无效 |
| `130` | 被中断；报告仍显示已运行的内容 |

下面是一份完整的报告，按 100 列宽的终端显示，保留颜色等全部效果：`alphaavatar doctor avatar.json --rounds 3`，视觉关闭，于 2026-11-27 由 51e81aeb 的源码（0.6.9）在 Doctor 测试的离线测试替身上录制。替身代替的是模型、STT 和 TTS 服务，Memory 和 Persona 插件，VAD 和 turn taking 的模型，以及朗读的样本；Router、Context、Loop、Engine、输出运行时和共享推理都是生产代码。第 2 轮的 STT 只给出求和问题的第一句，因此该轮停在 `stt.final`，并保留在报告中。其中的数值属于替身，而非某个服务，不能作为真实服务性能的依据；替身的 TTS 不记录 first PCM，其 STT 插件也不为请求计时，所以这些行是 `—` 并说明原因。每个数值都止于 Host 的输出：LiveKit 的传输、客户端的播放和设备都没有测量。`$WORK` 是录制时的目录。[cli-zh.html](cli-zh.html) 收录了这份录制和其他录制；其中其余测量运行的 Doctor 面板属于历史录制，由更早的构建录制，布局早于当前布局：

```terminal doctor-rounds
AlphaAvatar / Doctor
FAIL  Diagnostics completed · 12 passed · 2 failed · 1 skipped

Checks
  PASS  Environment            3 checks passed
  PASS  Configuration          avatar.json · 2 runners
  PASS  Directories            3 checks passed
  FAIL  Session and services   3 passed · 2 failed
        FAIL  services.external   2 passed, 1 failed, 3 not verified by the samples
              model providers (scripted): configured, authorized, reached, passed
              speech recognition (openai_segment): configured, authorized, reached, failed (stopped
              at stt.final)
              speech synthesis (openai): configured, authorized, reached, passed
              custom memory 'doctor': configured, authorized, reached: not observed, passed: not
              observed (external access unknown)
              custom persona 'doctor': configured, authorized, reached: not observed, passed: not
              observed (external access unknown)
              custom provider backend 'scripted': configured, authorized, reached: not observed,
              passed: not observed (external access unknown)
              livekit RTC server: not contacted; `alphaavatar dev
              $WORK/avatar.json`
              connects to it
              → See the failed scenarios' blocked stages and causes
        FAIL  session.scenarios   voice 2/3 passed, 2 not enabled, 1 no coverage
              → See each failed round's stage, cause and evidence

Not verified
  SKIP  Media devices
        Not verified: the diagnostic session uses its own samples and opens no microphone, camera or
        player
        LiveKit transport: not measured; the samples end at the Host's output
        client playback: not measured; no client takes part
        physical devices: not opened; the samples stand in for them
        camera input: not sent; the picture is a shared screen, so what reads a camera, such as face
        recognition, is not covered
        → Join a dev session from a client to try its devices

  PASS checked · WARN needs attention · FAIL fails as configured · SKIP not run here: why

Scenarios · 3 rounds, a session each
  FAIL  voice                  2/3 passed · stopped: 1 at stt.final
        Round 2: The transcript does not hold every sentence of the sample
        Round 2: Sentence 2: the final the Turn took (23 characters) holds another sentence too, and
        leaves this one out
        → See the transcript and each sentence in --json; another STT model or plugin compares
  SKIP  voice_vision           Vision is off or text only: voice runs instead
  SKIP  image_input            No input transport delivers images to a session yet
  SKIP  visual_output          No Character is configured
  With model m · stt openai_segment m · tts openai m · vision off
  Sample sum_question sha256:0f72883c4ad4

Failed rounds · voice
  Round 2 · stopped at stt.final · measured: Runtime first text 466 ms; First audio frame 487 ms;
  Response complete 716 ms; Text complete 466 ms; Last audio frame 716 ms; Input 412 ms; Context 3.2
  ms; Output 72 ms

Latency · voice · 2 of 3 rounds passed
  Metric                                               Round 1   n   Median    Range
  End to end
    Runtime first text                                  465 ms   1   463 ms   463 ms
    First audio frame                                   486 ms   1   485 ms   485 ms
    Response complete                                   715 ms   1   715 ms   715 ms
    Text complete                                       465 ms   1   464 ms   464 ms
    Last audio frame                                    714 ms   1   715 ms   715 ms
  Input                                                 410 ms   1   410 ms   410 ms
    Final speech → VAD close                            360 ms   1   359 ms   359 ms
    VAD close → Final transcript                         50 ms   1    51 ms    51 ms
  Context                                               3.5 ms   1   2.7 ms   2.7 ms
    Final transcript → Turn commit                      0.8 ms   1   0.7 ms   0.7 ms
    Turn commit → Context readiness check complete      0.9 ms   1   0.6 ms   0.6 ms
    Context readiness check complete → Context built    1.2 ms   1   0.9 ms   0.9 ms
    Context built → Model request sent                  0.6 ms   1   0.5 ms   0.5 ms
  Output                                                 72 ms   1    73 ms    73 ms
    Model request sent → First text delta                51 ms   1    51 ms    51 ms
    First text delta → TTS request                      0.9 ms   1   0.6 ms   0.6 ms
    TTS request → First PCM                                  —   0        —        —
    First PCM → First audio frame                            —   0        —        —
  n: later rounds that passed and observed it; the stages add up to First audio frame
  From the final speech, the frame with the sample's last voiced sample going in, to the Host's
  output boundary; RTC transport and client playback are not in it
  — First PCM → First audio frame: from an earlier node in 3 rounds, so no sample of it
  — TTS request → First PCM: merged into the next row: First PCM not observed: this TTS plugin logs
  no first PCM

Latency · voice · every round, the 1 not passed included
  Metric                                               Round 1   n   Median        Range
  End to end
    Runtime first text                                  465 ms   2   465 ms   463–466 ms
    First audio frame                                   486 ms   2   486 ms   485–487 ms
    Response complete                                   715 ms   2   716 ms   715–716 ms
    Text complete                                       465 ms   2   465 ms   464–466 ms
    Last audio frame                                    714 ms   2   715 ms   715–716 ms
  Input                                                 410 ms   2   411 ms   410–412 ms
    Final speech → VAD close                            360 ms   2   360 ms   359–360 ms
    VAD close → Final transcript                         50 ms   2    51 ms     51–52 ms
  Context                                               3.5 ms   2   2.9 ms   2.7–3.2 ms
    Final transcript → Turn commit                      0.8 ms   2   0.8 ms   0.7–0.9 ms
    Turn commit → Context readiness check complete      0.9 ms   2   0.7 ms   0.6–0.8 ms
    Context readiness check complete → Context built    1.2 ms   2   1.0 ms   0.9–1.0 ms
    Context built → Model request sent                  0.6 ms   2   0.5 ms       0.5 ms
  Output                                                 72 ms   2    72 ms     72–73 ms
    Model request sent → First text delta                51 ms   2    51 ms        51 ms
    First text delta → TTS request                      0.9 ms   2   0.6 ms   0.6–0.7 ms
    TTS request → First PCM                                  —   0        —            —
    First PCM → First audio frame                            —   0        —            —
  n: later rounds that observed it; the stages add up to First audio frame
  From the final speech, the frame with the sample's last voiced sample going in, to the Host's
  output boundary; RTC transport and client playback are not in it
  — First PCM → First audio frame: from an earlier node in 3 rounds, so no sample of it
  — TTS request → First PCM: merged into the next row: First PCM not observed: this TTS plugin logs
  no first PCM

Details · voice · every round, the 1 not passed included
  Metric                                               Round 1   n    Median        Range
  STT, the Turn's final
    Segment committed → STT final                        50 ms   2     51 ms     50–51 ms
    Queued in the plugin                                     —   0         —            —
    TCP connect                                              —   0         —            —
    TLS handshake                                            —   0         —            —
    Upload                                                   —   0         —            —
    Audio sent → answer headers, network and service         —   0         —            —
    Answer headers → first event                             —   0         —            —
    Answer headers → transcript done                         —   0         —            —
  Turn taking and Context
    Last assessment queued → started                    0.1 ms   2    0.1 ms       0.1 ms
    Assessments, final → commit                         0.0 ms   2    0.0 ms       0.0 ms
    Timed holds, final → commit                         0.0 ms   2    0.0 ms       0.0 ms
    Semantic addressing queued → started                     —   0         —            —
    Semantic addressing inference                            —   0         —            —
    Speech closed → association ready                        —   0         —            —
    Context readiness wait                              0.0 ms   2    0.0 ms       0.0 ms
  Model request, first attempt
    Client ready                                             —   0         —            —
    Request taken → sent                                     —   0         —            —
    Encoding                                            0.2 ms   2    0.2 ms       0.2 ms
    Pictures                                                 0   2         0            0
    Body sent                                          20.0 KB   2   20.0 KB      20.0 KB
    Attempts                                                 1   2         1            1
    Sent → first stream event, network and service      0.1 ms   2    0.1 ms       0.1 ms
  Audio out
    Answer audio                                        0.24 s   2    0.24 s       0.24 s
    Frame interval, median                               21 ms   2     21 ms        21 ms
    Largest gap between frames                           21 ms   2     21 ms     21–22 ms
    Underruns of a real-time queue                          11   2        11           11
    Producing time over audio duration                    0.95   2      0.95    0.95–0.96
    Output events dropped                                    0   2         0            0
  Doctor's input
    Sample frames late, at worst                        2.1 ms   2    2.0 ms   2.0–2.1 ms
  n: later rounds that observed it; each row from its own start
  — Queued in the plugin, TCP connect, TLS handshake, Upload, Audio sent → answer headers, network
  and service, Answer headers → first event, Answer headers → transcript done: not measured: its STT
  plugin times no request
  — Semantic addressing queued → started, Semantic addressing inference: not measured: no semantic
  addressing ran for the final, or none is traced
  — Speech closed → association ready: not measured: no association asked for the segment, or no
  resolver records one
  — Client ready, Request taken → sent: not measured: its provider logs no such step

Session
  Ready                  2.7 ms at the median of 3, 2.4–61 ms

Runners
  Runtime start          568 ms · the model cache did not grow (net)
  PASS  alphaavatar.voice.vad.silero
        started in 0.28 s · 1 worker · 162 calls, queue ≤ 0.0 ms, run ≤ 0.2 ms
  PASS  alphaavatar.router.turn_taking.smart_turn_v3
        started in 0.28 s · 1 worker · 3 calls, queue ≤ 0.0 ms, run ≤ 0.1 ms

Run again as JSON
  alphaavatar doctor avatar.json --rounds 3 --json
```

文本输出按组排列，采用[各命令共用的布局](README.md#output)，先给出结论。标题行给出报告的状态及其计数；会话运行过后显示 `Diagnostics completed`。`Checks` 每组一行，分为环境、配置、目录、会话与服务：全部通过的组只占它自己这一行，任何未通过的检查都在该组下另占一行，附其详情和下一步。什么都没运行的组列在 `Not verified` 下，说明原因以及怎样才能运行；随后一行说明每种状态的含义。接下来是各轮停在哪里：`Scenarios` 给出场景、已运行轮次中通过的轮数以及其余各轮停在哪里，其下是失败轮次的原因（每条原因只列一次，并附上共有该原因的轮次）和下一步，然后是这些轮次运行所用的配置和它们听到的样本；`Failed rounds` 给出每个失败的轮次、它停在的阶段以及它确实测到的内容，包括端到端和每个阶段。然后是端到端和分阶段的数据：基于通过各轮的 `Latency` 表格，先是端到端（Runtime first text、First audio frame、Response complete、Text complete、Last audio frame），然后是 `Input`、`Context` 和 `Output`，每个阶段的总计单独占一行，其各行列在下面，每行从前一个节点起算（见[指标](#指标)），再用一行说明所有指标的起止：从最终语音到 Host 的输出边界，不含 RTC 传输和客户端播放。有某轮未通过时，随后还有第二张表，覆盖观测到各指标的每一轮，包括失败的轮次，并在表头中注明。然后是用于诊断这些数据的内容：`Details` 覆盖每一轮（包括失败的轮次），按各指标所诊断的对象分组（STT，即 Turn 的终稿；轮次判断与 Context；模型请求的首次尝试；音频输出；视觉，仅限 `voice_vision`；Doctor 的输入），每行从自己的起点起算，如其标签所示。最后是 `Session`，给出所有会话就绪时间的中位数，以及 `Runners`，给出运行时的那一次启动及其间模型缓存的变化，然后是每个 runner 的启动、worker（按配置的数量，就绪数较少时还给出就绪了几个）、处理的调用，以及排队等待和执行的峰值；runner 处理过一次调用后才会汇总其调用，因此没有调用的 runner 显示 `no call summary observed`（`calls` 为 `null`）。`Latency` 和 `Details` 的每一行先给出第 1 轮，再给出后续轮数（`n`，在表下注明）、中位数和范围；只有通过各轮的 `Latency` 表格会在有 20 个样本后加上 P95。终端太窄时，每个指标单独占多行。没有任何一轮观测到的指标显示为 `—`，绝不显示为 `0 ms`，表下有一行说明原因；只有第 1 轮未观测到的指标也会说明原因，写法与该轮的指标相同（`…, round 1: …`）；第 1 轮未通过时，通过各轮的表格也会注明这一点。在部分轮次中被合并的行会注明合并的轮数。小于 10 ms 的时间保留一位小数。诊断未运行时，`Latency` 会注明 `Not measured` 及原因。`Run again as JSON` 给出以 JSON 输出同一诊断的命令，使用相同的 `--rounds`：包括每一轮、事件边界、样本数、服务和每条证据。带 `KEY=VALUE` 覆盖项运行时，它会提示给出相同的覆盖项，但不重复列出。`--list` 按相同的分组列出检查项。

JSON 保存状态、计数（`counts`）、所诊断的 `configuration`（按 [`config check --json`](config.md#config-check) 的方式汇总，未加载任何配置时为 `null`），以及检查项的扁平列表，每项含 `id`、`status`、`summary`、`details`、`action`、`runners`、`scenarios`、`metrics`、`services` 和 `summaries`；场景每轮一个，含 `name`、`outcome`、`summary`、`configuration`、`round`、`blocked_stage`、`cause`、`details`、`task`、`transcript`、`answer`（两者都有长度上限）、`reached`、`request`、`outputs`、`metrics`、`segments`、`frames`、`sentences`、`evidence` 和 `sample`；指标除其值和边界外还有 `merged`；runner 含 `method`、`status`、`summary`、`details`、`startup_seconds`、`workers`、`ready_workers`、`calls`、`queue_wait_max_ms` 和 `execution_max_ms`；汇总含 `name`、`configuration`、`rounds`、`passed`、`stopped_at`、`figures` 和 `sample`；服务含 `name`、`authorized`、`reached`、`passed` 和 `note`。文本、JSON 和详情经过与 `config check` 相同的输出边界：来自配置和环境的凭据被替换，控制字符被移除。`--list --json` 打印每项检查的 `id`、`title`、`needs_configuration`、`in_session` 和 `reaches`（`model downloads`、`external services`）。

模型供应商后端来自 start 会创建的供应商任务：内置插件的设置按 `config check` 的方式校验（`validate_plugin_settings`），因此省略的字段取默认值；已关闭的处理器（`enabled: false`）和已禁用的插件不创建任何东西，直接跳过。默认 memory、persona 和 MCP 的向量库 embedding 始终使用默认后端。对于其他 loop、memory、persona 或 MCP 插件，`packages.capabilities` 会警告其后端未经验证。内置插件的 schema 拒绝的设置（例如没有 `model` 的 realtime loop）会使 `config.load` 失败，与 `config check` 失败的方式相同；只在插件构造时才检查的设置（例如没有 `model` 的 STT）会使 `session.start` 失败。

无法读取的设置不会阻止指定的 bundle 或文件：`paths.home` 给出警告并指明需要修复的文件，因为 `config init` 和不带配置参数的运行都会读取它。没有参数时，默认 bundle 与已存储的凭据来自对设置的同一次读取，无法读取的设置或已存储凭据会使 `config.load` 失败。

App 或 TUI 可以调用 `alphaavatar.host.tools.doctor.diagnose(target, overrides)`（异步），或者用 `prepare(...)` 做静态检查、用 `Diagnosis.run()` 运行会话；CLI 负责读取 `.env`、解析参数、处理 Ctrl+C 并打印输出。会话的进程与推理 runner 一样用 `spawn` 启动，因此调用这些函数的脚本需要常规的 `if __name__ == "__main__":` 保护。

## 未覆盖的范围

- 客户端设备、LiveKit 的传输以及客户端显示或播放的内容：Doctor 不使用任何 RTC 服务器或客户端，每个指标都止于 Host 的输出；`devices.media` 将它们列为未测量，它们另行测量。
- 图像输入和视觉输出：没有传输能把图像送入会话，Character 的帧也不携带 Turn。
- 摄像头寻址：图片以共享屏幕的方式提供，因此不会用到视觉寻址。
- 保存真实数据的远程向量库：Doctor 从不写入它，因此诊断不运行；配置把其远程存储声明为测试存储时，诊断才会运行，报告也会注明。
- 自定义插件写入的内容：它拿到的是临时工作区，写到其他位置的任何内容都超出了 Doctor 能隔离的范围。
- 并行的 runner worker 以及长时间或高负载运行：见它们各自的测试，以及 `alphaavatar test`。
